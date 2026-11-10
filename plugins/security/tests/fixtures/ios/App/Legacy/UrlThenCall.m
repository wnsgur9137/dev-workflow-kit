#import <Foundation/Foundation.h>
#include <CommonCrypto/CommonDigest.h>

// I6 — // 가 든 URL 문자열 뒤 실제 호출 (PR #27 2차 재리뷰 W-A)
void urlThenDigest(const void *d, CC_LONG l, unsigned char *o) {
    NSURL *u = [NSURL URLWithString:@"https://e.com"]; CC_SHA1(d, l, o);
}
