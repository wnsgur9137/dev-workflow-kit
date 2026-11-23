---
name: create-pr
description: 현재 브랜치 변경사항을 분석해 PR 템플릿에 맞춰 Draft PR을 생성합니다 (옵션으로 Open 상태 생성).
argument-hint: "[--open] [base=<branch>]"
allowed-tools: Bash, Read, Glob, Grep, AskUserQuestion
---

# /create-pr

> **실행 환경** — 이 절차는 Claude Code와 Codex 모두에서 따른다. Claude Code가 아닌 환경(Codex 등)에서는:
> - 인자: 본문에서 인자 자리가 `$`로 시작하는 자리표시자 그대로 보이면, 사용자가 이 skill을 부른 메시지에서 skill 이름 뒤의 내용을 인자로 쓴다.
> - 사용자에게 묻기: `AskUserQuestion`이 없으면 같은 질문과 선택지를 번호 목록으로 보여 주고 답을 기다린다. 대화할 수 없는 실행(예: `codex exec`)이면 확인이 필요한 지점에서 멈추고 무엇을 확인해야 하는지 보고한다 — 임의로 기본값을 골라 진행하지 않는다.
> - GitHub·`git fetch`/`push`는 네트워크가 필요하다. sandbox 때문에 실패하면 권한 상승 승인을 요청한다.

GitHub 작업은 `gh` CLI로 한다(`gh auth status`로 인증 확인). `gh`를 쓸 수 없고 GitHub MCP 도구가 연결돼 있으면 같은 작업을 MCP로 해도 된다.

현재 브랜치의 작업 내용을 파악해 프로젝트 PR 템플릿에 맞춰 PR을 생성한다.
기본은 **Draft**, 인자에 `--open`이 포함되면 **Open** 상태로 생성한다.

## 입력 인자

사용자가 넘긴 인자: `$ARGUMENTS`

- `--open` (또는 `open`): Draft 대신 Open 상태로 PR 생성
- `base=<branch>`: base 브랜치를 강제로 지정 (예: `base=main`)

인자가 없으면 Draft + 자동 base 추론.

## 실행 절차

다음 순서대로 정확히 수행한다. 각 단계 결과를 사용자에게 한 줄로 보고하며 진행한다.

### 1. 현재 브랜치 / 커밋 / 푸시 상태 파악

```bash
git rev-parse --abbrev-ref HEAD
git status --short
git log -1 --format='%H %s'
```

- 현재 브랜치명이 `main` / `master` / `develop` 같은 보호 브랜치면 PR 생성을 중단하고 사용자에게 알릴 것.
- 워킹 트리에 untracked / 수정 파일이 있으면 그 목록을 보여주고 "커밋되지 않은 변경이 있는데 진행할까?" 사용자에게 확인한다. (AskUserQuestion)

### 2. Base 브랜치 결정

우선순위:
1. 인자에 `base=<branch>`가 있으면 그 값 사용.
2. `CLAUDE.md` / `AGENTS.md`에 "PR 대상", "base branch", "기본 브랜치" 같은 표현이 있으면 그 값을 사용.
3. `origin/develop`이 존재하면 `develop`을 우선 사용 (Git-flow 컨벤션).
4. 그 외에는 `origin/main` → `origin/master` 순으로 폴백.

결정한 base와 현재 브랜치(head)가 같으면 중단.

### 3. 변경 내역 분석

```bash
git fetch origin <base> --quiet
git log --oneline origin/<base>..HEAD
git diff --stat origin/<base>...HEAD
git diff origin/<base>...HEAD     # 본문 작성용. 길면 요약만.
```

`origin/<base>..HEAD`에 커밋이 0개면 PR 만들 게 없다고 알리고 중단한다.

### 4. 원격 푸시 확인 및 푸시

```bash
git ls-remote origin refs/heads/<현재 브랜치> | head -1
```

- 원격에 없거나 로컬과 다르면 사용자에게 "원격에 푸시할까?" 확인 후 `git push -u origin <현재 브랜치>` 실행. (AskUserQuestion)
- `--force` 종류 푸시는 절대 자동 실행하지 않는다. 거부되면 그대로 중단.

### 5. PR 템플릿 로드

다음 경로를 순서대로 확인하고 **첫 번째로 발견되는 것**을 본문 베이스로 사용한다.

