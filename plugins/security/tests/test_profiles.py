"""profiles.py 단위 테스트 — YAML 부분집합 파서, 스키마 검증, 스택 감지."""

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts", "lib"))

import checks  # noqa: E402
import profiles  # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures", "detect")


class YamlSubsetTest(unittest.TestCase):
    def test_block_map_list_and_flow(self):
        src = """
name: web   # 주석
detect:
  - "**/next.config.*"
  - { file: "**/package.json", has_dependency: [next, "@angular/core"] }
semgrep:
  rulesets: [javascript, typescript]
empty:
"""
        data = profiles.parse_yaml(src)
        self.assertEqual(data["name"], "web")
        self.assertEqual(data["detect"][0], "**/next.config.*")
        self.assertEqual(data["detect"][1], {"file": "**/package.json", "has_dependency": ["next", "@angular/core"]})
        self.assertEqual(data["semgrep"]["rulesets"], ["javascript", "typescript"])
        self.assertIsNone(data["empty"])

    def test_list_without_indent_and_list_of_maps(self):
        data = profiles.parse_yaml("items:\n- a\n- b\nchecks:\n  - id: A1\n    title: 'x # not comment'\n  - id: A2\n")
        self.assertEqual(data["items"], ["a", "b"])
        self.assertEqual(data["checks"], [{"id": "A1", "title": "x # not comment"}, {"id": "A2"}])

    def test_rejects_unsupported_and_broken(self):
        for bad in ("a: &anchor x", "a: [1, 2", "a: 'x", "a: 1\na: 2", "a:\n\t- x", "a: 1\n   b: 2"):
            with self.subTest(bad=bad):
                with self.assertRaises(profiles.YamlError):
                    profiles.parse_yaml(bad)


class YamlEdgeTest(unittest.TestCase):
    def test_apostrophe_inside_plain_value_and_bom(self):
        self.assertEqual(profiles.parse_yaml("description: Flutter's app # 주석\n"), {"description": "Flutter's app"})
        self.assertEqual(profiles.parse_yaml("\ufeffname: x\n".lstrip("\ufeff")), {"name": "x"})

    def test_bare_dash_item_after_key(self):
        self.assertEqual(profiles.parse_yaml("a:\n-\n  b: 1\n"), {"a": [{"b": 1}]})


class SchemaTest(unittest.TestCase):
    def _write(self, d, name, body):
        with open(os.path.join(d, name), "w", encoding="utf-8") as f:
            f.write(body)

    def test_repo_profiles_are_valid(self):
        loaded = profiles.load_profiles(profiles.DEFAULT_PROFILE_DIR)
        self.assertEqual(sorted(loaded), ["android", "flutter", "ios", "react-native", "server", "web"])

    def test_schema_errors_are_reported(self):
        with tempfile.TemporaryDirectory() as d:
            self._write(d, "bad.yaml", """
name: other
detect: []
typo: 1
semgrep: { rulesets: javascript }
sca: { lockfiles: [] }
artifact: { types: [exe], analyzer: x }
exclude_if: [missing]
""")
            with self.assertRaises(profiles.ProfileError) as ctx:
                profiles.load_profiles(d)
            msg = "\n".join(ctx.exception.errors)
            for expected in ("파일 이름과 다릅니다", "detect 는 비어 있지 않은", "알 수 없는 키 'typo'",
                             "semgrep.rulesets", "artifact.types", "artifact.analyzer", "'missing' 프로파일이 없습니다"):
                self.assertIn(expected, msg)

    def test_dependency_condition_requires_known_manifest(self):
        errs = profiles.validate_profile({
            "name": "x", "detect": [{"file": "**/Gemfile", "has_dependency": ["rails"]}],
            "semgrep": {"rulesets": []}, "sca": {"lockfiles": []},
        }, "x.yaml")
        self.assertTrue(any("detect[0].file" in e for e in errs))

    def test_detect_exclude_must_be_string_list(self):
        base = {"name": "x", "detect": ["**/a"], "semgrep": {"rulesets": []}, "sca": {"lockfiles": []}}
        self.assertEqual(profiles.validate_profile(dict(base, detect_exclude=["**/macos/**"]), "x.yaml"), [])
        self.assertEqual(profiles.validate_profile(dict(base, detect_exclude=[]), "x.yaml"), [])
        errs = profiles.validate_profile(dict(base, detect_exclude="**/macos/**"), "x.yaml")
        self.assertTrue(any("detect_exclude 는 문자열 리스트" in e for e in errs))


