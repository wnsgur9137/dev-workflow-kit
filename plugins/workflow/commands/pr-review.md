# PR Review Command

PR URL: $ARGUMENTS

## Step 0: Usage Guide

Before starting, ALWAYS display the usage guide from `.claude/templates/review/templates.md` > `usage_guide` 템플릿.

**Argument Parsing:**

`$ARGUMENTS`를 다음과 같이 파싱합니다:
1. `--help`가 포함되어 있거나 `$ARGUMENTS`가 비어 있으면 → 도움말 출력 후 종료 (아래 **Help Mode** 참조)
2. `https://github.com/...` 패턴으로 PR URL 추출
3. `--`로 시작하는 토큰을 옵션으로 파싱
4. 인식 불가 옵션은 무시하되 "알 수 없는 옵션: {option}" 경고 출력

**Help Mode (`--help` 또는 인자 없음):**

다음 정보를 출력하고 종료합니다:

```
=== /pr-review 도움말 ===

Usage: /pr-review <PR_URL> [options]
Example: /pr-review https://github.com/owner/repo/pull/32
         /pr-review https://github.com/owner/repo/pull/32 --mode=strict

-- Options --
  --mode=strict    모든 severity 코멘트 생성, WARNING 2개 이상이면 REQUEST_CHANGES
  --mode=normal    표준 판정 매트릭스 적용 (기본값)
  --mode=relaxed   CRITICAL만 코멘트, 나머지는 Summary에만 기록
  --focus=항목,...  지정 카테고리만 집중 리뷰 (예: security,performance,memory)
  --skip=항목,...   지정 severity/카테고리 건너뛰기 (예: nitpick,style)
  --help           이 도움말을 표시합니다

-- Review Process --
1. PR URL 파싱 + 상태 확인 (draft/merged/CI)
2. GitHub MCP를 통해 PR 정보 수집
3. 보안 스캔 (Secret/Code/Dependabot alerts)
4. 변경 파일 확장자로 PR 타입 감지 (iOS/Android/FrontEnd/BackEnd)
5. 타입별 우선순위에 따라 코드 리뷰
6. 리뷰 결과 CLI 출력 → 사용자 확인 후 PR에 인라인 코멘트 게시
7. 리뷰 결과 기록

-- Severity Levels --
  🚨 CRITICAL  : 머지 전 반드시 수정 (버그, 보안, 데이터 손실)
  ⚠️ WARNING   : 수정 권장 (성능, 코드 스멜)
  💡 SUGGESTION: 개선 제안 (가독성, 베스트 프랙티스)
  ❓ QUESTION  : 작성자에게 확인 필요
  🔹 NITPICK   : 매우 사소한 스타일 이슈

-- Verdict Matrix --
  🔒 Secret alert 발견      → REQUEST_CHANGES (무조건)
  🚨 CRITICAL >= 1          → REQUEST_CHANGES
  ⚠️ WARNING >= 3 (normal)  → REQUEST_CHANGES
  ⚠️ WARNING 1~2            → COMMENT
  💡 SUGGESTION만            → COMMENT
  이슈 없음 / 🔹 NITPICK만  → APPROVE
  Draft PR                  → COMMENT (고정)

========================
```

도움말 출력 후 다른 작업은 수행하지 않습니다.

**옵션별 동작:**

| 옵션 | Step 6 판정 영향 | 코멘트 필터링 |
|------|-----------------|-------------|
| `--mode=strict` | WARNING >= 2이면 REQUEST_CHANGES | 모든 severity 코멘트 |
| `--mode=normal` | 표준 판정 매트릭스 | 모든 severity 코멘트 |
| `--mode=relaxed` | CRITICAL 있을 때만 REQUEST_CHANGES | CRITICAL만 인라인 코멘트, 나머지는 Summary에 목록으로 |
| `--focus=X,Y` | 변경 없음 | 지정 카테고리만 리뷰 (나머지 건너뜀) |
| `--skip=X,Y` | 변경 없음 | 지정 severity/카테고리 건너뜀 |

If `$ARGUMENTS` is empty or does not contain a valid PR URL (`https://github.com/{owner}/{repo}/pull/{number}`), show the usage guide and stop. Do NOT proceed.

