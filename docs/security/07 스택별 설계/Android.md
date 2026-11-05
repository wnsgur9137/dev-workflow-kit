---
title: Android
tags: [security/stack, stack/android]
status: draft
created: 2026-11-05
profile: android
---

# Android (Kotlin / Java)

상위: [[스택 프로파일 개요]] · 결정: [[ADR-008 스택별 프로파일]]

## 주요 위협
1. APK에 포함된 API 키 (디컴파일로 쉽게 추출)
2. Manifest 설정 오류 (`debuggable`, `allowBackup`, `exported` 컴포넌트)
3. 평문 통신 허용 (`usesCleartextTraffic`, network_security_config)
4. 난독화 미적용 (R8/ProGuard 꺼짐)
5. 취약 의존성 (Gradle)

## 감지 (`profiles/android.yaml`)
```yaml
detect:
  - { glob: "**/AndroidManifest.xml", root_markers: [settings.gradle, settings.gradle.kts] }
  - { file: "**/build.gradle", has_dependency: [com.android.application, com.android.library] }
  - { file: "**/build.gradle.kts", has_dependency: [com.android.application, com.android.library] }
exclude_paths: ["**/build/**", "**/.gradle/**", "**/generated/**"]
```
- `build.gradle*` 파일 존재만으로는 일반 JVM 서버(Spring 등)와 구분되지 않아 **Android Gradle 플러그인 id**가 있을 때만 감지한다 (P0 구현 시 변경).
- `AndroidManifest.xml`은 `app/src/main/`에 있으므로 감지 항목의 `root_markers`로 가장 가까운 Gradle 루트(`settings.gradle*`가 있는 폴더)를 하위 프로젝트 경로로 잡는다. Flutter·RN의 `android/`가 이렇게 잡힌다.

## 점검 항목

| # | 점검 | 방법 | 대상 | 심각도 |
|---|---|---|---|---|
| A1 | 하드코딩 시크릿 | Gitleaks + Semgrep `generic` | 소스, `strings.xml`, `gradle.properties`, `local.properties` 커밋 여부 | high |
| A2 | `android:debuggable="true"`, `android:allowBackup="true"` | 커스텀 검사 (XML 파싱) | `AndroidManifest.xml` | high / medium |
| A3 | `exported="true"` 이면서 권한 없는 Activity·Service·Receiver·Provider | 커스텀 검사 | `AndroidManifest.xml` | high |
| A4 | 평문 통신 (`usesCleartextTraffic`, `cleartextTrafficPermitted`) | 커스텀 검사 | Manifest, `res/xml/network_security_config.xml` | high |
| A5 | 릴리스 빌드 `minifyEnabled false` | 커스텀 검사 (Gradle 텍스트) | `build.gradle(.kts)` | medium |
| A6 | WebView `setJavaScriptEnabled` + `addJavascriptInterface`, `setAllowFileAccess` | Semgrep `java`/`kotlin` 공식 + 커스텀 | `*.kt`, `*.java` | medium |
| A7 | 약한 암호화·`SecureRandom` 시드 고정·`MODE_WORLD_READABLE` | Semgrep 공식 `java`/`kotlin` | 소스 | medium |
| A8 | 취약 의존성 | OSV-Scanner | `gradle.lockfile`, `verification-metadata.xml` | CVSS 기준 |
| A9 | 바이너리 점검 (권한, 인증서, 임베디드 키, 난독화) | [[MobSF]] (`/security:scan-app` APK·AAB) | `.apk`, `.aab` | MobSF 기준 |

## Semgrep 규칙
- 공식: `semgrep-rules/kotlin`, `semgrep-rules/java`(Android 관련 포함), `generic`
- 커스텀: `$PLUGIN/rules/custom/android/` — A6 보강

## SCA 한계와 대응
- Gradle 프로젝트 대부분은 lockfile이 없음 → OSV 정확도 낮음
- 대응: lockfile이 없으면 summary에 **`dependencyLocking` 활성화 방법**을 안내 (Gradle `--write-locks`)

## /security:scan-app (APK·AAB)
- 릴리스 빌드(`assembleRelease`/`bundleRelease`) 기준으로 판단, 디버그 빌드의 `debuggable`은 별도 표시
- A2·A4는 소스 점검과 MobSF가 중복될 수 있음 → 정규화에서 병합

## 수동 체크리스트
- [ ] Play App Signing 사용, 업로드 키 보관 위치
- [ ] `local.properties`·`google-services.json` 커밋 정책 확인
- [ ] 딥링크 `intent-filter` 입력 검증

## 픽스처
`tests/fixtures/android/`: `debuggable`·`allowBackup`·`exported` 켠 Manifest, cleartext 허용 network_security_config, `minifyEnabled false`, WebView JS 인터페이스 코드

> [!warning] 검증 필요
> - `semgrep-rules`의 Kotlin 규칙 범위
> - OSV-Scanner의 `gradle.lockfile`·`verification-metadata.xml` 지원
> - MobSF의 AAB 직접 분석 지원 여부
