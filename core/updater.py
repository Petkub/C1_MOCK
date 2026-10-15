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
  - never reads or writes student files (Mock_K/N.cpp, progress.json). Outside Judge/ it only handles
    "managed" files the students do not edit (Mock_K.pdf, Makefile, judge.bat, README.txt, Guide.pdf,
    Progress.md, .vscode/) and "create-only" files (Mock_K/N.cpp templates of a new set, added only when
    missing). The old copy of every replaced file goes to Judge/.backup/ (package files under _package/)
  - updates only an installed package (Judge/judge.py and Judge/manifest.json exist), never the source repo

Speed: files are downloaded in parallel (each one retried), and a whole problem folder comes as one zip ("bundle")
when many of its files are needed, so a new set of problems takes a few requests instead of thousands. Every file
taken from a bundle is still checked against its own hash in the manifest.

Manifest format 2: the top level is what judges older than 2.3 read (their updater downloads one file at a time).
For them it lists only the new judge.py / updater.py and the files that did not change since the last format-1
release, so an old judge first takes this updater (two files) and this updater then reads "full", the real version.

Recovery:  python3 ../Judge/updater.py      force a check and re-download changed or damaged files
"""
import concurrent.futures
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile

REPO = "Petkub/C1_MOCK"
BASE_URL = "https://raw.githubusercontent.com/" + REPO + "/main/"      # the one place the hosting is set
TIMEOUT = 2.0                       # seconds per network operation
CHECK_INTERVAL = 600                # seconds between automatic checks (10 minutes)
MAX_MANIFEST = 8 * 1024 * 1024      # bytes
MAX_FILE = 64 * 1024 * 1024
MAX_BUNDLE = 64 * 1024 * 1024
TRIES = 3                           # attempts per file (the manifest itself: one, so an offline start stays fast)
WORKERS = 8                         # parallel downloads
BUNDLE_MIN = 8                      # fetch a folder's bundle when at least this many of its files are needed
NOTIFY_MIN = 20                     # say "Downloading ..." when an update needs at least this many files
ROOT = os.path.dirname(os.path.abspath(__file__))
STAMP = ".update_check"             # Judge/.update_check: time of the last check
BACKUP = ".backup"
TMP = ".update_tmp"
NEVER_UPDATE = {"manifest.json", "progress.json", "progress.json.tmp"}
SET_FILE = re.compile(r"^Mock_[0-9]+/[0-9]+\.cpp$")                 # create-only: a student's own files
MANAGED_FILE = re.compile(r"^(Mock_[0-9]+/(Makefile|judge\.bat|Mock_[0-9]+\.pdf)|Guide\.pdf|README\.txt"
                          r"|Progress\.md|\.vscode/(tasks|settings)\.json)$")   # replaced when they change


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


def fetch(url, limit, fresh=False, tries=1):
    """Download url (at most limit bytes), trying up to tries times. Raises on any problem. fresh: skip the CDN
    cache (GitHub raw keeps a file for up to 5 minutes), used by the forced check so --update sees a new version
    at once."""
    if fresh:
        url += "?t=" + str(int(time.time()))
    req = urllib.request.Request(url, headers={"User-Agent": "posn-judge-updater"})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                data = r.read(limit + 1)
            break
        except Exception:
            if attempt + 1 == tries:
                raise
            time.sleep(0.5 * (attempt + 1))
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


def managed_path(rel):
    """Path (relative to the folder holding Judge/) of a managed package file, or None."""
    return os.path.join(*rel.split("/")) if isinstance(rel, str) and MANAGED_FILE.match(rel) else None


def good_spec(spec):
    return (isinstance(spec, list) and len(spec) == 2 and is_hash(spec[0]) and isinstance(spec[1], str)
            and ".." not in spec[1])


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


def view(manifest):
    """The part of a manifest this updater acts on: "full" in format 2, else the manifest itself."""
    full = manifest.get("full") if isinstance(manifest, dict) else None
    return full if isinstance(full, dict) else manifest


def plan_bundles(remote):
    """{repo path of a zip: (sha256, Judge/ folder prefix)} from the manifest. Raises ValueError when not acceptable."""
    out = {}
    for name, spec in (remote.get("bundles") or {}).items():
        if (not isinstance(name, str) or ".." in name or name.startswith("/") or "\\" in name
                or not isinstance(spec, dict) or not is_hash(spec.get("sha256"))
                or not isinstance(spec.get("prefix"), str) or judge_path(spec["prefix"].rstrip("/")) is None):
            raise ValueError("bad bundle: " + str(name))
        out[name] = (spec["sha256"], spec["prefix"])
    return out


# ----------------------------------------------------------------------------- planning
def plan(judge_dir, remote, local, force):
    """Lists of (path, repo path, sha): Judge/ files to update, managed package files to replace, create-only
    set files to add. Raises ValueError when the manifest is not acceptable."""
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
    base = os.path.dirname(judge_dir)
    known_managed = local.get("managed", {}) if isinstance(local, dict) else {}
    managed = []
    for rel, spec in (remote.get("managed") or {}).items():
        p = managed_path(rel)
        if p is None or not good_spec(spec):
            raise ValueError("bad managed entry: " + str(rel))
        full = os.path.join(base, p)
        if not os.path.exists(full):
            changed = True
        elif force or known_managed.get(rel) != spec:
            changed = file_sha(full) != spec[0]
        else:
            changed = False
        if changed:
            managed.append((p, spec[1], spec[0]))
    creates = []
    for rel, spec in (remote.get("create_only") or {}).items():
        p = set_path(rel)
        if p is None or not good_spec(spec):
            raise ValueError("bad create-only entry: " + str(rel))
        if not os.path.exists(os.path.join(base, p)):
            creates.append((p, spec[1], spec[0]))
    return updates, managed, creates


def from_bundles(items, url, fresh, bundles, pool):
    """{Judge/ path: data} of the items that come in a bundle (a folder's zip, fetched when it holds at least
    BUNDLE_MIN of the needed files). A member is taken only when its hash is the one in the manifest; whatever a
    bundle lacks is downloaded on its own afterwards."""
    wanted = {p.replace(os.sep, "/"): sha for p, _, sha in items}
    jobs = []
    for name, (sha, prefix) in sorted(bundles.items()):
        mine = {rel: s for rel, s in wanted.items() if rel.startswith(prefix)}
        if len(mine) >= BUNDLE_MIN:
            jobs.append((name, sha, mine, pool.submit(fetch, url + name, MAX_BUNDLE, fresh, TRIES)))
    got = {}
    for name, sha, mine, job in jobs:
        data = job.result()
        if sha256(data) != sha:
            raise ValueError("hash mismatch: " + name)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            sizes = {i.filename: i.file_size for i in z.infolist()}
            for rel, s in mine.items():
                if sizes.get(rel, MAX_FILE + 1) <= MAX_FILE:
                    member = z.read(rel)
                    if sha256(member) == s:
                        got[rel] = member
    return got


def save(data, p, tmp):
    dest = os.path.join(tmp, p)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        f.write(data)
    if p.endswith(".py"):
        compile(data.decode("utf-8"), p, "exec")       # a syntax error must never reach Judge/


def download(items, tmp, url, fresh, pool, bundles=None):
    """Download every item into tmp (same relative paths), in parallel, from bundles where that saves requests,
    and verify its hash. Raises on any mismatch or failed download."""
    got = from_bundles(items, url, fresh, bundles, pool) if bundles else {}
    rest = [item for item in items if item[0].replace(os.sep, "/") not in got]
    sources = sorted({src for _, src, _ in rest})          # e.g. one template.cpp for all the N.cpp files
    data = dict(zip(sources, pool.map(lambda src: fetch(url + src.replace(os.sep, "/"), MAX_FILE, fresh, TRIES),
                                      sources)))
    for p, src, sha in rest:
        if sha256(data[src]) != sha:
            raise ValueError("hash mismatch: " + p)
        save(data[src], p, tmp)
    for p, _, _ in items:
        if p.replace(os.sep, "/") in got:
            save(got[p.replace(os.sep, "/")], p, tmp)


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


def replace_file(src, dest, bak):
    """Move src over dest; the old dest (if any) is kept at bak."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest):
        os.makedirs(os.path.dirname(bak), exist_ok=True)
        os.replace(dest, bak)
    os.replace(src, dest)


