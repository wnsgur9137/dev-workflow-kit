# Dev Workflow Kit

Claude Code에서 쓰는 개발 워크플로 플러그인 모음입니다. 커밋 → PR 생성 → 리뷰 → 반영 → 병합까지의 흐름을 커맨드로 자동화합니다.

> 저장소 이름이 `pr-review-command`에서 `dev-workflow-kit`으로 바뀌었습니다. 이전 주소는 새 주소로 자동 연결되지만, 로컬 clone의 remote는 `git remote set-url origin <새 주소>`로 갱신하는 것을 권장합니다.

## 플러그인

| 플러그인 | 상태 | 커맨드 | 설명 |
|---|---|---|---|
| `workflow` | ✅ 사용 가능 | `/workflow:commit` `/workflow:create-pr` `/workflow:pr-review` `/workflow:apply-review` `/workflow:pipeline` | 커밋부터 병합까지 |
| `security` | ✅ 사용 가능 (남은 일: LuLu 실측) | `/security:scan-code`, `/security:scan-app`, `/security:scan-web` | 로컬·네트워크 격리 보안 점검. **Docker 호환 런타임 필수** ([설계 문서](docs/security/보안%20툴킷.md)) |

## 목차

- [플러그인](#플러그인)
- [설치](#설치)
  - [이전 설치 방식(복사)에서 옮겨오기](#이전-설치-방식복사에서-옮겨오기)
  - [Codex에서 쓰기](#codex에서-쓰기)
- [요구사항](#요구사항)
  - [Docker 런타임](#docker-런타임)
- [커맨드](#커맨드)
- [security 플러그인](#security-플러그인)
  - [설치와 준비](#설치와-준비)
  - [권한 설정](#권한-설정)
  - [데이터 위치](#데이터-위치)
  - [업데이트](#업데이트)
  - [문제 해결](#문제-해결)
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

### Codex에서 쓰기

[Codex CLI](https://github.com/openai/codex)도 이 마켓플레이스를 그대로 설치할 수 있습니다. Codex는 플러그인의 `skills/`만 읽습니다.

| 플러그인 | Codex 지원 |
|---|---|
| `security` | ✅ `$security:scan-code <경로>` 형식으로 부릅니다 |
| `workflow` | ❌ 아직 지원하지 않습니다 (Claude Code 전용 `commands/` 형식) |

```bash
codex plugin marketplace add wnsgur9137/dev-workflow-kit
codex plugin add security@dev-workflow-kit
```

- 업데이트: `codex plugin marketplace upgrade dev-workflow-kit` 후 `codex plugin add security@dev-workflow-kit`
- **sandbox 권한**: security는 Docker로 도구를 돌리고 `~/.local/share/dev-workflow-kit/security/reports/`에 리포트를 씁니다. Codex 기본 sandbox(workspace-write)는 둘 다 막아서, 스캔할 때 Codex가 권한 상승 승인을 요청합니다.
  - **권장**: 설정 파일은 고치지 않습니다. 승인 창에서 **스캔 스크립트(`…/scripts/scan-code.sh` 등)로 시작하는 명령을 계속 허용**하는 선택지를 고르세요. 그 스크립트만 sandbox 밖에서 돌고, 다음부터는 묻지 않습니다. 스크립트는 정해진 도구 컨테이너만 네트워크를 끊고 실행합니다.
  - **비권장 — sandbox 설정을 넓히는 방법**: 아래 설정으로도 승인 없이 동작합니다(실측한 최소 설정). 다만 `network_access = true`는 Codex가 실행하는 **모든 명령**에 네트워크와 Docker 데몬 접근을 열어 줍니다. Docker 데몬에 접근할 수 있으면 호스트 폴더를 마운트한 컨테이너를 띄울 수 있으므로 **sandbox를 사실상 끄는 것**과 같습니다. 이 세션에서 신뢰할 수 없는 코드나 문서를 다룬다면 쓰지 마세요.

    ```toml
    [sandbox_workspace_write]
    network_access = true    # Docker 소켓 연결에 필요 (위 경고 참고)
    writable_roots = ["/Users/<사용자>/.local/share/dev-workflow-kit/security/reports"]   # 절대 경로. 리포트 폴더만. DWK_SECURITY_DATA_DIR을 바꿨으면 <그 경로>/reports
    ```
- Claude Code의 [권한 설정](#권한-설정)(`allowed-tools`, `settings.json`)은 Codex에 적용되지 않습니다.

---

## 요구사항

| 항목 | 필요한 커맨드 | 설명 |
|---|---|---|
| **GitHub MCP 서버** | `pr-review`·`apply-review` 필수, `create-pr` 선택 | `cp examples/mcp.json.example .mcp.json` 후 사용. `.mcp.json`은 커밋하지 않습니다 |
| **`GITHUB_PERSONAL_ACCESS_TOKEN`** | GitHub MCP 사용 시 | 환경 변수로만 주입 |
| **Docker 호환 런타임** | GitHub MCP 사용 시, `security` 플러그인 전체 | GitHub MCP 서버와 보안 도구를 모두 컨테이너로 실행. 아래 [Docker 런타임](#docker-런타임) 참고 |
| **`gh` CLI** | `apply-review` 답글, `create-pr` 폴백, `pipeline` | `gh auth login` 필요 |
| **Codex CLI** (선택) | `pr-review` (`pipeline` 11단계 포함) | 있으면 Claude 리뷰에 Codex 교차 리뷰를 더합니다. `codex login` 필요. 없거나 사용량 제한이면 생략. **PR 코드·diff가 OpenAI로 전송**되므로 원치 않으면 `--no-codex` ([상세](docs/workflow/pr-review.md#codex-교차-리뷰)) |

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
| `/workflow:pr-review <PR_URL>` | 플랫폼별 기준으로 코드 리뷰(+ Codex 교차 리뷰), 확인 후 GitHub 인라인 코멘트 게시 | [pr-review](docs/workflow/pr-review.md) |
| `/workflow:apply-review <PR>` | 리뷰 코멘트를 코드에 반영하고 코멘트 스레드마다 답글 | [apply-review](docs/workflow/apply-review.md) |
| `/workflow:pipeline [이슈번호]` | 작업 파악부터 병합까지 14단계 (`--no-issue`로 구현~병합만, 이전 `/ship`) | [pipeline](docs/workflow/pipeline.md) |

모든 커맨드는 `--help`로 옵션을 볼 수 있습니다.

---

## security 플러그인

> ✅ **사용 가능** — `/security:scan-code`(시크릿·코드 패턴·취약 의존성), `/security:scan-app`(APK·AAB·IPA 정적 분석), `/security:scan-web`(허용목록 웹 대상의 수동 점검)을 쓸 수 있습니다. 스택별 커스텀 검사는 **Web·Server·Android·iOS·Flutter·React Native** 모두 들어가 있습니다. 남은 일은 사람이 수행하는 LuLu 실측입니다. 진행 상황: [구현 계획](docs/security/06%20로드맵/구현%20계획.md)

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
   | D6 | 고정 digest 이미지·로컬 빌드 이미지(egress-proxy)·규칙·OSV DB 존재 | `update.sh` 실행 안내 (스캔은 다운로드·빌드하지 않음) |
   | D7 | 컨테이너에서 대상 폴더가 보임 | 런타임 공유 경로 설정 안내 (Colima 기본값은 홈 아래만 공유) |

2. **python3 3.8 이상** — 스택 감지·리포트 정규화에 씁니다 (표준 라이브러리만 사용).
3. **도구 데이터 받기** — 이미지·규칙·OSV DB는 툴킷에서 외부와 통신하는 유일한 스크립트인 `update.sh`로 받습니다. Claude에게 맡기지 말고 **터미널에서 직접** 실행하세요.

   ```bash
   ~/.claude/plugins/cache/dev-workflow-kit/security/<버전>/scripts/update.sh          # 전부
   ~/.claude/plugins/cache/dev-workflow-kit/security/<버전>/scripts/update.sh --osv    # OSV DB만 (주 1회 권장)
   ```

   이미지는 `images.lock`의 digest, 규칙은 `rules.lock`의 커밋으로 고정해 받습니다. `/security:scan-web` 의 egress-proxy(tinyproxy)는 공식 이미지가 없어 받지 않고, `update.sh` 가 고정된 공식 alpine 위에 서명된 Alpine 패키지로 빌드합니다(빌드할 때 패키지를 받으러 네트워크를 씁니다).

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

```
/security:scan-app ~/develop/my-app/build/app/outputs/flutter-apk/app-release.apk
/security:scan-app ~/Desktop/Export/MyApp.ipa
```

| 도구 | 점검 | 비고 |
|---|---|---|
| MobSF v4.6.4 | APK·AAB·IPA 정적 분석 — 매니페스트·ATS·network_security_config, 서명, 디컴파일 코드 패턴, 바이너리 보호 기법, 위험 권한, 하드코딩 시크릿 후보 | **인터넷·호스트 포트가 없는 내부 네트워크**에서만 실행, 실행마다 새 스택을 띄웠다 지움. 이미지 약 2.5GB, VM 메모리 8GB 권장 |
| Gitleaks | 산출물(ZIP) 안의 텍스트 파일(RN 번들·설정 파일)의 키 | `--network none` |

- 직접 빌드한 **릴리스** 산출물을 권장합니다. 디버그 키로 서명된 빌드는 summary 에 표시됩니다. App Store 에서 받은 암호화된 IPA 는 분석할 수 없습니다.
- AAB 는 툴킷이 universal APK 로 바꿔 분석합니다 (서명은 점검하지 않음). Flutter·React Native 는 산출물에서 판정해 `--dart-define`·JS 번들 안내와 스택별 수동 체크리스트를 붙입니다.
- MobSF 리포트에 든 시크릿 원문·문자열 덤프는 리포트 폴더에 남기지 않습니다 (키 이름만). MobSF API 키는 실행마다 새로 만듭니다.

```
/security:scan-web http://host.docker.internal:3000/
/security:scan-web https://staging.my-app.example/
```

| 도구 | 점검 | 비고 |
|---|---|---|
| OWASP ZAP 2.17.0 (baseline) | 보안 헤더(CSP·HSTS·X-Frame-Options 등) 누락, 쿠키 속성(Secure·HttpOnly·SameSite), 서버 버전·오류 정보 노출 | **수동(passive) 규칙만** — 공격 요청을 보내지 않음(active·full scan 없음). 인증 없이 크롤링(스파이더 3분). 이미지 약 3.6GB, VM 메모리 6GB 권장 |
| egress-proxy (tinyproxy 1.11, 공식 alpine 에서 `update.sh` 가 로컬 빌드) | ZAP 의 유일한 출구 | 이번 대상의 출처(scheme+host+port) 하나만 열고 나머지는 403 + 로그 → summary 의 "프록시가 막은 요청" |

- **허용목록이 먼저 필요합니다.** `~/.config/dev-workflow-kit/security/targets.allowlist` 에 직접 소유·운영하는 대상을 **사용자가 직접** 한 줄에 하나씩 적습니다 (`scheme://host[:port]`, 경로·와일드카드 없음, `chmod 600`). 목록에 없거나 주석에 `prod` 가 붙은 대상은 컨테이너를 띄우기 전에 거부합니다. [권한 설정](#권한-설정)의 deny 규칙을 병합하면 Claude 는 이 파일을 고칠 수 없습니다.

  ```text
  # 직접 운영하는 대상만
  http://host.docker.internal:3000      # 로컬 개발 서버 (Colima 는 host.lima.internal 도 됨)
  https://staging.my-app.example
  ```

- 호스트에서 띄운 개발 서버는 `localhost` 대신 `host.docker.internal` 로 지정합니다 (컨테이너 안의 `localhost` 는 컨테이너 자신).
- 소스맵 공개·API 에러 스택트레이스·로그인 뒤 페이지처럼 baseline 이 확인하지 못하는 항목은 summary 의 수동 체크리스트로 붙습니다.

모든 컨테이너는 `--network none`(MobSF 는 내부 전용 네트워크, ZAP 은 허용목록 프록시만 닿는 내부 네트워크)·권한 제거 상태로 돌고, 대상 저장소는 읽기 전용으로 마운트합니다. 대상 저장소의 `.gitleaks.toml`·`osv-scanner.toml`·억제 주석은 쓰지 않고 툴킷 고정 설정으로 점검합니다. 결과는 `reports/<run-id>/`의 `summary.md`(Claude가 읽는 요약)·`findings.json`·`raw/`에 남습니다. 같은 대상을 다시 점검하면 summary 의 "이전 실행과 비교" 에 직전 실행 대비 **신규·유지·해결** 개수와 해결된 결과가 나옵니다. 어느 한쪽 실행에서 실패한 도구는 비교하지 않습니다. 리포트는 **30일** 보관합니다. 스캔할 때마다 그보다 오래된 `reports/<run-id>/` 를 지우고, 지운 이름을 새 실행의 `run.log` 에 남깁니다.

> [!WARNING]
> **0.10.0 으로 올린 뒤 첫 스캔에서 30일 지난 리포트가 바로 지워집니다 (되돌릴 수 없음)**
> - 먼저 확인: `~/.claude/plugins/cache/dev-workflow-kit/security/<버전>/scripts/cleanup.sh --dry-run`
> - 가장 안전한 방법: **업그레이드 전에** 남길 리포트를 `reports/` 밖의 다른 폴더로 복사하세요. 폴더 이름을 바꿔도 됩니다(`<run-id>` 형식이 아니면 건드리지 않습니다). `reports` 자체를 링크로 다른 곳에 두었다면 **그 대상 폴더도 같은 규칙으로 정리**되니, 보관용 사본은 링크 대상이 아닌 별도 폴더에 두세요
> - 보관 기간 늘리기(1~3650일): 스캔은 Claude Code 가 실행하므로 **Claude Code 가 보는 환경**에 넣어야 합니다. 다른 터미널에서 `export` 한 것은 이미 떠 있는 세션에 전달되지 않습니다. `~/.claude/settings.json` 에 `"env": {"DWK_SECURITY_RETENTION_DAYS": "90"}` 을 넣거나, 셸 설정 파일(`~/.zshrc` 등)에 `export DWK_SECURITY_RETENTION_DAYS=90` 을 넣은 뒤 Claude Code 를 다시 시작하세요. 스캔 출력의 "보관 기간(N일)" 으로 적용됐는지 확인할 수 있습니다
> - 직접 정리: `cleanup.sh [--days N] [--dry-run]`. 나이는 폴더 이름의 시각으로 판정하고, 다른 이름·링크는 건드리지 않습니다. 자동 정리는 `DWK_SECURITY_RETENTION_DAYS` 를 따르므로 `--days` 로 길게 잡아도 다음 스캔에서 그 기간으로 다시 정리됩니다

### 권한 설정

플러그인은 권한을 스스로 설정할 수 없습니다. [`plugins/security/examples/settings.permissions.json`](plugins/security/examples/settings.permissions.json)의 `allow`·`deny`를 `~/.claude/settings.json`에 **직접 병합**하세요.

- 스캔 스크립트만 승인 없이 실행되고, `update.sh`·`docker run`·허용목록 수정·`.env` 열람은 Claude 권한 밖에 둡니다.
- 이 툴킷을 쓰는 세션에서는 **bypass permissions 모드를 쓰지 마세요.** deny 규칙은 실수 방지용이고, 실제 경계는 네트워크 격리와 권한 프롬프트입니다. ([Claude Code 권한 정책](docs/security/04%20보안/Claude%20Code%20권한%20정책.md))

### 데이터 위치

리포트·DB·설정은 플러그인 폴더 밖에 두므로 플러그인을 업데이트해도 사라지지 않고, 점검 대상 저장소에 커밋될 수도 없습니다.

| 경로 | 내용 | 권한 |
|---|---|---|
| `~/.local/share/dev-workflow-kit/security/` | 리포트(`reports/<run-id>/`), OSV DB, 규칙 | 폴더 700 |
| `~/.config/dev-workflow-kit/security/` | `targets.allowlist` (MobSF 키는 저장하지 않고 실행마다 생성) | 폴더 700 / 파일 600 |

점검 대상으로 홈 디렉터리 자체·그 상위, `~/.ssh` 같은 자격증명 폴더, 시스템 폴더, 위 데이터 폴더는 거부합니다.

### 업데이트

1. **플러그인**: `/plugin marketplace update dev-workflow-kit` 후 `/plugin update security@dev-workflow-kit`. 리포트·규칙·DB 는 플러그인 폴더 밖에 있어 그대로 남습니다.
2. **도구 데이터**: 플러그인을 올린 뒤 터미널에서 **새 버전 폴더의** `update.sh` 를 실행합니다(외부와 통신하는 유일한 스크립트 — Claude 에게 맡기지 마세요). 셸 기록의 옛 경로(`…/security/<옛 버전>/scripts/update.sh`)를 다시 쓰면 옛 lock 으로 "이미지 있음" 만 찍히고 끝납니다 — 스캔의 D6 안내에 찍힌 경로를 그대로 쓰면 됩니다.
   - 평소: `update.sh --images --rules` — 이미지·규칙은 받을 것이 없으면 "이미지 있음·규칙 최신" 으로 건너뜁니다
   - OSV DB: `update.sh --osv` — **주 1회** 권장. OSV DB 는 실행할 때마다 전체(수백 MB)를 다시 받으므로, 인자 없이(`update.sh`) 돌리면 매번 받습니다. 7일이 지나면 summary 가 경고합니다
   - summary 에 "설치된 Semgrep 규칙이 rules.lock 과 다릅니다" 가 나오면 `update.sh --rules`
3. **버전 고정**: 이미지는 `images.lock` 의 digest, 규칙은 `rules.lock` 의 커밋으로 고정됩니다. egress-proxy 는 베이스 alpine 을 `images.lock` 의 `egress-proxy-base` digest 로, tinyproxy 를 `docker/egress-proxy/Dockerfile` 의 패키지 버전(리비전까지)으로 고정합니다. 사용자는 lock 을 고치지 않습니다 — 관리자가 공개 7일 이상 지난 릴리스로 PR 을 올립니다([업데이트 절차](docs/security/03%20워크플로/업데이트%20절차.md)).
4. 업데이트 직후 첫 스캔의 "이전 실행과 비교" 는 규칙 커밋·도구 이미지·프로파일이 바뀐 도구와, 플러그인 버전이 바뀐 툴킷 자체 검사(checks)를 비교하지 않습니다(정상).

### 문제 해결

메시지는 스캔 출력의 실제 문구로 찾을 수 있게 적었습니다. 해결 방법은 대부분 그 메시지 아래에 함께 나옵니다.

| 증상 | 원인 | 해결 |
|---|---|---|
| `[D2] Docker 엔진에 연결할 수 없습니다 (꺼져 있음)` | 런타임이 꺼져 있거나, 현재 docker 컨텍스트가 지운·꺼진 런타임을 가리킴 | `colima start`(Docker Desktop 이면 앱 실행). 컨텍스트는 `docker context ls` 로 확인 |
| `[D3] docker compose v2 이상이 필요합니다` | `brew install colima docker` 만 하고 compose 를 빠뜨림 | `brew install docker-compose` 후 메시지가 안내하는 `cliPluginsExtraDirs` 설정 |
| `[D5]` 메모리 경고 | VM 메모리가 권장치보다 작음 (scan-code 4·scan-web 6·scan-app 8 GB) | 경고에 나온 값으로 `colima stop && colima start --memory <GB>` (Docker Desktop: Settings → Resources → Memory). 경고만이라 진행은 됩니다 |
| `[D6] 필요한 이미지가 준비되지 않았습니다` | 처음 설치, 플러그인 업데이트로 고정 버전·egress-proxy 가 바뀜, 런타임을 바꿈(Colima ↔ Docker Desktop), `docker image prune -a`·`colima delete` | 터미널에서 `update.sh --images` |
| `[D6] Semgrep 규칙 또는 OSV 오프라인 DB 가 없습니다` (scan-code) | 규칙·OSV DB 를 아직 받지 않음 | 메시지에 찍힌 대로 인자 없이 `update.sh` |
| `[D7]` 컨테이너에서 대상 폴더가 보이지 않음 | 런타임이 그 폴더를 공유하지 않음 (Colima 기본값은 홈 아래만) | Colima: `colima stop` 후 `colima start --edit` 로 `mounts` 를 고칩니다. **`mounts` 가 비어 있을 때만 홈이 자동 공유되고, 항목을 적으면 적은 것만 공유됩니다** — `- location: ~` (`writable: true`)를 함께 적고 그 아래에 대상 폴더(`writable: false` 로 충분)를 더하세요. 빠뜨리면 scan-app 은 플러그인 폴더, scan-code 는 툴킷 데이터(규칙·OSV DB·리포트)·플러그인 폴더가 보이지 않는다는 D7 로 스캔 전에 멈춥니다(scan-web 은 호스트 폴더를 마운트하지 않아 영향이 없습니다). 확인: `colima ssh -- ls <경로>`. Docker Desktop: Settings → Resources → File sharing. 공유는 필요한 폴더로만 좁히세요(`/`·`/Volumes` 전체는 피함). 대상·규칙·플러그인은 읽기 전용으로 마운트하고, 리포트 폴더만 쓰기로 마운트합니다(데이터 폴더를 홈 밖에 두면 `writable: true`) |
| `[D7] … 확인용 컨테이너를 실행하지 못했습니다` | 공유 경로가 아니라 컨테이너 실행 자체가 실패 | 메시지의 종료코드·출력을 확인하고 `docker info` 로 런타임 상태를 봅니다. 이미지가 손상됐으면 `update.sh --images` 를 다시 실행 |
| 대상 경로 거부 | 홈 전체·그 상위, 최상위 폴더 자체(`/opt`·`/Volumes`), 시스템 폴더(`/usr`·`/Library` 등)와 시스템 공용 폴더(`/tmp`·`/private/tmp` 등), 자격증명·민감 폴더(`~/.ssh`·`~/.aws`·`~/.config`·`~/.claude`·`~/.gradle`·`~/.android`·`~/Library` 등 — 그 아래 프로젝트도. iCloud Drive·`~/Library/Developer` 아래도 거부), 툴킷 데이터·설정 폴더, `:`·`,` 가 든 경로 | 메시지에 거부 이유가 나옵니다. 점검할 저장소 폴더를 정확히 지정 |
| scan-app 산출물 거부 | APK·AAB·IPA 가 아니거나 ZIP 이 아님, 500MB 초과, 항목 20만 개 초과, 압축 해제 합계 4GB 초과 | 빌드 산출물을 직접 지정 |
| `update.sh` 가 `credsStore` 오류로 멈춤 | Docker Desktop 을 지운 뒤 `~/.docker/config.json` 에 `"credsStore": "desktop"` 이 남음 (그 helper 가 없어 이미 깨진 설정) | 그 줄을 지우세요(앞 줄 끝의 쉼표도 확인 — JSON 이 깨지면 docker 전체가 실패). 나중에 `docker login` 을 할 거라면 `brew install docker-credential-helper` 후 `"credsStore": "osxkeychain"` 으로 바꾸는 편이 안전합니다(지우면 자격증명이 `config.json` 에 평문으로 저장됨) |
| `update.sh` 의 egress-proxy 빌드 실패 (`unable to select packages`) | Alpine 저장소의 tinyproxy 리비전이 바뀜 | 그동안 scan-web 은 쓸 수 없습니다(scan-code·scan-app 은 영향 없음). 관리자가 Dockerfile 버전을 올린 플러그인 업데이트를 기다리거나 이슈로 알려 주세요 |
| arm64 에뮬레이션 경고 | 그 이미지에 Apple Silicon 용 빌드가 없음 (지금 고정된 이미지는 모두 arm64 를 지원) | 느리지만 동작합니다 |
| scan-web `허용목록에 없는 대상입니다` | `~/.config/dev-workflow-kit/security/targets.allowlist` 에 그 출처(scheme·host·port)가 없음 | 메시지에 나온 허용목록 파일에 직접 추가 ([권한 설정](#권한-설정)의 deny 규칙을 병합했다면 Claude 는 이 파일을 고칠 수 없습니다) |
| scan-web `… 는 컨테이너 자신을 가리킵니다` | 대상이 `localhost`·`127.0.0.1` | 호스트의 개발 서버는 `http://host.docker.internal:<포트>` 로 지정 |
| scan-web "대상에 접속하지 못했습니다" | 서버가 꺼져 있거나 포트·주소가 허용목록과 다름 | 서버가 떠 있는지, 허용목록의 포트가 맞는지 확인 |
| scan-web "55초 안에 응답하지 않았습니다" | 개발 서버의 첫 요청 컴파일·콜드 스타트 | 브라우저로 한 번 열어 둔 뒤 다시 실행 |
| scan-web·scan-app "격리 확인 실패" | 컨테이너에서 프록시를 거치지 않는 통신이 됨(오래된 Docker 엔진의 DNS 누출, `~/.docker/config.json` 의 `proxies`, 런타임 네트워크 설정), 또는 (scan-web) 프록시가 허용목록 밖 요청을 막지 않음 | Docker 엔진을 올리고 `proxies` 설정을 확인하세요. 대상에는 요청하지 않고 멈춥니다 |
| Claude 가 스캔 도중 끊김 | Bash 도구의 기본 시간 제한(2분) | 스킬은 백그라운드로 실행하게 돼 있습니다. 직접 실행할 때는 터미널에서 돌리세요 |
| 오래된 리포트가 사라짐 | 보관 기간(30일)이 지나 스캔 시 자동 정리 | 지운 이름은 새 실행의 `run.log` 에 남습니다. 기간은 `DWK_SECURITY_RETENTION_DAYS`(Claude Code 가 보는 환경)로 바꿉니다 |
| "이전 실행과 비교" 가 비교하지 않음 | 같은 대상의 직전 실행이 없음, 이전 버전 리포트, 도구 실패·부분 결과, 규칙·도구가 바뀜 | summary 에 이유가 적혀 있습니다. 원인이 없어진 실행의 **다음 실행부터** 비교됩니다(도구가 계속 실패하면 계속 비교하지 않음) |
| summary 에 "Semgrep 이 N개 파일의 일부를 점검하지 못했습니다" | 파싱하지 못하는 문법·타임아웃 | `raw/semgrep.json` 의 `errors` 를 확인하세요. 그 파일의 결과는 베이스라인 비교에서도 빠집니다 |

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