1. `.github/PULL_REQUEST_DESCRIPTION_TEMPLATE.md`
2. `.github/PULL_REQUEST_TEMPLATE.md`
3. `.github/pull_request_template.md`
4. `.github/PULL_REQUEST_TEMPLATE/*.md` (여러 개면 첫 번째)
5. `docs/PULL_REQUEST_TEMPLATE.md`
6. `docs/pull_request_template.md`
7. `PULL_REQUEST_TEMPLATE.md`
8. `pull_request_template.md`

템플릿이 없으면 다음 최소 본문 사용:

```markdown
## 🎯 요약

## 📋 작업 배경
- **현재 상황**:
- **해결할 문제**:

## 🔧 변경 사항
- **Feature**:
- **Refactor**:
- **Fix**:
- **Update**:
```

### 6. 본문 작성 규칙

- 템플릿의 **HTML 주석(`<!-- ... -->`)은 제거하지 말고 유지**. 주석 안에 있는 작성 가이드(예: MCP 가이드 블록)도 그대로 둔다.
- 각 섹션은 실제 커밋/diff 내용을 근거로 구체적으로 채운다. 추상적 표현 금지("개선했다", "수정함" 만 적지 말 것).
- `## 🔧 변경 사항`은 커밋 prefix(`feat:`/`fix:`/`refactor:`/`update:`)를 기반으로 분류한다. 해당 카테고리에 없으면 그 줄은 비워두지 말고 `- **Feature**: -` 처럼 명시.
- `## 🏗️ 구현 세부 사항`은 diff에서 파악 가능한 핵심 로직/제약 변경을 1-3줄로 요약. 모를 경우 "해당 없음" 명시.
- `## 📸 동작 데모`는 자동으로 채울 수 없으므로 Before/After 자리만 비워두고 **"<!-- 스크린샷 첨부 필요 -->"** 안내를 남긴다.
- 제목(title): 가장 대표적인 커밋 메시지 또는 커밋들의 공통 주제를 기반으로 70자 이내로 작성. `type: 설명` 형식 유지(예: `feat: ...`, `fix: ...`).

### 6-1. 라벨 선택 (필수)

PR에는 **항상 라벨을 붙인다.** 저장소에 이미 있는 라벨 중에서만 고르고, 새 라벨은 만들지 않는다.

```bash
gh label list -R <owner>/<repo> --limit 200 --json name,description
```

- 커밋 prefix와 diff 내용에 맞는 라벨을 모두 고른다. 예: `feat` → Feature, `fix` → BugFix, `refactor` → Refactor, `chore`·설정 파일 → Setting, `docs` → Docs, `test` → Test, 의존성·lock 파일 변경 → Dependency, 배포·CI 설정 → Deploy, LLM·AI 관련 → AI.
- 라벨 이름은 이모지까지 포함해 저장소의 표기를 **그대로** 쓴다(예: `✨Feature`).
- 저장소에 라벨이 하나도 없거나 맞는 라벨이 없으면 라벨 없이 진행하되, 사후 보고에 그 사실을 적는다.

### 6-2. 연결 이슈와 마일스톤

저장소가 마일스톤을 쓰면 PR도 같은 마일스톤에 넣는다.

```bash
gh api repos/<owner>/<repo>/milestones --jq '.[] | "\(.number) \(.title)"'
gh issue list -R <owner>/<repo> --state open --json number,title,milestone
```

- 연결 이슈는 브랜치 이름의 이슈 번호(`feat/12-…`), 커밋·브랜치의 작업 ID(예: `M0-3`)와 같은 ID가 제목에 든 이슈(`[M0-3] …`) 순서로 찾는다. 찾으면 본문에 `Closes #N`을 넣는다(기획서 PR이면 `Refs #N`).
- PR 마일스톤은 연결 이슈의 마일스톤을 그대로 쓴다. 연결 이슈가 없으면 작업 ID 접두사(`M0`)로 시작하는 열린 마일스톤을 쓴다.
- 연결 이슈를 못 찾았는데 마일스톤이 있는 저장소면, 이슈 없이 진행할지 사용자에게 확인한다(AskUserQuestion). 이슈·마일스톤을 임의로 새로 만들지 않는다.

### 7. PR 생성 (`gh`)

