---
description: PR 리뷰 코멘트를 코드에 반영하고, 리뷰 코멘트 스레드마다 반영 결과를 답글로 남깁니다.
argument-hint: "<PR_NUMBER_OR_URL> [--reviewer=username] [--auto-commit] [--branch=name] [--help]"
---

# Apply Review Command

PR 리뷰 코멘트를 코드에 반영합니다.

PR Number or URL: $ARGUMENTS

## Step 0: Usage Guide

Before starting, ALWAYS display the usage guide from `${CLAUDE_PLUGIN_ROOT}/templates/apply-review/templates.md` > `usage_guide` 템플릿.

**Argument Parsing:**

`$ARGUMENTS`를 다음과 같이 파싱합니다:
1. `--help`가 포함되어 있거나 `$ARGUMENTS`가 비어 있으면 → 도움말 출력 후 종료 (아래 **Help Mode** 참조)
2. 숫자만 있으면 PR 번호로 간주 → `git remote -v`에서 `owner`/`repo` 추출
3. `https://github.com/{owner}/{repo}/pull/{number}` 패턴이면 URL에서 추출
4. `--`로 시작하는 토큰을 옵션으로 파싱
5. 유효한 PR 번호/URL이 없으면 usage guide만 출력 후 종료

**Help Mode (`--help` 또는 인자 없음):**

`${CLAUDE_PLUGIN_ROOT}/templates/apply-review/templates.md` > `usage_guide` 템플릿을 출력하고 종료합니다. 다른 작업은 수행하지 않습니다.

## Mandatory User Interaction Policy

**CRITICAL**: 아래 Step에서 사용자 선택이 필요한 부분은 반드시 `AskUserQuestion`을 사용하여 사용자에게 옵션을 제시하고 응답을 받아야 합니다. 절대로 임의 판단으로 생략하거나 기본값을 가정하지 마세요.

**필수 사용자 선택 지점:**
- Step 1.2: PR이 closed/merged 상태일 때, 다른 사용자의 PR일 때
- Step 1.3: 브랜치 불일치 시 체크아웃 여부
- Step 1.4: 로컬 브랜치가 뒤처져 있을 때 pull 여부
- Step 2.1: 이전 반영 기록 존재 시 증분/전체/재확인 선택
- Step 5: 반영할 코멘트 선택 (전체 진행/전체 취소/개별 선택/DISAGREE 포함)
- Step 6: 대규모 변경 시 브랜치 분리 여부
- Step 9: 커밋, Push, PR 생성 여부
- Step 10: 리뷰 코멘트 답글 작성 여부 (답글 초안 확인 포함)

이 정책은 모든 옵션에 우선합니다. 사용자 선택 없이 다음 Step으로 진행하는 것은 허용되지 않습니다.

## Error Handling Policy

모든 GitHub MCP 호출에 대해 다음 에러 핸들링을 적용합니다:

**인증/권한 오류 (401/403)**:
- "GitHub 토큰 권한이 부족합니다. GITHUB_PERSONAL_ACCESS_TOKEN을 확인하세요." 출력 후 중단

**Not Found (404)**:
- "PR을 찾을 수 없습니다. 번호/URL을 확인하세요." 출력 후 중단

**Rate Limit (429)**:
- "GitHub API rate limit에 도달했습니다." 출력
- 현재까지 반영 완료된 항목을 보존하고 나머지 중단

**코멘트 0개**:
- "반영할 리뷰 코멘트가 없습니다." 출력 후 종료

**`gh` CLI 미설치 또는 미인증 (Step 10 답글 게시 시)**:
- `gh auth status` 실패 시 "답글 게시에 `gh` CLI 인증이 필요합니다. `gh auth login` 후 다시 시도하세요." 출력
- 답글만 건너뛰고 Step 11은 그대로 진행

**git remote 없음 (bare number 사용 시)**:
- "현재 디렉토리에 git remote가 없습니다. 전체 PR URL을 입력하세요." 출력 후 중단

**레포지토리 불일치**:
- "현재 디렉토리가 PR 대상 레포지토리와 일치하지 않습니다." 출력 후 중단

## Instructions

