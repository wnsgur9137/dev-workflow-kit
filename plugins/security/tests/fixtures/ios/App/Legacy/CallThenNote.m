#import <Foundation/Foundation.h>
#include <CommonCrypto/CommonDigest.h>

// I6 — 호출 뒤 줄 끝 주석 (PR #27 2차 재리뷰 S-B)
void digestWithNote(const void *d, CC_LONG l, unsigned char *o) {
    CC_MD5(d, l, o); // 호환용
}
