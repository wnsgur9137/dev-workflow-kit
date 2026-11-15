"""/security:scan-app 단위 테스트 — 산출물 검사(artifact.py), MobSF 리포트 해석·정제(mobsf_report.py·normalize.py),
API 클라이언트(mobsf_client.py, 가짜 HTTP 서버). Docker 가 필요한 종단 테스트는 test_scan_app.sh."""

import http.server
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PLUGIN, "scripts"))
sys.path.insert(0, os.path.join(PLUGIN, "scripts", "lib"))

import artifact  # noqa: E402
import mobsf_client  # noqa: E402
import mobsf_report  # noqa: E402
import normalize  # noqa: E402

FIX = os.path.join(HERE, "fixtures", "app")
# 커밋하지 않는 가짜 키 — 실행할 때 조립한다 (push protection·저장소 자체 점검에 걸리지 않게)
GOOGLE_KEY = "AI" + "za" + "SyB" + "9" * 8 + "fakeKeyForTests" + "x" * 9
AWS_KEY = "AK" + "IA" + "QZ7RT2XNVB4K8M3P"
API_KEY = "k" * 64


def load_fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        text = f.read().replace("@@GOOGLE_KEY@@", GOOGLE_KEY).replace("@@AWS_KEY@@", AWS_KEY)
    return json.loads(text)


def make_zip(path, names, data=b"x"):
    with zipfile.ZipFile(path, "w") as z:
        for n in names:
            z.writestr(n, data)


class ArtifactInspectTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d)

    def run_inspect(self, path, ext):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = artifact.inspect(path, ext)
        rows = [ln.split("\t", 1) for ln in out.getvalue().splitlines()]
        return rc, rows, err.getvalue()

    def test_android_flutter_react_native_detection(self):
        p = os.path.join(self.d, "a.apk")
        make_zip(p, ["AndroidManifest.xml", "classes.dex", "lib/arm64-v8a/libflutter.so"])
        rc, rows, _ = self.run_inspect(p, "apk")
        self.assertEqual(rc, 0)
        self.assertIn(["profile", "android"], rows)
        self.assertIn(["profile", "flutter"], rows)
        self.assertNotIn(["profile", "react-native"], rows)
        make_zip(p, ["AndroidManifest.xml", "assets/index.android.bundle"])
        _, rows, _ = self.run_inspect(p, "apk")
        self.assertIn(["profile", "react-native"], rows)

    def test_aab_and_ipa_layout(self):
        aab = os.path.join(self.d, "a.aab")
        make_zip(aab, ["base/manifest/AndroidManifest.xml", "base/lib/arm64-v8a/libflutter.so"])
        rc, rows, _ = self.run_inspect(aab, "aab")
        self.assertEqual(rc, 0)
        self.assertIn(["type", "aab"], rows)
        self.assertIn(["profile", "flutter"], rows)
        ipa = os.path.join(self.d, "a.ipa")
        make_zip(ipa, ["Payload/X.app/Info.plist", "Payload/X.app/X", "Payload/X.app/main.jsbundle",
                       "Payload/X.app/SC_Info/X.sinf"])
        rc, rows, _ = self.run_inspect(ipa, "ipa")
        self.assertEqual(rc, 0)
        self.assertIn(["profile", "ios"], rows)
        self.assertIn(["profile", "react-native"], rows)
        self.assertTrue(any(r[0] == "warning" and "FairPlay" in r[1] for r in rows))

    def test_rejects_non_zip_missing_manifest_and_symlink(self):
        p = os.path.join(self.d, "a.apk")
        with open(p, "wb") as f:
            f.write(b"not a zip file at all, just text padding")
        rc, _, err = self.run_inspect(p, "apk")
        self.assertEqual(rc, 1)
        self.assertIn("ZIP 시그니처", err)
        make_zip(p, ["classes.dex"])
        rc, _, err = self.run_inspect(p, "apk")
        self.assertEqual(rc, 1)
        self.assertIn("AndroidManifest.xml", err)
        ipa = os.path.join(self.d, "b.ipa")
        make_zip(ipa, ["Payload/X.app/X"])
        self.assertEqual(self.run_inspect(ipa, "ipa")[0], 1)
        link = os.path.join(self.d, "l.apk")
        make_zip(p, ["AndroidManifest.xml"])
        os.symlink(p, link)
        rc, _, err = self.run_inspect(link, "apk")
        self.assertEqual(rc, 1, "심볼릭 링크를 따라가면 안 된다")

    def test_size_and_entry_limits_and_duplicate_names(self):
        p = os.path.join(self.d, "a.apk")
        make_zip(p, ["AndroidManifest.xml", "a", "b"])
        old = artifact.MAX_BYTES, artifact.MAX_ENTRIES
        try:
            artifact.MAX_BYTES = 10
            rc, _, err = self.run_inspect(p, "apk")
            self.assertEqual(rc, 1)
            self.assertIn("너무 큽니다", err)
            artifact.MAX_BYTES, artifact.MAX_ENTRIES = old[0], 2
            rc, _, err = self.run_inspect(p, "apk")
            self.assertEqual(rc, 1)
            self.assertIn("항목이 너무 많습니다", err)
        finally:
            artifact.MAX_BYTES, artifact.MAX_ENTRIES = old
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("AndroidManifest.xml", b"a")
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                z.writestr("AndroidManifest.xml", b"b")
        rc, rows, _ = self.run_inspect(p, "apk")
        self.assertEqual(rc, 0)
        self.assertTrue(any(r[0] == "warning" and "같은 이름" in r[1] for r in rows))


