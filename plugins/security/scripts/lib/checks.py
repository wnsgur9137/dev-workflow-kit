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
import hashlib
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
        """대상 폴더 안의 일반 파일을 텍스트로 (read_bytes 참고)."""
        data = self.read_bytes(full)
        return None if data is None else data.decode("utf-8-sig", "replace")

    def read_bytes(self, full):
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
            return data
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
    prev_word, in_word = "", False
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
            prev, prev_word, in_word = c, "", False
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
                prev, prev_word, in_word = "/", "", False
            else:                # 줄 안에서 끝나지 않으면 나눗셈으로 본다
                out.append(c)
                prev = c
                i += 1
        else:
            out.append(c)
            if c.isspace():
                in_word = False                                # 공백에서 단어가 끝난다 (이전: 계속 이어 붙어 이차 시간)
            else:
                if c.isalnum() or c in "_$":
                    # return·typeof 판정에는 최근 몇 글자면 충분 — 길이를 제한해 선형으로 둔다
                    prev_word = ((prev_word + c) if in_word else c)[-8:]
                    in_word = True
                else:
                    prev_word, in_word = "", False
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


def _public_env_regexes(start, end, prefixes=PUBLIC_ENV_PREFIXES):
    """(비밀 정규식, API 키 정규식). start·end 는 이름 앞뒤 경계 (변수 이름은 ^ $, 대괄호 문자열은 따옴표 포함).
    prefixes=("",) 이면 접두사와 무관하게 이름만 본다 (react-native-config)."""
    tail = r"(?:_[A-Za-z0-9_]*)?" + end

    def guarded(words, public):
        return r"(?!" + _SEG + _alt(public) + r"(?:_|" + end + r"))" + _SEG + _alt(words) + tail

    prefix = start + _alt(prefixes)
    secret = prefix + r"(?:" + _SEG + _alt(STRONG_WORDS) + tail + "|" + guarded(TOKEN_WORDS, TOKEN_PUBLIC) + ")"
    return secret, prefix + guarded(KEY_WORDS, KEY_PUBLIC)


PUBLIC_ENV_SECRET_RE, PUBLIC_ENV_KEY_RE = _public_env_regexes("^", "$")
# Semgrep 의 process.env['X'] 형태용 — 메타변수 텍스트에 따옴표가 포함된다
PUBLIC_ENV_SECRET_BRACKET_RE, PUBLIC_ENV_KEY_BRACKET_RE = _public_env_regexes("^[\"']", "[\"']$")
_SECRET_NAME = re.compile(PUBLIC_ENV_SECRET_RE)
_KEY_NAME = re.compile(PUBLIC_ENV_KEY_RE)
_ANY_SECRET_NAME, _ANY_KEY_NAME = (re.compile(r) for r in _public_env_regexes("^", "$", ("",)))
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
             "influxdb", "cockroach", "etcd", "zookeeper", "kafka", "nats", "minio", "mysql-server",
             "mongodb-community-server", "mongodb-enterprise-server", "cp-kafka", "oracle-xe", "oracle-free", "mssql"}
LOOPBACK = ("127.0.0.1", "localhost", "::1", "[::1]")
# 줄은 strip_yaml_comment 로 끝 공백이 지워진 상태 — 끝의 [ \t]*$ 를 두면 이차 백트래킹이 생긴다 (PR #25 재리뷰)
SERVICE_KEY = re.compile(r"( *)([\"']?)([\w.-]+)\2[ \t]*:(?:[ \t]+&\S+)?")
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
    m = re.fullmatch(r"\$\{[\w]+:?-([^}]*)\}", image.strip())     # ${PG_IMAGE:-postgres:16} → 기본값으로 판정
    if m:
        image = m.group(1)
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
    """S6 — docker-compose 의 privileged, docker.sock 마운트, DB·캐시 포트의 전체 인터페이스 바인딩 (서비스 본문 한 번 순회).
    서비스 직속 키(첫 들여쓰기)만 해석한다 — labels 같은 하위 매핑 안의 같은 이름은 보지 않는다."""
    out = []
    for rel, full in ctx.files(lambda rel, name: bool(COMPOSE_FILE.search(rel))):
        text = ctx.read(full)
        if text is None:
            continue
        for name, body in _compose_services(text):
            if not body:
                continue
            key_indent = _indent(body[0][1])
            image = next((kv[1] for _, l in body if _indent(l) == key_indent
                          for kv in [_kv(l.strip())] if kv and kv[0] == "image"), "")
            is_db = _image_is_db(image) if image else False
            block, entries, flow, flow_line, flow_kind = None, [], None, None, None
            for n, line in body + [(None, "")]:
                st, ind = line.strip(), _indent(line)
                if flow is not None:                      # 여러 줄 흐름 문법 ports|volumes: [ … ]
                    flow += " " + st
                    if "]" in st or len(flow) > MAX_LINE or n is None:
                        inner = flow.split("[", 1)[-1].rsplit("]", 1)[0]
                        entries += [(flow_line, flow_kind, _flow_entry(x)) for x in _split_flow(inner) if x]
                        flow = None
                    continue
                if block and (n is None or ind < key_indent or (ind == key_indent and not st.startswith("-"))):
                    block = None
                if n is None:
                    break
                if block is None:
                    if ind != key_indent:
                        continue
                    if PRIVILEGED.fullmatch(st):
                        out.append(ctx.finding(
                            "compose", "server.compose-privileged", "medium", "config", rel, n,
                            "compose 서비스가 privileged 로 실행됩니다",
                            evidence=f"서비스 {name}: privileged: true — 호스트 장치·커널 기능에 거의 제한 없이 접근합니다",
                            fix_hint="privileged 를 빼고 필요한 cap_add 만 지정하세요.", references=["CWE-250"]))
                    kv = _kv(st)
                    if kv and kv[0] in ("ports", "volumes"):
                        val = re.sub(r"^!(override|reset)\b[ \t]*", "", kv[1])   # compose 2.24+ 태그
                        if val.startswith("["):
                            if "]" in val:
                                inner = val.split("[", 1)[1].rsplit("]", 1)[0]
                                entries += [(n, kv[0], _flow_entry(x)) for x in _split_flow(inner) if x]
                            else:
                                flow, flow_line, flow_kind = val, n, kv[0]
                        elif not val:
                            block = kv[0]
                    continue
                # ports·volumes 블록 안
                if st.startswith("-"):
                    item = st[1:].strip()
                    is_scalar = not item or item[0].isdigit() or item.startswith(("'", '"', "[", "/", ".", "$", "~"))
                    kv = None if is_scalar else _kv(item)
                    if kv:
                        entries.append((n, block, {kv[0]: kv[1]}))
                    else:
                        entries.append((n, block, {"short": _unquote(item)} if item else {}))
                elif entries:
                    kv = _kv(st)
                    if kv:
                        entries[-1][2].pop("short", None)
                        entries[-1][2][kv[0]] = kv[1]
            seen = set()
            for en, kind, e in entries:
                if kind == "volumes":
                    src = e.get("short") or e.get("source", "")
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
NOT_A_SECRET = re.compile(r"(null|~|none|changeme)", re.I)
# 불리언·숫자는 설정 값일 가능성이 높아 제외하되, 비밀번호 키(password·passwd·pwd)는 숫자도 비밀번호로 본다 (PR #25 재리뷰)
NOT_A_SECRET_SETTING = re.compile(r"(true|false|yes|no|on|off|\d+(\.\d+)?)", re.I)
PASSWORD_KEY = re.compile(r"(password|passwd|pwd)$", re.I)
PROPS_LINE = re.compile(r"[ \t]*((?:\\.|[^=:\s\\])+)[ \t]*(?:[=:]|[ \t])[ \t]*(.*)")
YAML_KEY = re.compile(r"( *)([\w.\-\[\]\"']+)[ \t]*:(.*)")


