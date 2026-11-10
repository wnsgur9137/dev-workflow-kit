# Dev Workflow Kit

Claude Code에서 쓰는 개발 워크플로 플러그인 모음입니다. 커밋 → PR 생성 → 리뷰 → 반영 → 병합까지의 흐름을 커맨드로 자동화합니다.

> 저장소 이름이 `pr-review-command`에서 `dev-workflow-kit`으로 바뀌었습니다. 이전 주소는 새 주소로 자동 연결되지만, 로컬 clone의 remote는 `git remote set-url origin <새 주소>`로 갱신하는 것을 권장합니다.

## 플러그인

| 플러그인 | 상태 | 커맨드 | 설명 |
|---|---|---|---|
| `workflow` | ✅ 사용 가능 | `/workflow:commit` `/workflow:create-pr` `/workflow:pr-review` `/workflow:apply-review` `/workflow:pipeline` | 커밋부터 병합까지 |
| `security` | 🚧 구현 중 (P1 scan-code) | `/security:scan-code`, `/security:scan-app` `/security:scan-web` (예정) | 로컬·네트워크 격리 보안 점검. **Docker 호환 런타임 필수** ([설계 문서](docs/security/보안%20툴킷.md)) |

## 목차

- [플러그인](#플러그인)
- [설치](#설치)
  - [이전 설치 방식(복사)에서 옮겨오기](#이전-설치-방식복사에서-옮겨오기)
- [요구사항](#요구사항)
  - [Docker 런타임](#docker-런타임)
- [커맨드](#커맨드)
- [security 플러그인](#security-플러그인)
  - [설치와 준비](#설치와-준비)
  - [권한 설정](#권한-설정)
  - [데이터 위치](#데이터-위치)
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
| **Docker 호환 런타임** | GitHub MCP 사용 시, `security` 플러그인 전체 | GitHub MCP 서버와 보안 도구를 모두 컨테이너로 실행. 아래 [Docker 런타임](#docker-런타임) 참고 |
| **`gh` CLI** | `apply-review` 답글, `create-pr` 폴백, `pipeline` | `gh auth login` 필요 |

### Docker 런타임

Docker CLI + Compose v2 + dockerd 엔진이면 됩니다. **무료로 쓰려면 Colima를 권장**합니다.

| 런타임 | 비용 |
|---|---|
| **Colima** (권장) | 무료 (MIT) |
| Docker Desktop | 개인·교육·소규모 사업(직원 250명 미만, 연 매출 1천만 달러 미만)은 무료, **그 외 업무 사용은 유료** |
| Rancher Desktop (dockerd 모드) | 무료 |
| OrbStack | 개인 무료, 상업 사용 유료 |

```bash
brew install colima docker docker-compose
colima start --cpu 4 --memory 8      # security 플러그인의 MobSF까지 쓰면 메모리 8GB 권장
docker info && docker compose version
```

`docker compose`를 찾을 수 없다고 나오면 Homebrew의 compose 플러그인 경로를 등록하세요: `~/.docker/config.json`에 `"cliPluginsExtraDirs": ["/opt/homebrew/lib/docker/cli-plugins"]` 추가 (Intel Mac은 `/usr/local/lib/docker/cli-plugins`).

Podman은 아직 지원하지 않습니다. 런타임 비교·리소스·Apple Silicon 주의사항: [Docker 런타임](docs/security/01%20개요/Docker%20런타임.md)

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

## security 플러그인

> 🚧 **구현 중** — `/security:scan-code`(시크릿·코드 패턴·취약 의존성)를 쓸 수 있습니다. 스택별 커스텀 검사는 **Web·Server·Android·iOS·Flutter·React Native** 모두 들어가 있습니다(`/security:scan-app`·`/security:scan-web`은 아직 없음). 진행 상황: [구현 계획](docs/security/06%20로드맵/구현%20계획.md)

개인 앱·웹 프로젝트를 **Claude Code 안에서, 외부 전송 없이** 점검합니다. 모든 도구는 네트워크가 차단된 컨테이너에서 실행되고, Claude는 정규화된 요약 리포트만 읽습니다. 설계: [보안 툴킷](docs/security/보안%20툴킷.md)

### 설치와 준비

```
/plugin install security@dev-workflow-kit
```

1. **Docker 호환 런타임** — 필수입니다. 위 [Docker 런타임](#docker-런타임)을 따라 Colima 등을 준비하세요. 스캔 전에 매번 다음을 점검하고, 하나라도 실패하면 컨테이너를 띄우지 않고 해결 방법을 안내합니다.

   | # | 점검 | 실패 시 |
   |---|---|---|
   | D1 | `docker` CLI 존재 | 런타임 설치 안내 |
   | D2 | 엔진 실행 중 | `colima start` 안내 |
   | D3 | Compose v2 이상 | compose 플러그인 안내 |
   | D4 | dockerd(moby) 엔진 | Podman 미지원 안내 |
   | D5 | VM 메모리 권장치 이상 | 경고만 |
   | D6 | 고정 digest 이미지·규칙·OSV DB 존재 | `update.sh` 실행 안내 (스캔은 다운로드하지 않음) |
   | D7 | 컨테이너에서 대상 폴더가 보임 | 런타임 공유 경로 설정 안내 (Colima 기본값은 홈 아래만 공유) |

2. **python3 3.8 이상** — 스택 감지·리포트 정규화에 씁니다 (표준 라이브러리만 사용).
3. **도구 데이터 받기** — 이미지·규칙·OSV DB는 툴킷에서 외부와 통신하는 유일한 스크립트인 `update.sh`로 받습니다. Claude에게 맡기지 말고 **터미널에서 직접** 실행하세요.

   ```bash
   ~/.claude/plugins/cache/dev-workflow-kit/security/<버전>/scripts/update.sh          # 전부
   ~/.claude/plugins/cache/dev-workflow-kit/security/<버전>/scripts/update.sh --osv    # OSV DB만 (주 1회 권장)
   ```

   이미지는 `images.lock`의 digest, 규칙은 `rules.lock`의 커밋으로 고정해 받습니다.

### 사용법

```
/security:scan-code ~/develop/my-app
/security:scan-code ~/develop/my-app --profile=web,server   # 스택 감지 대신 지정
```

| 도구 | 점검 | 비고 |
|---|---|---|
| Gitleaks | 하드코딩 시크릿 (작업 트리 + git 히스토리) | 리포트에는 시크릿 원문을 남기지 않음 |
| Semgrep | 취약 코드 패턴 | `generic` + 감지된 스택의 언어 규칙셋 |
| OSV-Scanner | 취약 의존성 (lockfile) | 오프라인 DB 사용, DB가 오래되면 경고. npm·PyPI·Go·Maven·Pub·SwiftPM·crates.io·RubyGems·Packagist·NuGet (CocoaPods 미지원) |
| 스택 검사 (툴킷) | 설정 파일·lockfile 메타데이터 등 Semgrep 으로 표현하기 어려운 점검 | 호스트 Python 이 대상 파일을 읽기만 함 (컨테이너·네트워크 없음) |

| 스택 | 커스텀 점검 | 설계 |
|---|---|---|
| Server (Python·Go·Java·Node, Docker) | Django `DEBUG = True`, Dockerfile `COPY .env`·`ADD <URL>`(+ 공식 `USER` 없음·`:latest`), compose `privileged`·docker.sock·DB 포트 전체 바인딩, Spring 설정 평문 비밀(키 이름만) | [Server](docs/security/07%20스택별%20설계/Server.md) |
| Android (Kotlin·Java) | Manifest `debuggable`·`allowBackup`·`usesCleartextTraffic`·권한 없는 exported 컴포넌트, network_security_config 평문·사용자 CA, release 난독화 꺼짐, WebView JS 인터페이스·파일 접근, `MODE_WORLD_READABLE`, `gradle.properties` 서명 비밀번호(키 이름만) | [Android](docs/security/07%20스택별%20설계/Android.md) |
| iOS (Swift·Objective-C) | Info.plist ATS 예외(`NSAllowsArbitraryLoads`·평문 예외 도메인·낮은 TLS), `UserDefaults` 토큰·비밀번호 저장, 민감 정보 로그, MD5·SHA1·DES·ECB, WKWebView 파일 URL 접근, xcconfig 평문 비밀(키 이름만) | [iOS](docs/security/07%20스택별%20설계/iOS.md) |
| Flutter (Dart) | `.env` asset 번들, CI 릴리스 빌드 `--obfuscate` 없음, `badCertificateCallback` → true, 평문 HTTP URL, `shared_preferences` 토큰. 하위 `android/`·`ios/`는 네이티브 프로파일 | [Flutter·RN](docs/security/07%20스택별%20설계/Flutter·React%20Native.md) |
| React Native | 공개 변수(`EXPO_PUBLIC_` 등)·`react-native-config` `.env`의 비밀 이름(키 이름만), `AsyncStorage` 토큰, WebView `originWhitelist`의 `'*'`, 평문 HTTP 요청, `__DEV__` 밖 민감 로그. 하위 `android/`·`ios/`는 네이티브 프로파일 | [Flutter·RN](docs/security/07%20스택별%20설계/Flutter·React%20Native.md) |
| Web (Next.js·React·Vite 등) | 공개 접두사 변수(`NEXT_PUBLIC_`·`VITE_` 등)에 비밀 이름, API 라우트 인증 누락(휴리스틱), SSRF, `next.config` 보안 헤더·원격 이미지 와일드카드·브라우저 소스맵, 설치 스크립트 있는 의존성 목록 | [Web](docs/security/07%20스택별%20설계/Web.md) |

모든 컨테이너는 `--network none`·읽기 전용 루트·권한 제거 상태로 돌고, 대상 저장소는 읽기 전용으로 마운트합니다. 대상 저장소의 `.gitleaks.toml`·`osv-scanner.toml`·억제 주석은 쓰지 않고 툴킷 고정 설정으로 점검합니다. 결과는 `reports/<run-id>/`의 `summary.md`(Claude가 읽는 요약)·`findings.json`·`raw/`에 남습니다.

### 권한 설정

플러그인은 권한을 스스로 설정할 수 없습니다. [`plugins/security/examples/settings.permissions.json`](plugins/security/examples/settings.permissions.json)의 `allow`·`deny`를 `~/.claude/settings.json`에 **직접 병합**하세요.

- 스캔 스크립트만 승인 없이 실행되고, `update.sh`·`docker run`·허용목록 수정·`.env` 열람은 Claude 권한 밖에 둡니다.
- 이 툴킷을 쓰는 세션에서는 **bypass permissions 모드를 쓰지 마세요.** deny 규칙은 실수 방지용이고, 실제 경계는 네트워크 격리와 권한 프롬프트입니다. ([Claude Code 권한 정책](docs/security/04%20보안/Claude%20Code%20권한%20정책.md))

### 데이터 위치

리포트·DB·설정은 플러그인 폴더 밖에 두므로 플러그인을 업데이트해도 사라지지 않고, 점검 대상 저장소에 커밋될 수도 없습니다.

| 경로 | 내용 | 권한 |
|---|---|---|
| `~/.local/share/dev-workflow-kit/security/` | 리포트(`reports/<run-id>/`), OSV DB, 규칙 | 폴더 700 |
| `~/.config/dev-workflow-kit/security/` | `.env`(MobSF 키), `targets.allowlist` | 폴더 700 / 파일 600 |

점검 대상으로 홈 디렉터리 자체·그 상위, `~/.ssh` 같은 자격증명 폴더, 시스템 폴더, 위 데이터 폴더는 거부합니다.

> **개발자**: `plugins/security/tests/run.sh`(단위·통합 테스트), `plugins/security/tests/lint.sh`(shellcheck)가 게이트입니다.

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
