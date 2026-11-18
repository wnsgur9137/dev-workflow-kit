"""베이스라인 비교 — 같은 종류·같은 대상의 직전 실행과 결과를 비교해 신규·유지·해결을 표시한다 (P4, 리포트 포맷).

거짓 '해결'·'신규'를 줄이는 규칙 (PR #40 리뷰 W1~W3):
- 두 실행 모두에서 **완전했던 단위**(status.tsv 의 도구가 ok, 결과 파일 해석 성공, 부분 오류·결과 상한 없음 — complete_units)만 비교한다.
- 단위마다 **비교 키**(id 계산 버전·플러그인 버전·이미지 digest·Semgrep 규칙 커밋·프로파일)를 남기고, 키가 다르면 비교하지 않는다
  — 규칙·도구·파서가 바뀌면 코드와 무관하게 결과가 생기거나 사라진다.
- id 에 줄 번호가 들어 있어 위치만 바뀐 결과는 id 가 달라진다. 정확히 같은 id 를 맞춘 뒤 남은 신규·해결을
  (단위, 규칙, 파일, 패키지)별로 짝지어 '위치 이동'으로 센다.
이전 실행의 findings.json 은 도구가 대상에서 뽑은 데이터가 든 파일이다 — 형식을 검증하고 짧은 식별자만 꺼낸다.
"""

import hashlib
import json
import os
import stat

import cleanup_reports as _runs

RESOLVED_MAX = 50
SEVERITIES = ("critical", "high", "medium", "low", "info")
MAX_FILE = 64 * 1024 * 1024
ID_VERSION = 1      # normalize.finding_id 의 입력이 바뀌면 올린다 — 다르면 비교하지 않는다 (리뷰 S6)
# 단위별 파서 버전 — 파서가 결과를 거르는 방식이 바뀌면 그 단위만 올린다. 플러그인 버전은 툴킷 자체 검사(checks)에만 넣는다
# (모든 단위에 넣으면 업그레이드마다 비교가 통째로 끊긴다, 2차 리뷰 S2)
PARSER_VERSION = {"semgrep": 1, "gitleaks-git": 1, "gitleaks-dir": 1, "osv-scanner": 1, "checks": 1, "mobsf": 1,
                  "gitleaks-artifact": 1, "zap": 1}
# 위치 이동으로 짝짓지 않는 단위 — 시크릿은 위치가 바뀐 것보다 새로 들어온 것이 위험하다 (2차 리뷰 S1)
NO_MOVE = {"gitleaks-git", "gitleaks-dir", "gitleaks-artifact"}
PARTIAL_PATHS_MAX = 2000
# 단위 → 이미지 이름(images.lock). checks 는 툴킷 자체 검사라 플러그인 버전이 곧 도구 버전이다
UNIT_TOOL = {"semgrep": "semgrep", "gitleaks-git": "gitleaks", "gitleaks-dir": "gitleaks", "osv-scanner": "osv-scanner",
             "checks": None, "mobsf": "mobsf", "gitleaks-artifact": "gitleaks", "zap": "zap"}


def unit_keys(units, tools, rules, profiles, plugin_version):
    """단위별 비교 키. OSV DB 날짜는 넣지 않는다 — DB 갱신으로 새 취약점이 '신규'로 보이는 것은 의도한 동작이다."""
    digest = {t.get("name"): t.get("digest") for t in tools or [] if isinstance(t, dict)}
    commits = sorted(f"{r.get('name')}@{r.get('commit')}" for r in rules or [] if isinstance(r, dict))
    out = {}
    for u in units:
        parts = [f"id={ID_VERSION}", f"parser={PARSER_VERSION.get(u)}"]
        if u == "checks":
            parts.append(f"plugin={plugin_version}")
        if UNIT_TOOL.get(u):
            parts.append(f"image={digest.get(UNIT_TOOL[u])}")
        if u in ("semgrep", "checks"):
            parts.append("profiles=" + ",".join(sorted(str(p) for p in profiles or [])))
        if u == "semgrep":
            parts += commits
        out[u] = hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]
    return out


