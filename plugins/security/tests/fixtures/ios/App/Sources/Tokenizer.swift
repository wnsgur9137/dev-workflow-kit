import Foundation

// 음성 — 키워드 뒤에 소문자가 이어지는 이름(Tokenizer)과 흔한 비민감 접미사(tokenCount 등)는 민감 정보가 아니다
struct Tokenizer {
    let count = 0
}

func report(tokenizer: Tokenizer, tokenCount: Int, passwordField: UITextField, isTokenValid: Bool) {
    print(tokenizer.count)
    print("tokenCount \(tokenCount)")
    print(passwordField.isHidden)
    print(isTokenValid)
    print("password_reset sent")
}
