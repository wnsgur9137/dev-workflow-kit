#!/usr/bin/env python3
"""스택별 커스텀 검사 — Semgrep 규칙으로 표현하기 어려운 파일 단위 점검 (설정 파일·lockfile 메타데이터 등).

docs/security/07 스택별 설계/스택 프로파일 개요.md 의 `checks`. 표준 라이브러리만 사용한다.

사용:
  checks.py --target DIR --profiles-tsv FILE [--profile-dir DIR] --out FILE

- 호스트에서 대상 저장소 파일을 **읽기만** 한다. 네트워크·외부 명령·대상 코드 실행 없음.
- 대상은 신뢰하지 않는 입력이다: 심볼릭 링크는 따라가지 않고(O_NOFOLLOW), 대상 폴더 밖 경로는 읽지 않으며,
  파일 크기·순회 항목 수·전체 실행 시간을 제한한다. 정규식은 한 줄·잘라 낸 구간에만 적용해 선형 시간으로 둔다.
- 시크릿 값은 결과에 넣지 않는다 (키 이름·위치만). 결과 문자열은 normalize.py 가 다시 정제한다.
- 출력: {"results": [<finding>...], "errors": ["..."], "warnings": ["..."]}
  finding: check · rule_id · severity · category · profile · file · line · title · evidence · fix_hint · references · package
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import stat
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import profiles as _profiles  # noqa: E402

MAX_FILE = 1_000_000
MAX_LINE = 4_000            # 이보다 긴 줄은 정규식에 넘기지 않는다 (축소·생성 파일)
MAX_RESULTS_PER_CHECK = 200
MAX_WALK_ENTRIES = _profiles.MAX_WALK_ENTRIES
TIMEOUT_SEC = int(os.environ.get("DWK_CHECKS_TIMEOUT", "120"))


class Ctx:
    """검사 하나가 보는 범위: 대상 루트, 프로파일 하위 경로, 제외 하위 경로, 프로파일 제외 패턴.
    파일 목록은 한 번만 순회해 같은 범위의 검사들이 함께 쓴다."""

    def __init__(self, target, profile, root, excluded, exclude_paths, warn):
        self.target = os.path.realpath(target)
        self.profile = profile
        self.root = root
        self.excluded = excluded
        self.exclude_paths = exclude_paths
        self._warn = warn
        self._files = None

    def _walk(self):
        out = []
        base = self.target if self.root == "." else os.path.join(self.target, self.root)
        if not os.path.isdir(base) or os.path.islink(base):
            return out
        seen = 0
        for dirpath, dirs, files in os.walk(base):
            seen += len(dirs) + len(files)
            if seen > MAX_WALK_ENTRIES:
                self._warn(f"{self.profile}: 파일이 너무 많아({MAX_WALK_ENTRIES}개 초과) 스택 검사가 일부 경로를 보지 못했습니다")
                break
            rel_dir = os.path.relpath(dirpath, self.target)
            keep = []
            for d in dirs:
                rel = d if rel_dir == "." else f"{rel_dir}/{d}"
                if d in _profiles.WALK_SKIP_DIRS or os.path.islink(os.path.join(dirpath, d)):
                    continue
                if any(_profiles._is_under(rel, x) for x in self.excluded):
                    continue
                keep.append(d)
            dirs[:] = sorted(keep)
            for fn in sorted(files):
                rel = fn if rel_dir == "." else f"{rel_dir}/{fn}"
                full = os.path.join(dirpath, fn)
                if os.path.islink(full):
                    continue
                if any(_profiles.glob_match(x, rel) or _profiles.glob_match(x, rel + "/") for x in self.exclude_paths):
                    continue
                out.append((rel, full, fn))
        return out

    def files(self, pred):
        """프로파일 하위 경로 안의 파일 중 pred(rel, name) 가 참인 것 — (rel, 절대 경로)."""
        if self._files is None:
            self._files = self._walk()
        for rel, full, fn in self._files:
            if pred(rel, fn):
                yield rel, full

    def read(self, full):
        """대상 폴더 안의 일반 파일만, 크기 제한 안에서 읽는다 (넘거나 문제가 있으면 None).
        마지막 경로 구성 요소는 O_NOFOLLOW 로 열고, 연 뒤의 fstat 으로 일반 파일·크기를 다시 확인한다."""
        real = os.path.realpath(full)
        if not real.startswith(self.target + os.sep):
            return None
        try:
            fd = os.open(real, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        except OSError:
            return None
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_FILE:
                return None
            with os.fdopen(fd, "rb", closefd=False) as f:
                data = f.read(MAX_FILE + 1)
            if len(data) > MAX_FILE:
                return None
            return data.decode("utf-8", "replace")
        except OSError:
            return None
        finally:
            os.close(fd)

    def warn(self, msg):
        self._warn(msg)

    def finding(self, check, rule_id, severity, category, rel, line, title, evidence="", fix_hint="",
                references=None, package=None):
        return {"check": check, "rule_id": rule_id, "severity": severity, "category": category,
                "profile": self.profile, "file": rel, "line": line, "title": title, "evidence": evidence,
                "fix_hint": fix_hint, "references": references or [], "package": package}


def _lines(text):
    """(줄 번호, 줄) — 너무 긴 줄은 건너뛴다."""
    for n, line in enumerate(text.splitlines(), 1):
        if len(line) <= MAX_LINE:
            yield n, line


def strip_js_comments(text):
    """JS/TS 의 // · /* */ 주석을 지운다 (문자열·템플릿 리터럴 안은 유지, 줄 수 유지). 선형 시간 상태 기계."""
    out, i, n, quote = [], 0, len(text), None
    while i < n:
        c = text[i]
        if quote:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in "'\"`":
            quote = c
            out.append(c)
            i += 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            seg = text[i:n if j < 0 else j + 2]
            out.append("\n" * seg.count("\n"))
            i = n if j < 0 else j + 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# web