def _load(path):
    """링크·큰 파일은 읽지 않는다 — 연 파일 자체를 확인한다 (리뷰 N2)."""
    try:
        # O_NONBLOCK: FIFO 를 열 때 쓰는 쪽을 기다리며 멈추지 않게 (2차 리뷰 S4). 정규 파일에는 영향이 없다
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_FILE:
            return None
        with os.fdopen(fd, encoding="utf-8") as f:
            fd = None
            return json.load(f)
    except (OSError, ValueError):
        return None
    finally:
        if fd is not None:
            os.close(fd)


def _order(name):
    """같은 초의 접미사(-2 … -1000)를 숫자로 비교한다 ('-10' 이 '-9' 보다 뒤, 리뷰 N1)."""
    t = _runs.run_time(name)
    parts = name.split("-")
    return (t, int(parts[3]) if len(parts) > 3 else 1)


def find_previous(run_dir, kind, target):
    """(run_id, meta, findings) — 같은 종류·대상의 가장 최근 이전 실행. 없으면 None.
    meta 에 complete_units·unit_keys 가 없으면(이전 버전 리포트) findings 는 None 으로 돌려준다."""
    reports, me = os.path.split(os.path.normpath(run_dir))
    if _runs.run_time(me) is None:
        return None
    try:
        names = os.listdir(reports)
    except OSError:
        return None
    mine = _order(me)
    cands = sorted((n for n in names if _runs.run_time(n) is not None and n.split("-")[2] == kind and _order(n) < mine),
                   key=_order)
    for name in reversed(cands):
        d = os.path.join(reports, name)
        try:
            if not stat.S_ISDIR(os.lstat(d).st_mode):
                continue
        except OSError:
            continue
        meta = _load(os.path.join(d, "meta.json"))
        if not isinstance(meta, dict) or meta.get("kind") != kind or meta.get("target") != target:
            continue
        if not isinstance(meta.get("complete_units"), list) or not isinstance(meta.get("unit_keys"), dict):
            return name, meta, None
        rep = _load(os.path.join(d, "findings.json"))
        if not isinstance(rep, dict) or not isinstance(rep.get("findings"), list):
            return name, meta, None
        return name, meta, rep["findings"]
    return None


def _strs(v, limit=None):
    """이전 meta 의 목록 값 — 리스트의 문자열 원소만 받는다 (형식이 다르면 빈 목록, 3차 리뷰 S3)."""
    if not isinstance(v, list):
        return []
    out = [x for x in v if isinstance(x, str)]
    return out if limit is None else out[:limit + 1]


def _no_move(f):
    """짝짓지 않는 결과 — gitleaks 단위와, 다른 도구(semgrep 의 시크릿 규칙 등)의 시크릿 분류 (3차 리뷰 S1)."""
    return f.get("unit") in NO_MOVE or f.get("category") == "secret"


def _brief(f):
    loc = f.get("location") if isinstance(f.get("location"), dict) else {}
    sev = f.get("severity") if f.get("severity") in SEVERITIES else "info"
    return {"id": str(f.get("id", ""))[:64], "severity": sev, "tool": str(f.get("tool", ""))[:40],
            "rule_id": str(f.get("rule_id", ""))[:200],
            "location": {k: (str(loc[k])[:300] if loc.get(k) is not None else None) for k in ("file", "line", "url", "package")}}


def _move_key(f):
    loc = f.get("location") if isinstance(f.get("location"), dict) else {}
    return (f.get("unit"), str(f.get("rule_id")), str(loc.get("file") or loc.get("url")), str(loc.get("package")))


