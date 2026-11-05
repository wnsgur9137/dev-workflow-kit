---
title: ADR-009 Docker 호환 런타임 필수
tags: [adr]
status: accepted
date: 2026-11-05
---

# ADR-009 Docker 호환 런타임 필수

상위: [[보안 툴킷]] · 상세: [[Docker 런타임]]

## 맥락
security 플러그인은 도구 6개를 모두 컨테이너로 실행한다([[ADR-004 네트워크 격리 강제]]). 그런데 사용자 안내(README, 요구사항)에 Docker가 필요하다는 내용이 없었고, 요구사항 "무료"([[요구사항]] NFR-1)와 관련해 Docker Desktop의 라이선스 조건도 다루지 않았다.

## 결정
1. security 플러그인은 **Docker 호환 런타임(Docker CLI + Compose v2 + dockerd 엔진)을 필수**로 한다.
2. 무료 기본값으로 **Colima**를 안내하고, Docker Desktop·Rancher Desktop·OrbStack도 지원한다. Podman은 검증 전까지 미지원.
3. Docker 없이 도구를 직접 설치하는 모드는 두지 않는다.
4. 모든 스캔은 사전 점검(D1~D6)을 통과해야 컨테이너를 띄운다.

## 근거
- 외부 전송 차단을 네트워크 차원에서 보장하는 유일한 수단이 컨테이너 격리
- MobSF는 Docker 없이 실행하기 어려움
- Docker Desktop은 일정 규모 이상 조직의 업무 사용이 유료 → "무료" 조건을 지키려면 무료 런타임을 기본값으로 안내해야 함

## 결과 / 트레이드오프
- 설치 단계가 하나 늘어남 (런타임 설치·실행)
- VM 메모리 8GB 이상 권장(MobSF 사용 시)
- 런타임별 차이(로컬 호스트 주소 등)를 문서화하고 사전 점검으로 흡수

## 재검토 조건
- Podman의 compose·internal 네트워크 동작을 검증하면 지원 목록에 추가