# ---------------------------------------------------------------------------
# W2 이름 규칙 — rules/custom/web/public-env-*.yaml 의 metavariable-regex 와 같은 문자열이어야 한다 (테스트가 확인)
PUBLIC_ENV_PREFIXES = ("NEXT_PUBLIC_", "VITE_", "REACT_APP_", "NUXT_PUBLIC_", "GATSBY_", "EXPO_PUBLIC_", "PUBLIC_")
# 공개용으로 설계된 값을 뜻하는 이름 조각 (접두사를 뗀 나머지에서 단어 단위로 본다)
PUBLIC_BY_DESIGN = ("PUBLISHABLE", "ANON", "PUBLIC", "SITE", "SITEKEY", "MEASUREMENT", "FIREBASE", "MAPBOX")
SECRET_WORDS = ("SECRET", "PRIVATE", "PASSWORD", "PASSWD", "TOKEN", "SERVICE_ROLE", "CREDENTIAL", "CREDENTIALS")
KEY_WORDS = ("API_KEY", "APIKEY", "ACCESS_KEY")


def _public_env_regex(words):
    seg = r"(?:[A-Za-z0-9]+_)*"
    return (r"^(?:" + "|".join(PUBLIC_ENV_PREFIXES) + r")"
            + r"(?!" + seg + r"(?:" + "|".join(PUBLIC_BY_DESIGN) + r")(?:_|$))"
            + seg + r"(?:" + "|".join(words) + r")(?:_[A-Za-z0-9_]*)?$")


PUBLIC_ENV_SECRET_RE = _public_env_regex(SECRET_WORDS)   # high
PUBLIC_ENV_KEY_RE = _public_env_regex(KEY_WORDS)         # medium (공개 API 키도 흔해 한 단계 낮춘다)
_SECRET_NAME = re.compile(PUBLIC_ENV_SECRET_RE)
_KEY_NAME = re.compile(PUBLIC_ENV_KEY_RE)
ENV_ASSIGN = re.compile(r"[ \t]*(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)[ \t]*=")


def public_env_severity(name):
    """공개 접두사 변수 이름이 비밀(high)·API 키(medium)를 가리키면 심각도, 아니면 None."""
    if _SECRET_NAME.match(name):
        return "high"
    if _KEY_NAME.match(name):
        return "medium"
    return None


def _is_env_file(rel, name):
    return name == ".env" or name.startswith(".env.")


