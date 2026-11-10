#import <Foundation/Foundation.h>

// 음성 — 주석 안의 알고리즘 이름과 tokenizer 로그 (PR #27 재리뷰 S1·W1)
void legacyNote(void) {
    int x = 1; // CC_MD5 은 예전 구현에서 썼다
    /* CC_SHA1(data, len, out) 은 지웠다 */
    NSLog(@"tokenizer ready %d", x);
}
