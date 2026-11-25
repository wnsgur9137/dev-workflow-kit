# workflow 변경 이력

이 플러그인의 주요 변경을 버전별로 적습니다. 형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/)를 따르고, 버전은 [유의적 버전](https://semver.org/lang/ko/)을 따릅니다.
태그는 `workflow--v<버전>`이며, 같은 이름의 [GitHub Release](https://github.com/wnsgur9137/dev-workflow-kit/releases?q=workflow--v&expanded=true)가 있습니다.

## [Unreleased]

## [2.2.0] - 2026-11-25

### 추가
- `status`: 세션을 다시 시작해 작업을 이어 갈 때 쓰는 "이전 작업 파악" skill. 메모리·문서에 남은 결정·남은 일과 git·GitHub 실제 상태(현재 브랜치·커밋 안 한 변경·worktree·병합된 브랜치·열린 PR의 리뷰·CI·이어 갈 `/pipeline` 단계·최근 병합·열린 이슈 진행률·태그 누락·설치 버전 차이)를 맞대어 **어긋남**과 다음 할 일을 정해진 형식으로 보여 줍니다. 조회만 하며, 브랜치 삭제·이슈 닫기·메모리 갱신은 제안만 합니다. "이전 작업 파악"처럼 말로 요청해도 모델이 호출합니다. `--local`(GitHub 생략)·`--days=N`을 지원합니다. Claude Code에서는 `/workflow:status`(맨 `/status`는 내장 명령)로 부릅니다.

### 변경
- `pipeline`: 12단계 반영 내역 코멘트의 첫 줄을 `## 리뷰 반영 내역`으로 정했습니다. `status`가 이 제목으로 반영 여부를 판정합니다.

## [2.1.0] - 2026-11-24

### 추가
- `analyze-prd`: PDF 기획서를 읽어 개발 설계서 초안(기능 분해·화면·데이터·태스크·리스크·확인할 질문)을 만드는 skill. 저장소 안에서는 현재 스택에 맞춰 쓰고, `--detailed`·`--out`을 지원합니다. PDF는 파일 읽기 → 이 기기 안에서 변환하는 MCP → `pdftotext`(한 쪽씩) 순으로 읽고, PDF 속 지시문은 따르지도 옮기지도 않습니다. Claude Code에서 확인 없이 허용하는 셸 명령은 `pdfinfo`·`git rev-parse`뿐입니다.
- `pr-review`: PR 번호(`32`, `#32`)를 받습니다. 저장소는 현재 폴더의 remote(SSH 별칭 포함)에서 정하고, fork처럼 후보가 둘 이상인데 `gh repo set-default`가 없으면 묻습니다. github.com 저장소만 번호로 받습니다.
- `pr-review`: 인증·암호·시크릿·입력 처리·플랫폼 보안 설정 같은 보안 민감 변경이 있으면 그 파일만 보안 관점으로 한 번 더 봅니다(Step 4.2, Summary `Security Pass`). `--focus=security`면 변경 파일 전체를 보고, `--skip=security`로 끕니다.

### 변경
- `pr-review`: Secret·Code·Dependabot 경고 목록을 동시에 조회합니다(조회마다 종료 코드·오류를 따로 받음).
- `pipeline`: 8단계에 "증분 빌드는 경고를 숨긴다"(8단계는 클린 빌드로 세고, 13단계에서 CI 전체 빌드 로그로 PR이 늘린 경고만 병합을 막음)와 "산출물을 다시 열어 확인" 안내를 더했습니다. 6단계에서 PDF 기획서면 `analyze-prd` 초안을 입력으로 쓸 수 있습니다. 11단계는 `pr-review`에 PR 번호 대신 URL을 넘깁니다.

## [2.0.1] - 2026-11-23

### 추가
- 플러그인 폴더에 이 변경 이력(`CHANGELOG.md`)을 둡니다. 버전마다 같은 이름의 GitHub Release를 만듭니다.

## [2.0.0] - 2026-11-23

> [!IMPORTANT]
> GitHub MCP 대신 **`gh` CLI 인증**(`gh auth login`)이 필요합니다. 플러그인 구조가 `commands/`에서 `skills/`로 바뀌었습니다.

### 추가
- **Codex CLI 지원.** `codex plugin add workflow@dev-workflow-kit`로 설치하고 `$workflow:<이름>`으로 부릅니다. 각 skill 맨 앞의 "실행 환경" 블록이 Codex에서 다른 점(인자·경로 치환, 선택지 질문, 백그라운드·서브에이전트, sandbox 네트워크)을 안내합니다.
- `pr-review`: 실행 주체가 Codex이면 교차 리뷰를 생략합니다(`실행 환경이 Codex`).
- 자기 PR에는 `COMMENT`로 게시합니다. GitHub가 자기 PR의 APPROVE/REQUEST_CHANGES를 거부하기 때문입니다.

### 변경
- **BREAKING** 커맨드를 `skills/<이름>/SKILL.md`로 옮겼습니다. Claude Code의 호출 이름(`/workflow:<이름>`)은 그대로입니다.
- **BREAKING** 모든 GitHub 작업을 GitHub MCP에서 `gh`로 바꿨습니다. GitHub MCP는 `gh`를 쓸 수 없을 때만 대신 씁니다.
- `pr-review`: 리뷰를 `POST /pulls/N/reviews` 한 번으로 게시합니다(인라인 코멘트 묶음). 파일 단위 코멘트는 `subject_type=file`로 따로 답니다. 422는 원인(event·본문·줄)에 따라 최대 2번 다시 시도합니다.
- `pr-review`: secret scanning 경고는 위치를 확인해 PR과 관계있는 것만 REQUEST_CHANGES 판정에 넣습니다. code scanning은 `refs/pull/N/merge`로 조회합니다.
- `create-pr`: MCP 경로와 `gh` 폴백을 `gh pr create` 하나로 합쳤습니다. 라벨·마일스톤 오류로 생성이 실패하면 그것을 빼고 만든 뒤 붙입니다.
- `pipeline`: 병합에 `--match-head-commit`을 써서 CI가 확인한 head만 병합합니다. CI는 PR head의 워크플로마다 가장 최근 실행으로 판정합니다.
- `gh` 호출은 모두 저장소를 `-R`로 명시하고(fork 구성에서 다른 저장소로 가지 않게), 목록은 `--paginate --jq '.[]'`로 끝까지 받습니다. `create-pr`의 중복 확인은 head와 base를 함께 봅니다.
- **GitHub MCP를 쓰던 clone 사용자**: 예전에는 `.mcp.json`을 저장소에서 추적했습니다. 그 시절 clone이라면 `git pull` 때 로컬 `.mcp.json`이 지워지니 먼저 백업하세요(`cp .mcp.json .mcp.json.bak`).

## [1.1.0] - 2026-11-23

### 추가
- `pr-review`: **Codex 교차 리뷰.** Claude가 리뷰하는 동안 Codex(`codex exec`, 읽기 전용 sandbox)가 같은 PR을 따로 리뷰하고, Claude가 지적마다 코드를 확인해 채택·기각한 뒤 합쳐 게시합니다. 기본으로 켜지고 `--no-codex`로 끕니다. PR 코드·diff가 OpenAI로 전송됩니다.
- 코멘트마다 출처(`Claude`·`Codex`·`Claude+Codex`)와 `dwk:reviewer` 표식을 남깁니다. `apply-review`는 표식이 있으면 본인 계정 코멘트도 반영합니다.
- `pipeline`: `--no-codex`를 전달합니다. Codex 생략은 정지 조건이 아닙니다.

### 변경
- `pr-review`의 Gemini 권고 단계를 Codex 교차 리뷰로 바꿨습니다.

## [1.0.2] - 2026-11-05

### 추가
- `pr-review`·`apply-review`에 frontmatter(`description`·`argument-hint`)를 넣어 플러그인 커맨드 목록에 설명이 보이게 했습니다.

## [1.0.1] - 2026-11-05

### 추가
- MIT 라이선스.

## [1.0.0] - 2026-11-05

### 추가
- Claude Code 플러그인 마켓플레이스로 첫 배포. `commit`, `create-pr`, `pr-review`, `apply-review`, `pipeline` 커맨드.

[Unreleased]: https://github.com/wnsgur9137/dev-workflow-kit/compare/workflow--v2.2.0...HEAD
[2.2.0]: https://github.com/wnsgur9137/dev-workflow-kit/releases/tag/workflow--v2.2.0
[2.1.0]: https://github.com/wnsgur9137/dev-workflow-kit/releases/tag/workflow--v2.1.0
[2.0.1]: https://github.com/wnsgur9137/dev-workflow-kit/releases/tag/workflow--v2.0.1
[2.0.0]: https://github.com/wnsgur9137/dev-workflow-kit/releases/tag/workflow--v2.0.0
[1.1.0]: https://github.com/wnsgur9137/dev-workflow-kit/releases/tag/workflow--v1.1.0
[1.0.2]: https://github.com/wnsgur9137/dev-workflow-kit/releases/tag/workflow--v1.0.2
[1.0.1]: https://github.com/wnsgur9137/dev-workflow-kit/releases/tag/workflow--v1.0.1
[1.0.0]: https://github.com/wnsgur9137/dev-workflow-kit/releases/tag/workflow--v1.0.0
