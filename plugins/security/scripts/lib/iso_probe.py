"""scan-web 격리 확인 — ZAP 컨테이너 안에서 스캔 직전에 실행한다 (V1 N2, docs/security/04 보안/네트워크 격리.md).

scan-web.sh 가 이 파일 내용을 `python3 -I -c "<내용>" <대상 host> <대상 port> <시작 URL>` 로 넘긴다 (ZAP 컨테이너에는 마운트가 없다).
표준 라이브러리만 쓰고, 마지막 줄에 결과 하나를 쓴다:
  LEAK <항목…>          격리가 깨졌다 — 대상에 요청하지 않는다
  UNREACHABLE <사유>    격리는 정상인데 프록시를 거쳐 시작 URL 에 닿지 않는다 — 스캔하지 않는다
                        사유: proxy-<5xx>·timeout·tunnel-<코드>·<예외 이름>·probe-error:<이름>
                        (서버가 안 떠 있거나 포트가 틀리면 ZAP 이 프록시의 500 오류 페이지를 대상으로 점검해 거짓 결과를 낸다,
                         PR #34 2차 리뷰 W-B)
  isolated              격리 정상 · 대상 도달

  dns:<이름>        인터넷 이름이 풀린다 (internal 네트워크의 DNS 가 밖으로 샌다, 예: CVE-2024-29018)
  ip                인터넷 IP 로 직접 연결된다
  target-direct     프록시를 거치지 않고 대상 host:port 로 직접 연결된다 (host-gateway 경로가 internal 을 우회, PR #34 리뷰 W4)
  proxy-env:<키>    프록시 환경변수(no_proxy 포함 — 도달 확인이 프록시를 건너뛴다)가 남아 있다 (compose-web.yml 이 비우므로 무언가 다시 넣은 것)
  proxy-allows-outside / proxy-status:<코드> / proxy-unreachable
                    egress-proxy 가 허용목록 밖(.invalid)을 403 으로 막지 않는다 — 필터가 적용되지 않았다
"""

import http.client
import os
import re
import socket
import sys
import urllib.error
import urllib.request

PROXY = "http://egress-proxy:8888"
PROBE_URL = "http://dwk-isolation-probe.invalid/"   # web_target.ISOLATION_PROBE_HOST — 차단 목록에서는 뺀다
INTERNET_NAMES = ("example.com", "www.zaproxy.org")
INTERNET_IP = ("1.1.1.1", 443)
# 개발 서버 첫 요청 컴파일·콜드 스타트를 기다린다. egress-proxy 의 Timeout(60) 보다 짧게 둬 늘 이쪽이 먼저 끝나게 한다 —
# 같으면 프록시가 먼저 끊을 때 '시간 초과' 대신 '접속하지 못했습니다'로 갈린다 (3차 리뷰 R3-S3·4차 리뷰 R4-S2)
REACH_TIMEOUT = 55


def probe(target_host, target_port, resolve=socket.getaddrinfo, connect=socket.create_connection,
          proxy_open=None, environ=None):
    environ = os.environ if environ is None else environ
    leaks = []
    for h in INTERNET_NAMES:
        try:
            resolve(h, 443)
            leaks.append("dns:" + h)
        except OSError:
            pass
    for addr, tag in ((INTERNET_IP, "ip"), ((target_host, int(target_port)), "target-direct")):
        try:
            connect(addr, timeout=4).close()
            leaks.append(tag)
        except OSError:
            pass
    leaks += ["proxy-env:" + k for k, v in environ.items()
              if k.lower() in ("http_proxy", "https_proxy", "ftp_proxy", "all_proxy", "no_proxy") and v.strip()]
    if proxy_open is None:
        proxy_open = _opener(urllib.request.ProxyHandler({"http": PROXY})).open
    try:
        resp = proxy_open(PROBE_URL, timeout=6)
        leaks.append("proxy-allows-outside")
    except urllib.error.HTTPError as e:
        e.close()
        if e.code != 403:
            leaks.append("proxy-status:%d" % e.code)
    except OSError:
        leaks.append("proxy-unreachable")
    else:
        resp.close()
    return leaks


def _opener(*handlers):
    """필요한 핸들러만 넣는다 — 리다이렉트·ftp·file 핸들러가 없다 (PR #34 3차 리뷰 R3-W1·R3-S1).
    대상이 보낸 3xx 는 따라가지 않고 HTTPError 로 올라온다. 리다이렉트를 따라가면 https·IdP·ftp 로 새 연결을 열어
    정상 대상을 '닿지 않음'으로 오진하거나 프록시를 거치지 않는 접속을 시도한다."""
    od = urllib.request.OpenerDirector()
    for h in handlers + (urllib.request.HTTPHandler(), urllib.request.HTTPDefaultErrorHandler(),
                         urllib.request.HTTPErrorProcessor()):
        od.add_handler(h)
    return od


def _reason(e):
    """닿지 않은 사유 — urllib 은 연결 거부·이름 풀이·터널 실패·TLS·시간 초과를 모두 URLError 로 감싸므로 안쪽 원인을 본다 (R3-S3)."""
    r = getattr(e, "reason", e)
    if isinstance(r, (TimeoutError, socket.timeout)) or "timed out" in str(r):
        return "timeout"
    m = re.search(r"Tunnel connection failed: (\d{3})", str(r))
    if m:
        return "tunnel-" + m.group(1)
    return type(r).__name__ if isinstance(r, BaseException) else type(e).__name__


def reach(url, proxy_open=None, proxy=PROXY, timeout=REACH_TIMEOUT):
    """프록시를 거쳐 시작 URL 에 GET 한 번 — 리다이렉트는 따라가지 않고 첫 응답만 본다.
    대상이 보낸 응답이면(3xx 포함 상태 코드 무관) None, 닿지 않으면 사유.
    tinyproxy 는 대상에 접속하지 못하면 'Server: tinyproxy' 인 5xx 를 돌려준다 (1.11.3 실측: 500 Unable to connect)."""
    if proxy_open is None:
        # 도달 여부만 본다 — 스테이징의 자체 서명 인증서로 거짓 실패하지 않게 검증하지 않는다 (ZAP 도 인증서 오류를 무시하고 점검한다)
        import ssl
        proxy_open = _opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}),
                             urllib.request.HTTPSHandler(context=ssl._create_unverified_context())).open
    try:
        resp = proxy_open(url, timeout=timeout)
        if resp is None:   # 처리할 핸들러가 없는 스킴 — 여기까지 오지 않는다(web_target 이 http·https 만 받는다)
            return "unsupported-scheme"
        resp.close()
        return None
    except urllib.error.HTTPError as e:
        server = (e.headers.get("Server") if e.headers else "") or ""
        e.close()
        if e.code >= 500 and server.strip().lower().startswith("tinyproxy"):
            return "proxy-%d" % e.code
        return None
    except (OSError, http.client.HTTPException) as e:
        # HTTPException: 대상이 HTTP 가 아닌 응답(BadStatusLine·LineTooLong)을 보냄 — 격리 문제가 아니다 (R3-S5)
        return _reason(e)


if __name__ == "__main__":
    socket.setdefaulttimeout(4)
    found = probe(sys.argv[1], sys.argv[2])
    if found:
        print("LEAK " + " ".join(found))
    else:
        try:
            why = reach(sys.argv[3]) if len(sys.argv) > 3 else None
        except Exception as e:  # 예상 못 한 오류도 '격리 확인 실패'가 아니라 '닿지 않음'으로 (R3-S5)
            why = "probe-error:" + type(e).__name__
        print("isolated" if why is None else "UNREACHABLE " + why)