def _secret_value(raw, key="", yaml=False):
    """평문 비밀로 볼 값이면 (True, 설명), 아니면 (False, None). ${NAME:기본값} 은 기본값을 본다.
    YAML 의 별칭(*x)·앵커(&x)는 따옴표를 벗기기 전 값에서만 판정한다."""
    raw = raw.strip()
    if yaml:
        if raw.startswith("*"):                              # 별칭 — 값이 아니다
            return False, None
        if raw.startswith("&"):                              # 앵커 — 뒤의 값을 본다
            raw = raw.split(None, 1)[1] if " " in raw else ""
    v = _unquote(raw)

    def plain(x):
        if not x or NOT_A_SECRET.fullmatch(x) or x.startswith(("{cipher}", "ENC(")):
            return False
        if not NOT_A_SECRET_SETTING.fullmatch(x):
            return True
        return bool(PASSWORD_KEY.search(key)) and bool(re.fullmatch(r"\d+", x))   # 숫자 비밀번호(1234)만 인정

    if v.startswith("${") and v.endswith("}") and v.count("${") == 1:
        inner = v[2:-1]
        if ":" not in inner:
            return False, None
        default = inner.split(":", 1)[1].lstrip("-")
        return plain(default), "자리표시자의 기본값"
    if "${" in v:
        return False, None
    return plain(v), None


TEST_PATH = re.compile(r"(^|/)src/[^/]*[Tt]est[^/]*/|-test\.")


def check_spring_config_secret(ctx):
    """S1 보강 — Spring application*·bootstrap*(.yml·.properties)의 비밀 키에 평문 값 (값은 결과에 넣지 않는다).
    ${ENV}·{cipher}·ENC(...)·불리언·숫자는 제외, ${ENV:기본값} 은 기본값이 평문이면 결과. 테스트 설정은 low."""
    out = []
    for rel, full in ctx.files(lambda rel, name: bool(SPRING_CONFIG.search(rel))):
        text = ctx.read(full)
        if text is None:
            continue
        sev = "low" if TEST_PATH.search(rel) else "high"
        hits = []
        if rel.endswith(".properties"):
            continued = False
            for n, line in enumerate(text.splitlines(), 1):      # 이어짐 상태는 긴 줄도 포함해 계산한다
                was_continued, continued = continued, (len(line) - len(line.rstrip("\\"))) % 2 == 1
                if was_continued or len(line) > MAX_LINE or not line.strip() or line.lstrip().startswith(("#", "!")):
                    continue
                m = PROPS_LINE.fullmatch(line.rstrip("\\") if continued else line)
                if not m:
                    continue
                key = m.group(1).replace("\\", "")
                ok, note = _secret_value(m.group(2).strip(), key)
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
                ok, note = _secret_value(val, key, yaml=True)
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
# android
# ---------------------------------------------------------------------------
ANDROID_NS = "{http://schemas.android.com/apk/res/android}"
TOOLS_NODE = "{http://schemas.android.com/tools}node"
COMPONENTS = ("activity", "activity-alias", "service", "receiver", "provider")
# 디버그·테스트 소스셋의 Manifest 는 일부러 debuggable·cleartext 를 켜는 경우가 흔하다 — low 로 낮춘다
ANDROID_DEBUG_SOURCESET = re.compile(r"(^|/)src/(?:debug|androidTest\w*|test\w*|\w+Debug)/")
RES_NAME = re.compile(r"[A-Za-z0-9_]+")


def parse_xml(ctx, rel, full):
    """대상 XML 을 안전하게 파싱한다 — DOCTYPE·엔티티 선언이 있으면 거부(엔티티 확장 공격 방지). 실패하면 None."""
    import xml.etree.ElementTree as ET
    text = ctx.read(full)
    if text is None:
        return None, None
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        ctx.warn(f"{rel}: DOCTYPE·엔티티 선언이 있어 해석하지 않았습니다")
        return None, None
    try:
        return ET.fromstring(text), text
    except ET.ParseError:
        ctx.warn(f"{rel}: XML 을 해석하지 못했습니다")
        return None, None


class _LineCursor:
    """문서 순서대로 찾으며 줄 번호를 이어 센다 (선형) — 같은 문자열이 여러 번 나와도 앞에서부터 차례로."""

    def __init__(self, text):
        self.text, self.pos, self.line = text or "", 0, 1

    def find(self, needle):
        k = self.text.find(needle, self.pos)
        return self._move(k)

    def find_re(self, rx):
        m = rx.search(self.text, self.pos)
        return self._move(m.start() if m else -1)

    def _move(self, k):
        if k < 0:
            return None                      # 못 찾으면 커서를 움직이지 않는다 (뒤 요소를 놓치지 않게)
        self.line += self.text.count("\n", self.pos, k)
        self.pos = k
        return self.line


def _xml_line(text, needle, start=0):
    pos = (text or "").find(needle, start)
    return (text.count("\n", 0, pos) + 1) if pos >= 0 else 1


def _attr(el, name):
    return el.get(ANDROID_NS + name)


def _is_launcher(el):
    for f in el.findall("intent-filter"):
        actions = {_attr(a, "name") for a in f.findall("action")}
        cats = {_attr(c, "name") for c in f.findall("category")}
        if "android.intent.action.MAIN" in actions and "android.intent.category.LAUNCHER" in cats:
            return True
    return False