class GlobTest(unittest.TestCase):
    def test_double_star(self):
        self.assertTrue(profiles.glob_match("**/package.json", "package.json"))
        self.assertTrue(profiles.glob_match("**/package.json", "a/b/package.json"))
        self.assertFalse(profiles.glob_match("**/package.json", "a/package.json.bak"))
        self.assertTrue(profiles.glob_match("**/build/**", "android/app/build/x/y.class"))
        self.assertFalse(profiles.glob_match("*.json", "a/b.json"))
        self.assertTrue(profiles.glob_match("**/requirements*.txt", "svc/requirements-dev.txt"))


class DependencyTest(unittest.TestCase):
    def test_pyproject_and_requirements(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "pyproject.toml")
            with open(p, "w") as f:
                f.write('[project]\nname = "fastapi-demo"\ndependencies = ["Fast_API>=1", "uvicorn[standard]"]\n'
                        '[tool.poetry.dependencies]\npython = "^3.11"\nDjango = "^5"\n')
            names = profiles.dependency_names(p)
            self.assertIn("fast-api", names)
            self.assertIn("uvicorn", names)
            self.assertIn("django", names)
            self.assertNotIn("python", names)
            self.assertNotIn("name", names)
            r = os.path.join(d, "requirements.txt")
            with open(r, "w") as f:
                f.write("# c\n-r base.txt\nflask==3.0\n")
            self.assertEqual(profiles.dependency_names(r), {"flask"})

    def test_pyproject_without_tomllib(self):
        """Python 3.8~3.10 (tomllib 없음) 대체 파서."""
        from unittest import mock
        src = ('[project]\nname = "demo"\ndependencies = [\n  "fastapi>=0.1",\n  "uvicorn[standard]",\n]\n'
               '[tool.poetry.dependencies]\npython = "^3.11"\nDjango = "^5"\n')
        with mock.patch.dict(sys.modules, {"tomllib": None}):
            names = profiles._pyproject_deps(src)
        self.assertEqual(names, {"fastapi", "uvicorn", "django"})

    def test_gradle_plugin_ids(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "build.gradle.kts")
            with open(p, "w") as f:
                f.write('plugins { id("com.android.library") }\ndependencies { implementation("com.squareup.okhttp3:okhttp:4.12.0") }\n')
            names = profiles.dependency_names(p)
            self.assertIn("com.android.library", names)
            self.assertIn("okhttp", names)
            self.assertIn("com.squareup.okhttp3:okhttp", names)


