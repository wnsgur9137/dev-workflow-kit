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
        self.assertEqual(self.detect("none", ["web", "server"]), [("web", "."), ("server", ".")])
        with self.assertRaises(SystemExit):
            self.detect("none", ["cobol"])

    def test_labels(self):
        self.assertEqual(profiles.format_profile_label("flutter", "."), "flutter")
        self.assertEqual(profiles.format_profile_label("android", "android"), "android:android/")

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
