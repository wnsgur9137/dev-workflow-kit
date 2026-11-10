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
| F1 | 스택 검사 — `pubspec.yaml` 최상위 `flutter.assets`의 `.env`·`.env.*`. 블록 목록(같은 들여쓰기 포함)·흐름 문법(`assets: [.env, a/]`, 여러 줄)·Flutter 3.19+ `- path: .env`·`- {path: …, flavors: […]}`를 읽는다. 예시 파일(이름 조각에 `example`·`sample`·`template`·`dist`·`defaults`)은 제외. 디렉터리 항목(`- assets/env/`·`- ./`)은 그 폴더 바로 아래의 `.env*` 파일이 있으면 보고. 여러 줄 흐름 문법은 괄호 깊이를 세어 끝을 찾고(`{path: …, flavors: [dev]}` 중첩), `- flavors: […]` 다음 줄의 `path:`도 같은 항목으로 읽는다 | `flutter.env-asset` | high |
| F3 | 스택 검사(저장소 전체) — `.github/workflows/*.yml`·`.circleci/config.yml`·`codemagic.yaml`·`bitrise.yml`·`.gitlab-ci.yml`·`azure-pipelines.yml`·`bitbucket-pipelines.yml`·`melos.yaml`·`Jenkinsfile`·`Makefile`·`*.sh`·`fastlane/Fastfile`의 `flutter build apk|appbundle|ipa|ios|ios-framework`에 `--obfuscate` 없음. 주석(Jenkinsfile 은 `//` 도)을 지우고 줄 끝 `\` 이음·YAML 접힘 블록(`run: >`)·YAML plain 여러 줄 스칼라(`- run: flutter build apk` 다음 줄에 더 깊게 들여쓴 `--obfuscate`)를 한 명령으로 합친다(`MAX_LINE` 상한). YAML 단계의 `name:` 값(`name: >`·`name: |` 블록 본문 포함)은 명령으로 보지 않는다. `--debug`·`--profile`, `echo`·`printf` 출력 문구는 제외하고, 플래그를 변수(`$(FLAGS)`·`${{ … }}`)로 넘기면 판단을 보류한다. 빌드 명령이 없으면 판단하지 않음 | `flutter.build-no-obfuscate` | medium |
| F4 | Semgrep 커스텀(Dart) — `badCertificateCallback = (...) => true`(cascade 포함), `Uri.parse`·`Uri.http`·Dio `BaseOptions(baseUrl:)`·`dio.get/post`의 `http://`(보간 문자열 `'http://host/$id'` 포함, 호스트가 정확히 localhost·127.0.0.1·10.0.2.2 이면 제외 — `localhost.evil.com`·`10.0.2.20`은 잡음) | `custom.flutter.bad-certificate-callback`, `custom.flutter.insecure-http-url` | high / medium |
| F5 | Semgrep 커스텀(Dart) — `setString(<키>, …)`의 키(리터럴·상수 `kTokenKey`·보간 `'${prefix}_token'`)가 token·password·secret 등. 키워드(+ 선택적 `Key`·`_id` 꼬리) 뒤에 영문자·숫자·`_`가 이어지면 제외(`tokenizer_lang`·`tokenCount`·`PASSWORDLESS_ENABLED`·`last_token_refresh_at`) | `custom.flutter.insecure-storage` | medium |
| F6 | OSV-Scanner — `pubspec.lock` | — | CVSS |
| R1 | Gitleaks + web 의 공개 변수 규칙(`EXPO_PUBLIC_` 포함, Semgrep `public-env-*`·검사 `env-public-secret`) + `react-native-config` 의존성이 있으면 프로젝트 루트(`package.json` 폴더)의 `.env*`에서 비밀 이름 변수를 접두사와 무관하게 보고(값 미포함). react-native-config 는 루트 `.env`(`ENVFILE`도 루트 기준)만 읽으므로 하위 폴더(`server/.env`·`e2e/.env.test`)는 보지 않는다 | `custom.web.public-env-*`, `web.env-public-secret`, `react-native.config-env-secret` | high (API 키 이름은 medium) |
| R2 | Semgrep 커스텀 — `AsyncStorage.setItem(<키>, …)`의 키(리터럴·상수 `TOKEN_KEY`·`kTokenKey`·보간 `` `${prefix}:token` ``)가 token·password 등. F5 와 같은 꼬리 규칙으로 `tokenCount`·`PASSWORDLESS_ENABLED`·`last_token_refresh_at` 제외 | `custom.react-native.insecure-storage` | medium |
| R3 | Semgrep 커스텀 — `<WebView … originWhitelist={[…, '*', …]} />`, `fetch`·`axios.*`·`axios.create({baseURL})`·`axios({ url })`·인스턴스 호출(`api.get/post/put/patch/delete/head/request`)의 `http://`(보간 템플릿 `` `http://host/${id}` `` 포함)·`new WebSocket('ws://…')`(로컬 개발 주소 제외) | `custom.react-native.webview-origin-wildcard`, `custom.react-native.insecure-http-url` | medium |
| R4 | Semgrep 커스텀 — `console.log/info/debug/warn/error`의 인자 식(문자열 연결·함수 호출·`??`·`!`·`as`·템플릿 보간·객체) 안의 식별자·멤버·객체 키·대괄호 키(`user['token']`) 이름이 token·password 등으로 끝남(`authToken`·`user.accessToken`·`'token: ' + token`). `metavariable-pattern`으로 인자 안을 찾는다. `if (__DEV__)`·`if (__DEV__ && …)`의 then 쪽, `__DEV__ && console.log(…)`, `if (!__DEV__) … else`의 else 쪽은 제외하고, 앞 두 if 의 else 쪽과 `if (!__DEV__)`의 then 쪽은 잡는다. 문자열 문장·라벨(`'Refresh token expired'`)과 불리언 이름(`hasToken`·`showPassword` — `has`·`is`·`show`·`should`·`no` 접두사)은 잡지 않음 | `custom.react-native.sensitive-log` | low |
| R5 | OSV-Scanner — npm lockfile | — | CVSS |

