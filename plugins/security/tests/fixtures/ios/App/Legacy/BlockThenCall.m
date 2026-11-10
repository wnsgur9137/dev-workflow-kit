#import <Foundation/Foundation.h>
#include <CommonCrypto/CommonDigest.h>

// I6 — 같은 줄의 닫힌 블록 주석 뒤 실제 호출 (PR #27 2차 재리뷰 W-A)
void inlineDigest(const void *d, CC_LONG l, unsigned char *o) {
    /* old */ CC_MD5(d, l, o);
}