def check_env_public_secret(ctx):
    """W2 — .env* 의 공개 접두사 변수 이름이 비밀 값을 가리킨다 (값은 읽어도 결과에 넣지 않는다)."""
    out = []
    for rel, full in ctx.files(_is_env_file):
        text = ctx.read(full)
        if text is None:
            continue
        for n, line in _lines(text):
            m = ENV_ASSIGN.match(line)
            if not m:
                continue
            sev = public_env_severity(m.group(1))
            if not sev:
                continue
            out.append(ctx.finding(
                "env-public-secret", "web.env-public-secret", sev, "secret" if sev == "high" else "config", rel, n,
                "공개 접두사 환경 변수에 비밀 값 이름 — 클라이언트 번들에 그대로 포함됩니다",
                evidence=f"변수 이름: {m.group(1)} (값은 리포트에 남기지 않습니다)",
                fix_hint="공개 접두사를 빼고 서버에서만 읽도록 옮기세요. 이미 배포됐다면 키를 폐기(rotate)하세요.",
                references=["CWE-200"]))
    return out


ROUTE_FILE = re.compile(r"(^|/)(app/api/(?:[^/]+/)*route|pages/api/(?:[^/]+/)*[^/]+)\.(js|jsx|ts|tsx|mjs|cjs)$")
ROUTE_EXPORT = re.compile(
    r"export[ \t]+(?:async[ \t]+)?function[ \t]+(GET|POST|PUT|PATCH|DELETE)\b"
    r"|export[ \t]+const[ \t]+(GET|POST|PUT|PATCH|DELETE)[ \t]*="
    r"|export[ \t]+default\b"
    r"|export[ \t]*\{[^}\n]{0,300}\b(GET|POST|PUT|PATCH|DELETE)\b")
# 인증 확인 호출 — getUser·getSession 같은 일반 이름은 수식된 형태(auth.getUser 등)만 인정한다
AUTH_CALL = re.compile(
    r"(?<![\w.])(auth|getServerSession|unstable_getServerSession|getToken|currentUser|getAuth|requireAuth|withAuth|"
    r"verifyToken|verifySession|validateRequest|getKindeServerSession|withApiAuthRequired|getIronSession)[ \t]*\("
    r"|\.auth\.(getUser|getSession|protect)[ \t]*\(|\bauth\(\)\.protect[ \t]*\(|\bclerkClient\b")
MIDDLEWARE_NAMES = ("middleware", "proxy")   # Next.js 16 은 middleware.ts 를 proxy.ts 로 바꿨다
MIDDLEWARE_EXTS = ("js", "ts", "mjs")
UNIVERSAL_MATCHERS = ("/", "/(.*)", "/:path*", "/((.*))", "/(.*)?")


def _middleware_covers_api(text):
    """middleware(proxy) 가 /api 경로를 덮는지 — matcher 가 없으면 전체를 덮는다.
    matcher 문자열마다: /api 로 시작하거나 전체 매처면 덮음, 부정 lookahead 안에 api 가 있으면 덮지 않음."""
    code = strip_js_comments(text)
    m = re.search(r"\bmatcher\b", code)
    if not m:
        return True
    region = code[m.end():m.end() + 2000]
    for p in re.findall(r"['\"`]([^'\"`\n]{0,300})['\"`]", region):
        if "(?!" in p:
            neg = p[p.index("(?!"):]
            if not re.search(r"\bapi\b", neg.split(")")[0]):
                return True
            continue
        if p.startswith("/api") or p in UNIVERSAL_MATCHERS:
            return True
    return False


