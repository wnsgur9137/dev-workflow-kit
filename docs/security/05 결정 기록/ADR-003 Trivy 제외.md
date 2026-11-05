---
title: ADR-003 Trivy 제외
tags: [adr]
status: accepted
date: 2026-11-05
---

# ADR-003 Trivy 제외

상위: [[보안 툴킷]]

## 맥락
Trivy는 의존성·컨테이너·IaC를 한 번에 스캔하는 무료 도구다. 다만 2026년 3월경 Trivy 배포본과 관련 GitHub Action이 침해되어 자격증명 탈취 코드가 배포됐다는 보고가 있었다.

> [!warning] 검증 필요
> 사고의 정확한 범위·버전·조치 현황은 Aqua Security 공식 공지로 확인할 것. 이 ADR은 기억에 근거해 작성됨.

## 결정
의존성 스캔은 [[OSV-Scanner]]로 대체하고, Trivy는 기본 구성에서 제외한다.

## 근거
- 필요 기능(SCA)은 OSV-Scanner로 충분
- 보안 도구는 높은 권한으로 소스·자격증명에 접근하므로 공급망 이력이 중요
- 선택지를 줄여 관리 대상 축소

## 재검토 조건
- 컨테이너 이미지·IaC(Terraform, Dockerfile) 스캔이 필요해질 때 → 그때도 [[업데이트 절차]]의 지연 도입·digest 고정 적용
