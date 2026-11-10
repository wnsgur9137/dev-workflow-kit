import UIKit

// I4 — 입력 필드 값 자체(passwordField.text)를 출력 (PR #27 3차 재리뷰 W-2)
func debugLogin(passwordField: UITextField) {
    print(passwordField.text ?? "")
}