class PlanExcludeTest(unittest.TestCase):
    """PR #19 QUESTION: exclude_paths 는 그 프로파일이 감지된 하위 경로 안에서만 적용한다."""

    @classmethod
    def setUpClass(cls):
        cls.profiles = profiles.load_profiles(profiles.DEFAULT_PROFILE_DIR)

    def excludes(self, detected):
        with tempfile.TemporaryDirectory() as d:
            return [v for k, v in profiles.build_plan(detected, self.profiles, d, d) if k == "exclude"]

    def test_root_profile_applies_everywhere(self):
        ex = self.excludes([("server", ".")])
        self.assertIn("build", ex)
        self.assertIn("node_modules", ex)

    def test_subpath_profile_is_anchored_to_its_root(self):
        """Flutter 의 ios/ 프로파일이 macos 러너(macos/)나 다른 프로젝트의 build/ 를 제외하지 않는다"""
        ex = self.excludes([("flutter", "."), ("ios", "ios"), ("android", "android"), ("server", "backend")])
        self.assertIn("ios/**/DerivedData", ex)
        self.assertFalse(any("macos" in x for x in ex))  # macos 는 감지에서만 뺀다 (detect_exclude)
        self.assertIn("backend/**/build", ex)
        self.assertIn("backend/**/node_modules", ex)
        self.assertIn("build", ex)            # flutter(.) 자체의 제외는 전체 적용
        self.assertNotIn("node_modules", ex)  # server 는 backend/ 에서만 감지됨
        self.assertIn("Pods", ex)             # 어느 프로파일에도 속하지 않는 macos/Pods 도 전역 제외 (PR #22 리뷰)

    def test_root_pattern_with_separator_applies_at_any_depth(self):
        """PR #22 리뷰: gitignore 에서 가운데 / 가 있는 패턴은 루트에 고정되므로 **/ 를 붙인다"""
        ex = self.excludes([("react-native", ".")])
        self.assertIn("**/ios/Pods", ex)
        self.assertIn("**/android/build", ex)
        self.assertEqual(profiles.scoped_exclude("**/Carthage/Build/**", "."), "**/Carthage/Build")
        self.assertEqual(profiles.scoped_exclude("**/gen/**", "./pkg"), "pkg/**/gen")

    def test_subpath_glob_characters_are_escaped(self):
        self.assertEqual(profiles.scoped_exclude("**/build/**", "apps/a[1]"), "apps/a\\[1\\]/**/build")
        self.assertEqual(profiles.scoped_exclude("**/*.g.dart", "!pkg"), "\\!pkg/**/*.g.dart")
        self.assertEqual(profiles.scoped_exclude("**/gen/**", "#h"), "\\#h/**/gen")
        self.assertEqual(profiles.scoped_exclude("**/gen/**", "q?"), "q\\?/**/gen")
        self.assertEqual(profiles.scoped_exclude("**/gen/**", "back\\sl"), "back\\\\sl/**/gen")
        self.assertEqual(profiles.scoped_exclude("**/x/**", "."), "x")


class DetectTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profiles = profiles.load_profiles(profiles.DEFAULT_PROFILE_DIR)

    def detect(self, case, forced=None):
        return profiles.detect(os.path.join(FIXTURES, case), self.profiles, forced)

    def test_ios_native(self):
        self.assertEqual(self.detect("ios-native"), [("ios", ".")])

    def test_android_native(self):
        self.assertEqual(self.detect("android-native"), [("android", ".")])

    def test_flutter_applies_native_profiles_to_subpaths_only(self):
        self.assertEqual(self.detect("flutter-app"), [("android", "android"), ("flutter", "."), ("ios", "ios")])

    def test_react_native_is_not_web_and_native_subpaths(self):
        self.assertEqual(self.detect("react-native-app"),
                         [("android", "android"), ("ios", "ios"), ("react-native", ".")])

    def test_web_next_ignores_node_modules(self):
        self.assertEqual(self.detect("web-next"), [("web", ".")])

    def test_server_python(self):
        self.assertEqual(self.detect("server-python"), [("server", ".")])

    def test_server_go(self):
        self.assertEqual(self.detect("server-go"), [("server", ".")])

    def test_jvm_server_is_not_android(self):
        self.assertEqual(self.detect("server-jvm"), [("server", ".")])

    def test_monorepo_exclude_if_per_subproject(self):
        self.assertEqual(self.detect("monorepo"),
                         [("react-native", "apps/mobile"), ("server", "services/api"), ("web", "apps/web")])

    def test_none_detected(self):
        self.assertEqual(self.detect("none"), [])

    def test_pure_dart_package_is_not_flutter(self):
        self.assertEqual(self.detect("dart-package"), [])

    def test_forced_profiles(self):
        self.assertEqual(self.detect("none", ["web", "server", "web"]), [("web", "."), ("server", ".")])
        with self.assertRaises(SystemExit):
            self.detect("none", ["cobol"])

    def test_labels(self):
        self.assertEqual(profiles.format_profile_label("flutter", "."), "flutter")
        self.assertEqual(profiles.format_profile_label("android", "android"), "android:android/")

    def _tree(self, d, files):
        for rel, body in files.items():
            path = os.path.join(d, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(body)

    def test_root_markers_do_not_hoist_other_detect_items(self):
        """PR #18 W5: 루트 Android 앱 + backend(express) — server 가 루트로 올라가 사라지면 안 된다."""
        with tempfile.TemporaryDirectory() as d:
            self._tree(d, {
                "settings.gradle": "include ':app'",
                "app/build.gradle": "plugins { id 'com.android.application' }",
                "app/src/main/AndroidManifest.xml": "<manifest/>",
                "backend/package.json": '{"dependencies": {"express": "4"}}',
                "tools/requirements.txt": "flask==3.0\n",
            })
            self.assertEqual(profiles.detect(d, self.profiles),
                             [("android", "."), ("server", "backend"), ("server", "tools")])

    def test_collapsed_root_keeps_exclude_if_subpaths(self):
        """PR #18 W6: 루트 devDependencies 의 react 로 web 이 . 이 돼도 RN 앱 경로는 제외 경로로 남는다."""
        with tempfile.TemporaryDirectory() as d:
            self._tree(d, {
                "package.json": '{"devDependencies": {"react": "18"}}',
                "apps/web/package.json": '{"dependencies": {"react": "18"}}',
                "apps/mobile/package.json": '{"dependencies": {"react": "18", "react-native": "0.74"}}',
            })
            self.assertEqual(profiles.detect_full(d, self.profiles),
                             [("react-native", "apps/mobile", []), ("web", ".", ["apps/mobile"])])

    def test_pubspec_four_space_indent(self):
        with tempfile.TemporaryDirectory() as d:
            self._tree(d, {"pubspec.yaml": "name: a\ndependencies:\n    flutter:\n        sdk: flutter\n    http: ^1.0.0\n"})
            self.assertEqual(profiles.dependency_names(os.path.join(d, "pubspec.yaml")), {"flutter", "http"})
            self.assertEqual(profiles.detect(d, self.profiles), [("flutter", ".")])

    def test_flutter_macos_runner_is_not_ios(self):
        with tempfile.TemporaryDirectory() as d:
            self._tree(d, {
                "pubspec.yaml": "dependencies:\n  flutter:\n    sdk: flutter\n",
                "ios/Runner.xcodeproj/project.pbxproj": "x",
                "macos/Runner.xcodeproj/project.pbxproj": "x",
            })
            self.assertEqual(profiles.detect(d, self.profiles), [("flutter", "."), ("ios", "ios")])

    def test_detect_exclude_only_affects_detection(self):
        """ios 의 **/macos/** 는 감지에서만 뺀다 — 루트 iOS 프로젝트의 macos/ 소스는 스캔·스택 검사 대상이다"""
        with tempfile.TemporaryDirectory() as d:
            self._tree(d, {
                "App.xcodeproj/project.pbxproj": "x",
                "macos/Info.plist": "x",
                "macos/Sources/AppDelegate.swift": "x",
            })
            self.assertEqual(profiles.detect(d, self.profiles), [("ios", ".")])
            with tempfile.TemporaryDirectory() as r:
                ex = [v for k, v in profiles.build_plan([("ios", ".")], self.profiles, r, r) if k == "exclude"]
            self.assertFalse(any("macos" in x for x in ex), ex)
            self.assertIn(".build", ex)
        # 스택 검사(checks.run)도 macos/ 의 Info.plist 를 본다
        with tempfile.TemporaryDirectory() as d:
            self._tree(d, {
                "App.xcodeproj/project.pbxproj": "x",
                "macos/Info.plist": ('<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0"><dict>'
                                     '<key>NSAppTransportSecurity</key><dict><key>NSAllowsArbitraryLoads</key><true/>'
                                     '</dict></dict></plist>\n'),
            })
            out = checks.run(d, profiles.detect_full(d, self.profiles), self.profiles)
            files = {r.get("file") for r in out["results"] if str(r.get("rule_id", "")).startswith("ios.ats")}
            self.assertIn("macos/Info.plist", files, out)

    def test_venv_dirs_by_marker_file(self):
        """가상환경은 이름이 아니라 pyvenv.cfg + site-packages 로 찾는다 (PR #30 3차 W-A, 4차 S-1·S-2)"""
        sp = "lib/python3.12/site-packages/x.py"
        with tempfile.TemporaryDirectory() as d:
            self._tree(d, {
                "pyvenv.cfg": "x", sp: "x",              # 대상 루트 자체는 제외하지 않는다
                "env/pyvenv.cfg": "x", "env/" + sp: "x",
                "env/lib/inner/pyvenv.cfg": "x",         # 가상환경 안으로는 내려가지 않는다
                "apps/a[1]/.venv-3.12/pyvenv.cfg": "x", "apps/a[1]/.venv-3.12/" + sp: "x",
                "win/pyvenv.cfg": "x", "win/Lib/site-packages/x.py": "x",   # Windows 배치
                "venv/py311/pyvenv.cfg": "x", "venv/py311/" + sp: "x",      # Semgrep 이 보는 venv/ 아래도 찾는다
                "out/v/pyvenv.cfg": "x", "out/v/" + sp: "x",
                "node_modules/x/pyvenv.cfg": "x", "node_modules/x/" + sp: "x",  # Semgrep 이 안 보는 폴더는 건너뜀
                "src/env/main.py": "x",                  # 같은 이름이라도 표식이 없으면 소스
                "src/fake/pyvenv.cfg": "x", "src/fake/app.py": "x",         # 표식만 있고 site-packages 가 없으면 소스
                "fake/pyvenv.cfg/readme": "x",           # pyvenv.cfg 가 폴더면 표식이 아니다
            })
            os.makedirs(os.path.join(d, "linked"))
            os.symlink(os.path.join(d, "env", "pyvenv.cfg"), os.path.join(d, "linked", "pyvenv.cfg"))
            os.symlink(os.path.join(d, "env", "lib"), os.path.join(d, "linked", "lib"))
            self.assertEqual(profiles.venv_dirs(d),
                             ["apps/a[1]/.venv-3.12", "env", "out/v", "venv/py311", "win"])
        self.assertEqual(profiles.venv_exclude("env"), "/env")
        self.assertEqual(profiles.venv_exclude("apps/a[1]/v*?"), "/apps/a\\[1\\]/v\\*\\?")

    def test_venv_structure_guards_each_fixed(self):
        """가드를 하나씩 고정한다 — symlink 는 판정 경로 어느 단계에서도 쓰지 않고, 이름은 대소문자까지 맞아야 하며,
        인터프리터 폴더는 python*·pypy* 만 본다 (PR #30 5차 리뷰 S-1·S-4)"""
        sp = "lib/python3.12/site-packages/x.py"
        with tempfile.TemporaryDirectory() as d:
            self._tree(d, {
                "env/pyvenv.cfg": "x", "env/" + sp: "x",
                "win/pyvenv.cfg": "x", "win/Lib/site-packages/x.py": "x",
                "pypy/pyvenv.cfg": "x", "pypy/lib/pypy3.10/site-packages/x.py": "x",   # PyPy 가상환경
                "foo/pyvenv.cfg": "x", "foo/lib/foo/site-packages/x.py": "x",         # 접두어가 다르면 소스
                "nover/pyvenv.cfg": "x", "nover/lib/site-packages/x.py": "x",         # 인터프리터 폴더 없음 (대소문자 무관 FS 에서 Lib 분기로도 통과 금지)
                "lncfg/" + sp: "x",                                                   # 진짜 lib + symlink cfg
                "lnlib/pyvenv.cfg": "x",                                              # 진짜 cfg + symlink lib
                "lnver/pyvenv.cfg": "x", "lnver/lib/keep": "x",                       # 인터프리터 폴더가 symlink
                "lnsp/pyvenv.cfg": "x", "lnsp/lib/python3.12/keep": "x",              # site-packages 가 symlink
                "lnwin/pyvenv.cfg": "x", "lnwin/Lib/keep": "x",                       # Windows site-packages 가 symlink
                "lnwinlib/pyvenv.cfg": "x",                                           # Windows Lib 가 symlink
                # 이름의 대소문자 — 대소문자를 가리지 않는 FS(macOS 기본)에서만 뜻이 있다 (PR #31 1차 리뷰 S-1)
                "upcfg/PYVENV.CFG": "x", "upcfg/" + sp: "x",
                "winupsp/pyvenv.cfg": "x", "winupsp/Lib/SITE-PACKAGES/x.py": "x",
                "uplib/pyvenv.cfg": "x", "uplib/Lib/python3.12/site-packages/x.py": "x",
                "upsp/pyvenv.cfg": "x", "upsp/lib/python3.12/SITE-PACKAGES/x.py": "x",
                "cfgdir/pyvenv.cfg/readme": "x", "cfgdir/" + sp: "x",                 # pyvenv.cfg 가 폴더
            })

            def j(*a):
                return os.path.join(d, *a)
            os.symlink(j("env", "pyvenv.cfg"), j("lncfg", "pyvenv.cfg"))
            os.symlink(j("env", "lib"), j("lnlib", "lib"))
            os.symlink(j("env", "lib", "python3.12"), j("lnver", "lib", "python3.12"))
            os.symlink(j("env", "lib", "python3.12", "site-packages"), j("lnsp", "lib", "python3.12", "site-packages"))
            os.symlink(j("win", "Lib", "site-packages"), j("lnwin", "Lib", "site-packages"))
            os.symlink(j("win", "Lib"), j("lnwinlib", "Lib"))
            self.assertEqual(profiles.venv_dirs(d), ["env", "pypy", "win"])

    def test_venv_walk_limit_warning_matches_scan_code_contract(self):
        """상한에 걸린 stderr 한 줄은 scan-code.sh 가 고르는 접두어로 시작해야 summary 경고로 옮겨진다 (PR #30 5차 리뷰 S-3)"""
        import contextlib
        import io
        import re
        scan_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "scan-code.sh")
        with open(scan_path, encoding="utf-8") as f:
            scan = f.read()
        pats = re.findall(r"grep [^\n]*?'(\^[^']*)' \"\$RAW/detect\.log\"", scan)
        self.assertEqual(len(pats), 1, f"scan-code.sh 의 상한 경고 grep 은 한 곳이어야 한다: {pats}")
        # grep BRE 와 Python 정규식의 해석이 갈리지 않게 '^리터럴' 꼴만 허용하고 startswith 로 비교한다 (PR #31 1차 리뷰 N-3)
        self.assertRegex(pats[0], r"^\^[^\\.*\[\]$]+$")
        prefix = pats[0][1:]
        with tempfile.TemporaryDirectory() as d:
            self._tree(d, {"a/x.py": "x", "b/x.py": "x"})
            err = io.StringIO()
            old = profiles.MAX_WALK_ENTRIES
            profiles.MAX_WALK_ENTRIES = 1
            try:
                with contextlib.redirect_stderr(err):
                    profiles.venv_dirs(d)
            finally:
                profiles.MAX_WALK_ENTRIES = old
        lines = err.getvalue().splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(lines[0].startswith(prefix), (lines[0], prefix))

    def test_global_excludes_avoid_source_like_names(self):
        for name in (".next", "__pycache__", "Carthage", ".nuxt"):
            self.assertIn(name, profiles.GLOBAL_EXCLUDES)
        for name in ("out", "target", "coverage", "env", "src", "lib"):
            self.assertNotIn(name, profiles.GLOBAL_EXCLUDES)

    def test_macos_only_project_is_not_ios(self):
        with tempfile.TemporaryDirectory() as d:
            self._tree(d, {"macos/Runner.xcodeproj/project.pbxproj": "x", "macos/Podfile": "x"})
            self.assertEqual(profiles.detect(d, self.profiles), [])

    def test_symlinked_dirs_are_not_followed(self):
        with tempfile.TemporaryDirectory() as d:
            outside = os.path.join(d, "outside")
            os.makedirs(outside)
            with open(os.path.join(outside, "go.mod"), "w") as f:
                f.write("module x\n")
            proj = os.path.join(d, "proj")
            os.makedirs(proj)
            os.symlink(outside, os.path.join(proj, "link"))
            self.assertEqual(profiles.detect(proj, self.profiles), [])


if __name__ == "__main__":
    unittest.main()
