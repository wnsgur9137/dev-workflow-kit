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
# 정제 (raw 보관본)
# ---------------------------------------------------------------------------
_DROP_KEYS = {"strings", "secrets", "logs", "files", "base_url", "dwd_dir", "icon_path", "info_plist",
              "playstore_details", "appstore_details", "sbom"}


def sanitize(report, mask):
    """raw/mobsf.json 으로 남길 사본. mask(str)->str 는 normalize.clean_text 계열(시크릿 재마스킹)."""
    def walk(v, depth=0):
        if depth > 40:
            return "(깊이 제한)"
        if isinstance(v, dict):
            return {str(k)[:200]: walk(x, depth + 1) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x, depth + 1) for x in v[:2000]]
        if isinstance(v, str):
            return mask(v)
        return v

    out = {}
    for k, v in (report or {}).items():
        if k in _DROP_KEYS:
            if isinstance(v, list):
                out[k] = {"(정제됨)": "원문은 보관하지 않습니다", "count": len(v)}
            elif isinstance(v, dict):
                out[k] = {"(정제됨)": "원문은 보관하지 않습니다",
                          "count": {str(a)[:60]: (len(b) if isinstance(b, (list, dict)) else 1) for a, b in v.items()}}
            else:
                out[k] = "(정제됨)"
            continue
        out[k] = walk(v)
    return out


# ---------------------------------------------------------------------------
# 해석
# ---------------------------------------------------------------------------
def _first_line(lines) -> int | None:
    m = re.match(r"\s*(\d{1,7})", str(lines or ""))
    return int(m.group(1)) if m else None


def _secret_key_name(s: str) -> str | None:
    """'"google_api_key" : "AIza…"' → google_api_key. 키 이름 문자만 남긴다 (값은 버린다)."""
    m = re.match(r'\s*"?([A-Za-z0-9_.\-]{1,80})"?\s*:', str(s or ""))
    return m.group(1) if m else None


def is_debug_signed(report) -> bool:
    info = str(((report or {}).get("certificate_analysis") or {}).get("certificate_info") or "")
    return "CN=Android Debug" in info


