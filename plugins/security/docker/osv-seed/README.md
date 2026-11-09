# OSV 오프라인 DB 씨앗 (seed)

`update.sh` 가 OSV-Scanner 의 `--download-offline-databases` 로 생태계별 DB 를 받을 때 쓰는 최소 lockfile 들입니다.
OSV-Scanner 는 **스캔한 lockfile 의 생태계 DB 만** 받으므로, 지원 스택의 생태계마다 하나씩 둡니다.

| 파일 (`.seed` 를 떼고 복사) | 생태계 | 스택 |
|---|---|---|
| `package-lock.json.seed` | npm | web, react-native, server(Node) |
| `requirements.txt.seed` | PyPI | server(Python) |
| `go.mod.seed` | Go | server(Go) |
| `gradle.lockfile.seed` | Maven | android, server(JVM) |
| `pubspec.lock.seed` | Pub | flutter |
| `Package.resolved.seed` | SwiftURL | ios |

- 저장소의 의존성 알림(Dependabot 등)이 씨앗을 실제 의존성으로 오인하지 않도록 `.seed` 확장자로 둡니다.
- CocoaPods(`Podfile.lock`)는 OSV-Scanner v2.7.0 이 추출하지 않습니다 (P1 실측).