class MobsfReportTest(unittest.TestCase):
    def parse(self, name, **kw):
        f, w = normalize.parse_mobsf(load_fixture(name), "android" if "android" in name else "ios", **kw)
        return {x["rule_id"]: x for x in f}, w

    def test_android_findings_and_source_rule_links(self):
        f, _ = self.parse("mobsf-android.json")
        for rule, sev in (("mobsf.manifest.app-is-debuggable", "high"), ("mobsf.manifest.app-allowbackup", "medium"),
                          ("mobsf.manifest.clear-text-traffic", "high"), ("mobsf.network.cleartext", "high"),
                          ("mobsf.network.user-certs", "high"), ("mobsf.code.android-md5", "medium"),
                          ("mobsf.secret.hardcoded", "high")):
            self.assertIn(rule, f)
            self.assertEqual(f[rule]["severity"], sev, rule)
        self.assertIn("scan-code: android.manifest-debuggable", f["mobsf.manifest.app-is-debuggable"]["references"])
        self.assertIn("scan-code: android.nsc-user-certs", f["mobsf.network.user-certs"]["references"])
        self.assertEqual(f["mobsf.code.android-md5"]["location"]["line"], 12)
        self.assertEqual(f["mobsf.code.android-md5"]["location"]["file"], "com/example/vulnapp/MainActivity.java")

    def test_secret_values_never_reach_findings(self):
        f, _ = self.parse("mobsf-android.json")
        dump = json.dumps(list(f.values()), ensure_ascii=False)
        self.assertNotIn(GOOGLE_KEY, dump)
        self.assertNotIn(AWS_KEY, dump)
        s = f["mobsf.secret.hardcoded"]
        self.assertEqual(s["location"]["package"], "google_api_key")
        self.assertEqual(s["category"], "secret")
        self.assertEqual(s["evidence"], normalize.SECRET_EVIDENCE)

    def test_ios_findings_platform_and_info_protections_dropped(self):
        rep = load_fixture("mobsf-ios.json")
        self.assertEqual(mobsf_report.platform_of(rep), "ios", "iOS app_type 은 언어 이름이다")
        f, _ = self.parse("mobsf-ios.json")
        ats = [r for r in f if r.startswith("mobsf.ats.")]
        self.assertEqual(len(ats), 1)
        self.assertEqual(f[ats[0]]["severity"], "high")
        self.assertIn("scan-code: ios.ats-*", f[ats[0]]["references"])
        self.assertIn("mobsf.macho.stack-canary", f)
        # 보호 기법이 켜진 정상 상태(info)는 결과가 아니다, 암호화되지 않은 직접 빌드 IPA 는 정상
        self.assertNotIn("mobsf.macho.pie", f)
        self.assertNotIn("mobsf.macho.nx", f)
        self.assertEqual(f.get("mobsf.macho.encrypted", {}).get("severity", "info"), "info")

    def test_converted_aab_drops_signature_results(self):
        rep = load_fixture("mobsf-android.json")
        rep["certificate_analysis"]["certificate_findings"] = [["high", "unsigned", "Missing Code Signing certificate"]]
        f, w = normalize.parse_mobsf(rep, "android", converted_aab=True)
        self.assertFalse([x for x in f if x["rule_id"].startswith("mobsf.cert.")])
        self.assertTrue(any("AAB 의 서명은 점검하지 않았습니다" in x for x in w))
        f, _ = normalize.parse_mobsf(rep, "android", converted_aab=False)
        self.assertTrue([x for x in f if x["rule_id"].startswith("mobsf.cert.")])

    def test_debug_signed_build_is_marked(self):
        rep = load_fixture("mobsf-android.json")
        rep["certificate_analysis"]["certificate_info"] = "X.509 Subject: C=US, O=Android, CN=Android Debug"
        f, _ = normalize.parse_mobsf(rep, "android")
        dbg = next(x for x in f if x["rule_id"] == "mobsf.manifest.app-is-debuggable")
        self.assertIn("디버그 키로 서명된 빌드", dbg["fix_hint"])
        self.assertTrue(any("디버그 키" in w for w in normalize.app_warnings(rep, ["android"])))

    def test_sanitize_drops_secrets_and_string_dumps(self):
        rep = load_fixture("mobsf-android.json")
        rep["urls"] = [{"urls": ["https://user:hunter2pass@api.example.com/x"], "path": "a"}]
        out = mobsf_report.sanitize(rep, lambda t: normalize.clean_text(t, 4000))
        dump = json.dumps(out, ensure_ascii=False)
        self.assertNotIn(GOOGLE_KEY, dump)
        self.assertNotIn(AWS_KEY, dump)
        self.assertNotIn("hunter2pass", dump)
        self.assertEqual(out["secrets"]["count"], 1)
        self.assertIn("manifest_analysis", out)

    def test_unexpected_shapes_do_not_crash(self):
        weird = {"app_type": "apk", "package_name": "x", "manifest_analysis": {"manifest_findings": ["str", 3, None]},
                 "network_security": {"network_findings": [{"scope": None, "description": None}]},
                 "code_analysis": {"findings": {"k": "notadict", "k2": {"files": {}, "metadata": {}}}},
                 "binary_analysis": [None, {"name": 3, "nx": {"severity": "high"}}], "secrets": [None, 5, "no colon"],
                 "permissions": {"p": "x"}, "file_analysis": [None, {"finding": "Hardcoded Keystore", "files": [None]}]}
        f, _ = normalize.parse_mobsf(weird, "android")
        self.assertTrue(f)
        with self.assertRaises(ValueError):
            mobsf_report.parse([], normalize.clean_text, normalize.clean_ident, 160, 200, "x", "android")


