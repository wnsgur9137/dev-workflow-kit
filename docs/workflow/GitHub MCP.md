---
title: Why GitHub MCP?
tags: [workflow, setup]
---

# Why GitHub MCP?

상위: [Home](../Home.md) · [README](../../README.md)

이 프로젝트는 `gh` CLI 대신 **GitHub MCP (Model Context Protocol)** 서버를 사용합니다.

|            | `gh` CLI                         | GitHub MCP                                      |
| ---------- | -------------------------------- | ----------------------------------------------- |
| **동작 방식**  | Claude가 Bash로 `gh` 명령어 실행        | Claude가 MCP 도구를 직접 호출                           |
| **인증**     | `gh auth login` 필요 (interactive) | 환경변수 토큰으로 자동 인증                                 |
| **데이터 접근** | CLI 출력 텍스트를 파싱해야 함               | 구조화된 JSON 데이터 직접 수신                             |
| **권한 관리**  | 사용자 세션 전체 권한                     | 토큰 scope로 세밀한 제어                                |
| **리뷰 게시**  | `gh api`로 복잡한 REST 호출 필요         | `create_pending_pull_request_review` 등 전용 도구 제공 |
| **안정성**    | 셸 실행 → 출력 파싱 → 오류 가능성 높음         | 타입이 보장된 도구 호출 → 안정적                             |

핵심 이유: GitHub MCP는 PR 리뷰 생성, 인라인 코멘트 게시, pending review 관리 등 **리뷰 워크플로우에 특화된 도구**를 제공하여, `gh` CLI로는 여러 단계의 API 호출이 필요한 작업을 단일 도구 호출로 처리할 수 있습니다.

## 인라인 코멘트와 Pending Review

`/pr-review`의 코멘트 게시(Step 6.3)는 GitHub MCP의 pending review 워크플로우를 사용합니다:

```
1. create_pending_pull_request_review  → 리뷰 세션 시작
2. add_comment_to_pending_review       → 인라인 코멘트 N개 추가 (반복)
3. submit_pending_pull_request_review  → 리뷰 한 번에 제출 (APPROVE/COMMENT/REQUEST_CHANGES)
```

이 3단계 패턴은 **GitHub MCP만 전용 도구로 제공**하며, `gh` CLI에는 `add_comment_to_pending_review`에 대응하는 명령이 없습니다. `gh api`로 REST API를 직접 호출할 수는 있지만, pending review ID 추적과 diff position 계산이 필요하여 복잡하고 오류 확률이 높습니다.

| 기능 | GitHub MCP | gh CLI |
|------|-----------|--------|
| PR 정보 조회 | `get_pull_request` | `gh pr view --json` |
| diff/파일 목록 | `get_pull_request_diff` | `gh pr diff` |
| 기존 리뷰 조회 | `get_pull_request_reviews` | `gh api .../reviews` |
| 보안 스캔 | `list_secret_scanning_alerts` 등 | `gh api .../alerts` |
| **인라인 코멘트 묶음 게시** | **전용 도구 3개** | **직접 대응 없음** |

> **결론**: PR 데이터 조회는 원리상 `gh` CLI로 대체 가능하지만, **인라인 코멘트를 리뷰로 묶어서 게시하는 기능은 GitHub MCP가 필수**입니다.
>
> 현재 구현 기준 GitHub MCP 의존도는 커맨드마다 다릅니다:
> - **`/create-pr`**: GitHub MCP 우선, 실패 시 `gh pr create`로 폴백 (MCP 없이도 동작 가능)
> - **`/apply-review`**: 코멘트 조회는 `mcp__github__*` 도구 사용 (**MCP 필수**). 리뷰 코멘트 스레드 답글은 MCP에 대응 도구가 없어 `gh api .../comments/{id}/replies`로 게시 (**`gh` CLI 필요**)
> - **`/pr-review`**: pending review 워크플로우와 보안 스캔에 GitHub MCP 전용 도구 사용 (**MCP 필수**)
