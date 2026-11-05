#!/usr/bin/env python3
"""security 플러그인 스택 프로파일 로더·감지기.

표준 라이브러리만 사용한다 (PyYAML 미설치 환경 대비). 프로파일 파일은 아래
"YAML 부분집합"만 쓴다 — 블록 매핑/리스트, 흐름 리스트 `[a, b]`, 흐름 매핑
`{k: v}`, 따옴표 문자열, `#` 주석. 앵커·여러 줄 문자열·태그는 지원하지 않는다.

사용:
  profiles.py validate [--dir DIR]
  profiles.py get NAME [--dir DIR]
  profiles.py detect TARGET [--profiles a,b] [--format tsv|json] [--dir DIR]

detect 출력(tsv): 한 줄에 `<프로파일>\t<하위 경로>` (하위 경로는 대상 기준, 루트는 `.`)
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import sys

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_PROFILE_DIR = os.path.join(PLUGIN_ROOT, "profiles")

# 감지 시 내려가지 않는 폴더 (빌드 산출물·의존성·VCS)
WALK_SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "Pods", "Carthage", ".build", "build",
    "DerivedData", ".dart_tool", ".gradle", ".idea", ".vscode", "vendor", "dist",
    ".next", ".nuxt", "out", "target", "__pycache__", ".venv", "venv", ".tox",
    ".expo", ".symlinks", "ephemeral",
}
# 감지에서 매칭은 하되 그 안으로는 내려가지 않는 번들형 디렉터리
WALK_BUNDLE_SUFFIXES = (".xcodeproj", ".xcworkspace", ".framework", ".xcframework", ".app")
MAX_WALK_ENTRIES = 200_000


# ---------------------------------------------------------------------------
# YAML 부분집합 파서
# ---------------------------------------------------------------------------
class YamlError(ValueError):
    pass


def _strip_comment(line: str) -> str:
    out, quote = [], None
    for i, ch in enumerate(line):
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
        elif ch in ("'", '"') and (i == 0 or line[i - 1] in " \t[{,:-"):
            # 따옴표는 토큰 시작에서만 문자열을 연다 (Flutter's 같은 값 중간의 ' 는 문자)
            quote = ch
            out.append(ch)
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        else:
            out.append(ch)
    return "".join(out).rstrip()


def _split_flow(body: str, lineno: int) -> list[str]:
    parts, depth, quote, cur = [], 0, None, []
    for ch in body:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
            continue
        cur.append(ch)
    if quote or depth != 0:
        raise YamlError(f"{lineno}행: 괄호·따옴표 짝이 맞지 않습니다")
    tail = "".join(cur).strip()
    if tail:
        parts.append(tail)
    return parts


def _split_key(text: str, lineno: int):
    """`key: rest` → (key, rest). 따옴표 키 지원. 콜론이 없으면 None."""
    if text[:1] in ("'", '"'):
        q = text[0]
        end = text.find(q, 1)
        if end < 0:
            raise YamlError(f"{lineno}행: 키 따옴표가 닫히지 않았습니다")
        key, rest = text[1:end], text[end + 1:]
        if not rest.startswith(":"):
            return None
        return key, rest[1:].strip()
    m = re.match(r"^([^:\s][^:]*?)\s*:(\s+|$)(.*)$", text)
    if not m:
        return None
    return m.group(1), m.group(3).strip()


def _scalar(text: str, lineno: int):
    text = text.strip()
    if text == "":
        return None
    if text[0] == "[":
        if not text.endswith("]"):
            raise YamlError(f"{lineno}행: 흐름 리스트가 닫히지 않았습니다")
        return [_scalar(p, lineno) for p in _split_flow(text[1:-1], lineno)]
    if text[0] == "{":
        if not text.endswith("}"):
            raise YamlError(f"{lineno}행: 흐름 매핑이 닫히지 않았습니다")
        out = {}
        for p in _split_flow(text[1:-1], lineno):
            kv = _split_key(p, lineno)
            if kv is None:
                raise YamlError(f"{lineno}행: 흐름 매핑 항목에 키가 없습니다: {p}")
            if kv[0] in out:
                raise YamlError(f"{lineno}행: 키 중복: {kv[0]}")
            out[kv[0]] = _scalar(kv[1], lineno)
        return out
    if text[0] in ("'", '"'):
        if len(text) < 2 or text[-1] != text[0]:
            raise YamlError(f"{lineno}행: 문자열 따옴표가 닫히지 않았습니다")
        return text[1:-1]
    if text in ("true", "false"):
        return text == "true"
    if text in ("null", "~"):
        return None
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if text[0] in "&*!|>":
        raise YamlError(f"{lineno}행: 지원하지 않는 YAML 문법입니다: {text[:20]}")
    return text


def parse_yaml(src: str):
    lines = []
    for n, raw in enumerate(src.splitlines(), 1):
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise YamlError(f"{n}행: 들여쓰기에 탭을 쓸 수 없습니다")
        s = _strip_comment(raw)
        if s.strip() in ("", "---"):
            continue
        lines.append((n, len(s) - len(s.lstrip(" ")), s.strip()))
    if not lines:
        return {}
    value, idx = _parse_block(lines, 0, lines[0][1])
    if idx != len(lines):
        raise YamlError(f"{lines[idx][0]}행: 들여쓰기가 맞지 않습니다")
    return value


def _parse_block(lines, idx, indent):
    n, ind, text = lines[idx]
    if text.startswith("- ") or text == "-":
        return _parse_list(lines, idx, indent)
    return _parse_map(lines, idx, indent)


def _parse_map(lines, idx, indent):
    out = {}
    while idx < len(lines):
        n, ind, text = lines[idx]
        if ind < indent:
            break
        if ind > indent:
            raise YamlError(f"{n}행: 들여쓰기가 맞지 않습니다")
        if text.startswith("- "):
            raise YamlError(f"{n}행: 매핑 안에 리스트 항목이 섞였습니다")
        kv = _split_key(text, n)
        if kv is None:
            raise YamlError(f"{n}행: `키: 값` 형식이 아닙니다: {text}")
        key, rest = kv
        if key in out:
            raise YamlError(f"{n}행: 키 중복: {key}")
        idx += 1
        if rest == "":
            if idx < len(lines) and lines[idx][1] > indent:
                out[key], idx = _parse_block(lines, idx, lines[idx][1])
            elif idx < len(lines) and lines[idx][1] == indent and (lines[idx][2].startswith("- ") or lines[idx][2] == "-"):
                # 들여쓰기 없이 바로 이어지는 리스트 (key:\n- a)
                out[key], idx = _parse_list(lines, idx, indent)
            else:
                out[key] = None
        else:
            out[key] = _scalar(rest, n)
    return out, idx


def _parse_list(lines, idx, indent):
    out = []
    while idx < len(lines):
        n, ind, text = lines[idx]
        if ind < indent or not (text.startswith("- ") or text == "-"):
            if ind > indent:
                raise YamlError(f"{n}행: 들여쓰기가 맞지 않습니다")
            break
        if ind > indent:
            raise YamlError(f"{n}행: 들여쓰기가 맞지 않습니다")
        item = text[1:].strip()
        idx += 1
        if item == "":
            if idx < len(lines) and lines[idx][1] > indent:
                val, idx = _parse_block(lines, idx, lines[idx][1])
            else:
                val = None
            out.append(val)
            continue
        kv = None if item[0] in "[{'\"" else _split_key(item, n)
        if kv is not None:
            # "- key: value" 로 시작하는 블록 매핑 항목
            sub_indent = ind + 2
            synthetic = [(n, sub_indent, item)]
            j = idx
            while j < len(lines) and lines[j][1] >= sub_indent:
                synthetic.append(lines[j])
                j += 1
            val, k = _parse_map(synthetic, 0, sub_indent)
            if k != len(synthetic):
                raise YamlError(f"{synthetic[k][0]}행: 들여쓰기가 맞지 않습니다")
            out.append(val)
            idx = j
        else:
            out.append(_scalar(item, n))
    return out, idx


# ---------------------------------------------------------------------------
# 프로파일 스키마
# ---------------------------------------------------------------------------
NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
DEP_MANIFESTS = ("package.json", "pubspec.yaml", "pyproject.toml", "go.mod", "pom.xml",
                 "build.gradle", "build.gradle.kts", "requirements.txt")
ARTIFACT_TYPES = {"apk", "aab", "ipa"}


def _is_str_list(v):
    return isinstance(v, list) and all(isinstance(x, str) and x for x in v)


def validate_profile(p, fname: str) -> list[str]:
    errs = []
    if not isinstance(p, dict):
        return [f"{fname}: 최상위가 매핑이 아닙니다"]
    allowed = {"name", "description", "detect", "exclude_if", "exclude_paths",
               "semgrep", "sca", "artifact", "checklist", "checks"}
    for k in p:
        if k not in allowed:
            errs.append(f"{fname}: 알 수 없는 키 '{k}'")
    name = p.get("name")
    stem = os.path.splitext(os.path.basename(fname))[0]
    if not isinstance(name, str) or not NAME_RE.match(name):
        errs.append(f"{fname}: name 이 없거나 형식이 틀렸습니다")
    elif name != stem:
        errs.append(f"{fname}: name '{name}' 이 파일 이름과 다릅니다")
    if "description" in p and not isinstance(p["description"], str):
        errs.append(f"{fname}: description 은 문자열이어야 합니다")

    detect = p.get("detect")
    if not isinstance(detect, list) or not detect:
        errs.append(f"{fname}: detect 는 비어 있지 않은 리스트여야 합니다")
    else:
        for i, d in enumerate(detect):
            if isinstance(d, str):
                if not d:
                    errs.append(f"{fname}: detect[{i}] 가 비었습니다")
            elif isinstance(d, dict) and "glob" in d:
                # 형식 3: { glob, root_markers } — 깊은 근거 파일을 모듈 루트로 올려 잡는다
                if set(d) != {"glob", "root_markers"}:
                    errs.append(f"{fname}: detect[{i}] 는 glob·root_markers 두 키만 가집니다")
                elif not isinstance(d["glob"], str) or not d["glob"]:
                    errs.append(f"{fname}: detect[{i}].glob 은 문자열이어야 합니다")
                elif not _is_str_list(d["root_markers"]) or not d["root_markers"]:
                    errs.append(f"{fname}: detect[{i}].root_markers 는 비어 있지 않은 문자열 리스트여야 합니다")
            elif isinstance(d, dict):
                if set(d) != {"file", "has_dependency"}:
                    errs.append(f"{fname}: detect[{i}] 는 file·has_dependency 두 키만 가집니다")
                    continue
                if not isinstance(d["file"], str) or os.path.basename(d["file"]) not in DEP_MANIFESTS:
                    errs.append(f"{fname}: detect[{i}].file 은 {', '.join(DEP_MANIFESTS)} 중 하나여야 합니다")
                if not _is_str_list(d["has_dependency"]) or not d["has_dependency"]:
                    errs.append(f"{fname}: detect[{i}].has_dependency 는 문자열 리스트여야 합니다")
            else:
                errs.append(f"{fname}: detect[{i}] 는 glob 문자열, {{file, has_dependency}}, {{glob, root_markers}} 중 하나여야 합니다")

    for key in ("exclude_if", "exclude_paths"):
        if key in p and not (p[key] == [] or _is_str_list(p[key])):
            errs.append(f"{fname}: {key} 는 문자열 리스트여야 합니다")

    sg = p.get("semgrep")
    if not isinstance(sg, dict):
        errs.append(f"{fname}: semgrep 매핑이 필요합니다")
    else:
        for k in sg:
            if k not in ("rulesets", "custom"):
                errs.append(f"{fname}: semgrep 의 알 수 없는 키 '{k}'")
        if not _is_str_list(sg.get("rulesets")):
            errs.append(f"{fname}: semgrep.rulesets 는 문자열 리스트여야 합니다")
        if "custom" in sg and not (sg["custom"] == [] or _is_str_list(sg["custom"])):
            errs.append(f"{fname}: semgrep.custom 은 문자열 리스트여야 합니다")

    sca = p.get("sca")
    if not isinstance(sca, dict):
        errs.append(f"{fname}: sca 매핑이 필요합니다")
    else:
        for k in sca:
            if k not in ("lockfiles", "missing_lockfile_hint"):
                errs.append(f"{fname}: sca 의 알 수 없는 키 '{k}'")
        if not _is_str_list(sca.get("lockfiles")):
            errs.append(f"{fname}: sca.lockfiles 는 문자열 리스트여야 합니다")
        if "missing_lockfile_hint" in sca and not isinstance(sca["missing_lockfile_hint"], str):
            errs.append(f"{fname}: sca.missing_lockfile_hint 는 문자열이어야 합니다")

    art = p.get("artifact")
    if art is not None:
        if not isinstance(art, dict) or set(art) - {"types", "analyzer"}:
            errs.append(f"{fname}: artifact 는 types·analyzer 만 가집니다")
        else:
            if not _is_str_list(art.get("types")) or set(art["types"]) - ARTIFACT_TYPES:
                errs.append(f"{fname}: artifact.types 는 {sorted(ARTIFACT_TYPES)} 중에서 고릅니다")
            if art.get("analyzer") != "mobsf":
                errs.append(f"{fname}: artifact.analyzer 는 mobsf 만 지원합니다")

    if "checklist" in p and not isinstance(p["checklist"], str):
        errs.append(f"{fname}: checklist 는 문자열이어야 합니다")
    if "checks" in p and not (p["checks"] == [] or _is_str_list(p["checks"])):
        errs.append(f"{fname}: checks 는 문자열 리스트여야 합니다")
    return errs


def load_profiles(profile_dir: str) -> dict:
    profiles, errs = {}, []
    if not os.path.isdir(profile_dir):
        raise SystemExit(f"프로파일 폴더가 없습니다: {profile_dir}")
    for fn in sorted(os.listdir(profile_dir)):
        if not fn.endswith(".yaml"):
            continue
        path = os.path.join(profile_dir, fn)
        try:
            with open(path, encoding="utf-8-sig") as f:
                data = parse_yaml(f.read())
        except YamlError as e:
            errs.append(f"{fn}: {e}")
            continue
        errs.extend(validate_profile(data, fn))
        if isinstance(data, dict) and isinstance(data.get("name"), str):
            profiles[data["name"]] = data
    names = set(profiles)
    for name, p in profiles.items():
        for other in p.get("exclude_if") or []:
            if other not in names:
                errs.append(f"{name}.yaml: exclude_if 의 '{other}' 프로파일이 없습니다")
            if other == name:
                errs.append(f"{name}.yaml: exclude_if 에 자기 자신을 넣을 수 없습니다")
    if errs:
        raise ProfileError(errs)
    return profiles


class ProfileError(Exception):
    def __init__(self, errors):
        super().__init__("\n".join(errors))
        self.errors = errors


# ---------------------------------------------------------------------------
# glob
# ---------------------------------------------------------------------------
_GLOB_CACHE: dict = {}


def glob_to_regex(pattern: str):
    """`**` 는 0개 이상의 경로 구성요소, `*`·`?` 는 구성요소 안에서만 매칭."""
    if pattern in _GLOB_CACHE:
        return _GLOB_CACHE[pattern]
    i, out = 0, []
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c == "[":
            j = pattern.find("]", i + 1)
            if j < 0:
                out.append(re.escape(c))
                i += 1
            else:
                out.append(fnmatch.translate(pattern[i:j + 1])[4:-3])
                i = j + 1
        else:
            out.append(re.escape(c))
            i += 1
    rx = re.compile("^" + "".join(out) + "$")
    _GLOB_CACHE[pattern] = rx
    return rx


def glob_match(pattern: str, relpath: str) -> bool:
    return bool(glob_to_regex(pattern).match(relpath))


# ---------------------------------------------------------------------------
# 의존성 이름 추출
# ---------------------------------------------------------------------------
def _read(path, limit=2_000_000):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return ""


_PEP508_NAME = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")


def _norm_py(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _pyproject_deps(text: str) -> set:
    """[project] dependencies·optional-dependencies, [dependency-groups], [tool.poetry.*dependencies]."""
    names: set = set()
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        tomllib = None
    if tomllib is not None:
        try:
            data = tomllib.loads(text)
        except Exception:
            return names
        reqs = list(data.get("project", {}).get("dependencies", []) or [])
        for group in (data.get("project", {}).get("optional-dependencies", {}) or {}).values():
            reqs.extend(group or [])
        for group in (data.get("dependency-groups", {}) or {}).values():
            reqs.extend(x for x in (group or []) if isinstance(x, str))
        for r in reqs:
            if isinstance(r, str):
                m = _PEP508_NAME.match(r.strip())
                if m:
                    names.add(_norm_py(m.group(1)))
        poetry = data.get("tool", {}).get("poetry", {}) or {}
        tables = [poetry.get("dependencies", {}), poetry.get("dev-dependencies", {})]
        for grp in (poetry.get("group", {}) or {}).values():
            tables.append((grp or {}).get("dependencies", {}))
        for t in tables:
            if isinstance(t, dict):
                names.update(_norm_py(k) for k in t if k != "python")
        return names
    # tomllib 이 없는 Python(3.8~3.10): 배열 안 PEP 508 문자열과 poetry 테이블 키만 본다
    section = ""
    in_array = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("["):
            section = line.strip("[] ")
            in_array = False
            continue
        if section == "project" and re.match(r"^dependencies\s*=", line):
            in_array = True
        elif section in ("project.optional-dependencies", "dependency-groups") and "=" in line:
            in_array = True
        elif section.startswith("tool.poetry") and section.endswith("dependencies"):
            m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*=", line)
            if m and m.group(1) != "python":
                names.add(_norm_py(m.group(1)))
            continue
        if in_array:
            for s in re.findall(r"""["']([^"']+)["']""", line):
                m = _PEP508_NAME.match(s.strip())
                if m:
                    names.add(_norm_py(m.group(1)))
            if "]" in line:
                in_array = False
    return names


def dependency_names(path: str) -> set:
    base = os.path.basename(path)
    text = _read(path)
    names: set = set()
    if base == "package.json":
        try:
            data = json.loads(text)
        except ValueError:
            return names
        if isinstance(data, dict):
            for sec in ("dependencies", "devDependencies", "peerDependencies"):
                d = data.get(sec)
                if isinstance(d, dict):
                    names.update(d.keys())
    elif base == "pubspec.yaml":
        section, child_indent = None, None
        for line in text.splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if re.match(r"^\S", line):
                m = re.match(r"^(dependencies|dev_dependencies|dependency_overrides)\s*:", line)
                section, child_indent = (m.group(1) if m else None), None
            elif section:
                indent = len(line) - len(line.lstrip(" "))
                if child_indent is None:
                    child_indent = indent  # 섹션의 첫 하위 줄 들여쓰기를 기준으로 (2칸·4칸 모두)
                if indent == child_indent:
                    m = re.match(r"^\s*([A-Za-z0-9_]+)\s*:", line)
                    if m:
                        names.add(m.group(1))
    elif base == "requirements.txt":
        for line in text.splitlines():
            m = _PEP508_NAME.match(line.strip())
            if m and not line.strip().startswith(("#", "-")):
                names.add(_norm_py(m.group(1)))
    elif base == "pyproject.toml":
        names.update(_pyproject_deps(text))
    elif base == "go.mod":
        for m in re.finditer(r"(?m)^\s*(?:require\s+)?([a-z0-9.\-]+\.[a-z]+/[^\s]+)\s+v", text):
            mod = m.group(1)
            names.add(mod)
    elif base == "pom.xml":
        names.update(re.findall(r"<artifactId>\s*([^<\s]+)\s*</artifactId>", text))
        for g, a in re.findall(r"<groupId>\s*([^<\s]+)\s*</groupId>\s*<artifactId>\s*([^<\s]+)\s*</artifactId>", text):
            names.add(f"{g}:{a}")
    elif base in ("build.gradle", "build.gradle.kts"):
        for g, a in re.findall(r"""["']([\w.\-]+):([\w.\-]+)(?::[^"']*)?["']""", text):
            names.add(a)
            names.add(f"{g}:{a}")
        names.update(re.findall(r"""\bid\s*\(?\s*["']([\w.\-]+)["']""", text))
        names.update(re.findall(r"""apply\s+plugin\s*:\s*["']([\w.\-]+)["']""", text))
    return names


def _dep_matches(wanted: str, have: set) -> bool:
    if wanted in have:
        return True
    w = wanted.lower()
    for h in have:
        hl = h.lower()
        if hl == w:
            return True
        # go 모듈: github.com/gin-gonic/gin 은 github.com/gin-gonic/gin/v2 도 포함
        if "/" in w and hl.startswith(w + "/"):
            return True
    return False


# ---------------------------------------------------------------------------
# 감지
# ---------------------------------------------------------------------------
def walk_target(target: str):
    """대상 기준 상대 경로 목록 (파일과 디렉터리). 심볼릭 링크는 따라가지 않는다."""
    entries = []
    for root, dirs, files in os.walk(target, followlinks=False):
        rel_root = os.path.relpath(root, target)
        rel_root = "" if rel_root == "." else rel_root + "/"
        keep = []
        for d in sorted(dirs):
            entries.append(rel_root + d)
            if d in WALK_SKIP_DIRS or d.endswith(WALK_BUNDLE_SUFFIXES):
                continue
            if os.path.islink(os.path.join(root, d)):
                continue
            keep.append(d)
        dirs[:] = keep
        for fn in sorted(files):
            entries.append(rel_root + fn)
        if len(entries) > MAX_WALK_ENTRIES:
            raise SystemExit(f"대상 파일이 너무 많습니다 (>{MAX_WALK_ENTRIES}). 하위 프로젝트 경로를 지정하세요.")
    return entries


def _parent(rel: str) -> str:
    d = os.path.dirname(rel)
    return d if d else "."


def _resolve_root(target: str, rel_dir: str, markers) -> str:
    """rel_dir 에서 위로 올라가며 root_markers 중 하나가 있는 가장 가까운 폴더."""
    if not markers:
        return rel_dir
    cur = rel_dir
    while True:
        base = target if cur == "." else os.path.join(target, cur)
        if any(os.path.exists(os.path.join(base, m)) for m in markers):
            return cur
        if cur == ".":
            return rel_dir
        cur = _parent(cur)


def _is_under(child: str, parent: str) -> bool:
    if parent == ".":
        return True
    return child == parent or child.startswith(parent + "/")


def detect(target: str, profiles: dict, forced=None):
    """[(프로파일, 하위 경로)] — 하위 경로 안에서 제외할 더 깊은 경로는 detect_full 참고."""
    return [(n, r) for n, r, _ in detect_full(target, profiles, forced)]


def detect_full(target: str, profiles: dict, forced=None):
    """[(프로파일, 하위 경로, [제외 하위 경로])]

    제외 하위 경로: 상위 경로로 합쳐진 프로파일 안에 exclude_if 대상 프로파일이 더 깊은 경로에서
    감지된 경우 그 경로. 예) 루트 package.json 에 react 가 있는 모노레포의 web(.) 은
    RN 앱 apps/mobile 을 제외 경로로 가진다 (감지 규칙 4항: 하위 프로젝트 단위 적용).
    """
    target = os.path.realpath(target)
    if forced:
        unknown = [f for f in forced if f not in profiles]
        if unknown:
            raise SystemExit(f"알 수 없는 프로파일: {', '.join(unknown)} (사용 가능: {', '.join(sorted(profiles))})")
        seen, out = set(), []
        for f in forced:
            if f not in seen:
                seen.add(f)
                out.append((f, ".", []))
        return out

    entries = walk_target(target)
    dep_cache: dict = {}
    raw_hits: dict = {}  # profile -> set(root)  (병합 전)
    for name, p in profiles.items():
        roots = set()
        excludes = p.get("exclude_paths") or []
        for item in p["detect"]:
            if isinstance(item, str):
                pattern, markers = item, None
            elif "glob" in item:
                pattern, markers = item["glob"], item["root_markers"]
            else:
                pattern, markers = item["file"], None
            for rel in entries:
                if not glob_match(pattern, rel):
                    continue
                if any(glob_match(x, rel) or glob_match(x, rel + "/") for x in excludes):
                    continue
                full = os.path.join(target, rel)
                if isinstance(item, dict) and "has_dependency" in item:
                    if not os.path.isfile(full):
                        continue
                    if full not in dep_cache:
                        dep_cache[full] = dependency_names(full)
                    if not any(_dep_matches(w, dep_cache[full]) for w in item["has_dependency"]):
                        continue
                    root = _parent(rel)
                else:
                    # 번들형 디렉터리(.xcodeproj 등)·파일 모두 그 부모가 하위 프로젝트
                    root = _parent(rel)
                    if os.path.isdir(full) and not rel.endswith(WALK_BUNDLE_SUFFIXES):
                        root = rel
                    if markers:
                        root = _resolve_root(target, root, markers)
                roots.add(root)
        if roots:
            raw_hits[name] = roots

    # exclude_if (1차) — 같은 하위 프로젝트 경로에서 다른 프로파일이 감지되면 그 경로는 제외
    hits: dict = {}
    for name, roots in raw_hits.items():
        excl = profiles[name].get("exclude_if") or []
        kept = {r for r in roots if not any(r in raw_hits.get(o, set()) for o in excl)}
        if kept:
            hits[name] = kept

    result = []
    for name in sorted(hits):
        roots = hits[name]
        # 상위 경로가 이미 있으면 하위 경로는 합친다
        collapsed = sorted(r for r in roots if not any(o != r and _is_under(r, o) for o in roots))
        excl_names = profiles[name].get("exclude_if") or []
        for root in collapsed:
            # exclude_if (2차) — 합쳐진 상위 경로 안에서 exclude_if 대상이 감지된 더 깊은 경로
            inner = sorted({r for o in excl_names for r in raw_hits.get(o, set())
                            if r != root and _is_under(r, root)})
            result.append((name, root, inner))
    return result


def format_profile_label(name: str, root: str) -> str:
    return name if root == "." else f"{name}:{root}/"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="profiles.py")
    ap.add_argument("--dir", default=DEFAULT_PROFILE_DIR)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate")
    g = sub.add_parser("get")
    g.add_argument("name")
    d = sub.add_parser("detect")
    d.add_argument("target")
    d.add_argument("--profiles", default="")
    d.add_argument("--format", choices=("tsv", "json"), default="tsv")
    args = ap.parse_args(argv)

    try:
        profiles = load_profiles(args.dir)
    except ProfileError as e:
        for err in e.errors:
            print(f"프로파일 오류: {err}", file=sys.stderr)
        return 2

    if args.cmd == "validate":
        print(f"프로파일 {len(profiles)}개 정상: {', '.join(sorted(profiles))}")
        return 0
    if args.cmd == "get":
        if args.name not in profiles:
            print(f"알 수 없는 프로파일: {args.name}", file=sys.stderr)
            return 1
        print(json.dumps(profiles[args.name], ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "detect":
        if not os.path.isdir(args.target):
            print(f"디렉터리가 아닙니다: {args.target}", file=sys.stderr)
            return 1
        forced = [x.strip() for x in args.profiles.split(",") if x.strip()]
        found = detect_full(args.target, profiles, forced or None)
        if args.format == "json":
            print(json.dumps([{"profile": n, "path": r, "exclude": ex, "label": format_profile_label(n, r)}
                              for n, r, ex in found], ensure_ascii=False))
        else:
            for n, r, ex in found:
                print(f"{n}\t{r}\t{','.join(ex)}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
