# tagprobe

**Run one probe spec against two release tags of a Python package and diff what the code actually
returns** — values, exception types, exception messages and stdout — instead of diffing source text.
Needed now because release notes and semver say nothing about the thousands of pure-Python decisions
(router tables, path classifiers, policy resolvers) that change silently between tags.

Upstream: https://github.com/Tracer-Cloud/opensre

## What the upstream is, and what it cannot tell you

`opensre` is a 13k-star open-source SRE agent. Its CI selects which pytest targets to run for a
changed path through one pure function, `classify(changed)` in `infra/ci/test_scope_rules.py`
([v2026.6.25](https://github.com/Tracer-Cloud/opensre/blob/v2026.6.25/infra/ci/test_scope_rules.py#L72),
[v2026.6.26](https://github.com/Tracer-Cloud/opensre/blob/v2026.6.26/infra/ci/test_scope_rules.py#L74)).
The rule table is a module-level constant (`RULES`), and the only caller,
`run_test_scope.py`, evaluates the *working tree* it is standing in. Nothing in the repository can
answer "does the same changed path produce the same escalation decision at the previous tag?" — that
requires executing both revisions, which is what tagprobe does.

Evidence gathered at release time (2026-11-20) is recorded in `case-study/`; no issue link is claimed
because none was found in the open tracker that states this gap.

## The real measurement (not an example)

The same 64-path corpus was fed to `classify` from the two adjacent tags
`v2026.6.25` and `v2026.6.26` (files fetched with `gh api`, kept outside the repo):

```
$ python3 bin/tagprobe --a /tmp/tp/a --b /tmp/tp/b --spec case-study/opensre-probes.json \
      --report case-study/opensre-2026.6.25-vs-2026.6.26.json
17/64 cases identical, 47 drifted
digest sha256:30d081b474fce224adc1326cd4c8edc6d76cb1b85c1eb0b5c4022781d2e67ac8
```

* 47/64 paths (73%) produce a different `(escalate, areas, unmapped)` tuple across the two tags.
* 43 of those 47 also change diagnostic output (`stdout`), so a run that was silent at .25 can warn at .26.
* Concrete: `app/cli/main.py` → `(False, [], ["cli"])` at .25, `(True, [], [])` at .26 (no longer an
  unmapped path, now full escalation). `core/runtime/` → `(False, [], [])` at .25,
  `(False, [], ["core/runtime/"])` at .26.
* Replay is byte-deterministic: the digest is identical on a second run and from a copy of the trees.

**Honest limitation of this case study:** between the two tags the package layout was renamed
(`app/*` → `core/*`, `platform/*`, `integrations/*`), so part of the 47 is a rename, not a rule
rewrite. The tool measures *decision drift for the same input*, which is exactly what a CI cache or a
pinned path list would experience — but it does not attribute the drift to a cause.

## What it does / does not do

* Does: load a JSON probe spec, import every listed module from tree A and tree B in separate
  interpreters, call the listed functions with the listed arguments, canonicalise the results, and
  classify each pair as `same` or a drift of kind `value_drift`, `outcome_drift`, `error_type_drift`,
  `error_message_drift`, `stdout_drift`, `missing_symbol`.
* Does not: install packages, resolve third-party dependencies, generate probes automatically,
  attribute a drift to a commit, or prove that a drift is a bug.

## Install

Zero dependencies, Python 3.9+:

```bash
git clone git@github-linmoxi33:linmoxi33/tagprobe.git && cd tagprobe
python3 -m unittest discover -s tests -v     # 20 tests, all green
```

## Usage

```bash
python3 bin/tagprobe --a examples/in/a --b examples/in/b --spec examples/in/spec.json
python3 bin/tagprobe --a A --b B --spec spec.json --json --only-drift
python3 bin/tagprobe --a A --b B --spec spec.json --report out.json
```

Probe spec:

```json
{"calls": [{"id": "div-zero", "module": "calc", "function": "div", "args": [1, 0]}]}
```

`--json` prints the full report (parseable with `json.load`); `--only-drift` trims identical cases;
`--report FILE` always writes the untrimmed report.

| exit code | meaning |
|---|---|
| 0 | every probe behaved identically |
| 1 | at least one drift was found |
| 2 | usage or input error (bad spec, missing tree, runner failure) |

## 本轮创新

首次把同一份变更路径语料喂给两个真实 release tag 的 CI 决策函数并比较**运行时返回值**：台账里的
schema/契约差分只比声明层，这里测出 opensre 47/64 条决策漂移、43 条诊断输出漂移，且报告可逐字节复现
（digest 两次一致）。不是换皮审计：结论只能靠真实执行两个 tag 得到。

## Limitations

* Only pure-Python, importable-without-third-party-deps modules can be probed; the runner has a
  per-tree timeout and no network isolation beyond the process boundary.
* Exception messages are normalised (`0xADDR`, `/tmp/TMP`) before comparison; a message change that
  is only a path or address is therefore *not* reported.
* `missing_symbol` cannot tell "removed in B" from "renamed in B".
* The upstream `classify` sample is Apache-2.0 and is not vendored here; `case-study/` holds only the
  probe corpus and the produced report.

MIT licensed. The example trees under `examples/in/` are synthetic fixtures written for this repo.
