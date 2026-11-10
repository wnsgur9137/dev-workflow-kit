import Foundation

final class Session {
    func save(accessToken: String, password: String) {
        UserDefaults.standard.set(accessToken, forKey: "accessToken")
        UserDefaults.standard.set(password, forKey: "user_password")
        UserDefaults.standard.set(true, forKey: "onboarded")
        print("login token: \(accessToken)")
    }
}