def check_android_manifest(ctx):
    """A2·A3·A4 — AndroidManifest.xml 의 debuggable·allowBackup·usesCleartextTraffic, 권한 없는 exported 컴포넌트,
    networkSecurityConfig 의 cleartextTrafficPermitted·사용자 CA 신뢰(debug-overrides 밖). 디버그·테스트 소스셋은 low."""
    out = []
    for rel, full in ctx.files(lambda rel, name: name == "AndroidManifest.xml"):
        root, text = parse_xml(ctx, rel, full)
        if root is None:
            continue
        app = root.find("application")
        if app is None:
            continue
        debug_set = bool(ANDROID_DEBUG_SOURCESET.search(rel))

        def sev(normal):
            return "low" if debug_set else normal

        cur = _LineCursor(text)
        cur.find("<application")
        nsc = _attr(app, "networkSecurityConfig")
        for attr, rid, normal, title, hint, cwe in (
            ("debuggable", "android.manifest-debuggable", "high",
             "android:debuggable=\"true\" — 릴리스 빌드에 남으면 디버거 연결·데이터 추출이 가능합니다",
             "Manifest 에서 debuggable 을 지우세요(빌드 타입이 정합니다).", "CWE-489"),
            ("allowBackup", "android.manifest-allow-backup", "medium",
             "android:allowBackup=\"true\" — adb backup·클라우드 백업으로 앱 데이터가 밖으로 나갈 수 있습니다",
             "false 로 두거나 dataExtractionRules·fullBackupContent 로 민감 데이터를 제외하세요.", "CWE-530"),
            ("usesCleartextTraffic", "android.manifest-cleartext", "high",
             "android:usesCleartextTraffic=\"true\" — 평문 HTTP 통신을 허용합니다",
             "false 로 두고, 꼭 필요한 도메인만 network_security_config 의 domain-config 로 허용하세요.", "CWE-319"),
        ):
            if _attr(app, attr) != "true":
                continue
            s_ = sev(normal)
            note = ""
            if attr == "usesCleartextTraffic" and nsc:
                s_, note = sev("medium"), " (networkSecurityConfig 가 있어 API 24 이상에서는 그 설정이 우선)"
            out.append(ctx.finding(
                "android-manifest", rid, s_, "mobile", rel, _xml_line(text, f'android:{attr}=', cur.pos),
                title, evidence=f"application android:{attr}=\"true\"{note}" + (" — 디버그·테스트 소스셋" if debug_set else ""),
                fix_hint=hint, references=[cwe]))
        app_perm = _attr(app, "permission")      # application 의 permission 은 컴포넌트 기본값이다
        for el in app:
            if el.tag not in COMPONENTS:
                continue
            name = _attr(el, "name") or "?"
            # 요소의 android:name= 속성 위치 (작은·큰따옴표 모두) — 다른 속성의 같은 값(targetActivity 등)으로 앞질러 가지 않게
            line = cur.find_re(re.compile(r"\bandroid:name[ \t\r\n]*=[ \t\r\n]*[\"']" + re.escape(name) + r"[\"']")) if name != "?" else None
            if _attr(el, "exported") != "true" or el.get(TOOLS_NODE) in ("remove", "removeAll"):
                continue
            if el.tag in ("activity", "activity-alias") and _is_launcher(el):
                continue
            if app_perm or any(_attr(el, k) for k in ("permission", "readPermission", "writePermission")):
                continue
            out.append(ctx.finding(
                "android-manifest", "android.manifest-exported-component", sev("high"), "mobile", rel, line,
                "권한 없이 exported 된 컴포넌트 — 다른 앱이 호출할 수 있습니다",
                evidence=f"{el.tag} {name}: exported=\"true\", permission 없음",
                fix_hint="외부 호출이 필요 없으면 exported=\"false\", 필요하면 signature 수준 permission 을 지정하세요.",
                references=["CWE-926"]))
            if len(out) > MAX_RESULTS_PER_CHECK:
                break
        if nsc and nsc.startswith("@xml/"):
            res = nsc[5:]
            if not RES_NAME.fullmatch(res):
                ctx.warn(f"{rel}: networkSecurityConfig 값이 리소스 이름 형식이 아니어서 확인하지 않았습니다")
                continue
            nsc_rel = os.path.normpath(os.path.join(os.path.dirname(rel), "res", "xml", res + ".xml"))
            nsc_full = os.path.join(ctx.target, nsc_rel)
            if os.path.isfile(nsc_full) and not os.path.islink(nsc_full):
                out += _check_nsc(ctx, nsc_rel, nsc_full, debug_set)
            else:
                ctx.warn(f"{rel}: networkSecurityConfig 가 가리키는 {nsc_rel} 을 찾지 못해 확인하지 않았습니다 (다른 소스셋·flavor 일 수 있음)")
    return out


def _check_nsc(ctx, rel, full, debug_set=False):
    """network_security_config — base-config·domain-config 의 평문 허용과 사용자 CA (debug-overrides 는 디버그 빌드 전용이라 제외)."""
    out = []
    root, text = parse_xml(ctx, rel, full)
    if root is None:
        return out
    cur = _LineCursor(text)
    for el in root.iter():
        if el.tag not in ("base-config", "domain-config"):
            continue
        line = cur.find("<" + el.tag)
        if el.get("cleartextTrafficPermitted") == "true":
            scope = "전체" if el.tag == "base-config" else "일부 도메인"
            normal = "high" if el.tag == "base-config" else "medium"
            out.append(ctx.finding(
                "android-manifest", "android.nsc-cleartext", "low" if debug_set else normal, "mobile", rel, line,
                f"network_security_config 가 평문 HTTP 를 허용합니다 ({scope})",
                evidence=f"{el.tag} cleartextTrafficPermitted=\"true\"",
                fix_hint="평문이 꼭 필요한 개발용 도메인만 domain-config 로 허용하고 base-config 는 false 로 두세요.",
                references=["CWE-319"]))
        for anchors in el.findall("trust-anchors"):
            if any(c.get("src") == "user" for c in anchors.findall("certificates")):
                out.append(ctx.finding(
                    "android-manifest", "android.nsc-user-certs", "low" if debug_set else "medium", "mobile", rel, line,
                    "network_security_config 가 사용자 설치 CA 를 신뢰합니다 — 중간자 공격 프록시가 TLS 를 가로챌 수 있습니다",
                    evidence=f"{el.tag} 의 trust-anchors 에 certificates src=\"user\"",
                    fix_hint="debug-overrides 안으로 옮겨 디버그 빌드에서만 허용하세요.", references=["CWE-295"]))
    return out


