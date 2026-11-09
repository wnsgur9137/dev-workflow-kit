"""profiles.py 단위 테스트 — YAML 부분집합 파서, 스키마 검증, 스택 감지."""

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts", "lib"))

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
        self.assertIn("ios/**/macos", ex)
        self.assertNotIn("macos", ex)
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
