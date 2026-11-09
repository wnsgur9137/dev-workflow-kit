import Foundation

// 음성 — 키워드 뒤에 소문자가 이어지는 이름(Tokenizer)은 민감 정보가 아니다
struct Tokenizer {
    let count = 0
}

func report(tokenizer: Tokenizer) {
    print(tokenizer.count)
}
