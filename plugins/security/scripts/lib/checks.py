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
def _timeout_from_env(default=120):
    try:
        v = int(os.environ.get("DWK_CHECKS_TIMEOUT", default))
    except ValueError:
        return default
    return v if v >= 1 else default


TIMEOUT_SEC = _timeout_from_env()


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
            return data.decode("utf-8-sig", "replace")
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


_REGEX_PREV = set("(,=:[!&|?{};+-*%<>~^") | {""}


def strip_js_comments(text):
    """JS/TS 의 // · /* */ 주석을 지운다 (줄 수 유지). 선형 시간 상태 기계.

    - '·" 문자열은 줄바꿈에서 끝난 것으로 본다 (JS 문자열은 여러 줄에 걸치지 않는다 — JSX 텍스트의 아포스트로피가
      파일 끝까지 번지지 않게). 템플릿 리터럴(`)은 여러 줄을 허용한다.
    - 앞의 공백 아닌 문자가 연산자·여는 괄호·줄 시작이거나 return 뒤면 / 는 정규식 리터럴로 보고 건너뛴다
      (정규식 안의 `/*` 를 주석으로 오인하지 않게). 문자 클래스 [...] 안의 / 는 끝으로 보지 않는다.
    - 닫히지 않은 블록 주석은 주석으로 보지 않는다 (파일 끝까지 지워 판정을 바꾸지 않게).
    """
    out, i, n, quote = [], 0, len(text), None
    prev = ""            # 마지막으로 낸 공백 아닌 문자 (정규식 리터럴 판정용)
    prev_word = ""
    while i < n:
        c = text[i]
        if quote:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == quote or (c == "\n" and quote != "`"):
                quote = None
                prev = c if c != "\n" else prev
            i += 1
            continue
        if c in "'\"`":
            quote = c
            out.append(c)
            prev = c
            i += 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            if j < 0:            # 닫히지 않은 블록 주석 — 그대로 둔다
                out.append(text[i:])
                break
            out.append("\n" * text.count("\n", i, j))
            i = j + 2
        elif c == "/" and (prev in _REGEX_PREV or prev_word in ("return", "typeof", "case", "in", "of")):
            # 정규식 리터럴 — 줄 안에서 이스케이프되지 않은 / 까지 (문자 클래스 안 제외)
            j, in_class = i + 1, False
            while j < n and text[j] != "\n":
                ch = text[j]
                if ch == "\\":
                    j += 2
                    continue
                if ch == "[":
                    in_class = True
                elif ch == "]":
                    in_class = False
                elif ch == "/" and not in_class:
                    break
                j += 1
            if j < n and text[j] == "/":
                out.append(text[i:j + 1])
                i = j + 1
                prev, prev_word = "/", ""
            else:                # 줄 안에서 끝나지 않으면 나눗셈으로 본다
                out.append(c)
                prev = c
                i += 1
        else:
            out.append(c)
            if not c.isspace():
                if c.isalnum() or c in "_$":
                    prev_word = (prev_word + c) if (prev.isalnum() or prev in "_$") else c
                else:
                    prev_word = ""
                prev = c
            i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# web
# ---------------------------------------------------------------------------
# W2 이름 규칙 — rules/custom/web/public-env-*.yaml 의 metavariable-regex 와 같은 문자열이어야 한다 (테스트가 확인)
PUBLIC_ENV_PREFIXES = ("NEXT_PUBLIC_", "VITE_", "REACT_APP_", "NUXT_PUBLIC_", "GATSBY_", "EXPO_PUBLIC_", "PUBLIC_")
# 강한 단어 — 공개용 조각과 함께 있어도 항상 high (예: FIREBASE_PRIVATE_KEY, MAPBOX_SECRET_TOKEN)
STRONG_WORDS = ("SECRET", "PRIVATE", "PASSWORD", "PASSWD", "SERVICE_ROLE", "CREDENTIAL", "CREDENTIALS")
# 약한 단어 — 공개용으로 발급되는 경우가 흔해, 이름에 공개용 조각이 있으면 제외한다
TOKEN_WORDS = ("TOKEN",)
TOKEN_PUBLIC = ("PUBLIC", "ANON", "PUBLISHABLE", "MAPBOX")                 # high
KEY_WORDS = ("API_KEY", "APIKEY", "ACCESS_KEY")
KEY_PUBLIC = ("PUBLISHABLE", "ANON", "PUBLIC", "SITE", "SITEKEY", "FIREBASE", "MEASUREMENT")   # medium
_SEG = r"(?:[A-Za-z0-9]+_)*"


