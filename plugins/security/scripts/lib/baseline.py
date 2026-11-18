"""베이스라인 비교 — 같은 종류·같은 대상의 직전 실행과 결과를 비교해 신규·유지·해결을 표시한다 (P4, 리포트 포맷).

도구가 실패하면 결과가 비어 '해결'로 보이므로, 두 실행 모두에서 **완전했던 단위**(status.tsv 의 도구가 ok 이고
결과 파일을 해석했음 — meta.json 의 complete_units)만 비교한다. 나머지 단위의 결과는 'not-compared' 로 둔다.
이전 실행의 findings.json 은 도구가 대상에서 뽑은 데이터가 든 파일이다 — 형식을 검증하고 짧은 식별자만 꺼낸다.
"""

import json
import os
import stat

import cleanup_reports as _runs

RESOLVED_MAX = 50
SEVERITIES = ("critical", "high", "medium", "low", "info")
MAX_FILE = 64 * 1024 * 1024


def _load(path):
    try:
        st = os.lstat(path)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_FILE:
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def find_previous(run_dir, kind, target):
    """(run_id, meta, findings) — 같은 종류·대상의 가장 최근 이전 실행. 없으면 None.
    meta 에 complete_units 가 없으면(이전 버전 리포트) findings 는 None 으로 돌려준다."""
    reports, me = os.path.split(os.path.normpath(run_dir))
    try:
        names = os.listdir(reports)
    except OSError:
        return None
    cands = sorted(n for n in names if n != me and n < me and _runs.run_time(n) is not None
                   and (n.split("-")[2] == kind))
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
        if not isinstance(meta.get("complete_units"), list):
            return name, meta, None
        rep = _load(os.path.join(d, "findings.json"))
        if not isinstance(rep, dict) or not isinstance(rep.get("findings"), list):
            return name, meta, None
        return name, meta, rep["findings"]
    return None


def _brief(f):
    loc = f.get("location") if isinstance(f.get("location"), dict) else {}
    sev = f.get("severity") if f.get("severity") in SEVERITIES else "info"
    return {"id": str(f.get("id", ""))[:64], "severity": sev, "tool": str(f.get("tool", ""))[:40],
            "rule_id": str(f.get("rule_id", ""))[:200],
            "location": {k: (str(loc[k])[:300] if loc.get(k) is not None else None) for k in ("file", "line", "url", "package")}}


def compare(findings, complete_units, prev):
    """findings 에 'baseline' 을 붙이고 meta 용 요약을 돌려준다. prev = find_previous(...) 결과."""
    if prev is None:
        for f in findings:
            f["baseline"] = "not-compared"
        return {"run_id": None, "reason": "같은 대상의 이전 실행이 없습니다(또는 보관 기간이 지나 지워졌습니다)"}
    name, meta, prev_findings = prev
    if prev_findings is None:
        for f in findings:
            f["baseline"] = "not-compared"
        return {"run_id": name, "reason": "이전 실행이 비교 정보가 없는 이전 버전 리포트이거나 읽을 수 없습니다"}
    comparable = set(complete_units) & {u for u in meta["complete_units"] if isinstance(u, str)}
    prev_ids = {}
    for f in prev_findings:
        if isinstance(f, dict) and f.get("unit") in comparable and isinstance(f.get("id"), str):
            prev_ids.setdefault(f["id"], f)
    counts = {"new": 0, "existing": 0, "not-compared": 0}
    cur_ids = set()
    for f in findings:
        if f.get("unit") in comparable:
            f["baseline"] = "existing" if f["id"] in prev_ids else "new"
            cur_ids.add(f["id"])
        else:
            f["baseline"] = "not-compared"
        counts[f["baseline"]] += 1
    order = {s: i for i, s in enumerate(SEVERITIES)}
    resolved = sorted((_brief(f) for i, f in prev_ids.items() if i not in cur_ids),
                      key=lambda b: (order[b["severity"]], b["tool"], b["location"].get("file") or ""))
    units = set(complete_units) | {u for u in meta["complete_units"] if isinstance(u, str)}
    return {"run_id": name, "compared_units": sorted(comparable), "not_compared_units": sorted(units - comparable),
            "new": counts["new"], "existing": counts["existing"], "not_compared": counts["not-compared"],
            "resolved": len(resolved), "resolved_items": resolved[:RESOLVED_MAX]}
