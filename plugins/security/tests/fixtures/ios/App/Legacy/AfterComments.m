#import <Foundation/Foundation.h>
#include <CommonCrypto/CommonDigest.h>

// I6 — 같은 줄의 닫힌 블록 주석 여러 개와 "//" 문자열 뒤 호출 (PR #27 3차 재리뷰 S-1)
void afterComments(const void *d, CC_LONG l, unsigned char *o) {
    NSString *s = @"//"; /* a */ /* b */ CC_SHA1(d, l, o);
}
