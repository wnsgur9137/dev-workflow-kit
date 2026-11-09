# android 픽스처 (S-Android 기준선)

`tests/baseline/android.json` 의 기대 결과를 만드는 일부러 취약한 Android 앱입니다. 실제 앱이 아닙니다.

| 점검 | 파일 | 기대 |
|---|---|---|
| A1 서명 비밀번호 평문 | `gradle.properties` | `properties-secret` |
| A2 debuggable·allowBackup | `app/src/main/AndroidManifest.xml` | `manifest-debuggable`, `manifest-allow-backup` |
| A3 권한 없는 exported 컴포넌트 | `AndroidManifest.xml` 의 `SyncService`·`DataProvider`(음성: 런처 Activity, 권한 있는 `SafeProvider`) | `manifest-exported-component` |
| A4 평문 통신 | `AndroidManifest.xml`(`usesCleartextTraffic`), `res/xml/network_security_config.xml` | `manifest-cleartext`, `nsc-cleartext`, `nsc-user-certs` |
| A5 릴리스 난독화 꺼짐 | `app/build.gradle` | `gradle-release-minify-disabled` |
| A6 WebView | `MainActivity.kt`(addJavascriptInterface·allowFileAccess) | `webview-javascript-interface`, `webview-file-access` |
| A7 world-readable | `Storage.java` | `world-readable-mode` |
| A8 취약 의존성 | `gradle.lockfile.fixture`(테스트에서 `app/gradle.lockfile` 로 복사) | `jackson-databind@2.9.8` |
