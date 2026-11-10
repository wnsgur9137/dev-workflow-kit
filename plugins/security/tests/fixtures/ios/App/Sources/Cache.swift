import UIKit

// 음성 — UserDefaults 가 아닌 객체의 set·setValue (PR #27 2차 재리뷰 S-B)
final class TokenCache {
    let cache = NSCache<NSString, NSString>()
    func set(_ v: String, forKey k: String) { cache.setObject(v as NSString, forKey: k as NSString) }

    func keep(token: String, view: UIView) {
        self.cache.set(token, forKey: "authToken")
        view.layer.setValue(token, forKey: "authToken")
    }
}
