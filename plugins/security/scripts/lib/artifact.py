#!/usr/bin/env python3
"""앱 산출물(APK·AAB·IPA) 사전 검사와 스택 판정 — scan-app.sh 가 호스트에서 실행한다. 표준 라이브러리만 사용.

  artifact.py inspect <파일> <확장자>   → stdout TSV 한 줄씩:
      type\t<apk|aab|ipa>
      profile\t<android|ios|flutter|react-native>     (여러 줄)
      warning\t<문구>                                  (여러 줄)
  종료코드: 0 정상 · 1 거부(사유는 stderr)

산출물은 신뢰하지 않는 입력이다. 압축을 풀지 않고 ZIP 중앙 디렉터리의 **항목 이름만** 읽는다
(내용 해석·추출은 컨테이너 안의 MobSF·Gitleaks 가 한다). 항목 수와 파일 크기에 상한을 둔다.
"""

from __future__ import annotations

import os
import re
import stat
import sys
import zipfile

MAX_BYTES = 500 * 1024 * 1024     # 산출물 크기 상한 (docs/security/03 워크플로/scan-app.md)
MAX_ENTRIES = 200_000             # ZIP 항목 수 상한
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
        f.seek(0)
        try:
            with zipfile.ZipFile(f) as z:
                infos = z.infolist()
        except (zipfile.BadZipFile, ValueError, OverflowError) as e:
            return _fail(f"ZIP 구조를 읽을 수 없습니다: {type(e).__name__}")
        if len(infos) > MAX_ENTRIES:
            return _fail(f"ZIP 항목이 너무 많습니다 ({len(infos)} > {MAX_ENTRIES})")
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
    # 같은 이름이 두 번 들어 있는 ZIP 은 도구마다 다른 항목을 읽을 수 있다 (해석 차이로 결과 은폐)
    seen, dup = set(), None
    for n in names:
        if n in seen:
            dup = n
            break
        seen.add(n)
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