If a valid PR URL is provided, show the guide briefly then proceed below.

## Mandatory User Interaction Policy

**CRITICAL**: 아래 Step에서 사용자 선택이 필요한 부분은 반드시 `AskUserQuestion`을 사용하여 사용자에게 옵션을 제시하고 응답을 받아야 합니다. 절대로 임의 판단으로 생략하거나 기본값을 가정하지 마세요.

**필수 사용자 선택 지점:**
- Step 2.1: PR이 closed/merged 상태일 때 계속 여부
- Step 2.4: 재리뷰 감지 시 증분/전체 리뷰 선택
- Step 2.5: 다른 레포지토리일 때 분석 옵션 선택
- Step 6.2: PR 코멘트 게시 여부 (전체 게시 / 선택 후 게시 / 종료)
- Step 6.2.1: "선택 후 게시" 시 개별 코멘트 선택

이 정책은 모든 옵션에 우선합니다. 사용자 선택 없이 다음 Step으로 진행하는 것은 허용되지 않습니다.

## Error Handling Policy

모든 GitHub MCP 호출에 대해 다음 에러 핸들링을 적용합니다:

**인증/권한 오류 (401/403)**:
- "GitHub 토큰 권한이 부족합니다. GITHUB_PERSONAL_ACCESS_TOKEN을 확인하세요." 출력 후 리뷰 중단

**Not Found (404)**:
- PR 조회 시: "PR을 찾을 수 없습니다. URL을 확인하세요." 출력 후 중단
- 보안 도구 (Step 2.7): "보안 스캔 접근 권한 없음 - 건너뜀" 출력 후 계속 진행
- 파일/이슈 조회: "리소스를 찾을 수 없음 - 건너뜀" 출력 후 계속 진행

**Rate Limit (429)**:
- "GitHub API rate limit에 도달했습니다." 출력
- 현재까지의 리뷰 결과를 Summary로 출력 후 중단

**네트워크 오류 / 타임아웃**:
- "GitHub API 연결 오류. 네트워크를 확인하세요." 출력 후 중단

**바이너리 파일 감지**:
- 확장자가 `.png`, `.jpg`, `.jpeg`, `.gif`, `.ico`, `.svg`, `.woff`, `.woff2`, `.ttf`, `.eot`, `.zip`, `.jar`, `.aar`, `.framework`, `.xcframework`, `.a`, `.dylib`, `.so`, `.dll`, `.exe`, `.pdf`, `.mp3`, `.mp4`, `.mov` 인 파일은 리뷰에서 제외
- diff에서 `Binary files ... differ` 패턴도 제외
- "바이너리 파일 {N}개 건너뜀" 안내

**대규모 PR 경고**:
- 변경 파일 50개 초과: "대규모 PR ({N}개 파일). 주요 로직 파일 위주로 리뷰합니다."
- 변경 라인 1000줄 초과: "변경량이 많습니다 ({N}줄). 리뷰 시간이 길어질 수 있습니다."
- 변경 파일 200개 초과: "매우 큰 PR입니다. PR 분할을 강력 권장합니다." → SUGGESTION으로 Summary에 기록

**자동 생성 파일 감지**:
- `*.generated.*`, `*.min.js`, `*.min.css`, `*.lock`, `*.sum`, `*.pbxproj` 등 자동 생성 파일은 리뷰 우선순위를 최하위로 설정
- "자동 생성 파일 {N}개는 축약 리뷰 적용" 안내

## Instructions

You are a senior code reviewer. Review the given GitHub Pull Request and provide detailed, actionable feedback as line-by-line comments.

### Step 1: Parse PR URL

Extract `owner`, `repo`, and `pr_number` from the PR URL.
The URL format is: `https://github.com/{owner}/{repo}/pull/{pr_number}`

### Step 2: Fetch PR Information & Pre-check

Use GitHub MCP tools to gather PR data and validate PR status:

**2.1 PR 기본 정보 및 상태 확인:**

`mcp__github__get_pull_request`로 PR 정보를 가져온 뒤 상태를 확인합니다:

