"""MobSF 정적 분석 리포트(JSON) 정제·해석 — normalize.py 와 scan-app.sh 가 쓴다. 표준 라이브러리만 사용한다.

- sanitize(): raw 보관용 사본. MobSF 리포트에는 앱에서 뽑은 **시크릿 원문**(secrets)과 문자열 덤프(strings)가
  그대로 들어 있으므로 그 둘은 개수만 남기고, 나머지 문자열은 normalize 의 시크릿 마스킹을 거친다.
- parse(): 리포트 → findings (docs/security/01 개요/리포트 포맷.md). 문자열은 앱(신뢰하지 않는 입력)에서 나온
  데이터이므로 호출자(normalize.py)가 넘긴 clean 함수로 정제한다.

MobSF v4.6.4 실측 구조 (Android APK·AAB, iOS IPA):
  manifest_analysis.manifest_findings[]      {rule, title, severity, description, component}
  network_security.network_findings[]        {scope[], description, severity}
  certificate_analysis.certificate_findings[] [severity, description, title]
  code_analysis.findings{key}                {files{path: "줄,줄"}, metadata{severity, description, cwe, masvs, ...}}
  binary_analysis (Android) []               {name, <보호기법>: {severity, description, ...}}
  binary_analysis (iOS) .findings{title}     {detailed_desc, severity, cwe, masvs}
  macho_analysis (iOS) {name, <보호기법>: {severity, description}}
  dylib_analysis·framework_analysis (iOS) [] macho_analysis 와 같은 모양
  ats_analysis.ats_findings[]                {issue, severity, description}
  file_analysis[]                            {finding|issue, files[]}
  permissions{name}                          {status, info, description}
  secrets[]                                  '"키" : "값"' 문자열
  severity: high · warning · info · secure · good · suppressed
"""

from __future__ import annotations

import re

SEVERITY_MAP = {"high": "high", "warning": "medium", "medium": "medium", "info": "info", "low": "low"}
SKIP_SEVERITIES = {"secure", "good", "suppressed", "hotspot", ""}
MAX_PER_SECTION = 300          # 섹션당 결과 상한 — 절단은 경고로 알린다
MAX_FILES_PER_RULE = 20        # 코드 분석 규칙 하나가 가리키는 파일 수 상한

# MobSF 결과와 소스 점검(/security:scan-code 스택 검사) 규칙의 대응 — 두 리포트를 함께 볼 때 같은 문제로 묶는다
# (키는 rule_id 의 'mobsf.' 뒤 — MobSF 규칙 이름을 _slug 로 바꾼 형태)
SOURCE_RULES = {
    "manifest.app-is-debuggable": "android.manifest-debuggable",
    "manifest.app-allowbackup": "android.manifest-allow-backup",
    "manifest.clear-text-traffic": "android.manifest-cleartext",
    "network.cleartext": "android.nsc-cleartext",
    "network.user-certs": "android.nsc-user-certs",
}
_SOURCE_RULE_PREFIXES = (
    ("ats.", "ios.ats-*"),
)

# 앱 자체를 점검하는 맥락에서 의미가 약한 항목 — 결과는 남기되 info 로 내린다
DOWNGRADE_TO_INFO = {
    "macho.encrypted",   # 직접 빌드한 IPA 는 암호화되지 않은 것이 정상 (App Store 배포 시 FairPlay 가 적용)
}

_SLUG = re.compile(r"[^a-z0-9]+")


def _slug(text, limit: int = 60) -> str:
    s = _SLUG.sub("-", str(text or "").lower()).strip("-")
    return (s[:limit].rstrip("-")) or "unknown"


def _sev(raw):
    s = str(raw or "").strip().lower()
    if s in SKIP_SEVERITIES:
        return None
    return SEVERITY_MAP.get(s, "medium")


def platform_of(report) -> str:
    """app_type 은 Android 에서 'apk', iOS 에서 'Objective C'·'Swift' 같은 언어 이름이다 (v4.6.4 실측) — 섹션으로 판정한다."""
    r = report or {}
    if "manifest_analysis" in r or "package_name" in r:
        return "android"
    if "ats_analysis" in r or "bundle_id" in r or "macho_analysis" in r:
        return "ios"
    return "unknown"