- 하위 `ios/`·`android/`는 감지기가 네이티브 프로파일을 그 하위 경로에만 붙이고, 커스텀 규칙·스택 검사 결과도 그 경로의 프로파일로 귀속된다(E2E 가 하위 경로 밖 귀속이 없는지 확인).
- 커스텀 규칙은 Semgrep 이 저장소 전체에 한 번 돌리므로 귀속을 이렇게 정한다(`normalize.py` `ProfileIndex.for_custom`): 파일을 덮는 가장 깊은 프로파일이 그 규칙을 쓰면 그 프로파일(RN 이 함께 쓰는 web 규칙 결과는 `react-native`), 그 프로파일이 규칙을 쓰지 않고 그 언어 확장자를 보는 다른 스택이면 **버린다**(모노레포 `apps/web`의 `react-native.sensitive-log`), 어느 프로파일도 덮지 않는 파일(서버가 `api/`에만 잡힌 저장소의 루트 `Dockerfile` 등)은 남겨 규칙을 쓰는 프로파일로 귀속한다.
- CWE-312·532·798 규칙(저장·로그·하드코딩 비밀)의 evidence 는 문자열 리터럴 값을 `[MASKED]`로 가리고, **키 자리**(`(`·`[` 바로 뒤 첫 인자 — 단 뒤에 `forKey:`·`key:` 라벨이 이어지면 값, `forKey:`·`key:` 뒤, 사이 줄바꿈 허용)의 키 이름(비밀 단어를 포함한 공백 없는 짧은 이름)만 남긴다 — 값 자리의 리터럴은 비밀 단어가 있어도 가린다(`setItem('password', '[MASKED]')`). 백틱·삼중 따옴표 리터럴은 줄을 넘겨 닫힐 때까지 가리고, 리터럴 밖 `//`·공백 뒤 `# ` 주석은 그대로 둔다. 키=값 형태가 아닌 인자 값 노출 방지. E2E 가 리포트 폴더(raw 포함)에 비밀 단어가 든 픽스처 리터럴(`fixture-password-hunter2`)이 없는지 확인한다.
- 규칙 단위 테스트: `tests/semgrep/<스택>/`(규칙 파일과 같은 이름, `ruleid:`·`ok:` 주석)을 고정 이미지의 `semgrep --test`로 돌린다(`test_real_semgrep_rule_unit_tests`). 음성 예는 픽스처 `lib/safe.dart`·`.github/workflows/safe.yml`·`src/safe.ts`로 분리해 기준선 `must_not_find`로 고정했다.
- Semgrep 1.182.0 실측: Dart 파서로 cascade(`..badCertificateCallback`)·문자열 정규식 리터럴이 동작하고, Dart·JS 에서는 문자열 리터럴 메타변수에도 `metavariable-regex`가 맞는다(Swift 와 다름). `if (__DEV__) {…} else $ELSE` + `focus-metavariable`로 else 쪽만 다시 볼 수 있다.
- F1 디렉터리 asset: flutter_tools `asset.dart`의 `_parseAssetsFromFolder`는 `listSync()` 결과에서 하위 폴더만 빼고 숨김 파일을 거르지 않는다(바로 아래 파일만, 재귀 없음) — 그래서 폴더 바로 아래 `.env*`만 본다.
- 한계 (PR #28 2차 리뷰 반영 후 남은 것):
  - R4 는 삼항(`__DEV__ ? console.log(token) : …`)·`if (!__DEV__) return` 뒤의 로그·`__DEV__` 를 담은 변수(`const dev = __DEV__`)는 구분하지 않는다(보고됨). 중첩 분기(`if (__DEV__) { … }` 안의 else 쪽 등)는 가장 바깥 분기만 본다. 로그 인자 안의 `token.length`·`password.trim()`처럼 민감 이름 변수에서 파생된 값도 보고된다(구 규칙과 같은 범위).
  - F3 는 변수로 넘긴 플래그·다른 스크립트를 호출하는 빌드는 판단하지 않는다. 따옴표 YAML 여러 줄 스칼라(`run: "flutter build apk\n  --obfuscate"`)·Groovy `/* … */` 블록 주석·Makefile 의 `$(…)` 정의 추적은 하지 않는다.
  - F4·R3 은 변수에 담은 URL(`fetch(url)`·`Uri.parse(base + '/x')`)·문자열 연결 URL 을 따라가지 않는다. R3 의 WebView `originWhitelist={origins}`처럼 변수에 담은 출처 목록은 보지 않는다.
  - F1 은 YAML 앵커·별칭(`assets: *list`)과 여러 문서(`---`)를 해석하지 않는다.
  - evidence 리터럴 마스킹은 따옴표 안의 이름만 키로 본다 — 키를 상수로 넘기면(`setItem(TOKEN_KEY, 'v')`) 상수 이름은 리터럴이 아니라 남고 값은 가려진다. `/* … */` 블록 주석 안의 따옴표는 리터럴로 본다(주석 문구가 `[MASKED]`가 될 수 있음).
  - evidence 리터럴 마스킹의 키 자리 판정은 "`(`·`[` 바로 뒤 첫 인자 = 키" 가정이다(3차 리뷰 M1). 첫 인자 리터럴 뒤 40자 안에 `,` 와 `forKey:`·`key:` 라벨이 이어지면(Swift `set("<값>", forKey:)`) 값으로 보고 가리지만, 그 밖의 값-먼저 API(CWE-798 `login('SuperSecret99')` 등)에서 비밀 단어를 포함한 공백 없는 첫 인자 리터럴은 키로 보고 남긴다. 리터럴 밖 줄 끝 주석(`log('a') // 'hunter2'`) 안의 따옴표는 가리지 않는다.
  - R4 는 호출·생성 대상 이름(`validatePassword(p)`·`new Token()`)과 값이 리터럴인 객체 키(`{ password: '***' }`), 뒤에 오는 `__DEV__`(`if (x && __DEV__)`·`a && __DEV__ && console.log(…)`)는 제외한다(3차 리뷰 S4). 호출하지 않는 함수 참조(`console.log(setToken)`)·상수 멤버(`Keys.TOKEN`·`styles.password`)는 여전히 보고되고, 중괄호 없는 `if (!__DEV__) console.log(token); else …` 의 then 쪽은 놓친다.
  - R3 인스턴스 호출(`$O.get(…)` 등)은 수신자 이름이 `map`·`cache`·`params`·`storage`·`router`·`i18n`·`headers` 로 끝나면 제외하는 이름 기반 판정이다(3차 리뷰 S3) — 다른 이름의 Map·캐시는 보고될 수 있고, 그 이름으로 끝나는 HTTP 클라이언트는 놓친다. Flutter F4 의 `$D.get`(`prefs.get`·`map.get`) 오탐은 그대로다.
  - R2·F5 저장 키 정규식은 키워드 뒤 `Key`·`_id`(복수 포함)·버전 꼬리(`_v2`)까지만 허용한다 — `token_old` 같은 다른 꼬리는 잡지 않는다.
  - F3·F1 은 따옴표 짝이 맞지 않는 경우(Jenkinsfile 여러 줄 `'''` 안의 `//`, pubspec `assets: [it's/, .env]`)를 놓친다. F1 은 `transformers:` 아래 더 깊은 `path:` 도 asset 으로 읽는다(실제 transformer 항목에는 `path:` 가 없어 영향 없음).
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
