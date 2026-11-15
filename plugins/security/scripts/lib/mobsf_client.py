#!/usr/bin/env python3
"""MobSF REST API 클라이언트 — mobsf-client 컨테이너(scan-internal 네트워크) 안에서 실행한다.

업로드 → 스캔 → JSON 리포트 → 내부 저장본 삭제를 차례로 하고, 리포트 JSON 을 stdout 으로 내보낸다.
호스트로 쓰는 마운트가 없으므로 결과 파일은 호스트(scan-app.sh)가 umask 077 로 만든다.

사용: mobsf_client.py --url http://mobsf:8000 --file /in/app.apk [--convert-aab]
  API 키는 환경변수 DWK_MOBSF_API_KEY 로 받는다 (명령줄에 두면 ps 로 보인다).

종료코드: 0 성공 · 2 인자·키 오류 · 3 서버 준비 안 됨 · 4 업로드(AAB 변환 포함) 실패 · 5 스캔 실패 · 6 리포트 실패
표준 라이브러리만 사용한다 (호스트 단위 테스트에서 가짜 서버로 검증).
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

REPORT_MAX = 256 * 1024 * 1024   # 리포트 응답 상한 — 이보다 크면 실패로 본다 (메모리 보호)
SMALL_MAX = 1024 * 1024          # 업로드·삭제 응답 상한
# MobSF 이미지 안의 bundletool (v4.6.4: bundletool-all-1.17.2.jar)
BUNDLETOOL_GLOB = "/home/mobsf/Mobile-Security-Framework-MobSF/mobsf/StaticAnalyzer/tools/bundletool-all-*.jar"


class ClientError(Exception):
    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code = code


def _read_limited(resp, limit: int) -> bytes:
    data = resp.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"응답이 상한({limit} 바이트)을 넘습니다")
    return data


def _request(url: str, key: str, data: bytes | None, headers: dict, timeout: float, limit: int):
    req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET")
    req.add_header("X-Mobsf-Api-Key", key)
    for k, v in headers.items():
        req.add_header(k, v)
    # 프록시 환경변수를 무시한다 — 내부 네트워크의 mobsf 로만 간다
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.status, _read_limited(resp, limit)
    except urllib.error.HTTPError as e:
        try:
            body = _read_limited(e, SMALL_MAX)
        except Exception:  # noqa: BLE001
            body = b""
        finally:
            e.close()
        return e.code, body


def _form(url: str, key: str, fields: dict, timeout: float, limit: int):
    body = urllib.parse.urlencode(fields).encode()
    return _request(url, key, body, {"Content-Type": "application/x-www-form-urlencoded"}, timeout, limit)


def _short(body: bytes) -> str:
    return body[:300].decode("utf-8", "replace").replace("\n", " ")


def wait_ready(base: str, key: str, timeout: float) -> None:
    """API 가 키를 받아들일 때까지 기다린다 (compose --wait 의 헬스체크는 웹 로그인 페이지만 본다)."""
    deadline = time.monotonic() + timeout
    last = ""
    while True:
        try:
            # 빈 hash 로 report_json 을 부르면 준비된 서버는 4xx(JSON)를, 키가 틀리면 401 을 준다
            status, body = _form(f"{base}/api/v1/report_json", key, {"hash": "0" * 32}, 10, SMALL_MAX)
            if status == 401:
                raise ClientError(2, "API 키가 거부됐습니다 (401)")
            if status < 500:
                return
            last = f"HTTP {status}"
        except ClientError:
            raise
        except Exception as e:  # noqa: BLE001 — 기동 중에는 연결 거부가 정상이다
            last = type(e).__name__
        if time.monotonic() > deadline:
            raise ClientError(3, f"MobSF API 가 {int(timeout)}초 안에 준비되지 않았습니다 ({last})")
        time.sleep(2)


def upload(base: str, key: str, path: str, timeout: float) -> str:
    name = os.path.basename(path)
    boundary = "dwk" + uuid.uuid4().hex
    with open(path, "rb") as f:
        content = f.read()
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
            "Content-Type: application/octet-stream\r\n\r\n").encode()
    body = head + content + f"\r\n--{boundary}--\r\n".encode()
    status, resp = _request(f"{base}/api/v1/upload", key, body,
                            {"Content-Type": f"multipart/form-data; boundary={boundary}"}, timeout, SMALL_MAX)
    if status != 200:
        raise ClientError(4, f"업로드 실패 HTTP {status}: {_short(resp)}")
    try:
        h = json.loads(resp)["hash"]
    except Exception:  # noqa: BLE001
        raise ClientError(4, f"업로드 응답에 hash 가 없습니다: {_short(resp)}")
    if not (isinstance(h, str) and len(h) == 32 and all(c in "0123456789abcdef" for c in h)):
        raise ClientError(4, "업로드 응답의 hash 형식이 다릅니다")
    return h


def convert_aab(aab: str, bundletool: str, aapt2: str, workdir: str) -> str:
    """AAB → universal APK. MobSF v4.6.4 는 bundletool 내장 aapt2(x86-64)로 변환해 arm64 이미지에서 늘 실패한다
    (실측) — 이미지에 있는 aapt2 를 지정해 여기서 미리 바꾼다. 컨테이너의 tmpfs 안에서만 쓴다."""
    import subprocess
    import zipfile

    os.makedirs(workdir, exist_ok=True)
    apks = os.path.join(workdir, "app.apks")
    out = os.path.join(workdir, "app.apk")
    cmd = ["java", "-jar", bundletool, "build-apks", f"--bundle={aab}", f"--output={apks}",
           "--mode=universal", f"--aapt2={aapt2}"]
    try:
        r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=900)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ClientError(4, f"AAB 변환 실행 실패: {type(e).__name__}")
    if r.returncode != 0 or not os.path.isfile(apks):
        tail = r.stderr.decode("utf-8", "replace").strip().splitlines()[-2:]
        raise ClientError(4, "AAB 를 APK 로 변환하지 못했습니다 (bundletool): " + " / ".join(t[:150] for t in tail))
    with zipfile.ZipFile(apks) as z:
        try:
            info = z.getinfo("universal.apk")
        except KeyError:
            raise ClientError(4, "bundletool 결과에 universal.apk 가 없습니다")
        with z.open(info) as src, open(out, "wb") as dst:
            while True:
                chunk = src.read(1 << 20)
                if not chunk:
                    break
                dst.write(chunk)
    os.unlink(apks)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="mobsf_client.py")
    ap.add_argument("--url", required=True)
    ap.add_argument("--file", required=True)
    ap.add_argument("--ready-timeout", type=float, default=180)
    ap.add_argument("--scan-timeout", type=float, default=3600)
    ap.add_argument("--convert-aab", action="store_true", help="AAB 를 universal APK 로 바꿔 올린다")
    ap.add_argument("--bundletool", default="")
    ap.add_argument("--aapt2", default="/usr/bin/aapt2")
    ap.add_argument("--workdir", default="/tmp/dwk-aab")
    args = ap.parse_args(argv)
    key = os.environ.get("DWK_MOBSF_API_KEY", "")
    if len(key) < 32:
        print("mobsf_client: DWK_MOBSF_API_KEY 가 없거나 짧습니다", file=sys.stderr)
        return 2
    base = args.url.rstrip("/")
    h = None
    try:
        path = args.file
        if args.convert_aab:
            bundletool = args.bundletool or next(iter(sorted(glob.glob(BUNDLETOOL_GLOB))), "")
            if not bundletool:
                raise ClientError(4, f"bundletool 을 찾지 못했습니다: {BUNDLETOOL_GLOB}")
            print("mobsf_client: AAB 를 universal APK 로 변환 중 (bundletool)", file=sys.stderr)
            path = convert_aab(args.file, bundletool, args.aapt2, args.workdir)
        wait_ready(base, key, args.ready_timeout)
        h = upload(base, key, path, 600)
        print(f"mobsf_client: 업로드 완료 ({h[:8]}…), 정적 분석 중", file=sys.stderr)
        status, resp = _form(f"{base}/api/v1/scan", key, {"hash": h}, args.scan_timeout, REPORT_MAX)
        if status != 200:
            raise ClientError(5, f"스캔 실패 HTTP {status}: {_short(resp)}")
        status, resp = _form(f"{base}/api/v1/report_json", key, {"hash": h}, 600, REPORT_MAX)
        if status != 200:
            raise ClientError(6, f"리포트 실패 HTTP {status}: {_short(resp)}")
        try:
            report = json.loads(resp)
        except ValueError:
            raise ClientError(6, "리포트가 JSON 이 아닙니다")
        if not isinstance(report, dict) or "app_type" not in report:
            raise ClientError(6, f"리포트에 app_type 이 없습니다 (분석 오류일 수 있음): {_short(resp)}")
        sys.stdout.buffer.write(resp)
        sys.stdout.flush()
        return 0
    except ClientError as e:
        print(f"mobsf_client: {e}", file=sys.stderr)
        return e.code
    except Exception as e:  # noqa: BLE001
        print(f"mobsf_client: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
        return 5
    finally:
        # MobSF 내부 저장본(업로드 파일·디컴파일 결과·DB 기록)을 지운다. 볼륨도 실행마다 지우지만 이중으로.
        if h:
            try:
                status, _ = _form(f"{base}/api/v1/delete_scan", key, {"hash": h}, 60, SMALL_MAX)
                if status != 200:
                    print(f"mobsf_client: delete_scan HTTP {status}", file=sys.stderr)
            except Exception as e:  # noqa: BLE001
                print(f"mobsf_client: delete_scan 실패 {type(e).__name__}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
