---
title: iOS
tags: [security/stack, stack/ios]
status: draft
created: 2026-11-05
profile: ios
---

# iOS (Swift / Objective-C)

상위: [[스택 프로파일 개요]] · 결정: [[ADR-008 스택별 프로파일]]

## 주요 위협
1. 앱 번들·소스에 하드코딩된 API 키 (IPA는 쉽게 풀림)
2. ATS 예외로 인한 평문 HTTP 통신
3. 민감 정보를 `UserDefaults`·파일에 평문 저장 (Keychain 미사용)
4. 취약한 서드파티 의존성 (SPM, CocoaPods)
5. 디버그 로그·디버그 설정이 릴리스 빌드에 남음

## 감지 (`profiles/ios.yaml`)
```yaml
detect: ["**/*.xcodeproj", "**/*.xcworkspace", "**/Package.swift", "**/Podfile"]
exclude_paths: ["**/Pods/**", "**/DerivedData/**", "**/.build/**", "**/Carthage/Build/**", "**/macos/**"]
```

## 점검 항목

| # | 점검 | 방법 | 대상 | 심각도 |
|---|---|---|---|---|
| I1 | 하드코딩 시크릿 | Gitleaks + Semgrep `generic` (+ 스택 검사 xcconfig — 구현 메모) | 소스, `*.plist`, `*.xcconfig` | high |
| I2 | ATS 예외 (`NSAllowsArbitraryLoads`, `NSExceptionAllowsInsecureHTTPLoads`) | 커스텀 검사 (plist 파싱) | `Info.plist` | high |
| I3 | `UserDefaults`에 토큰·비밀번호 저장 | Semgrep 커스텀 `ios/insecure-storage` | `*.swift` | medium |
| I4 | `print`/`NSLog`로 민감 정보 출력 | Semgrep 커스텀 `ios/sensitive-log` | `*.swift`, `*.m` | low |
| I5 | 취약 의존성 | OSV-Scanner | `Package.resolved` (`Podfile.lock`은 미지원 — "점검되지 않음" 경고) | CVSS 기준 |
| I6 | 약한 암호화 (`CC_MD5`, `kCCAlgorithmDES`, `CommonCrypto` ECB) | Semgrep 커스텀 `ios/weak-crypto` | `*.swift`, `*.m` | medium |
| I7 | WebView JS 브리지·`allowFileAccessFromFileURLs` | Semgrep 커스텀 `ios/webview` | `*.swift` | medium |
| I8 | 바이너리 점검 (ATS, PIE·스택 보호, 임베디드 URL·키) | [[MobSF]] (`/security:scan-app` IPA) | `.ipa` | MobSF 기준 |

## 구현 메모 (S-iOS)

| # | 구현 | 규칙·검사 ID | 심각도 |
|---|---|---|---|
| I1 | Gitleaks (공통) + 스택 검사 — `*.xcconfig`의 비밀 키 평문 값(조건부 `[sdk=…][arch=…]` 여러 개, `//` 는 어디서든 주석, `$(…)`·`${…}` 참조는 안쪽부터 지우고 남은 평문만 판정 — 다 못 지운 중첩 참조와 참조 바로 뒤 경로(`$(SRCROOT)/…`)는 제외, **키 이름만**). plist 의 평문 비밀은 Gitleaks 만 본다 | `ios.xcconfig-secret` | high |
| I2 | 스택 검사 — `*Info.plist`(대소문자 무시, XML·바이너리)의 `NSAllowsArbitraryLoads`(high — iOS 10+ 에서 무시되는 조합, 즉 `…ForMedia`·`…InWebContent`·`NSAllowsLocalNetworking` 중 하나가 있으면 low), `…InWebContent`·`…ForMedia`(medium), 예외 도메인의 평문 허용(`NSException…`·`NSTemporaryException…`·`NSThirdPartyException…AllowsInsecureHTTPLoads`, medium)·최소 TLS 1.0·1.1(medium). `NSIncludesSubdomains`는 evidence 에 표시. 줄 번호는 `<key>…</key>`를 문서 순서대로 이어 찾고(선형), 결과는 줄과 상관없이 키 경로(package)로 구분(바이너리·한 줄짜리 plist, package 가 120자를 넘는 93자 초과 도메인은 해시 접미사). CDATA·문자 참조로 쓴 정수와 100자 이상 정수가 있는 plist 는 해석하지 않음 | `ios.ats-*` | high / medium / low |
| I3 | Semgrep 커스텀 — UserDefaults(`standard`·`suiteName:`(`?`·`!`)·이름이 defaults 인 변수·`self.defaults` 같은 속성)의 `set(…, forKey: "…token|password|secret|session_id…")` + 공식 `swift-user-defaults`. Keychain 래퍼의 같은 API 는 제외. 지역 별칭(`let ud = UserDefaults.standard; ud.set(…)`)은 잡지 않는다 | `custom.ios.insecure-storage` | medium |
| I4 | Semgrep 커스텀 — `print`·`NSLog`·`debugPrint`·`os_log`·`Logger` 인자에 token·password 등(카멜케이스 `userPassword`·`refreshToken` 포함, 뒤에 소문자가 이어지는 `Tokenizer` 등과 `tokenCount`·`passwordField`·`isTokenValid`·`password_reset` 같은 비민감 접미사는 제외 — 단 `passwordField.text`·`tokenLabel.stringValue`처럼 입력값을 꺼내면 탐지, ObjC 메시지 형태 `[self.passwordField text]`는 미탐), Objective-C `NSLog`의 형식 문자열·인자 | `custom.ios.sensitive-log(-objc)` | low |
| I5 | OSV-Scanner (공통) — `Package.resolved`. `Podfile.lock`은 "점검되지 않음" 경고 | — | CVSS |
| I6 | Semgrep 커스텀 — `CC_MD5`·`CC_SHA1`(`_Init` 포함)·`Insecure.MD5/SHA1`(스트리밍 포함)·`kCCAlgorithmDES/3DES/RC4/RC2`·`kCCOptionECBMode` (Swift), Objective-C 는 같은 이름 정규식(줄 단위 — 문자열 리터럴과 같은 줄에서 닫힌 블록 주석은 건너뛰고, 닫히지 않은 `//`·`/*` 뒤와 문자열 안의 이름은 제외) | `custom.ios.weak-crypto(-objc)` | medium |
| I7 | Semgrep 커스텀 — `setValue(true|1|NSNumber(value: true), forKey: "allowFileAccessFromFileURLs"|"allowUniversalAccessFromFileURLs")`, Objective-C `setValue:@YES forKey:@"…"` | `custom.ios.webview-file-access(-objc)` | medium |