def apply(judge_dir, updates, managed, creates, tmp):
    """Swap the verified files in: data first, judge.py last; keep the old file in Judge/.backup/."""
    order = sorted(updates, key=lambda u: (u[0].endswith(".py"), u[0] == "judge.py"))
    for p, _, _ in order:
        replace_file(os.path.join(tmp, p), os.path.join(judge_dir, p), os.path.join(judge_dir, BACKUP, p))
    base = os.path.dirname(judge_dir)
    for p, _, _ in managed:
        replace_file(os.path.join(tmp, "_managed", p), os.path.join(base, p),
                     os.path.join(judge_dir, BACKUP, "_package", p))
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
def check(judge_dir=ROOT, force=False, notify=None):
    """Update Judge/ if the repo has a newer version. Returns a Result; never raises. notify(text) is called
    once before a big download (NOTIFY_MIN files or more), so the student knows why the judge waits."""
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
        remote = view(json.loads(data.decode("utf-8")))
        updates, managed, creates = plan(judge_dir, remote, local, force)
        bundles = plan_bundles(remote)
        if not updates and not managed and not creates and remote["version"] == version:
            return Result("current", f"Judge v{version} is up to date", version)
        count = len(updates) + len(managed) + len(creates)
        if notify is not None and count >= NOTIFY_MIN:
            notify(f"Downloading Judge v{remote['version']} ({count} files) ...")
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp)
        with concurrent.futures.ThreadPoolExecutor(WORKERS) as pool:
            download(updates, tmp, url, force, pool, bundles)
            download(managed, os.path.join(tmp, "_managed"), url, force, pool)
            download(creates, os.path.join(tmp, "_sets"), url, force, pool)
        test_new_judge(tmp)
        apply(judge_dir, updates, managed, creates, tmp)
        with open(os.path.join(tmp, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(remote, f, indent=0, sort_keys=True)      # what is installed now (format 2: its "full" part)
            f.write("\n")
        os.replace(os.path.join(tmp, "manifest.json"), os.path.join(judge_dir, "manifest.json"))
        names = [p.replace(os.sep, "/") for p, _, _ in updates + managed + creates]
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