class NormalizeAppTest(unittest.TestCase):
    def setUp(self):
        self.run = tempfile.mkdtemp()
        os.mkdir(os.path.join(self.run, "raw"))

    def tearDown(self):
        shutil.rmtree(self.run)

    def write(self, name, text):
        with open(os.path.join(self.run, "raw", name), "w", encoding="utf-8") as f:
            f.write(text)

    def test_app_run_writes_sanitized_raw_checklist_and_warnings(self):
        self.write("mobsf-full.json", json.dumps(load_fixture("mobsf-android.json")))
        self.write("status.tsv", "mobsf\tok\t0\t\n")      # gitleaks-artifact 행 누락 → 실패로 드러나야 한다
        self.write("gitleaks-artifact.json", json.dumps([{"RuleID": "generic-api-key", "Description": "key",
                                                          "File": "/in/artifact.zip!assets/index.android.bundle",
                                                          "StartLine": 3, "Match": "key=REDACTED"}]))
        self.write("profiles.tsv", "android\t.\t\nreact-native\t.\t\n")
        rc = normalize.main(["--run-dir", self.run, "--kind", "app", "--target", "/x/app-release.apk",
                             "--profiles-tsv", os.path.join(self.run, "raw", "profiles.tsv")])
        self.assertEqual(rc, 0)
        raw = os.path.join(self.run, "raw")
        self.assertFalse(os.path.exists(os.path.join(raw, "mobsf-full.json")), "원본(시크릿 포함)은 지워야 한다")
        self.assertTrue(os.path.exists(os.path.join(raw, "mobsf.json")))
        for root, _dirs, files in os.walk(self.run):
            for fn in files:
                with open(os.path.join(root, fn), encoding="utf-8", errors="replace") as f:
                    body = f.read()
                self.assertNotIn(GOOGLE_KEY, body, fn)
                self.assertNotIn(AWS_KEY, body, fn)
        # normalize 가 쓰는 파일은 모두 600 (입력 파일은 테스트가 만든 것이라 보지 않는다)
        for rel in ("findings.json", "summary.md", "meta.json", "raw/mobsf.json"):
            self.assertEqual(os.stat(os.path.join(self.run, rel)).st_mode & 0o777, 0o600, rel)
        with open(os.path.join(self.run, "findings.json"), encoding="utf-8") as f:
            report = json.load(f)
        gl = [x for x in report["findings"] if x["tool"] == "gitleaks"]
        self.assertEqual(gl[0]["location"]["file"], "assets/index.android.bundle")
        self.assertIn("앱 산출물 내부", gl[0]["evidence"])
        with open(os.path.join(self.run, "summary.md"), encoding="utf-8") as f:
            summary = f.read()
        self.assertIn("# 보안 점검 요약 — app", summary)
        self.assertIn("## 수동 확인 (스택별 체크리스트)", summary)
        self.assertIn("Play App Signing", summary)
        self.assertIn("OTA 업데이트", summary)
        self.assertIn("React Native: JS 번들", summary)
        self.assertIn("| gitleaks-artifact | failed |", summary)
        # 앱 이름의 인젝션 문구는 summary 에 코드 블록 밖으로 나오지 않는다
        inside = False
        for ln in summary.splitlines():
            if ln.startswith("````"):
                inside = not inside
            elif "IGNORE ALL PREVIOUS INSTRUCTIONS" in ln:
                self.assertTrue(inside, ln)

    def test_broken_mobsf_json_is_a_parse_error_not_silence(self):
        self.write("mobsf-full.json", "{not json")
        self.write("status.tsv", "mobsf\tok\t0\t\ngitleaks-artifact\tok\t0\t\n")
        self.write("gitleaks-artifact.json", "[]")
        rc = normalize.main(["--run-dir", self.run, "--kind", "app", "--target", "/x/a.ipa"])
        self.assertEqual(rc, 0)
        with open(os.path.join(self.run, "summary.md"), encoding="utf-8") as f:
            summary = f.read()
        self.assertIn("mobsf.json 파싱 실패", summary)
        self.assertFalse(os.path.exists(os.path.join(self.run, "raw", "mobsf-full.json")))


