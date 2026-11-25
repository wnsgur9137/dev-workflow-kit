<h1 align="center">Dev Workflow Kit</h1>

<p align="center">이슈 선택부터 병합까지의 개발 워크플로와 외부 전송 없는 보안 점검을<br>Claude Code와 Codex에서 쓰는 플러그인 모음</p>

<p align="center">
  <a href="plugins/workflow/CHANGELOG.md"><img alt="workflow version" src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2Fwnsgur9137%2Fdev-workflow-kit%2Fmaster%2Fplugins%2Fworkflow%2F.claude-plugin%2Fplugin.json&query=%24.version&label=workflow&prefix=v&color=2f6feb&style=flat-square"></a>
  <a href="plugins/security/CHANGELOG.md"><img alt="security version" src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2Fwnsgur9137%2Fdev-workflow-kit%2Fmaster%2Fplugins%2Fsecurity%2F.claude-plugin%2Fplugin.json&query=%24.version&label=security&prefix=v&color=8250df&style=flat-square"></a>
  <a href="LICENSE"><img alt="license" src="https://img.shields.io/github/license/wnsgur9137/dev-workflow-kit?style=flat-square"></a>
</p>

<p align="center">
  <a href="#빠른-시작">빠른 시작</a> ·
  <a href="#플러그인">플러그인</a> ·
  <a href="#호환성">호환성</a> ·
  <a href="docs/Home.md">문서</a> ·
  <a href="https://github.com/wnsgur9137/dev-workflow-kit/releases">릴리스</a>
</p>

