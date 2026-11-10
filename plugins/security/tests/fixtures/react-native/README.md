# react-native 픽스처 (S-Flutter·RN 기준선)

`tests/baseline/react-native.json` 의 기대 결과를 만드는 일부러 취약한 React Native 앱입니다.
하위 `android/`·`ios/` 의 위반이 해당 하위 경로의 네이티브 프로파일로만 잡히는지도 확인합니다.

| 점검 | 파일 | 기대 |
|---|---|---|
| R1 번들에 포함되는 공개 변수 비밀 | `env.fixture`(테스트에서 `.env` 로 복사), `src/config.ts` | `web.env-public-secret`, `public-env-secret` |
| R1 react-native-config 의 비밀 이름 변수 (접두사 무관) | `env.fixture`(`PAYMENT_SECRET_KEY`), `package.json`(`react-native-config`) | `react-native.config-env-secret` |
| R2 AsyncStorage 토큰 (리터럴 값은 리포트에서 가림) | `src/session.ts` | `insecure-storage` |
| R3 WebView 모든 출처 허용 | `src/Browser.tsx` | `webview-origin-wildcard` |
| R3 평문 HTTP | `src/api.ts` | `insecure-http-url` |
| R4 `__DEV__` 밖 민감 로그 | `src/session.ts` | `sensitive-log` |
| 음성 사례 | `src/safe.ts`(`theme`·`tokenizer_lang` 키, 문장 속 token, `__DEV__` 안 로그, localhost 요청) | 기준선 `must_not_find` |
| R5 취약 의존성 | `package-lock.json.fixture`(테스트에서 `package-lock.json` 으로 복사) | `lodash@4.17.20` |
| 네이티브 Android | `android/app/src/main/AndroidManifest.xml` | `android.manifest-exported-component` |
| 네이티브 iOS | `ios/App/Info.plist` | `ios.ats-arbitrary-loads` |
