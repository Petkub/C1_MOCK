#!/usr/bin/env python3
"""
Regression tests for the POSN Practice Judge.

  python3 tests/run_regression.py          run everything (exit code 0 = all passed)

1. Every sample in samples/expected.json is judged and must get its verdict (and score, when given).
   Verdict = CE if it does not compile, else the first non-AC verdict, else AC.
2. The judge's command line is run like a student would (repo layout, --ascii, --list).
3. A student package is built with tools/build_dist.py and judged from inside Mock_1.
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = os.path.join(REPO, "core")
SAMPLES = os.path.join(REPO, "samples")
JUDGE = os.path.join(CORE, "judge.py")
sys.path.insert(0, CORE)
sys.dont_write_bytecode = True     # no __pycache__ inside core/ (it ships to students)
import judge  # noqa: E402

FAILED = []


def check(ok, name, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else "   " + detail))
    if not ok:
        FAILED.append(name)


# ----------------------------------------------------------------------------- 1. verdicts
def judge_sample(src, problem, full):
    """(verdict, score) of src on problem K-P; full = run every test (needed for the score)."""
    meta = judge.load_meta()
    pdir, num = judge.find_problem(problem, meta)
    if not pdir:
        return "no such problem " + problem, 0
    judge.set_sample_count(meta, num)
    st = judge.Style(color=False, ascii_only=True, tty=False)
    tmp = tempfile.mkdtemp(prefix="judge_")
    try:
        exe, _, _ = judge.compile_source(src, tmp)
        if not exe:
            return "CE", 0
        with contextlib.redirect_stdout(io.StringIO()):
            results, _, total = judge.run_tests(exe, pdir, st, 1.0, 0, not full, quiet=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    bad = [v for _, v, _ in results if v != "AC"]
    return (bad[0] if bad else "AC"), judge.compute_score(results, total)[0]


def test_samples():
    print("Samples")
    with open(os.path.join(SAMPLES, "expected.json"), encoding="utf-8") as f:
        expected = json.load(f)
    for name, want in expected.items():
        full = "score" in want
        verdict, score = judge_sample(os.path.join(SAMPLES, name), want["problem"], full)
        ok = verdict == want["verdict"] and (not full or score == want["score"])
        got = verdict + (f" {score}" if full else "")
        check(ok, f"{name:<28} {want['verdict']}", f"got {got}")


# ----------------------------------------------------------------------------- 2. command line
def run_judge(args, cwd=REPO, judge_path=JUDGE):
    """Run judge.py like a student. Returns (exit code, output text, output is plain ASCII)."""
    p = subprocess.run([sys.executable, judge_path] + args, cwd=cwd,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stdout.isascii()


def test_cli():
    print("Command line")
    ok_cpp = os.path.join(SAMPLES, "batch", "primes_ok.cpp")
    wa_cpp = os.path.join(SAMPLES, "batch", "primes_offbyone.cpp")
    code, out, _ = run_judge([ok_cpp, "1-3", "--no-color"])
    check(code == 0 and "ACCEPTED" in out, "judge.py primes_ok.cpp 1-3", f"exit {code}\n{out}")
    code, out, plain = run_judge([wa_cpp, "1-3", "--ascii", "--no-color"])
    check(code == 0 and "First failure" in out and plain, "judge.py --ascii shows the failure, ASCII only",
          f"exit {code}, ascii={plain}\n{out}")
    code, out, plain = run_judge(["--list", "--ascii"])
    check(code == 0 and "Set 15" in out and plain, "judge.py --list --ascii", f"exit {code}\n{out}")
    code, out, _ = run_judge(["--tl", "abc"])
    check(code == 2 and "--tl must be" in out, "judge.py --tl abc is rejected", f"exit {code}\n{out}")


# ----------------------------------------------------------------------------- 3. student package
def test_student_package():
    print("Student package")
    tmp = tempfile.mkdtemp(prefix="judge_dist_")
    try:
        p = subprocess.run([sys.executable, os.path.join(REPO, "tools", "build_dist.py"), "--out", tmp, "--no-zip"],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        check(p.returncode == 0, "build_dist.py", p.stdout.decode("utf-8", "replace"))
        if p.returncode != 0:
            return
        root = os.path.join(tmp, "Mock_Test")
        set1 = os.path.join(root, "Mock_1")
        templates = [os.path.join(set1, f"{i}.cpp") for i in range(1, 9)]
        check(all(judge.is_template(t) for t in templates), "Mock_1/1.cpp ... 8.cpp are empty templates")
        shutil.copy(os.path.join(SAMPLES, "batch", "primes_ok.cpp"), os.path.join(set1, "3.cpp"))
        student_judge = os.path.join(os.pardir, "Judge", "judge.py")
        code, out, _ = run_judge(["3", "--no-color"], cwd=set1, judge_path=student_judge)
        check(code == 0 and "ACCEPTED" in out, "inside Mock_1: judge.py 3", f"exit {code}\n{out}")
        code, out, _ = run_judge(["--no-color"], cwd=set1, judge_path=student_judge)
        check(code == 0 and "Total" in out and "Problem 3" in out, "inside Mock_1: judge.py (whole set)",
              f"exit {code}\n{out}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    if not shutil.which("g++"):
        print("g++ not found: the regression tests need a C++ compiler in PATH.")
        return 1
    test_samples()
    test_cli()
    test_student_package()
    print()
    if FAILED:
        print(f"{len(FAILED)} FAILED: " + ", ".join(FAILED))
        return 1
    print("All regression tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