def check_next_unauth_route(ctx):
    """W4 — Next.js API 라우트 핸들러 파일에 인증 확인 호출이 보이지 않는다 (휴리스틱, medium).

    Semgrep 은 "이 호출이 없다"를 함수 이름 목록으로 표현하기 어려워 파일 단위로 검사한다 (주석은 지우고 본다).
    프로파일 루트의 middleware(proxy) 가 matcher 상 /api 를 덮으면 인증을 그쪽에서 할 수 있으므로 low 로 낮춘다.
    """
    root = "" if ctx.root == "." else ctx.root.rstrip("/") + "/"
    mw_paths = {f"{root}{d}{n}.{e}" for d in ("", "src/") for n in MIDDLEWARE_NAMES for e in MIDDLEWARE_EXTS}
    covers = False
    for _rel, full in ctx.files(lambda rel, name: rel in mw_paths):
        if _middleware_covers_api(ctx.read(full) or ""):
            covers = True
    out = []
    for rel, full in ctx.files(lambda rel, name: bool(ROUTE_FILE.search(rel))):
        text = ctx.read(full)
        if text is None:
            continue
        code = strip_js_comments(text)
        m = ROUTE_EXPORT.search(code)
        if not m or AUTH_CALL.search(code):
            continue
        out.append(ctx.finding(
            "next-unauth-route", "web.next-unauth-route", "low" if covers else "medium", "sast", rel,
            code.count("\n", 0, m.start()) + 1,
            "API 라우트에서 인증 확인 호출이 보이지 않습니다 (휴리스틱)",
            evidence=("middleware(proxy) matcher 가 /api 를 덮어 낮춤 — middleware 의 인증 여부를 확인하세요"
                      if covers else "핸들러 파일에 auth()·getServerSession() 등의 호출이 없습니다"),
            fix_hint="공개 엔드포인트가 아니라면 핸들러 첫 부분에서 세션을 확인하고 없으면 401 을 돌려주세요.",
            references=["CWE-306"]))
    return out


NEXT_CONFIG = re.compile(r"(^|/)next\.config\.(js|mjs|cjs|ts|mts)$")
WILDCARD_HOST = re.compile(r"hostname[ \t]*:[ \t]*['\"`](\*\*?|\*\.\*\*?)['\"`]")
WILDCARD_URL = re.compile(r"new[ \t]+URL\([ \t]*['\"`][a-z]+://\*")
BROWSER_MAPS = re.compile(r"productionBrowserSourceMaps[ \t]*:[ \t]*true")
HEADERS_FN = re.compile(r"\bheaders[ \t]*(\(|:)")
SECURITY_HEADERS = ("Content-Security-Policy", "Strict-Transport-Security", "X-Frame-Options", "X-Content-Type-Options")


def _domains_wildcard(code):
    """images.domains 배열에 와일드카드가 있는지 — 배열 구간을 잘라 따로 본다 (백트래킹 없음)."""
    for m in re.finditer(r"\bdomains[ \t]*:[ \t]*\[", code):
        end = code.find("]", m.end(), m.end() + 2000)
        region = code[m.end():end if end >= 0 else m.end() + 2000]
        if re.search(r"['\"`]\*{1,2}['\"`]", region):
            return code.count("\n", 0, m.start()) + 1
    return None


def check_next_config(ctx):
    """W6 — next.config.* 의 보안 헤더 미설정, 원격 이미지 호스트 와일드카드, 프로덕션 브라우저 소스맵 (주석은 지우고 본다)."""
    out = []
    for rel, full in ctx.files(lambda rel, name: bool(NEXT_CONFIG.search(rel))):
        text = ctx.read(full)
        if text is None:
            continue
        code = strip_js_comments(text)
        lower = code.lower()
        missing = [h for h in SECURITY_HEADERS if h.lower() not in lower]
        if not HEADERS_FN.search(code):
            out.append(ctx.finding(
                "next-config", "web.next-config-no-security-headers", "medium", "config", rel, 1,
                "next.config 에 보안 헤더 설정(headers())이 없습니다",
                evidence="headers() 없음 — CSP·HSTS·X-Frame-Options·X-Content-Type-Options 가 응답에 붙지 않습니다",
                fix_hint="async headers() 로 모든 경로에 CSP·HSTS·X-Frame-Options·X-Content-Type-Options 를 추가하세요 "
                         "(배포 플랫폼이나 리버스 프록시에서 붙인다면 무시해도 됩니다).",
                references=["CWE-693"]))
        elif missing:
            out.append(ctx.finding(
                "next-config", "web.next-config-missing-security-headers", "low", "config", rel, 1,
                "next.config 의 headers() 에 일부 보안 헤더가 없습니다",
                evidence="없는 헤더: " + ", ".join(missing),
                fix_hint="빠진 헤더를 headers() 에 추가하세요.", references=["CWE-693"]))
        line = None
        for rx in (WILDCARD_HOST, WILDCARD_URL):
            m = rx.search(code)
            if m:
                line = code.count("\n", 0, m.start()) + 1
                break
        line = line or _domains_wildcard(code)
        if line:
            out.append(ctx.finding(
                "next-config", "web.next-config-wildcard-remote-image", "medium", "config", rel, line,
                "원격 이미지 호스트(images.remotePatterns·domains)가 와일드카드입니다", evidence="와일드카드 호스트",
                fix_hint="이미지 최적화 엔드포인트가 임의 호스트 이미지를 받아 와 SSRF·비용 남용에 쓰일 수 있습니다. 허용 호스트를 명시하세요.",
                references=["CWE-918"]))
        m = BROWSER_MAPS.search(code)
        if m:
            out.append(ctx.finding(
                "next-config", "web.next-config-browser-sourcemaps", "medium", "config", rel,
                code.count("\n", 0, m.start()) + 1,
                "프로덕션 브라우저 소스맵이 켜져 있습니다 (productionBrowserSourceMaps: true)",
                evidence="원본 소스가 /_next/static/**/*.map 으로 공개됩니다",
                fix_hint="productionBrowserSourceMaps 를 끄거나, 소스맵을 오류 수집 서비스에만 올리세요.",
                references=["CWE-540"]))
    return out