- `state` == "closed": `AskUserQuestion`으로 "이 PR은 이미 닫혔습니다. 리뷰를 계속 하시겠습니까?" 확인 (옵션: 계속 진행 / 중단)
- `merged` == true: `AskUserQuestion`으로 "이 PR은 이미 머지되었습니다. 리뷰를 계속 하시겠습니까?" 확인 (옵션: 계속 진행 / 중단)
- `draft` == true: "Draft PR입니다. 리뷰 코멘트는 작성하되, submit은 COMMENT로 제한합니다." 안내
- `mergeable` == false: "Merge conflict가 있습니다." 경고 안내

**2.2 CI 상태 확인:**

`mcp__github__get_pull_request_status`로 CI 통과 여부를 확인합니다:
- 모든 check가 success: 정상 진행
- pending/in_progress: "CI가 아직 실행 중입니다" 안내 후 진행
- failure: "CI가 실패했습니다. CI 실패 관련 이슈도 리뷰에 포함합니다." 안내

**2.3 변경 파일 및 Diff:**

- `mcp__github__get_pull_request_files`로 변경 파일 목록 조회
- `mcp__github__get_pull_request_diff`로 전체 diff 조회

**2.4 기존 리뷰 확인 (중복 방지 + 재리뷰 감지):**

- `mcp__github__get_pull_request_reviews`로 기존 리뷰 조회
  - 각 리뷰의 state (APPROVED, CHANGES_REQUESTED, COMMENTED)와 reviewer 기록
  - 이미 REQUEST_CHANGES 상태인 리뷰가 있으면 해당 리뷰어가 지적한 사항 파악
- `mcp__github__get_pull_request_review_comments`로 기존 인라인 코멘트 조회
  - 기존 코멘트의 path, line, body를 파싱하여 이미 지적된 이슈 목록 생성

**재리뷰 감지:**

기존 리뷰 중 현재 사용자(GitHub MCP의 인증 사용자)가 남긴 리뷰가 있는지 확인합니다. `mcp__github__get_me`로 현재 사용자를 확인하고, 기존 리뷰의 `user.login`과 비교합니다.

이전 리뷰가 발견되면 `AskUserQuestion`으로 다음 옵션을 제시합니다:

- **🔄 증분 리뷰 (Recommended)**: 이전 리뷰의 `submitted_at` 이후에 추가된 커밋만 리뷰합니다. `mcp__github__list_commits`에서 이전 리뷰 시점 이후의 커밋만 필터링하고, 해당 커밋에서 변경된 파일/라인만 리뷰 대상으로 합니다. 이전에 지적한 이슈가 수정되었는지도 확인합니다.
- **🔁 전체 리뷰**: 이전 리뷰를 무시하고 PR 전체를 처음부터 다시 리뷰합니다. 단, 동일 파일 + 동일 라인 + 유사 내용의 기존 코멘트는 여전히 건너뜁니다.

**증분 리뷰 동작:**

1. 이전 리뷰의 `submitted_at` 타임스탬프를 기준으로 이후 커밋 목록을 필터링
2. 해당 커밋들에서 변경된 파일만 리뷰 대상으로 설정
3. 이전에 지적한 CRITICAL/WARNING 이슈에 대해:
   - 해당 라인이 새 커밋에서 수정되었으면: "✅ 이전 지적사항 수정 확인" 으로 Summary에 기록
   - 해당 라인이 여전히 동일하면: 건너뜀 (이미 지적됨)
4. 새로 발견된 이슈만 코멘트 대상으로 추가

**이전 리뷰가 없는 경우:** 옵션 없이 전체 리뷰로 진행합니다. 다른 리뷰어(Gemini 등)의 코멘트는 기존대로 중복 방지에만 활용합니다.

**중복 방지 (전체 리뷰 및 증분 리뷰 공통):**
  - Step 6에서 코멘트 작성 시, 동일 파일 + 동일 라인 + 유사 내용의 코멘트가 이미 존재하면 건너뛰기
  - 건너뛴 코멘트는 Step 7 Summary에 "Already flagged by {reviewer}" 로 기록

**2.5 관련 이슈 자동 조회:**

