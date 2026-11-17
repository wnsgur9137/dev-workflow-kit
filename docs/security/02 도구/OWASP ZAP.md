---
title: OWASP ZAP
tags: [tool/dast]
status: draft
created: 2026-11-05
license: Apache-2.0
network: web-internal + egress-proxy (허용목록)
---

# OWASP ZAP (baseline scan)

상위: [[보안 툴킷]] · 워크플로: [[scan-web]] · 관련: [[ADR-005 Active Scan 금지]]

## 역할
대상 웹을 크롤링하고 **수동(passive) 규칙만** 적용. 공격 요청을 보내지 않는다.
탐지 예: 보안 헤더 누락(CSP, HSTS, X-Frame-Options), 쿠키 속성(Secure/HttpOnly/SameSite), 서버 버전·스택트레이스 노출, 혼합 콘텐츠.

## 실행 방식
- 이미지: `zaproxy/zap-stable` 2.17.0 (digest 고정, `images.lock`)
- 스크립트: `zap-baseline.py` 만 실행한다. 명령은 `docker/compose-web.yml` 에 고정돼 있고 `scan-web.sh` 는 대상 URL·시간만 환경변수로 넘긴다 — `zap-full-scan.py`·`zap-api-scan.py`·`--hook`·`-u`(원격 설정) 같은 인자를 넣을 경로가 없다
- 네트워크: `web-internal`(internal) + 업스트림 프록시 `egress-proxy`
- 하드닝: 읽기 전용 루트, `cap_drop: ALL`, `no-new-privileges`, 메모리 3GB·pids 1024 상한, 작업 폴더·홈은 tmpfs. 리포트는 stdout 으로만 내보낸다 (호스트 쓰기 마운트 없음)

```bash
zap-baseline.py -t "$DWK_TARGET_URL" -J zap.json -m 3 -T 10 -I -s \
  -z "-silent -config network.connection.httpProxy.enabled=true \
      -config network.connection.httpProxy.host=egress-proxy -config network.connection.httpProxy.port=8888"
```

## 외부 통신
| 항목 | 이 설계 |
|---|---|
| 대상 접속 | 프록시 경유, 허용목록 도메인만 |
| 업데이트·애드온 확인, call-home | `-silent` 로 끄기 + 프록시에서 차단 (막히면 차단 목록에 드러남) |

## 크롤링 범위 제한
- `-m` (spider 분) 제한
- 대상 외 도메인으로의 링크는 프록시가 차단 → 의도치 않은 제3자 접속 방지

## Severity 매핑
ZAP risk `High/Medium/Low/Informational` → `high/medium/low/info`

> [!check] 확인됨 (P3, ZAP 2.17.0 · Colima, 2026-11-17)
> - 업스트림 프록시: `-config network.connection.httpProxy.enabled=true`·`.host=`·`.port=` (network 애드온). 이 설정으로 크롤링한 요청이 모두 프록시 로그에 나온다
> - **`-silent` 가 없으면 `zap-baseline.py` 가 `-addonupdate -addoninstall pscanrulesBeta` 를 실행해 외부로 나간다** (`zap-baseline.py` 435~437행). `-silent` 면 이 단계를 건너뛰고 업데이트 확인·call-home 도 하지 않는다. 그 대신 이미지에 든 애드온만 쓴다 — 수동 규칙은 release(`pscanrules-release-77`)만 있고 beta 규칙은 없다
> - 호스트 uid 로는 시작하지 못한다 — Java 가 passwd 의 홈을 써서 `/zap/?/.ZAP` 을 만들려다 실패한다. 이미지 사용자 `zap`(1000)으로 돌리고 홈·작업 폴더를 tmpfs 로 준다 (호스트에 쓰지 않으므로 uid 를 맞출 필요가 없다)
> - 범위 밖 링크(`http://example.com/…`)는 스파이더가 요청하지 않는다 — 프록시 로그에도 나오지 않는다
> - 로컬 개발 서버는 `host.docker.internal:<포트>` 를 허용목록에 넣는다. 이 이름은 egress-proxy 에서만 풀리고, 프록시는 그 출처(scheme+host+port) 하나만 연다 → [[Docker 런타임#로컬 서버 점검 시 호스트 주소]]