1. `gh auth status`로 인증을 확인한다.
2. `mktemp`로 본문 파일을 만들고 **출력된 경로를 그대로** 기억한다. 셸 변수는 도구 호출 사이에 남지 않으므로 이후 명령에는 그 경로 문자열을 쓴다. 본문은 그 경로에 쓴다(파일 쓰기 도구, 또는 `'EOF'`처럼 인용한 heredoc — 본문에 그 구분자가 있으면 다른 구분자).
3. PR을 만든다.

```bash
gh pr create -R "<owner>/<repo>" \
  --base "<base>" \
  --head "<현재 브랜치>" \
  --title "<title>" \
  --body-file "<본문 파일 경로>" \
  --label "<라벨1>" --label "<라벨2>" \
  --milestone "<마일스톤>" \
  --draft
```

4. 본문 파일을 지운다(`rm -f "<본문 파일 경로>"`).

- `--label`: 6-1에서 고른 라벨마다 하나씩. 고른 라벨이 없으면 뺀다.
- `--milestone`: 6-2에서 정한 마일스톤이 있을 때만 넣는다.
- `--draft`: `--open` 인자가 없을 때만 넣는다.
- 줄 끝 `\` 뒤에는 주석을 붙이지 않는다(줄 이어짐이 끊긴다).

- owner / repo는 `git remote get-url origin`에서 추출 (예: `git@github.com:foo/bar.git` 또는 `https://github.com/foo/bar.git`, 또는 `git@<alias>:foo/bar.git` 형태도 지원). 필요하면 `-R <owner>/<repo>`로 지정한다.
- 연결 이슈는 본문의 `Closes #N`/`Refs #N`으로 연결한다(6-2). 라벨·마일스톤은 `gh pr create` 플래그로 한 번에 붙인다.
- `gh pr create`는 라벨·마일스톤을 먼저 확인하므로, 이름이 틀렸거나 권한(triage)이 없으면 **PR까지 만들어지지 않는다.** 라벨·마일스톤·권한 오류로 실패하면 `--label`·`--milestone`을 빼고 다시 만든 뒤 `gh pr edit <번호> -R <owner>/<repo> --add-label "<라벨>" --milestone "<마일스톤>"`으로 붙이고, 붙이지 못한 것은 보고에 적는다.
- `gh`가 미설치/미인증이면 그 상태를 알리고 중단. 절대 임의로 토큰을 만들거나 설정을 바꾸지 않는다.
- 생성 성공 시 PR URL을 굵게 표시해 보고한다. 생성 후 `gh pr view <번호> -R <owner>/<repo> --json labels,milestone,closingIssuesReferences`로 라벨·마일스톤·연결 이슈를 확인한다.

### 8. 사후 보고

PR 생성 결과를 다음 형식으로 요약 출력한다.

```
✅ PR 생성 완료
- URL: <PR URL>
- 상태: Draft | Open
- Base ← Head: <base> ← <head>
- 라벨: <붙인 라벨 목록 | 없음(이유)>
- 마일스톤 / 연결 이슈: <마일스톤> / Closes #N | 없음
- 커밋 수: N개
- 변경 파일: M개 (+추가 / -삭제)
- 다음 단계: <스크린샷 첨부 / 리뷰어 지정 / Ready for review 전환 등 권장 액션>
```

## 안전 규칙

- **사용자 확인 없이는 force push, base 브랜치로의 직접 commit, 다른 브랜치 checkout, 기존 PR 수정/머지/클로즈를 절대 하지 않는다.**
- 이미 같은 head→base 조합의 Open PR이 있으면 (`gh pr list -R <owner>/<repo> --head <branch> --base <base> --state open --json number,url,isDraft,baseRefName`로 확인 — head만으로 찾으면 다른 base로 향하는 PR을 중복으로 오인한다) 신규 생성하지 않고 기존 PR URL을 안내한다.
- `.env`, `*.key`, `credentials*` 같은 민감 파일이 변경에 포함돼 있으면 본문 생성 전에 경고하고 진행 여부를 확인한다.
- 본문 생성 시 사용자나 동료의 개인정보 / API 키 / 토큰을 절대 인용하지 않는다.

## 출력 톤

- 진행 단계마다 한 줄씩 짧게 알린다. 장황한 설명 금지.
- 한국어로 응답.
