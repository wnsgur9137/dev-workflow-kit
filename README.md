# Dev Workflow Kit

Claude Code에서 쓰는 개발 워크플로 플러그인 모음입니다. 커밋 → PR 생성 → 리뷰 → 반영 → 병합까지의 흐름을 커맨드로 자동화합니다.

> 저장소 이름이 `pr-review-command`에서 `dev-workflow-kit`으로 바뀌었습니다. 이전 주소는 새 주소로 자동 연결되지만, 로컬 clone의 remote는 `git remote set-url origin <새 주소>`로 갱신하는 것을 권장합니다.

## 플러그인

| 플러그인 | 상태 | 커맨드 | 설명 |
|---|---|---|---|
| `workflow` | ✅ 사용 가능 | `/workflow:commit` `/workflow:create-pr` `/workflow:pr-review` `/workflow:apply-review` `/workflow:pipeline` | 커밋부터 병합까지 |
| `security` | 🚧 설계 단계 | `/security:scan-code` `/security:scan-app` `/security:scan-web` (예정) | 로컬·네트워크 격리 보안 점검 ([설계 문서](docs/security/보안%20툴킷.md)) |

## 목차

- [플러그인](#플러그인)
- [설치](#설치)
  - [이전 설치 방식(복사)에서 옮겨오기](#이전-설치-방식복사에서-옮겨오기)
- [요구사항](#요구사항)
- [커맨드](#커맨드)
- [커스터마이징](#커스터마이징)
- [문서](#문서)
- [라이선스](#라이선스)

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

## 요구사항

| 항목 | 필요한 커맨드 | 설명 |
|---|---|---|
| **GitHub MCP 서버** | `pr-review`·`apply-review` 필수, `create-pr` 선택 | `cp examples/mcp.json.example .mcp.json` 후 사용. `.mcp.json`은 커밋하지 않습니다 |
| **`GITHUB_PERSONAL_ACCESS_TOKEN`** | GitHub MCP 사용 시 | 환경 변수로만 주입 |
| **Docker** | GitHub MCP 사용 시 | 공식 GitHub MCP 서버를 Docker 이미지로 실행 |
| **`gh` CLI** | `apply-review` 답글, `create-pr` 폴백, `pipeline` | `gh auth login` 필요 |

자세한 설정·의존성: [docs/workflow/설정.md](docs/workflow/설정.md) · 왜 GitHub MCP인가: [docs/workflow/GitHub MCP.md](docs/workflow/GitHub%20MCP.md)

> **기존 clone 사용자**: 이전 버전은 `.mcp.json`을 저장소에서 추적했습니다. `git pull` 시 로컬 `.mcp.json`이 삭제되므로 **pull 전에 백업**(`cp .mcp.json .mcp.json.bak`)한 뒤 복원하세요.

---

## 커맨드

| 커맨드 | 설명 | 상세 |
|---|---|---|
| `/workflow:commit [옵션]` | 변경사항과 기존 커밋 컨벤션을 분석해 Conventional Commits(+gitmoji) 커밋 생성. push는 하지 않음 | [commit](docs/workflow/commit.md) |
| `/workflow:create-pr [--open] [base=<branch>]` | 변경 내용을 분석해 PR 템플릿에 맞춰 Draft PR 생성, 라벨·연결 이슈·마일스톤 지정 | [create-pr](docs/workflow/create-pr.md) |
| `/workflow:pr-review <PR_URL>` | 플랫폼별 기준으로 코드 리뷰, 확인 후 GitHub 인라인 코멘트 게시 | [pr-review](docs/workflow/pr-review.md) |
| `/workflow:apply-review <PR>` | 리뷰 코멘트를 코드에 반영하고 코멘트 스레드마다 답글 | [apply-review](docs/workflow/apply-review.md) |
| `/workflow:pipeline [이슈번호]` | 작업 파악부터 병합까지 14단계 (`--no-issue`로 구현~병합만, 이전 `/ship`) | [pipeline](docs/workflow/pipeline.md) |

모든 커맨드는 `--help`로 옵션을 볼 수 있습니다.

---

## 커스터마이징

- **리뷰 기준**: `plugins/workflow/templates/review-criteria/`의 플랫폼별 파일(ios, android, frontend, backend, general). 새 파일을 추가하면 새 플랫폼으로 인식합니다.
- **출력 형식**: `plugins/workflow/templates/review/`, `plugins/workflow/templates/apply-review/`
- 설치된 플러그인 폴더를 직접 고치면 업데이트 때 덮어써집니다. **저장소를 fork해 수정한 뒤 fork를 마켓플레이스로 추가**하세요.

상세: [docs/workflow/커스터마이징.md](docs/workflow/커스터마이징.md)

---

## 문서

`docs/`는 Obsidian vault입니다. Obsidian에서 `docs/` 폴더를 vault로 열고 [`docs/Home.md`](docs/Home.md)에서 시작하세요.

```
docs/
├── Home.md        # 문서 허브
├── workflow/      # 커맨드별 상세 문서
├── security/      # security 플러그인 설계 (보안 툴킷.md)
└── project/       # 저장소 단위 계획·결정 기록
```

---

## 라이선스

[MIT](LICENSE). `security` 플러그인이 호출하는 외부 도구(MobSF GPL-3.0 등)는 저장소에 포함되지 않고 각자의 라이선스로 Docker 이미지에서 실행됩니다.