# ---------------------------------------------------------------------------
# 앱이 정하는 식별자 (PR #32 리뷰 W1)
# ---------------------------------------------------------------------------
# 디컴파일 클래스 경로·ZIP 항목 이름·NSC 도메인·권한 이름·바이너리 이름은 앱(공격자)이 마음대로 정한다.
# summary 에서는 이 값들이 코드 블록 밖(인라인 코드·표)에 놓이므로, 경로·식별자 문자 밖은 UTF-8 퍼센트 인코딩한다.
# - 공백이 %20 이 되어 마크다운 구조(줄바꿈·백틱·표)를 만들 수 없고 문장으로 읽기도 어려워진다 (단어는 남는다, 2차 리뷰 NS1)
# - 되돌릴 수 있는 표기라 서로 다른 이름이 같은 문자열로 모이지 않는다 — '?' 치환은 한글 파일 이름 두 개를 'assets/?.json'
#   하나로 만들어 id 중복 제거에서 결과가 사라졌다 (2차 리뷰 NW2). '%' 자체도 인코딩한다.
_SAFE_IDENT_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/$@+:,*-[]")


def safe_ident(text, limit: int = 200) -> str | None:
    if text is None or text == "":
        return None
    out = []
    for ch in str(text):
        out.append(ch if ch in _SAFE_IDENT_CHARS else "".join(f"%{b:02X}" for b in ch.encode("utf-8")))
    t = "".join(out)
    return t if len(t) <= limit else t[: limit - 1] + "…"


def _d(v) -> dict:
    return v if isinstance(v, dict) else {}


def _l(v) -> list:
    return v if isinstance(v, list) else []


# ---------------------------------------------------------------------------
# 정제 (raw 보관본)
# ---------------------------------------------------------------------------
_DROP_KEYS = {"strings", "secrets", "logs", "files", "base_url", "dwd_dir", "icon_path", "info_plist",
              "playstore_details", "appstore_details", "sbom"}
SANITIZE_LIST_MAX = 2000


# 경로가 확실한 자리 — 이 자리의 문자열만 식별자용 마스킹(고엔트로피 패턴 없음)을 쓴다. 값의 모양('/' 가 있고 공백이 없음)으로
# 고르면 URL 쿼리 토큰·'/' 가 든 base64 시크릿의 마스킹까지 꺼진다 (2차 리뷰 NW1)
_PATH_VALUE_KEYS = {"file_path", "path", "name"}
_PATH_KEYED_DICTS = {"files"}   # code_analysis.*.files = {경로: 줄}


def sanitize(report, mask, mask_ident=None):
    """raw/mobsf.json 으로 남길 사본. mask(str)->str 는 normalize.clean_text 계열(시크릿 재마스킹),
    mask_ident 는 경로·식별자용(긴 경로가 [MASKED-TOKEN] 이 되지 않는다, 1차 리뷰 S4) — 경로가 확실한 자리에만 쓴다.
    사전 키도 가린다."""
    mask_ident = mask_ident or mask

    def walk(v, depth=0, key=None):
        if depth > 40:
            return "(깊이 제한)"
        if isinstance(v, dict):
            kmask = mask_ident if key in _PATH_KEYED_DICTS else mask
            return {kmask(str(k))[:300]: walk(x, depth + 1, str(k)) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x, depth + 1, key) for x in v[:SANITIZE_LIST_MAX]]
        if isinstance(v, str):
            return mask_ident(v) if key in _PATH_VALUE_KEYS else mask(v)
        return v

    out = {}
    for k, v in (report or {}).items():
        k = mask(str(k))[:200]
        if k in _DROP_KEYS:
            if isinstance(v, list):
                out[k] = {"(정제됨)": "원문은 보관하지 않습니다", "count": len(v)}
            elif isinstance(v, dict):
                out[k] = {"(정제됨)": "원문은 보관하지 않습니다",
                          "count": {mask(str(a))[:60]: (len(b) if isinstance(b, (list, dict)) else 1) for a, b in v.items()}}
            else:
                out[k] = "(정제됨)"
            continue
        out[k] = walk(v, 0, k)
    return out


# ---------------------------------------------------------------------------
# 해석
# ---------------------------------------------------------------------------
def _first_line(lines) -> int | None:
    m = re.match(r"\s*(\d{1,7})", str(lines or ""))
    return int(m.group(1)) if m else None


