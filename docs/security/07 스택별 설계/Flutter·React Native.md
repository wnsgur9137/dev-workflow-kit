---
title: Flutter·React Native
tags: [security/stack, stack/flutter, stack/react-native]
status: draft
created: 2026-11-05
profile: [flutter, react-native]
---

# Flutter · React Native

상위: [[스택 프로파일 개요]] · 결정: [[ADR-008 스택별 프로파일]] · 네이티브: [[iOS]], [[Android]]

크로스플랫폼 앱은 **공용 코드(Dart / JS·TS) 프로파일 + 네이티브 하위 프로젝트 프로파일**을 함께 적용한다.

## 네이티브 하위 프로젝트
| 앱 | 공용 코드 | 네이티브 경로 → 적용 프로파일 |
|---|---|---|
| Flutter | `lib/` (Dart) | `ios/` → [[iOS]], `android/` → [[Android]] |
| React Native | `src/`, `App.tsx` 등 (JS/TS) | `ios/` → [[iOS]], `android/` → [[Android]] |

- 네이티브 프로파일은 **해당 하위 경로에만** 적용 (루트 전체에 Swift·Kotlin 규칙을 돌리지 않음)
- Expo managed 프로젝트처럼 `ios/`·`android/`가 없으면 네이티브 소스 점검은 생략하고 `/security:scan-app` 산출물 점검으로 대신함

---

## Flutter (`profiles/flutter.yaml`)
```yaml
detect:
  - { file: "**/pubspec.yaml", has_dependency: [flutter] }   # 순수 Dart 패키지·서버는 제외 (P0 구현 시 변경)
exclude_paths: ["**/.dart_tool/**", "**/build/**", "**/*.g.dart", "**/*.freezed.dart"]
semgrep:
  rulesets: []   # semgrep-rules 에 dart 규칙셋이 없다 (P1 확인) — generic + 커스텀 규칙으로 점검
```

| # | 점검 | 방법 | 대상 | 심각도 |
|---|---|---|---|---|
| F1 | 하드코딩 시크릿 (특히 `lib/`의 API 키, `.env`를 asset으로 번들) | Gitleaks + 커스텀 검사 (`pubspec.yaml` assets에 `.env` 포함 여부) | `lib/`, `pubspec.yaml` | high |
| F2 | `--dart-define`으로 넣은 값은 바이너리에 평문으로 남음 | summary 안내 + MobSF 문자열 결과 확인 | 빌드 산출물 | info |
| F3 | 릴리스 빌드 난독화 미적용 (`--obfuscate --split-debug-info`) | 커스텀 검사 (CI·빌드 스크립트 텍스트), MobSF | 빌드 스크립트 | medium |
| F4 | 평문 HTTP URL, 인증서 검증 우회(`badCertificateCallback` → true) | Semgrep 커스텀 `flutter/insecure-http` | `*.dart` | high |
| F5 | `shared_preferences`에 토큰 저장 (보안 저장소 미사용) | Semgrep 커스텀 `flutter/insecure-storage` | `*.dart` | medium |
| F6 | 취약 의존성 | OSV-Scanner | `pubspec.lock` | CVSS 기준 |

- Semgrep Dart 지원은 제한적 → F4·F5는 **패턴이 단순한 커스텀 규칙**으로 작성

## React Native (`profiles/react-native.yaml`)
```yaml
detect:
  - { file: "**/package.json", has_dependency: [react-native, expo] }
exclude_paths: ["**/node_modules/**", "**/ios/Pods/**", "**/android/build/**"]
```

| # | 점검 | 방법 | 대상 | 심각도 |
|---|---|---|---|---|
| R1 | JS 번들에 포함되는 시크릿 (`.env` → `react-native-config`·`EXPO_PUBLIC_` 값은 번들에 평문) | Gitleaks + summary 안내 | 소스, `.env*` | high |
| R2 | `AsyncStorage`에 토큰 저장 | Semgrep 커스텀 `rn/insecure-storage` | `*.js`, `*.ts(x)` | medium |
| R3 | 평문 HTTP, `WebView`의 `originWhitelist={['*']}`·`javaScriptEnabled` + 신뢰 안 된 URL | Semgrep `javascript`/`typescript` 공식 + 커스텀 `rn/webview` | 소스 | medium |
| R4 | 디버그 코드 (`__DEV__` 분기 밖 `console.log`로 민감 정보) | Semgrep 커스텀 `rn/sensitive-log` | 소스 | low |
| R5 | 취약 의존성 | OSV-Scanner | `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml` | CVSS 기준 |
| R6 | 번들 산출물의 키 (`index.android.bundle`, `main.jsbundle`, Hermes 바이트코드) | [[MobSF]] 문자열 결과 + Gitleaks(번들 파일 대상) | `.apk`, `.ipa` | high |