- Semgrep 은 Objective-C 를 지원하지 않아 `*.m`·`*.mm`은 `generic` 언어 정규식으로만 본다.
- Semgrep 1.182.0 Swift 에서 문자열 리터럴 메타변수(`forKey: $K`)에 `metavariable-regex` 가 맞지 않아 키 이름은 `pattern-regex` 로 확인한다 (실측). `patterns` 안의 정규식 여러 개는 매칭 범위가 겹쳐야 해서 한 정규식으로 쓴다.
- plist 는 표준 `plistlib`로 읽는다(XML 엔티티 선언을 거부). 100자리 넘는 `<integer>`는 파싱 전에 거른다(Python 3.8·3.9 초기 버전의 int 변환 이차 시간). JS 브리지(`WKScriptMessageHandler`)는 정상 사용이 많아 아직 다루지 않는다.

## Semgrep 규칙
- 공식: `semgrep-rules/swift` (규칙 수가 적음), `generic`
- 커스텀: `$PLUGIN/rules/custom/ios/` — I3, I4, I6, I7

## /security:scan-app (IPA)
- **직접 빌드한 IPA**(Xcode Archive → Export)는 암호화되지 않아 MobSF 정적분석 가능
- App Store에서 받은 IPA는 FairPlay 암호화로 분석 불가 → 범위 밖
- MobSF 결과의 ATS 항목은 I2와 중복될 수 있음 → 정규화에서 같은 위치면 병합

## 수동 체크리스트 (summary 하단)
- [ ] 릴리스 빌드에서 디버그 메뉴·테스트 서버 URL 제거
- [ ] Keychain 접근성(`kSecAttrAccessible...`) 수준 확인
- [ ] 푸시 토큰·딥링크(Universal Link) 처리 시 입력 검증

## 픽스처 (회귀 기준선)
`tests/fixtures/ios/`: `NSAllowsArbitraryLoads=true`인 `Info.plist`, `UserDefaults.standard.set(token, ...)`, `CC_MD5` 호출, 가짜 키 문자열이 든 Swift 파일 몇 개

## 한계
- Semgrep Swift 지원 범위가 다른 언어보다 좁음 → 커스텀 규칙 품질에 의존
- Objective-C는 Semgrep 지원이 제한적 → 시크릿·바이너리 점검 위주
- 줄 단위 정규식 규칙(`*-objc`)은 여러 줄 블록 주석의 가운데 줄을 주석으로 알아보지 못한다(오탐). `weak-crypto-objc`는 줄에서 닫히지 않은 `"`(예: 문자 리터럴 `'"'`·`'\"'`) 뒤를 보지 않고, 한 줄이 약 13만 자를 넘는 파일은 PCRE2 한도에 걸려 놓칠 수 있다(미탐)
- xcconfig: 참조 바로 뒤 경로처럼 보이는 값(`$(PREFIX)/평문`), `${`가 섞인 평문, `$(VAR:default=…)`의 기본값은 판정하지 않는다
- plist 정수 사전 차단은 UTF-8 바이트 기준이라 UTF-16 plist 는 거치지 않는다. 거대 정수는 Python 의 int 자릿수 제한(3.11+, 또는 CVE-2020-10735 패치 버전)에 걸려 "plist 를 해석하지 못했습니다" 경고로 끝난다 — 그보다 오래된 Python 은 지원하지 않는다

> [!warning] 검증 필요
> - ~~`semgrep-rules`의 Swift 규칙 수와 Semgrep의 Swift/Objective-C 파서 지원 수준~~ → `swift/` 규칙은 소수(`swift-user-defaults` 등), Objective-C 는 미지원(generic 정규식으로 보완)
> - ~~OSV-Scanner의 `Package.resolved`(SwiftPM)·`Podfile.lock`(CocoaPods) 지원 여부~~ → P1 확인: `Package.resolved`만 지원, `Podfile.lock`은 v2.7.0이 추출하지 않음 (`unsupported_lockfiles`로 경고)
> - MobSF iOS 정적분석 항목 범위 (Info.plist·바이너리 보호 기법)
