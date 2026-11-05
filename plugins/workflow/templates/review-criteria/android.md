# Android Review Priorities

| Priority | Category | Description |
|----------|----------|-------------|
| 1 | **Lifecycle Safety** | Activity/Fragment lifecycle awareness, `ViewModel` scoping, `LiveData`/`StateFlow` usage |
| 2 | **Memory Leaks** | Context leaks, inner class references, `ViewBinding` cleanup in Fragments |
| 3 | **Thread Safety** | Coroutine scope management, `Dispatchers` usage, `withContext` for IO operations |
| 4 | **Crash Prevention** | Null safety, `!!` operator usage, unchecked casts, exception handling |
| 5 | **Architecture** | MVVM/MVI compliance, Repository pattern, Use Case layer, DI (Hilt/Dagger) |
| 6 | **Performance** | RecyclerView `DiffUtil`, image loading (Glide/Coil), lazy initialization |
| 7 | **Security** | ProGuard rules, API key exposure, `SharedPreferences` vs `EncryptedSharedPreferences` |
| 8 | **UI/UX** | Compose recomposition, XML layout optimization, Material Design compliance |
| 9 | **Testing** | Unit tests, `Turbine` for Flow testing, `MockK`/`Mockito` usage |
| 10 | **Kotlin Conventions** | Kotlin idioms, extension functions, sealed classes, data classes |

## Android-Specific Checks

- Jetpack Compose `remember`, `derivedStateOf` correctness
- `LaunchedEffect` key management
- Navigation component safe args
- Room database migration handling
- WorkManager constraints and retry policies

## Android Security Checklist

- `EncryptedSharedPreferences` 사용 여부 (민감 데이터 저장 시)
- R8/ProGuard 난독화 규칙 누락 확인
- `android:exported` 속성 명시 확인 (Android 12+ 필수)
- 하드코딩된 시크릿/API 키 탐지 (`BuildConfig` 또는 환경변수 사용 여부)
- WebView `@JavascriptInterface` 보안 (노출 범위 최소화)
- `android:debuggable=true` 잔재 확인
- Network Security Config (`res/xml/network_security_config.xml`) cleartext 허용 여부
- Content Provider 접근 제어 (`android:permission`)
