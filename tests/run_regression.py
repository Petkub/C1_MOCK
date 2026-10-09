#!/usr/bin/env python3
"""
Regression tests for the POSN Practice Judge.

  python3 tests/run_regression.py          run everything (exit code 0 = all passed)

1. Every sample in samples/expected.json is judged and must get its verdict (and score, when given).
   Verdict = CE if it does not compile, else the first non-AC verdict, else AC.
2. The judge's command line is run like a student would (repo layout, --ascii, --list).
3. A student package is built with tools/build_dist.py and judged from inside Mock_1.
4. Self-update: a local HTTP server serves a modified copy of the repo as v9.9; a package must update itself
   (hashes, backups, restart, create-only set files), and must refuse bad hashes, bad paths and no network.
5. manifest.json is up to date.
"""
import contextlib
import functools
import glob
import hashlib
import http.server
import socket
import threading
import time
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
os.environ["JUDGE_NO_UPDATE"] = "1"       # the judge never contacts GitHub during the tests


def check(ok, name, detail=""):
    detail = detail.encode("ascii", "backslashreplace").decode("ascii")    # Windows consoles: cp1252
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


# ----------------------------------------------------------------------------- 4. self-update
def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def serve(folder):
    """Serve folder over HTTP on a free port of this computer (stands in for raw.githubusercontent.com)."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=folder)
    handler.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_repo2(tmp, version, marker):
    """A copy of the repo with a new VERSION, a marker line in judge.py and a changed README, manifest rebuilt."""
    repo2 = os.path.join(tmp, "repo2")
    if os.path.exists(repo2):
        shutil.rmtree(repo2)
    shutil.copytree(REPO, repo2, ignore=shutil.ignore_patterns(".git", "dist", "__pycache__"))
    with open(os.path.join(repo2, "VERSION"), "w") as f:
        f.write(version + "\n")
    with open(os.path.join(repo2, "core", "judge.py"), "a") as f:
        f.write(f"\n# {marker}\n")
    with open(os.path.join(repo2, "core", "README.txt"), "a") as f:
        f.write(f"{marker}\n")
    rebuild_manifest(repo2)
    return repo2


def rebuild_manifest(repo2):
    subprocess.run([sys.executable, os.path.join(repo2, "tools", "build_manifest.py")], check=True,
                   stdout=subprocess.DEVNULL)


def edit_manifest(repo2, fn):
    p = os.path.join(repo2, "manifest.json")
    with open(p, encoding="utf-8") as f:
        m = json.load(f)
    fn(m)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(m, f)


def run_student(args, cwd, url):
    env = dict(os.environ, JUDGE_UPDATE_URL=url)
    env.pop("JUDGE_NO_UPDATE", None)
    t0 = time.time()
    p = subprocess.run([sys.executable, os.path.join(os.pardir, "Judge", "judge.py")] + args, cwd=cwd, env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
    return p.returncode, p.stdout.decode("utf-8", "replace"), time.time() - t0


def test_updater():
    print("Self-update")
    tmp = tempfile.mkdtemp(prefix="judge_upd_")
    try:
        subprocess.run([sys.executable, os.path.join(REPO, "tools", "build_dist.py"), "--out", tmp, "--no-zip"],
                       check=True, stdout=subprocess.DEVNULL)
        root = os.path.join(tmp, "Mock_Test")
        judge_dir, set1 = os.path.join(root, "Judge"), os.path.join(root, "Mock_1")
        shutil.copy(os.path.join(SAMPLES, "batch", "primes_ok.cpp"), os.path.join(set1, "3.cpp"))
        student_hash, old_judge = sha(os.path.join(set1, "3.cpp")), sha(os.path.join(judge_dir, "judge.py"))
        template = sha(os.path.join(set1, "1.cpp"))

        # a) automatic update during a normal run: new files, backup, restart with the new judge
        repo2 = make_repo2(tmp, "9.9", "marker-v9.9")
        edit_manifest(repo2, lambda m: m["create_only"].update(
            {"Mock_1/9.cpp": [sha(os.path.join(REPO, "student", "set_files", "template.cpp")), "student/set_files/template.cpp"]}))
        srv, url = serve(repo2)
        code, out, _ = run_student(["3.cpp", "--no-color"], set1, url)
        check(code == 0 and "restarting" in out and "ACCEPTED" in out and "Judge v9.9" in out,
              "normal run updates to v9.9, restarts, judges", f"exit {code}\n{out}")
        with open(os.path.join(judge_dir, "judge.py"), encoding="utf-8") as f:
            new_judge = f.read()
        check("marker-v9.9" in new_judge and sha(os.path.join(judge_dir, ".backup", "judge.py")) == old_judge,
              "judge.py replaced, old one kept in Judge/.backup/")
        check(sha(os.path.join(set1, "3.cpp")) == student_hash and sha(os.path.join(set1, "1.cpp")) == template,
              "student files untouched")
        check(os.path.exists(os.path.join(set1, "9.cpp")) and sha(os.path.join(set1, "9.cpp")) == template,
              "create-only Mock_1/9.cpp added")
        check(not os.path.exists(os.path.join(judge_dir, ".update_tmp")), "no temp folder left behind")
        code, out, _ = run_student(["--update", "--no-color"], set1, url)
        check(code == 0 and "up to date" in out, "--update: up to date", f"exit {code}\n{out}")

        # b) a newer version appears: normal runs wait 10 minutes, --update takes it now
        repo2 = make_repo2(tmp, "9.11", "marker-v9.11")
        code, out, _ = run_student(["3.cpp", "--no-color"], set1, url)
        check(code == 0 and "Judge v9.9" in out and "restarting" not in out, "checked recently: no update yet")
        code, out, _ = run_student(["--update", "--no-color"], set1, url)
        check(code == 0 and "updated to v9.11" in out, "--update: updated to v9.11", f"exit {code}\n{out}")

        # c) served file does not match its hash: nothing changes
        edit_manifest(repo2, lambda m: m["files"].update({"README.txt": "1" * 64}) or m.update(version="9.12"))
        before = sha(os.path.join(judge_dir, "README.txt"))
        code, out, _ = run_student(["--update", "--no-color"], set1, url)
        check(code == 1 and "hash mismatch" in out and sha(os.path.join(judge_dir, "README.txt")) == before
              and "9.11" in open(os.path.join(judge_dir, "manifest.json"), encoding="utf-8").read(),
              "bad hash: update refused, files unchanged", f"exit {code}\n{out}")

        # d) manifest with a path outside Judge/: refused
        rebuild_manifest(repo2)
        edit_manifest(repo2, lambda m: m["files"].update({"../evil.txt": "0" * 64}) or m.update(version="9.13"))
        code, out, _ = run_student(["--update", "--no-color"], set1, url)
        check(code == 1 and "bad path" in out and not os.path.exists(os.path.join(root, "evil.txt")),
              "path outside Judge/: refused", f"exit {code}\n{out}")

        # e) recovery: a damaged file is re-downloaded by python Judge/updater.py
        rebuild_manifest(repo2)
        os.remove(os.path.join(judge_dir, "README.txt"))
        env = dict(os.environ, JUDGE_UPDATE_URL=url)
        p = subprocess.run([sys.executable, os.path.join(judge_dir, "updater.py")], env=env, cwd=set1,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out = p.stdout.decode("utf-8", "replace")
        check(p.returncode == 0 and os.path.exists(os.path.join(judge_dir, "README.txt")),
              "python Judge/updater.py restores a missing file", f"exit {p.returncode}\n{out}")
        srv.shutdown()

        # f) no network: the judge works as usual, quickly
        os.remove(os.path.join(judge_dir, ".update_check"))
        code, out, dt = run_student(["3.cpp", "--no-color"], set1, f"http://127.0.0.1:{free_port()}/")
        check(code == 0 and "ACCEPTED" in out and "restarting" not in out and dt < 30,
              f"offline: judge works ({dt:.1f} s)", f"exit {code}\n{out}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_data():
    """Every test input has its expected output (the judge silently skips an .in without .out)."""
    print("Test data")
    orphans = [f for f in glob.glob(os.path.join(REPO, "problems", "batch", "Mock_*", "*", "*.in"))
               if not os.path.exists(f[:-3] + ".out")]
    check(not orphans, "every .in has an .out", ", ".join(os.path.relpath(f, REPO) for f in orphans[:5]))


def test_manifest():
    print("Manifest")
    p = subprocess.run([sys.executable, os.path.join(REPO, "tools", "build_manifest.py"), "--check"],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    check(p.returncode == 0, "manifest.json is up to date", p.stdout.decode("utf-8", "replace"))


def main():
    if not shutil.which("g++"):
        print("g++ not found: the regression tests need a C++ compiler in PATH.")
        return 1
    test_samples()
    test_cli()
    test_student_package()
    test_updater()
    test_data()
    test_manifest()
    print()
    if FAILED:
        print(f"{len(FAILED)} FAILED: " + ", ".join(FAILED))
        return 1
    print("All regression tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
