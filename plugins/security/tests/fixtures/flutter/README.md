# flutter 픽스처 (S-Flutter·RN 기준선)

`tests/baseline/flutter.json` 의 기대 결과를 만드는 일부러 취약한 Flutter 앱입니다. 실제 앱이 아닙니다.
하위 `android/`·`ios/` 의 위반이 **해당 하위 경로의 네이티브 프로파일**로만 잡히는지도 확인합니다.

| 점검 | 파일 | 기대 |
|---|---|---|
| F1 `.env` 를 asset 으로 번들 | `pubspec.yaml` | `flutter.env-asset` |
| F3 릴리스 빌드 난독화 없음 | `.github/workflows/release.yml` | `flutter.build-no-obfuscate` |
| F4 인증서 검증 우회·평문 HTTP | `lib/api.dart` | `bad-certificate-callback`, `insecure-http-url` |
| F5 SharedPreferences 토큰 | `lib/api.dart` | `insecure-storage` |
| F6 취약 의존성 | `pubspec.lock.fixture`(테스트에서 `pubspec.lock` 으로 복사) | `dio@4.0.0` |
| 네이티브 Android | `android/app/src/main/AndroidManifest.xml` | `android.manifest-debuggable` (profile android) |
| 네이티브 iOS | `ios/Runner/Info.plist` | `ios.ats-arbitrary-loads` (profile ios) |