GRADLE_FILE = re.compile(r"(^|/)build\.gradle(\.kts)?$")
# 플러그인 선언 형태만 (namespace = "org.android.application.core" 같은 문자열은 아니다)
APP_PLUGIN_LINE = re.compile(
    r"\bid[ \t]*\(?[ \t]*[\"']com\.android\.application[\"']"
    r"|\bapply[ \t]+plugin[ \t]*:[ \t]*[\"']com\.android\.application[\"']"
    r"|\blibs\.plugins\.android\.application\b|\blibs\.plugins\.androidApplication\b")
RELEASE_BLOCK = re.compile(r"(?:\brelease|\b(?:getByName|named|maybeCreate|create)\([ \t]*[\"']release[\"'][ \t]*\)(?:\.apply|\.configure)?)(?:[ \t]*\n)?[ \t]*\{")
BUILD_TYPES = re.compile(r"\bbuildTypes(?:[ \t]*\n)?[ \t]*\{")     # 공백 수량자가 연달아 붙지 않게
MINIFY_ON = re.compile(r"\b(?:is)?[mM]inifyEnabled[ \t]*(?:=[ \t]*|\([ \t]*)?true\b")


def _brace_block(code, start):
    """code[start] 가 '{' 일 때 짝이 맞는 '}' 까지의 내용 (주석은 이미 지운 코드). 못 찾으면 None.
    문자열 안의 중괄호는 무시하고, 백슬래시는 다음 문자를 건너뛴다 ('C:\\\\' 처럼 이스케이프된 백슬래시)."""
    depth, quote, k, end = 0, None, start, min(len(code), start + 200_000)
    while k < end:
        c = code[k]
        if quote:
            if c == "\\":
                k += 2
                continue
            if c == quote:
                quote = None
        elif c in "'\"":
            quote = c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return code[start + 1:k]
        k += 1
    return None


def _is_android_app_module(text):
    """앱 모듈 빌드 파일인지 — 플러그인 선언 줄에 apply false 가 붙은 루트 빌드 파일은 아니다 (원문에서 먼저 거른다)."""
    for line in text.splitlines():
        st = line.strip()
        if len(line) > MAX_LINE or st.startswith(("//", "/*", "*")):
            continue                                   # 주석 줄 (블록 주석 안의 줄은 * 로 시작하는 관례만 거른다)
        code = line.split(" //", 1)[0]
        if APP_PLUGIN_LINE.search(code) and "apply false" not in code and "apply(false)" not in code:
            return True
    return False


def check_android_gradle_release(ctx):
    """A5 — 앱 모듈의 release 빌드 타입이 난독화(R8)를 끄거나 release 블록이 없다 (기본값은 꺼짐)."""
    out = []
    for rel, full in ctx.files(lambda rel, name: bool(GRADLE_FILE.search(rel))):
        text = ctx.read(full)
        if text is None or not _is_android_app_module(text):
            continue
        code = strip_js_comments(text)      # Groovy·Kotlin 주석 문법이 같다
        if not re.search(r"\bandroid[ \t]*\{", code):
            continue
        release, line = None, 1
        # 문자열 안 'buildTypes {' 같은 가짜 일치를 건너뛰되, 닫히지 않은 블록이 반복돼도 이차 시간이 되지 않게 시도 횟수를 제한한다
        for attempt, m in enumerate(BUILD_TYPES.finditer(code)):
            if attempt >= 5:
                break
            types = _brace_block(code, m.end() - 1)
            if types is None:
                continue
            line = code.count("\n", 0, m.start()) + 1
            r = RELEASE_BLOCK.search(types)
            if r:
                release = _brace_block(types, r.end() - 1)
                break
        if release is not None and MINIFY_ON.search(release):
            continue
        out.append(ctx.finding(
            "android-gradle-release", "android.gradle-release-minify-disabled", "medium", "mobile", rel, line,
            "release 빌드에서 코드 축소·난독화(R8)가 꺼져 있습니다",
            evidence=("release 빌드 타입에 minifyEnabled true 가 없습니다" if release is not None
                      else "release 빌드 타입이 없어 기본값(난독화 꺼짐)이 적용됩니다"),
            fix_hint="buildTypes.release 에 minifyEnabled true(isMinifyEnabled = true)와 shrinkResources true 를 켜고 proguard 규칙을 관리하세요.",
            references=["CWE-656"]))
    return out


GRADLE_PROPS = re.compile(r"(^|/)(gradle|local|keystore|signing)\.properties$")
SECRET_KEYWORD = re.compile(r"(password|passwd|pwd|secret|token|api[-_]?key|private[-_]?key|access[-_]?key)", re.I)
# 위치·설정을 뜻하는 접미사 — TOKEN_URL·secretsPropertiesFile·keystorePasswordFile 같은 키는 비밀 값이 아니다
LOCATION_SUFFIX = re.compile(r"(url|uri|file|path|dir|directory|name|host|endpoint|enabled|alias|type|header)$", re.I)


def is_secret_key(key):
    """properties·xcconfig 키가 비밀 값을 담는 키인지 — 키워드는 어디에 있어도 되고(SECRET_KEY·AUTH_TOKEN_DEV),
    위치·설정을 뜻하는 접미사로 끝나면 제외한다."""
    return bool(SECRET_KEYWORD.search(key)) and not LOCATION_SUFFIX.search(key)


def check_android_properties_secret(ctx):
    """A1 보강 — gradle.properties·local.properties·keystore.properties 의 비밀 키 평문 값 (서명 비밀번호 등, 값은 기록하지 않음)."""
    out = []
    for rel, full in ctx.files(lambda rel, name: bool(GRADLE_PROPS.search(rel))):
        text = ctx.read(full)
        if text is None:
            continue
        continued = False
        for n, line in enumerate(text.splitlines(), 1):          # 이어짐(\) 상태는 긴 줄도 포함해 계산
            was_continued, continued = continued, (len(line) - len(line.rstrip("\\"))) % 2 == 1
            if was_continued or len(line) > MAX_LINE or not line.strip() or line.lstrip().startswith(("#", "!")):
                continue
            m = PROPS_LINE.fullmatch(line.rstrip("\\") if continued else line)
            if not m:
                continue
            key = m.group(1).replace("\\", "")
            ok, _note = _secret_value(m.group(2).strip(), key)
            if is_secret_key(key) and ok:
                out.append(ctx.finding(
                    "android-properties-secret", "android.properties-secret", "high", "secret", rel, n,
                    "properties 파일의 비밀 키에 평문 값이 있습니다 (서명 키 비밀번호 등)",
                    evidence=f"키: {key[:60]} — 값은 리포트에 남기지 않습니다",
                    fix_hint="~/.gradle/gradle.properties(저장소 밖)나 CI 시크릿으로 옮기고, 커밋됐다면 키를 교체하세요.",
                    references=["CWE-798"]))
    return out


