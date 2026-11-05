# iOS Review Priorities

| Priority | Category | Description |
|----------|----------|-------------|
| 1 | **Memory Management** | Retain cycles, strong reference in closures, `[weak self]` usage, `deinit` verification |
| 2 | **Thread Safety** | Main thread UI updates, `@MainActor` usage, data race conditions, `DispatchQueue` usage |
| 3 | **Crash Prevention** | Force unwrap (`!`), force cast (`as!`), unhandled optionals, index out of bounds |
| 4 | **Architecture** | MVVM/MVC/Clean Architecture compliance, dependency injection, protocol-oriented design |
| 5 | **API Design** | Access control (`public/private/internal`), naming conventions, protocol conformance |
| 6 | **Performance** | TableView/CollectionView reuse, image caching, lazy loading, unnecessary redraws |
| 7 | **UI/UX** | Auto Layout constraints, safe area handling, dynamic type support, dark mode |
| 8 | **Error Handling** | `Result` type usage, `do-catch` blocks, user-facing error messages |
| 9 | **Testing** | Testability, mock/stub usage, XCTest assertions |
| 10 | **Swift Conventions** | Swift naming guidelines, modern Swift features (`async/await`, `Sendable`) |

## iOS-Specific Checks

- `@Sendable` compliance for Swift Concurrency
- `MainActor` isolation for UI code
- Proper use of `Task` and `TaskGroup`
- SwiftUI `@State`, `@Binding`, `@ObservedObject` correctness
- CoreData/SwiftData thread confinement
- Info.plist privacy descriptions for permissions

## iOS Security Checklist

- Keychain 사용 여부 (민감 데이터를 UserDefaults에 저장하지 않는지)
- ATS (App Transport Security) 예외 설정 확인 (Info.plist의 `NSAppTransportSecurity`)
- 하드코딩된 시크릿/API 키 탐지 (문자열 리터럴에 key, secret, token, password 패턴)
- 바이오메트리 인증 우회 가능성 (`LAContext` 사용 패턴)
- 디버그 코드 잔재 (`#if DEBUG` 외부의 `print`/`NSLog`)
- `URLSession` TLS 핀닝 설정 확인
- 클립보드(`UIPasteboard`) 민감 데이터 노출