def _pnpm_package_key(line):
    """pnpm-lock.yaml 의 packages 항목 줄(들여쓰기 2칸, ':' 로 끝남) → (이름, 버전) 또는 None.
    v5: `  /esbuild/0.18.20:`  v6: `  /esbuild@0.18.20:` · `  /@scope/pkg@1.0.0(peer@1):`. 정규식 없이 문자열로 자른다."""
    if not line.startswith("  ") or line.startswith("   ") or not line.rstrip().endswith(":"):
        return None
    key = line.strip()[:-1].strip().strip("'\"")
    key = key.split("(", 1)[0].lstrip("/")
    if not key:
        return None
    scoped = key.startswith("@")
    body = key[1:] if scoped else key
    if "@" in body:                                   # v6 이상: name@version
        name, _, ver = body.rpartition("@")
    elif "/" in body:                                 # v5: name/version
        name, _, ver = body.rpartition("/")
    else:
        return None
    if not name or not ver or not ver[:1].isdigit():
        return None
    return ("@" + name if scoped else name), ver


def check_npm_install_scripts(ctx):
    """W8 — 설치 스크립트(postinstall 등)가 있는 의존성 목록 (package-lock v2+ hasInstallScript, pnpm v5~v8 requiresBuild).

    취약점이 아니라 공급망 검토 대상 목록이다 (info). 패키지 이름은 lockfile 에서 온 신뢰하지 않는 문자열이라
    제목은 고정 문장으로 두고 이름은 location.package 에만 넣는다. pnpm v9 lockfile 은 이 정보를 담지 않아 경고만 남긴다.
    """
    out = []

    def add(rel, name, version, line):
        out.append(ctx.finding(
            "npm-install-scripts", "web.npm-install-script", "info", "dependency", rel, line,
            "설치 스크립트가 있는 의존성 (공급망 검토 대상)",
            evidence="lockfile 에 설치 스크립트 표시(hasInstallScript·requiresBuild)가 있습니다",
            fix_hint="꼭 필요한 패키지인지 확인하고, CI 에서는 npm ci --ignore-scripts 후 필요한 것만 rebuild 하는 방식을 검토하세요.",
            package=f"{name}@{version}"))

    for rel, full in ctx.files(lambda rel, name: name == "package-lock.json"):
        text = ctx.read(full)
        if text is None:
            continue
        try:
            data = json.loads(text)
        except (ValueError, RecursionError):
            continue
        pkgs = data.get("packages") if isinstance(data, dict) else None
        if not isinstance(pkgs, dict):
            continue
        for key, meta in sorted(pkgs.items()):
            # 워크스페이스 자체 패키지(packages/app 등)는 의존성이 아니다
            if "node_modules/" not in key or not isinstance(meta, dict) or meta.get("hasInstallScript") is not True:
                continue
            name = key.rsplit("node_modules/", 1)[-1]
            pos = text.find(json.dumps(key, ensure_ascii=False))
            add(rel, name, str(meta.get("version", "?")), _line_count(text, pos) if pos >= 0 else None)
    for rel, full in ctx.files(lambda rel, name: name == "pnpm-lock.yaml"):
        text = ctx.read(full)
        if text is None:
            continue
        ver = re.search(r"^lockfileVersion:[ \t]*['\"]?(\d+)", text[:500], re.M)
        if ver and int(ver.group(1)) >= 9:
            ctx.warn(f"{rel}: pnpm lockfile v9 에는 설치 스크립트 표시가 없어 W8(설치 스크립트 의존성 목록)을 판별하지 못했습니다 — "
                     "pnpm-workspace.yaml 의 onlyBuiltDependencies 를 직접 확인하세요")
            continue
        current = None
        for n, line in _lines(text):
            key = _pnpm_package_key(line)
            if key:
                current = (key[0], key[1], n)
            elif current and line.strip() == "requiresBuild: true" and line.startswith("    "):
                add(rel, current[0], current[1], current[2])
                current = None
    return out


