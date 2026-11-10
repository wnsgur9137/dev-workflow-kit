import Foundation

// I3 — 강제 언래핑 UserDefaults(suiteName:) (PR #27 재리뷰 W2)
func storeShared(token: String) {
    UserDefaults(suiteName: "group.example")!.set(token, forKey: "refresh_token")
}