def _alt(words):
    return "(?:" + "|".join(words) + ")"


def _public_env_regexes(start, end):
    """(비밀 정규식, API 키 정규식). start·end 는 이름 앞뒤 경계 (변수 이름은 ^ $, 대괄호 문자열은 따옴표 포함)."""
    tail = r"(?:_[A-Za-z0-9_]*)?" + end

    def guarded(words, public):
        return r"(?!" + _SEG + _alt(public) + r"(?:_|" + end + r"))" + _SEG + _alt(words) + tail

    prefix = start + _alt(PUBLIC_ENV_PREFIXES)
    secret = prefix + r"(?:" + _SEG + _alt(STRONG_WORDS) + tail + "|" + guarded(TOKEN_WORDS, TOKEN_PUBLIC) + ")"
    return secret, prefix + guarded(KEY_WORDS, KEY_PUBLIC)


PUBLIC_ENV_SECRET_RE, PUBLIC_ENV_KEY_RE = _public_env_regexes("^", "$")
# Semgrep 의 process.env['X'] 형태용 — 메타변수 텍스트에 따옴표가 포함된다
PUBLIC_ENV_SECRET_BRACKET_RE, PUBLIC_ENV_KEY_BRACKET_RE = _public_env_regexes("^[\"']", "[\"']$")
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


ROUTE_EXTS = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")


def is_route_file(rel):
    """app/api/**/route.<ext> 또는 pages/api/**/<파일>.<ext> — 경로 구성 요소로 판정 (정규식 백트래킹 없음)."""
    if not rel.endswith(ROUTE_EXTS):
        return False
    parts = rel.split("/")
    stem = parts[-1].rsplit(".", 1)[0]
    for i in range(len(parts) - 2):          # api 뒤에 구성 요소가 하나 이상 있어야 한다
        if parts[i + 1] != "api":
            continue
        if parts[i] == "pages" or (parts[i] == "app" and stem == "route"):
            return True
    return False


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


def _matcher_values(code):
    """config 객체의 matcher 값(문자열 목록). config·matcher 가 없으면 None, 해석할 수 없으면 []."""
    cm = re.search(r"\bconfig\b[^=\n]{0,80}=[ \t]*\{", code)
    if not cm:
        return None
    mm = re.search(r"\bmatcher[ \t]*:[ \t]*", code[cm.end():cm.end() + 5000])
    if not mm:
        return None
    rest = code[cm.end() + mm.end():cm.end() + mm.end() + 3000]
    if rest[:1] in "'\"`":
        end = rest.find(rest[0], 1)
        return [rest[1:end]] if end > 0 else []
    if rest[:1] != "[":
        return []
    values, i, quote, buf = [], 1, None, []
    while i < len(rest):           # 짝이 맞는 ] 까지, 문자열 안의 [ ] 는 무시
        c = rest[i]
        if quote:
            if c == "\\":
                buf.append(rest[i:i + 2])
                i += 2
                continue
            if c == quote:
                values.append("".join(buf))
                quote, buf = None, []
            else:
                buf.append(c)
        elif c in "'\"`":
            quote = c
        elif c == "]":
            return values
        i += 1
    return []


def _middleware_covers_api(text):
    """middleware(proxy) 가 /api 경로를 덮는지.
    - matcher 가 파일 어디에도 없으면 전체를 덮는다.
    - config.matcher 문자열마다: /api 로 시작하거나 전체 매처면 덮음, 부정 lookahead 안에 api 가 있으면 덮지 않음.
    - matcher 가 있는데 config 에서 해석할 수 없으면(가져온 값 등) 애매하므로 덮지 않는 것으로 본다 (medium 유지)."""
    code = strip_js_comments(text)
    values = _matcher_values(code)
    if values is None:
        return not re.search(r"\bmatcher\b", code)
    for p in values:
        if "(?!" in p:
            neg = p[p.index("(?!") + 3:].split(")")[0]
            if not re.search(r"\bapi\b", neg):
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
    for rel, full in ctx.files(lambda rel, name: is_route_file(rel)):
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