You are a senior developer applying PR review feedback. Read the review comments, assess their validity, and apply the approved changes to the codebase.

### Step 1: PR Information Fetch & Branch Validation

**1.1 PR 번호 파싱:**

`$ARGUMENTS`에서 PR 번호를 추출합니다. bare number인 경우 `git remote -v`로 `owner`/`repo`를 추출합니다.

**1.2 PR 정보 수집:**

`mcp__github__get_pull_request`로 PR 정보를 가져옵니다:
- PR title, state, draft, merged, head.ref, base.ref, author
- `mcp__github__get_me`로 현재 사용자 확인

**레포지토리 일치 검증:**

`git remote -v`로 현재 로컬 레포의 `owner/repo`를 추출하고, PR의 `owner/repo`와 비교합니다.

- **일치하지 않을 경우** `${CLAUDE_PLUGIN_ROOT}/templates/apply-review/templates.md` > `repo_mismatch` 템플릿으로 경고 출력 후 즉시 종료
- fork 레포인 경우도 검증: `git remote -v`의 `origin`과 `upstream` 모두 확인하여 PR의 `owner/repo`와 하나라도 일치하면 통과

**상태 검증:**
- `state` == "closed" 또는 `merged` == true: "이 PR은 이미 닫혔거나 머지되었습니다. 반영을 계속하시겠습니까?" `AskUserQuestion`
- PR author != current user: "이 PR은 다른 사용자의 PR입니다. 계속하시겠습니까?" 경고

**1.3 브랜치 검증:**

`git branch --show-current`로 현재 로컬 브랜치를 확인하고 PR의 `head.ref`와 비교합니다.

**일치하지 않을 경우** `AskUserQuestion`으로 옵션 제시:

- **PR 브랜치로 체크아웃**: `git checkout {head.ref}` 실행
- **현재 브랜치에서 계속**: 주의 안내 후 진행
- **취소**: 반영 중단

체크아웃 전 uncommitted changes가 있으면:
- "uncommitted changes가 있습니다. stash 하시겠습니까?" `AskUserQuestion`

**1.4 로컬 최신 상태 확인:**

`git fetch origin` 후 `git status`로 remote와의 차이를 확인합니다:
- 로컬이 뒤처져 있으면: "로컬 브랜치가 원격보다 {N}개 커밋 뒤처져 있습니다. pull 하시겠습니까?" `AskUserQuestion`

**1.5 PR 요약 출력:**

`${CLAUDE_PLUGIN_ROOT}/templates/apply-review/templates.md` > `pr_summary` 템플릿으로 출력.

### Step 2: Previous Apply History Check

**2.1 이전 반영 기록 확인:**

`~/.claude/review-history/{owner}/{repo}/apply-review-pr-{number}.json` 파일이 존재하는지 확인합니다. `{owner}/{repo}`는 PR URL 또는 `git remote -v`에서 추출합니다.

**기록 파일이 존재하면** `${CLAUDE_PLUGIN_ROOT}/templates/apply-review/templates.md` > `previous_apply_history` 템플릿으로 이전 반영 정보를 출력하고 `AskUserQuestion`으로 옵션을 제시합니다:

**옵션:**

- **증분 반영 (Recommended)**: 이전 반영 이후 새로 추가된 코멘트만 수집하여 반영
  - `last_applied_at` 타임스탬프 이후에 작성된 코멘트만 필터링
  - 이전에 DISAGREE/SKIP으로 제외했던 코멘트도 재수집하지 않음
- **처음부터 다시 확인**: 이전 기록을 무시하고 모든 코멘트를 대상으로 전체 프로세스 진행
- **이전 제외 항목만 재확인**: 이전에 DISAGREE/SKIP으로 제외했던 코멘트만 다시 판단
  - 리뷰어가 추가 설명을 달았거나 상황이 변한 경우 유용

**기록 파일이 없으면** 이 Step을 건너뛰고 전체 코멘트를 대상으로 진행합니다.

### Step 3: Review Comment Collection & Classification

**3.1 리뷰 코멘트 수집:**

- `mcp__github__get_pull_request_reviews`로 리뷰 목록 조회
- `mcp__github__get_pull_request_review_comments`로 인라인 코멘트 조회

