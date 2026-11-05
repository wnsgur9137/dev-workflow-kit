---
title: README 구성안
tags: [roadmap, docs]
status: draft
created: 2026-11-05
---

# README 구성안

상위: [[레포 통합 계획]]

## 원칙
- README는 **처음 보는 사람이 5분 안에 설치·사용**할 수 있는 수준까지만. 목표 10KB 이하 (현재 36KB)
- 커맨드별 상세 옵션·절차는 `docs/`로 이동하고 링크만 남김
- 한국어 작성 (기존 레포와 동일)

## PR별 README 변경

| PR | 변경 범위 |
|---|---|
| PR 1 정리 | 설정 섹션: `.mcp.json` 직접 커밋 → `examples/mcp.json.example` 복사 안내 |
| PR 2 동기화 | 제목 변경, `/ship` → `/pipeline`, `/create-pr` 라벨·마일스톤, 목차 갱신 |
| PR 3 플러그인 | 설치: `~/.claude` 복사 → `/plugin marketplace add` + `/plugin install`, 디렉터리 구조 |
| PR 4 문서 | 아래 구성으로 전체 재작성 |

## 최종 구성 (PR 4)

```markdown
# Dev Workflow Kit

Claude Code에서 쓰는 개발 워크플로·보안 점검 플러그인 모음.

## 플러그인
| 플러그인 | 커맨드 | 설명 |
|---|---|---|
| workflow | /commit /create-pr /pr-review /apply-review /pipeline | 커밋부터 병합까지 |
| security | /security:scan-code /security:scan-app /security:scan-web | 로컬·네트워크 격리 보안 점검 |

## 빠른 시작
/plugin marketplace add wnsgur9137/dev-workflow-kit
/plugin install workflow@dev-workflow-kit
/plugin install security@dev-workflow-kit

## 요구사항
- workflow: GitHub MCP (examples/mcp.json.example), gh CLI(폴백)
- security: Docker, 최초 1회 update.sh

## 커맨드 요약
(커맨드당 2~3줄 + docs 링크)

## 보안 원칙 (security 플러그인)
- 무료, 외부 전송 없음(네트워크 격리), 공격 요청 없음 — docs/security 링크

## 문서
docs/는 Obsidian vault. docs/00 Home/Home.md에서 시작

## 커스터마이징
리뷰 기준(review-criteria), 출력 템플릿, 보안 허용목록

## 라이선스
```

## 기존 README에서 옮길 내용
| 기존 섹션 | 이동 위치 |
|---|---|
| Why GitHub MCP? | `docs/workflow/GitHub MCP.md` |
| /commit ~ /ship 상세 | `docs/workflow/<커맨드>.md` |
| 의존성, 설정 | README 요약 + `docs/workflow/설정.md` |
| 커스터마이징 | README 요약 + `docs/workflow/커스터마이징.md` |

> [!check] 확인됨 (2026-11-05)
> - 설치 명령 `/plugin marketplace add wnsgur9137/dev-workflow-kit`, `/plugin install workflow@dev-workflow-kit`로 실제 설치 (PR #9)
> - 라이선스 MIT 추가 (PR #14)
