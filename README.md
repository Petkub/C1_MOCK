# C1_MOCK — POSN Camp 1 Practice Judge (teacher's guide)

This repo is the source of the judge that students run on their own computers for the Camp 1 mock exams
(15 sets × 8 problems). Students never clone it: they download `Mock_Test.zip` once from
[Releases](https://github.com/Petkub/C1_MOCK/releases/latest), and from then on their judge **updates itself from
this repo** every time you push to `main`.

The Camp 2 judge lives in [C2_MOCK](https://github.com/Petkub/C2_MOCK) and works the same way (its README lists
the differences). `CLAUDE.md` has the rules for working on the code with Claude Code.

---

## 1. What is where

```
core/                  what students get inside Judge/   (judge.py, updater.py, include/, README.txt, CHANGELOG.txt)
problems/batch/        test data: Mock_K/N/01.in, 01.out, ...   + problems.json (problem bank) + sets.json (sets)
student/               the rest of the student package: README.txt, Guide.pdf, .vscode/, Mock_K/Mock_K.pdf,
                       set_files/ (Makefile, judge.bat, template.cpp -> 1.cpp ... 8.cpp)
samples/               known-verdict programs used by the tests (expected.json says which verdict each must get)
tests/run_regression.py   the test suite: run before every push
tools/build_manifest.py   writes manifest.json (hashes of everything students get)
tools/build_dist.py       builds dist/Mock_Test.zip for new students
VERSION                   the version students see ("Judge v1.4")
manifest.json             generated, served to students by GitHub; never edit by hand
```

What a student has: `Mock_Test/Judge/` (= `core/` + `problems/` + `manifest.json`) and `Mock_Test/Mock_K/1.cpp ... 8.cpp`
(their code, which the updater never touches).

## 2. One-time setup on a new computer

```bash
git clone https://github.com/Petkub/C1_MOCK.git
cd C1_MOCK
python3 tests/run_regression.py        # needs python3 and g++; ~20 s; must end with "All regression tests passed."
```
Optional: `gh auth login` (GitHub CLI) if you want to publish releases from the terminal.

## 3. The release routine (every change students should get)

```bash
cd ~/stupidGrader/C1_MOCK            # or wherever your clone is
# ... make the change (see section 4) ...
python3 tests/run_regression.py       # 1. tests pass
cat VERSION                           # 2. bump the version: one higher than this
echo 1.5 > VERSION
python3 tools/build_manifest.py       # 3. rebuild manifest.json (ALWAYS after the change, never before)
git add -A
git commit -m "Mock_3/5: add test 17"  # 4. commit ...
git push                              #    ... and push
```
Then check that CI is green: <https://github.com/Petkub/C1_MOCK/actions> (it runs the tests on Windows, macOS,
Linux and Python 3.7, and fails if `manifest.json` is stale).

Students receive it automatically: their judge checks GitHub at most every 10 minutes, GitHub caches files for
up to 5 minutes, so everyone who is judging gets the new version within ~15 minutes; a student who opens the judge
later gets it on that first run. To see it immediately on any installed copy:
`python3 ../Judge/judge.py --update` (inside a `Mock_K` folder).

Add one line to `core/CHANGELOG.txt` for each version; students can read it.

## 4. Common changes

### 4a. Add a test to a problem
1. Find the folder: `problems/batch/Mock_K/N/` (set K, problem N of that set). Tests are `01.in/01.out`,
   `02.in/02.out`, ... Tests `01..samples` are the samples printed in the PDF (`"samples"` in `problems.json`);
   a new test goes at the end as a hidden test.
2. Write the input, e.g. `17.in`. Create the output **with the official solution**, never by hand:
   `g++ -O2 -std=c++17 -o sol solution.cpp && ./sol < 17.in > 17.out`
3. Release (section 3). The test suite refuses an `.in` without its `.out`.

### 4b. Fix a bug in the judge
1. Edit `core/judge.py` (or `core/updater.py`).
2. Add a sample program that shows the bug under `samples/batch/` and its expected verdict in
   `samples/expected.json`, so the bug cannot come back.
3. Run the tests, release. If it cannot be tested on Linux (a Windows-only problem), rely on CI's Windows job.