**3.2 코멘트 필터링:**

- `--reviewer=username` 옵션이 있으면 해당 리뷰어의 코멘트만 필터
- 자기 자신의 코멘트 제외 (자기가 자기에게 남긴 메모는 반영 대상이 아님)
- reply 코멘트 중 "resolved" 또는 수정 확인 내용이 있는 스레드는 제외
- bot 코멘트는 별도 표시하되 포함

**3.3 코멘트 분류:**

각 코멘트를 다음 카테고리로 자동 분류:

| 유형 | 아이콘 | 판단 기준 |
|------|--------|----------|
| `CODE_CHANGE` | 🔧 | suggestion 블록 포함, "수정", "변경", "fix", "change" 등 |
| `REFACTOR` | ♻️ | "리팩토링", "분리", "추출", "refactor", "extract" 등 |
| `QUESTION` | ❓ | 물음표로 끝남, "왜", "이유", "why", "reason" 등 |
| `STYLE` | 🎨 | "네이밍", "컨벤션", "naming", "style" 등 |
| `ARCHITECTURE` | 🏗️ | "패턴", "구조", "아키텍처", "architecture", "design" 등 |
| `INFO` | ℹ️ | 수정 요청이 아닌 설명, 참고사항, 칭찬 |

**3.4 코멘트 요약 출력:**

`${CLAUDE_PLUGIN_ROOT}/templates/apply-review/templates.md` > `comment_collection_summary` 템플릿으로 출력.

### Step 4: AI Validity Assessment

각 코멘트에 대해 AI가 합당성을 판단합니다. 프로젝트의 CLAUDE.md, conventions.md, `${CLAUDE_PLUGIN_ROOT}/templates/review-criteria/` 디렉토리의 플랫폼별 리뷰 기준을 참조합니다.

**4.1 판단 기준:**

| 판정 | 기준 | 아이콘 |
|------|------|--------|
| **AGREE** | 기술적으로 정확하고, 코드 품질/안전성을 명확히 개선 | ✅ |
| **PARTIAL** | 지적은 맞지만 제안된 해결 방식보다 나은 대안이 있음 | 🔶 |
| **DISAGREE** | 기술적으로 부정확하거나, 프로젝트 컨벤션과 충돌, 트레이드오프상 현재 코드가 나음 | ❌ |
| **SKIP** | 질문/정보성 코멘트로 코드 변경 불필요 | ⏭️ |

**AGREE 조건 (하나 이상):**
- 명백한 버그 지적 (NPE, 범위 초과, 타입 불일치)
- 보안 취약점 지적
- suggestion 블록의 코드가 문법적/기능적으로 올바름
- 프로젝트 컨벤션/린트 규칙 위반 지적

**PARTIAL 조건:**
- 문제 지적은 맞지만 suggestion 코드에 오류가 있음
- 지적은 타당하나 프로젝트 컨벤션상 다른 해결 방식이 적절
- 여러 이슈를 하나의 코멘트에 섞어서 지적 (일부만 타당)

**DISAGREE 조건:**
- 기술적으로 부정확한 지적
- 프로젝트 컨벤션과 충돌하는 제안
- 트레이드오프상 현재 코드가 더 나은 경우
- 이미 다른 곳에서 처리되고 있는 이슈

**SKIP 조건:**
- 순수 질문 (코드 변경 불필요)
- 칭찬/감사/정보 제공 목적 코멘트

**4.2 판단 시 참조:**
- 해당 파일의 현재 상태를 로컬에서 `Read`하여 컨텍스트 확인
- `${CLAUDE_PLUGIN_ROOT}/templates/review-criteria/` 디렉토리의 해당 플랫폼 파일 우선순위 기준 참조
- 캐시된 conventions.md가 있으면 프로젝트 컨벤션 참조

**4.3 판단 결과 출력:**

`${CLAUDE_PLUGIN_ROOT}/templates/apply-review/templates.md` > `ai_verdict` 템플릿으로 출력.

### Step 5: User Confirmation (Interactive Selection)

`AskUserQuestion`으로 사용자에게 반영할 코멘트를 선택하도록 합니다.

