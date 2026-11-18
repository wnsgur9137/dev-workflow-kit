"""scan-app 격리 확인 — MobSF 컨테이너 안에서 앱을 올리기 전에 실행한다 (V1 N1, docs/security/02 도구/MobSF.md).

scan-app.sh 가 이 파일 내용을 `python3 -I -c "<내용>"` 로 넘긴다 (MobSF 컨테이너에는 툴킷 마운트가 없다).
표준 라이브러리만 쓰고, 마지막 줄에 결과 하나를 쓴다:
  isolated              격리 정상
  LEAK <항목…>          격리가 깨졌다 — 앱을 올리지 않는다
    dns:<이름>          인터넷 이름이 풀린다 (internal 네트워크의 외부 DNS 를 dockerd 가 대신 보내던 엔진, CVE-2024-29018)
    ip                  인터넷 IP 로 직접 연결된다
    proxy-env:<키>      프록시 환경변수가 남아 있다 — MobSF 의 requests(trust_env)가 internal 네트워크에서 닿는 프록시로
                        나갈 수 있다. compose.yml 이 이 변수들을 빈 값으로 덮어쓰므로 값이 있으면 무언가 다시 넣은 것이다
"""

import os
import socket
import sys

INTERNET_NAMES = ("example.com", "play.google.com")
INTERNET_IP = ("1.1.1.1", 443)
# compose.yml 의 mobsf·mobsf-client 가 빈 값으로 덮어쓰는 변수와 같아야 한다 (tests/test_scan_app.py 가 고정, PR #32 5차 N1)
PROXY_ENV_KEYS = ("http_proxy", "https_proxy", "ftp_proxy", "all_proxy")


def probe(resolve=socket.getaddrinfo, connect=socket.create_connection, environ=None):
    environ = os.environ if environ is None else environ
    leaks = []
    for h in INTERNET_NAMES:
        try:
            resolve(h, 443)
            leaks.append("dns:" + h)
        except OSError:
            pass
    try:
        connect(INTERNET_IP, timeout=3).close()
        leaks.append("ip")
    except OSError:
        pass
    leaks += ["proxy-env:" + k for k, v in environ.items() if k.lower() in PROXY_ENV_KEYS and str(v).strip()]
    return leaks


if __name__ == "__main__":
    socket.setdefaulttimeout(3)
    try:
        found = probe()
    except Exception as e:  # noqa: BLE001 — 예상 못 한 오류는 격리를 확인하지 못한 것이다 (fail-closed)
        found = ["probe-error:" + type(e).__name__]
    print("isolated" if not found else "LEAK " + " ".join(found))
    sys.stdout.flush()
