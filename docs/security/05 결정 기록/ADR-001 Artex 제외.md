---
title: ADR-001 Artex 제외
tags: [adr]
status: accepted
date: 2026-11-05
---

# ADR-001 Artex 제외

상위: [[보안 툴킷]]

## 맥락
초기 후보는 MobSF + Artex(`jiwoochris/artex-global`). Artex는 LLM 멀티에이전트 **자율 침투테스트** 프레임워크(Go + Next.js UI + PostgreSQL, AGPL-3.0, Autumn-27/ARTEX 포크)다.

## 결정
Artex를 도입하지 않는다. 웹 점검은 [[OWASP ZAP]] baseline(+선택 [[Nuclei]])으로 대체한다.

## 근거
1. **유료**: 에이전트 루프에 `ANTHROPIC_API_KEY` 또는 `OPENAI_API_KEY` 필요 (README). Claude 구독으로 대체 불가 → [[요구사항]] NFR-1 위반
2. **실제 공격 수행**: 인젝션 → 자격증명 획득 → 권한 상승을 자율 실행 → NFR-4 위반
3. **프롬프트 인젝션 증폭**: 대상 응답을 읽고 다음 공격을 결정하는 구조 + 셸/Kali 권한 → [[위협 모델#T5 프롬프트 인젝션]]
4. **상시 공격 표면**: 관리자 웹 UI, DB, MITM 프록시 → [[위협 모델#T2 툴킷 서비스 노출]]
5. **유지보수 불확실**: 포크, README상 핵심 SDK(norma) 저장소 접근 불가
6. **모바일 분석 없음**: MobSF와 보완 관계가 아님

## 결과
- 자율 익스플로잇 능력은 포기. 사이드 프로젝트 주요 위험(키 유출, 취약 의존성, 설정 오류)은 대체 조합으로 커버
- 재검토 조건: 격리 VM + 전용 스테이징이 준비되고 실제 침투테스트가 필요해질 때

## 미확인
- `mcphttp/` 디렉터리가 외부 에이전트(Claude Code)에서 도구만 호출 가능한 구조인지, 로컬 LLM 지원 여부 — 코드 미검토
