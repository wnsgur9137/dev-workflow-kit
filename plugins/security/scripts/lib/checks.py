#!/usr/bin/env python3
"""스택별 커스텀 검사 — Semgrep 규칙으로 표현하기 어려운 파일 단위 점검 (설정 파일·lockfile 메타데이터 등).

docs/security/07 스택별 설계/스택 프로파일 개요.md 의 `checks`. 표준 라이브러리만 사용한다.

사용:
  checks.py --target DIR --profiles-tsv FILE [--profile-dir DIR] --out FILE

- 호스트에서 대상 저장소 파일을 **읽기만** 한다. 네트워크·외부 명령·대상 코드 실행 없음.
- 대상은 신뢰하지 않는 입력이다: 심볼릭 링크는 따라가지 않고, 대상 폴더 밖 경로는 읽지 않으며, 파일 크기를 제한한다.
- 시크릿 값은 결과에 넣지 않는다 (키 이름·위치만). 결과 문자열은 normalize.py 가 다시 정제한다.
- 출력: {"results": [<finding>...], "errors": ["..."]}
  finding: check · rule_id · severity · category · profile · file · line · title · evidence · fix_hint · references · package
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import profiles as _profiles  # noqa: E402

MAX_FILE = 1_000_000
MAX_RESULTS_PER_CHECK = 200


class Ctx:
    """검사 하나가 보는 범위: 대상 루트, 프로파일 하위 경로, 제외 하위 경로, 프로파일 제외 패턴."""

    def __init__(self, target, profile, root, excluded, exclude_paths):
        self.target = os.path.realpath(target)
        self.profile = profile
        self.root = root
        self.excluded = excluded
        self.exclude_paths = exclude_paths

    def files(self, pred):
        """프로파일 하위 경로 안의 일반 파일 중 pred(rel, name) 가 참인 것 — (rel, 절대 경로)."""
        base = self.target if self.root == "." else os.path.join(self.target, self.root)
        if not os.path.isdir(base) or os.path.islink(base):
            return
        for dirpath, dirs, files in os.walk(base):
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
                if os.path.islink(full) or not os.path.isfile(full):
                    continue
                if any(_profiles.glob_match(x, rel) or _profiles.glob_match(x, rel + "/") for x in self.exclude_paths):
                    continue
                if pred(rel, fn):
                    yield rel, full

    def read(self, full):
        """대상 폴더 안의 파일만, 크기 제한 안에서 읽는다 (넘으면 None)."""
        real = os.path.realpath(full)
        if not real.startswith(self.target + os.sep):
            return None
        try:
            if os.path.getsize(real) > MAX_FILE:
                return None
            with open(real, encoding="utf-8", errors="replace") as f:
                return f.read()
        except OSError:
            return None

    def finding(self, check, rule_id, severity, category, rel, line, title, evidence="", fix_hint="",
                references=None, package=None):
        return {"check": check, "rule_id": rule_id, "severity": severity, "category": category,
                "profile": self.profile, "file": rel, "line": line, "title": title, "evidence": evidence,
                "fix_hint": fix_hint, "references": references or [], "package": package}


def _line_of(text, pos):
    return text.count("\n", 0, pos) + 1


# ---------------------------------------------------------------------------
# web
# ---------------------------------------------------------------------------
PUBLIC_PREFIX = r"(?:NEXT_PUBLIC_|VITE_|REACT_APP_|NUXT_PUBLIC_|GATSBY_|PUBLIC_|EXPO_PUBLIC_)"
# 비밀을 뜻하는 이름 — 공개용으로 설계된 키(publishable·anon·site key 등)는 뺀다
SECRET_WORD = re.compile(r"(SECRET|PRIVATE|PASSWORD|PASSWD|TOKEN|SERVICE_ROLE|CREDENTIAL)", re.I)
PUBLIC_BY_DESIGN = re.compile(r"(PUBLISHABLE|ANON|PUBLIC_KEY|SITE_KEY|SITEKEY|MEASUREMENT_ID)", re.I)
ENV_LINE = re.compile(rf"^\s*(?:export\s+)?({PUBLIC_PREFIX}[A-Za-z0-9_]*)\s*=", re.M)


def _is_env_file(rel, name):
    return name == ".env" or name.startswith(".env.")


def check_env_public_secret(ctx):
    """W2 — .env* 의 공개 접두사 변수 이름이 비밀 값을 가리킨다 (값은 읽어도 결과에 넣지 않는다)."""
    out = []
    for rel, full in ctx.files(_is_env_file):
        text = ctx.read(full)
        if text is None:
            continue
        for m in ENV_LINE.finditer(text):
            key = m.group(1)
            if not SECRET_WORD.search(key) or PUBLIC_BY_DESIGN.search(key):
                continue
            out.append(ctx.finding(
                "env-public-secret", "web.env-public-secret", "high", "secret", rel, _line_of(text, m.start()),
                "공개 접두사 환경 변수에 비밀 값 이름 — 클라이언트 번들에 그대로 포함됩니다",
                evidence=f"변수 이름: {key} (값은 리포트에 남기지 않습니다)",
                fix_hint="공개 접두사를 빼고 서버에서만 읽도록 옮기세요. 이미 배포됐다면 키를 폐기(rotate)하세요.",
                references=["CWE-200"]))
    return out


ROUTE_FILE = re.compile(r"(^|/)(app/api/.+/route|pages/api/.+)\.(js|jsx|ts|tsx|mjs|cjs)$")
ROUTE_EXPORT = re.compile(
    r"export\s+(?:async\s+)?function\s+(GET|POST|PUT|PATCH|DELETE)\b|export\s+default\s+(?:async\s+)?function\b"
    r"|export\s+const\s+(GET|POST|PUT|PATCH|DELETE)\s*=")
AUTH_CALL = re.compile(
    r"\b(auth|getServerSession|getSession|getToken|currentUser|getAuth|auth\.protect|requireAuth|withAuth|"
    r"verifyToken|verifySession|validateRequest|getUser|clerkClient|getKindeServerSession|withApiAuthRequired|"
    r"getIronSession|unstable_getServerSession)\s*\(")
MIDDLEWARE = re.compile(r"(^|/)(src/)?middleware\.(js|ts|mjs)$")


def check_next_unauth_route(ctx):
    """W4 — Next.js API 라우트 핸들러 파일에 인증 확인 호출이 보이지 않는다 (휴리스틱, medium).

    Semgrep 은 "이 호출이 없다"를 함수 이름 목록으로 표현하기 어려워 파일 단위로 검사한다.
    middleware 가 /api 를 덮으면(matcher 에 api 가 있거나 matcher 가 없으면) 인증을 그쪽에서 할 수 있으므로 low 로 낮춘다.
    """
    middleware_covers_api = False
    for _rel, full in ctx.files(lambda rel, name: bool(MIDDLEWARE.search(rel))):
        text = ctx.read(full) or ""
        if "matcher" not in text or re.search(r"['\"`][^'\"`]*api", text):
            middleware_covers_api = True
    out = []
    for rel, full in ctx.files(lambda rel, name: bool(ROUTE_FILE.search(rel))):
        text = ctx.read(full)
        if text is None:
            continue
        m = ROUTE_EXPORT.search(text)
        if not m or AUTH_CALL.search(text):
            continue
        sev = "low" if middleware_covers_api else "medium"
        out.append(ctx.finding(
            "next-unauth-route", "web.next-unauth-route", sev, "sast", rel, _line_of(text, m.start()),
            "API 라우트에서 인증 확인 호출이 보이지 않습니다 (휴리스틱)",
            evidence=("middleware 가 /api 를 덮을 수 있어 낮춤 — middleware 의 인증 여부를 확인하세요"
                      if middleware_covers_api else "핸들러 파일에 auth()·getServerSession() 등의 호출이 없습니다"),
            fix_hint="공개 엔드포인트가 아니라면 핸들러 첫 부분에서 세션을 확인하고 없으면 401 을 돌려주세요.",
            references=["CWE-306"]))
    return out


NEXT_CONFIG = re.compile(r"(^|/)next\.config\.(js|mjs|cjs|ts|mts)$")
WILDCARD_HOST = re.compile(r"hostname\s*:\s*['\"`](\*\*?|\*\.\*\*?)['\"`]")
WILDCARD_DOMAINS = re.compile(r"domains\s*:\s*\[[^\]]*['\"`]\*\*?['\"`]")
BROWSER_MAPS = re.compile(r"productionBrowserSourceMaps\s*:\s*true")
HEADERS_FN = re.compile(r"\bheaders\s*(\(|:)")
SECURITY_HEADERS = ("Content-Security-Policy", "Strict-Transport-Security", "X-Frame-Options", "X-Content-Type-Options")


def check_next_config(ctx):
    """W6 — next.config.* 의 보안 헤더 미설정, 원격 이미지 호스트 와일드카드, 프로덕션 브라우저 소스맵."""
    out = []
    for rel, full in ctx.files(lambda rel, name: bool(NEXT_CONFIG.search(rel))):
        text = ctx.read(full)
        if text is None:
            continue
        has_headers = bool(HEADERS_FN.search(text))
        missing = [h for h in SECURITY_HEADERS if h.lower() not in text.lower()]
        if not has_headers:
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
        for rx, rid, title, hint in (
            (WILDCARD_HOST, "web.next-config-wildcard-remote-image",
             "images.remotePatterns 의 hostname 이 와일드카드입니다",
             "이미지 최적화 엔드포인트가 임의 호스트 이미지를 받아 와 SSRF·비용 남용에 쓰일 수 있습니다. 허용 호스트를 명시하세요."),
            (WILDCARD_DOMAINS, "web.next-config-wildcard-remote-image",
             "images.domains 에 와일드카드가 있습니다", "허용 호스트를 명시하세요."),
        ):
            m = rx.search(text)
            if m:
                out.append(ctx.finding("next-config", rid, "medium", "config", rel, _line_of(text, m.start()),
                                       title, evidence="와일드카드 호스트", fix_hint=hint, references=["CWE-918"]))
        m = BROWSER_MAPS.search(text)
        if m:
            out.append(ctx.finding(
                "next-config", "web.next-config-browser-sourcemaps", "medium", "config", rel, _line_of(text, m.start()),
                "프로덕션 브라우저 소스맵이 켜져 있습니다 (productionBrowserSourceMaps: true)",
                evidence="원본 소스가 /_next/static/**/*.map 으로 공개됩니다",
                fix_hint="productionBrowserSourceMaps 를 끄거나, 소스맵을 오류 수집 서비스에만 올리세요.",
                references=["CWE-540"]))
    return out


def check_npm_install_scripts(ctx):
    """W8 — 설치 스크립트(postinstall 등)가 있는 의존성 목록 (package-lock v2+ hasInstallScript, pnpm requiresBuild).

    취약점이 아니라 공급망 검토 대상 목록이다 (info). 패키지 이름은 lockfile 에서 온 신뢰하지 않는 문자열이라
    제목은 고정 문장으로 두고 이름은 location.package 에만 넣는다.
    """
    out = []

    def add(rel, name, version, line):
        if len(out) < MAX_RESULTS_PER_CHECK:
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
        except ValueError:
            continue
        pkgs = data.get("packages") if isinstance(data, dict) else None
        if not isinstance(pkgs, dict):
            continue
        for key, meta in sorted(pkgs.items()):
            if not isinstance(meta, dict) or meta.get("hasInstallScript") is not True or not key:
                continue
            name = key.rsplit("node_modules/", 1)[-1]
            pos = text.find(json.dumps(key))
            add(rel, name, meta.get("version", "?"), _line_of(text, pos) if pos >= 0 else None)
    pnpm_pkg = re.compile(r"^  /?('?)(@?[^@\s'(]+)@([^:\s'(]+)[^:]*\1:\s*$")
    for rel, full in ctx.files(lambda rel, name: name == "pnpm-lock.yaml"):
        text = ctx.read(full)
        if text is None:
            continue
        current = None
        for n, line in enumerate(text.splitlines(), 1):
            m = pnpm_pkg.match(line)
            if m:
                current = (m.group(2), m.group(3), n)
            elif current and re.match(r"^    requiresBuild:\s*true\s*$", line):
                add(rel, current[0], current[1], current[2])
                current = None
    return out


# ---------------------------------------------------------------------------
# 등록부
# ---------------------------------------------------------------------------
CHECKS = {
    "env-public-secret": check_env_public_secret,
    "next-unauth-route": check_next_unauth_route,
    "next-config": check_next_config,
    "npm-install-scripts": check_npm_install_scripts,
}


def run(target, detected, profile_defs):
    results, errors = [], []
    for name, root, excluded in detected:
        p = profile_defs.get(name) or {}
        ctx = Ctx(target, name, root, excluded, p.get("exclude_paths") or [])
        for check in p.get("checks") or []:
            fn = CHECKS.get(check)
            if fn is None:
                errors.append(f"{name}: 알 수 없는 검사 '{check}'")
                continue
            try:
                results.extend(fn(ctx)[:MAX_RESULTS_PER_CHECK])
            except Exception as ex:  # noqa: BLE001 — 대상 파일은 신뢰하지 않는 입력이다
                errors.append(f"{name}/{check}: 검사 실패 — {type(ex).__name__}")
    return {"results": results, "errors": errors}


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
    report = run(args.target, _read_detected(args.profiles_tsv), defs)
    fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