PR description (body)에서 이슈 참조 패턴을 파싱합니다:
- 패턴: `Fixes #N`, `Closes #N`, `Resolves #N`, `Related #N`, `refs #N` (대소문자 무관)
- 각 이슈 번호에 대해 `mcp__github__get_issue`로 이슈 내용 조회
- 이슈의 title, body, labels를 리뷰 컨텍스트에 추가
- Step 4 리뷰 시: PR 변경 내용이 이슈 요구사항을 충족하는지 검증
- Step 7 Summary에 "Linked Issues Coverage" 섹션 추가

**2.6 커밋 분석:**

`mcp__github__list_commits`로 PR의 커밋 목록을 조회합니다:
- 커밋 수가 20개 초과: Summary에 "스쿼시 머지를 권장합니다" SUGGESTION
- 커밋 메시지 패턴 분석:
  - "fix typo", "formatting", "lint" 등 포매팅 전용 커밋이 전체의 50% 이상이면: "포매팅 변경과 로직 변경을 별도 PR로 분리하면 리뷰가 용이합니다" SUGGESTION
  - "WIP", "tmp", "test" 등 임시 커밋 메시지 발견 시: "머지 전 커밋 메시지 정리를 권장합니다" NITPICK
- 커밋 분석 결과는 Step 7 Summary의 "Commit Quality" 섹션에 기록

**2.8 PR 요약 출력:**

Step 2의 정보 수집이 완료되면, CLI에 PR 요약을 출력합니다:

`.claude/templates/review/templates.md` > `pr_summary` 템플릿으로 출력.

이 요약은 사용자가 리뷰 대상 PR을 빠르게 파악할 수 있도록 합니다. 요약 출력 후 나머지 Step을 계속 진행합니다.

### Step 2.5: Local Project Context (if applicable)

Check if the PR's repository matches the current working directory's git remote:

1. Run `git remote -v` to get the current project's remote URL.
2. Compare the remote's `owner/repo` with the PR's `owner/repo`.
3. **If they match** (same repository), gather local project context:
   - **CLAUDE.md**: Read the project root `CLAUDE.md` and any `CLAUDE.md` files in subdirectories. These contain project conventions, coding standards, and architecture decisions that the review MUST respect.
   - **PR 관련 문서**: Identify which directories/modules the PR touches, then read relevant documentation:
     - `README.md` files in affected directories
     - `AGENTS.md` files if they exist
     - `CONTRIBUTING.md`, `ARCHITECTURE.md`, or similar docs
     - Any `.md` files in `docs/` related to the changed modules
   - **기존 코드 패턴**: Use `Glob` and `Read` to examine existing code in the same directories as the changed files. This helps verify the PR follows established patterns (naming conventions, architecture, error handling style, etc.).
   - **테스트 패턴**: Check existing test files in the same module to ensure the PR's tests (if any) follow the same patterns.
