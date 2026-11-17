#!/usr/bin/env python3
"""앱 산출물(APK·AAB·IPA) 사전 검사와 스택 판정 — scan-app.sh 가 호스트에서 실행한다. 표준 라이브러리만 사용.

  artifact.py inspect <파일> <확장자>   → stdout TSV 한 줄씩:
      type\t<apk|aab|ipa>
      profile\t<android|ios|flutter|react-native>     (여러 줄)
      text_entries\t<개수>                            Gitleaks 가 볼 텍스트로 보이는 항목 수
      warning\t<문구>                                  (여러 줄)
  종료코드: 0 정상 · 1 거부(사유는 stderr)

산출물은 신뢰하지 않는 입력이다. 압축을 풀지 않고 ZIP 중앙 디렉터리의 **항목 이름만** 읽는다
(내용 해석·추출은 컨테이너 안의 MobSF·Gitleaks 가 한다). 항목 수와 파일 크기에 상한을 둔다.
항목 수·중앙 디렉터리 크기는 ZipFile 이 중앙 디렉터리 전체를 메모리에 올리기 **전에** EOCD 로 확인한다
(빈 항목 30만 개짜리 26MB ZIP 이 171MB·4초를 쓰던 문제, PR #32 리뷰 W3). 압축 해제 총량에도 상한을 둔다(W4).
"""

from __future__ import annotations

import os
import re
import stat
import struct
import sys
import zipfile

MAX_BYTES = 500 * 1024 * 1024     # 산출물 크기 상한 (docs/security/03 워크플로/scan-app.md)
MAX_ENTRIES = 200_000             # ZIP 항목 수 상한
# 중앙 디렉터리 크기 상한 — 20만 항목 × 평균 이름 60자 ≈ 21MB. EOCD 의 항목 수를 속여도 ZipFile 은 이 크기만큼 파싱하므로
# (64MB 에서 RSS 708MB 실측, 2차 리뷰 NS2) 정상 상한에 가깝게 둔다
MAX_CD_BYTES = 32 * 1024 * 1024
MAX_UNCOMPRESSED = 4 * 1024 ** 3  # 항목 크기(압축 해제) 합계 상한 — MobSF 가 볼륨에 풀어 쓰는 양
TEXT_EXTS = (".js", ".bundle", ".jsbundle", ".json", ".xml", ".plist", ".txt", ".properties", ".yaml", ".yml",
             ".env", ".html", ".htm", ".css", ".cfg", ".conf", ".ini", ".pem", ".strings", ".config", ".mf", ".sf")
ZIP_MAGIC = (b"PK\x03\x04",)      # 빈 ZIP(PK\x05\x06)·분할 ZIP 은 앱 산출물이 아니다

# 크로스플랫폼 프레임워크 표식 (ZIP 항목 이름)
_FLUTTER = {
    "android": re.compile(r"^(?:base/)?lib/[^/]+/libflutter\.so$"),
    "ios": re.compile(r"^Payload/[^/]+\.app/Frameworks/Flutter\.framework/"),
}
_RN = {
    "android": re.compile(r"^(?:base/)?(?:assets/index\.android\.bundle|lib/[^/]+/libreactnativejni\.so|lib/[^/]+/libreactnative\.so)$"),
    "ios": re.compile(r"^Payload/[^/]+\.app/(?:main\.jsbundle|Frameworks/React(?:-Core)?\.framework/|Frameworks/hermes\.framework/)"),
}
_CASE_SENSITIVE_IMPORTANT = re.compile(
    r"(?i)^(?:base/(?:manifest/)?|base/dex/|base/root/)?(?:androidmanifest\.xml|classes\d*\.dex|resources\.(?:arsc|pb)"
    r"|meta-inf/|lib/[^/]+/[^/]+\.so$|assets/index\.android\.bundle)"
    r"|^payload/[^/]+\.app/(?:info\.plist|main\.jsbundle|[^/]+$)")
_ANDROID_BINARY_XML = re.compile(r"^(?:base/)?(?:manifest/)?(?:androidmanifest\.xml$|res/)")
_IOS_APP = re.compile(r"^Payload/[^/]+\.app/Info\.plist$")
_ANDROID_MANIFEST = {"apk": re.compile(r"^AndroidManifest\.xml$"), "aab": re.compile(r"^base/manifest/AndroidManifest\.xml$")}


def _fail(msg: str) -> int:
    print(msg, file=sys.stderr)
    return 1


