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
exclude_paths: ["**/Pods/**", "**/DerivedData/**", "**/.build/**", "**/Carthage/Build/**"]
```

## 점검 항목

| # | 점검 | 방법 | 대상 | 심각도 |
|---|---|---|---|---|
| I1 | 하드코딩 시크릿 | Gitleaks + Semgrep `generic` | 소스, `*.plist`, `*.xcconfig` | high |
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
| I1 | Gitleaks (공통) + 스택 검사 — `*.xcconfig`의 비밀 키 평문 값(`$(…)` 참조 제외, **키 이름만**) | `ios.xcconfig-secret` | high |
| I2 | 스택 검사 — `*Info.plist`(XML·바이너리)의 `NSAllowsArbitraryLoads`(high), `…InWebContent`·`…ForMedia`(medium), 예외 도메인의 `NSExceptionAllowsInsecureHTTPLoads`·`NSTemporary…`(medium), `NSExceptionMinimumTLSVersion` TLS 1.0·1.1(medium) | `ios.ats-*` | high / medium |
| I3 | Semgrep 커스텀 — `UserDefaults…set(…, forKey: "…token|password|secret…")` + 공식 `swift-user-defaults` | `custom.ios.insecure-storage` | medium |
| I4 | Semgrep 커스텀 — `print`·`NSLog`·`debugPrint` 인자에 token·password 등, Objective-C `NSLog(@"…password…")` | `custom.ios.sensitive-log(-objc)` | low |
| I5 | OSV-Scanner (공통) — `Package.resolved`. `Podfile.lock`은 "점검되지 않음" 경고 | — | CVSS |
| I6 | Semgrep 커스텀 — `CC_MD5`·`CC_SHA1`·`Insecure.MD5/SHA1`·`kCCAlgorithmDES/3DES`·`kCCOptionECBMode` (Swift), Objective-C 는 같은 이름 정규식 | `custom.ios.weak-crypto(-objc)` | medium |
| I7 | Semgrep 커스텀 — `setValue(true, forKey: "allowFileAccessFromFileURLs"|"allowUniversalAccessFromFileURLs")` | `custom.ios.webview-file-access` | medium |

- Semgrep 은 Objective-C 를 지원하지 않아 `*.m`·`*.mm`은 `generic` 언어 정규식으로만 본다.
- Semgrep 1.182.0 Swift 에서 문자열 리터럴 메타변수(`forKey: $K`)에 `metavariable-regex` 가 맞지 않아 키 이름은 `pattern-regex` 로 확인한다 (실측). `patterns` 안의 정규식 여러 개는 매칭 범위가 겹쳐야 해서 한 정규식으로 쓴다.
- plist 는 표준 `plistlib`로 읽는다(XML 엔티티 선언을 거부). JS 브리지(`WKScriptMessageHandler`)는 정상 사용이 많아 아직 다루지 않는다.

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

> [!warning] 검증 필요
> - ~~`semgrep-rules`의 Swift 규칙 수와 Semgrep의 Swift/Objective-C 파서 지원 수준~~ → `swift/` 규칙은 소수(`swift-user-defaults` 등), Objective-C 는 미지원(generic 정규식으로 보완)
> - ~~OSV-Scanner의 `Package.resolved`(SwiftPM)·`Podfile.lock`(CocoaPods) 지원 여부~~ → P1 확인: `Package.resolved`만 지원, `Podfile.lock`은 v2.7.0이 추출하지 않음 (`unsupported_lockfiles`로 경고)
> - MobSF iOS 정적분석 항목 범위 (Info.plist·바이너리 보호 기법)
