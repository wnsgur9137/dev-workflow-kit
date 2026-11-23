---
title: GitHub MCP에서 gh로
tags: [workflow, setup]
---

# GitHub MCP에서 gh로

상위: [Home](../Home.md) · [README](../../README.md)

workflow 플러그인은 1.x까지 GitHub 작업에 **GitHub MCP 서버**를 썼고, **2.0.0부터 `gh` CLI를 기본으로** 씁니다. GitHub MCP는 `gh`를 쓸 수 없을 때만 대신 쓰는 선택 사항입니다.

## 왜 바꿨나

| | GitHub MCP (1.x) | `gh` CLI (2.0.0~) |
|---|---|---|
| 준비 | Docker 런타임 + `GITHUB_PERSONAL_ACCESS_TOKEN` + 프로젝트별 `.mcp.json` | `gh auth login` 한 번 |
| Codex 지원 | 도구 이름(`mcp__github__*`)이 Claude Code 방식이라 Codex에서는 맞지 않음 | Claude Code·Codex 모두 셸에서 같은 명령 |
| 장애 | MCP 서버 연결이 실패하면 리뷰·반영이 멈춤 (예: 인증 헤더 오류) | `gh` 인증만 유지하면 됨 |
| 이미 쓰던 곳 | — | `/apply-review` 답글, `/create-pr` 폴백, `/pipeline`은 1.x에서도 `gh`가 필요했음 |

1.x 문서는 "인라인 코멘트를 리뷰 하나로 묶어 게시하려면 MCP의 pending review 도구가 필수"라고 적었습니다. 이 설명은 정확하지 않았습니다. REST API의 [Create a review](https://docs.github.com/en/rest/pulls/reviews#create-a-review-for-a-pull-request)는 `comments` 배열을 받아 **요청 한 번으로** 인라인 코멘트가 묶인 리뷰를 만들고, 줄 위치는 diff position이 아니라 `line`·`side`로 지정합니다.

```bash
gh api -X POST "repos/{owner}/{repo}/pulls/{N}/reviews" --input review.json
```

```json
{
  "commit_id": "<head sha>",
  "event": "COMMENT",
  "body": "<Summary>",
  "comments": [{ "path": "src/a.ts", "line": 42, "side": "RIGHT", "body": "..." }]
}
```

## 달라진 점

- 파일 단위 코멘트(줄이 diff 밖)는 리뷰 API의 `comments`에 넣을 수 없습니다. 리뷰를 만든 뒤 `POST /pulls/{N}/comments`에 `subject_type=file`로 따로 답니다.
- 조회 결과는 REST 필드 이름(`base.sha`, `commit_id`, `submitted_at` 등)을 그대로 씁니다. 목록은 `--paginate`로 끝까지 받습니다.
- 보안 알림(secret scanning·code scanning·Dependabot) 조회는 권한이 없으면 403/404가 납니다. 이전과 같이 "확인할 수 없음"으로 적고 건너뜁니다.

## GitHub MCP를 계속 쓰려면

`gh`를 쓸 수 없는 환경이면 [설정 > GitHub MCP (선택)](설정.md#github-mcp-선택)대로 `.mcp.json`을 두세요. 각 skill은 "`gh`를 쓸 수 없고 GitHub MCP 도구가 연결돼 있으면 같은 작업을 MCP로 해도 된다"고 안내합니다.