# ---------------------------------------------------------------------------
# ios
# ---------------------------------------------------------------------------
WEAK_TLS = ("TLSv1.0", "TLSv1.1")
# iOS 10 이상에서 이 키 중 하나라도 있으면 NSAllowsArbitraryLoads 는 무시된다 (Apple 문서 NSAllowsArbitraryLoads)
ATS_OVERRIDES = ("NSAllowsArbitraryLoadsForMedia", "NSAllowsArbitraryLoadsInWebContent", "NSAllowsLocalNetworking")
# 숫자 100자 이상, 또는 CDATA·문자 참조로 쓴 정수(정규식 우회 차단 — 정상 plist 는 정수를 이렇게 쓰지 않는다)
HUGE_PLIST_INT = re.compile(rb"<integer>[ \t\r\n]*(?:[-+]?[0-9]{100,}|<!\[CDATA\[|&#)")


def _load_plist(ctx, rel, full):
    """Info.plist(XML·바이너리)를 표준 plistlib 로 읽는다 — XML 엔티티 선언은 plistlib 이 거부한다.
    아주 긴 정수(Python 3.8·3.9 초기 버전의 int 변환 이차 시간, CVE-2020-10735)는 파싱 전에 거른다."""
    import plistlib
    data = ctx.read_bytes(full)
    if data is None:
        return None, None
    if HUGE_PLIST_INT.search(data):
        ctx.warn(f"{rel}: 비정상적으로 긴 정수가 있어 plist 를 해석하지 않았습니다")
        return None, None
    try:
        return plistlib.loads(data), (data.decode("utf-8", "replace") if data[:6] != b"bplist" else "")
    except Exception:  # noqa: BLE001 — 대상 파일은 신뢰하지 않는 입력이다
        ctx.warn(f"{rel}: plist 를 해석하지 못했습니다")
        return None, None


def _plist_key(k):
    from xml.sax.saxutils import escape
    return f"<key>{escape(str(k))}</key>"


ATS_DOMAIN_ID_MAX = 120 - len("ATS:NSExceptionDomains/") - len("/tls")  # 93


def _ats_domain_id(domain):
    """결과 표시·id 용 도메인 — 긴 이름은 잘라 해시를 붙여 앞부분이 같은 도메인끼리 겹치지 않게 한다.
    package `ATS:NSExceptionDomains/<도메인>/tls` 가 normalize 의 120자 절단 안에 들어오도록 93자를 기준으로 한다 (PR #27 2차 재리뷰 W-B)"""
    d = str(domain)
    if len(d) <= ATS_DOMAIN_ID_MAX:
        return d
    return d[:70] + "…#" + hashlib.sha256(d.encode("utf-8", "replace")).hexdigest()[:12]


def check_ios_ats(ctx):
    """I2 — Info.plist 의 ATS 예외: NSAllowsArbitraryLoads(전체 평문 허용, iOS 10+ 에서 무시되는 조합이면 low),
    웹 콘텐츠·미디어 예외, 예외 도메인의 평문 허용·낮은 최소 TLS 버전.
    줄 번호는 plist 키를 문서 순서대로 이어 찾는다(선형, plistlib 은 dict 순서를 파일 순서대로 보존).
    결과는 줄과 상관없이 키 경로(package 자리)로 구분한다 — 바이너리·한 줄짜리 plist 에서도 도메인마다 id 가 다르다."""
    out = []
    for rel, full in ctx.files(lambda rel, name: name.lower().endswith("info.plist")):
        data, text = _load_plist(ctx, rel, full)
        if not isinstance(data, dict):
            continue
        ats = data.get("NSAppTransportSecurity")
        if not isinstance(ats, dict):
            continue
        cur = _LineCursor(text)
        cur.find("<key>NSAppTransportSecurity</key>") if text else None

        def add(rid, sev, line, keypath, title, evidence, hint, cwe):
            out.append(ctx.finding("ios-ats", rid, sev, "mobile", rel, line, title, evidence=evidence, fix_hint=hint,
                                   references=[cwe], package=f"ATS:{keypath}"))

        overrides = [k for k in ATS_OVERRIDES if k in ats]
        for key, value in ats.items():
            line = cur.find(_plist_key(key)) if text else None
            if key == "NSAllowsArbitraryLoads" and value is True:
                if overrides:
                    add("ios.ats-arbitrary-loads", "low", line, key,
                        "NSAllowsArbitraryLoads = true — iOS 9 이하에서만 적용됩니다", f"NSAllowsArbitraryLoads = true (iOS 10 이상에서는 {overrides[0]} 가 있어 무시)",
                        "최소 배포 버전이 iOS 10 이상이면 키를 지우세요.", "CWE-319")
                else:
                    add("ios.ats-arbitrary-loads", "high", line, key,
                        "ATS 가 꺼져 있습니다 (NSAllowsArbitraryLoads = true) — 모든 도메인에 평문 HTTP 를 허용합니다",
                        "NSAppTransportSecurity.NSAllowsArbitraryLoads = true",
                        "키를 지우고, 평문이 꼭 필요한 도메인만 NSExceptionDomains 로 좁히세요.", "CWE-319")
            elif key in ("NSAllowsArbitraryLoadsInWebContent", "NSAllowsArbitraryLoadsForMedia") and value is True:
                add("ios.ats-arbitrary-loads-partial", "medium", line, key, f"ATS 부분 예외가 켜져 있습니다 ({key} = true)",
                    f"NSAppTransportSecurity.{key} = true", "필요한 경우가 아니면 지우세요.", "CWE-319")
            elif key == "NSExceptionDomains" and isinstance(value, dict):
                for domain, conf in value.items():
                    if len(out) > MAX_RESULTS_PER_CHECK:
                        break
                    dline = cur.find(_plist_key(domain)) if text else None
                    if not isinstance(conf, dict):
                        continue
                    d = _ats_domain_id(domain)
                    sub = " (하위 도메인 포함)" if conf.get("NSIncludesSubdomains") is True else ""
                    if any(conf.get(k) is True for k in ("NSExceptionAllowsInsecureHTTPLoads",
                                                         "NSTemporaryExceptionAllowsInsecureHTTPLoads",
                                                         "NSThirdPartyExceptionAllowsInsecureHTTPLoads")):
                        add("ios.ats-insecure-http-exception", "medium", dline, f"NSExceptionDomains/{d}",
                            "ATS 예외 도메인에 평문 HTTP 를 허용합니다", f"도메인 {d}{sub}: 평문 HTTP 허용",
                            "서버를 HTTPS 로 옮기고 예외를 지우세요.", "CWE-319")
                    tls = (conf.get("NSExceptionMinimumTLSVersion") or conf.get("NSTemporaryExceptionMinimumTLSVersion")
                           or conf.get("NSThirdPartyExceptionMinimumTLSVersion"))
                    if isinstance(tls, str) and tls in WEAK_TLS:
                        add("ios.ats-weak-tls", "medium", dline, f"NSExceptionDomains/{d}/tls",
                            "ATS 예외 도메인의 최소 TLS 버전이 낮습니다", f"도메인 {d}{sub}: 최소 TLS {tls}",
                            "TLS 1.2 이상만 허용하세요.", "CWE-326")
    return out