class FakeMobsf(http.server.BaseHTTPRequestHandler):
    """report_json·upload·scan·delete_scan 만 흉내 낸다. 동작은 클래스 속성으로 바꾼다."""
    calls = []
    scan_status = 200
    report_body = None

    def log_message(self, *a):
        pass

    def _send(self, status, obj):
        body = json.dumps(obj).encode() if not isinstance(obj, bytes) else obj
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n)
        FakeMobsf.calls.append((self.path, body[:200]))
        if self.headers.get("X-Mobsf-Api-Key") != API_KEY:
            return self._send(401, {"error": "unauthorized"})
        if self.path == "/api/v1/upload":
            if b'filename="app.apk"' not in body:
                return self._send(400, {"error": "bad file"})
            return self._send(200, {"hash": "a" * 32, "scan_type": "apk"})
        if self.path == "/api/v1/scan":
            return self._send(FakeMobsf.scan_status, {"app_type": "apk"} if FakeMobsf.scan_status == 200 else {"error": "x"})
        if self.path == "/api/v1/report_json":
            if b"hash=" + b"0" * 32 in body:
                return self._send(404, {"report": "Report not Found"})
            return self._send(200, FakeMobsf.report_body if FakeMobsf.report_body is not None else {"app_type": "apk", "x": 1})
        if self.path == "/api/v1/delete_scan":
            return self._send(200, {"deleted": "yes"})
        return self._send(404, {})


class MobsfClientTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeMobsf)
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        FakeMobsf.calls = []
        FakeMobsf.scan_status = 200
        FakeMobsf.report_body = None
        self.d = tempfile.mkdtemp()
        self.apk = os.path.join(self.d, "app.apk")
        make_zip(self.apk, ["AndroidManifest.xml"])
        os.environ["DWK_MOBSF_API_KEY"] = API_KEY

    def tearDown(self):
        shutil.rmtree(self.d)
        os.environ.pop("DWK_MOBSF_API_KEY", None)

    def client(self):
        out = io.BytesIO()

        class W:
            buffer = out

            @staticmethod
            def flush():
                pass

        err = io.StringIO()
        old = sys.stdout
        sys.stdout = W
        try:
            with redirect_stderr(err):
                rc = mobsf_client.main(["--url", self.url, "--file", self.apk, "--ready-timeout", "5"])
        finally:
            sys.stdout = old
        return rc, out.getvalue(), err.getvalue()

    def paths(self):
        return [p for p, _ in FakeMobsf.calls]

    def test_success_flow_outputs_report_and_deletes_scan(self):
        rc, out, _ = self.client()
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["app_type"], "apk")
        self.assertEqual(self.paths()[-1], "/api/v1/delete_scan")
        self.assertIn("/api/v1/scan", self.paths())

    def test_scan_failure_still_deletes_and_returns_error(self):
        FakeMobsf.scan_status = 500
        rc, out, err = self.client()
        self.assertEqual(rc, 5)
        self.assertEqual(out, b"")
        self.assertIn("스캔 실패 HTTP 500", err)
        self.assertEqual(self.paths()[-1], "/api/v1/delete_scan")

    def test_report_without_app_type_is_failure(self):
        FakeMobsf.report_body = {"error": "Invalid AAB File"}
        rc, out, _ = self.client()
        self.assertEqual(rc, 6)
        self.assertEqual(out, b"")

    def test_wrong_key_and_short_key(self):
        os.environ["DWK_MOBSF_API_KEY"] = "x" * 64
        rc, _, err = self.client()
        self.assertEqual(rc, 2)
        self.assertIn("401", err)
        os.environ["DWK_MOBSF_API_KEY"] = "short"
        rc, _, _ = self.client()
        self.assertEqual(rc, 2)
        self.assertNotIn("/api/v1/upload", self.paths())


if __name__ == "__main__":
    unittest.main()