> [!IMPORTANT]
> **workflow 2.0.0**부터 GitHub 작업에 GitHub MCP 대신 **`gh` CLI**를 씁니다. `gh auth login`을 먼저 해 두세요. 바뀐 점: [변경 이력](plugins/workflow/CHANGELOG.md#200---2026-11-23)

## 플러그인

<table>
<tr>
<td width="50%" valign="top">

### workflow

커밋부터 병합까지의 흐름을 skill로 자동화합니다.

- 저장소의 커밋 컨벤션을 읽어 커밋을 만들고, PR 템플릿에 맞춰 Draft PR을 엽니다
- 플랫폼별 기준으로 리뷰하고 **Codex 교차 리뷰**를 더해 인라인 코멘트로 게시합니다
- 리뷰를 반영하고 스레드마다 답글을 남긴 뒤, CI를 확인하고 병합합니다

[명령 목록](#명령) · [설정](docs/workflow/설정.md) · [변경 이력](plugins/workflow/CHANGELOG.md)

</td>
<td width="50%" valign="top">

### security

개인 앱·웹 프로젝트를 **외부 전송 없이** 점검합니다.

- 시크릿·취약 코드 패턴·취약 의존성 (`scan-code`)
- APK·AAB·IPA 정적 분석 (`scan-app`)
- 허용목록 웹 대상의 수동 점검, 공격 요청 없음 (`scan-web`)

모든 도구는 네트워크가 차단되거나 허용목록 프록시로만 나가는 컨테이너에서 돕니다.

[사용법](plugins/security/README.md) · [설계](docs/security/보안%20툴킷.md) · [변경 이력](plugins/security/CHANGELOG.md)

</td>
</tr>
</table>

## 빠른 시작

**Claude Code**

```
/plugin marketplace add wnsgur9137/dev-workflow-kit
/plugin install workflow@dev-workflow-kit
/plugin install security@dev-workflow-kit
```

**Codex CLI**

```bash
codex plugin marketplace add wnsgur9137/dev-workflow-kit
codex plugin add workflow@dev-workflow-kit
codex plugin add security@dev-workflow-kit
```

필요한 플러그인만 설치해도 됩니다. 터미널에서는 `claude plugin marketplace add …`, `claude plugin install …`로 같은 일을 할 수 있습니다. Claude Code에서는 `/workflow:commit`, Codex에서는 `$workflow:commit`처럼 부르고, 모든 명령은 `--help`로 옵션을 볼 수 있습니다.

> [!IMPORTANT]
> **업데이트할 때는 마켓플레이스를 먼저 갱신하세요.** 갱신하지 않으면 새 버전을 받지 못합니다.
>
> | | 마켓플레이스 갱신 | 플러그인 업데이트 |
> |---|---|---|
> | Claude Code | `/plugin marketplace update dev-workflow-kit` | `/plugin update workflow@dev-workflow-kit` |
> | Codex CLI | `codex plugin marketplace upgrade dev-workflow-kit` | `codex plugin add workflow@dev-workflow-kit` |
>
> security도 같은 방식이고, 올린 뒤 터미널에서 `update.sh`로 도구 데이터를 갱신합니다. [security 업데이트](plugins/security/README.md#업데이트)

security는 처음 한 번 도구 이미지·규칙을 받아야 합니다(`update.sh`). [설치와 준비](plugins/security/README.md#설치와-준비)를 보세요.

## 호환성

| 플러그인 | 버전 | Claude Code | Codex CLI | 필요한 도구 |
|---|---|:-:|:-:|---|
| workflow | [![workflow](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2Fwnsgur9137%2Fdev-workflow-kit%2Fmaster%2Fplugins%2Fworkflow%2F.claude-plugin%2Fplugin.json&query=%24.version&label=&prefix=v&color=2f6feb&style=flat-square)](plugins/workflow/CHANGELOG.md) | ✅ | ✅ | `gh` CLI(인증), git · 선택: Codex CLI(교차 리뷰) |
| security | [![security](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2Fwnsgur9137%2Fdev-workflow-kit%2Fmaster%2Fplugins%2Fsecurity%2F.claude-plugin%2Fplugin.json&query=%24.version&label=&prefix=v&color=8250df&style=flat-square)](plugins/security/CHANGELOG.md) | ✅ | ✅ | Docker 호환 런타임([Colima 권장](plugins/security/README.md#docker-런타임)), python3 3.8+ |

- 검증한 버전: Claude Code 2.1, Codex CLI 0.171, `gh` 2.96 (2026-11 기준).
- security는 아직 0.x라 마이너 버전에서도 동작이 바뀔 수 있습니다.
- Codex에서 다른 점: 선택지를 번호 목록으로 묻고, `codex exec`처럼 대화할 수 없는 실행에서는 확인이 필요한 지점에서 멈춥니다. Codex는 플러그인의 `skills/`만 읽습니다. `gh`·`git push`·Docker는 sandbox 때문에 권한 승인을 요청하니, 승인 창에서 필요한 명령만 계속 허용하세요. 실행 주체가 Codex이면 `pr-review`의 Codex 교차 리뷰는 생략합니다.

## 명령

**workflow**

| 명령 | 하는 일 | 문서 |
|---|---|---|
| `commit` | 변경과 기존 커밋 컨벤션을 분석해 Conventional Commits(+gitmoji) 커밋 생성. push는 하지 않음 | [commit](docs/workflow/commit.md) |
| `create-pr` | PR 템플릿에 맞춰 Draft PR 생성, 라벨·연결 이슈·마일스톤 지정 | [create-pr](docs/workflow/create-pr.md) |
| `pr-review <PR_URL\|번호>` | 플랫폼별 기준 리뷰 + Codex 교차 리뷰, 확인 후 인라인 코멘트 게시 | [pr-review](docs/workflow/pr-review.md) |
| `apply-review <PR>` | 리뷰 코멘트를 코드에 반영하고 스레드마다 답글 | [apply-review](docs/workflow/apply-review.md) |
| `pipeline [이슈번호]` | 작업 파악부터 병합까지 14단계 (`--no-issue`로 구현~병합만) | [pipeline](docs/workflow/pipeline.md) |
| `analyze-prd <PDF>` | PDF 기획서를 읽어 개발 설계서 초안(기능 분해·태스크·확인할 질문) 작성 | [analyze-prd](docs/workflow/analyze-prd.md) |
| `status` | 이전 작업 파악: 메모리의 결정·남은 일과 git·GitHub 실제 상태를 맞대어 어긋남과 다음 할 일을 정리 (조회만) | [status](docs/workflow/status.md) |

> [!NOTE]
> `pr-review`의 Codex 교차 리뷰는 **PR 코드·diff를 OpenAI로 보냅니다.** Codex CLI가 설치·로그인돼 있으면 기본으로 켜지고, 원치 않으면 `--no-codex`를 쓰세요. [자세히](docs/workflow/pr-review.md#codex-교차-리뷰)

**security**

| 명령 | 하는 일 |
|---|---|
| `scan-code <저장소 경로>` | Gitleaks·Semgrep·OSV-Scanner + 스택별 검사(Web·Server·Android·iOS·Flutter·React Native) |
| `scan-app <APK·AAB·IPA>` | 인터넷이 없는 내부 네트워크의 MobSF 정적 분석 + Gitleaks |
| `scan-web <URL>` | 허용목록 출처만 여는 프록시를 거친 OWASP ZAP baseline(수동 규칙만) |

도구·스택별 점검 항목·권한 설정·문제 해결은 [security 사용법](plugins/security/README.md)에 있습니다.

## 더 보기

<details>
<summary><b>설치 없이 한 세션만 시험하기</b></summary>

```bash
git clone https://github.com/wnsgur9137/dev-workflow-kit.git
claude --plugin-dir dev-workflow-kit/plugins/workflow
```

</details>

<details>
<summary><b>이전 설치 방식(복사)에서 옮겨오기</b></summary>

예전에는 `~/.claude/commands/`와 `~/.claude/templates/`에 파일을 복사해 설치했습니다. 복사본을 남겨 두면 `/commit`(복사본)과 `/workflow:commit`(플러그인)이 따로 존재해, 업데이트가 반영되지 않은 쪽을 실행할 수 있습니다.

```bash
mkdir -p ~/.claude/backup/commands ~/.claude/backup/templates
mv ~/.claude/commands/{commit,create-pr,pr-review,apply-review,pipeline,ship}.md ~/.claude/backup/commands/ 2>/dev/null
mv ~/.claude/templates/{review,review-criteria,apply-review} ~/.claude/backup/templates/ 2>/dev/null
```

리뷰 이력(`~/.claude/review-history/`)과 외부 레포 캐시(`~/.claude/repo-cache/`)는 그대로 두면 됩니다.

</details>

<details>
<summary><b>GitHub MCP를 계속 쓰려면 (선택)</b></summary>

`gh`를 쓸 수 없는 환경에서만 GitHub MCP로 대신할 수 있습니다. `examples/mcp.json.example`을 `.mcp.json`으로 복사하고 `GITHUB_PERSONAL_ACCESS_TOKEN` 환경 변수를 설정하세요(Docker 필요). `.mcp.json`은 커밋하지 않습니다. 예전에는 저장소가 이 파일을 추적했으므로, 그 시절 clone이라면 `git pull` 전에 백업하세요(`cp .mcp.json .mcp.json.bak`). 바꾼 이유: [GitHub MCP에서 gh로](docs/workflow/GitHub%20MCP.md)

</details>

<details>
<summary><b>저장소 이름 변경 (pr-review-command → dev-workflow-kit)</b></summary>

이전 주소는 새 주소로 자동 연결됩니다. 로컬 clone의 remote는 `git remote set-url origin <새 주소>`로 갱신하세요.

</details>

## 커스터마이징

- **리뷰 기준**: `plugins/workflow/templates/review-criteria/`의 플랫폼별 파일(ios, android, frontend, backend, general). 새 파일을 더하면 새 플랫폼으로 인식합니다.
- **출력 형식**: `plugins/workflow/templates/review/`, `plugins/workflow/templates/apply-review/`
- 설치된 플러그인 폴더를 고치면 업데이트 때 덮어써집니다. **저장소를 fork해 고친 뒤 fork를 마켓플레이스로 추가**하세요. [자세히](docs/workflow/커스터마이징.md)

## 문서

| 문서 | 내용 |
|---|---|
| [docs/Home.md](docs/Home.md) | 문서 허브 (`docs/`는 Obsidian vault) |
| [docs/workflow/](docs/workflow/설정.md) | workflow 설정·명령별 상세 |
| [plugins/security/README.md](plugins/security/README.md) | security 사용법·권한·데이터 위치·문제 해결 |
| [docs/security/](docs/security/보안%20툴킷.md) | security 설계 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 개발·버전·릴리스 규칙 |

## 라이선스

[MIT](LICENSE). `security` 플러그인이 호출하는 외부 도구(MobSF GPL-3.0 등)는 저장소에 포함되지 않고, 각자의 라이선스로 Docker 이미지에서 실행됩니다.
