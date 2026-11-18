#!/usr/bin/env python3
"""/security:scan-web 대상 허용목록 검사 · egress-proxy(tinyproxy) 필터 생성 · 프록시 차단 로그 해석.

표준 라이브러리만 쓴다. docs/security/03 워크플로/scan-web.md · docs/security/04 보안/네트워크 격리.md

사용:
  web_target.py check <허용목록 파일> <URL>
      허용목록과 URL 의 scheme+host+port 를 정확히 비교한다 (와일드카드 없음). 통과하면 stdout 에
        url\t<정규화한 URL>
        origin\t<scheme://host:port>
        filter\t<tinyproxy ERE 한 줄>     (여러 줄일 수 있다)
      를 쓰고 0 으로 끝난다. 거부하면 stderr 에 사유를 쓰고 1 로 끝난다.
  web_target.py denied <프록시 로그 파일>
      tinyproxy 로그의 'Proxying refused on filtered url "..."' 줄에서 막은 요청을 모아 JSON 으로 쓴다.

원칙
  - 허용목록은 사용자가 직접 관리한다 (Claude 는 권한으로 수정 금지 — examples/settings.permissions.json).
    그룹·다른 사용자가 쓸 수 있는 파일이면 거부한다.
  - '# prod' 처럼 prod 라고 표시한 줄은 허용목록에 있어도 거부한다 (ADR-005, 운영 대상 점검 금지).
  - 프록시에는 허용목록 전체가 아니라 **이번 대상의 출처(scheme+host+port) 하나만** 연다.
  - 프록시 로그의 URL 은 스캐너가 대상 페이지의 링크를 따라 만든 값이다 — 신뢰하지 않는 데이터로 다룬다.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import stat
import sys
import urllib.parse

DEFAULT_PORTS = {"http": 80, "https": 443}
URL_MAX = 2000
# RFC 1123 호스트 이름 (점으로 구분한 라벨) — IPv4 주소와 그 16진 변형 표기(0x7f000001)도 이 모양에 맞으므로
# _check_host 가 숫자·16진 라벨만으로 된 이름을 따로 거른다
_HOST_RE = re.compile(r"(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*")
_ENTRY_RE = re.compile(r"(https?)://([^/:\s]+)(?::(\d{1,5}))?/?")
_PROD_RE = re.compile(r"(?i)(?<![a-z0-9])prod(?:uction)?(?![a-z0-9])")
# 컨테이너 안에서 localhost 는 컨테이너 자신이다 — 호스트의 개발 서버는 호스트 주소로 접근해야 한다
_LOOPBACK_NAMES = ("localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback")
_HOST_HINT = ("호스트에서 띄운 개발 서버는 컨테이너에서 host.docker.internal(Docker Desktop·OrbStack·Colima) 또는 "
              "host.lima.internal(Colima) 로 접근합니다. 예: http://host.docker.internal:3000")


class TargetError(Exception):
    pass


def _check_host(host: str, where: str) -> str:
    h = host.lower().rstrip(".") if host else ""
    if not h:
        raise TargetError(f"{where}: 호스트가 없습니다")
    if h.startswith("[") or ":" in h:
        raise TargetError(f"{where}: IPv6 주소는 지원하지 않습니다 ({host}) — 호스트 이름이나 IPv4 주소를 쓰세요")
    if not _HOST_RE.fullmatch(h):
        raise TargetError(f"{where}: 호스트 이름 형식이 아닙니다 ({host})")
    loop = h in _LOOPBACK_NAMES or h.endswith(".localhost")
    try:
        ip = ipaddress.ip_address(h)
        loop = loop or ip.is_loopback or ip.is_unspecified
    except ValueError:
        # 10진·8진·16진(0x…) 라벨만으로 된 이름은 inet_aton 이 IPv4 로 해석한다 (0x7f.1 = 127.0.0.1) — 받지 않는다
        if all(re.fullmatch(r"[0-9]+|0x[0-9a-f]*", lab) for lab in h.split(".")):
            raise TargetError(f"{where}: IPv4 주소 형식이 아닙니다 ({host}) — 점 네 개로 된 10진 표기만 받습니다") from None
    if loop:
        raise TargetError(f"{where}: {host} 는 컨테이너 자신을 가리킵니다. {_HOST_HINT}")
    return h


def _check_port(port: str | None, scheme: str, where: str) -> int:
    if port is None or port == "":
        return DEFAULT_PORTS[scheme]
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        raise TargetError(f"{where}: 포트가 1~65535 범위가 아닙니다 ({port})")
    return int(port)


def parse_allowlist(path: str):
    """허용목록 → [(scheme, host, port, prod여부, 줄 번호)]. 형식이 틀린 줄이 하나라도 있으면 전체를 거부한다
    (사용자의 의도를 추측해 일부만 받아들이지 않는다)."""
    try:
        st = os.stat(path)
    except FileNotFoundError:
        raise TargetError(
            f"허용목록이 없습니다: {path}\n"
            "  점검할 대상(직접 소유·운영하는 개발 서버나 스테이징)을 한 줄에 하나씩 직접 적으세요. 예:\n"
            "    http://host.docker.internal:3000\n"
            "    https://staging.my-app.example\n"
            "  파일은 사용자만 쓸 수 있게 두세요 (chmod 600). Claude 는 이 파일을 고칠 수 없습니다.") from None
    if not stat.S_ISREG(st.st_mode):
        raise TargetError(f"허용목록이 일반 파일이 아닙니다: {path}")
    if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise TargetError(f"허용목록을 그룹·다른 사용자가 쓸 수 있습니다: {path} — chmod 600 으로 고친 뒤 다시 실행하세요")
    if hasattr(os, "getuid") and st.st_uid != os.getuid():
        raise TargetError(f"허용목록의 소유자가 현재 사용자가 아닙니다: {path}")
    entries, errors = [], []
    with open(path, encoding="utf-8", errors="replace") as f:
        for no, line in enumerate(f, 1):
            body, _, comment = line.partition("#")
            body = body.strip()
            if not body:
                continue
            m = _ENTRY_RE.fullmatch(body)
            if not m:
                errors.append(f"{no}번째 줄: scheme://host[:port] 형식이 아닙니다 (경로·와일드카드·사용자 정보 불가)")
                continue
            scheme = m.group(1)
            try:
                host = _check_host(m.group(2), f"{no}번째 줄")
                port = _check_port(m.group(3), scheme, f"{no}번째 줄")
            except TargetError as e:
                errors.append(str(e))
                continue
            entries.append((scheme, host, port, bool(_PROD_RE.search(comment)), no))
    if errors:
        raise TargetError("허용목록 형식 오류 — 고친 뒤 다시 실행하세요:\n  " + "\n  ".join(errors[:20]))
    if not entries:
        raise TargetError(f"허용목록에 대상이 없습니다: {path}")
    return entries


def parse_target(url: str):
    """점검 URL → (scheme, host, port, 정규화한 URL). 사용자 정보·제어문자·공백·조각은 받지 않는다."""
    if not url or len(url) > URL_MAX:
        raise TargetError(f"URL 이 비었거나 너무 깁니다 (최대 {URL_MAX}자)")
    if re.search(r"[\x00-\x20\x7f\\]", url) or not url.isascii():
        raise TargetError("URL 에 공백·제어문자·역슬래시·ASCII 밖 문자가 있습니다 (퍼센트 인코딩해서 넘기세요)")
    try:
        u = urllib.parse.urlsplit(url)
        port_raw = u.netloc.rpartition(":")[2] if ":" in u.netloc.rpartition("]")[2] else None
    except ValueError as e:
        raise TargetError(f"URL 을 해석할 수 없습니다: {e}") from None
    scheme = u.scheme.lower()
    if scheme not in DEFAULT_PORTS:
        raise TargetError(f"http·https URL 만 점검합니다 (받은 scheme: {u.scheme or '없음'})")
    if "@" in u.netloc:
        raise TargetError("URL 에 사용자 정보(user@host)를 넣을 수 없습니다")
    if u.netloc.count(":") > 1:
        raise TargetError(f"URL 의 호스트·포트를 해석할 수 없습니다 ({u.netloc}) — ':' 는 포트 앞에 하나만 씁니다")
    host = _check_host(u.hostname or "", "URL")
    port = _check_port(port_raw, scheme, "URL")
    path = u.path or "/"
    norm = f"{scheme}://{host}:{port}{path}" + (f"?{u.query}" if u.query else "")
    return scheme, host, port, norm


def match(entries, scheme, host, port):
    for e in entries:
        if (e[0], e[1], e[2]) == (scheme, host, port):
            return e
    return None


def display_url(norm: str) -> str:
    """로그·리포트에 남기는 점검 URL — 질의 문자열 값·조각을 가린다 (ZAP 에는 원문을 넘긴다, PR #34 리뷰 W1)."""
    return _redact_url(norm)


def prod_like_host(host: str) -> bool:
    """호스트 이름의 라벨이 prod·production 이면 운영 대상일 수 있다 (경고만, PR #34 리뷰 S7)."""
    return any(lab in ("prod", "production") or lab.startswith(("prod-", "production-")) or lab.endswith(("-prod", "-production"))
               for lab in host.split("."))


def proxy_filters(scheme: str, host: str, port: int):
    """tinyproxy(FilterType ere, FilterURLs On) 필터 — 요청 URL 전체에 맞춘다.
    http 는 'http://host[:port]/…', https 는 CONNECT 의 'host:port' 로 들어온다 (tinyproxy 1.11.3 실측).
    대소문자는 tinyproxy 기본값(FilterCaseSensitive No)으로 무시된다.
    http 는 출처 바로 뒤에 '/' 나 끝만 허용한다 — tinyproxy 는 첫 '/' 앞을 호스트 부분으로 보고 그 안의 '@' 앞을 버리므로,
    'http://허용:3000?@다른곳:3000/' 처럼 '?' 를 허용하면 필터는 통과하고 '다른곳'으로 접속한다 (PR #34 리뷰 C1, 1.11.3 실측)."""
    # 호스트 이름은 [a-z0-9.-] 만 남는다(_check_host). POSIX ERE 에서 '\-' 같은 이스케이프는 정의되지 않으므로 '.' 만 이스케이프한다
    h = host.replace(".", "\\.")
    if scheme == "https":
        return [f"^{h}:{port}$"]
    p = f"(:{port})?" if port == DEFAULT_PORTS[scheme] else f":{port}"
    return [f"^http://{h}{p}(/|$)"]


# 텍스트 안의 URL — 따옴표·꺾쇠·괄호·공백으로 나눈 토큰마다 본다 (정규식 되돌림 없이 길이에 선형, 길이 상한 없음).
# 상한을 두면 2000자 넘는 URL 의 꼬리(뒤쪽 질의값)가 URL 로 다시 잡히지 않고 남는다 (PR #34 3차 리뷰 R3-W2)
_TOKEN = re.compile(r"[^\s\"'<>()`]+")
_URL_START = re.compile(r"(?i)(?:https?:)?//")
# '/' 없는 상대 URL 의 경로 매개변수·조각 값('cb;jsessionid=…', 'cb#access_token=…', 4차 리뷰 R4-S4) — 문자 클래스가 구분자를 빼서 선형
_PARAM_HINT = re.compile(r";[^=;]*=|#[^#]*=")
# 쿠키 헤더 이름 — 값은 _mask_cookies 가 한 글자씩 읽는다(정규식 반복 그룹은 'cookie:' 반복에서 이차 시간, 5차 리뷰 R5-S1).
# 단어 중간('xcookie:')은 잡지 않되 'X-Session-Cookie:' 와 이스케이프된 줄바꿈('\r\nSet-Cookie:') 뒤는 잡는다.
# 'Set-Cookie:' 안쪽 'Cookie:' 는 바깥 매치가 먼저 소비한다
_COOKIE_HDR = re.compile(r"(?i)(?:(?<!\w)|(?<=\\[rn]))(set-cookie|cookie):")
COOKIE_NAME_MAX = 256
# JSON 의 ASCII 유니코드 이스케이프('\u002f'·'\u0026'·'\u003d', R4-S4) — '\/' 와 같이 미리 푼다
_JSON_U = re.compile(r"\\u00([2-7][0-9a-fA-F])")   # 인쇄 가능한 ASCII 만 — 제어문자는 풀지 않는다 (R5 NITPICK)
DECODE_MAX = 2   # 인코딩 풀기 단계 — 두 번 인코딩된 중첩 URL 까지 (R4-S4)


def _redact_token(tok: str, depth: int = 0) -> str:
    if depth < DECODE_MAX and "%" in tok:
        # 인코딩된 중첩 URL('http%3A%2F%2Fh%2Fcb%3Fcode%3D…') — 풀어서 가릴 것이 있으면 푼 모양으로 가린다 (3차 리뷰 R3-S2)
        d = urllib.parse.unquote(tok)
        if d != tok:
            r = _redact_token(d, depth + 1)
            if r != d:
                return r
    m = _URL_START.search(tok)
    if m:
        pre = tok[:m.start()]
        # 앞부분이 상대 URL 이면('/authorize?code=…&redirect_uri=https://…') 뒤의 절대 URL 은 그 질의값이다 — 토큰 전체를 URL 로 본다
        # (4차 리뷰 R4-W1). 그렇지 않으면 앞부분(예: 'url=')은 그대로 둔다
        if "?" in pre or "#" in pre or ";" in pre:
            return _redact_url(tok)
        return pre + _redact_url(tok[m.start():])
    # 상대 URL: 질의가 있거나, 경로에 조각·경로 매개변수가 붙었다 ('cb?code=…', '../cb?…', '/cb;jsessionid=…', 'cb;jsessionid=…')
    if "?" in tok or ("/" in tok and ("#" in tok or ";" in tok)) or _PARAM_HINT.search(tok):
        return _redact_url(tok)
    return tok


def _cookie_pairs(t: str, i: int, first_only: bool):
    """t[i:] 의 'name=value; name=value' 를 읽어 가릴 값의 (시작, 끝) 목록과 읽은 끝 위치를 돌려준다 — 한 번 훑는다.
    공백은 이름·'='·';' 앞뒤에 허용, 값은 따옴표(또는 JSON 이스케이프 '\\"') 통째, 아니면 ';'·공백·이스케이프 줄바꿈·'\\"' 앞까지
    (5차 리뷰 R5-S2: 'a=1 ; b=…'·'sid=abc\\def; tok=…'·'a=\\"q\\"; tok=…')."""
    n, spans = len(t), []
    def skip(j):
        while j < n and t[j] in " \t":
            j += 1
        return j
    while True:
        j = skip(i)
        k = j
        while k < n and k - j <= COOKIE_NAME_MAX and t[k] not in "=; \t\r\n\\":
            k += 1
        if k - j > COOKIE_NAME_MAX:   # 이름이 아니다 — 'cookie:' 반복 같은 입력에서 길게 훑지 않는다 (R5-S1)
            return spans, i
        k = skip(k)
        if k >= n or t[k] != "=":
            return spans, i
        v = skip(k + 1)
        if t.startswith('"', v) or t.startswith('\\"', v):
            q = '"' if t[v] == '"' else '\\"'
            e = t.find(q, v + len(q))
            e = n if e < 0 else e + len(q)
        else:
            e = v
            while e < n and t[e] not in "; \t\r\n" and not (t[e] == "\\" and t[e + 1:e + 2] in ("r", "n", '"')):
                e += 1
        spans.append((v, e))
        i = skip(e)
        if first_only or i >= n or t[i] != ";":
            return spans, i
        i += 1


def _mask_cookies(t: str) -> str:
    """Cookie 는 모든 쌍, Set-Cookie 는 첫 쌍(뒤는 Path=/ 같은 속성)의 값을 가린다. 쌍 문법이 끝나면 멈춰 줄 나머지를 남긴다."""
    out, last, pos = [], 0, 0
    while True:
        m = _COOKIE_HDR.search(t, pos)
        if not m:
            break
        spans, pos = _cookie_pairs(t, m.end(), m.group(1).lower() == "set-cookie")
        pos = max(pos, m.end())
        for v, e in spans:
            out.append(t[last:v] + "[MASKED]")
            last = e
    out.append(t[last:])
    return "".join(out)


def redact_text(text: str) -> str:
    """로그·근거 같은 자유 텍스트 안의 URL 값과 쿠키 값을 가린다 (JSON 이스케이프 '\\/' 도 풀어서 본다)."""
    t = _JSON_U.sub(lambda m: chr(int(m.group(1), 16)), str(text).replace("\\/", "/"))
    # 쿠키를 먼저 가린다 — URL 가림이 먼저 'a=1;tok=' 를 바꾸면 따옴표 값이 쌍 문법에서 빠진다 (5차 리뷰 R5-S2)
    t = _mask_cookies(t)
    return _TOKEN.sub(lambda m: _redact_token(m.group(0)), t)


# ---------------------------------------------------------------------------
# 프록시 차단 로그
# ---------------------------------------------------------------------------
_REFUSED_RE = re.compile(r'Proxying refused on filtered url "([^"\n]{0,4000})"')
# scan-web.sh 의 격리 확인이 일부러 보내는 요청 — 차단 목록에서 뺀다
ISOLATION_PROBE_HOST = "dwk-isolation-probe.invalid"
DENIED_MAX = 50
URL_SHOW_MAX = 500


def _mask_params(text: str, sep: str) -> str:
    return sep.join(p.split("=", 1)[0] + ("=[MASKED]" if "=" in p else "") for p in text.split(sep))


def _redact_url(u: str) -> str:
    """URL 에서 토큰일 수 있는 부분을 가린다 — 사용자 정보, 질의 문자열 값, 조각(#…) 전체, 경로 매개변수(;jsessionid=…) 값.
    출처와 경로·매개변수 이름만 남긴다 (PR #34 리뷰 S2: 조각 뒤 '?' 를 질의로 오인하지 않게 조각을 먼저 자른다).
    스킴 상대(//host/…)·상대 경로(/cb?code=…, cb;jsessionid=…)도 받는다. 길이는 **가린 뒤** 표시용으로만 자른다 (3차 리뷰 R3-W2)."""
    u = re.sub(r"[\x00-\x1f\x7f]", "", u)
    # 사용자 정보는 출처 부분(첫 '/' 전)의 마지막 '@' 까지 가린다 — 인코딩 안 된 '@' 가 든 비밀번호도 (2차 리뷰 NITPICK)
    u = re.sub(r"(?:(?<=://)|(?<=^//))[^/\s]*@", "[MASKED]@", u)
    u, h, _frag = u.partition("#")
    base, q, query = u.partition("?")
    # '/' 로 나눈 조각마다 경로 매개변수 값을 가린다 — 절대·스킴 상대·상대 경로 모두 같은 규칙 (3차 리뷰 R3-S2: '//h/a;jsessionid=…').
    # 호스트 조각에는 ';' 가 들어갈 수 없으므로 출처는 그대로 남는다
    path = "/".join(_mask_params(seg, ";") if ";" in seg else seg for seg in base.split("/"))
    out = path + ("?" + _mask_params(query, "&") if q else "") + ("#[MASKED]" if h else "")
    return out if len(out) <= URL_SHOW_MAX else out[:URL_SHOW_MAX] + "…[TRUNCATED]"


def denied_requests(log_text: str):
    seen, out, total = set(), [], 0
    for m in _REFUSED_RE.finditer(log_text):
        u = m.group(1)
        if ISOLATION_PROBE_HOST in u.lower():
            continue
        total += 1
        r = _redact_url(u)
        if r in seen:
            continue
        seen.add(r)
        if len(out) < DENIED_MAX:
            out.append(r)
    return {"total": total, "unique": len(seen), "urls": out}


def main(argv) -> int:
    if len(argv) == 3 and argv[0] == "check":
        try:
            entries = parse_allowlist(argv[1])
            scheme, host, port, norm = parse_target(argv[2])
            e = match(entries, scheme, host, port)
            if e is None:
                raise TargetError(
                    f"허용목록에 없는 대상입니다: {scheme}://{host}:{port}\n"
                    f"  scheme·호스트·포트가 정확히 같은 줄이 있어야 합니다 (와일드카드 없음). 허용목록: {argv[1]}\n"
                    "  직접 소유·운영하는 대상이면 사용자가 그 파일에 직접 추가하세요.")
            if e[3]:
                raise TargetError(f"허용목록 {e[4]}번째 줄이 운영(prod) 대상으로 표시돼 있어 점검하지 않습니다: "
                                  f"{scheme}://{host}:{port} (ADR-005)")
        except TargetError as ex:
            print(str(ex), file=sys.stderr)
            return 1
        print(f"url\t{norm}")
        print(f"display\t{display_url(norm)}")
        print(f"origin\t{scheme}://{host}:{port}")
        if prod_like_host(host):
            print(f"warning\t호스트 이름({host})에 prod 가 들어 있습니다 — 운영 대상이 아닌지 확인하세요. 운영이면 허용목록에서 빼거나 '# prod' 로 표시하세요")
        for f in proxy_filters(scheme, host, port):
            print(f"filter\t{f}")
        return 0
    if len(argv) == 2 and argv[0] == "redact-file":
        # 진행 로그(raw/zap.log)를 제자리에서 가린다 — 실패 메모가 이 꼬리에서 만들어진다 (2차 리뷰 W-A·S-B)
        with open(argv[1], encoding="utf-8", errors="replace") as f:
            text = f.read()
        with open(argv[1], "w", encoding="utf-8") as f:
            f.write("\n".join(redact_text(line) for line in text.split("\n")))
        return 0
    if len(argv) == 2 and argv[0] == "denied":
        with open(argv[1], encoding="utf-8", errors="replace") as f:
            print(json.dumps(denied_requests(f.read()), ensure_ascii=False))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
