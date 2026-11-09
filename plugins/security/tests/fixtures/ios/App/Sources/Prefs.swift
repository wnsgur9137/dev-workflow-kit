import Foundation

// I3 — 클래스 안 self.defaults·강제 언래핑 UserDefaults (PR #27 재리뷰 W2)
final class Prefs {
    let defaults = UserDefaults.standard

    func store(token: String) {
        self.defaults.set(token, forKey: "authToken")
        UserDefaults(suiteName: "group.example")!.set(token, forKey: "refresh_token")
    }
}
