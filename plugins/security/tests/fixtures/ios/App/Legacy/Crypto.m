#import <CommonCrypto/CommonCrypto.h>

void legacy(NSString *password) {
    NSLog(@"password=%@", password);
    CCCrypt(kCCEncrypt, kCCAlgorithmDES, kCCOptionECBMode, NULL, 0, NULL, NULL, 0, NULL, 0, NULL);
}