def _line_count(text, pos):
    return text.count("\n", 0, pos) + 1


# ---------------------------------------------------------------------------
# 등록부
# ---------------------------------------------------------------------------
CHECKS = {
    "env-public-secret": check_env_public_secret,
    "next-unauth-route": check_next_unauth_route,
    "next-config": check_next_config,
    "npm-install-scripts": check_npm_install_scripts,
}
# 저장소 전체를 보는 검사 — 인프라 설정처럼 프로파일 하위 경로가 아니라 저장소 루트에 있는 경우가 많은 것.
# 감지된 프로파일 중 하나라도 이 검사를 쓰면 대상 루트 기준으로 한 번만 실행한다.
REPO_WIDE: set = set()


class _Timeout(Exception):
    pass


def run(target, detected, profile_defs, timeout=None):
    results, errors, warnings = [], [], []
    repo_wide_done, ctx_cache = set(), {}

    def ctx_for(name, root, excluded, exclude_paths):
        key = (name, root, tuple(excluded), tuple(exclude_paths))
        if key not in ctx_cache:
            ctx_cache[key] = Ctx(target, name, root, excluded, exclude_paths, warnings.append)
        return ctx_cache[key]

    def on_alarm(_sig, _frame):
        raise _Timeout()

    use_alarm = bool(timeout) and hasattr(signal, "SIGALRM")
    if use_alarm:
        old = signal.signal(signal.SIGALRM, on_alarm)
        signal.alarm(timeout)
    try:
        for name, root, excluded in detected:
            p = profile_defs.get(name) or {}
            for check in p.get("checks") or []:
                fn = CHECKS.get(check)
                if fn is None:
                    errors.append(f"{name}: 알 수 없는 검사 '{check}'")
                    continue
                if check in REPO_WIDE:
                    if check in repo_wide_done:
                        continue
                    repo_wide_done.add(check)
                    ctx = ctx_for(name, ".", [], p.get("exclude_paths") or [])
                else:
                    ctx = ctx_for(name, root, excluded, p.get("exclude_paths") or [])
                try:
                    found = fn(ctx)
                except _Timeout:
                    raise
                except Exception as ex:  # noqa: BLE001 — 대상 파일은 신뢰하지 않는 입력이다
                    errors.append(f"{name}/{check}: 검사 실패 — {type(ex).__name__}")
                    continue
                if len(found) > MAX_RESULTS_PER_CHECK:
                    warnings.append(f"{name}/{check}: 결과 {len(found)}건 중 {MAX_RESULTS_PER_CHECK}건만 리포트에 담았습니다")
                results.extend(found[:MAX_RESULTS_PER_CHECK])
    except _Timeout:
        errors.append(f"스택 검사가 시간 제한({timeout}초)을 넘어 중단됐습니다 — 그때까지의 결과만 담았습니다")
    finally:
        if use_alarm:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old)
    return {"results": results, "errors": errors, "warnings": warnings}


def _read_detected(path):
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 2 and parts[0]:
                out.append((parts[0], parts[1], [x for x in (parts[2].split(",") if len(parts) > 2 else []) if x]))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="checks.py")
    ap.add_argument("--target", required=True)
    ap.add_argument("--profiles-tsv", required=True)
    ap.add_argument("--profile-dir", default=_profiles.DEFAULT_PROFILE_DIR)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    defs = _profiles.load_profiles(args.profile_dir)
    report = run(args.target, _read_detected(args.profiles_tsv), defs, timeout=TIMEOUT_SEC)
    fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