_KEY_NAME = re.compile(r'\s*"?([A-Za-z][A-Za-z0-9_.\-]{0,59})"?\s*:')
_DIGIT_RUN = re.compile(r"\d{4}")


def _secret_key_name(s) -> str | None:
    """'"google_api_key" : "AIza…"' → google_api_key. 값은 버린다.
    키 자리에 값이 온 형식('"MyRealPassw0rdValue" : ""')이 이름으로 남지 않게, 이름처럼 보일 때만 돌려준다 (리뷰 S1):
    영문자로 시작, 숫자 비율 25% 이하·4자리 연속 숫자 없음, 구분자(_ . -) 없는 이름은 16자 이하의 소문자 시작."""
    mt = _KEY_NAME.match(str(s or ""))
    if not mt:
        return None
    k = mt.group(1)
    digits = sum(c.isdigit() for c in k)
    if digits * 4 > len(k) or _DIGIT_RUN.search(k):
        return None
    if not re.search(r"[_.\-]", k) and (len(k) > 16 or not k[0].islower()):
        return None
    return k


def is_debug_signed(report) -> bool:
    info = str(_d(_d(report).get("certificate_analysis")).get("certificate_info") or "")
    return "CN=Android Debug" in info


def _ref(v) -> str:
    """'CWE-312: Cleartext …' → 'CWE-312' (None·숫자도 받는다, 리뷰 W7)."""
    return str(v or "").split(":")[0].strip()


