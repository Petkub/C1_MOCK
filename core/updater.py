#!/usr/bin/env python3
"""
Self-update for the POSN Practice Judge (Python 3.7+, standard library only).

judge.py calls check() when it starts (at most once every 10 minutes). check() fetches manifest.json from the GitHub
repo over HTTPS, compares the SHA-256 of the files in Judge/ with it, downloads the changed files to a temp
folder, verifies every hash, test-runs the new judge.py, and only then swaps the files in with os.replace,
keeping the old version of each file in Judge/.backup/. Anything wrong (no network, slow network, a bad hash,
an odd path) means: keep the current version and say nothing. A failed update never stops the judge.

Rules
  - writes only inside Judge/ and only the files listed in the manifest; never deletes anything
  - never reads or writes student files (Mock_K/N.cpp, progress.json); a new mock set may add Mock_K/N.cpp,
    Makefile, judge.bat and Mock_K.pdf, and only when the file does not exist yet
  - updates only an installed package (Judge/judge.py and Judge/manifest.json exist), never the source repo

Recovery:  python3 ../Judge/updater.py      force a check and re-download changed or damaged files
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

REPO = "Petkub/C1_MOCK"
BASE_URL = "https://raw.githubusercontent.com/" + REPO + "/main/"      # the one place the hosting is set
TIMEOUT = 2.0                       # seconds per network operation
CHECK_INTERVAL = 600                # seconds between automatic checks (10 minutes)
MAX_MANIFEST = 8 * 1024 * 1024      # bytes
MAX_FILE = 64 * 1024 * 1024
ROOT = os.path.dirname(os.path.abspath(__file__))
STAMP = ".update_check"             # Judge/.update_check: time of the last check
BACKUP = ".backup"
TMP = ".update_tmp"
NEVER_UPDATE = {"manifest.json", "progress.json", "progress.json.tmp"}
SET_FILE = re.compile(r"^Mock_[0-9]+/([0-9]+\.cpp|Makefile|judge\.bat|Mock_[0-9]+\.pdf)$")


class Result:
    def __init__(self, status, message, version="", files=()):
        self.status = status            # "updated", "current", "skipped", "failed"
        self.message = message
        self.version = version
        self.files = list(files)


# ----------------------------------------------------------------------------- helpers
def base_url():
    """BASE_URL, or JUDGE_UPDATE_URL (for testing: HTTPS, or plain HTTP to this computer only)."""
    url = os.environ.get("JUDGE_UPDATE_URL") or BASE_URL
    if not url.endswith("/"):
        url += "/"
    if not (url.startswith("https://") or url.startswith("http://127.0.0.1:") or url.startswith("http://localhost:")):
        raise ValueError("the update URL must use https")
    return url


def fetch(url, limit, fresh=False):
    """Download url (at most limit bytes). Raises on any problem. fresh: skip the CDN cache (GitHub raw keeps
    a file for up to 5 minutes), used by the forced check so --update sees a new version at once."""
    if fresh:
        url += "?t=" + str(int(time.time()))
    req = urllib.request.Request(url, headers={"User-Agent": "posn-judge-updater"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise ValueError("file too big: " + url)
    return data


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    try:
        with open(path, "rb") as f:
            return sha256(f.read())
    except OSError:
        return None


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def judge_path(rel):
    """Path inside Judge/ for a manifest entry, or None when the entry is not allowed."""
    if not isinstance(rel, str) or not rel or "\\" in rel or ":" in rel or rel.startswith("/"):
        return None
    parts = rel.split("/")
    if any(p in ("", ".", "..") or p.startswith(".") or p == "__pycache__" for p in parts):
        return None
    if rel in NEVER_UPDATE:
        return None
    return os.path.join(*parts)


def set_path(rel):
    """Path (relative to the folder holding Judge/) of a create-only Mock_K file, or None."""
    return os.path.join(*rel.split("/")) if isinstance(rel, str) and SET_FILE.match(rel) else None


def source_of(rel, sources):
    """Repo path of a Judge/ file: the longest matching prefix in the manifest's sources map."""
    best = None
    for prefix, repo_dir in sources.items():
        if rel.startswith(prefix) and (best is None or len(prefix) > len(best)):
            best = prefix
    if best is None:
        raise ValueError("no source for " + rel)
    return sources[best] + rel[len(best):]


def is_hash(s):
    return isinstance(s, str) and len(s) == 64 and all(c in "0123456789abcdef" for c in s)


