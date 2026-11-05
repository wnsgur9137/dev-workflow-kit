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
- 이미지: `zaproxy/zap-stable` (digest 고정)
- 스크립트: `zap-baseline.py` 만 허용. `zap-full-scan.py`, `zap-api-scan.py`의 active 모드는 스크립트에서 차단
- 네트워크: `web-internal`(internal) + 업스트림 프록시 `egress-proxy`

```bash
docker compose run --rm zap \
  zap-baseline.py -t "$TARGET_URL" -J /zap/wrk/zap.json -m 3 \
  -z "-config network.connection.httpProxy.enabled=true ..."
```

## 외부 통신
| 항목 | 이 설계 |
|---|---|
| 대상 접속 | 프록시 경유, 허용목록 도메인만 |
| 업데이트·애드온 확인, call-home | 설정으로 끄기 + 프록시에서 차단 |

## 크롤링 범위 제한
- `-m` (spider 분) 제한
- 대상 외 도메인으로의 링크는 프록시가 차단 → 의도치 않은 제3자 접속 방지

## Severity 매핑
ZAP risk `High/Medium/Low/Informational` → `high/medium/low/info`

> [!warning] 검증 필요
> - ZAP 업스트림 프록시 설정 키 정확한 이름
> - call-home/업데이트 확인 비활성 옵션
> - 로컬 개발 서버(호스트의 localhost) 접근 방법: `host.docker.internal`을 프록시 허용목록에 넣는 방식이 안전한지
