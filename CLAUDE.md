# C1_MOCK: POSN Camp 1 Practice Judge

A terminal judge that students run on their own machines to practice for the POSN Computer Olympiad (Camp 1, fundamental contest: 15 sets x 8 problems).
Sibling repo `C2_MOCK` is the Camp 2 judge (same structure); fix shared bugs in both.
Today it judges batch problems (`judge.py`). We are adding interactive and communication problems,
and a safe self-update mechanism so bugs can be fixed without re-sending zip files.

## Hard constraints (never break these)

1. **Python 3.7+ standard library only.** No pip packages. Students have Python and g++, nothing else.
2. **Student machines run Windows, macOS and Linux.** Every change must work on all three.
   Use `os.name == "nt"` guards like `judge.py` does. Never assume `/tmp`, `fork`, `resource`, or bash.
3. **Never touch student code.** The updater may write only inside the `Judge/` folder, and only
   files listed in `manifest.json`. It must never read, move, delete or overwrite `Mock_*/*.cpp`.
4. **Never delete files the updater does not own.** No "wipe and reinstall" step, ever.
5. **Fail safe.** If the network is down, slow (>2 s), or a hash does not match, keep the current
   version and continue silently. A broken update must never stop a student from judging.
6. **Do not change the existing look.** New commands reuse `Style`, `box`, `rule`, `bar`, `compile_source`
   and the scoring functions from `judge.py` so everything feels the same (verdict table, score bar).
7. **Output is English, ASCII-safe.** Keep the `--ascii` and `--no-color` fallbacks working.

## Repo layout

```
C1_MOCK/
  CLAUDE.md
  core/                         # what students get inside Judge/
    judge.py                    # batch judge (existing, keep working)
    interactive_judge.py        # interactive problems (prototype exists)
    communication_judge.py      # TODO: IOI-style manager + stub
    updater.py                  # self-update (manifest + hashes)
    include/bits/stdc++.h       # macOS fallback header
  launcher/
    judge_launcher.py           # tiny, almost never changes; runs updater then core
  problems/
    batch/Mock_K/N/*.in|out
    batch/problems.json         # problem bank: id -> title, tier, dir (Mock_K/N), samples, subtasks
    batch/sets.json             # set K -> list of 8 problem ids
    interactive/<name>/{problem.json, interactor.cpp, tests/NN.in}
    communication/<name>/{problem.json, manager.cpp, stub/, tests/}
  student/                      # student-side files outside Judge/ (copied by build_dist.py)
    README.txt, Guide.pdf, .vscode/, Mock_K/Mock_K.pdf
    set_files/{Makefile, judge.bat, template.cpp}   # put in every Mock_K; template.cpp -> 1.cpp ... 8.cpp
  samples/                      # known-verdict programs used as regression tests
    batch/primes_ok.cpp, primes_offbyone.cpp, primes_loop.cpp, primes_crash.cpp, primes_syntax.cpp
    interactive/guess_ok.cpp, guess_noflush.cpp, guess_linear.cpp, guess_crash.cpp
    expected.json               # {"batch/primes_ok.cpp": {"problem": "1-3", "verdict": "AC", "score": 100}, ...}
                                # verdict: AC/WA/TLE/RE/CE (first failing test); "score" optional (runs all tests)
  tools/
    build_manifest.py           # writes manifest.json (version + SHA-256 of every core/problem file)
    build_dist.py               # builds the student zip (Mock_Test/ layout with Judge/ and empty Mock_K/*.cpp)
  tests/
    run_regression.py           # runs every sample, compares verdicts with expected.json
  .github/workflows/ci.yml      # matrix: windows-latest, macos-latest, ubuntu-latest
  manifest.json                 # generated, do not edit by hand
```

Student-side layout (what `build_dist.py` produces): `Mock_Test/Judge/` = `core/` + `problems/`,
and `Mock_Test/Mock_K/1.cpp ... 8.cpp` = student files. The repo layout is **not** the student layout.
`judge.py` finds batch data in the first existing of `Judge/problems/batch/` (student package),
`../problems/batch/` (repo, run from `core/`) and `Judge/tests/` (older zips, JSON files next to judge.py).

## Interactive protocol (already implemented, keep compatible)

- Interactor is called as `interactor <input-file> <output-file>` and talks to the student on stdin/stdout.
- Exit code: `0` OK, `1` Wrong Answer, `2` Presentation Error (treated as WA), `3` judge failure.
  One line on stderr is the message shown to the student. This matches testlib.
- The judge relays the pipes and records the conversation, so failures show a `you` / `judge` transcript.
- A student program that hangs while the judge waits gets a flush hint
  (`cin.tie(0); ios::sync_with_stdio(0);` disables the automatic flush; the course template has it).
- Times are wall-clock on the student's machine: fine for practice, not for ranking.

## Communication problems (next, design before coding)

Manager process + one or more student processes linked by pipes, with a stub/grader header the
student includes. Reuse the pipe relay and transcript code from `interactive_judge.py`.
Propose the design and wait for approval before writing it.

## Self-update rules

- `launcher/judge_launcher.py` is tiny and stable. It checks `manifest.json` (HTTPS only), downloads
  changed files to temp names, verifies SHA-256, then replaces atomically (`os.replace`).
- Keep the previous version of each replaced file in `Judge/.backup/`.
- Reject any manifest path that is absolute or contains `..`. Only paths under `Judge/` are allowed.
- Only update when `Judge/judge.py` exists in the target folder (guards against a wrong working directory).
- Provide `--update` (force) and show `Judge vX.Y` in the header box.
- Hosting is **undecided** (GitHub raw vs Cloudflare Pages vs other). Keep the base URL in one constant.
- New problem sets may add template `N.cpp` files only if they do not already exist.

## Commands

```
python3 tests/run_regression.py          # must pass before every commit
python3 tools/build_manifest.py          # after changing anything under core/ or problems/
python3 tools/build_dist.py              # build dist/Mock_Test/ + dist/Mock_Test.zip (--out DIR, --no-zip)
python3 core/judge.py samples/batch/primes_ok.cpp 1-3      # judge one file from the repo (set 1, problem 3)
python3 core/interactive_judge.py guess samples/interactive/guess_ok.cpp
```

## Working rules for Claude Code

- Before changing `judge.py`, run the regression tests; after changing it, run them again.
- Add a sample program + expected verdict for every new behaviour or bug fix.
- Keep functions small and readable, in the same style as `judge.py`. No new dependencies.
- If a change cannot be verified on Windows locally, say so and rely on the CI matrix.
- Ask before: changing the manifest format, the exit-code protocol, or anything in the updater.
