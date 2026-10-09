#!/usr/bin/env python3
"""
Build the student package.

  python3 tools/build_dist.py                  writes dist/Mock_Test/ and dist/Mock_Test.zip
  python3 tools/build_dist.py --out DIR        writes DIR/Mock_Test/ (and DIR/Mock_Test.zip)
  python3 tools/build_dist.py --no-zip         folder only

Layout produced:
  Mock_Test/README.txt, Guide.pdf, .vscode/    from student/
  Mock_Test/Judge/                             core/ + problems/
  Mock_Test/Mock_K/Mock_K.pdf                  from student/Mock_K/
  Mock_Test/Mock_K/Makefile, judge.bat         from student/set_files/
  Mock_Test/Mock_K/1.cpp ... 8.cpp             empty template (student/set_files/template.cpp)
"""
import json
import os
import shutil
import sys
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STUDENT = os.path.join(REPO, "student")
NAME = "Mock_Test"
MARKER = ".built_by_build_dist"     # only a folder with this file may be replaced by a new build
SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")


def prepare(out):
    """Create out/Mock_Test, replacing an earlier build but never a folder this script did not make."""
    root = os.path.join(out, NAME)
    if os.path.exists(root):
        if not os.path.exists(os.path.join(root, MARKER)):
            sys.exit(f"Refusing to replace {root}: it was not made by build_dist.py (it may hold student code).")
        shutil.rmtree(root)
    os.makedirs(root)
    with open(os.path.join(root, MARKER), "w") as f:
        f.write("Made by tools/build_dist.py; not part of the zip.\n")
    return root


def copy_judge(root):
    judge = os.path.join(root, "Judge")
    shutil.copytree(os.path.join(REPO, "core"), judge, ignore=SKIP)
    shutil.copytree(os.path.join(REPO, "problems"), os.path.join(judge, "problems"), ignore=SKIP)


def copy_student_files(root):
    for name in ("README.txt", "Guide.pdf"):
        p = os.path.join(STUDENT, name)
        if os.path.exists(p):
            shutil.copy2(p, root)
    if os.path.isdir(os.path.join(STUDENT, ".vscode")):
        shutil.copytree(os.path.join(STUDENT, ".vscode"), os.path.join(root, ".vscode"))


def make_sets(root):
    with open(os.path.join(REPO, "problems", "batch", "sets.json"), encoding="utf-8") as f:
        sets = json.load(f)
    files = os.path.join(STUDENT, "set_files")
    for s in sets:
        k = s["set"]
        d = os.path.join(root, f"Mock_{k}")
        os.makedirs(d)
        pdf = os.path.join(STUDENT, f"Mock_{k}", f"Mock_{k}.pdf")
        if os.path.exists(pdf):
            shutil.copy2(pdf, d)
        for name in ("Makefile", "judge.bat"):
            shutil.copy2(os.path.join(files, name), d)
        for i in range(1, len(s["problems"]) + 1):
            shutil.copy2(os.path.join(files, "template.cpp"), os.path.join(d, f"{i}.cpp"))
    return len(sets)


def make_zip(root):
    path = root + ".zip"
    out = os.path.dirname(root)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames.sort()
            for name in sorted(filenames):
                if name == MARKER:
                    continue
                full = os.path.join(dirpath, name)
                z.write(full, os.path.relpath(full, out).replace(os.sep, "/"))
    return path


def main():
    argv = sys.argv[1:]
    out = os.path.join(REPO, "dist")
    if "--out" in argv:
        i = argv.index("--out")
        if i + 1 >= len(argv):
            sys.exit("--out needs a folder")
        out = os.path.abspath(argv[i + 1])
    root = prepare(out)
    copy_judge(root)
    copy_student_files(root)
    n = make_sets(root)
    print(f"Built {root} ({n} sets)")
    if "--no-zip" not in argv:
        path = make_zip(root)
        print(f"Built {path} ({os.path.getsize(path) // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
