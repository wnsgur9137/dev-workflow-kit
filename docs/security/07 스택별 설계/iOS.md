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
| I5 | 취약 의존성 | OSV-Scanner | `Package.resolved`, `Podfile.lock` | CVSS 기준 |
| I6 | 약한 암호화 (`CC_MD5`, `kCCAlgorithmDES`, `CommonCrypto` ECB) | Semgrep 커스텀 `ios/weak-crypto` | `*.swift`, `*.m` | medium |
| I7 | WebView JS 브리지·`allowFileAccessFromFileURLs` | Semgrep 커스텀 `ios/webview` | `*.swift` | medium |
| I8 | 바이너리 점검 (ATS, PIE·스택 보호, 임베디드 URL·키) | [[MobSF]] (`/scan-app` IPA) | `.ipa` | MobSF 기준 |

## Semgrep 규칙
- 공식: `semgrep-rules/swift` (규칙 수가 적음), `generic`
- 커스텀: `$PLUGIN/rules/custom/ios/` — I3, I4, I6, I7

## /scan-app (IPA)
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
> - `semgrep-rules`의 Swift 규칙 수와 Semgrep의 Swift/Objective-C 파서 지원 수준
> - OSV-Scanner의 `Package.resolved`(SwiftPM)·`Podfile.lock`(CocoaPods) 지원 여부
> - MobSF iOS 정적분석 항목 범위 (Info.plist·바이너리 보호 기법)
