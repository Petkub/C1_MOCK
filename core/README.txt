POSN Camp 1 - Mock Exam Judge
==============================
Requirements: Python 3.7+ and g++ in PATH (Linux / macOS / Windows; on Windows type python, not python3).
macOS: g++ is Apple clang without <bits/stdc++.h>; the judge adds include/ (a fallback header) automatically.

Inside a set folder (e.g. Mock_3):
  python3 ../Judge/judge.py               judge the whole set (1.cpp ... 8.cpp)
  python3 ../Judge/judge.py 5.cpp         judge problem 5 of this set
  python3 ../Judge/judge.py 5             the same (just the problem number)

From the Judge folder (or use ../Judge/judge.py from a set folder):
  python3 judge.py --list                 list all 15 sets and their problems
  python3 judge.py --set 3                show set 3
  python3 judge.py --set 3 FOLDER         judge a whole set (files 1.cpp ... 8.cpp in FOLDER)
  python3 judge.py my.cpp 3-5             judge one solution: set 3, problem 5

Options: --tl SECONDS  --diff N  --stop  --ascii  --no-color
Test data: problems/batch/Mock_K/P/*.in|out (the first 5 or 6 tests are the samples shown in the statement).
Windows: VS Code's Ctrl+Shift+B runs judge.cmd (uses the py launcher if installed, else python).
Updates: the judge updates itself from GitHub when online (checked at most once every 10 minutes; your .cpp files
are never touched). Force a check: python3 ../Judge/judge.py --update   (version shown in the header box)