4. **If they don't match** (different repository), **반드시 `AskUserQuestion`으로 레포지토리 분석 옵션을 사용자에게 제시합니다. 이 단계를 생략하거나 임의로 옵션을 선택하지 마세요.**

   **먼저 `.claude/repo-cache/{owner}/{repo}/meta.json` 파일이 존재하는지 `Glob`으로 확인합니다.**

   **캐시가 없는 경우** — `AskUserQuestion` 옵션:
   - **분석 없이 PR diff만으로 리뷰 진행**: 추가 분석 없이 진행
   - **레포지토리를 분석하고 문서를 저장한 뒤 리뷰 진행**: GitHub MCP로 분석 후 캐시

   **캐시가 있는 경우** — `AskUserQuestion` 옵션:
   - **분석 없이 PR diff만으로 리뷰 진행**: 추가 분석 없이 진행
   - **기존 저장된 분석 문서를 참조하여 리뷰 진행**: 캐시된 문서 활용
   - **기존 문서를 삭제하고 새로 분석 진행**: 캐시 초기화 후 재분석

   description에 "이 PR은 현재 프로젝트와 다른 레포지토리입니다: {owner}/{repo}" 를 포함합니다.
   캐시가 있는 경우 description에 캐시 생성 일시도 포함합니다 (예: "캐시 생성일: 2026-03-25").

   - **분석 없이 진행**: 추가 분석 없이 PR diff와 GitHub 컨텍스트만으로 리뷰를 진행합니다.
   - **레포지토리 분석 후 진행**: GitHub MCP를 통해 레포지토리를 분석합니다:
     1. `mcp__github__get_file_contents`로 루트의 `README.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `ARCHITECTURE.md` 등 주요 문서를 가져옵니다.
     2. PR이 수정한 디렉토리의 문서와 주요 소스 파일을 가져옵니다.
     3. 분석 결과를 `.claude/repo-cache/{owner}/{repo}/` 디렉토리에 저장합니다:
        - `meta.json`: 분석 일시, PR 타입, 주요 기술 스택, 브랜치 전략 등
        - `conventions.md`: 코딩 컨벤션, 네이밍 규칙, 아키텍처 패턴
        - `structure.md`: 디렉토리 구조 및 모듈 설명
        - `review-notes.md`: 리뷰 시 참고할 특이사항
        - `review-priorities.md`: 리뷰 우선순위 문서 (아래 참조)

     **`review-priorities.md` 자동 생성 규칙:**

     레포지토리의 기술 스택, 아키텍처, 코드 패턴을 분석하여 해당 프로젝트에 특화된 리뷰 우선순위 문서를 생성합니다:

     ```markdown
     # {owner}/{repo} Review Priorities
     Generated: {YYYY-MM-DD}

     ## 프로젝트 개요
     - 기술 스택: {감지된 언어/프레임워크}
     - 아키텍처: {감지된 패턴 - MVVM, Clean Architecture, 등}
     - PR 타입: {iOS/Android/FrontEnd/BackEnd/복합}

     ## 핵심 리뷰 영역 (반드시 확인)
     1. {프로젝트에서 가장 중요한 리뷰 포인트}
     2. ...

     ## 주요 리뷰 영역 (권장 확인)
     1. ...

     ## 참고 리뷰 영역 (시간 허용 시)
     1. ...

     ## 프로젝트 특이사항
     - {CI/CD 관련, 특수 린트 규칙, 커밋 컨벤션 등}

     ## 자주 발견되는 이슈 패턴
     - {이전 PR 리뷰에서 반복된 이슈가 있다면 기록}
     ```

     생성 시 다음을 분석합니다:
     - **README/CONTRIBUTING**: 프로젝트가 명시한 기여 규칙
     - **린트/포매터 설정**: `.eslintrc`, `.swiftlint.yml`, `detekt.yml` 등에서 프로젝트가 중시하는 코드 품질 규칙
     - **CI 설정**: `.github/workflows/`, `Jenkinsfile` 등에서 자동화된 검증 항목 (이미 CI가 검증하는 항목은 우선순위를 낮춤)
     - **테스트 구조**: 테스트 커버리지 정책, 테스트 프레임워크, 필수 테스트 패턴
     - **보안 민감 영역**: auth, payment, crypto 등 디렉토리 식별 → 해당 영역 변경 시 최우선 리뷰
     - **최근 PR/이슈**: `mcp__github__list_pull_requests`로 최근 머지된 PR 패턴을 참고하여 자주 발생하는 이슈 파악
     4. 저장된 문서를 참조하여 리뷰를 진행합니다.
   - **기존 분석 문서 참조**: `.claude/repo-cache/{owner}/{repo}/` 에 저장된 기존 문서를 읽어 리뷰에 활용합니다. 저장된 문서가 없으면 사용자에게 알리고 다시 선택하도록 합니다.
   - **기존 문서 삭제 후 새로 분석**: `.claude/repo-cache/{owner}/{repo}/` 디렉토리를 삭제하고 "레포지토리 분석 후 진행"과 동일하게 새로 분석을 진행합니다.

   **캐시 문서 유효기간**: `meta.json`의 분석 일시가 30일 이상 경과한 경우, 옵션 3 선택 시 "저장된 문서가 30일 이상 지났습니다. 새로 분석하시겠습니까?" 라고 안내합니다.

When local context is available (same repo or cached analysis), use it to:
- Flag deviations from project conventions documented in CLAUDE.md or cached conventions
- Verify consistency with existing code patterns in the same module
- Check if the PR aligns with documented architecture decisions
- Ensure naming, error handling, and test patterns match the project style

### Step 2.7: Security Alert Scan

PR이 속한 레포지토리의 보안 경고를 확인합니다. 이 정보는 Step 4 리뷰와 Step 6 판정에서 참조됩니다.

1. **Secret Scanning**: `mcp__github__list_secret_scanning_alerts`로 시크릿 노출 경고 조회
   - `owner`, `repo`, `state: "open"` 파라미터 사용
   - PR이 변경한 파일 경로와 교차 확인
   - 발견 시: 해당 파일에 CRITICAL 코멘트 자동 생성 대상으로 마킹
   - **Secret alert가 있으면 Step 6에서 무조건 REQUEST_CHANGES 판정**

2. **Code Scanning**: `mcp__github__list_code_scanning_alerts`로 CodeQL 정적 분석 경고 조회
   - `ref`: PR의 head branch
   - PR 변경 파일과 교차 확인하여 관련 경고만 필터링
   - severity가 `critical` 또는 `high`인 경고는 CRITICAL 코멘트 대상
   - severity가 `medium`인 경고는 WARNING 코멘트 대상

3. **Dependabot Alerts**: `mcp__github__list_dependabot_alerts`로 의존성 취약점 조회
   - `state: "open"` 필터
   - PR이 의존성 파일(`package.json`, `package-lock.json`, `Podfile`, `Podfile.lock`, `build.gradle`, `requirements.txt`, `go.mod`, `go.sum`, `Cargo.toml`, `Cargo.lock`)을 수정했을 때만 조회
   - CVSS 7.0 이상: CRITICAL 코멘트 대상
   - CVSS 4.0~6.9: WARNING 코멘트 대상

4. **결과 집계**:
   - 보안 경고가 1개 이상이면 Step 7 Summary에 `[SECURITY SCAN]` 섹션 포함
   - 각 경고의 상세 정보 (타입, severity, 영향 파일)를 기록

**에러 핸들링**: 403/404 에러 시 "보안 스캔 접근 권한 없음 - 건너뜀" 출력 후 다음 Step으로 진행. 보안 스캔 실패가 전체 리뷰를 중단시키지 않습니다.

### Step 3: Detect PR Type

Analyze the changed files to determine the PR type. A PR can have multiple types.

**Detection Rules:**

| Type | File Extensions / Paths |
|------|------------------------|
| **iOS** | `.swift`, `.m`, `.h`, `.xib`, `.storyboard`, `.pbxproj`, `.plist`, `Podfile`, `.xcworkspace`, `.xcodeproj`, `Package.swift` |
| **Android** | `.kt`, `.java`, `.xml` (under `res/`), `build.gradle`, `.kts`, `AndroidManifest.xml`, `proguard-rules.pro` |
| **FrontEnd** | `.js`, `.jsx`, `.ts`, `.tsx`, `.vue`, `.svelte`, `.css`, `.scss`, `.less`, `.html`, `package.json`, `next.config`, `vite.config`, `webpack.config` |
| **BackEnd** | `.go`, `.py`, `.rb`, `.rs`, `.java` (under `src/main`), `.sql`, `Dockerfile`, `docker-compose`, `.env.example`, `requirements.txt`, `go.mod`, `Cargo.toml` |

If a file matches multiple types, assign the most specific one. If no type is detected, default to general code review.

### Step 4: Apply Review Priorities by Type

Read the review templates from `.claude/templates/review-criteria/` directory — load the matching platform file(s) based on detected PR type (e.g., `ios.md`, `frontend.md`). If no type is detected, use `general.md`. Apply the review criteria following the priority order defined in each template.

### Step 4.5: Impact Analysis (로컬 레포 일치 시 또는 원격 레포)

변경의 영향 범위를 분석합니다. **변경 파일이 20개 이하일 때만 실행합니다.** 초과 시 건너뛰고 Summary에 "영향도 분석 건너뜀 (대규모 PR)" 기록.

**로컬 레포 일치 시 (Glob/Grep 활용):**

1. **함수/메서드 호출자 추적**:
   - PR에서 시그니처가 변경된 public/internal 함수/메서드 식별 (파라미터 추가/삭제/타입 변경, 반환 타입 변경)
   - `Grep`으로 해당 함수명의 호출부 검색
   - 호출부가 PR에 포함되지 않으면 QUESTION 코멘트: "이 함수의 시그니처가 변경되었습니다. 다음 호출부에서도 수정이 필요한지 확인해주세요: {file:line 목록}"

2. **Breaking Change 감지**:
   - public 인터페이스/프로토콜의 메서드 추가/삭제/변경 감지
   - enum case 추가/삭제 (switch 문 영향)
   - 삭제된 export/public 심볼 목록 → WARNING 코멘트: "public API가 삭제되었습니다. 하위 호환성을 확인하세요."

3. **의존 파일 확인**:
   - 변경된 파일을 import/include/require하는 다른 파일 목록을 `Grep`으로 탐색
   - 영향받는 파일 수가 10개 이상이면: SUGGESTION "이 파일은 {N}개 파일에서 참조됩니다. 변경 영향을 신중히 확인하세요."

**원격 레포인 경우 (GitHub MCP 활용):**

1. `mcp__github__search_code`로 동일 레포 내에서 변경된 함수/클래스명 검색
2. 검색 결과에서 PR에 포함되지 않은 참조 파일 식별
3. 일관성이 깨지는 경우 SUGGESTION 코멘트

### Step 5: Decide on Gemini Code Review

Evaluate whether to recommend Gemini code review based on these criteria:
- **Recommend Gemini**: If the PR has more than 500 lines changed, touches security-sensitive code (auth, crypto, permissions), or involves complex algorithmic logic.
- **Skip Gemini**: For small PRs (<100 lines), documentation-only changes, or simple refactors.
- Output your recommendation with reasoning at the end of the review.

### Step 6: Display Review Results in CLI

리뷰 분석이 완료되면, **먼저 Claude Code 내에서 리뷰 결과를 출력**합니다. PR에 코멘트를 게시하기 전에 사용자가 결과를 확인할 수 있도록 합니다.

**6.1 리뷰 결과 출력:**

발견된 이슈를 severity 순서대로 (🚨 CRITICAL → ⚠️ WARNING → 💡 SUGGESTION → ❓ QUESTION → 🔹 NITPICK) 출력합니다:

`.claude/templates/review/templates.md` > `review_result` 템플릿으로 출력.

**6.2 PR 코멘트 게시 여부 확인:**

리뷰 결과 출력 후 사용자에게 `AskUserQuestion`으로 다음 옵션을 제시합니다:

- **전체 코멘트 게시**: 모든 코멘트를 그대로 PR에 게시
- **코멘트 선택 후 게시**: 게시할 코멘트를 개별 선택 (아래 6.2.1 참조)
- **코멘트 없이 종료**: CLI 출력만으로 리뷰 종료 (PR에 아무것도 남기지 않음)

**6.2.1 코멘트 개별 선택 (사용자가 "코멘트 선택 후 게시"를 선택한 경우):**

`AskUserQuestion`의 `multiSelect: true` 옵션을 사용하여 게시할 코멘트를 선택하도록 합니다.
각 코멘트를 번호와 함께 옵션으로 제시합니다:

- 각 옵션의 `label`: `#{번호} [{emoji} {severity}] {파일명}:{line}`
- 각 옵션의 `description`: 코멘트 내용 요약 (1줄)

