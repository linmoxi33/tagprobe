"""tagprobe core: run one declarative probe spec against two source trees."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

RUNNER = r'''
import contextlib, importlib, io, json, sys

tree, spec_path = sys.argv[1], sys.argv[2]
sys.path.insert(0, tree)
if spec_path == "-":
    spec = json.loads(sys.stdin.read())
else:
    with open(spec_path, "r", encoding="utf-8") as fh:
        spec = json.load(fh)


def canon(value, depth=0):
    if depth > 8:
        return {"__truncated__": type(value).__name__}
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return {"__float__": repr(value)}
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return {"__seq__": type(value).__name__, "items": [canon(v, depth + 1) for v in value]}
    if isinstance(value, dict):
        items = sorted(([canon(k, depth + 1), canon(v, depth + 1)] for k, v in value.items()),
                       key=lambda kv: json.dumps(kv[0], sort_keys=True))
        return {"__map__": items}
    if isinstance(value, (set, frozenset)):
        return {"__set__": sorted(json.dumps(canon(v, depth + 1), sort_keys=True) for v in value)}
    return {"__repr__": repr(value), "__type__": type(value).__name__}


def norm_message(text):
    import re
    text = re.sub(r"0x[0-9a-fA-F]+", "0xADDR", str(text))
    text = re.sub(r"/tmp/[^\s:'\"]+", "/tmp/TMP", text)
    return text[:400]


results = []
for case in spec["calls"]:
    rec = {"id": case["id"]}
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            mod = importlib.import_module(case["module"])
            fn = getattr(mod, case["function"])
            value = fn(*case.get("args", []), **case.get("kwargs", {}))
        rec["outcome"] = "return"
        rec["value"] = canon(value)
    except AttributeError as exc:
        rec["outcome"] = "missing"
        rec["detail"] = norm_message(exc)
    except BaseException as exc:
        rec["outcome"] = "raise"
        rec["error"] = {"type": type(exc).__name__, "message": norm_message(exc)}
    rec["stdout"] = norm_message(buf.getvalue())
    results.append(rec)

json.dump({"results": results}, sys.stdout)
'''


class SpecError(ValueError):
    """Raised when the probe spec is malformed."""


def load_spec(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            spec = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise SpecError(f"cannot read spec {path}: {exc}") from exc
    calls = spec.get("calls")
    if not isinstance(calls, list) or not calls:
        raise SpecError("spec must contain a non-empty 'calls' list")
    seen = set()
    for index, call in enumerate(calls):
        if not isinstance(call, dict):
            raise SpecError(f"call #{index} must be an object")
        for key in ("id", "module", "function"):
            if not isinstance(call.get(key), str) or not call[key]:
                raise SpecError(f"call #{index} needs a non-empty string '{key}'")
        if call["id"] in seen:
            raise SpecError(f"duplicate call id {call['id']!r}")
        seen.add(call["id"])
        if "args" in call and not isinstance(call["args"], list):
            raise SpecError(f"call {call['id']!r}: 'args' must be a list")
        if "kwargs" in call and not isinstance(call["kwargs"], dict):
            raise SpecError(f"call {call['id']!r}: 'kwargs' must be an object")
    return spec


def run_tree(tree, spec, timeout=30.0):
    tree_path = Path(tree).resolve()
    if not tree_path.is_dir():
        raise SpecError(f"tree is not a directory: {tree}")
    payload = json.dumps(spec)
    proc = subprocess.run(
        [sys.executable, "-c", RUNNER, str(tree_path), "-"],
        input=payload,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, "PYTHONPATH": str(tree_path), "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if proc.returncode != 0:
        raise SpecError(f"runner failed for {tree}: {proc.stderr.strip()[:300]}")
    try:
        return {rec["id"]: rec for rec in json.loads(proc.stdout)["results"]}
    except (json.JSONDecodeError, KeyError) as exc:
        raise SpecError(f"runner produced invalid output for {tree}: {exc}") from exc


def _kinds(a, b):
    if a.get("outcome") == "missing" or b.get("outcome") == "missing":
        return ["missing_symbol"]
    kinds = []
    if a.get("outcome") != b.get("outcome"):
        kinds.append("outcome_drift")
    elif a.get("outcome") == "return":
        if json.dumps(a.get("value"), sort_keys=True) != json.dumps(b.get("value"), sort_keys=True):
            kinds.append("value_drift")
    else:
        ea, eb = a.get("error", {}), b.get("error", {})
        if ea.get("type") != eb.get("type"):
            kinds.append("error_type_drift")
        elif ea.get("message") != eb.get("message"):
            kinds.append("error_message_drift")
    if a.get("stdout") != b.get("stdout"):
        kinds.append("stdout_drift")
    return kinds


def compare(spec, results_a, results_b, label_a="a", label_b="b"):
    cases = []
    for call in spec["calls"]:
        cid = call["id"]
        a, b = results_a.get(cid, {"outcome": "missing"}), results_b.get(cid, {"outcome": "missing"})
        kinds = _kinds(a, b)
        cases.append({
            "id": cid,
            "module": call["module"],
            "function": call["function"],
            "status": "same" if not kinds else "drift",
            "kinds": kinds,
            label_a: a,
            label_b: b,
        })
    counts = {}
    for case in cases:
        for kind in case["kinds"]:
            counts[kind] = counts.get(kind, 0) + 1
    report = {
        "tool": "tagprobe",
        "cases": cases,
        "summary": {
            "total": len(cases),
            "same": sum(1 for c in cases if c["status"] == "same"),
            "drift": sum(1 for c in cases if c["status"] == "drift"),
            "kinds": dict(sorted(counts.items())),
        },
    }
    digest_src = json.dumps(
        [{"id": c["id"], "kinds": c["kinds"], "a": c[label_a], "b": c[label_b]} for c in cases],
        sort_keys=True,
    )
    report["digest"] = "sha256:" + hashlib.sha256(digest_src.encode()).hexdigest()
    return report


def run(a_dir, b_dir, spec, timeout=30.0):
    results_a = run_tree(a_dir, spec, timeout=timeout)
    results_b = run_tree(b_dir, spec, timeout=timeout)
    return compare(spec, results_a, results_b)