def _pnpm_package_key(line, lock_major=6):
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
    if lock_major < 6:                                # v5: name/version[_peer@ver…]
        if "/" not in body:
            return None
        name, _, ver = body.rpartition("/")
        ver = ver.split("_", 1)[0]
    elif "@" in body:                                 # v6~v8: name@version
        name, _, ver = body.rpartition("@")
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
        cursor, line_at, line_no = 0, 0, 1
        for key, meta in pkgs.items():           # 파일 순서 그대로 — 줄 번호를 이어서 센다 (선형)
            # 워크스페이스 자체 패키지(packages/app 등)는 의존성이 아니다
            if "node_modules/" not in key or not isinstance(meta, dict) or meta.get("hasInstallScript") is not True:
                continue
            name = key.rsplit("node_modules/", 1)[-1]
            line = None
            if len(out) <= MAX_RESULTS_PER_CHECK:
                pos = text.find(json.dumps(key, ensure_ascii=False), cursor)
                if pos >= 0:
                    line_no += text.count("\n", line_at, pos)
                    line_at = cursor = pos
                    line = line_no
            add(rel, name, str(meta.get("version", "?")), line)
    for rel, full in ctx.files(lambda rel, name: name == "pnpm-lock.yaml"):
        text = ctx.read(full)
        if text is None:
            continue
        ver = re.search(r"^lockfileVersion:[ \t]*['\"]?(\d+)", text[:500], re.M)
        major = int(ver.group(1)) if ver else 6
        if major >= 9:
            ctx.warn(f"{rel}: pnpm lockfile v9 에는 설치 스크립트 표시가 없어 W8(설치 스크립트 의존성 목록)을 판별하지 못했습니다 — "
                     "pnpm-workspace.yaml 의 onlyBuiltDependencies 를 직접 확인하세요")
            continue
        current = None
        for n, line in _lines(text):
            key = _pnpm_package_key(line, major)
            if key:
                current = (key[0], key[1], n)
            elif current and line.strip() == "requiresBuild: true" and line.startswith("    "):
                add(rel, current[0], current[1], current[2])
                current = None
    return out


def _line_count(text, pos):
    return text.count("\n", 0, pos) + 1


# ---------------------------------------------------------------------------
# server
# ---------------------------------------------------------------------------
COMPOSE_FILE = re.compile(r"(^|/)(docker-)?compose([.-][\w.-]*)?\.ya?ml$")
# DB·캐시 이미지 — 이미지 이름의 마지막 구성 요소(태그·digest 앞)가 정확히 일치할 때만 (mongo-express·postgrest 제외)
DB_IMAGES = {"postgres", "postgis", "postgresql", "timescaledb", "mysql", "mariadb", "percona", "mongo", "mongodb",
             "redis", "redis-stack", "redis-stack-server", "valkey", "keydb", "elasticsearch", "opensearch",
             "memcached", "cassandra", "scylla", "couchdb", "rabbitmq", "clickhouse", "clickhouse-server", "neo4j",
             "influxdb", "cockroach", "etcd", "zookeeper", "kafka", "nats", "minio"}
LOOPBACK = ("127.0.0.1", "localhost", "::1", "[::1]")
SERVICE_KEY = re.compile(r"( *)([\"']?)([\w.-]+)\2[ \t]*:[ \t]*(?:&\S+)?[ \t]*$")
PRIVILEGED = re.compile(r"privileged[ \t]*:[ \t]*(true|True|TRUE)$")


def _indent(line):
    return len(line) - len(line.lstrip(" "))


def strip_yaml_comment(v):
    """줄 끝 YAML 주석(공백 뒤 #)을 지운다 — 따옴표 안은 유지. 선형 스캔."""
    quote = None
    for k, c in enumerate(v):
        if quote:
            if c == quote:
                quote = None
        elif c in "'\"":
            quote = c
        elif c == "#" and (k == 0 or v[k - 1] in " \t"):
            return v[:k].rstrip()
    return v.rstrip()


