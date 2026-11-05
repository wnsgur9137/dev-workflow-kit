---
title: Home
tags: [moc]
---

# Dev Workflow Kit 문서

`dev-workflow-kit` 저장소의 Obsidian vault입니다. Obsidian에서 **"Open folder as vault"로 이 `docs/` 폴더**를 열면 됩니다. 설치·빠른 시작은 저장소 [README](../README.md)를 보세요.

## 🔧 workflow 플러그인 (사용 중)

| 커맨드 | 문서 |
|---|---|
| `/workflow:commit` | [[commit]] |
| `/workflow:create-pr` | [[create-pr]] |
| `/workflow:pr-review` | [[pr-review]] |
| `/workflow:apply-review` | [[apply-review]] |
| `/workflow:pipeline` | [[pipeline]] |

- 설정·의존성: [[설정]] · 왜 GitHub MCP인가: [[GitHub MCP]] · 리뷰 기준·출력 형식: [[커스터마이징]]

## 🛡️ security 플러그인 (설계 단계)

로컬·네트워크 격리 상태로 동작하는 무료 보안 점검(`/scan-code`, `/scan-app`, `/scan-web`) 설계 문서입니다.

- 시작: [[보안 툴킷]] — 요구사항, 아키텍처, 도구, 위협 모델, 결정 기록(ADR-001~005)
- 구현 순서: [[구현 계획]] · 열린 질문: [[미결정 사항]]

## 🗂️ 프로젝트

- [[레포 통합 계획]] — `pr-review-command` → `dev-workflow-kit` 전환 기록 (PR #6, #7, #9, 이 문서 PR)
- [[README 구성안]]
- [[ADR-006 플러그인 마켓플레이스 구조]] · [[ADR-007 레포 이름과 커맨드 정리]]

## 폴더 구조

```
docs/
├── Home.md          # 이 문서
├── workflow/        # workflow 플러그인 커맨드별 상세 (README에서 분리)
├── security/        # security 플러그인 설계 (보안 툴킷.md에서 시작)
├── project/         # 저장소 단위 계획·결정
└── _templates/      # 노트 템플릿 (ADR)
```
