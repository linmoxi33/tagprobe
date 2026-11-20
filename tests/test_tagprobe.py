"""Behaviour tests for tagprobe. Fixtures are the two example trees."""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tagprobe.cli import main  # noqa: E402
from tagprobe.core import SpecError, load_spec, run  # noqa: E402

A = ROOT / "examples" / "in" / "a"
B = ROOT / "examples" / "in" / "b"
SPEC = ROOT / "examples" / "in" / "spec.json"
TMP = Path(tempfile.mkdtemp(prefix="tagprobe-tests-"))


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def write_spec(name, calls):
    path = TMP / name
    path.write_text(json.dumps({"calls": calls}), encoding="utf-8")
    return path


def run_cli(argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main(argv)
    return code, buf.getvalue()


class SpecValidationTests(unittest.TestCase):
    def test_missing_calls_rejected(self):
        path = TMP / "empty.json"
        path.write_text("{}", encoding="utf-8")
        with self.assertRaises(SpecError):
            load_spec(path)

    def test_duplicate_ids_rejected(self):
        call = {"id": "x", "module": "calc", "function": "add", "args": [1, 2]}
        path = write_spec("dup.json", [call, call])
        with self.assertRaises(SpecError):
            load_spec(path)

    def test_non_list_args_rejected(self):
        path = write_spec("badargs.json", [{"id": "x", "module": "calc", "function": "add", "args": 1}])
        with self.assertRaises(SpecError):
            load_spec(path)

    def test_missing_tree_rejected(self):
        spec = load_spec(SPEC)
        with self.assertRaises(SpecError):
            run(str(TMP / "nope"), str(B), spec)


class BehaviourTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = load_spec(SPEC)
        cls.report = run(str(A), str(B), cls.spec)

    def case(self, cid):
        return next(c for c in self.report["cases"] if c["id"] == cid)

    def test_identical_call_is_same(self):
        self.assertEqual(self.case("add-int")["status"], "same")

    def test_return_value_drift(self):
        case = self.case("scale-int")
        self.assertEqual(case["kinds"], ["value_drift"])
        self.assertEqual(case["a"]["value"], 14)
        self.assertIn("21", json.dumps(case["b"]["value"]))

    def test_exception_type_drift(self):
        case = self.case("div-zero")
        self.assertEqual(case["kinds"], ["error_type_drift"])
        self.assertEqual(case["a"]["error"]["type"], "ZeroDivisionError")
        self.assertEqual(case["b"]["error"]["type"], "ValueError")

    def test_exception_message_drift(self):
        case = self.case("parse-bad")
        self.assertEqual(case["kinds"], ["error_message_drift"])
        self.assertEqual(case["a"]["error"]["type"], case["b"]["error"]["type"])

    def test_missing_symbol_both_directions(self):
        self.assertEqual(self.case("only-a")["kinds"], ["missing_symbol"])
        self.assertEqual(self.case("only-b")["kinds"], ["missing_symbol"])

    def test_stdout_drift(self):
        case = self.case("noisy-stdout")
        self.assertIn("stdout_drift", case["kinds"])
        self.assertIn("processing", case["a"]["stdout"])
        self.assertEqual(case["b"]["stdout"], "")

    def test_dict_payload_drift(self):
        self.assertEqual(self.case("tag-dict")["kinds"], ["value_drift"])

    def test_summary_matches_cases(self):
        summary = self.report["summary"]
        self.assertEqual(summary["total"], len(self.report["cases"]))
        self.assertEqual(summary["same"] + summary["drift"], summary["total"])
        self.assertEqual(summary["drift"], 7)

    def test_digest_is_stable_across_directories(self):
        clone_a, clone_b = TMP / "ca", TMP / "cb"
        shutil.copytree(A, clone_a)
        shutil.copytree(B, clone_b)
        again = run(str(clone_a), str(clone_b), self.spec)
        self.assertEqual(again["digest"], self.report["digest"])


class CliTests(unittest.TestCase):
    def test_exit_1_on_drift(self):
        code, out = run_cli(["--a", str(A), "--b", str(B), "--spec", str(SPEC)])
        self.assertEqual(code, 1)
        self.assertIn("7/8 cases identical, 1 drifted".replace("1 drifted", "7 drifted") if False else "7 drifted", out)

    def test_exit_0_when_identical(self):
        spec = write_spec("same.json", [{"id": "add", "module": "calc", "function": "add", "args": [1, 2]}])
        code, _ = run_cli(["--a", str(A), "--b", str(A), "--spec", str(spec)])
        self.assertEqual(code, 0)

    def test_exit_2_on_bad_spec(self):
        bad = TMP / "broken.json"
        bad.write_text("{not json", encoding="utf-8")
        err = io.StringIO()
        from contextlib import redirect_stderr
        with redirect_stderr(err):
            code, _ = run_cli(["--a", str(A), "--b", str(B), "--spec", str(bad)])
        self.assertEqual(code, 2)
        self.assertIn("tagprobe:", err.getvalue())

    def test_json_output_is_parseable(self):
        code, out = run_cli(["--a", str(A), "--b", str(B), "--spec", str(SPEC), "--json"])
        self.assertEqual(code, 1)
        payload = json.loads(out)
        self.assertEqual(payload["tool"], "tagprobe")
        self.assertTrue(payload["digest"].startswith("sha256:"))

    def test_only_drift_filters_same_cases(self):
        code, out = run_cli(["--a", str(A), "--b", str(B), "--spec", str(SPEC), "--json", "--only-drift"])
        payload = json.loads(out)
        self.assertEqual(len(payload["cases"]), 7)
        self.assertTrue(all(c["status"] == "drift" for c in payload["cases"]))

    def test_report_file_written(self):
        target = TMP / "report.json"
        run_cli(["--a", str(A), "--b", str(B), "--spec", str(SPEC), "--report", str(target)])
        self.assertTrue(json.loads(target.read_text(encoding="utf-8"))["summary"]["total"] == 8)

    def test_bin_launcher_runs_from_checkout(self):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "bin" / "tagprobe"), "--a", str(A), "--b", str(B), "--spec", str(SPEC), "--json"],
            capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(json.loads(proc.stdout)["summary"]["drift"], 7)


if __name__ == "__main__":
    unittest.main()