**AskUserQuestion 제약 (options 최대 4개)에 따른 처리:**

- 코멘트가 4개 이하: 각 코멘트를 개별 옵션으로 제시
- 코멘트가 5개 이상: severity 그룹 단위로 옵션을 제시
  - 예: "🚨 CRITICAL 2건 모두 포함", "⚠️ WARNING 3건 모두 포함", "💡 SUGGESTION 2건 모두 포함"
  - 사용자가 그룹 단위로 포함/제외를 선택
  - 그룹 내 개별 제외가 필요하면 추가 `AskUserQuestion`으로 해당 그룹의 코멘트를 개별 나열

선택되지 않은 코멘트는 게시하지 않으며, Step 7 Summary의 "Excluded Comments" 섹션에 기록합니다.

**6.3 PR 코멘트 게시 (사용자 승인 시):**

1. **Create a pending review**: Use `mcp__github__create_pending_pull_request_review` to start a review.
2. **Add comments**: For each issue found, use `mcp__github__add_comment_to_pending_review` with:
   - `path`: The file path
   - `line`: The specific line number in the diff
   - `body`: The review comment (follow the comment format below)
3. **Submit the review**: Use `mcp__github__submit_pending_pull_request_review` with:
   - `event`: 아래 판정 매트릭스에 따라 결정:

     | 조건 | 판정 (event) |
     |------|-------------|
     | Secret scanning alert 발견 | `REQUEST_CHANGES` (무조건) |
     | 🚨 CRITICAL >= 1 | `REQUEST_CHANGES` |
     | 🚨 CRITICAL 0, ⚠️ WARNING >= 3 | `REQUEST_CHANGES` |
     | 🚨 CRITICAL 0, ⚠️ WARNING 1~2 | `COMMENT` |
     | 🚨 CRITICAL 0, ⚠️ WARNING 0, 💡 SUGGESTION만 존재 | `COMMENT` |
     | 이슈 없음 또는 🔹 NITPICK만 존재 | `APPROVE` |
     | Draft PR | `COMMENT` (APPROVE/REQUEST_CHANGES 금지) |

   - `body`: 판정 근거를 포함한 Summary (Step 7 참조)