# ----------------------------------------------------------------------------- planning
def plan(judge_dir, remote, local, force):
    """Lists of (judge-relative path, repo path, sha) to update and of create-only set files to add.
    Raises ValueError when the manifest is not acceptable."""
    files, sources = remote.get("files"), remote.get("sources")
    if not isinstance(files, dict) or not isinstance(sources, dict) or not isinstance(remote.get("version"), str):
        raise ValueError("bad manifest")
    if not all(isinstance(k, str) and isinstance(v, str) and ".." not in k and ".." not in v for k, v in sources.items()):
        raise ValueError("bad sources")
    known = local.get("files", {}) if isinstance(local, dict) else {}
    updates = []
    for rel, sha in files.items():
        p = judge_path(rel)
        if p is None or not is_hash(sha):
            raise ValueError("bad path in manifest: " + str(rel))
        full = os.path.join(judge_dir, p)
        if not os.path.exists(full):
            changed = True
        elif force or known.get(rel) != sha:
            changed = file_sha(full) != sha
        else:
            changed = False          # same hash as the installed manifest: trust it, do not re-read the file
        if changed:
            updates.append((p, source_of(rel, sources), sha))
    creates = []
    for rel, spec in (remote.get("create_only") or {}).items():
        p = set_path(rel)
        if p is None or not (isinstance(spec, list) and len(spec) == 2 and is_hash(spec[0])
                             and isinstance(spec[1], str) and ".." not in spec[1]):
            raise ValueError("bad create-only entry: " + str(rel))
        if not os.path.exists(os.path.join(os.path.dirname(judge_dir), p)):
            creates.append((p, spec[1], spec[0]))
    return updates, creates


def download(items, tmp, url, fresh):
    """Download every item into tmp (same relative paths) and verify its hash. Raises on any mismatch."""
    for p, src, sha in items:
        data = fetch(url + src.replace(os.sep, "/"), MAX_FILE, fresh)
        if sha256(data) != sha:
            raise ValueError("hash mismatch: " + p)
        dest = os.path.join(tmp, p)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(data)
        if p.endswith(".py"):
            compile(data.decode("utf-8"), p, "exec")       # a syntax error must never reach Judge/


def test_new_judge(tmp):
    """The downloaded judge.py must at least start and print its help."""
    j = os.path.join(tmp, "judge.py")
    if not os.path.isfile(j):
        return
    env = dict(os.environ, JUDGE_NO_UPDATE="1")
    r = subprocess.run([sys.executable, j, "--help"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       env=env, timeout=30)
    if r.returncode != 0:
        raise ValueError("the new judge.py does not run")


def apply(judge_dir, updates, creates, tmp):
    """Swap the verified files in: data first, judge.py last; keep the old file in Judge/.backup/."""
    order = sorted(updates, key=lambda u: (u[0].endswith(".py"), u[0] == "judge.py"))
    for p, _, _ in order:
        dest = os.path.join(judge_dir, p)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if os.path.exists(dest):
            bak = os.path.join(judge_dir, BACKUP, p)
            os.makedirs(os.path.dirname(bak), exist_ok=True)
            os.replace(dest, bak)
        os.replace(os.path.join(tmp, p), dest)
    base = os.path.dirname(judge_dir)
    for p, _, _ in creates:
        dest = os.path.join(base, p)
        if not os.path.exists(dest):                # create only, never overwrite a student's file
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            os.replace(os.path.join(tmp, "_sets", p), dest)


def touch_stamp(judge_dir):
    try:
        with open(os.path.join(judge_dir, STAMP), "w") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + "\n")
    except OSError:
        pass


def checked_recently(judge_dir):
    try:
        return time.time() - os.path.getmtime(os.path.join(judge_dir, STAMP)) < CHECK_INTERVAL
    except OSError:
        return False


# ----------------------------------------------------------------------------- main entry
def check(judge_dir=ROOT, force=False):
    """Update Judge/ if the repo has a newer version. Returns a Result; never raises."""
    local = load_json(os.path.join(judge_dir, "manifest.json"))
    if not os.path.isfile(os.path.join(judge_dir, "judge.py")) or local is None:
        return Result("skipped", "not an installed Judge package (no manifest.json next to judge.py)")
    if not force and checked_recently(judge_dir):
        return Result("skipped", "checked recently")
    version = str(local.get("version", "?"))
    tmp = os.path.join(judge_dir, TMP)
    try:
        touch_stamp(judge_dir)
        url = base_url()
        data = fetch(url + "manifest.json", MAX_MANIFEST, force)
        remote = json.loads(data.decode("utf-8"))
        updates, creates = plan(judge_dir, remote, local, force)
        if not updates and not creates and remote["version"] == version:
            return Result("current", f"Judge v{version} is up to date", version)
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp)
        download(updates, tmp, url, force)
        download(creates, os.path.join(tmp, "_sets"), url, force)
        test_new_judge(tmp)
        apply(judge_dir, updates, creates, tmp)
        with open(os.path.join(tmp, "manifest.json"), "wb") as f:
            f.write(data)
        os.replace(os.path.join(tmp, "manifest.json"), os.path.join(judge_dir, "manifest.json"))
        names = [p.replace(os.sep, "/") for p, _, _ in updates] + [p.replace(os.sep, "/") for p, _, _ in creates]
        return Result("updated", f"updated to v{remote['version']} ({len(names)} files)", remote["version"], names)
    except Exception as ex:          # network, hash, bad manifest, read-only folder, ...: keep what we have
        return Result("failed", f"{type(ex).__name__}: {ex}", version)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    r = check(force=True)
    print(r.message)
    for name in r.files[:20]:
        print("  " + name)
    if len(r.files) > 20:
        print(f"  ... {len(r.files) - 20} more")
    return 0 if r.status in ("updated", "current") else 1


if __name__ == "__main__":
    sys.exit(main())
