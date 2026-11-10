import Foundation

// I3 — 클래스 안 self.defaults (PR #27 재리뷰 W2)
final class Prefs {
    let defaults = UserDefaults.standard

    func store(token: String) {
        self.defaults.set(token, forKey: "authToken")
    }
}
