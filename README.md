# Review Command for Claude Code

Claude Code에서 사용할 수 있는 PR 리뷰 자동화 글로벌 커맨드 모음입니다.

> **글로벌 커맨드**: 이 커맨드들은 `~/.claude/commands/`에 설치되어 **모든 프로젝트에서 사용 가능**합니다. 프로젝트별 오버라이드도 지원됩니다.
>
> **필수 조건**: `/pr-review`와 `/apply-review`는 **GitHub MCP 서버**가 프로젝트의 `.mcp.json`에 설정되어 있어야 동작합니다. `/create-pr`은 GitHub MCP를 우선 사용하되, 없거나 실패하면 사용자 승인 후 `gh` CLI로 폴백합니다. 아래 [설정](#설정) 섹션을 먼저 확인하세요.

## 목차

- [Why GitHub MCP?](#why-github-mcp)
- [커맨드 목록](#커맨드-목록)
- [/commit](#commit)
- [/create-pr](#create-pr)
- [/pr-review](#pr-review)
  - [코멘트 선택 게시](#코멘트-선택-게시)
  - [외부 레포지토리 분석](#외부-레포지토리-분석)
  - [재리뷰 감지](#재리뷰-감지)
  - [code-review-graph 통합](#code-review-graph-통합)
  - [토큰 최적화](#토큰-최적화)
- [/apply-review](#apply-review)
- [/ship](#ship)
  - [단계와 정지 조건](#단계와-정지-조건)
  - [Draft 유지 순서](#draft-유지-순서)
  - [진행 상태 판정](#진행-상태-판정)
  - [게이트 자동 감지](#게이트-자동-감지)
  - [보호 브랜치에서 시작할 때](#보호-브랜치에서-시작할-때)
- [의존성](#의존성)
- [설정](#설정)
  - [필수 요구사항](#필수-요구사항)
  - [글로벌 디렉토리 구조](#글로벌-디렉토리-구조)
  - [커스터마이징](#커스터마이징)

---

## Why GitHub MCP?

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

### 인라인 코멘트와 Pending Review

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

---

## 커맨드 목록

| 커맨드 | 설명 |
|--------|------|
| `/commit [옵션]` | 변경사항과 기존 커밋 컨벤션을 분석해 gitmoji·Conventional Commits 형식의 커밋 생성 |
| `/commit --help` | `/commit` 옵션·동작 절차 도움말 표시 |
| `/create-pr [--open] [base=<branch>]` | 현재 브랜치 변경 내용을 분석해 PR 템플릿에 맞춰 Draft PR 생성 |
| `/pr-review <PR_URL>` | PR 코드 리뷰 수행 및 GitHub 인라인 코멘트 게시 |
| `/pr-review --help` | `/pr-review` 도움말 표시 |
| `/apply-review <PR>` | PR 리뷰 코멘트를 로컬 코드에 반영 |
| `/apply-review --help` | `/apply-review` 도움말 표시 |
| `/ship [설명] [옵션]` | 구현부터 병합까지 7단계 파이프라인을 순서대로 수행 (위 커맨드들을 조합) |
| `/ship --help` | `/ship` 도움말 표시 |

---

## /commit

스테이징된 변경과 **이 레포의 기존 커밋 컨벤션**을 분석해 커밋 메시지를 만들고 커밋합니다. gitmoji와 Conventional Commits 형식을 지원하며, push는 절대 자동 실행하지 않습니다.

### 사용법

```
/commit [-G|--no-gitmoji] [-g|--gitmoji] [-C|--no-coauthor] [-a|--all] [-e|--amend] [-S|--no-split] [-y|--yes] [-h|--help]
```

### 예시

```
/commit                  # 컨벤션 감지 → 메시지 생성 → 미리보기 후 커밋
/commit --gitmoji        # 컨벤션이 이모지를 안 써도 gitmoji 강제
/commit --no-gitmoji     # gitmoji 없이
/commit -ay              # = --all --yes (전체 스테이징 + 미리보기 생략)
/commit --amend          # 직전 커밋 수정
/commit --no-coauthor    # Co-Authored-By 푸터 제거
```

### 옵션

> 별칭 규칙: **소문자 = 동작 켜기, 대문자 = 끄기/제거(`--no-*`)**. 묶어 쓰기 가능(예: `-ay` = `--all --yes`).

| 옵션 | 짧은 별칭 | 설명 |
|------|------|------|
| `--no-gitmoji` | `-G` | gitmoji를 절대 붙이지 않음 (최우선) |
| `--gitmoji` | `-g` | 컨벤션이 이모지를 안 써도 gitmoji 강제 |
| `--no-coauthor` | `-C` | `Co-Authored-By: Claude ...` 푸터 제거 (기본은 유지) |
| `--all` | `-a` | 스테이징된 변경이 없을 때 확인 없이 `git add -A` 후 진행 |
| `--amend` | `-e` | 새 커밋 대신 직전 커밋 수정 (푸시된 경우 경고) |
| `--no-split` | `-S` | 변경이 섞여 있어도 커밋 분리를 제안하지 않고 단일 커밋 |
| `--yes` | `-y` | 커밋 전 미리보기 확인 생략 (민감 파일 경고는 유지) |
| `--help` | `-h` | 옵션 설명·동작 절차를 출력하고 종료 (커밋하지 않음) |

### gitmoji 사용 여부 우선순위

| 우선순위 | 조건 | 결과 |
|---------|------|------|
| 1 | `--no-gitmoji` 인자 | 사용 안 함 |
| 2 | `--gitmoji` 인자 | 사용 |
| 3 | 기존 커밋이 이모지를 **일관되게 사용** | 사용 |
| 3 | 기존 커밋이 이모지를 **안 씀** | 사용 안 함 |
| 4 | 컨벤션 불명확 / 히스토리 거의 없음 | 기본값 ON |

> gitmoji를 쓰기로 결정됐는데 CLI가 없으면 설치 여부를 묻고, 승인 시 `brew install gitmoji`(없으면 `npm i -g gitmoji-cli`)로 설치합니다. 메시지에는 유니코드 이모지 문자(`✨`)를 직접 넣습니다.

### 실행 절차

1. 변경 / 스테이징 상태 파악 (스테이징 없으면 확인, 보호 브랜치 경고)
2. 기존 커밋 컨벤션 분석 (형식·이모지·언어·본문·scope·co-author 패턴)
3. gitmoji 사용 여부 결정 (위 우선순위, 필요 시 CLI 설치)
4. 커밋 분리 판단 (여러 논리 단위면 분리 제안, `--no-split`로 생략)
5. 메시지 생성 (`[emoji ]type(scope): 요약` + 선택적 본문 + Co-Authored-By 푸터)
6. 미리보기 + 사용자 확인 (`--yes`면 생략)
7. 커밋 실행 (`git commit -F -`, `--amend` 지원, pre-commit hook 존중)
8. SHA / 변경 파일 / gitmoji·co-author 여부 / 다음 단계 보고

### 안전 규칙

- push, force push, 브랜치 checkout/생성, reset/rebase는 사용자 확인 없이 절대 자동 실행하지 않음 (커밋까지만)
- `.env`, `*.key`, `*.pem`, `credentials*` 등 민감 파일이 스테이징에 포함되면 경고 후 진행 여부 확인 (`--yes`여도 유지)
- API 키·토큰·비밀번호가 diff에 보이면 경고하고 메시지에 인용하지 않음
- 보호 브랜치(`main`/`master`/`develop`) 직접 커밋 시 경고

---

## /create-pr

현재 브랜치의 커밋과 diff를 분석해 프로젝트 PR 템플릿에 맞춰 PR을 생성합니다. 기본은 **Draft**, `--open` 인자를 주면 **Open** 상태로 만듭니다.

### 사용법

```
/create-pr [--open] [base=<branch>]
```

### 예시

```
/create-pr
/create-pr --open
/create-pr base=main
/create-pr --open base=develop
```

### 옵션

| 옵션 | 설명 |
|------|------|
| `--open` (또는 `open`) | Draft 대신 Open 상태로 PR 생성 |
| `base=<branch>` | base 브랜치를 강제로 지정 (예: `base=main`) |
| (인자 없음) | Draft 모드 + 자동 base 추론 |

### 실행 절차

1. 현재 브랜치 / 커밋 / 푸시 상태 파악 (보호 브랜치 차단)
2. Base 브랜치 결정 (인자 → `CLAUDE.md`/`AGENTS.md` 명시 → `origin/develop` → `origin/main`/`master` 순)
3. 변경 내역 분석 (`origin/<base>..HEAD` 커밋과 diff 수집)
4. 원격 푸시 확인 및 필요 시 `git push -u` (사용자 확인 후, force push는 금지)
5. PR 템플릿 로드 (`.github/PULL_REQUEST_TEMPLATE.md` 등 여러 경로 순차 탐색, 없으면 기본 본문)
6. 본문 작성: 커밋 prefix(`feat:`/`fix:`/`refactor:`/`update:`) 기반 분류, HTML 주석 유지, 데모 자리 비움
7. PR 생성 (`mcp__github__create_pull_request` 우선, 실패 시 사용자 승인 후 `gh pr create` 폴백)
8. URL / Draft·Open 상태 / base ← head / 커밋 수 / 변경 파일 / 다음 단계 보고

### Base 브랜치 자동 추론

| 우선순위 | 조건 |
|---------|------|
| 1 | 인자에 `base=<branch>` 명시 |
| 2 | `CLAUDE.md` / `AGENTS.md`에 "PR 대상", "base branch", "기본 브랜치" 표기 존재 |
| 3 | `origin/develop` 존재 (Git-flow 컨벤션) |
| 4 | `origin/main` → `origin/master` 순서로 폴백 |

### PR 템플릿 탐색 경로

1. `.github/PULL_REQUEST_DESCRIPTION_TEMPLATE.md`
2. `.github/PULL_REQUEST_TEMPLATE.md`
3. `.github/pull_request_template.md`
4. `.github/PULL_REQUEST_TEMPLATE/*.md` (여러 개면 첫 번째)
5. `docs/PULL_REQUEST_TEMPLATE.md`
6. `docs/pull_request_template.md`
7. `PULL_REQUEST_TEMPLATE.md`
8. `pull_request_template.md`

발견되지 않으면 `🎯 요약 / 📋 작업 배경 / 🔧 변경 사항` 섹션만 가진 최소 본문을 사용합니다.

### 안전 규칙

- 현재 브랜치가 `main` / `master` / `develop` 같은 보호 브랜치면 PR 생성을 중단
- 동일 head→base 조합으로 이미 Open된 PR이 있으면 (`mcp__github__list_pull_requests` 또는 `gh pr list --head`) 신규 생성 대신 기존 URL을 안내
- `.env`, `*.key`, `credentials*` 등 민감 파일이 변경에 포함되면 사용자에게 경고 후 진행 여부 확인
- force push, base 브랜치 직접 commit, 다른 브랜치 checkout, 기존 PR 수정/머지/클로즈는 사용자 확인 없이 절대 수행하지 않음
- 본문에 사용자/동료의 개인정보 · API 키 · 토큰을 인용하지 않음

---

## /pr-review

PR의 변경 사항을 분석하고, GitHub에 인라인 리뷰 코멘트를 자동으로 게시합니다.

### 사용법

```
/pr-review <PR_URL> [options]
```

### 예시

```
/pr-review https://github.com/owner/repo/pull/123
/pr-review https://github.com/owner/repo/pull/123 --mode=strict
/pr-review https://github.com/owner/repo/pull/123 --focus=security,performance
```

### 옵션

| 옵션 | 설명 |
|------|------|
| `--mode=strict` | 모든 severity 코멘트 생성, WARNING 2개 이상이면 REQUEST_CHANGES |
| `--mode=normal` | 표준 판정 매트릭스 적용 (기본값) |
| `--mode=relaxed` | CRITICAL만 코멘트, 나머지는 Summary에만 기록 |
| `--focus=항목,...` | 지정 카테고리만 집중 리뷰 (예: security,performance,memory) |
| `--skip=항목,...` | 지정 severity/카테고리 건너뛰기 (예: nitpick,style) |
| `--help` | `/pr-review` 도움말 표시 |

### 리뷰 프로세스

1. PR URL 파싱 + 상태 확인 (draft/merged/CI)
2. GitHub MCP를 통해 PR 정보 수집 (기존 리뷰 중복 방지, 재리뷰 감지)
3. 보안 스캔 (Secret/Code/Dependabot alerts)
4. 레포지토리 컨텍스트 분석 (로컬 일치 시 자동, 외부 레포 시 사용자 선택)
   - **code-review-graph 감지 시**: AST 기반 구조 분석 자동 활용
5. 변경 파일 확장자로 PR 타입 감지 (iOS/Android/FrontEnd/BackEnd)
6. 타입별 우선순위에 따라 코드 리뷰
   - **code-review-graph 감지 시**: 구조적 리뷰 컨텍스트 + blast radius 분석
7. CLI에 리뷰 결과 출력 → 사용자가 게시할 코멘트를 선택
8. GitHub PR에 선택된 인라인 코멘트 게시
9. 리뷰 결과 기록

### Severity 레벨

| Emoji | Level | 설명 |
|-------|-------|------|
| 🚨 | `CRITICAL` | 머지 전 반드시 수정 (버그, 보안, 데이터 손실) |
| ⚠️ | `WARNING` | 수정 권장 (성능, 코드 스멜) |
| 💡 | `SUGGESTION` | 개선 제안 (가독성, 베스트 프랙티스) |
| ❓ | `QUESTION` | 작성자에게 확인 필요 |
| 🔹 | `NITPICK` | 사소한 스타일 이슈 |

### 판정 매트릭스

| 조건 | 판정 |
|------|------|
| Secret alert 발견 | REQUEST_CHANGES (무조건) |
| CRITICAL >= 1 | REQUEST_CHANGES |
| WARNING >= 3 (normal) / >= 2 (strict) | REQUEST_CHANGES |
| WARNING 1~2 | COMMENT |
| SUGGESTION만 | COMMENT |
| 이슈 없음 / NITPICK만 | APPROVE |
| Draft PR | COMMENT (고정) |

### 코멘트 선택 게시

리뷰 결과가 CLI에 출력된 후, 게시 방식을 선택할 수 있습니다:

| 옵션 | 설명 |
|------|------|
| **전체 코멘트 게시** | 모든 리뷰 코멘트를 그대로 PR에 게시 |
| **코멘트 선택 후 게시** | 게시할 코멘트를 개별 선택 (체크박스) |
| **코멘트 없이 종료** | CLI 출력만으로 리뷰 종료 |

"코멘트 선택 후 게시"를 선택하면:
- 코멘트 4개 이하: 각 코멘트를 개별 체크박스로 선택
- 코멘트 5개 이상: severity 그룹 단위 선택 → 필요 시 그룹 내 개별 제외

### 외부 레포지토리 분석

PR이 현재 프로젝트와 다른 레포지토리인 경우, 캐시 유무에 따라 적절한 옵션만 노출됩니다:

**캐시가 없는 경우:**

| 옵션             | 설명                                                      |
| -------------- | ------------------------------------------------------- |
| **분석 없이 진행**   | PR diff만으로 리뷰                                           |
| **레포 분석 후 진행** | CLAUDE.md, README 등을 가져와 `.claude/repo-cache/`에 저장 후 리뷰 |

**캐시가 있는 경우:**

| 옵션              | 설명                                |
| --------------- | --------------------------------- |
| **분석 없이 진행**    | PR diff만으로 리뷰                     |
| **기존 캐시 참조**    | 이전에 저장된 분석 문서 활용 (30일 경과 시 갱신 안내) |
| **캐시 삭제 후 재분석** | 기존 캐시 초기화 후 새로 분석                 |

### 재리뷰 감지

동일 PR에 현재 사용자의 이전 리뷰가 있으면 자동으로 감지하여 옵션을 제시합니다:

- **증분 리뷰**: 이전 리뷰 이후 추가된 커밋만 리뷰
- **전체 리뷰**: PR 전체를 처음부터 다시 리뷰

### 지원 플랫폼

- **iOS**: `.swift`, `.m`, `.xib`, `.pbxproj` 등
- **Android**: `.kt`, `.java`, `build.gradle` 등
- **FrontEnd**: `.ts`, `.tsx`, `.vue`, `.css` 등
- **BackEnd**: `.go`, `.py`, `.rs`, `Dockerfile` 등

### code-review-graph 통합

[code-review-graph](https://github.com/tirth8205/code-review-graph)가 설치되고 그래프가 빌드된 프로젝트에서는 자동으로 AST 기반 정밀 분석을 활용합니다. 설치되지 않은 경우 기존 Grep/Glob 방식으로 폴백합니다.

| 기능 | graph 없음 (기존) | graph 있음 (강화) |
|------|-------------------|-------------------|
| **영향 분석** | Grep 문자열 검색 | AST call graph BFS 탐색 |
| **호출자 추적** | 함수명 텍스트 매칭 | `callers_of` 정확한 호출 관계 |
| **테스트 커버리지** | 확인 불가 | `tests_for`로 테스트 유무 검증 |
| **Blast Radius** | 수동 추정 | 자동 계산 (depth, node count) |
| **대규모 함수 탐지** | 없음 | `find_large_functions` 자동 감지 |

**설치 방법:**
```bash
pip install code-review-graph
code-review-graph install
# 프로젝트에서 그래프 빌드
code-review-graph build
```

설치 후 별도 설정 없이 `/pr-review` 실행 시 자동 감지됩니다.

### 토큰 최적화

`/pr-review` 커맨드는 토큰 효율성을 위해 `~/.claude/agents/`에 정의된 전용 서브에이전트를 활용하여 모델을 강제 분기합니다.

**전용 서브에이전트:**

| 에이전트 | 모델 (frontmatter 고정) | 상대 비용 | 용도 |
|---------|----------------------|----------|------|
| `review-diff-reader` | **Haiku** | 1x | diff 파싱, 파일별 변경 요약, 함수명 추출 |
| `review-analyzer` | **Sonnet** | 4x | 리뷰 기준 적용, 인라인 코멘트 생성 |
| `review-security` | **Opus** | 19x | 보안 취약점 심층 분석 (필요 시에만) |

에이전트 정의 파일의 `model` frontmatter로 모델이 고정되므로, 지시문 수준이 아닌 **시스템 레벨에서 강제 적용**됩니다.

**실행 흐름 (변경 라인 500줄 이상 PR):**
```
1. review-diff-reader (Haiku)  → diff 요약 생성
2. review-analyzer (Sonnet)    → 요약 기반으로 인라인 코멘트 생성
3. review-security (Opus)      → 보안 관련 변경이 있을 때만 병렬 실행
```

**최적화 원칙:**
- **메인 세션은 Sonnet**으로 실행, 서브에이전트 레벨에서만 모델 분기
- **파일 읽기는 Haiku 서브에이전트**에 위임 → 요약만 메인 세션에 반환 (컨텍스트 격리)
- **보안 관련 변경이 있을 때만** Opus 에이전트 생성 (불필요 시 생략)
- **독립 태스크는 병렬 실행** (보안 스캔 3종 동시 호출, 분석 에이전트 background 실행)
- **code-review-graph 선활용** — 파일을 직접 읽기 전에 구조 요약(~200토큰)으로 대체

---

## /apply-review

PR에 달린 리뷰 코멘트를 분석하여 로컬 코드에 자동으로 반영합니다.

### 사용법

```
/apply-review <PR_NUMBER_OR_URL> [options]
```

### 예시

```
/apply-review 32
/apply-review https://github.com/owner/repo/pull/32
/apply-review 32 --reviewer=octocat
/apply-review 32 --auto-commit
```

### 옵션

| 옵션 | 설명 |
|------|------|
| `--reviewer=username` | 특정 리뷰어의 코멘트만 반영 |
| `--auto-commit` | 확인 없이 자동 커밋 (push는 여전히 확인) |
| `--branch=name` | 변경 사항을 새 브랜치에 적용 |
| `--help` | `/apply-review` 도움말 표시 |

### 반영 프로세스

1. PR 정보 수집 + 브랜치/레포지토리 검증
2. 이전 반영 기록 확인 (증분/전체/제외항목 재확인)
3. 리뷰 코멘트 수집 및 분류
4. AI 합당성 판단
5. 사용자 확인 (전체 진행/전체 취소/개별 선택)
6. 대규모 변경 감지 + 브랜치 분리 제안
7. 코멘트 반영 (병렬 agent 활용)
8. 반영 결과 검증
9. 커밋 / Push / PR 생성 옵션
10. 리뷰 코멘트별 답글 작성 옵션 (초안 확인 후 게시)
11. 반영 기록 저장

### 리뷰 코멘트 답글

반영 결과를 PR 전체 코멘트 하나로 모으지 않고, **원래 리뷰 코멘트 스레드에 답글**로 남깁니다.

| 경우 | 답글 내용 |
|------|----------|
| 반영함 | ✅ 반영 내용 1~2줄 + 커밋 링크 |
| 반영하지 않음 | ⏭️ 이유 1~2줄 |
| 질문 | 💬 코드 컨텍스트 기반 답변 |

- 게시 전 답글 초안을 표로 보여주고 확인받습니다. INFO·칭찬 코멘트에는 답글을 달지 않습니다.
- 인라인 코멘트는 `gh api`로 스레드 답글을 게시하고, 답글 스레드가 없는 리뷰 본문·일반 코멘트는 원문 인용과 함께 PR 코멘트로 게시합니다.
- 반영 기록은 `~/.claude/review-history/{owner}/{repo}/apply-review-pr-{number}.json`에 저장됩니다.

### AI 판정

| 판정         | 설명                       |
| ---------- | ------------------------ |
| ✅ AGREE    | 동의 — 코멘트대로 반영            |
| 🔶 PARTIAL | 부분 동의 — AI 대안으로 반영       |
| ❌ DISAGREE | 반대 — 반영 비추천 (사용자가 강제 가능) |
| ⏭️ SKIP    | 건너뜀 — 질문/정보성 코멘트         |

### 증분 반영

동일 PR에 대해 `/apply-review`를 재실행하면 이전 반영 기록을 감지하여 옵션을 제시합니다:

- **증분 반영**: 이전 반영 이후 새로 추가된 코멘트만 반영
- **처음부터 다시 확인**: 모든 코멘트를 대상으로 전체 프로세스 진행
- **이전 제외 항목만 재확인**: DISAGREE/SKIP이었던 코멘트만 재판단

---

## /ship

작업을 **구현부터 병합까지** 한 번에 흘려보냅니다. 2~5단계는 위 커맨드들을 재구현하지 않고 그대로 호출합니다.

```
1. 구현        2. /commit      3. /create-pr(Draft)   4. /pr-review
5. /apply-review   6. Ready 전환(CI)   7. 병합
```

### 사용법

```
/ship [작업 설명] [--loop=N] [--from=N] [--stop-at=N] [--base=<branch>] [--branch=<name>] [--no-cleanup] [--post] [-y|--yes] [-h|--help]
```

인자 없이 호출하면 현재 브랜치 상태를 판정해 **다음에 해야 할 단계부터** 이어서 진행합니다.

### 예시

```
/ship                        # 현재 상태 판정 → 다음 단계부터 끝까지
/ship "W6 App 조립"          # 작업 설명을 주고 1단계부터
/ship --from=4               # 리뷰 단계부터 재개 (실패 후 이어받기)
/ship --stop-at=6            # Ready 전환까지만, 병합은 하지 않음
/ship --loop=10              # 구현을 지속 반복 모드로 최대 10회
/ship --post                 # 병합 후 진행 문서 갱신·실기기 체크리스트까지
```

### 옵션

| 옵션 | 짧은 별칭 | 설명 |
|------|------|------|
| `--loop=N` | | 1단계(구현)를 지속 반복 모드로, 최대 N회. **미지정이 기본**(직접 구현) |
| `--from=N` | | N단계부터 재개 |
| `--stop-at=N` | | N단계까지만 수행 |
| `--base=<branch>` | | base 브랜치 지정 (기본: 자동 추론) |
| `--branch=<name>` | | 작업 브랜치 이름 지정 (기본: 기존 병합 이력에서 패턴을 뽑아 제안) |
| `--no-cleanup` | | 병합 후 브랜치 삭제 생략 |
| `--post` | | 병합 후 진행 문서 갱신·실기기 체크리스트 출력 |
| `--yes` | `-y` | 병합 직전 확인 생략 |
| `--help` | `-h` | 도움말을 출력하고 종료 (아무것도 실행하지 않음) |

### 단계와 정지 조건

| # | 단계 | 게이트 | 실패 시 |
|---|------|--------|---------|
| 0 | 사전 점검 | 보호 브랜치 아님 | 중단 |
| 1 | 구현 | 빌드·테스트·린트 통과 | **중단** |
| 2 | `/commit` | 관심사·계층별 분리 | — |
| 3 | `/create-pr` | **항상 Draft 로 생성** | 중단 |
| 4 | `/pr-review` | — | — |
| 5 | `/apply-review` | 반영 후 게이트 재통과 | **중단** |
| 6 | Ready 전환 | CI green | **중단** + 실패 로그 |
| 7 | 병합 | CI green 재확인 | 중단 |

게이트 실패·CI red·리뷰 CRITICAL·merge conflict 중 하나라도 있으면 **그 단계에서 멈추고** 다음으로 넘어가지 않습니다. 중단 시 `--from=N` 재개 방법을 함께 알립니다.

**병합(7단계)은 `--yes` 가 없으면 직전에 확인**합니다. 되돌리기 비용이 가장 큰 단계이기 때문입니다.

### Draft 유지 순서

`/ship` 이 PR 을 **항상 Draft 로 만드는** 이유입니다.

CI 가 Draft PR 을 건너뛰는 설정이면, Ready 전환 후의 모든 push 가 CI 를 재실행시킵니다(`synchronize`).

```
잘못된 순서: 생성 → Ready → 리뷰 → 반영(push) → CI 2회
/ship 의 순서: 생성(Draft) → 리뷰 → 반영 → Ready → CI 1회
```

3~5단계를 Draft 에서 끝내고 6단계에서 한 번만 Ready 로 올리므로 CI 가 1회로 끝납니다. CI 1회가 10분을 넘는 프로젝트에서 차이가 큽니다.

### 진행 상태 판정

상태 파일을 만들지 않습니다. 매 단계 시작 전 **git·GitHub 에 직접 물어** 어디까지 됐는지 판정합니다.

| 판정 | 근거 |
|------|------|
| 구현·커밋 완료 | 워킹트리 clean **그리고** `<base>..HEAD` 에 커밋 존재 |
| PR 생성됨 | `list_pull_requests(head: 현재 브랜치, state: open)` |
| 리뷰 완료 | 그 PR 에 자체 리뷰 결과 코멘트 존재 |
| Ready 상태 | PR 의 `draft` 필드 |
| CI 결과 | `list_workflow_jobs(run_id)` 의 `conclusion` |

상태 파일은 반드시 실제 진행과 어긋나므로 쓰지 않습니다. 사람이 중간에 손댄 것도 그대로 인식됩니다.

**인자와 실물이 어긋나면 실물을 신뢰합니다.** `--from=N` 으로 지정한 단계의 선행 조건이 충족되지 않으면 중단하고 무엇이 빠졌는지 알립니다(예: `--from=4` 인데 열린 PR 이 없음 → "3단계가 먼저 필요하다").

### 게이트 자동 감지

`.github/workflows/*.yml` 에서 **CI 가 실제로 실행하는 명령**을 추출해 로컬 게이트로 씁니다. CI 와 같은 것을 먼저 돌리므로 6단계 CI 실패를 앞당겨 잡습니다.

추출한 명령은 **준비**(checkout·툴체인 선택·의존성 설치·프로젝트 생성·캐시)와 **검증**(lint·format·build·test)으로 나눕니다. 준비는 로컬에 이미 갖춰져 있으면 건너뛰고, 검증은 항상 실행합니다. `|| true` 가 붙은 명령은 실패해도 통과하므로 게이트에서 제외합니다.

**docs-only 변경이면 빌드·테스트를 돌리지 않습니다.** CI 조차 건너뛰는 변경에 로컬 빌드를 돌릴 이유가 없습니다. 대신 **문서 게이트**를 씁니다 — HTML 태그 균형·목차 앵커 정합, Markdown 상대 링크의 대상 존재 여부. 문서도 깨집니다.

감지 실패 시 `package.json` scripts·`Makefile`·`CLAUDE.md` 순으로 찾고, 그래도 없으면 사용자에게 묻습니다. 끝내 없으면 **게이트 없이 진행하되 그 사실을 명시**합니다.

### 보호 브랜치에서 시작할 때

작업은 늘 `main` 에서 시작하므로, 보호 브랜치라고 무조건 멈추면 커맨드를 쓸 수 없습니다. **시작 단계에 따라 갈립니다.**

| 시작 단계 | 의미 | 동작 |
|-----------|------|------|
| 1~2 (구현·커밋) | 정상 | **작업 브랜치를 만든다** |
| 3 이상 | 이상 — PR 브랜치가 체크아웃돼 있어야 한다 | **중단** |

브랜치 이름은 `--branch` → 없으면 `git log --merges` 의 기존 브랜치명에서 패턴을 뽑아 제안하고 확인받습니다(`--yes` 면 제안값 사용). 병합된 브랜치는 삭제돼 `git branch -r` 에 없지만 **병합 커밋 메시지에는 남아 있습니다.**

보호 브랜치에 커밋하지 않는 것이 목적이지, 멈추는 것이 목적이 아닙니다.

### 보고 규칙

- 리뷰 단계에서 **작성자와 리뷰어가 동일**하다는 사실을 리뷰 결과와 PR 코멘트에 명시합니다. 변경 500줄 초과면 외부 리뷰어를 권고합니다.
- 스크린샷·실기기 검증처럼 자동으로 확인할 수 없는 것은 **미수행이라고 적습니다**. 비워두고 넘어가지 않습니다.
- 게이트 실패를 우회하려고 테스트를 지우거나 약화시키지 않습니다.

---

## 의존성

이 커맨드들의 필수/선택 의존성을 정리합니다.

| 항목 | 필수 여부 | 설명 |
|------|----------|------|
| **GitHub MCP 서버** | `/pr-review`·`/apply-review` 필수 / `/create-pr` 선택 | PR 정보 수집·코멘트 게시에 사용. 프로젝트 `.mcp.json`에 설정(`examples/mcp.json.example` 복사). `/create-pr`은 미설정·실패 시 `gh` CLI로 폴백 |
| **`GITHUB_PERSONAL_ACCESS_TOKEN`** | GitHub MCP 사용 시 필수 | GitHub API 인증용 환경변수 |
| **`gh` CLI** | `/apply-review` 답글 게시 시 필요 / `/create-pr` 폴백 시 필요 | `/apply-review`의 리뷰 코멘트 스레드 답글 게시, GitHub MCP 불가 시 `/create-pr`의 PR 생성 폴백 경로. `gh auth login` 인증 필요 |
| **`~/.claude/commands/`** | 필수 | 글로벌 커맨드 정의 파일 (`commit.md`, `create-pr.md`, `pr-review.md`, `apply-review.md`, `ship.md`) |
| **`/commit`·`/create-pr`·`/pr-review`·`/apply-review`** | `/ship` 필수 | `/ship`은 2~5단계에서 이 커맨드들을 재구현하지 않고 그대로 호출한다 |
| **`~/.claude/templates/`** | 필수 | 출력 템플릿 및 플랫폼별 리뷰 기준 |
| **oh-my-claudecode (OMC)** | 불필요 | `/pr-review`, `/apply-review`는 OMC와 독립적으로 동작. OMC 설치 여부와 무관하게 사용 가능 |
| **code-review-graph** | 선택 | 설치+그래프 빌드 시 AST 기반 정밀 분석 자동 활용. 미설치 시 기존 Grep/Glob 방식으로 폴백 |

> **OMC와의 관계**: OMC는 Claude Code의 멀티 에이전트 오케스트레이션 플러그인으로, `/pr-review` 커맨드와는 완전히 별개입니다. OMC가 제공하는 `/oh-my-claudecode:code-review`는 OMC 자체의 코드 리뷰 기능이며, 이 프로젝트의 `/pr-review`와는 다른 도구입니다.
>
> **code-review-graph와의 관계**: code-review-graph가 Claude Code 플러그인으로 설치되고 MCP 서버가 연결되면, `/pr-review` 실행 시 자동으로 감지하여 blast radius 분석, 테스트 커버리지 확인, 정밀 호출자 추적 등을 수행합니다. 별도 설정 없이 "있으면 활용, 없으면 기존 방식" 으로 동작합니다.

---

## 설정

### 필수 요구사항

1. **GitHub MCP 서버**가 `.mcp.json`에 설정되어 있어야 합니다 (`/pr-review`·`/apply-review` 필수, `/create-pr`은 없으면 `gh` CLI로 폴백)
2. `GITHUB_PERSONAL_ACCESS_TOKEN` 환경 변수에 PR 접근 권한이 있는 토큰이 필요합니다
3. GitHub MCP 서버를 Docker 이미지로 실행하므로 **Docker**가 필요합니다

`.mcp.json`은 개인 설정이라 저장소에 커밋하지 않습니다(`.gitignore` 대상). 예시 파일을 복사해 사용하세요.

```bash
cp examples/mcp.json.example .mcp.json
```

> **기존 clone 사용자**: 이전 버전은 `.mcp.json`을 저장소에서 추적했습니다. 이 변경 이후 `git pull`하면 git이 로컬 `.mcp.json`을 삭제하므로, **pull 전에 백업**(`cp .mcp.json .mcp.json.bak`)한 뒤 pull 후 다시 복원하세요.

[`examples/mcp.json.example`](examples/mcp.json.example) 내용:
```json
{
  "mcpServers": {
    "github": {
      "type": "stdio",
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "-e",
        "GITHUB_PERSONAL_ACCESS_TOKEN",
        "ghcr.io/github/github-mcp-server"
      ],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_PERSONAL_ACCESS_TOKEN}"
      }
    }
  }
}
```

> 토큰은 파일에 직접 적지 말고 환경 변수로만 주입하세요. 다른 MCP 서버를 추가하는 것은 자유이며, `.mcp.json`이 커밋되지 않으므로 개인 경로를 넣어도 저장소에 노출되지 않습니다.

### 글로벌 디렉토리 구조

```
~/.claude/
├── commands/                        # 글로벌 커맨드 정의
│   ├── create-pr.md
│   ├── pr-review.md
│   └── apply-review.md
├── templates/
│   ├── review-criteria/             # 리뷰 기준 (커스터마이징 권장)
│   │   ├── ios.md
│   │   ├── android.md
│   │   ├── frontend.md
│   │   ├── backend.md
│   │   ├── general.md
│   │   └── README.md               # 가이드 문서
│   ├── review/                      # /pr-review 출력 형식 (선택적 커스터마이징)
│   │   └── templates.md
│   └── apply-review/                # /apply-review 출력 형식 (선택적 커스터마이징)
│       └── templates.md
├── review-history/                  # 리뷰/반영 이력 (자동 생성)
│   └── {owner}/{repo}/
├── repo-cache/                      # 외부 레포 분석 캐시 (자동 생성)
│   └── {owner}/{repo}/
└── settings.json                    # 글로벌 권한 설정
```

> **프로젝트 오버라이드**: 특정 프로젝트의 `.claude/commands/`에 동일 이름의 커맨드 파일을 배치하면 글로벌 커맨드를 오버라이드할 수 있습니다.

### 커스터마이징

#### 리뷰 기준 커스텀

`.claude/templates/review-criteria/` 디렉토리의 플랫폼별 파일을 편집하여 리뷰 기준을 자유롭게 조정할 수 있습니다.

각 파일은 **우선순위 테이블**, **플랫폼별 체크리스트**, **보안 체크리스트** 3개 섹션으로 구성되어 있으며, 프로젝트 특성에 맞게 다음과 같이 커스텀할 수 있습니다:

- **우선순위 변경**: 테이블의 Priority 순서를 조정하여 중요도를 재배치
- **항목 추가/제거**: 프로젝트에 불필요한 카테고리를 제거하거나, 프로젝트 고유의 체크 항목을 추가
- **보안 체크리스트 보강**: 프로젝트에 특화된 보안 검사 항목 추가

**새 플랫폼 추가**: `.claude/templates/review-criteria/` 디렉토리에 새 파일을 생성하면 자동으로 인식됩니다 (예: `flutter.md`, `react-native.md`). 기존 파일을 복사하여 수정하는 것을 권장합니다.

기본 제공 플랫폼:

| 파일 | 대상 | 감지 확장자 |
|------|------|------------|
| `ios.md` | iOS / Swift | `.swift`, `.m`, `.xib`, `.pbxproj` |
| `android.md` | Android / Kotlin | `.kt`, `.java`, `build.gradle` |
| `frontend.md` | FrontEnd / Web | `.ts`, `.tsx`, `.vue`, `.css` |
| `backend.md` | BackEnd / Server | `.go`, `.py`, `.rs`, `Dockerfile` |
| `general.md` | 타입 미감지 시 | 모든 파일 |

#### 출력 형식 커스텀

- **리뷰 출력 형식**: `.claude/templates/review/templates.md`에서 `/pr-review` 커맨드의 출력 템플릿을 편집
- **반영 출력 형식**: `.claude/templates/apply-review/templates.md`에서 `/apply-review` 커맨드의 출력 템플릿을 편집

