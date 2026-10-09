#!/usr/bin/env python3
"""
Write manifest.json: the version (file VERSION) and the SHA-256 of every file the student package gets inside
Judge/, plus the create-only Mock_K files (templates, Makefile, judge.bat, Mock_K.pdf) of every set.
Judge/updater.py on the students' computers compares this file with what they have.

  python3 tools/build_manifest.py            write manifest.json (run after changing core/, problems/, student/)
  python3 tools/build_manifest.py --check    exit 1 if manifest.json is stale (used by CI)

Manifest format (version 1):
  {"version": "1.0",
   "sources": {"problems/": "problems/", "": "core/"},        Judge/ path prefix -> repo folder
   "files": {"judge.py": "<sha256>", "problems/batch/Mock_1/1/01.in": "<sha256>", ...},
   "create_only": {"Mock_1/1.cpp": ["<sha256>", "student/set_files/template.cpp"], ...}}
"""
import hashlib
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(REPO, "manifest.json")
SOURCES = {"problems/": "problems/", "": "core/"}
SKIP_NAMES = {"__pycache__", ".DS_Store", "progress.json", "progress.json.tmp", ".update_check"}
SKIP_SUFFIXES = (".pyc",)


def sha256_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def version():
    with open(os.path.join(REPO, "VERSION"), encoding="utf-8") as f:
        return f.read().strip()


def shipped(dirpath, names):
    """Names in dirpath that go into the package (override point for repos with generated tests)."""
    return [n for n in names if n not in SKIP_NAMES and not n.endswith(SKIP_SUFFIXES) and not n.startswith(".")]


def judge_files():
    """Every file of Judge/ as (Judge-relative path, repo-relative path), both with '/' separators."""
    out = []
    for prefix, repo_dir in SOURCES.items():
        top = os.path.join(REPO, repo_dir)
        for dirpath, dirnames, filenames in os.walk(top):
            dirnames[:] = sorted(shipped(dirpath, dirnames))
            for name in sorted(shipped(dirpath, filenames)):
                rel = os.path.relpath(os.path.join(dirpath, name), top).replace(os.sep, "/")
                out.append((prefix + rel, repo_dir + rel))
    return sorted(out)


def set_files():
    """Create-only files of every set as (path relative to the package root, repo-relative source path)."""
    with open(os.path.join(REPO, "problems", "batch", "sets.json"), encoding="utf-8") as f:
        sets = json.load(f)
    out = []
    for s in sets:
        k = s["set"]
        for i in range(1, len(s["problems"]) + 1):
            out.append((f"Mock_{k}/{i}.cpp", "student/set_files/template.cpp"))
        out.append((f"Mock_{k}/Makefile", "student/set_files/Makefile"))
        out.append((f"Mock_{k}/judge.bat", "student/set_files/judge.bat"))
        if os.path.exists(os.path.join(REPO, "student", f"Mock_{k}", f"Mock_{k}.pdf")):
            out.append((f"Mock_{k}/Mock_{k}.pdf", f"student/Mock_{k}/Mock_{k}.pdf"))
    return out


def build():
    files = {rel: sha256_file(os.path.join(REPO, src)) for rel, src in judge_files()}
    creates = {rel: [sha256_file(os.path.join(REPO, src)), src] for rel, src in set_files()}
    return {"version": version(), "sources": SOURCES, "files": files, "create_only": creates}


def dumps(manifest):
    return json.dumps(manifest, indent=0, sort_keys=True) + "\n"


def main():
    manifest = build()
    text = dumps(manifest)
    if "--check" in sys.argv[1:]:
        try:
            with open(MANIFEST, encoding="utf-8") as f:
                current = f.read()
        except OSError:
            current = ""
        if current != text:
            print("manifest.json is stale: run  python3 tools/build_manifest.py  and commit it.")
            return 1
        print(f"manifest.json is up to date (v{manifest['version']}, {len(manifest['files'])} files).")
        return 0
    with open(MANIFEST, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"Wrote manifest.json: v{manifest['version']}, {len(manifest['files'])} files in Judge/, "
          f"{len(manifest['create_only'])} create-only set files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