### Comment Format

Each comment should follow `.claude/templates/review/templates.md` > `comment_format` 템플릿.

**Severity Emoji Map:**
- 🚨 CRITICAL
- ⚠️ WARNING
- 💡 SUGGESTION
- ❓ QUESTION
- 🔹 NITPICK

**GitHub Suggestion Block (수정 제안 시 필수 사용):**

CRITICAL 또는 WARNING 이슈에서 구체적인 코드 수정을 제안할 때는 반드시 `.claude/templates/review/templates.md` > `suggestion_block` 형식을 사용합니다.

**Suggestion 규칙:**
- suggestion 블록 안에는 해당 라인을 대체할 완전한 코드만 작성
- 설명은 suggestion 블록 바깥에 작성
- 여러 줄 수정 시 `start_line`과 `line` 파라미터를 활용하여 범위 지정
- suggestion 블록은 하나의 코멘트에 하나만 사용 (GitHub 제한)

**예시:** `.claude/templates/review/templates.md` > `comment_example` 참조.

**Severity Levels:**
- 🚨 `CRITICAL`: Must fix before merge (bugs, security issues, data loss risks)
- ⚠️ `WARNING`: Should fix, but not blocking (performance issues, code smells)
- 💡 `SUGGESTION`: Nice to have improvements (style, readability, best practices)
- ❓ `QUESTION`: Needs clarification from the author
- 🔹 `NITPICK`: Very minor style/preference issues