def parse(report, clean, ident, title_max: int, evidence_max: int, secret_evidence: str, profile: str,
          converted_aab: bool = False):
    """→ (findings 원형 목록, 경고 목록). 각 원형은 normalize 가 id·정렬을 붙인다.
    clean(text, limit, single_line) · ident(text, limit) 는 normalize 의 정제 함수.
    converted_aab: 툴킷이 AAB 를 서명 없는 universal APK 로 바꿔 올렸다 — 서명 결과는 사용자 빌드의 것이 아니므로 뺀다."""
    findings, warnings = [], []
    if not isinstance(report, dict):
        raise ValueError("MobSF 리포트 최상위가 객체가 아닙니다")
    plat = platform_of(report)
    debug_signed = is_debug_signed(report)

    def add(section, key, severity, title, desc="", file=None, line=None, package=None, refs=(), fix=""):
        sev = _sev(severity)
        if sev is None:
            return
        rule_key = f"{section}.{key}"
        if rule_key in DOWNGRADE_TO_INFO:
            sev = "info"
        references = [clean(r, 60, True) for r in refs if r][:5]
        src = SOURCE_RULES.get(rule_key) or next((v for p, v in _SOURCE_RULE_PREFIXES if rule_key.startswith(p)), None)
        if src and src.startswith(plat + "."):
            references.append(clean(f"scan-code: {src}", 60, True))
        if rule_key == "manifest.app-is-debuggable" and debug_signed:
            fix = (fix + " " if fix else "") + "디버그 키로 서명된 빌드입니다 — 디버그 빌드의 debuggable 은 정상이므로 릴리스 빌드(assembleRelease·bundleRelease)로 다시 점검하세요."
        findings.append({
            "rule_id": ident(f"mobsf.{rule_key}", 120),
            "severity": sev,
            "category": "secret" if section == "secret" else "mobile",
            "profile": profile,
            "title": clean(title, title_max, True),
            "file": ident(file, 300) if file else None,
            "line": line if isinstance(line, int) else None,
            "package": ident(package, 120) if package else None,
            "evidence": clean(desc, evidence_max, True) if section != "secret" else secret_evidence,
            "fix_hint": clean(fix, evidence_max, True),
            "references": references,
        })

    def capped(items, name):
        items = list(items or [])
        if len(items) > MAX_PER_SECTION:
            warnings.append(f"MobSF {name} 결과 {len(items)}건 중 {MAX_PER_SECTION}건만 리포트에 넣었습니다 (raw/mobsf.json 참고).")
        return items[:MAX_PER_SECTION]

    # Android 매니페스트
    for f in capped(((report.get("manifest_analysis") or {}).get("manifest_findings")), "manifest"):
        if isinstance(f, dict):
            add("manifest", _slug(f.get("rule") or f.get("title")), f.get("severity"), f.get("title") or f.get("rule"),
                f.get("description"), file="AndroidManifest.xml")
    # Android network_security_config
    for f in capped(((report.get("network_security") or {}).get("network_findings")), "network_security"):
        if isinstance(f, dict):
            scope = ", ".join(str(s) for s in (f.get("scope") or [])[:5])
            add("network", _network_key(f.get("description")), f.get("severity"), f.get("description"),
                f"scope: {scope}", file="res/xml (networkSecurityConfig)", package=scope or None)
    # 서명 인증서
    if converted_aab:
        warnings.append("AAB 의 서명은 점검하지 않았습니다 — 툴킷이 만든 universal APK 는 서명되지 않으므로 MobSF 서명 결과를 뺐습니다. "
                        "업로드 키 서명은 Play Console·apksigner 로 확인하세요.")
    for f in ([] if converted_aab else
              capped(((report.get("certificate_analysis") or {}).get("certificate_findings")), "certificate")):
        if isinstance(f, (list, tuple)) and len(f) >= 3:
            add("cert", _slug(f[2]), f[0], f[2], f[1])
    # 코드 분석 (디컴파일 소스 경로·줄)
    for key, v in list(((report.get("code_analysis") or {}).get("findings") or {}).items())[:MAX_PER_SECTION]:
        if not isinstance(v, dict):
            continue
        md = v.get("metadata") or {}
        refs = [md.get("cwe", "").split(":")[0], md.get("masvs"), md.get("owasp-mobile", "").split(":")[0]]
        files = list((v.get("files") or {}).items())
        if not files:
            add("code", _slug(key), md.get("severity"), md.get("description") or key, refs=refs)
        for path, lines in files[:MAX_FILES_PER_RULE]:
            add("code", _slug(key), md.get("severity"), md.get("description") or key,
                file=path, line=_first_line(lines), refs=refs)
        if len(files) > MAX_FILES_PER_RULE:
            warnings.append(f"MobSF 코드 분석 {_slug(key)} 은 파일 {len(files)}개 중 {MAX_FILES_PER_RULE}개만 넣었습니다.")
    # 바이너리 (Android .so 목록 / iOS findings 사전)
    ba = report.get("binary_analysis")
    if isinstance(ba, dict):
        for title, v in list((ba.get("findings") or {}).items())[:MAX_PER_SECTION]:
            if isinstance(v, dict):
                add("binary", _slug(title), v.get("severity"), title, v.get("detailed_desc"),
                    refs=[str(v.get("cwe", "")).split(":")[0], v.get("masvs")])
    elif isinstance(ba, list):
        for item in capped(ba, "binary_analysis"):
            _protections(add, "so", item)
    # iOS 실행 파일·동적 라이브러리·프레임워크의 보호 기법
    if isinstance(report.get("macho_analysis"), dict):
        _protections(add, "macho", report["macho_analysis"])
    for sec in ("dylib_analysis", "framework_analysis"):
        for item in capped(report.get(sec), sec):
            _protections(add, "dylib", item)
    # iOS ATS
    for f in capped(((report.get("ats_analysis") or {}).get("ats_findings")), "ats"):
        if isinstance(f, dict):
            add("ats", _slug(f.get("issue")), f.get("severity"), f.get("issue"), f.get("description"), file="Info.plist")
    # 파일 분석 (인증서·키 파일 포함 등). iOS 의 'Plist Files' 같은 목록성 항목은 뺀다
    for f in capped(report.get("file_analysis"), "file_analysis"):
        if not isinstance(f, dict):
            continue
        name = f.get("finding") or f.get("issue") or ""
        if not re.search(r"(?i)cert|key|keystore|database|sqlite|credential", name):
            continue
        for path in (f.get("files") or [])[:MAX_FILES_PER_RULE]:
            p = path.get("file_path") if isinstance(path, dict) else path
            add("file", _slug(name), "warning", name, file=p)
    # 위험 권한 (목록성 정보 — info)
    for name, v in list((report.get("permissions") or {}).items())[:MAX_PER_SECTION]:
        if isinstance(v, dict) and str(v.get("status")).lower() == "dangerous":
            add("permission", _slug(name), "info", f"위험 권한 사용: {name}", v.get("info"), package=name)
    # 하드코딩 시크릿 후보 — 키 이름만 남기고 값은 버린다
    secrets = report.get("secrets") or []
    for s in capped(secrets, "secrets"):
        key = _secret_key_name(s)
        add("secret", "hardcoded", "high", "앱에 하드코딩된 시크릿 후보" + (f" ({key})" if key else ""),
            file="(앱 리소스·코드 문자열 — MobSF 는 파일 위치를 주지 않음)", package=key, refs=["CWE-798"],
            fix="클라이언트에 넣은 키는 공개된다고 가정하세요 — 키를 폐기(rotate)하고 서버 프록시나 키 제한(패키지명·번들 ID·API 범위)으로 옮기세요.")
    return findings, warnings


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
            add(section, _slug(k), v.get("severity"), f"{k}: {v.get('description') or ''}"[:200],
                v.get("description"), file=name or None)
