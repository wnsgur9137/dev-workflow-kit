# ios 픽스처 (S-iOS 기준선)

`tests/baseline/ios.json` 의 기대 결과를 만드는 일부러 취약한 iOS 앱입니다. 실제 앱이 아닙니다.

| 점검 | 파일 | 기대 |
|---|---|---|
| I1 xcconfig 비밀 | `App/Config.xcconfig` | `xcconfig-secret` |
| I2 ATS 예외 | `App/Info.plist`(NSAllowsArbitraryLoads, 평문 예외 도메인, TLS 1.0) | `ats-arbitrary-loads`, `ats-insecure-http-exception`, `ats-weak-tls` |
| I3 UserDefaults 비밀 저장 | `App/Sources/Session.swift` | `insecure-storage` |
| I4 민감 정보 로그 | `App/Sources/Session.swift`, `App/Legacy/Crypto.m` | `sensitive-log`, `sensitive-log-objc` |
| I5 취약 의존성 | `Package.resolved.fixture`(테스트에서 `Package.resolved` 로 복사) | OSV |
| I6 약한 암호화 | `App/Sources/Hash.swift`, `App/Legacy/Crypto.m` | `weak-crypto`, `weak-crypto-objc` |
| 음성 | `App/Sources/SecureStore.swift`(Keychain 래퍼) | `must_not_find` |
| I7 WebView 파일 접근 | `App/Sources/Web.swift` | `webview-file-access` |
