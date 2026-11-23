# security 변경 이력

이 플러그인의 주요 변경을 버전별로 적습니다. 형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/)를 따르고, 버전은 [유의적 버전](https://semver.org/lang/ko/)을 따릅니다.
태그는 `security--v<버전>`이며, 같은 이름의 [GitHub Release](https://github.com/wnsgur9137/dev-workflow-kit/releases?q=security--v&expanded=true)가 있습니다.

> [!NOTE]
> 아직 0.x입니다. 마이너 버전(0.**N**.0)에서도 동작·설정이 바뀔 수 있습니다.

## [Unreleased]

## [0.12.1] - 2026-11-23

### 변경
- 사용법·권한·데이터 위치·문제 해결 문서를 저장소 README에서 플러그인의 [README](README.md)로 옮겼습니다. skill의 Codex 안내 링크도 그곳을 가리킵니다.

### 추가
- 플러그인 폴더에 이 변경 이력(`CHANGELOG.md`)을 둡니다. 버전마다 같은 이름의 GitHub Release를 만듭니다.

## [0.12.0] - 2026-11-23

### 추가
- **Codex CLI 지원.** `codex plugin add security@dev-workflow-kit`로 설치하고 `$security:scan-code <경로>` 형식으로 부릅니다. 각 skill에 Codex에서 다른 점(인자·경로, 시간 제한, sandbox)을 안내합니다.
- Codex sandbox는 Docker 소켓과 리포트 폴더 쓰기를 막습니다. 권장 방식은 스캔 스크립트 경로로 시작하는 명령만 계속 허용하는 승인입니다. `network_access`로 sandbox를 넓히는 방법은 사실상 sandbox를 끄는 것이라 비권장으로 안내합니다.

## [0.11.2] - 2026-11-23

### 수정
- 격리 확인이 연결을 닫기 전에 IP 누출을 기록해, 닫기에 실패해도 놓치지 않습니다.
- 식별자·자유 텍스트를 자를 때 퍼센트 표기(`%XX`)와 UTF-8 한 글자의 중간에서 끊지 않습니다.
- 데이터 폴더 확인 컨테이너의 실패를 공유 문제와 구분하고, 실행 폴더를 만들기 전에 확인합니다.
- 사전 점검 안내 개선: D7(Colima `mounts`), 데이터·플러그인 폴더 가시성 점검, D3(이 기기의 Homebrew 경로).
- 쿠키 값 가림이 다음 헤더 앞에서 끊겨 뒤 쿠키가 노출될 수 있던 문제.
- 부분 점검 파일 수 표시의 경계값·상한.

## [0.11.1] - 2026-11-18

### 수정
- 빌드 입력 해시가 숨김 파일·FIFO·실행 비트를 다루고, 이미지 ID 검사를 하나로 맞췄습니다. scan-app은 이미지를 받지 않습니다(`pull_policy: never`).
- 잘못된 UTF-8 파일 이름·짝 없는 서로게이트가 있어도 리포트 쓰기가 실패하지 않습니다.
- scan-code skill도 백그라운드로 실행해 2분 제한에 끊기지 않게 했습니다.
- 시크릿 결과의 위치 이동 처리와 이전 실행 메타 형식 오류 처리.

## [0.11.0] - 2026-11-18

### 추가
- 같은 대상의 직전 실행과 결과를 비교해 summary에 신규·유지·해결을 보입니다.

### 수정
- 리포트 정리의 링크된 `reports`·동시 정리·미래 시각 처리, 실패 원인 기록.

## [0.10.0] - 2026-11-18

### 추가
- 보관 기간(30일)이 지난 리포트를 지우는 `cleanup.sh`. 스캔을 시작할 때도 자동으로 정리합니다(실패해도 스캔은 계속).

### 수정
- 로컬 빌드 이미지의 입력·버전 라벨 확인(D6), 권한 예시 보강.

## [0.9.1] - 2026-11-18

### 변경
- scan-web의 egress-proxy를 공식 alpine과 고정한 패키지로 **로컬 빌드**합니다(`update.sh --images`). 빌드 기록의 이미지 ID로만 실행하고 리포트에 버전·이미지 ID를 남깁니다.

### 수정
- 쿠키·헤더 가림의 선형 처리, 정리 중 신호 처리.

## [0.9.0] - 2026-11-17

### 추가
- **`/security:scan-web`.** 허용목록에 있는 웹 대상을, 허용 출처만 여는 프록시를 거쳐 OWASP ZAP baseline(수동 규칙만, 공격 요청 없음)으로 점검합니다.

## [0.8.0] - 2026-11-15

### 추가
- **`/security:scan-app`.** 앱 산출물(APK·AAB·IPA)을 인터넷이 없는 내부 네트워크의 MobSF 정적 분석과 Gitleaks로 점검합니다.

### 수정
- 가상환경 판정·Semgrep 대상 범위 등 scan-code 잡음 감소.

## [0.7.0] - 2026-11-09

### 추가
- Flutter·React Native 프로파일: 커스텀 Semgrep 규칙과 스택 검사.

## [0.6.0] - 2026-11-09

### 추가
- iOS 프로파일: Info.plist ATS 예외, xcconfig 평문 비밀 검사.

## [0.5.0] - 2026-11-09

### 추가
- Android 프로파일: Manifest·network_security_config·Gradle release·properties 비밀 검사.

## [0.4.0] - 2026-11-09

### 추가
- Server 프로파일: compose·Spring 설정 평문 비밀 검사, Dockerfile 규칙셋.

## [0.3.0] - 2026-11-09

### 추가
- Web 프로파일: 커스텀 Semgrep 규칙과 스택 검사 틀.

## [0.2.0] - 2026-11-09

### 추가
- **`/security:scan-code`.** 소스 저장소의 하드코딩 시크릿(Gitleaks)·취약 코드 패턴(Semgrep)·취약 의존성(OSV-Scanner)을 네트워크가 차단된 컨테이너에서 점검합니다. 도구 이미지·규칙 고정과 `update.sh`, 스택 프로파일 6종 감지.

## [0.1.0] - 2026-11-05

### 추가
- 마켓플레이스에 security 플러그인 등록(기능 없음).

[Unreleased]: https://github.com/wnsgur9137/dev-workflow-kit/compare/security--v0.12.1...HEAD
[0.12.1]: https://github.com/wnsgur9137/dev-workflow-kit/releases/tag/security--v0.12.1
[0.12.0]: https://github.com/wnsgur9137/dev-workflow-kit/releases/tag/security--v0.12.0
[0.11.2]: https://github.com/wnsgur9137/dev-workflow-kit/releases/tag/security--v0.11.2
[0.11.1]: https://github.com/wnsgur9137/dev-workflow-kit/releases/tag/security--v0.11.1
[0.11.0]: https://github.com/wnsgur9137/dev-workflow-kit/releases/tag/security--v0.11.0
[0.10.0]: https://github.com/wnsgur9137/dev-workflow-kit/releases/tag/security--v0.10.0
[0.9.1]: https://github.com/wnsgur9137/dev-workflow-kit/releases/tag/security--v0.9.1
[0.9.0]: https://github.com/wnsgur9137/dev-workflow-kit/releases/tag/security--v0.9.0
[0.8.0]: https://github.com/wnsgur9137/dev-workflow-kit/releases/tag/security--v0.8.0
[0.7.0]: https://github.com/wnsgur9137/dev-workflow-kit/releases/tag/security--v0.7.0
[0.6.0]: https://github.com/wnsgur9137/dev-workflow-kit/releases/tag/security--v0.6.0
[0.5.0]: https://github.com/wnsgur9137/dev-workflow-kit/releases/tag/security--v0.5.0
[0.4.0]: https://github.com/wnsgur9137/dev-workflow-kit/releases/tag/security--v0.4.0
[0.3.0]: https://github.com/wnsgur9137/dev-workflow-kit/releases/tag/security--v0.3.0
[0.2.0]: https://github.com/wnsgur9137/dev-workflow-kit/releases/tag/security--v0.2.0
[0.1.0]: https://github.com/wnsgur9137/dev-workflow-kit/releases/tag/security--v0.1.0