def _unquote(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        return v[1:-1]
    return v


def _kv(st):
    """`key: value` → (key, value) (주석 제거·따옴표 제거). 키가 아니면 None."""
    if ":" not in st:
        return None
    k, v = st.split(":", 1)
    k = k.strip()
    if not k or " " in k:
        return None
    return _unquote(k), _unquote(strip_yaml_comment(v))


def _image_is_db(image):
    ref = image.split("@", 1)[0]
    last = ref.rsplit("/", 1)[-1].split(":", 1)[0].lower()
    return last in DB_IMAGES or "mssql/server" in ref.lower()


def _split_flow(text):
    """흐름 문법 [a, "b", {k: v}] 안쪽을 최상위 쉼표로 나눈다 (괄호 깊이를 센다)."""
    items, depth, buf, quote = [], 0, [], None
    for c in text:
        if quote:
            buf.append(c)
            if c == quote:
                quote = None
            continue
        if c in "'\"":
            quote = c
        elif c in "{[":
            depth += 1
        elif c in "}]":
            depth -= 1
        elif c == "," and depth == 0:
            items.append("".join(buf).strip())
            buf = []
            continue
        buf.append(c)
    if "".join(buf).strip():
        items.append("".join(buf).strip())
    return items


def _flow_entry(item):
    item = item.strip()
    if item.startswith("{") and item.endswith("}"):
        e = {}
        for pair in _split_flow(item[1:-1]):
            kv = _kv(pair)
            if kv:
                e[kv[0]] = kv[1]
        return e
    return {"short": _unquote(item)}


def _port_exposed(e):
    """ports 항목이 모든 인터페이스에 열리는지 — "127.0.0.1:5432:5432"·host_ip 루프백은 아님.
    긴 문법에서 published 를 생략해도(target 만) 임의 호스트 포트가 모든 인터페이스에 게시된다."""
    if "short" in e:
        v = e["short"]
        return bool(v) and not v.startswith(LOOPBACK)
    return ("published" in e or "target" in e) and e.get("host_ip", "") not in LOOPBACK


def _port_label(e):
    if "short" in e:
        return e["short"]
    return "/".join(str(e.get(k)) for k in ("host_ip", "published", "target") if e.get(k))


def _compose_services(text):
    """docker-compose 의 services 아래 서비스별 (이름, [(줄 번호, 주석 지운 줄)]) — 들여쓰기 기반, 한 번 순회.
    앵커·병합 같은 고급 문법은 해석하지 않는다 (보이는 줄만 본다)."""
    out, in_services, svc_indent, cur = [], False, None, None
    for n, raw in _lines(text):
        line = strip_yaml_comment(raw.replace("\t", "  "))
        if not line.strip():
            continue
        ind = _indent(line)
        if ind == 0:
            in_services = line.startswith("services:")
            cur, svc_indent = None, None
            continue
        if not in_services:
            continue
        if svc_indent is None:
            svc_indent = ind
        if ind == svc_indent:
            m = SERVICE_KEY.fullmatch(line)
            cur = (m.group(3), []) if m else None   # 서비스로 인식하지 못한 줄에서 끊는다
            if cur:
                out.append(cur)
        elif cur and ind > svc_indent:
            cur[1].append((n, line))
    return out


def check_compose(ctx):
    """S6 — docker-compose 의 privileged, docker.sock 마운트, DB·캐시 포트의 전체 인터페이스 바인딩 (서비스 본문 한 번 순회)."""
    out = []
    for rel, full in ctx.files(lambda rel, name: bool(COMPOSE_FILE.search(rel))):
        text = ctx.read(full)
        if text is None:
            continue
        for name, body in _compose_services(text):
            image = next((kv[1] for _, l in body for kv in [_kv(l.strip())] if kv and kv[0] == "image"), "")
            is_db = _image_is_db(image) if image else False
            block, block_indent, entries, flow, flow_line = None, None, [], None, None
            for n, line in body + [(None, "")]:
                st, ind = line.strip(), _indent(line)
                if flow is not None:                      # 여러 줄 흐름 문법 ports: [ … ]
                    flow += " " + st
                    if "]" in st or len(flow) > MAX_LINE or n is None:
                        inner = flow.split("[", 1)[-1].rsplit("]", 1)[0]
                        entries += [(flow_line, _flow_entry(x)) for x in _split_flow(inner) if x]
                        flow = None
                    continue
                if block and (n is None or (ind <= block_indent and not (ind == block_indent and st.startswith("-")))):
                    block = None
                if n is None:
                    break
                if block is None:
                    if PRIVILEGED.fullmatch(st):
                        out.append(ctx.finding(
                            "compose", "server.compose-privileged", "medium", "config", rel, n,
                            "compose 서비스가 privileged 로 실행됩니다",
                            evidence=f"서비스 {name}: privileged: true — 호스트 장치·커널 기능에 거의 제한 없이 접근합니다",
                            fix_hint="privileged 를 빼고 필요한 cap_add 만 지정하세요.", references=["CWE-250"]))
                    kv = _kv(st)
                    if kv and kv[0] in ("ports", "volumes"):
                        if kv[0] == "ports" and kv[1].startswith("["):
                            if "]" in kv[1]:
                                inner = kv[1].split("[", 1)[1].rsplit("]", 1)[0]
                                entries += [(n, _flow_entry(x)) for x in _split_flow(inner) if x]
                            else:
                                flow, flow_line = kv[1], n
                        elif not kv[1]:
                            block, block_indent = kv[0], ind
                    continue
                # ports·volumes 블록 안
                if st.startswith("-"):
                    item = st[1:].strip()
                    kv = _kv(item) if item and not item[0].isdigit() and not item.startswith(("'", '"', "[", "/", ".")) else None
                    if block == "volumes":
                        entries.append((n, {"volume": item}))
                    elif kv:
                        entries.append((n, {kv[0]: kv[1]}))
                    else:
                        entries.append((n, {"short": _unquote(item)} if item else {}))
                elif entries:
                    kv = _kv(st)
                    if kv:
                        entries[-1][1].pop("short", None)
                        entries[-1][1][kv[0]] = kv[1]
            seen = set()
            for en, e in entries:
                if "volume" in e or "source" in e:
                    src = e.get("volume") or e.get("source", "")
                    if "docker.sock" in src and ("volume", en) not in seen:
                        seen.add(("volume", en))
                        out.append(ctx.finding(
                            "compose", "server.compose-docker-socket", "medium", "config", rel, en,
                            "compose 서비스에 Docker 소켓이 마운트됩니다",
                            evidence=f"서비스 {name}: docker.sock 마운트 — 호스트 Docker 를 제어해 사실상 root 권한을 얻습니다",
                            fix_hint="꼭 필요하면 읽기 전용 프록시(docker-socket-proxy 등)로 범위를 줄이세요.", references=["CWE-250"]))
                elif is_db and ("short" in e or "published" in e or "target" in e) and _port_exposed(e) and ("port", en) not in seen:
                    seen.add(("port", en))
                    out.append(ctx.finding(
                        "compose", "server.compose-db-port-exposed", "medium", "config", rel, en,
                        "DB·캐시 서비스 포트가 모든 인터페이스에 열립니다",
                        evidence=f"서비스 {name}, 포트 {_port_label(e)} — 호스트 IP 없이 게시하면 0.0.0.0 에 바인딩되어 같은 네트워크에서 접속할 수 있습니다",
                        fix_hint="\"127.0.0.1:5432:5432\" 처럼 루프백에만 게시하거나, 다른 서비스만 접근하면 ports 대신 내부 네트워크를 쓰세요.",
                        references=["CWE-668"]))
    return out


SPRING_CONFIG = re.compile(r"(^|/)(application|bootstrap)(-[\w.-]+)?\.(ya?ml|properties)$")
SECRET_KEY = re.compile(r"(password|passwd|pwd|secret|token|api[-_]?key|private[-_]?key|credentials?)$", re.I)
NOT_A_SECRET = re.compile(r"(null|~|none|changeme|true|false|yes|no|on|off|\d+(\.\d+)?)", re.I)
PROPS_LINE = re.compile(r"[ \t]*((?:\\.|[^=:\s\\])+)[ \t]*(?:[=:]|[ \t])[ \t]*(.*)")
YAML_KEY = re.compile(r"( *)([\w.\-\[\]\"']+)[ \t]*:(.*)")


def _secret_value(v):
    """평문 비밀로 볼 값이면 (True, 설명), 아니면 (False, None). ${NAME:기본값} 은 기본값을 본다."""
    v = _unquote(v)
    if v.startswith("&"):                                   # YAML 앵커
        v = _unquote(v.split(None, 1)[1]) if " " in v else ""
    if v.startswith("${") and v.endswith("}") and v.count("${") == 1:
        inner = v[2:-1]
        if ":" not in inner:
            return False, None
        default = inner.split(":", 1)[1]
        ok = bool(default) and not NOT_A_SECRET.fullmatch(default) and not default.startswith(("{cipher}", "ENC("))
        return ok, "자리표시자의 기본값"
    if not v or "${" in v or NOT_A_SECRET.fullmatch(v) or v.startswith(("{cipher}", "ENC(", "|", ">", "*")):
        return False, None
    return True, None


def check_spring_config_secret(ctx):
    """S1 보강 — Spring application*·bootstrap*(.yml·.properties)의 비밀 키에 평문 값 (값은 결과에 넣지 않는다).
    ${ENV}·{cipher}·ENC(...)·불리언·숫자는 제외, ${ENV:기본값} 은 기본값이 평문이면 결과. 테스트 설정은 low."""
    out = []
    for rel, full in ctx.files(lambda rel, name: bool(SPRING_CONFIG.search(rel))):
        text = ctx.read(full)
        if text is None:
            continue
        sev = "low" if ("/src/test/" in "/" + rel or "-test." in rel) else "high"
        hits = []
        if rel.endswith(".properties"):
            continued = False
            for n, line in _lines(text):
                was_continued, continued = continued, (len(line) - len(line.rstrip("\\"))) % 2 == 1
                if was_continued or not line.strip() or line.lstrip().startswith(("#", "!")):
                    continue
                m = PROPS_LINE.fullmatch(line.rstrip("\\") if continued else line)
                if not m:
                    continue
                key = m.group(1).replace("\\", "")
                ok, note = _secret_value(m.group(2).strip())
                if SECRET_KEY.search(key) and ok:
                    hits.append((n, key, note))
        else:
            stack, block_indent = [], None
            for n, raw in _lines(text):
                if raw.startswith("---"):
                    stack, block_indent = [], None
                    continue
                if not raw.strip() or raw.lstrip().startswith("#"):
                    continue
                ind = _indent(raw)
                if block_indent is not None:
                    if ind > block_indent:
                        continue                              # 블록 스칼라 내용
                    block_indent = None
                line = raw
                if line.lstrip().startswith("- "):              # 리스트 항목의 첫 키
                    k = line.index("-")
                    line = line[:k] + " " + line[k + 1:]
                    ind = _indent(line)
                m = YAML_KEY.fullmatch(line)
                if not m:
                    continue
                key, val = _unquote(m.group(2)), strip_yaml_comment(m.group(3)).strip()
                while stack and stack[-1][0] >= ind:
                    stack.pop()
                stack.append((ind, key))
                if val.startswith(("|", ">")):
                    block_indent = ind
                    continue
                ok, note = _secret_value(val)
                if val and SECRET_KEY.search(key) and ok:
                    hits.append((n, ".".join(k for _, k in stack), note))
        for n, key, note in hits:
            out.append(ctx.finding(
                "spring-config-secret", "server.config-plaintext-secret", sev, "secret", rel, n,
                "설정 파일의 비밀 키에 평문 값이 있습니다",
                evidence=f"키: {key}{' (' + note + ')' if note else ''} — 값은 리포트에 남기지 않습니다",
                fix_hint="${ENV_VAR} 자리표시자로 바꾸고(기본값도 비우세요) 값은 환경 변수·시크릿 저장소로 옮기세요. 이미 커밋됐다면 폐기(rotate)하세요.",
                references=["CWE-798"]))
    return out


# ---------------------------------------------------------------------------
# 등록부
# ---------------------------------------------------------------------------
CHECKS = {
    "env-public-secret": check_env_public_secret,
    "next-unauth-route": check_next_unauth_route,
    "next-config": check_next_config,
    "npm-install-scripts": check_npm_install_scripts,
    "compose": check_compose,
    "spring-config-secret": check_spring_config_secret,
}
# 저장소 전체를 보는 검사 — 인프라 설정처럼 프로파일 하위 경로가 아니라 저장소 루트에 있는 경우가 많은 것.
# 감지된 프로파일 중 하나라도 이 검사를 쓰면 대상 루트 기준으로 한 번만 실행한다.
REPO_WIDE = {"compose"}


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
