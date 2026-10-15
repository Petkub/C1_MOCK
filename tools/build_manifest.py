#!/usr/bin/env python3
"""
Write manifest.json: the version (file VERSION) and the SHA-256 of every file the student package gets inside
Judge/, the managed package files outside Judge/ (Mock_K.pdf, Makefile, judge.bat, README.txt, Guide.pdf,
Progress.md, .vscode/: replaced on the students' computers when they change) and the create-only files
(Mock_K/N.cpp templates: added only when missing, never replaced).
Judge/updater.py on the students' computers compares this file with what they have.

  python3 tools/build_manifest.py            write manifest.json (run after changing core/, problems/, student/)
  python3 tools/build_manifest.py --check    exit 1 if manifest.json or a bundle is stale (used by CI)

It also writes bundles/<folder>.zip: every shipped file of one problem folder (problems/batch/<folder>/), so the
updater fetches a new set of problems in a few requests. A bundle is rewritten only when its content changes.

Manifest format 1 (what updaters before 2.3 understand):
  {"version": "1.0",
   "sources": {"problems/": "problems/", "": "core/"},        Judge/ path prefix -> repo folder
   "files": {"judge.py": "<sha256>", "problems/batch/Mock_1/1/01.in": "<sha256>", ...},
   "managed": {"Mock_1/Mock_1.pdf": ["<sha256>", "student/Mock_1/Mock_1.pdf"], "README.txt": [...], ...},
   "create_only": {"Mock_1/1.cpp": ["<sha256>", "student/set_files/template.cpp"], ...},
   "bundles": {"bundles/Mock_1.zip": {"sha256": "<sha256>", "prefix": "problems/batch/Mock_1/"}, ...}}
Format 2 (when tools/legacy_manifest.json exists, the last release that old updaters read): the format-1 manifest
goes under "full", and the top level is the legacy view for old updaters: the legacy release's entries that did
not change, plus the new judge.py and updater.py. An old judge (one file per request) therefore downloads just
those two files, and the new updater then installs "full".
"""
import hashlib
import json
import os
import sys
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(REPO, "manifest.json")
SOURCES = {"problems/": "problems/", "": "core/"}
SKIP_NAMES = {"__pycache__", ".DS_Store", "progress.json", "progress.json.tmp", ".update_check"}
SKIP_SUFFIXES = (".pyc",)
BUNDLES = "bundles"
LEGACY = os.path.join(REPO, "tools", "legacy_manifest.json")
BOOTSTRAP = ("judge.py", "updater.py")      # what an old updater must take so that this updater does the rest
STALE = []                                  # bundles that --check found out of date


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


def load_sets():
    with open(os.path.join(REPO, "problems", "batch", "sets.json"), encoding="utf-8") as f:
        return json.load(f)


def set_files():
    """Create-only files (the N.cpp templates of every set) as (package path, repo-relative source path)."""
    return [(f"Mock_{s['set']}/{i}.cpp", "student/set_files/template.cpp")
            for s in load_sets() for i in range(1, len(s["problems"]) + 1)]


def managed_files():
    """Managed package files outside Judge/ as (package path, repo-relative source path)."""
    out = []
    for name in ("README.txt", "Guide.pdf", "Progress.md", ".vscode/tasks.json", ".vscode/settings.json"):
        if os.path.exists(os.path.join(REPO, "student", *name.split("/"))):
            out.append((name, "student/" + name))
    for s in load_sets():
        k = s["set"]
        out.append((f"Mock_{k}/Makefile", "student/set_files/Makefile"))
        out.append((f"Mock_{k}/judge.bat", "student/set_files/judge.bat"))
        if os.path.exists(os.path.join(REPO, "student", f"Mock_{k}", f"Mock_{k}.pdf")):
            out.append((f"Mock_{k}/Mock_{k}.pdf", f"student/Mock_{k}/Mock_{k}.pdf"))
    return out


def with_hashes(pairs):
    return {rel: [sha256_file(os.path.join(REPO, src)), src] for rel, src in pairs}


