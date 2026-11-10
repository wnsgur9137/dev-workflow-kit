# ios 픽스처 (S-iOS 기준선)

`tests/baseline/ios.json` 의 기대 결과를 만드는 일부러 취약한 iOS 앱입니다. 실제 앱이 아닙니다.

| 점검 | 파일 | 기대 |
|---|---|---|
| I1 xcconfig 비밀 | `App/Config.xcconfig` | `xcconfig-secret` |
| I2 ATS 예외 | `App/Info.plist`(NSAllowsArbitraryLoads, 평문 예외 도메인, TLS 1.0) | `ats-arbitrary-loads`, `ats-insecure-http-exception`, `ats-weak-tls` |
| I3 UserDefaults 비밀 저장 | `App/Sources/Session.swift`, `App/Sources/Prefs.swift`(self.defaults), `App/Sources/SuitePrefs.swift`(강제 언래핑) | `insecure-storage` |
| I4 민감 정보 로그 | `App/Sources/Session.swift`, `App/Sources/Auth.swift`·`Refresh.swift`(카멜케이스)·`PasswordText.swift`(passwordField.text)·`PasswordHash.swift`, `App/Legacy/Crypto.m` | `sensitive-log`, `sensitive-log-objc` |
| I5 취약 의존성 | `Package.resolved.fixture`(테스트에서 `Package.resolved` 로 복사) | OSV |
| I6 약한 암호화 | `App/Sources/Hash.swift`, `App/Legacy/Crypto.m`, `App/Legacy/BlockThenCall.m`·`UrlThenCall.m`·`CallThenNote.m`·`AfterComments.m`(같은 줄 주석·URL 문자열 앞뒤의 호출)·`LongLine.m`(수천 자 줄 다음 호출) | `weak-crypto`, `weak-crypto-objc` |
| 음성 | `App/Sources/SecureStore.swift`(Keychain 래퍼), `App/Sources/Cache.swift`(UserDefaults 가 아닌 set), `App/Sources/Tokenizer.swift`(Tokenizer·tokenCount 등), `App/Legacy/Comments.m`(주석·tokenizer), `App/Legacy/InString.m`(문자열 안 알고리즘 이름) | `must_not_find` |
| I7 WebView 파일 접근 | `App/Sources/Web.swift` | `webview-file-access` |
