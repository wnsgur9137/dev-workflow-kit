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
# RFC 1123 호스트 이름 (점으로 구분한 라벨) — IPv4 주소도 이 모양에 맞는다
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
        if re.fullmatch(r"[0-9.]+", h):
            raise TargetError(f"{where}: IPv4 주소 형식이 아닙니다 ({host})") from None
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


def proxy_filters(scheme: str, host: str, port: int):
    """tinyproxy(FilterType ere, FilterURLs On) 필터 — 요청 URL 전체에 맞춘다.
    http 는 'http://host[:port]/…', https 는 CONNECT 의 'host:port' 로 들어온다 (tinyproxy 1.11.3 실측).
    대소문자는 tinyproxy 기본값(FilterCaseSensitive No)으로 무시된다."""
    # 호스트 이름은 [a-z0-9.-] 만 남는다(_check_host). POSIX ERE 에서 '\-' 같은 이스케이프는 정의되지 않으므로 '.' 만 이스케이프한다
    h = host.replace(".", "\\.")
    if scheme == "https":
        return [f"^{h}:{port}$"]
    p = f"(:{port})?" if port == DEFAULT_PORTS[scheme] else f":{port}"
    return [f"^http://{h}{p}([/?]|$)"]


# ---------------------------------------------------------------------------
# 프록시 차단 로그
# ---------------------------------------------------------------------------
_REFUSED_RE = re.compile(r'Proxying refused on filtered url "([^"\n]{0,4000})"')
# scan-web.sh 의 격리 확인이 일부러 보내는 요청 — 차단 목록에서 뺀다
ISOLATION_PROBE_HOST = "dwk-isolation-probe.invalid"
DENIED_MAX = 50


def _redact_url(u: str) -> str:
    """질의 문자열 값·사용자 정보는 토큰일 수 있으므로 지운다 (출처와 경로만 남긴다)."""
    u = re.sub(r"[\x00-\x1f\x7f]", "", u)[:500]
    u = re.sub(r"(?<=://)[^/@\s]*@", "[MASKED]@", u)
    base, q, query = u.partition("?")
    if q:
        base += "?" + "&".join(p.split("=", 1)[0] + ("=[MASKED]" if "=" in p else "") for p in query.split("&"))
    return base


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
        print(f"origin\t{scheme}://{host}:{port}")
        for f in proxy_filters(scheme, host, port):
            print(f"filter\t{f}")
        return 0
    if len(argv) == 2 and argv[0] == "denied":
        with open(argv[1], encoding="utf-8", errors="replace") as f:
            print(json.dumps(denied_requests(f.read()), ensure_ascii=False))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