def zip_members(path):
    """{member name: sha256} of a zip, or None when it is missing or broken."""
    try:
        with zipfile.ZipFile(path) as z:
            return {i.filename: hashlib.sha256(z.read(i)).hexdigest() for i in z.infolist()}
    except (OSError, zipfile.BadZipFile):
        return None


def write_zip(path, members):
    """Deterministic zip of (Judge/ path, repo path) pairs: fixed dates and modes, sorted names."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel, src in sorted(members):
            info = zipfile.ZipInfo(rel, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with open(os.path.join(REPO, src), "rb") as f:
                z.writestr(info, f.read())
    os.replace(tmp, path)


def bundles(pairs, files, write):
    """One bundle per problem folder problems/batch/<folder>/, rewritten only when its content changed."""
    groups = {}
    for rel, src in pairs:
        parts = rel.split("/")
        if len(parts) >= 4 and parts[0] == "problems" and parts[1] == "batch":
            groups.setdefault(parts[2], []).append((rel, src))
    out = {}
    for folder, members in sorted(groups.items()):
        name = f"{BUNDLES}/{folder}.zip"
        path = os.path.join(REPO, BUNDLES, folder + ".zip")
        if zip_members(path) != {rel: files[rel] for rel, _ in members}:
            if not write:
                STALE.append(name)
                continue
            write_zip(path, members)
        out[name] = {"sha256": sha256_file(path), "prefix": f"problems/batch/{folder}/"}
    return out


def legacy_view(full):
    """The top level of a format-2 manifest: what old updaters (one file per request) act on."""
    with open(LEGACY, encoding="utf-8") as f:
        base = json.load(f)

    def unchanged(old, new):
        return {rel: spec for rel, spec in old.items() if new.get(rel) == spec}

    files = unchanged({rel: sha for rel, sha in base["files"].items() if rel not in BOOTSTRAP}, full["files"])
    files.update({rel: full["files"][rel] for rel in BOOTSTRAP})
    return {"version": base["version"], "sources": SOURCES, "files": files,
            "managed": unchanged(base["managed"], full["managed"]),
            "create_only": unchanged(base["create_only"], full["create_only"])}


def build(write=True):
    pairs = judge_files()
    files = {rel: sha256_file(os.path.join(REPO, src)) for rel, src in pairs}
    full = {"version": version(), "sources": SOURCES, "files": files, "managed": with_hashes(managed_files()),
            "create_only": with_hashes(set_files()), "bundles": bundles(pairs, files, write)}
    if not os.path.exists(LEGACY):
        return full
    return dict(legacy_view(full), full=full)


def installed(manifest):
    """The part of a manifest that the updater installs (and writes as Judge/manifest.json)."""
    return manifest.get("full", manifest)


def dumps(manifest):
    return json.dumps(manifest, indent=0, sort_keys=True) + "\n"


def main():
    check = "--check" in sys.argv[1:]
    manifest = build(write=not check)
    text = dumps(manifest)
    if check:
        if STALE:
            print("bundles are stale (" + ", ".join(STALE[:3]) + "): run  python3 tools/build_manifest.py  and commit.")
            return 1
        try:
            with open(MANIFEST, encoding="utf-8") as f:
                current = f.read()
        except OSError:
            current = ""
        if current != text:
            print("manifest.json is stale: run  python3 tools/build_manifest.py  and commit it.")
            return 1
        full = installed(manifest)
        print(f"manifest.json is up to date (v{full['version']}, {len(full['files'])} files).")
        return 0
    with open(MANIFEST, "w", encoding="utf-8") as f:
        f.write(text)
    full = installed(manifest)
    print(f"Wrote manifest.json: v{full['version']}, {len(full['files'])} files in Judge/, "
          f"{len(full['managed'])} managed and {len(full['create_only'])} create-only package files, "
          f"{len(full['bundles'])} bundles" + (f"; {len(manifest['files'])} files for old updaters." if "full" in manifest else "."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
