---
title: Docker 런타임
tags: [overview, requirements, docker]
status: draft
created: 2026-11-05
---

# Docker 런타임

상위: [[보안 툴킷]] · 결정: [[ADR-009 Docker 호환 런타임 필수]] · 관련: [[네트워크 격리]]

> [!important] security 플러그인은 Docker 호환 런타임이 **필수**다
> 6개 도구를 모두 컨테이너로 실행한다. Docker가 없거나 꺼져 있으면 `/security:scan-*`는 실행되지 않고 설치 안내를 보여 준다.

## 왜 Docker인가
| 이유 | 내용 |
|---|---|
| 외부 전송 차단 보장 | `--network none` / `internal` 네트워크로 도구가 통신을 시도해도 나가지 못함 → [[ADR-004 네트워크 격리 강제]] |
| 실행 자체에 필요 | [[MobSF]]는 Docker가 사실상 유일한 설치 방법, [[OWASP ZAP]] baseline 스크립트도 이미지 기준 |
| 버전 고정 | 이미지 digest로 고정 → 침해된 새 버전이 몰래 들어오지 않음 ([[업데이트 절차]]) |
| 호스트 무설치 | 도구·의존성이 컨테이너 안에만 있음 |

Docker 없이 도구를 직접 설치하는 "가벼운 모드"는 두지 않는다. 외부 전송 차단을 보장할 수 없기 때문이다.

## 런타임 선택 (macOS)

| 런타임 | 비용·라이선스 | 지원 | 비고 |
|---|---|---|---|
| **Colima** | 무료 (MIT) | ✅ **권장 기본값** | Lima VM 기반 dockerd. Homebrew로 설치 |
| Docker Desktop | 개인·교육·비상업 오픈소스·소규모 사업(직원 250명 미만 **그리고** 연 매출 1천만 달러 미만)은 무료, **그 외 업무 사용은 유료 구독** | ✅ | 회사 장비에서 쓰면 조건 확인 필요 |
| Rancher Desktop (dockerd 모드) | 무료 (Apache-2.0) | ✅ | 컨테이너 엔진을 `dockerd (moby)`로 설정해야 함 |
| OrbStack | 개인 무료, 상업 사용 유료 | ✅ | |
| Podman | 무료 (Apache-2.0) | ❌ 미지원 | `compose`·`internal` 네트워크 동작 차이 검증 전 |

- 조건은 **Docker CLI + Compose v2 이상 + dockerd(moby) 엔진**이다. 위 지원 런타임은 모두 이 조건을 충족한다.
- 여러 런타임이 설치돼 있으면 `docker context ls`에서 `*` 표시된 컨텍스트를 쓴다. 스캔 스크립트는 현재 컨텍스트를 `meta.json`에 기록한다.

## Colima 설치 (권장)
```bash
brew install colima docker docker-compose
colima start --cpu 4 --memory 8 --disk 60
docker context use colima
docker info && docker compose version   # 둘 다 성공해야 함
```
- `docker-compose`를 Homebrew로 설치하면 `docker compose` 플러그인으로 쓰려면 `~/.docker/config.json`에 `"cliPluginsExtraDirs": ["/opt/homebrew/lib/docker/cli-plugins"]`(Intel Mac은 `/usr/local/lib/docker/cli-plugins`)가 필요할 수 있다.
- 재부팅 후에는 `colima start`를 다시 실행한다 (자동 시작: `brew services start colima`).

## 권장 리소스
| 사용 범위 | VM 메모리 | 디스크 여유 | 비고 |
|---|---|---|---|
| `/security:scan-code`만 | 4GB | 10GB | Semgrep·Gitleaks·OSV 이미지와 규칙·DB |
| + `/security:scan-web` | 6GB | 15GB | ZAP 이미지 |
| + `/security:scan-app` | **8GB** | 25GB | MobSF 이미지(수 GB), 분석 중 메모리 사용 큼 |

이미지 크기는 버전마다 다르다. `update.sh`가 받기 전에 예상 용량을 보여 준다.

## Apple Silicon (arm64)
- 이미지가 arm64를 지원하지 않으면 amd64 에뮬레이션으로 느리게 동작한다. `images.lock`에 이미지별 지원 아키텍처를 기록하고, 에뮬레이션이 필요하면 `update.sh`가 경고한다.
- Colima에서 amd64 에뮬레이션이 필요하면 `colima start --vm-type vz --vz-rosetta`.

## 사전 점검 (스캔 스크립트 공통, P0)
`scripts/lib/common.sh`의 `preflight`가 매 스캔 전에 확인한다. 하나라도 실패하면 **컨테이너를 띄우지 않고** 원인과 해결 방법을 출력한 뒤 종료한다.

| # | 확인 | 실패 시 안내 |
|---|---|---|
| D1 | `docker` CLI 존재 | 런타임 설치 안내 (이 노트의 Colima 설치) |
| D2 | `docker info` 성공 (엔진 실행 중) | `colima start` 또는 Docker Desktop 실행 |
| D3 | `docker compose version` v2 이상 | compose 플러그인 설치 안내 |
| D4 | 엔진이 dockerd(moby) | Podman 등 미지원 런타임 안내 |
| D5 | VM 메모리가 해당 스캔 권장치 이상 | 경고만 (계속 진행) |
| D6 | 필요한 이미지가 `images.lock` digest로 존재 | `update.sh` 실행 안내 (스캔 스크립트는 다운로드하지 않음) |

## 로컬 서버 점검 시 호스트 주소
`/security:scan-web`으로 내 Mac에서 띄운 서버(`localhost:3000`)를 점검할 때 컨테이너에서 보는 호스트 주소가 런타임마다 다를 수 있다.

| 런타임 | 호스트 주소 |
|---|---|
| Docker Desktop, OrbStack | `host.docker.internal` |
| Colima | `host.lima.internal` (버전에 따라 `host.docker.internal`도 동작) |

허용목록에는 실제로 쓰는 주소를 **포트까지** 적는다 → [[scan-web]]

> [!check] 확인됨 (P0, Colima 0.x · Docker 29 · Compose v5)
> - 엔진 판별: `docker version --format '{{range .Server.Components}}{{.Name}} {{end}}'` → `Engine containerd runc docker-init` (Podman은 `Podman Engine`)
> - VM 메모리: `docker info --format '{{.MemTotal}}'` (바이트, 설정값보다 약간 작게 보고됨 → 90% 기준)
> - Compose 버전은 v5까지 올라와 있으므로 "v2 이상"으로 판정
> - `~/.docker/config.json`에 `"credsStore": "desktop"`이 남아 있으면(Docker Desktop을 지운 뒤 Colima 사용) `docker pull`이 `docker-credential-desktop` 없음으로 실패한다 → 해당 줄 삭제 안내 (`update.sh`에서 감지)

> [!warning] 검증 필요
> - Colima에서 `host.docker.internal` 지원 여부(버전별)와 `internal: true` 네트워크 동작
> - MobSF·ZAP·Semgrep·Gitleaks·OSV-Scanner 공식 이미지의 arm64 지원 여부
> - 각 이미지의 실제 크기 (리소스 표 갱신)
