---
title: ADR-002 MCP 서버 대신 스킬
tags: [adr]
status: accepted
date: 2026-11-05
updated: 2026-11-05
---

# ADR-002 MCP 서버 대신 스킬

상위: [[보안 툴킷]]

## 맥락
Claude에서 스캐너를 호출하는 방법: (a) 도구별 MCP 서버, (b) Claude Code 스킬 + 셸 스크립트.

## 결정
**Claude Code 스킬(`SKILL.md`) + 셸 스크립트**를 사용하고, `dev-workflow-kit` 레포의 `security` 플러그인으로 배포한다. → [[ADR-006 플러그인 마켓플레이스 구조]]

## 근거
- 상시 실행 서버가 없음 → 공격 표면 감소 ([[설계 원칙]] 3)
- 서드파티 MCP 서버 코드에 대한 공급망 신뢰 불필요
- 스크립트는 사람이 읽고 감사하기 쉬움, Claude 없이도 실행 가능
- 권한 정책을 스크립트 단위로 걸 수 있음 → [[Claude Code 권한 정책]]
- 플러그인에 스킬·스크립트·Docker 파일을 함께 담아 배포 가능

## 트레이드오프
- **Claude Code CLI 전용** (확정). Claude 데스크톱/claude.ai에서는 사용 불가
- 구조화된 도구 스키마 대신 파일(`summary.md`) 기반 인터페이스
