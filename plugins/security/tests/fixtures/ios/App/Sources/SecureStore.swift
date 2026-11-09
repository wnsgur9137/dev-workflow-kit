// 음성 사례: Keychain 래퍼의 set(_:forKey:) 는 insecure-storage 로 잡히면 안 된다 (PR #27 리뷰)
import KeychainSwift

func store(token: String, keychain: KeychainSwift) {
    keychain.set(token, forKey: "accessToken")
}
