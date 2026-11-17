# /security:scan-app 픽스처

- `android/` — apktool 디코드 형식의 취약 앱 소스 (debuggable·allowBackup·usesCleartextTraffic, base-config 평문·사용자 CA,
  MD5, 로그, 하드코딩 키). 테스트가 MobSF 이미지 안의 apktool·aapt2·apksigner·bundletool 로 **네트워크 없이** APK·AAB 를 빌드한다.
- `ios/` — 최소 Mach-O(`main.c`, Xcode clang 으로 빌드)·ATS 를 끈 `Info.plist`·RN 번들 흉내(`main.jsbundle`)로 IPA 를 만든다.
  Xcode(iphoneos SDK)가 없으면 IPA 테스트는 건너뛴다.
- `mobsf-android.json`·`mobsf-ios.json` — 위 산출물을 MobSF v4.6.4 로 분석한 리포트를 잘라 낸 것 (파서 단위 테스트용).

시크릿은 커밋하지 않는다 — `@@GOOGLE_KEY@@`·`@@AWS_KEY@@` 자리에 테스트가 실행할 때 가짜 키를 만들어 넣는다.
`android/res/values/strings.xml` 의 앱 이름과 `android/assets/` 의 키스토어 흉내 파일 이름은 리포트 인젝션(T5) 확인용 문구다 —
파일 이름은 MobSF 결과의 위치로 summary 에 렌더링되므로, 식별자 문자만 남는지(`IGNORE?ALL?…`) 확인할 수 있다.