**Categories (by PR Type):**

Refer to `.claude/templates/review-criteria/` directory for type-specific categories (e.g., `ios.md`, `android.md`, `frontend.md`, `backend.md`, `general.md`).

### Step 7: Review Summary

After posting all comments, provide a summary in the review body using `.claude/templates/review/templates.md` > `review_summary` 템플릿.

### Step 8: Review Pattern Recording

리뷰 결과를 기록하여 향후 리뷰 품질을 개선합니다. 로컬 레포 또는 repo-cache가 있는 경우에만 실행합니다.

1. **review-priorities.md 업데이트**:
   - `.claude/repo-cache/{owner}/{repo}/review-priorities.md` 파일이 존재하면:
   - "자주 발견되는 이슈 패턴" 섹션에 이번 리뷰의 CRITICAL/WARNING 이슈 카테고리를 append
   - 동일 카테고리가 이미 있으면 횟수 카운트 증가
   - 형식: `- [{카테고리}] {이슈 요약} (발견 횟수: N회)`

2. **review-notes.md 히스토리 기록**:
   - `.claude/repo-cache/{owner}/{repo}/review-notes.md` 파일에 append:
   ```
   ## PR #{pr_number} - {pr_title}
   - Date: {YYYY-MM-DD}
   - Type: {detected types}
   - Verdict: {APPROVE/COMMENT/REQUEST_CHANGES}
   - Critical: {count}, Warning: {count}, Suggestion: {count}
   - Key Issues: {top 3 이슈 한줄 요약}
   ```

3. **로컬 레포인 경우**: 위 파일 경로를 `.claude/repo-cache/{owner}/{repo}/` 대신 프로젝트 루트의 `.claude/review-history/` 아래에 기록

**참고**: 이 Step은 자동 실행됩니다. 파일 쓰기 실패 시 조용히 건너뜁니다.