# 조건부 설정 [sdk=…][arch=…][config=…] 는 여러 개 붙을 수 있다 (구분자 [ 가 있어 백트래킹이 늘지 않는다)
XCCONFIG_ASSIGN = re.compile(r"[ \t]*([A-Za-z_][A-Za-z0-9_]*)(?:\[[^\]\n]{0,100}\]){0,4}[ \t]*=(.*)")
# 안쪽 참조부터 지운다 — $(A_$(B)) 같은 중첩은 여러 번 돌려 바깥까지 지운다 (구간에 $ 가 없어 시작점마다 즉시 끝난다)
XCCONFIG_REF = re.compile(r"\$[({][^(){}$\n]{0,200}[)}]")
XCCONFIG_REF_ROUNDS = 4


def check_ios_xcconfig_secret(ctx):
    """I1 보강 — *.xcconfig 의 비밀 키 평문 값 (빌드 설정은 Info.plist·바이너리로 들어간다). 값은 기록하지 않는다.
    xcconfig 에서 // 는 어디서든 주석이다 (그래서 URL 을 https:/$()/ 로 쓴다). $(…)·${…} 참조만 있는 값은 제외."""
    out = []
    for rel, full in ctx.files(lambda rel, name: name.endswith(".xcconfig")):
        text = ctx.read(full)
        if text is None:
            continue
        for n, line in _lines(text):
            if line.lstrip().startswith(("//", "#include")):
                continue
            m = XCCONFIG_ASSIGN.fullmatch(line)
            if not m or not is_secret_key(m.group(1)):
                continue
            key, value = m.group(1), m.group(2).split("//", 1)[0].strip()
            plain, had_ref = value, False
            for _ in range(XCCONFIG_REF_ROUNDS):                # $(inherited) realSecret → realSecret
                plain, n_sub = XCCONFIG_REF.subn("", plain)
                if not n_sub:
                    break
                had_ref = True
            plain = plain.strip()
            # 다 못 지운 참조(깊은 중첩·200자 초과)와 참조 바로 뒤 경로($(SRCROOT)/Secrets/x)는 평문 비밀이 아니다
            if "$(" in plain or "${" in plain or (had_ref and plain[:1] in ("/", ")", "}")):
                continue
            ok, _note = _secret_value(plain, key)
            if ok:
                out.append(ctx.finding(
                    "ios-xcconfig-secret", "ios.xcconfig-secret", "high", "secret", rel, n,
                    "xcconfig 의 비밀 키에 평문 값이 있습니다 — 앱 번들(Info.plist·바이너리)에 들어갈 수 있습니다",
                    evidence=f"키: {key[:60]} — 값은 리포트에 남기지 않습니다",
                    fix_hint="저장소 밖 xcconfig(gitignore)나 CI 시크릿으로 옮기고, 앱에 넣어야 하는 키라면 서버를 거쳐 발급받으세요.",
                    references=["CWE-798"]))
    return out


# ---------------------------------------------------------------------------
# react-native
# ---------------------------------------------------------------------------
def _has_npm_dependency(ctx, dep):
    """프로파일 루트의 package.json 이 dep 을 dependencies·devDependencies 에 둔다."""
    want = "package.json" if ctx.root == "." else f"{ctx.root}/package.json"
    for rel, full in ctx.files(lambda rel, name: rel == want):
        text = ctx.read(full)
        try:
            data = json.loads(text) if text else {}
        except ValueError:
            return False
        if not isinstance(data, dict):
            return False
        return any(isinstance(data.get(k), dict) and dep in data[k] for k in ("dependencies", "devDependencies"))
    return False


def check_rn_config_env_secret(ctx):
    """R1 — react-native-config 는 접두사와 무관하게 .env 의 모든 변수를 JS 번들·네이티브 리소스에 넣는다.
    비밀 이름 변수를 보고한다 (공개 접두사 변수는 env-public-secret 이 보고하므로 제외, 값은 결과에 넣지 않는다).
    react-native-config 는 프로젝트 루트(package.json 폴더)의 .env*(ENVFILE 도 루트 기준)만 읽으므로 하위 폴더
    (server/.env·e2e/.env.test)는 보지 않는다 (PR #28 2차 리뷰 N4)."""
    out = []
    if not _has_npm_dependency(ctx, "react-native-config"):
        return out
    root_dir = "" if ctx.root == "." else ctx.root
    for rel, full in ctx.files(lambda rel, name: _is_env_name(name) and os.path.dirname(rel) == root_dir):
        text = ctx.read(full)
        if text is None:
            continue
        for n, line in _lines(text):
            m = ENV_ASSIGN.match(line)
            if not m or public_env_severity(m.group(1)):
                continue
            name = m.group(1)
            sev = "high" if _ANY_SECRET_NAME.match(name) else "medium" if _ANY_KEY_NAME.match(name) else None
            if not sev:
                continue
            out.append(ctx.finding(
                "rn-config-env-secret", "react-native.config-env-secret", sev, "secret" if sev == "high" else "config", rel, n,
                "react-native-config 가 .env 변수를 앱 번들에 넣습니다 — 비밀 이름 변수가 앱에서 그대로 꺼내집니다",
                evidence=f"변수 이름: {name} (값은 리포트에 남기지 않습니다)",
                fix_hint="비밀 값은 앱 .env 에서 빼고 서버를 거쳐 받으세요. 이미 배포됐다면 키를 폐기(rotate)하세요.",
                references=["CWE-312"]))
    return out


# ---------------------------------------------------------------------------
# flutter
# ---------------------------------------------------------------------------
ENV_EXAMPLE_PARTS = {"example", "sample", "template", "dist", "defaults"}   # .env.example·.env.local.dist·.env.defaults


def _is_env_name(base):
    """.env·.env.* 이면서 예시 파일(이름 조각에 example·sample·template·dist·defaults)이 아닌 것."""
    if base != ".env" and not base.startswith(".env."):
        return False
    return not ENV_EXAMPLE_PARTS.intersection(base[1:].lower().split("."))