## 구현 메모 (S-Flutter·RN)

| # | 구현 | 규칙·검사 ID | 심각도 |
|---|---|---|---|
| F1 | 스택 검사 — `pubspec.yaml`의 `flutter.assets`에 `.env`·`.env.*`(예시 파일 제외) | `flutter.env-asset` | high |
| F3 | 스택 검사(저장소 전체) — `.github/workflows/*.yml`·`codemagic.yaml`·`bitrise.yml`·`.gitlab-ci.yml`·`azure-pipelines.yml`·`Makefile`·`*.sh`·`fastlane/Fastfile`의 `flutter build apk|appbundle|aab|ipa|ios`에 `--obfuscate` 없음(`--debug`·`--profile` 제외). 빌드 명령이 없으면 판단하지 않음 | `flutter.build-no-obfuscate` | medium |
| F4 | Semgrep 커스텀(Dart) — `badCertificateCallback = (...) => true`(cascade 포함), `Uri.parse`·`dio.get/post`의 `http://`(localhost·127.0.0.1·10.0.2.2 제외) | `custom.flutter.bad-certificate-callback`, `custom.flutter.insecure-http-url` | high / medium |
| F5 | Semgrep 커스텀(Dart) — `setString('…token|password|secret…', …)` | `custom.flutter.insecure-storage` | medium |
| F6 | OSV-Scanner — `pubspec.lock` | — | CVSS |
| R1 | Gitleaks + web 의 공개 변수 규칙(`EXPO_PUBLIC_` 포함, Semgrep `public-env-*`·검사 `env-public-secret`) | `custom.web.public-env-*`, `web.env-public-secret` | high |
| R2 | Semgrep 커스텀 — `AsyncStorage.setItem('…token|password…', …)` | `custom.react-native.insecure-storage` | medium |
| R3 | Semgrep 커스텀 — `<WebView … originWhitelist={['*']} />` | `custom.react-native.webview-origin-wildcard` | medium |
| R4 | Semgrep 커스텀 — `console.log/info/debug`에 token·password 등, `if (__DEV__) { … }` 안 제외 | `custom.react-native.sensitive-log` | low |
| R5 | OSV-Scanner — npm lockfile | — | CVSS |

- 하위 `ios/`·`android/`는 감지기가 네이티브 프로파일을 그 하위 경로에만 붙이고, 커스텀 규칙·스택 검사 결과도 그 경로의 프로파일로 귀속된다(E2E 가 하위 경로 밖 귀속이 없는지 확인).
- RN 이 함께 쓰는 web 커스텀 규칙의 결과는 `react-native`로 귀속한다(규칙을 쓰는 프로파일 중 파일을 덮는 것).
- Semgrep 1.182.0 의 Dart 파서로 cascade(`..badCertificateCallback`)·문자열 정규식 리터럴이 동작함을 실측했다. 문자열 리터럴 메타변수의 키 이름은 Swift 와 같이 `pattern-regex`로 본다.
- F2(`--dart-define` 값의 바이너리 평문)·R6(번들 산출물의 키)는 P2 MobSF 단계에서 다룬다.

## 공통 수동 체크리스트
- [ ] 클라이언트에 넣은 키는 **공개된다고 가정** — 서버 프록시 또는 키 제한(도메인·패키지명·API 범위) 적용
- [ ] OTA 업데이트(CodePush, EAS Update) 서명·채널 설정
- [ ] 릴리스 빌드에서 디버그·개발 메뉴 비활성화

## 픽스처
`tests/fixtures/flutter/`, `tests/fixtures/react-native/`: 공용 코드 위반 예 + `ios/`·`android/` 하위의 네이티브 위반 예를 함께 두어 **하위 경로 프로파일 적용**을 검증

> [!warning] 검증 필요
> - ~~Semgrep의 Dart 지원 상태(실험적 여부)와 커스텀 규칙 작성 가능 범위~~ → 1.182.0 에서 cascade·람다·문자열 정규식 패턴 동작 확인
> - ~~OSV-Scanner의 `pubspec.lock`·`pnpm-lock.yaml` 지원~~ → `pubspec.lock`은 픽스처(dio 4.0.0)로 탐지 확인