### 4c. Add a new mock set (e.g. set 16)
1. Test data: `problems/batch/Mock_16/1/ ... Mock_16/8/` with `NN.in`/`NN.out`.
2. `problems/batch/problems.json`: one entry per new problem (`"en"`, `"title"`, `"tier"`, `"dir": "Mock_16/1"`,
   `"samples"`, optional `"subtasks"`), with new ids.
3. `problems/batch/sets.json`: append `{"set": 16, "stage": ..., "problems": [ids in order]}`.
4. `student/Mock_16/Mock_16.pdf` (the statement).
5. Release. Existing students get the test data, `Mock_16/Mock_16.pdf`, `Makefile`, `judge.bat`, and the
   updater **creates** `Mock_16/1.cpp ... 8.cpp` (templates are only ever created, never overwritten).

### 4d. Change something students see outside Judge/ (README, Makefile, judge.bat, template)
Edit it under `student/` and release. These are *managed* files: the updater replaces them on every student's
computer when they change (the old copy goes to `Judge/.backup/_package/`), because students do not edit them.
The only files that are never replaced are the `Mock_K/N.cpp` templates (created once, then the student's own)
and `Judge/progress.json`.

### 4e. A new zip for new students
```bash
python3 tools/build_dist.py                              # -> dist/Mock_Test.zip
gh release create v1.5 dist/Mock_Test.zip --title "Mock_Test v1.5"
```
The link <https://github.com/Petkub/C1_MOCK/releases/latest/download/Mock_Test.zip> always gives the newest
release. You only need a new release for new students (or new sets); existing students update themselves.

## 5. How the self-update works (so you can trust it)

- `Judge/updater.py` fetches `manifest.json` from `raw.githubusercontent.com/Petkub/C1_MOCK/main/`, compares the
  SHA-256 of every file in `Judge/`, downloads the changed ones to a temp folder, verifies each hash, compiles
  the new `.py` files and test-runs the new `judge.py --help`, and only then swaps them in. The old file is kept
  in `Judge/.backup/`.
- Outside `Judge/` it only replaces the managed files above and creates missing `Mock_K/N.cpp` templates; it
  never deletes anything and never touches an existing `Mock_K/N.cpp`.
- No network, a slow network (> 2 s), a bad hash, a strange path: it keeps the current version and says nothing.
  A failed update never stops a student from judging.
- Students with a zip from **before** the updater existed (before v1.2) must download the zip once; nothing can
  reach them otherwise.

## 6. Checking a student's problem report

- "The judge says I have the old version": ask them to run `python3 ../Judge/judge.py --update`. Its message says
  why it cannot update (e.g. a school firewall, or a macOS Python without certificates:
  `CERTIFICATE_VERIFY_FAILED` → run "Install Certificates.command" from the Python folder).
- "My correct code gets Runtime Error / Wrong Answer": ask for the problem, the test number and the lines printed
  under *First failure* (e.g. `your program crashed (signal 11 SIGSEGV: invalid memory access)` and the program's
  own stderr below it, such as `terminate called after throwing ... out_of_range`), plus any g++ warnings printed
  after "Compiled". Then run their
  file here: `python3 core/judge.py their.cpp K-N`. The judge compiles with `-O2`, which exposes uninitialised
  variables and out-of-bounds reads that pass on the student's own compile.
- To check the judge itself, run every official solution: they must all score 100
  (`python3 core/judge.py solution.cpp K-N`).

## 7. Things that go wrong, and the fix

| Symptom | Fix |
|---|---|
| CI red: "manifest.json is stale" | `python3 tools/build_manifest.py`, commit, push. |
| CI red: "every .in has an .out" | you added `NN.in` without `NN.out` (section 4a). |
| A pushed version is broken | `git revert HEAD`, bump `VERSION`, rebuild the manifest, push. Students roll forward to the fixed version; their `Judge/.backup/` also still has the previous files. |
| `build_dist.py` refuses to overwrite | it only replaces a `dist/Mock_Test` folder it made itself, so a student folder is never wiped; delete `dist/` by hand if you are sure. |
| Students on Windows see `?` boxes | they can use `--ascii`; the judge output must stay ASCII-safe. |

## 8. Never

- Edit `manifest.json` by hand, or commit without rebuilding it.
- Delete or rename a test that students already have (the updater never deletes; add a new one instead).
- Type an expected output by hand.
- Change the judge's exit codes, the manifest format or the updater's safety rules without updating the tests.