옵션:
- **전체 진행 (Recommended)**: AGREE + PARTIAL 항목만 반영, DISAGREE/SKIP 제외
- **전체 취소**: 반영 중단
- **개별 선택**: 각 코멘트를 번호로 선택/제외
- **DISAGREE 포함 전체 진행**: DISAGREE 항목도 포함하여 모든 코드 변경 코멘트 반영

사용자가 "개별 선택"을 선택한 경우, 추가 `AskUserQuestion`으로 반영할 코멘트 번호를 입력받습니다.

### Step 6: Large-Scale Change Detection & Branch Separation

반영 대상으로 선택된 코멘트들의 예상 영향을 분석합니다.

**브랜치 분리 제안 기준:**

| 조건 | 동작 |
|------|------|
| 수정 예상 파일 > 10개 | 브랜치 분리 제안 |
| 수정 예상 라인 > 200줄 | 브랜치 분리 제안 |
| 🏗️ ARCHITECTURE 코멘트 포함 | 브랜치 분리 제안 |
| ♻️ REFACTOR 코멘트 >= 3개 | 브랜치 분리 제안 |

**브랜치 분리 제안 시** `AskUserQuestion`:

- **현재 브랜치에서 계속**: 그대로 진행
- **새 브랜치 생성**: `git checkout -b review/pr-{number}-feedback` 생성 후 진행
- **그룹별 분리 커밋**: 코멘트를 유형별로 그룹화하여 순차 커밋

위 기준에 해당하지 않으면 이 Step을 건너뜁니다.

### Step 7: Apply Changes

**7.1 병렬 처리 기준:**

| 반영 대상 코멘트 수 | 독립 파일 수 | 전략 |
|---------------------|-------------|------|
| 1~3개 | any | 순차 처리 |
| 4~7개 | >= 2 | 파일별 2~3 병렬 agent |
| 8개 이상 | >= 3 | 파일별 3~5 병렬 agent |
| any | 1 (모두 같은 파일) | 순차 처리 (강제) |

**핵심 규칙: 같은 파일의 코멘트는 반드시 같은 agent에서 순차 처리** (충돌 방지)

**7.2 각 코멘트 반영 프로세스:**

1. 해당 파일을 `Read`로 읽기
2. suggestion 블록이 있으면 해당 코드를 직접 적용
3. suggestion 블록이 없으면 AI가 코멘트 의도를 해석하여 코드 수정
4. PARTIAL 판정인 경우 AI 대안을 적용
5. `Edit`으로 파일 수정

**7.3 진행 상황 출력:**

`${CLAUDE_PLUGIN_ROOT}/templates/apply-review/templates.md` > `apply_progress` 템플릿으로 출력.

### Step 8: Verification

**8.1 변경 결과 검증:**
- 수정된 모든 파일을 `Read`하여 변경이 올바르게 적용되었는지 확인
- `git diff`로 전체 변경 사항 출력

**8.2 검증 결과 출력:**

`${CLAUDE_PLUGIN_ROOT}/templates/apply-review/templates.md` > `verification_result` 템플릿으로 출력.

### Step 9: Commit, Push & PR Options

순차적으로 `AskUserQuestion`을 사용하여 각 단계를 확인합니다.

**9.1 커밋 여부:**

- **커밋 (자동 메시지)**: 아래 형식으로 자동 커밋 메시지 생성
- **커밋 메시지 직접 입력**: 사용자가 메시지를 입력
- **커밋하지 않음**: unstaged 상태로 유지

자동 커밋 메시지 형식: `${CLAUDE_PLUGIN_ROOT}/templates/apply-review/templates.md` > `commit_message` 템플릿 (프로젝트의 커밋 컨벤션을 따름).

**9.2 Push 여부** (커밋한 경우에만):

- **Push**: `git push origin {branch}`
- **Push하지 않음**: 로컬에만 커밋 유지

**9.3 새 브랜치에서 작업한 경우 — PR 생성 여부** (Push한 경우에만):

- **PR 생성**: `mcp__github__create_pull_request` 사용
- **PR 생성하지 않음**: 건너뜀

