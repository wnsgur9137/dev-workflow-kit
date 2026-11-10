import Foundation

// I4 — 비민감 접미사 목록에 없는 민감 이름(passwordHash)은 계속 잡는다 (PR #27 3차 재리뷰)
func debugHash(passwordHash: String) {
    print("hash=\(passwordHash)")
}