def parse(report, clean, ident, title_max: int, evidence_max: int, secret_evidence: str, profile: str,
          converted_aab: bool = False):
    """→ (findings 원형 목록, 경고 목록). 각 원형은 normalize 가 id·정렬을 붙인다.
    clean(text, limit, single_line) · ident(text, limit) 는 normalize 의 정제 함수.
    converted_aab: 툴킷이 AAB 를 서명 없는 universal APK 로 바꿔 올렸다 — 서명 결과는 사용자 빌드의 것이 아니므로 뺀다.
    섹션 하나의 구조가 예상과 달라도 그 섹션만 빠지고 경고로 남는다 (리뷰 W7)."""
    findings, warnings = [], []
    if not isinstance(report, dict):
        raise ValueError("MobSF 리포트 최상위가 객체가 아닙니다")
    plat = platform_of(report)
    debug_signed = is_debug_signed(report)
    # 섹션 타입이 예상과 다르면(MobSF 버전 차이·조작된 리포트) 조용히 0건이 되지 않게 알린다 (2차 리뷰 NS4)
    for sec, types in _SECTION_TYPES.items():
        v = report.get(sec)
        if v is not None and not isinstance(v, types):
            warnings.append(f"MobSF {sec} 형식이 예상과 달라(type {type(v).__name__}) 그 섹션의 결과는 빠졌습니다.")

    def add(section, key, severity, title, desc="", file=None, line=None, package=None, refs=(), fix="",
            trusted_file=False):
        sev = _sev(severity)
        if sev is None:
            return
        rule_key = f"{section}.{key}"
        if rule_key in DOWNGRADE_TO_INFO:
            sev = "info"
        references = [x for x in (safe_ident(clean(r, 60, True), 60) for r in refs if r) if x][:5]
        src = SOURCE_RULES.get(rule_key) or next((v for p, v in _SOURCE_RULE_PREFIXES if rule_key.startswith(p)), None)
        if src and src.startswith(plat + "."):
            references.append(f"scan-code: {src}")
        if rule_key == "manifest.app-is-debuggable" and debug_signed:
            fix = (fix + " " if fix else "") + "디버그 키로 서명된 빌드입니다 — 디버그 빌드의 debuggable 은 정상이므로 릴리스 빌드(assembleRelease·bundleRelease)로 다시 점검하세요."
        # 위치는 툴킷이 정한 고정 문구(trusted_file)가 아니면 앱이 정한 값이다 → 식별자 문자 밖은 퍼센트 인코딩 (W1)
        loc = ident(file, 300) if (file and trusted_file) else (safe_ident(ident(file, 300), 300) if file else None)
        findings.append({
            # id 는 인코딩·절단 전의 값으로 계산한다 — 표시값이 같아져도 결과가 합쳐지지 않게 (2차 리뷰 NW2)
            "id_parts": (str(file or ""), str(package or "")),
            "rule_id": ident(f"mobsf.{rule_key}", 120),
            "severity": sev,
            "category": "secret" if section == "secret" else "mobile",
            "profile": profile,
            "title": clean(title, title_max, True),
            "file": loc,
            "line": line if isinstance(line, int) else None,
            "package": safe_ident(ident(package, 120), 200) if package else None,
            "evidence": clean(desc, evidence_max, True) if section != "secret" else secret_evidence,
            "fix_hint": clean(fix, evidence_max, True),
            "references": references,
        })

    def capped(items, name):
        items = _l(items)
        if len(items) > MAX_PER_SECTION:
            warnings.append(f"MobSF {name} 결과 {len(items)}건 중 {MAX_PER_SECTION}건만 리포트에 넣었습니다 "
                            f"(raw/mobsf.json 에도 목록마다 {SANITIZE_LIST_MAX}건까지만 남습니다).")
        return items[:MAX_PER_SECTION]

    def manifest():
        for f in capped(_d(report.get("manifest_analysis")).get("manifest_findings"), "manifest"):
            if isinstance(f, dict):
                add("manifest", _slug(f.get("rule") or f.get("title")), f.get("severity"), f.get("title") or f.get("rule"),
                    f.get("description"), file="AndroidManifest.xml", trusted_file=True)

    def network():
        for f in capped(_d(report.get("network_security")).get("network_findings"), "network_security"):
            if isinstance(f, dict):
                scope = ", ".join(str(x) for x in _l(f.get("scope"))[:5])
                add("network", _network_key(f.get("description")), f.get("severity"), f.get("description"),
                    f"scope: {scope}", file="res/xml (networkSecurityConfig)", trusted_file=True,
                    package=scope.replace(", ", ",") or None)

    def certificate():
        if converted_aab:
            warnings.append("AAB 의 서명은 점검하지 않았습니다 — 툴킷이 만든 universal APK 는 서명되지 않으므로 MobSF 서명 결과를 뺐습니다. "
                            "업로드 키 서명은 Play Console·apksigner 로 확인하세요.")
            return
        for f in capped(_d(report.get("certificate_analysis")).get("certificate_findings"), "certificate"):
            if isinstance(f, (list, tuple)) and len(f) >= 3:
                add("cert", _slug(f[2]), f[0], f[2], f[1])

    def code():
        for key, v in list(_d(_d(report.get("code_analysis")).get("findings")).items())[:MAX_PER_SECTION]:
            if not isinstance(v, dict):
                continue
            md = _d(v.get("metadata"))
            refs = [_ref(md.get("cwe")), md.get("masvs"), _ref(md.get("owasp-mobile"))]
            files = list(_d(v.get("files")).items())
            if not files:
                add("code", _slug(key), md.get("severity"), md.get("description") or key, refs=refs)
            for path, lines in files[:MAX_FILES_PER_RULE]:
                add("code", _slug(key), md.get("severity"), md.get("description") or key,
                    file=path, line=_first_line(lines), refs=refs)
            if len(files) > MAX_FILES_PER_RULE:
                warnings.append(f"MobSF 코드 분석 {_slug(key)} 은 파일 {len(files)}개 중 {MAX_FILES_PER_RULE}개만 넣었습니다.")

    def binary():
        ba = report.get("binary_analysis")
        if isinstance(ba, dict):
            for title, v in list(_d(ba.get("findings")).items())[:MAX_PER_SECTION]:
                if isinstance(v, dict):
                    add("binary", _slug(title), v.get("severity"), title, v.get("detailed_desc"),
                        refs=[_ref(v.get("cwe")), v.get("masvs")])
        else:
            for item in capped(ba, "binary_analysis"):
                _protections(add, "so", item)

    def macho():
        if isinstance(report.get("macho_analysis"), dict):
            _protections(add, "macho", report["macho_analysis"])
        for sec in ("dylib_analysis", "framework_analysis"):
            for item in capped(report.get(sec), sec):
                _protections(add, "dylib", item)

    def ats():
        for f in capped(_d(report.get("ats_analysis")).get("ats_findings"), "ats"):
            if isinstance(f, dict):
                add("ats", _slug(f.get("issue")), f.get("severity"), f.get("issue"), f.get("description"),
                    file="Info.plist", trusted_file=True)

    def file_analysis():
        # 인증서·키 파일 포함 등. iOS 의 'Plist Files' 같은 목록성 항목은 뺀다
        for f in capped(report.get("file_analysis"), "file_analysis"):
            if not isinstance(f, dict):
                continue
            name = str(f.get("finding") or f.get("issue") or "")
            if not re.search(r"(?i)cert|key|keystore|database|sqlite|credential", name):
                continue
            for path in _l(f.get("files"))[:MAX_FILES_PER_RULE]:
                p = path.get("file_path") if isinstance(path, dict) else path
                if isinstance(p, str):
                    add("file", _slug(name), "warning", name, file=p)

    def permissions():
        # 위험 권한 (목록성 정보 — info). 이름은 앱이 정하므로 제목·위치 모두 식별자 필터를 거친다
        for name, v in list(_d(report.get("permissions")).items())[:MAX_PER_SECTION]:
            if isinstance(v, dict) and str(v.get("status")).lower() == "dangerous":
                add("permission", _slug(name), "info", f"위험 권한 사용: {safe_ident(name, 160) or '?'}", v.get("info"),
                    package=name)

    def secrets():
        # 하드코딩 시크릿 후보 — 키 이름만 남기고 값은 버린다
        for s in capped(report.get("secrets"), "secrets"):
            key = _secret_key_name(s)
            add("secret", "hardcoded", "high", "앱에 하드코딩된 시크릿 후보" + (f" ({key})" if key else ""),
                file="(앱 리소스·코드 문자열 — MobSF 는 파일 위치를 주지 않음)", trusted_file=True, package=key,
                refs=["CWE-798"],
                fix="클라이언트에 넣은 키는 공개된다고 가정하세요 — 키를 폐기(rotate)하고 서버 프록시나 키 제한(패키지명·번들 ID·API 범위)으로 옮기세요.")

    for name, section in (("manifest", manifest), ("network_security", network), ("certificate", certificate),
                          ("code_analysis", code), ("binary_analysis", binary), ("macho·dylib", macho),
                          ("ats", ats), ("file_analysis", file_analysis), ("permissions", permissions),
                          ("secrets", secrets)):
        try:
            section()
        except Exception as ex:  # noqa: BLE001 — 리포트는 신뢰하지 않는 입력이다. 나머지 섹션은 계속한다
            warnings.append(f"MobSF {name} 섹션을 해석하지 못해 그 결과는 빠졌습니다: {type(ex).__name__}")
    return findings, warnings


