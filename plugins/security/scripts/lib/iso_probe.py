"""scan-web 격리 확인 — ZAP 컨테이너 안에서 스캔 직전에 실행한다 (V1 N2, docs/security/04 보안/네트워크 격리.md).

scan-web.sh 가 이 파일 내용을 `python3 -I -c "<내용>" <대상 host> <대상 port>` 로 넘긴다 (ZAP 컨테이너에는 마운트가 없다).
표준 라이브러리만 쓰고, 마지막 줄에 `isolated` 또는 `LEAK <항목…>` 을 쓴다. 하나라도 걸리면 scan-web.sh 는 대상에 요청하지 않는다.

  dns:<이름>        인터넷 이름이 풀린다 (internal 네트워크의 DNS 가 밖으로 샌다, 예: CVE-2024-29018)
  ip                인터넷 IP 로 직접 연결된다
  target-direct     프록시를 거치지 않고 대상 host:port 로 직접 연결된다 (host-gateway 경로가 internal 을 우회, PR #34 리뷰 W4)
  proxy-env:<키>    프록시 환경변수가 남아 있다 (compose-web.yml 이 비우므로 무언가 다시 넣은 것)
  proxy-allows-outside / proxy-status:<코드> / proxy-unreachable
                    egress-proxy 가 허용목록 밖(.invalid)을 403 으로 막지 않는다 — 필터가 적용되지 않았다
"""

import os
import socket
import sys
import urllib.error
import urllib.request

PROXY = "http://egress-proxy:8888"
PROBE_URL = "http://dwk-isolation-probe.invalid/"   # web_target.ISOLATION_PROBE_HOST — 차단 목록에서는 뺀다
INTERNET_NAMES = ("example.com", "www.zaproxy.org")
INTERNET_IP = ("1.1.1.1", 443)


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
              if k.lower() in ("http_proxy", "https_proxy", "ftp_proxy", "all_proxy") and v.strip()]
    if proxy_open is None:
        proxy_open = urllib.request.build_opener(urllib.request.ProxyHandler({"http": PROXY})).open
    try:
        proxy_open(PROBE_URL, timeout=6)
        leaks.append("proxy-allows-outside")
    except urllib.error.HTTPError as e:
        e.close()
        if e.code != 403:
            leaks.append("proxy-status:%d" % e.code)
    except OSError:
        leaks.append("proxy-unreachable")
    return leaks


if __name__ == "__main__":
    socket.setdefaulttimeout(4)
    found = probe(sys.argv[1], sys.argv[2])
    print("isolated" if not found else "LEAK " + " ".join(found))