def compare(findings, complete_units, keys, prev, all_units=(), partial_paths=None):
    """findings 에 'baseline'(new|existing|moved|not-compared)을 붙이고 meta 용 요약을 돌려준다.
    all_units: 이번 실행 status 의 도구 전체 — 양쪽 모두 불완전한 도구도 '비교하지 않음'으로 보이게 (2차 리뷰 W1)
    partial_paths: {단위: [파일]} — 그 파일만 점검하지 못한 단위. 단위는 비교하되 두 실행 중 어느 쪽에서든 오류가 난
                   파일의 결과는 비교하지 않는다 (파싱 못 하는 파일이 늘 있어도 나머지는 비교, 2차 리뷰 W2)"""
    def none(run_id, reason):
        for f in findings:
            f["baseline"] = "not-compared"
        return {"run_id": run_id, "reason": reason}

    if prev is None:
        return none(None, "같은 대상의 이전 실행이 없습니다(또는 보관 기간이 지나 지워졌습니다)")
    name, meta, prev_findings = prev
    if prev_findings is None:
        return none(name, "이전 실행이 비교 정보가 없는 이전 버전 리포트이거나 읽을 수 없습니다")
    prev_complete = {u for u in _strs(meta["complete_units"]) if u in UNIT_TOOL}
    both = set(complete_units) & prev_complete
    changed = {u for u in both if meta["unit_keys"].get(u) != keys.get(u)}
    comparable = both - changed
    prev_partial = meta.get("partial_paths") if isinstance(meta.get("partial_paths"), dict) else {}
    skip = {}
    for u in sorted(comparable):
        old = _strs(prev_partial.get(u), PARTIAL_PATHS_MAX)
        if len(old) > PARTIAL_PATHS_MAX:       # 이전 기록이 비정상적으로 크면 그 단위는 비교하지 않는다
            comparable.discard(u)
            continue
        skip[u] = set(_strs((partial_paths or {}).get(u))) | set(old)

    def file_of(f):
        loc = f.get("location") if isinstance(f.get("location"), dict) else {}
        return str(loc.get("file"))

    def in_scope(f):
        u = f.get("unit")
        return isinstance(u, str) and u in comparable and file_of(f) not in skip.get(u, ())

    prev_ids = {}
    for f in prev_findings:
        if isinstance(f, dict) and in_scope(f) and isinstance(f.get("id"), str):
            prev_ids.setdefault(f["id"], f)
    cur_ids, new = set(), []
    for f in findings:
        if in_scope(f):
            cur_ids.add(f["id"])
            if f["id"] in prev_ids:
                f["baseline"] = "existing"
            else:
                f["baseline"] = "new"
                new.append(f)
        else:
            f["baseline"] = "not-compared"
    gone = [f for i, f in prev_ids.items() if i not in cur_ids]
    # 위치만 바뀐 결과 — 같은 (단위, 규칙, 파일, 패키지)에 남은 신규와 해결을 개수만큼 짝짓는다 (리뷰 W2). 시크릿은 짝짓지 않는다
    pool = {}
    for f in gone:
        if not _no_move(f):
            pool.setdefault(_move_key(f), []).append(f)
    moved_away = set()
    for f in new:
        bucket = None if _no_move(f) else pool.get(_move_key(f))
        if bucket:
            old = bucket.pop()
            moved_away.add(id(old))
            f["baseline"] = "moved"
            line = (old.get("location") or {}).get("line") if isinstance(old.get("location"), dict) else None
            if isinstance(line, int):
                f["baseline_prev_line"] = line
    gone = [f for f in gone if id(f) not in moved_away]
    counts = {k: sum(1 for f in findings if f["baseline"] == k) for k in ("new", "existing", "moved", "not-compared")}
    order = {s: i for i, s in enumerate(SEVERITIES)}
    # 짝짓지 않은 시크릿은 줄만 바뀌어도 신규+해결로 남는다 — 같은 (단위, 규칙, 파일)에 신규가 있으면 해결 쪽에 표시한다 (3차 리뷰 S4)
    new_keys = {_move_key(f) for f in findings if f["baseline"] == "new"}
    briefs = []
    for f in gone:
        b = _brief(f)
        if _move_key(f) in new_keys:
            b["maybe_moved"] = True
        briefs.append(b)
    resolved = sorted(briefs, key=lambda b: (order[b["severity"]], b["tool"], b["location"].get("file") or ""))
    status_rows = meta.get("tool_status") if isinstance(meta.get("tool_status"), list) else []
    prev_status = {r.get("tool") for r in status_rows if isinstance(r, dict) and isinstance(r.get("tool"), str)}
    units = ({u for u in all_units if u in UNIT_TOOL} | {u for u in prev_status if u in UNIT_TOOL}
             | set(complete_units) | prev_complete)
    return {"run_id": name, "compared_units": sorted(comparable), "changed_units": sorted(changed),
            "not_compared_units": sorted(units - comparable - changed),
            "partial_units": {u: len(p) for u, p in sorted(skip.items()) if p},
            "new": counts["new"], "existing": counts["existing"],
            "moved": counts["moved"], "not_compared": counts["not-compared"],
            "resolved": len(resolved), "resolved_items": resolved[:RESOLVED_MAX]}