def inspect(path: str, ext: str) -> int:
    ext = ext.lower()
    if ext not in ("apk", "aab", "ipa"):
        return _fail(f"지원하지 않는 산출물 유형: {ext}")
    # 심볼릭 링크를 따라가지 않는다 (scan-app.sh 가 realpath 로 푼 경로를 넘긴다)
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as e:
        return _fail(f"산출물을 열 수 없습니다: {e.strerror}")
    with os.fdopen(fd, "rb") as f:
        st = os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode):
            return _fail("일반 파일이 아닙니다")
        if st.st_size > MAX_BYTES:
            return _fail(f"산출물이 너무 큽니다 ({st.st_size // (1024 * 1024)}MB > {MAX_BYTES // (1024 * 1024)}MB)")
        if st.st_size < 22:
            return _fail("파일이 너무 작아 앱 산출물이 아닙니다")
        if f.read(4) not in ZIP_MAGIC:
            return _fail("ZIP 시그니처(PK\\x03\\x04)가 없습니다 — APK·AAB·IPA 는 ZIP 형식입니다")
        # EOCD(ZIP64 포함)의 항목 수·중앙 디렉터리 크기를 먼저 본다
        # 표준 라이브러리 내부 함수(3.8~3.13 동일)라 없어지면 사전 검사만 건너뛴다 (뒤의 항목 수 검사는 남는다)
        end_rec = getattr(zipfile, "_EndRecData", None)
        if end_rec is not None:
            try:
                end = end_rec(f)
            except (OSError, ValueError, OverflowError, zipfile.BadZipFile, struct.error):
                end = None   # 다중 디스크 ZIP64 locator 등 (2차 리뷰 NN3)
            if not end:
                return _fail("ZIP 끝 레코드(EOCD)를 찾을 수 없습니다")
            total = end[getattr(zipfile, "_ECD_ENTRIES_TOTAL", 4)]
            cd_size = end[getattr(zipfile, "_ECD_SIZE", 5)]
            if total > MAX_ENTRIES:
                return _fail(f"ZIP 항목이 너무 많습니다 ({total} > {MAX_ENTRIES})")
            if cd_size > MAX_CD_BYTES:
                return _fail(f"ZIP 중앙 디렉터리가 너무 큽니다 ({cd_size // (1024 * 1024)}MB)")
        f.seek(0)
        try:
            with zipfile.ZipFile(f) as z:
                infos = z.infolist()
        except (zipfile.BadZipFile, ValueError, OverflowError) as e:
            return _fail(f"ZIP 구조를 읽을 수 없습니다: {type(e).__name__}")
        if len(infos) > MAX_ENTRIES:
            return _fail(f"ZIP 항목이 너무 많습니다 ({len(infos)} > {MAX_ENTRIES})")
        unpacked = sum(i.file_size for i in infos)
        if unpacked > MAX_UNCOMPRESSED:
            return _fail(f"압축을 풀면 너무 큽니다 ({unpacked // (1024 ** 3)}GB > {MAX_UNCOMPRESSED // (1024 ** 3)}GB) — 압축 폭탄일 수 있습니다")
    names = [i.filename for i in infos]

    platform = "ios" if ext == "ipa" else "android"
    if platform == "ios":
        if not any(_IOS_APP.match(n) for n in names):
            return _fail("IPA 안에 Payload/<앱>.app/Info.plist 가 없습니다")
    elif not any(_ANDROID_MANIFEST[ext].match(n) for n in names):
        where = "AndroidManifest.xml" if ext == "apk" else "base/manifest/AndroidManifest.xml"
        return _fail(f"{ext.upper()} 안에 {where} 가 없습니다")

    print(f"type\t{ext}")
    print(f"profile\t{platform}")
    if any(_FLUTTER[platform].match(n) for n in names):
        print("profile\tflutter")
    if any(_RN[platform].match(n) for n in names):
        print("profile\treact-native")
    if ext == "ipa" and any(re.match(r"^Payload/[^/]+\.app/SC_Info/", n) for n in names):
        print("warning\tIPA 에 SC_Info(FairPlay 암호화 정보)가 있습니다 — App Store 에서 받은 암호화된 앱은 바이너리 분석 결과가 비어 있을 수 있습니다. 직접 빌드(Archive → Export)한 IPA 로 점검하세요.")
    # APK·AAB 의 매니페스트·res/ 의 .xml 은 바이너리 AXML 이라 Gitleaks 가 볼 텍스트가 아니다 (2차 NN2). assets/ 의 .xml 은
    # 평문이므로 센다 (3차 NT9). IPA 의 plist 는 XML·바이너리가 섞인다
    def is_text(n: str) -> bool:
        low = n.lower()
        if not low.endswith(TEXT_EXTS):
            return False
        return not (platform == "android" and low.endswith(".xml") and _ANDROID_BINARY_XML.match(low))
    print(f"text_entries\t{sum(1 for n in names if is_text(n))}")
    # 같은 이름이 두 번 들어 있는 ZIP 은 도구마다 다른 항목을 읽을 수 있다 (해석 차이로 결과 은폐).
    # './' 접두·역슬래시는 늘 정규화하고, 대소문자만 다른 이름은 도구 해석에 중요한 항목에서만 같은 이름으로 본다 —
    # 릴리스 빌드의 리소스 경로 단축(shrinkResources)이 대소문자만 다른 res/ 이름을 만들 수 있어서다 (2차 리뷰 NS6)
    seen, dup = set(), None
    for n in names:
        k = n.replace("\\", "/")
        while k.startswith("./"):
            k = k[2:]
        if _CASE_SENSITIVE_IMPORTANT.match(k):
            k = "\0" + k.lower()
        if k in seen:
            dup = n
            break
        seen.add(k)
    if dup is not None:
        print("warning\tZIP 안에 같은 이름의 항목이 두 번 이상 있습니다 — 도구마다 다른 항목을 읽을 수 있어 결과를 그대로 믿기 어렵습니다.")
    return 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) == 3 and argv[0] == "inspect":
        return inspect(argv[1], argv[2])
    return _fail("사용: artifact.py inspect <파일> <apk|aab|ipa>")


if __name__ == "__main__":
    sys.exit(main())