def _pubspec_assets(text):
    """pubspec.yaml 최상위 flutter.assets 의 항목 — (줄 번호, 경로).
    블록 목록(`- .env`, 같은 들여쓰기 포함), 흐름 문법(`assets: [.env, a/]`, 여러 줄 포함),
    Flutter 3.19+ 매핑 항목(`- path: .env` · `- {path: .env, flavors: [x]}` · `- flavors: [x]` 다음 줄 `path: .env`)을 읽는다.
    여러 줄 흐름 문법은 괄호 깊이를 세어 깊이 0 의 `]` 에서 끝낸다 (PR #28 2차 리뷰 N7)."""
    out = []
    in_flutter, assets_indent, item_indent, flow, flow_line, depth = False, None, None, None, None, 0

    def flow_depth(v, d):
        quote = None
        for c in v:
            if quote:
                if c == quote:
                    quote = None
            elif c in "'\"":
                quote = c
            elif c in "[{":
                d += 1
            elif c in "]}":
                d -= 1
        return d

    def from_item(n, rest):
        if rest.startswith("{"):
            e = _flow_entry(rest)
            path = e.get("path", e.get("short"))
        else:
            kv = _kv(rest)
            if kv and kv[0] == "path":
                path = kv[1]
            elif kv and "/" not in kv[0] and "." not in kv[0]:
                path = None            # flavors: 같은 매핑의 다른 키
            else:
                path = _unquote(rest)
        if path:
            out.append((n, path))

    for n, raw in _lines(text):
        line = strip_yaml_comment(raw)
        st = line.strip()
        if flow is not None:                       # 여러 줄 흐름 문법 assets: [ … ]
            flow += " " + st
            depth = flow_depth(st, depth)
            if depth <= 0 or len(flow) > MAX_LINE:
                for x in _split_flow(flow.split("[", 1)[-1].rsplit("]", 1)[0]):
                    if x:
                        from_item(flow_line, x)
                flow = None
            continue
        if not st:
            continue
        ind = _indent(line)
        if ind == 0:
            in_flutter, assets_indent, item_indent = st == "flutter:", None, None
            continue
        if not in_flutter:
            continue
        if assets_indent is not None:
            if st.startswith("-") and ind >= assets_indent:
                if item_indent is None:
                    item_indent = ind
                if ind == item_indent:            # 더 깊은 - 는 항목 안의 목록(flavors 등)
                    from_item(n, st[1:].strip())
                continue
            if ind > assets_indent:
                if item_indent is not None and ind > item_indent:     # 매핑 항목의 다음 줄 path: (flavors 가 앞)
                    kv = _kv(st)
                    if kv and kv[0] == "path" and kv[1]:
                        out.append((n, kv[1]))
                continue
            assets_indent, item_indent = None, None
        kv = _kv(st)
        if not kv or kv[0] != "assets":
            continue
        if kv[1].startswith("["):
            flow, flow_line, depth = kv[1], n, flow_depth(kv[1], 0)
            if depth <= 0:
                for x in _split_flow(kv[1][1:].rsplit("]", 1)[0]):
                    if x:
                        from_item(n, x)
                flow = None
        elif not kv[1]:
            assets_indent = ind
    return out


def check_flutter_env_asset(ctx):
    """F1 — pubspec.yaml 의 flutter.assets 에 .env 가 들어 있어 앱 번들에 그대로 포함된다.
    디렉터리 항목(`- assets/env/`)은 flutter_tools 가 그 폴더 바로 아래 파일을 숨김 파일까지 모두 넣으므로
    (하위 폴더는 넣지 않음) 그 폴더에 .env 가 있으면 함께 보고한다."""
    out, env_files = [], None
    for rel, full in ctx.files(lambda rel, name: name == "pubspec.yaml"):
        text = ctx.read(full)
        if text is None:
            continue
        base_dir = os.path.dirname(rel)
        for n, item in _pubspec_assets(text):
            if item.endswith("/"):
                if env_files is None:
                    env_files = [r for r, _ in ctx.files(lambda r, name: _is_env_name(name))]
                d = os.path.normpath(os.path.join(base_dir, item))
                d = "" if d == "." else d                  # - ./ 는 pubspec 폴더(루트면 "") — N7
                hits = [r for r in env_files if os.path.dirname(r) == d]
                where = [f"flutter.assets 디렉터리 {item[:100]} 안의 {os.path.basename(r)}" for r in hits]
            else:
                where = [f"flutter.assets 항목: {item[:120]}"] if _is_env_name(item.rsplit("/", 1)[-1]) else []
            for ev in where:
                out.append(ctx.finding(
                    "flutter-env-asset", "flutter.env-asset", "high", "secret", rel, n,
                    ".env 파일을 asset 으로 번들합니다 — 앱 패키지에서 누구나 꺼낼 수 있습니다",
                    evidence=ev,
                    fix_hint="비밀 값은 앱에 넣지 말고 서버를 거쳐 받으세요. 공개 설정만 --dart-define 등으로 넣고, 그 값도 바이너리에 평문으로 남는다고 가정하세요.",
                    references=["CWE-312"]))
    return out


BUILD_SCRIPT = re.compile(r"(^|/)(\.github/workflows/[^/]+\.ya?ml|\.circleci/config\.ya?ml|codemagic\.ya?ml|bitrise\.ya?ml|"
                          r"\.gitlab-ci\.ya?ml|azure-pipelines\.ya?ml|bitbucket-pipelines\.ya?ml|melos\.ya?ml|"
                          r"Jenkinsfile|Makefile|[^/]+\.sh|fastlane/Fastfile)$")
# 명령은 _build_commands 가 공백을 한 칸으로 정규화한 상태 — 공백 수량자를 두지 않는다
FLUTTER_BUILD = re.compile(r"\bflutter build (apk|appbundle|ipa|ios-framework|ios)(?![\w-])")
YAML_FOLD = re.compile(r">[1-9+-]{0,2}")
YAML_BLOCK = re.compile(r"[>|][1-9+-]{0,2}")
BUILD_YAML_KEY = re.compile(r"[\w.\-]+:(?: |$)")
NOT_RUN = ("echo", "printf")


def _strip_slash_comment(v):
    """Groovy(Jenkinsfile) 줄 주석 — 따옴표 밖, 줄 처음이나 공백 뒤의 `//` 부터 지운다 (http:// 는 유지). 선형 스캔."""
    quote = None
    for k, c in enumerate(v):
        if quote:
            if c == quote:
                quote = None
        elif c in "'\"":
            quote = c
        elif c == "/" and v.startswith("//", k) and (k == 0 or v[k - 1] in " \t"):
            return v[:k].rstrip()
    return v


