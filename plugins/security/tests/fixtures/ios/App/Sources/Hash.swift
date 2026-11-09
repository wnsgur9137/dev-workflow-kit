import CommonCrypto
import CryptoKit
import Foundation

func legacyHash(_ data: Data) -> Data {
    var digest = [UInt8](repeating: 0, count: Int(CC_MD5_DIGEST_LENGTH))
    data.withUnsafeBytes { _ = CC_MD5($0.baseAddress, CC_LONG(data.count), &digest) }
    return Data(digest)
}

func weakDigest(_ data: Data) -> String {
    return Insecure.MD5.hash(data: data).description
}
