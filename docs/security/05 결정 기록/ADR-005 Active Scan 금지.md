---
title: ADR-005 Active Scan 금지
tags: [adr]
status: accepted
date: 2026-11-05
---

# ADR-005 Active Scan 금지

상위: [[보안 툴킷]]

## 결정
웹 점검은 **passive만** 허용한다. ZAP active scan, full scan, Nuclei 공격성 템플릿(`intrusive/dos/fuzz/bruteforce`)은 스크립트 수준에서 차단한다.

## 근거
- 스테이징이라도 데이터 손상·계정 잠금·외부 알림(메일 발송 등) 유발 가능 → [[위협 모델#T6 잘못된 대상 점검 / 파괴적 점검]]
- 인젝션류 취약점은 [[Semgrep]] 정적분석으로 소스 단계에서 우선 탐지
- 사이드 프로젝트 규모에서 비용 대비 효과 낮음

## 재검토 조건
- 일회용 스테이징(매번 재생성되는 DB)이 갖춰졌을 때, 별도 ADR로 제한적 active scan 허용 검토
