# Dev Workflow Kit

Claude Code에서 사용할 수 있는 개발 워크플로 커맨드 모음입니다. 커밋 → PR 생성 → 리뷰 → 반영 → 병합까지의 흐름을 자동화합니다.

> 저장소 이름이 `pr-review-command`에서 `dev-workflow-kit`으로 바뀌었습니다. 이전 주소는 새 주소로 자동 연결되지만, 로컬 clone의 remote는 `git remote set-url origin <새 주소>`로 갱신하는 것을 권장합니다.

> **플러그인**: Claude Code 플러그인 마켓플레이스로 배포됩니다. 한 번 설치하면 **모든 프로젝트에서 `/workflow:<커맨드>`** 로 사용할 수 있습니다. 아래 [설치](#설치)를 참고하세요.
>
> **필수 조건**: `/pr-review`와 `/apply-review`는 **GitHub MCP 서버**가 프로젝트의 `.mcp.json`에 설정되어 있어야 동작합니다. `/create-pr`은 GitHub MCP를 우선 사용하되, 없거나 실패하면 사용자 승인 후 `gh` CLI로 폴백합니다. 아래 [설정](#설정) 섹션을 먼저 확인하세요.

## 목차

- [설치](#설치)
  - [이전 설치 방식(복사)에서 옮겨오기](#이전-설치-방식복사에서-옮겨오기)
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
- [/pipeline](#pipeline)
  - [이슈 모드와 규약 문서](#이슈-모드와-규약-문서)
  - [단계와 정지 조건](#단계와-정지-조건)
  - [Draft 유지 순서](#draft-유지-순서)
  - [진행 상태 판정](#진행-상태-판정)
  - [게이트 자동 감지](#게이트-자동-감지)
  - [보호 브랜치에서 시작할 때](#보호-브랜치에서-시작할-때)
  - [/ship에서 옮겨오기](#ship에서-옮겨오기)
- [의존성](#의존성)
- [설정](#설정)
  - [필수 요구사항](#필수-요구사항)
  - [디렉토리 구조](#디렉토리-구조)
  - [커스터마이징](#커스터마이징)

---

## 설치

Claude Code에서 마켓플레이스를 추가하고 `workflow` 플러그인을 설치합니다.

```
/plugin marketplace add wnsgur9137/dev-workflow-kit
/plugin install workflow@dev-workflow-kit
```

터미널에서는 같은 일을 다음 명령으로 할 수 있습니다.

```bash
claude plugin marketplace add wnsgur9137/dev-workflow-kit
claude plugin install workflow@dev-workflow-kit
```

- 업데이트: `/plugin marketplace update dev-workflow-kit` 후 `/plugin update workflow@dev-workflow-kit`
- 플러그인 커맨드는 **`/workflow:<커맨드>`** 형식으로 호출합니다 (예: `/workflow:commit`, `/workflow:pr-review <URL>`). 이 문서의 `/commit` 등은 `/workflow:commit`을 줄여 쓴 것입니다.
- 설치 없이 한 세션만 시험하려면: `claude --plugin-dir <clone 경로>/plugins/workflow`

> **릴리스 규칙 (저장소 관리자)**: 커맨드·템플릿을 바꾸면 `plugins/workflow/.claude-plugin/plugin.json`과 `.claude-plugin/marketplace.json`의 해당 플러그인 `version`을 **함께** 올립니다. 버전이 그대로면 사용자의 `/plugin update`가 새 내용을 받지 못할 수 있습니다. 병합 후 `claude plugin tag plugins/workflow --push`로 `workflow--v<버전>` 태그를 남기면 두 파일의 버전 일치도 함께 검사됩니다.

### 이전 설치 방식(복사)에서 옮겨오기

이전에는 `~/.claude/commands/`와 `~/.claude/templates/`에 파일을 복사해 설치했습니다. 플러그인 설치 후에는 복사본을 정리하세요. 남겨 두면 `/commit`(복사본)과 `/workflow:commit`(플러그인)이 따로 존재해 업데이트가 반영되지 않은 쪽을 실행할 수 있습니다.

```bash
mkdir -p ~/.claude/backup/commands ~/.claude/backup/templates
mv ~/.claude/commands/{commit,create-pr,pr-review,apply-review,pipeline,ship}.md ~/.claude/backup/commands/ 2>/dev/null
mv ~/.claude/templates/{review,review-criteria,apply-review} ~/.claude/backup/templates/ 2>/dev/null
```

리뷰 이력(`~/.claude/review-history/`)과 외부 레포 캐시(`~/.claude/repo-cache/`)는 플러그인과 무관하므로 그대로 두면 됩니다.

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
| `/pipeline [이슈번호] [옵션]` | 작업 파악부터 병합까지 14단계 파이프라인 수행 (위 커맨드들을 조합) |
| `/pipeline --no-issue "설명"` | 이슈 없이 구현~병합만 수행 (이전 `/ship`) |
| `/pipeline --help` | `/pipeline` 도움말 표시 |

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
   - **라벨**: 저장소에 이미 있는 라벨 중 커밋 prefix·diff에 맞는 것을 모두 고른다 (새 라벨은 만들지 않음, 맞는 라벨이 없으면 생략하고 보고)
   - **연결 이슈·마일스톤**: 브랜치의 이슈 번호·작업 ID로 연결 이슈를 찾아 `Closes #N`, PR 마일스톤은 연결 이슈의 것을 사용 (임의 생성 금지)
7. PR 생성 (`mcp__github__create_pull_request` 우선, 실패 시 사용자 승인 후 `gh pr create` 폴백). MCP는 라벨·마일스톤을 받지 않으므로 생성 직후 붙이고 확인
8. URL / Draft·Open 상태 / base ← head / 커밋 수 / 변경 파일 / 라벨 / 마일스톤·연결 이슈 / 다음 단계 보고

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

## /pipeline

작업 파악부터 병합까지 **14단계**를 순서대로 수행합니다. 9~12단계는 위 커맨드들을 재구현하지 않고 그대로 호출합니다. 이전 `/ship`의 역할은 `--no-issue` 모드가 대신합니다.

```
 0 저장소·규약 확인
 1 현재 작업 파악   2 예정 작업 파악   3 진행 작업 확정
 4 레퍼런스(조건부) 5 기존 설계 파악   6 기획서(조건부)   7 디자인(조건부)
 8 개발·게이트
 9 /commit   10 Draft PR   11 /pr-review   12 /apply-review   13 Ready + CI   14 병합
```

### 사용법

```
/pipeline [이슈번호] [--from=N] [--stop-at=N] [--merge=critical|auto|confirm] [--type=<라벨>] [--area=<라벨>] [--base=<branch>] [--branch=<name>] [--no-cleanup] [--post] [-h|--help]
/pipeline --no-issue "작업 설명" [options]
```

인자 없이 호출하면 실물 상태를 판정해 **다음에 해야 할 단계부터** 이어서 진행합니다.

### 예시

```
/pipeline                                   # 상태 판정 → 다음 단계부터
/pipeline 12                                # 이슈 #12로 바로 진행
/pipeline --from=11 --merge=confirm         # 리뷰부터 재개, 병합 직전 항상 확인
/pipeline --no-issue "README 오타 수정" --stop-at=13   # 이슈 없이, 병합은 하지 않음
```

### 옵션

| 옵션 | 설명 |
|------|------|
| `<이슈번호>` | 해당 이슈로 바로 진행 (1~3단계의 선택 부분 생략) |
| `--no-issue "설명"` | 이슈 없이 0 → 8 → 9~14만 수행 (이전 `/ship`). 규약 문서 불필요 |
| `--from=N` / `--stop-at=N` | N단계부터 재개 / N단계까지만 |
| `--merge=` | 14단계 병합 처리: `critical`(기본) · `auto` · `confirm` |
| `--type=` / `--area=` | 라벨 강제 지정 (규약의 라벨 목록에 있는 이름) |
| `--base=<branch>` | base 브랜치 지정 (기본: 자동 추론) |
| `--branch=<name>` | 작업 브랜치 이름 지정 (기본: 규약 → 기존 병합 이력 패턴) |
| `--no-cleanup` | 병합 후 브랜치 삭제 생략 |
| `--post` | 병합 후 진행 문서 갱신·실기기 체크리스트 출력 |
| `-h`, `--help` | 도움말을 출력하고 종료 |

### 이슈 모드와 규약 문서

이슈 모드는 저장소의 **파이프라인 규약 문서**를 따릅니다. 라벨 체계·실행 매트릭스(4·6·7·8단계 실행 여부)·게이트·문서 경로는 이 커맨드가 아니라 규약 문서가 정본입니다.

- 탐색 순서: `CLAUDE.md`·`AGENTS.md`에 적힌 경로 → `docs/**/PIPELINE.md`
- 이슈 모드에서 규약 문서가 없으면 **중단**하고 `--no-issue`를 안내합니다. 라벨·경로를 지어내지 않습니다.
- 기획서(6단계)는 코드와 같은 PR에 싣지 않고 **선행 PR로 먼저 병합**합니다.

### 단계와 정지 조건

| 정지 조건 | 단계 |
|-----------|------|
| 규약 문서 없음(이슈 모드) | 0 |
| 설계와 어긋나는 작업 | 5 |
| 게이트 실패, 수정 20회 초과 | 8, 12 |
| 리뷰 CRITICAL 미해소 | 12 → 13 |
| CI red | 13 |
| merge conflict | 14 |

정지하면 **그 단계에서 멈추고** 원인과 `--from=N` 재개 방법을 알립니다.

**병합(14단계) 처리 (`--merge`)**

| 값 | 동작 |
|----|------|
| `critical` (기본) | CRITICAL 0건(또는 모두 반영)·미반영 WARNING 없음·CI 통과면 확인 없이 병합, 하나라도 걸리면 확인 |
| `confirm` | 항상 병합 직전에 확인 |
| `auto` | 정지 조건에 걸리지 않으면 확인 없이 병합 |

### Draft 유지 순서

PR을 **항상 Draft로 만드는** 이유입니다.

CI가 Draft PR을 건너뛰는 설정이면, Ready 전환 후의 모든 push가 CI를 재실행시킵니다(`synchronize`).

```
잘못된 순서: 생성 → Ready → 리뷰 → 반영(push) → CI 2회
/pipeline 순서: 생성(Draft) → 리뷰 → 반영 → Ready → CI 1회
```

10~12단계를 Draft에서 끝내고 13단계에서 한 번만 Ready로 올리므로 CI가 1회로 끝납니다.

### 진행 상태 판정

상태 파일을 만들지 않습니다. 매 실행 시작 시 **git·GitHub에 직접 물어** 어디까지 됐는지 판정합니다.

| 판정 | 근거 |
|------|------|
| 진행 작업 확정 | 이슈에 "진행 중" 라벨 + 이슈 번호가 든 작업 브랜치 |
| 기획서 병합됨 | base에 기획서 파일 존재 |
| 개발·커밋 완료 | 워킹트리 clean **그리고** `<base>..HEAD`에 커밋 존재 |
| PR 생성됨 | `list_pull_requests(head: 현재 브랜치, state: open)` |
| 리뷰 완료 / 반영 완료 | 그 PR에 자체 리뷰 코멘트 / 이후 반영 내역 코멘트 존재 |
| Ready 상태 | PR의 `draft` 필드 |
| CI 결과 | `list_workflow_jobs(run_id)`의 `conclusion` |

**인자와 실물이 어긋나면 실물을 신뢰합니다.** `--from=N`의 선행 조건이 없으면 중단하고 무엇이 빠졌는지 알립니다(예: `--from=11`인데 열린 PR이 없음 → "10단계가 먼저 필요하다").

### 게이트 자동 감지

규약에 area별 게이트 표가 있으면 그것을, 없으면 `.github/workflows/*.yml`에서 **CI가 실제로 실행하는 명령**을 추출해 로컬 게이트로 씁니다.

추출한 명령은 **준비**(checkout·툴체인·의존성 설치·캐시)와 **검증**(lint·format·typecheck·build·test)으로 나눕니다. 준비는 로컬에 갖춰져 있으면 건너뛰고, 검증은 항상 실행합니다. `|| true`가 붙은 명령은 게이트에서 제외합니다.

**docs-only 변경이면** 빌드·테스트 대신 **문서 게이트**(목차 앵커 정합, 상대 링크 대상 존재, HTML 태그 균형)를 씁니다. 그래도 게이트가 없으면 `package.json`·`Makefile`·`CLAUDE.md`를 찾고, 끝내 없으면 **게이트 없이 진행하되 PR 본문에 명시**합니다.

### 인증

- 환경 변수 `<OWNER>_GITHUB_TOKEN`(owner 대문자, `-`는 `_`)이 있으면 그 토큰을 `gh` 호출마다 붙여 씁니다. 예: owner `octo-org` → `OCTO_ORG_GITHUB_TOKEN`. 회사 계정 `GITHUB_TOKEN`이 개인 저장소 권한을 가로막는 경우를 위한 장치입니다.
- GitHub MCP가 연결되지 않았으면 같은 일을 `gh` CLI로 합니다.

### 보호 브랜치에서 시작할 때

| 시작 단계 | 의미 | 동작 |
|-----------|------|------|
| 0~8 | 정상 | **작업 브랜치를 만든다** |
| 9 이상 | 이상 — PR 브랜치가 체크아웃돼 있어야 한다 | **중단** |

브랜치 이름은 `--branch` → 규약 → `git log --merges`의 기존 브랜치명 패턴 → 기본 `<type>/<이슈번호>-<slug>` 순으로 정합니다. 보호 브랜치에 커밋하지 않는 것이 목적이지, 멈추는 것이 목적이 아닙니다.

### 보고 규칙

- 리뷰 단계에서 **작성자와 리뷰어가 동일**하다는 사실을 리뷰 결과와 PR 코멘트에 명시합니다. 변경 500줄 초과면 외부 리뷰어를 권고합니다.
- 스크린샷·실기기 검증처럼 자동으로 확인할 수 없는 것은 **미수행이라고 적습니다**.
- 게이트 실패를 우회하려고 테스트를 지우거나 약화시키지 않습니다.

### /ship에서 옮겨오기

| 이전 | 이후 |
|------|------|
| `/ship "작업 설명"` | `/pipeline --no-issue "작업 설명"` |
| `/ship --from=4` (리뷰부터) | `/pipeline --from=11` |
| `/ship --stop-at=6` (Ready까지) | `/pipeline --stop-at=13` |
| `/ship --yes` | `/pipeline --merge=auto` |
| `/ship --loop=N` | 제거됨 — 8단계는 직접 구현하고 게이트 통과까지 고칩니다 |

---

## 의존성

이 커맨드들의 필수/선택 의존성을 정리합니다.

| 항목 | 필수 여부 | 설명 |
|------|----------|------|
| **GitHub MCP 서버** | `/pr-review`·`/apply-review` 필수 / `/create-pr` 선택 | PR 정보 수집·코멘트 게시에 사용. 프로젝트 `.mcp.json`에 설정(`examples/mcp.json.example` 복사). `/create-pr`은 미설정·실패 시 `gh` CLI로 폴백 |
| **`GITHUB_PERSONAL_ACCESS_TOKEN`** | GitHub MCP 사용 시 필수 | GitHub API 인증용 환경변수 |
| **`gh` CLI** | `/apply-review` 답글 게시 시 필요 / `/create-pr` 폴백 시 필요 | `/apply-review`의 리뷰 코멘트 스레드 답글 게시, GitHub MCP 불가 시 `/create-pr`의 PR 생성 폴백 경로. `gh auth login` 인증 필요 |
| **`workflow` 플러그인** | 필수 | 커맨드 정의(`commands/`)와 템플릿(`templates/`)을 함께 배포. [설치](#설치) 참고 |
| **`/commit`·`/create-pr`·`/pr-review`·`/apply-review`** | `/pipeline` 필수 | `/pipeline`은 9~12단계에서 이 커맨드들을 재구현하지 않고 그대로 호출한다 |
| **파이프라인 규약 문서** | `/pipeline` 이슈 모드 필수 | 대상 저장소의 `docs/**/PIPELINE.md` 등. `--no-issue` 모드는 불필요 |
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

### 디렉토리 구조

저장소(플러그인 소스):

```
dev-workflow-kit/
├── .claude-plugin/marketplace.json  # 마켓플레이스 정의
├── plugins/
│   └── workflow/
│       ├── .claude-plugin/plugin.json
│       ├── commands/                # commit, create-pr, pr-review, apply-review, pipeline
│       └── templates/
│           ├── review-criteria/     # 플랫폼별 리뷰 기준 (ios, android, frontend, backend, general)
│           ├── review/              # /pr-review 출력 형식
│           └── apply-review/        # /apply-review 출력 형식
└── examples/mcp.json.example
```

사용자 데이터(플러그인 밖, 업데이트해도 유지):

```
~/.claude/
├── review-history/{owner}/{repo}/   # /apply-review 반영 기록 (자동 생성)
└── repo-cache/{owner}/{repo}/       # 외부 레포 분석 캐시 (자동 생성)

<프로젝트>/.claude/review-history/    # 로컬 레포 리뷰 기록 (/pr-review, 자동 생성)
```

커맨드는 템플릿을 `${CLAUDE_PLUGIN_ROOT}/templates/...` 경로로 읽습니다. 설치된 플러그인 위치가 어디든 동작합니다.

> **이름이 같은 개인 커맨드**: `~/.claude/commands/` 또는 프로젝트 `.claude/commands/`에 `commit.md`를 두면 `/commit`으로 따로 호출되며, 플러그인의 `/workflow:commit`과는 별개로 동작합니다.

### 커스터마이징

> 설치된 플러그인 폴더를 직접 고치면 업데이트 때 덮어써집니다. 템플릿을 바꾸려면 **저장소를 fork해 수정한 뒤 fork를 마켓플레이스로 추가**하세요(`/plugin marketplace add <내 계정>/dev-workflow-kit`).

#### 리뷰 기준 커스텀

`plugins/workflow/templates/review-criteria/` 디렉토리의 플랫폼별 파일을 편집하여 리뷰 기준을 자유롭게 조정할 수 있습니다.

각 파일은 **우선순위 테이블**, **플랫폼별 체크리스트**, **보안 체크리스트** 3개 섹션으로 구성되어 있으며, 프로젝트 특성에 맞게 다음과 같이 커스텀할 수 있습니다:

- **우선순위 변경**: 테이블의 Priority 순서를 조정하여 중요도를 재배치
- **항목 추가/제거**: 프로젝트에 불필요한 카테고리를 제거하거나, 프로젝트 고유의 체크 항목을 추가
- **보안 체크리스트 보강**: 프로젝트에 특화된 보안 검사 항목 추가

**새 플랫폼 추가**: `plugins/workflow/templates/review-criteria/` 디렉토리에 새 파일을 생성하면 자동으로 인식됩니다 (예: `flutter.md`, `react-native.md`). 기존 파일을 복사하여 수정하는 것을 권장합니다.

기본 제공 플랫폼:

| 파일 | 대상 | 감지 확장자 |
|------|------|------------|
| `ios.md` | iOS / Swift | `.swift`, `.m`, `.xib`, `.pbxproj` |
| `android.md` | Android / Kotlin | `.kt`, `.java`, `build.gradle` |
| `frontend.md` | FrontEnd / Web | `.ts`, `.tsx`, `.vue`, `.css` |
| `backend.md` | BackEnd / Server | `.go`, `.py`, `.rs`, `Dockerfile` |
| `general.md` | 타입 미감지 시 | 모든 파일 |

#### 출력 형식 커스텀

- **리뷰 출력 형식**: `plugins/workflow/templates/review/templates.md`에서 `/pr-review` 커맨드의 출력 템플릿을 편집
- **반영 출력 형식**: `plugins/workflow/templates/apply-review/templates.md`에서 `/apply-review` 커맨드의 출력 템플릿을 편집