PR 생성 시:
1. `.github/PULL_REQUEST_TEMPLATE.md`가 있으면 해당 템플릿 기반으로 body 작성
2. 없으면 `${CLAUDE_PLUGIN_ROOT}/templates/apply-review/templates.md` > `pr_body` 템플릿 사용

### Step 10: Post Feedback Comment to PR

`AskUserQuestion`으로 답글 작성 여부를 확인합니다:

- **답글 작성**: 각 리뷰 코멘트 스레드에 답글 게시
- **답글 작성하지 않음**: 건너뜀

게시 전 코멘트별 답글 초안(QUESTION 답변 포함)을 표로 보여주고 `AskUserQuestion`으로 확인받습니다.

**답글 대상:**

- 대상: 반영한 코멘트, DISAGREE·PARTIAL·사용자 제외로 반영하지 않은 코드 변경 요청, QUESTION
- 제외: INFO 유형과 칭찬·감사 등 답할 내용이 없는 SKIP 코멘트 (초안 표에 "답글 없음"으로 표시)

**10.1 답글 방식 (필수):**

PR 전체 코멘트 하나로 모아 쓰지 않고, **원래 리뷰 코멘트에 답글로** 작성합니다.

- 인라인 리뷰 코멘트: `gh api -X POST repos/{owner}/{repo}/pulls/{number}/comments/{comment_id}/replies -f body=...`
  - 답글에 대한 답글은 불가하므로 스레드의 최상위 코멘트 ID(`in_reply_to_id`가 없으면 자기 ID)를 사용
- 리뷰 본문·일반 PR 코멘트처럼 답글 스레드가 없는 경우에만 `mcp__github__add_issue_comment`로 게시하고, 첫 줄에 원 코멘트 링크와 인용(`> ...`)을 붙여 어떤 코멘트에 대한 답인지 표시

**10.2 답글 내용:**

판정과 실제 반영 여부에 따라 `${CLAUDE_PLUGIN_ROOT}/templates/apply-review/templates.md`의 템플릿을 사용합니다.

| 경우 | 템플릿 | 내용 |
|------|--------|------|
| 반영함 (AGREE·PARTIAL 반영) | `reply_applied` | 반영 내용 1~2줄 요약 + 커밋 첨부 |
| 반영하지 않음 (DISAGREE·SKIP·사용자 제외) | `reply_not_applied` | 반영하지 않은 이유를 1~2줄로 간략히 |
| QUESTION | `reply_answer` | 코드 컨텍스트 기반 답변 (위 답글 초안 확인에서 함께 확인) |

- 커밋은 Push된 커밋의 전체 URL(`https://github.com/{owner}/{repo}/commit/{hash}`) 또는 해시로 첨부. Push하지 않았다면 답글 작성 전에 그 사실을 알리고 확인받음
- Step 9에서 커밋하지 않았다면 `reply_applied` 답글을 게시하지 않고, 커밋 후 다시 실행하도록 안내 (`reply_not_applied`·`reply_answer`는 게시 가능)
- PARTIAL로 일부만 반영했다면 반영하지 않은 부분과 이유도 한 줄 덧붙임
- 빌드 확인·실기기 미확인 등 검증 상태는 답글에 쓰지 않음 (반영 내용·사유·답변만 작성)

### Step 11: Save Apply History

반영 완료 후, 다음 실행 시 증분 반영을 지원하기 위해 기록을 저장합니다.

**11.1 기록 파일 경로:**

- 모든 레포 공통: `~/.claude/review-history/{owner}/{repo}/apply-review-pr-{number}.json`
- `{owner}/{repo}`는 PR URL 또는 `git remote -v`에서 추출

**11.2 기록 파일 형식:**

`${CLAUDE_PLUGIN_ROOT}/templates/apply-review/templates.md` > `history_record` 템플릿의 JSON 스키마를 따름.

**11.3 기록 규칙:**

- 기존 기록 파일이 있으면 `history` 배열에 이전 실행 요약을 push하고 최상위 필드를 현재 실행으로 갱신
- `applied_comments`와 `skipped_comments`는 누적이 아닌 최신 실행 기준으로 덮어씀
- 파일 쓰기 실패 시 조용히 건너뜀 (전체 프로세스에 영향 없음)