_SECTION_TYPES = {
    "manifest_analysis": dict, "network_security": dict, "certificate_analysis": dict, "code_analysis": dict,
    "binary_analysis": (dict, list), "macho_analysis": dict, "dylib_analysis": list, "framework_analysis": list,
    "ats_analysis": dict, "file_analysis": list, "permissions": dict, "secrets": list,
}


def _network_key(desc) -> str:
    """network_security_config 결과 설명 → 짧은 규칙 이름 (설명 문장은 MobSF 버전마다 바뀔 수 있다)."""
    d = str(desc or "").lower()
    scope = "base" if d.startswith("base config") else "domain" if "domain config" in d else ""
    if "clear text" in d or "cleartext" in d:
        key = "cleartext"
    elif "user installed" in d or "user certificates" in d:
        key = "user-certs"
    elif "bypass" in d or "pin" in d:
        key = "pinning"
    else:
        return _slug(desc, 40)
    return key if scope in ("base", "") else f"{scope}-{key}"


def _protections(add, section, item):
    """{name, nx:{severity, description}, pie:{...}} 형태의 보호 기법 점검 결과.
    MobSF 는 보호 기법이 켜진 정상 상태도 info 로 보고하므로 high·warning 만 남긴다."""
    if not isinstance(item, dict):
        return
    name = str(item.get("name") or "")
    for k, v in item.items():
        if isinstance(v, dict) and "severity" in v and _sev(v.get("severity")) in ("high", "medium"):
            add(section, _slug(k), v.get("severity"), f"{_slug(k)}: {v.get('description') or ''}"[:200],
                v.get("description"), file=name or None)