def _yaml_plain(st):
    """YAML 줄(`- …`·`key: …`·`- key: …`)의 (키, 값이 plain 스칼라인가). 키·목록 항목이 아니면 (None, False)."""
    dash = st == "-" or st.startswith("- ")
    rest = st[2:].lstrip() if dash else st
    m = BUILD_YAML_KEY.match(rest)
    if not m and not dash:
        return None, False
    key = rest[:m.end()].rstrip().rstrip(":") if m else None
    value = rest[m.end():].strip() if m else rest
    return key, bool(value) and value[0] not in "'\"|>[{&*!"


def _build_commands(text, yaml=False, slash_comments=False):
    """(시작 줄 번호, 명령) — 주석을 지우고, 줄 끝 `\\` 이음과 YAML 접힘 블록(`run: >`)을 한 명령으로 합친다.
    합친 길이는 MAX_LINE 에서 끊는다. 공백은 한 칸으로 정규화한다. 리터럴 블록(`|`)은 줄마다 명령이다.
    yaml 이면 plain 여러 줄 스칼라(`- run: flutter build apk` 다음 줄에 더 깊게 들여쓴 `--obfuscate`)를 한 명령으로 합치고
    `name:` 값은 명령으로 보지 않는다(`name: >`·`name: |` 블록 본문도 버린다, 3차 리뷰 S2). slash_comments 면 `//` 주석도
    지운다 (PR #28 2차 리뷰 N5)."""
    out, buf, size, start, fold = [], [], 0, None, None
    plain, discard, skip = None, False, None

    def flush():
        nonlocal buf, size, start
        if buf:
            out.append((start, " ".join(" ".join(buf).split())))
        buf, size, start = [], 0, None

    def add(n, st):
        nonlocal size, start
        if start is None:
            start = n
        buf.append(st)
        size += len(st) + 1
        if size > MAX_LINE:
            flush()

    for n, raw in _lines(text):
        line = strip_yaml_comment(_strip_slash_comment(raw) if slash_comments else raw)
        st = line.strip()
        if skip is not None:
            if not st or _indent(line) > skip:
                continue
            skip = None
        if plain is not None:
            if st and _indent(line) > plain and not (st == "-" or st.startswith("- ")) and not BUILD_YAML_KEY.match(st):
                if not discard:
                    add(n, st[:-1] if st.endswith("\\") else st)
                continue
            flush()
            plain, discard = None, False
        if fold is not None:
            if not st:
                flush()                   # 빈 줄 = 접힘 블록의 문단 구분
                continue
            if _indent(line) > fold:
                add(n, st[:-1] if st.endswith("\\") else st)
                continue
            flush()
            fold = None
        if not st:
            flush()
            continue
        words = st.split()
        if yaml and words[-2:-1] == ["name:"] and len(words) <= 3 and (len(words) == 2 or words[0] == "-") \
                and YAML_BLOCK.fullmatch(words[-1]):
            flush()
            skip = line.index("name:")    # 키 열 — 본문은 이보다 깊고, `- name: >` 의 형제 키(run:)는 같은 열 (4차 리뷰 N1)
            continue
        if len(words) >= 2 and YAML_FOLD.fullmatch(words[-1]) and (words[-2].endswith(":") or words[-2] == "-"):
            flush()
            fold = _indent(line)
            continue
        key, is_plain = _yaml_plain(st) if yaml and not buf else (None, False)
        if key == "name":
            flush()
            plain, discard = (_indent(line), True) if is_plain else (None, False)
            continue
        cont = st.endswith("\\")
        add(n, st[:-1] if cont else st)
        if is_plain and not cont:
            plain = _indent(line)
        elif not cont:
            flush()
    flush()
    return out


def _shell_segments(cmd):
    """따옴표 밖의 ; | & 로 명령을 나눈다 (선형 스캔)."""
    segs, begin, quote = [], 0, None
    for k, c in enumerate(cmd):
        if quote:
            if c == quote:
                quote = None
        elif c in "'\"":
            quote = c
        elif c in ";|&":
            segs.append(cmd[begin:k])
            begin = k + 1
    segs.append(cmd[begin:])
    return segs


def check_flutter_build_obfuscate(ctx):
    """F3 — CI·빌드 스크립트의 릴리스 flutter build 에 --obfuscate 가 없다 (빌드 명령이 없으면 판단하지 않는다).
    echo·printf 로 출력만 하는 문구와, 플래그를 변수($(FLAGS)·${FLAGS}·$FLAGS)로 넘기는 명령은 판단을 보류한다."""
    out = []
    for rel, full in ctx.files(lambda rel, name: bool(BUILD_SCRIPT.search(rel))):
        text = ctx.read(full)
        if text is None:
            continue
        for n, cmd in _build_commands(text, yaml=rel.endswith((".yml", ".yaml")),
                                      slash_comments=rel.rsplit("/", 1)[-1] == "Jenkinsfile"):
            for seg in _shell_segments(cmd):
                m = FLUTTER_BUILD.search(seg)
                if not m or any(w.strip("'\"(") in NOT_RUN for w in seg[:m.start()].split()):
                    continue
                flags = [f.strip("'\"") for f in seg[m.end():].split()]
                if (any(f.startswith(("--obfuscate", "$")) for f in flags)
                        or "--debug" in flags or "--profile" in flags):
                    continue
                out.append(ctx.finding(
                    "flutter-build-obfuscate", "flutter.build-no-obfuscate", "medium", "mobile", rel, n,
                    "릴리스 flutter build 에 --obfuscate 가 없습니다 — Dart 코드의 클래스·함수 이름이 그대로 남습니다",
                    evidence=f"flutter build {m.group(1)} (--obfuscate 없음)",
                    fix_hint="--obfuscate --split-debug-info=<경로> 를 붙이고 심볼 파일은 크래시 분석용으로 따로 보관하세요.",
                    references=["CWE-656"]))
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
    "android-manifest": check_android_manifest,
    "android-gradle-release": check_android_gradle_release,
    "android-properties-secret": check_android_properties_secret,
    "ios-ats": check_ios_ats,
    "ios-xcconfig-secret": check_ios_xcconfig_secret,
    "rn-config-env-secret": check_rn_config_env_secret,
    "flutter-env-asset": check_flutter_env_asset,
    "flutter-build-obfuscate": check_flutter_build_obfuscate,
}
# 저장소 전체를 보는 검사 — 인프라 설정처럼 프로파일 하위 경로가 아니라 저장소 루트에 있는 경우가 많은 것.
# 감지된 프로파일 중 하나라도 이 검사를 쓰면 대상 루트 기준으로 한 번만 실행한다.
REPO_WIDE = {"compose", "flutter-build-obfuscate"}   # CI 설정은 저장소 루트에 있다


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
