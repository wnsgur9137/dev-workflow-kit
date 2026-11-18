"""베이스라인 비교 (P4) — 같은 종류·대상의 직전 실행과 비교해 신규·유지·해결, 실패한 도구는 비교하지 않는다."""

import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
sys.path.insert(0, os.path.join(HERE, "..", "scripts", "lib"))

import normalize  # noqa: E402

CODE_TOOLS = ("semgrep", "gitleaks-git", "gitleaks-dir", "osv-scanner", "checks")


def _w(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(obj if isinstance(obj, str) else json.dumps(obj))


def _read(path, as_json=True):
    with open(path, encoding="utf-8") as f:
        return json.load(f) if as_json else f.read()


def sg(line, check="rules.python.lang.security.audit.x.os-system", path="/src/src/app.py"):
    """같은 규칙·파일에서 줄만 다르면 '위치 이동'으로 짝지어진다 — 진짜 신규·해결은 규칙을 다르게 준다."""
    return {"check_id": check, "path": path, "start": {"line": line}, "end": {"line": line},
            "extra": {"severity": "ERROR", "message": "dangerous", "lines": "x", "metadata": {}}}


class BaselineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.reports = os.path.join(self.tmp.name, "reports")
        self.target = os.path.join(self.tmp.name, "target")
        _w(os.path.join(self.target, "src", "app.py"), "\n".join(f"os.system(c{i})" for i in range(20)) + "\n")

    def scan_profiles(self, run_id, profiles, semgrep, **k):
        self._profiles = profiles
        try:
            return self.scan(run_id, semgrep, **k)
        finally:
            self._profiles = ""

    _profiles = ""

    def scan(self, run_id, semgrep, status=None, target=None, checks=True, semgrep_errors=None, meta_in=None, checks_data=None):
        run = os.path.join(self.reports, run_id)
        st = dict.fromkeys(CODE_TOOLS, "ok")
        st.update(status or {})
        _w(os.path.join(run, "raw", "status.tsv"), "".join(f"{t}\t{s}\t0\t\n" for t, s in st.items()))
        _w(os.path.join(run, "raw", "semgrep.json"),
           {"results": semgrep, "errors": semgrep_errors or []} if st["semgrep"] == "ok" else "")
        _w(os.path.join(run, "raw", "gitleaks-git.json"), [])
        _w(os.path.join(run, "raw", "gitleaks-dir.json"), [])
        _w(os.path.join(run, "raw", "osv.json"), {"results": []})
        _w(os.path.join(run, "raw", "checks.json"),
           (checks_data or {"results": [], "errors": [], "warnings": []}) if checks else "")
        _w(os.path.join(run, "raw", "profiles.tsv"), self._profiles)
        _w(os.path.join(run, "raw", "meta-in.json"), dict({"osv_db_updated_at": "2099-01-01T00:00:00Z", "plugin_version": "0.11.0",
           "tools": [{"name": "semgrep", "digest": "sha256:a"}], "rules": [{"name": "semgrep-rules", "commit": "c1"}]},
           **(meta_in or {})))
        rc = normalize.main(["--run-dir", run, "--kind", "code", "--target", target or self.target,
                             "--profiles-tsv", os.path.join(run, "raw", "profiles.tsv"),
                             "--meta-json", os.path.join(run, "raw", "meta-in.json")])
        self.assertEqual(rc, 0)
        return (_read(os.path.join(run, "findings.json"))["findings"], _read(os.path.join(run, "meta.json")),
                _read(os.path.join(run, "summary.md"), False))

    def test_new_existing_resolved_against_previous_run_of_same_target(self):
        A, B, C = "r.a", "r.b", "r.c"
        f1, m1, s1 = self.scan("20261101-100000-code", [sg(1, A), sg(2, B)])
        self.assertEqual(m1["baseline"]["run_id"], None)
        self.assertIn("비교하지 않았습니다", s1)
        self.assertEqual({f["baseline"] for f in f1}, {"not-compared"})
        self.assertIn("semgrep", m1["complete_units"])
        f2, m2, s2 = self.scan("20261102-100000-code", [sg(2, B), sg(3, C)])
        b = m2["baseline"]
        self.assertEqual((b["run_id"], b["new"], b["existing"], b["resolved"]), ("20261101-100000-code", 1, 1, 1))
        self.assertEqual(sorted((f["location"]["line"], f["baseline"]) for f in f2), [(2, "existing"), (3, "new")])
        self.assertEqual(b["resolved_items"][0]["location"]["line"], "1")
        self.assertIn("**신규 1** · 유지 1 · **해결 1**", s2)
        self.assertIn("[high] [신규] semgrep", s2)
        self.assertIn("`src/app.py:1`", s2)

    def test_line_moves_are_paired_not_new_and_resolved(self):
        # 리뷰 W2: 위에 줄이 추가돼 같은 결과의 줄 번호만 바뀌면 id 가 달라진다 — 신규+해결이 아니라 위치 이동
        self.scan("20261101-100000-code", [sg(1), sg(5), sg(9, "r.other")])
        f, m, s = self.scan("20261102-100000-code", [sg(2), sg(6), sg(7)])
        b = m["baseline"]
        self.assertEqual((b["new"], b["moved"], b["resolved"]), (1, 2, 1))    # 같은 규칙에 하나가 더 늘었고 r.other 는 해결
        self.assertEqual(b["resolved_items"][0]["rule_id"], "r.other")
        self.assertIn("유지 2 (위치 이동 2)", s)
        self.assertIn("고쳤다고 단정하기 전에", s)

    def test_partial_results_are_not_complete(self):
        # 리뷰 W1: checks 시간 초과·결과 상한, 경로를 모르는 semgrep 부분 오류는 단위 전체를 '해결'로 보지 않는다
        self.scan("20261101-100000-code", [sg(1, "r.a"), sg(2, "r.b")])
        _, m, s = self.scan("20261102-100000-code", [], semgrep_errors=[{"level": "warn", "type": "Timeout", "message": "t"}],
                            checks_data={"results": [], "errors": ["스택 검사가 시간 제한(1초)을 넘어 중단됐습니다"], "warnings": []})
        self.assertNotIn("semgrep", m["complete_units"])
        self.assertNotIn("checks", m["complete_units"])
        self.assertEqual(m["baseline"]["resolved"], 0)
        _, m, _ = self.scan("20261103-100000-code", [sg(1, "r.a")],
                            checks_data={"results": [], "errors": [], "warnings": [], "truncated": True})
        self.assertNotIn("checks", m["complete_units"])

    def test_semgrep_partial_files_are_excluded_but_rest_is_compared(self):
        # 2차 리뷰 W2: 파싱 못 하는 파일이 늘 있어도 semgrep 의 나머지 파일은 비교한다 — 그 파일의 결과만 뺀다
        bad = [{"level": "warn", "type": "Syntax error", "path": "/src/src/legacy.swift", "message": "x"}]
        legacy = lambda line, rule: sg(line, rule, path="/src/src/legacy.swift")  # noqa: E731
        _w(os.path.join(self.target, "src", "legacy.swift"), "x\n" * 20)
        self.scan("20261101-100000-code", [sg(1, "r.a"), sg(2, "r.b"), legacy(1, "r.l")], semgrep_errors=bad)
        f, m, s = self.scan("20261102-100000-code", [sg(1, "r.a"), legacy(3, "r.l2")], semgrep_errors=bad)
        b = m["baseline"]
        self.assertIn("semgrep", m["complete_units"])
        self.assertEqual(m["partial_paths"], {"semgrep": ["src/legacy.swift"]})
        self.assertEqual((b["resolved"], b["new"]), (1, 0))                   # r.b 만 해결, legacy 의 r.l→r.l2 는 비교 안 함
        self.assertEqual(b["resolved_items"][0]["rule_id"], "r.b")
        self.assertEqual({(x["location"]["file"], x["baseline"]) for x in f},
                         {("src/app.py", "existing"), ("src/legacy.swift", "not-compared")})
        self.assertEqual(b["partial_units"], {"semgrep": 1})
        self.assertIn("일부 파일을 점검하지 못한 도구", s)

    def test_partial_file_in_only_one_run_is_excluded_from_both_sides(self):
        # 3차 리뷰 S2 a: 이번에만 파싱 못 한 파일의 이전 결과는 거짓 '해결'이 아니다. 반대로 이전에만 못 본 파일의 결과는 거짓 '신규'가 아니다
        bad = [{"level": "warn", "type": "Syntax error", "path": "/src/src/legacy.swift", "message": "x"}]
        legacy = lambda line, rule: sg(line, rule, path="/src/src/legacy.swift")  # noqa: E731
        _w(os.path.join(self.target, "src", "legacy.swift"), "x\n" * 20)
        self.scan("20261101-100000-code", [sg(1, "r.a"), legacy(1, "r.l")])
        _, m, _ = self.scan("20261102-100000-code", [sg(1, "r.a")], semgrep_errors=bad)
        self.assertEqual((m["baseline"]["resolved"], m["baseline"]["partial_units"]), (0, {"semgrep": 1}))
        f, m, _ = self.scan("20261103-100000-code", [sg(1, "r.a"), legacy(1, "r.l")])
        self.assertEqual(m["baseline"]["new"], 0)
        self.assertIn(("src/legacy.swift", "not-compared"), {(x["location"]["file"], x["baseline"]) for x in f})

    def test_too_many_partial_paths_make_semgrep_incomplete(self):
        bad = [{"level": "warn", "type": "Syntax error", "path": f"/src/f{i}.js", "message": "x"} for i in range(2001)]
        _, m, _ = self.scan("20261101-100000-code", [sg(1, "r.a")], semgrep_errors=bad)
        self.assertNotIn("semgrep", m["complete_units"])

    def test_population_comes_from_each_side_alone(self):
        # 이슈 #41 (R3-S2 b): 이번 status 에만 있는 도구, 이전 tool_status 에만 있는 도구가 각각 홀로 '비교하지 않음'에 보인다
        import baseline as bl
        prev = ("20261101-100000-code", {"complete_units": [], "unit_keys": {}, "tool_status": [{"tool": "zap", "status": "failed"}]}, [])
        r = bl.compare([], [], {}, prev, all_units=set())
        self.assertEqual(r["not_compared_units"], ["zap"])            # 이전 tool_status 만
        prev = ("20261101-100000-code", {"complete_units": [], "unit_keys": {}, "tool_status": []}, [])
        r = bl.compare([], [], {}, prev, all_units={"mobsf"})
        self.assertEqual(r["not_compared_units"], ["mobsf"])          # 이번 status 만

    def test_parser_version_is_in_keys(self):
        # 이슈 #41 (R3-S2 6): 단위의 파서 버전을 올리면 그 단위만 비교하지 않는다
        import baseline as bl
        same = bl.unit_keys(["semgrep", "zap"], [], [], [], "1")
        orig = dict(bl.PARSER_VERSION)
        try:
            bl.PARSER_VERSION["semgrep"] = orig["semgrep"] + 1
            bumped = bl.unit_keys(["semgrep", "zap"], [], [], [], "1")
        finally:
            bl.PARSER_VERSION.clear()
            bl.PARSER_VERSION.update(orig)
        self.assertNotEqual(same["semgrep"], bumped["semgrep"])
        self.assertEqual(same["zap"], bumped["zap"])

    def test_partial_count_display_is_capped_and_mentions_previous_run(self):
        # 이슈 #41 (R3-N1·N2)
        import baseline as bl
        text = "\n".join(normalize._render_baseline({"run_id": "r", "compared_units": ["semgrep"], "new": 0, "existing": 0,
                                                     "moved": 0, "resolved": 0,
                                                     "partial_units": {"semgrep": bl.PARTIAL_PATHS_MAX * 2}}))
        self.assertIn(f"{bl.PARTIAL_PATHS_MAX}개 넘는 파일", text)
        self.assertIn("이번이나 직전 실행에서", text)

    def test_units_only_in_previous_status_are_listed(self):
        # 3차 리뷰 S2 b: 이전 실행에만 있던 도구(도구 목록 변경)도 '비교하지 않음'에 보인다
        self.scan("20261101-100000-code", [sg(1, "r.a")])
        prev = os.path.join(self.reports, "20261101-100000-code", "meta.json")
        m = _read(prev)
        m["tool_status"].append({"tool": "zap", "status": "ok"})
        _w(prev, m)
        _, m, _ = self.scan("20261102-100000-code", [sg(1, "r.a")])
        self.assertIn("zap", m["baseline"]["not_compared_units"])

    def test_malformed_previous_meta_does_not_break_the_scan(self):
        # 3차 리뷰 S3: 이전 meta 값이 엉뚱한 형식이어도 이번 결과는 만든다
        prev = os.path.join(self.reports, "20261101-100000-code", "meta.json")
        for bad in ({"partial_paths": {"semgrep": 5}}, {"partial_paths": {"semgrep": "src/app.py"}}, {"tool_status": 5},
                    {"tool_status": [{"tool": ["x"]}]}, {"complete_units": [["a"], "semgrep"]}, {"unit_keys": {"semgrep": ["x"]}}):
            self.tmp.cleanup()
            os.makedirs(self.reports)
            _w(os.path.join(self.target, "src", "app.py"), "\n".join(f"os.system(c{i})" for i in range(20)) + "\n")
            self.scan("20261101-100000-code", [sg(1, "r.a")])
            m = _read(prev)
            m.update(bad)
            _w(prev, m)
            pf = os.path.join(self.reports, "20261101-100000-code", "findings.json")
            rep = _read(pf)
            rep["findings"][0]["unit"] = ["x"]
            _w(pf, rep)
            f, m2, s = self.scan("20261102-100000-code", [sg(1, "r.a")])
            self.assertIn("baseline", m2, bad)
            shutil_rm = __import__("shutil").rmtree
            shutil_rm(os.path.join(self.reports, "20261102-100000-code"))

    def test_tools_incomplete_in_both_runs_are_listed_as_not_compared(self):
        # 2차 리뷰 W1: 양쪽 모두 실패·부분 결과인 도구도 '비교하지 않음'에 보인다 — 변화 없음으로 읽히지 않게
        pathless = [{"level": "warn", "type": "Timeout", "message": "t"}]
        self.scan("20261101-100000-code", [sg(1, "r.a"), sg(2, "r.b")], semgrep_errors=pathless)
        _, m, s = self.scan("20261102-100000-code", [sg(1, "r.a")], semgrep_errors=pathless)
        self.assertIn("semgrep", m["baseline"]["not_compared_units"])
        self.assertIn("이 도구 영역의 변화는 알 수 없습니다", s)
        self.scan("20261103-100000-code", [], status={"semgrep": "failed"})
        _, m, _ = self.scan("20261104-100000-code", [], status={"semgrep": "failed"})
        self.assertIn("semgrep", m["baseline"]["not_compared_units"])

    def test_rule_tool_profile_or_plugin_changes_are_not_compared(self):
        # 리뷰 W3: 규칙 커밋·이미지·프로파일·(checks 의) 플러그인 버전이 바뀌면 그 단위는 비교하지 않는다
        self.scan("20261101-100000-code", [sg(1, "r.a")])
        f, m, s = self.scan("20261102-100000-code", [sg(1, "r.b")], meta_in={"rules": [{"name": "semgrep-rules", "commit": "c2"}]})
        b = m["baseline"]
        self.assertIn("semgrep", b["changed_units"])
        self.assertEqual((b["resolved"], [x["baseline"] for x in f]), (0, ["not-compared"]))
        self.assertIn("osv-scanner", b["compared_units"])               # 규칙과 무관한 도구는 비교한다
        self.assertIn("규칙·도구 이미지·프로파일·플러그인 버전이 바뀌어", s)
        # 플러그인 버전은 checks 에만 — 다른 단위는 업그레이드해도 비교를 이어 간다 (2차 리뷰 S2)
        _, m, _ = self.scan("20261103-100000-code", [sg(1, "r.b")],
                            meta_in={"rules": [{"name": "semgrep-rules", "commit": "c2"}], "plugin_version": "0.12.0"})
        self.assertEqual(m["baseline"]["changed_units"], ["checks"])
        _, m, _ = self.scan("20261104-100000-code", [sg(1, "r.b")],
                            meta_in={"rules": [{"name": "semgrep-rules", "commit": "c2"}], "plugin_version": "0.12.0",
                                     "tools": [{"name": "semgrep", "digest": "sha256:b"}]})
        self.assertEqual(m["baseline"]["changed_units"], ["semgrep"])
        # 프로파일이 바뀌면 semgrep·checks 가 바뀐다 (2차 리뷰 S3 b)
        _, m, _ = self.scan_profiles("20261105-100000-code", "server\t.\t\n", [sg(1, "r.b")],
                                     meta_in={"rules": [{"name": "semgrep-rules", "commit": "c2"}], "plugin_version": "0.12.0",
                                              "tools": [{"name": "semgrep", "digest": "sha256:b"}]})
        self.assertEqual(sorted(m["baseline"]["changed_units"]), ["checks", "semgrep"])

    def test_move_pairing_scope_and_marks(self):
        # 2차 리뷰 S3 a·S1: 같은 규칙이라도 다른 파일이면 이동이 아니다. 이동은 이전 줄을 보인다. 시크릿은 짝짓지 않는다
        _w(os.path.join(self.target, "src", "b.py"), "x\n" * 20)
        self.scan("20261101-100000-code", [sg(1, "r.a"), sg(4, "r.c")])
        f, m, s = self.scan("20261102-100000-code", [sg(1, "r.a", path="/src/src/b.py"), sg(6, "r.c")])
        b = m["baseline"]
        self.assertEqual((b["new"], b["moved"], b["resolved"]), (1, 1, 1))
        self.assertIn("[위치 이동 ← 4행]", s)
        self.assertIn("[high] [신규] semgrep", s)

    def test_secrets_are_never_paired_as_moves(self):
        # 3차 리뷰 S1·S2 d·S4: gitleaks 세 단위와 다른 도구의 시크릿 분류는 짝짓지 않고, 해결 쪽에 '위치만 바뀌었을 수 있음'을 표시한다
        import baseline as bl
        for unit, cat in (("gitleaks-dir", "secret"), ("gitleaks-git", "secret"), ("gitleaks-artifact", "secret"), ("semgrep", "secret")):
            leak = lambda line: {"tool": "x", "rule_id": "aws", "id": f"{unit}{line}", "severity": "high", "category": cat,  # noqa: E731
                                 "location": {"file": "a.env", "line": line, "url": None, "package": None}, "unit": unit}
            prev = ("20261101-100000-code", {"complete_units": [unit], "unit_keys": {unit: "k"}}, [leak(1)])
            cur = [leak(5)]
            r = bl.compare(cur, [unit], {unit: "k"}, prev)
            self.assertEqual((r["new"], r["moved"], r["resolved"]), (1, 0, 1), unit)
            self.assertTrue(r["resolved_items"][0].get("maybe_moved"), unit)
        text = "\n".join(normalize._render_baseline({"run_id": "r", "compared_units": ["gitleaks-dir"], "new": 1, "existing": 0,
                                                     "moved": 0, "resolved": 1, "resolved_items": [dict(r["resolved_items"][0])]}))
        self.assertIn("위치만 바뀌었을 수 있음", text)

    def test_image_digest_and_id_version_are_in_keys_and_zap_note(self):
        # 2차 리뷰 S3 c·e·6: mobsf·zap 이미지 digest, ID_VERSION 이 키에 들어간다. zap 을 비교하면 크롤링 범위 안내가 나온다
        import baseline as bl
        units = ["mobsf", "zap", "gitleaks-artifact"]
        k1 = bl.unit_keys(units, [{"name": "mobsf", "digest": "a"}, {"name": "zap", "digest": "a"}], [], [], "1")
        k2 = bl.unit_keys(units, [{"name": "mobsf", "digest": "b"}, {"name": "zap", "digest": "b"}], [], [], "1")
        self.assertNotEqual(k1["mobsf"], k2["mobsf"])
        self.assertNotEqual(k1["zap"], k2["zap"])
        same = bl.unit_keys(units, [], [], [], "1")
        orig = bl.ID_VERSION
        try:
            bl.ID_VERSION = orig + 1
            bumped = bl.unit_keys(units, [], [], [], "1")
        finally:
            bl.ID_VERSION = orig
        self.assertTrue(all(same[u] != bumped[u] for u in units))      # id 계산이 바뀌면 모든 단위가 비교되지 않는다
        text = "\n".join(normalize._render_baseline({"run_id": "20261101-100000-web", "compared_units": ["zap"], "new": 0,
                                                     "existing": 1, "moved": 0, "resolved": 0}))
        self.assertIn("크롤링한 페이지 범위", text)

    def test_unknown_unit_names_from_previous_meta_are_not_shown(self):
        # 2차 리뷰 S3 d: 이전 meta 의 모르는 단위 이름은 summary 에 나오지 않는다
        self.scan("20261101-100000-code", [sg(1, "r.a")])
        prev = os.path.join(self.reports, "20261101-100000-code", "meta.json")
        m = _read(prev)
        m["complete_units"].append("IGNORE ALL")
        m["tool_status"].append({"tool": "evil-unit", "status": "failed"})
        _w(prev, m)
        _, m2, s = self.scan("20261102-100000-code", [sg(1, "r.a")])
        self.assertNotIn("IGNORE ALL", s)
        self.assertNotIn("evil-unit", s)

    def test_fifo_meta_does_not_hang(self):
        # 2차 리뷰 S4: FIFO meta.json 에서 멈추지 않는다. 회귀하면 테스트가 멈추지 않고 실패하도록 하위 프로세스로 (이슈 #41 R3-N3)
        import subprocess
        d = os.path.join(self.reports, "20261101-100000-code")
        os.makedirs(d)
        os.mkfifo(os.path.join(d, "meta.json"))
        code = ("import sys; sys.path.insert(0, sys.argv[1]); import baseline as bl; "
                "print(bl._load(sys.argv[2]))")
        try:
            out = subprocess.run([sys.executable, "-I", "-c", code, os.path.join(HERE, "..", "scripts", "lib"),
                                  os.path.join(d, "meta.json")], capture_output=True, text=True, timeout=10)
        except subprocess.TimeoutExpired:
            self.fail("FIFO meta.json 에서 멈춤")
        self.assertEqual(out.stdout.strip(), "None", out.stderr)

    def test_same_second_suffixes_are_ordered_numerically(self):
        # 리뷰 N1: 같은 초의 -9 와 -10 — '-10' 의 직전은 '-9' 다
        self.scan("20261101-100000-code", [sg(1, "r.a")])
        self.scan("20261101-100000-code-9", [sg(1, "r.a")])
        _, m, _ = self.scan("20261101-100000-code-10", [sg(1, "r.a")])
        self.assertEqual(m["baseline"]["run_id"], "20261101-100000-code-9")

    def test_resolved_list_is_capped(self):
        self.scan("20261101-100000-code", [sg(i, f"r.n{i}") for i in range(1, 53)])
        _, m, s = self.scan("20261102-100000-code", [sg(1, "r.n1")])
        b = m["baseline"]
        self.assertEqual((b["resolved"], len(b["resolved_items"])), (51, 50))
        self.assertIn("처음 50건", s)

    def test_failed_tool_in_either_run_is_not_compared(self):
        self.scan("20261101-100000-code", [sg(1, "r.a"), sg(2, "r.b")])
        # 이번에 semgrep 이 실패 — 결과가 비었지만 '해결'로 보지 않는다
        f2, m2, s2 = self.scan("20261102-100000-code", [], status={"semgrep": "failed"})
        b = m2["baseline"]
        self.assertEqual(b["resolved"], 0)
        self.assertIn("semgrep", b["not_compared_units"])
        self.assertNotIn("semgrep", m2["complete_units"])
        self.assertIn("비교하지 않은 도구", s2)
        # 직전(실패) 실행과 비교하므로 다시 성공한 semgrep 결과도 '신규'가 아니라 '비교 안 함'
        f3, m3, _ = self.scan("20261103-100000-code", [sg(1)])
        self.assertEqual([f["baseline"] for f in f3], ["not-compared"])
        self.assertEqual(m3["baseline"]["run_id"], "20261102-100000-code")
        self.assertIn("semgrep", m3["baseline"]["not_compared_units"])       # '바뀜'이 아니라 '한쪽에서 실패'
        self.assertNotIn("semgrep", m3["baseline"]["changed_units"])
        # 결과 파일을 해석하지 못한 단위(checks 빈 파일)도 완전하지 않다
        _, m4, _ = self.scan("20261104-100000-code", [sg(1)], checks=False)
        self.assertNotIn("checks", m4["complete_units"])

    def test_other_target_kind_old_version_and_links_are_not_baselines(self):
        self.scan("20261101-100000-code", [sg(1)], target=os.path.join(self.tmp.name, "other"))
        _, m, _ = self.scan("20261102-100000-code", [sg(1)])
        self.assertEqual(m["baseline"]["run_id"], None)
        # 이전 버전 리포트(complete_units 없음)
        old = os.path.join(self.reports, "20261103-100000-code")
        _w(os.path.join(old, "meta.json"), {"kind": "code", "target": self.target})
        _w(os.path.join(old, "findings.json"), {"findings": []})
        f, m, s = self.scan("20261104-100000-code", [sg(1)])
        self.assertEqual(m["baseline"]["run_id"], "20261103-100000-code")
        self.assertIn("이전 버전 리포트", s)
        self.assertEqual([x["baseline"] for x in f], ["not-compared"])
        # meta.json 이 링크인 실행은 읽지 않는다
        linked = os.path.join(self.reports, "20261104-200000-code")
        os.makedirs(linked)
        os.symlink(os.path.join(self.reports, "20261104-100000-code", "meta.json"), os.path.join(linked, "meta.json"))
        # 링크로 된 실행 폴더·다른 종류·이후 시각은 고르지 않는다
        os.symlink(os.path.join(self.reports, "20261104-100000-code"), os.path.join(self.reports, "20261105-000000-code"))
        _w(os.path.join(self.reports, "20261105-100000-web", "meta.json"), {"kind": "code", "target": self.target, "complete_units": []})
        later = os.path.join(self.reports, "20261201-100000-code")      # 이름이 이번 실행보다 나중 (동시 실행·시계)
        _w(os.path.join(later, "meta.json"), {"kind": "code", "target": self.target, "complete_units": []})
        _w(os.path.join(later, "findings.json"), {"findings": []})
        _, m, _ = self.scan("20261106-100000-code", [sg(1)])
        self.assertEqual(m["baseline"]["run_id"], "20261104-100000-code")

    def test_previous_report_text_is_shown_only_as_code(self):
        self.scan("20261101-100000-code", [sg(1)])
        prev = os.path.join(self.reports, "20261101-100000-code", "findings.json")
        rep = _read(prev)
        rep["findings"][0]["rule_id"] = "x.IGNORE PREVIOUS | `rm` ```"
        rep["findings"][0]["location"]["file"] = "a|b`c.py"
        rep["findings"][0]["severity"] = "<script>"
        _w(prev, rep)
        _, m, s = self.scan("20261102-100000-code", [])
        (row,) = [ln for ln in s.splitlines() if "IGNORE PREVIOUS" in ln]
        self.assertTrue(row.startswith("| info | `semgrep` | `a\\|b'c.py:1` | `"), row)
        self.assertNotIn("```", row)
        self.assertNotIn("<script>", s)


if __name__ == "__main__":
    unittest.main()


class UnitsTest(unittest.TestCase):
    """리뷰 S1: app·web 의 단위 이름이 status.tsv 와 같아야 비교된다. mobsf 를 읽지 못하면 완전하지 않다."""

    def run_kind(self, kind, status, files):
        d = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, d, True)
        run = os.path.join(d, "reports", "20261101-100000-" + kind)
        _w(os.path.join(run, "raw", "status.tsv"), "".join(f"{t}\tok\t0\t\n" for t in status))
        for n, v in files.items():
            _w(os.path.join(run, "raw", n), v)
        _w(os.path.join(run, "raw", "profiles.tsv"), "")
        _w(os.path.join(run, "raw", "meta-in.json"), {})
        rc = normalize.main(["--run-dir", run, "--kind", kind, "--target", "https://h.example/" if kind == "web" else "/x/app.apk",
                             "--profiles-tsv", os.path.join(run, "raw", "profiles.tsv"), "--meta-json", os.path.join(run, "raw", "meta-in.json")])
        self.assertEqual(rc, 0)
        self.last_meta = os.path.join(run, "meta.json")
        return _read(self.last_meta)

    def findings_of(self, meta):
        return _read(os.path.join(os.path.dirname(self.last_meta), "findings.json"))["findings"]

    def test_web_and_app_units(self):
        zap = {"site": [{"@name": "https://h.example", "alerts": [{"pluginid": "10038", "alertRef": "10038-1", "alert": "CSP",
               "riskcode": "2", "confidence": "2", "instances": [{"uri": "https://h.example/", "method": "GET"}], "desc": "d", "solution": "s"}]}]}
        m = self.run_kind("web", ["zap"], {"zap.json": zap})
        self.assertEqual(m["complete_units"], ["zap"])
        self.assertEqual({f["unit"] for f in self.findings_of(m)}, {"zap"})      # 결과의 단위 = status 의 도구 이름
        leak = [{"RuleID": "aws", "File": "/in/artifact.zip!a.txt", "StartLine": 1, "Secret": "x", "Match": "x"}]
        m = self.run_kind("app", ["mobsf", "gitleaks-artifact"], {"gitleaks-artifact.json": leak})
        self.assertEqual(m["complete_units"], ["gitleaks-artifact"])     # mobsf 결과 없음 → 완전하지 않음
        self.assertEqual({f["unit"] for f in self.findings_of(m)}, {"gitleaks-artifact"})
        m = self.run_kind("app", ["mobsf", "gitleaks-artifact"], {"gitleaks-artifact.json": [], "mobsf-full.json": "{oops"})
        self.assertNotIn("mobsf", m["complete_units"])
        # mobsf 해석이 예외를 내면 완전하지 않다
        from unittest import mock
        with mock.patch.object(normalize, "parse_mobsf", side_effect=ValueError("x")):
            m = self.run_kind("app", ["mobsf", "gitleaks-artifact"], {"gitleaks-artifact.json": [], "mobsf-full.json": {"appsec": {}}})
        self.assertNotIn("mobsf", m["complete_units"])
        with mock.patch.object(normalize, "parse_mobsf", return_value=([], [])):
            m = self.run_kind("app", ["mobsf", "gitleaks-artifact"], {"gitleaks-artifact.json": [], "mobsf-full.json": {"appsec": {}}})
        self.assertIn("mobsf", m["complete_units"])
