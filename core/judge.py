#!/usr/bin/env python3
"""
POSN Camp 1 Practice Judge
==========================

Usage (inside a Mock_K folder, e.g. Mock_3, with the judge in ../Judge)
  python3 ../Judge/judge.py                    judge the whole set (1.cpp ... 8.cpp in this folder)
  python3 ../Judge/judge.py 5.cpp              judge problem 5 of this set   (or just: python3 ../Judge/judge.py 5)

Usage (anywhere)
  python3 judge.py SOLUTION.cpp K-P            judge one solution for set K, problem P   (e.g. 3-5)
  python3 judge.py --set K FOLDER              judge a whole mock exam set (files 1.cpp ... 8.cpp in FOLDER)
  python3 judge.py --set K                     show the problems of mock exam set K
  python3 judge.py --list                      list all sets and problems

Options
  --tl SECONDS     time limit per test (default 1.0)
  --ml MB          memory limit per test (default: the problem's, usually 64 MB)
  --diff N         show up to N differing lines for the first failed test (default 3, 0 = off)
  --stop           stop at the first failed test
  --ascii          plain ASCII drawing (for old consoles)
  --no-color       disable colors
  --update         check for a new judge version now (otherwise checked at most once every 10 minutes)
  --no-update      do not check for a new version this time

Requirements: Python 3.7+ and g++ in PATH (Linux / macOS / Windows).
Output comparison: line by line, ignoring trailing spaces and trailing empty lines.
Score: share of tests passed (with subtasks: each subtask's points x share of its tests passed).
"""
import glob
import json
import locale
import os
import re
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True      # no __pycache__ in Judge/ (updater.py is imported from there)
try:
    import updater                  # Judge/updater.py: self-update from the GitHub repo
except Exception:                   # missing or broken: the judge works without it
    updater = None
WIDTH = 64
PY = "python" if os.name == "nt" else "python3"
OUTPUT_LIMIT = 64 * 1024 * 1024     # bytes of stdout kept per test; more than this = Wrong Answer
COMPILE_TIMEOUT = 60                # seconds
STACK_BYTES = 256 * 1024 * 1024     # stack size for the judged program (like most online judges)
MEMORY_LIMIT_MB = 64                # default memory limit per test (the statements); problems.json "ml" overrides
STDERR_KEEP = 8 * 1024              # bytes of the judged program's stderr kept (shown after a crash)
WARNINGS_SHOWN = 6                  # g++ warning lines printed after a successful compile

# ----------------------------------------------------------------------------- styling
class Style:
    def __init__(self, color=True, ascii_only=False, tty=True):
        self.color = color
        self.ascii = ascii_only
        self.tty = tty

    def c(self, code, s):
        return f"\033[{code}m{s}\033[0m" if self.color else s

    def bold(self, s): return self.c("1", s)
    def dim(self, s): return self.c("2", s)
    def green(self, s): return self.c("32", s)
    def red(self, s): return self.c("31", s)
    def yellow(self, s): return self.c("33", s)
    def magenta(self, s): return self.c("35", s)
    def cyan(self, s): return self.c("36", s)
    def blue(self, s): return self.c("34", s)

    # box drawing
    @property
    def chars(self):
        if self.ascii:
            return dict(tl="+", tr="+", bl="+", br="+", h="-", v="|", ok="+", bad="x", full="#", empty=".",
                        star="*", nostar=".", dot="*", arrow=">")
        return dict(tl="╭", tr="╮", bl="╰", br="╯", h="─", v="│", ok="✔", bad="✘", full="█", empty="░",
                    star="★", nostar="☆", dot="•", arrow="›")


def char_width(c):
    """Terminal columns of one character: Thai vowel/tone marks take 0, CJK takes 2."""
    if ord(c) < 0x300:
        return 1
    if unicodedata.combining(c) or unicodedata.category(c) in ("Mn", "Me", "Cf"):
        return 0
    return 2 if unicodedata.east_asian_width(c) in ("W", "F") else 1


def visible_len(s):
    out, i = 0, 0
    while i < len(s):
        if s[i] == "\033":
            while i < len(s) and s[i] != "m":
                i += 1
        else:
            out += char_width(s[i])
        i += 1
    return out


def box(st, lines, color_fn=None):
    ch = st.chars
    paint = color_fn or (lambda x: x)
    print(paint(ch["tl"] + ch["h"] * (WIDTH - 2) + ch["tr"]))
    for ln in lines:
        pad = WIDTH - 4 - visible_len(to_ascii(ln) if st.ascii else ln)
        print(paint(ch["v"]) + " " + ln + " " * max(pad, 0) + " " + paint(ch["v"]))
    print(paint(ch["bl"] + ch["h"] * (WIDTH - 2) + ch["br"]))


def rule(st, title=""):
    ch = st.chars
    if title:
        t = f" {title} "
        print(st.dim(ch["h"] * 2) + st.bold(t) + st.dim(ch["h"] * max(WIDTH - 2 - len(t), 2)))
    else:
        print(st.dim(ch["h"] * WIDTH))


def bar(st, frac, width=24):
    ch = st.chars
    n = round(frac * width)
    col = st.green if frac >= 0.999 else (st.yellow if frac >= 0.4 else st.red)
    return col(ch["full"] * n) + st.dim(ch["empty"] * (width - n))


def stars(st, tier):
    ch = st.chars
    return st.yellow(ch["star"] * tier) + st.dim(ch["nostar"] * (3 - tier))


def installed_version():
    """Version of the installed package (Judge/manifest.json), '' in the source repo."""
    try:
        with open(os.path.join(ROOT, "manifest.json"), encoding="utf-8") as f:
            return str(json.load(f).get("version", ""))
    except (OSError, ValueError):
        return ""


def title(st, text):
    """First line of the header box: the title and, in an installed package, 'Judge vX.Y'."""
    ver = installed_version()
    return st.bold(st.cyan(text)) + (st.dim(f"  Judge v{ver}") if ver else "")


VERDICT = {
    "AC": ("Accepted", "green"),
    "WA": ("Wrong Answer", "red"),
    "TLE": ("Time Limit Exceeded", "yellow"),
    "RE": ("Runtime Error", "magenta"),
    "MLE": ("Memory Limit Exceeded", "blue"),
}

ASCII_MAP = {"·": "-", "…": "...", "→": "->", "‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"}


def to_ascii(s):
    if s.isascii():
        return s
    res = []
    for c in s:
        if ord(c) < 128:
            res.append(c)
        elif c in ASCII_MAP:
            res.append(ASCII_MAP[c])
        else:
            base = unicodedata.normalize("NFKD", c).encode("ascii", "ignore").decode("ascii")
            res.append(base or "?")
    return "".join(res)


class AsciiOut:
    """Transliterate output to plain ASCII for consoles without Unicode support."""

    def __init__(self, out):
        self.out = out

    def write(self, s):
        self.out.write(to_ascii(s))

    def flush(self):
        self.out.flush()


# ----------------------------------------------------------------------------- data
# test data folders Mock_K/P, first found wins: Judge/problems/batch (student package), ../problems/batch
# (judge.py run from core/ in the repo), Judge/tests (older student packages)
DATA_DIRS = (os.path.join(ROOT, "problems", "batch"),
             os.path.normpath(os.path.join(ROOT, os.pardir, "problems", "batch")),
             os.path.join(ROOT, "tests"))


def data_file(name):
    """problems.json / sets.json: next to the test data, else next to judge.py (older packages)."""
    p = os.path.join(data_root(), name)
    return p if os.path.exists(p) else os.path.join(ROOT, name)


def load_meta():
    p = data_file("problems.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return {int(k): v for k, v in json.load(f).items()}
    return {}


def load_sets():
    p = data_file("sets.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return []


def student_layout():
    """True when the test data is in Mock_K/P folders (student package or repo), not the source tree's work/."""
    return any(os.path.isdir(d) for d in DATA_DIRS)


def data_root():
    """Test data root: the first of DATA_DIRS that exists, else work/ in the full source tree."""
    for d in DATA_DIRS:
        if os.path.isdir(d):
            return d
    return os.path.join(ROOT, "work")


def tests_dir(pdir):
    """Folder holding the .in/.out files of a problem folder (PROBLEM/tests/ or the folder itself)."""
    t = os.path.join(pdir, "tests")
    return t if os.path.isdir(t) else pdir


def has_tests(d):
    return os.path.isdir(d) and bool(glob.glob(os.path.join(glob.escape(tests_dir(d)), "*.in")))


def find_problem(arg, meta):
    parts = arg.split("-")
    if len(parts) == 2 and all(x.isdecimal() for x in parts):
        k, p = int(parts[0]), int(parts[1])
        sets = load_sets()
        if 1 <= k <= len(sets) and 1 <= p <= len(sets[k - 1]["problems"]):
            return find_problem(str(sets[k - 1]["problems"][p - 1]), meta)
        return None, None
    if arg.isdecimal():                 # a bank id: never a folder of the current directory
        n = int(arg)
        if n in meta and meta[n].get("dir"):
            d = os.path.join(data_root(), meta[n]["dir"])
            if os.path.isdir(d):
                return os.path.abspath(d), n
    for d in (arg, os.path.join(ROOT, arg), os.path.join(data_root(), arg)):
        if not arg.isdecimal() and has_tests(d):
            d = os.path.abspath(d)
            if os.path.basename(d.rstrip("/\\")) == "tests" and has_tests(os.path.dirname(d)):
                d = os.path.dirname(d)          # PROBLEM/tests given instead of PROBLEM
            real = os.path.normcase(os.path.realpath(d))
            for n, m in meta.items():          # a folder listed in problems.json
                md = m.get("dir")
                if md and os.path.normcase(os.path.realpath(os.path.join(data_root(), md))) == real:
                    return d, n
            if student_layout():
                return d, None
            base = os.path.basename(d.rstrip("/\\"))
            num = int(base.split("_")[0]) if base.split("_")[0].isdecimal() else None
            return d, num
    key = arg.split("_")[0]
    if key.isdecimal():
        n = int(key)
        if n in meta and meta[n].get("dir"):
            d = os.path.join(data_root(), meta[n]["dir"])
            if os.path.isdir(d):
                return d, n
        cands = glob.glob(os.path.join(glob.escape(data_root()), f"{n:02d}_*"))
        if len(cands) == 1:
            return cands[0], n
    return None, None


def where_in_sets(num):
    for s in load_sets():
        if num in s["problems"]:
            return f"Set {s['set']} · #{s['problems'].index(num) + 1}"
    return f"{num:02d}" if num is not None else "?"


def normalize(b):
    text = b.decode("utf-8", "replace")
    # ignore trailing ASCII whitespace " \t\r\f\v" (also the \r of CRLF), not e.g. a no-break space;
    # for usual ASCII text plain rstrip() does the same, and is much faster
    if text.isascii() and not any(c in text for c in "\x1c\x1d\x1e\x1f"):
        lines = [ln.rstrip() for ln in text.split("\n")]
    else:
        lines = [ln.rstrip(" \t\r\f\v") for ln in text.split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def test_key(path):
    name = os.path.basename(path)[:-3]
    return (0, int(name), name) if name.isdecimal() else (1, 0, name)


SAMPLE_COUNT = [6]  # number of statement samples of the problem being judged (tests 01..k)


SUBTASKS = [None]  # [{"points": 40, "tests": ["01", ...]}, ...] or None (score = share of tests passed)
TEST_NAMES = [[]]  # names of all tests of the problem being judged (also those --stop did not run)


MEM_LIMIT = [MEMORY_LIMIT_MB]   # MB, of the problem being judged
ML_OPTION = [None]              # --ml MB overrides the problem's limit


def set_sample_count(meta, num):
    m = meta.get(num, {}) if num is not None else {}
    SAMPLE_COUNT[0] = int(m.get("samples", 6))
    SUBTASKS[0] = m.get("subtasks")
    ml = m.get("ml", MEMORY_LIMIT_MB)
    MEM_LIMIT[0] = ML_OPTION[0] or (ml if isinstance(ml, int) and ml > 0 else MEMORY_LIMIT_MB)


def subtasks_usable():
    """Use the subtasks only if they split exactly the tests on disk (no test missing, extra or in two subtasks);
    otherwise (e.g. a test was added to the folder later) score by the share of tests passed."""
    subs = SUBTASKS[0]
    # a hand-edited problems.json may have e.g. "points": "40" or "tests": [1, 2]: fall back, do not crash
    if not isinstance(subs, list) or not subs or not all(
            isinstance(s, dict) and type(s.get("points")) is int and s["points"] >= 0
            and isinstance(s.get("tests"), list) and s["tests"] and all(isinstance(x, str) for x in s["tests"])
            for s in subs):
        return False
    listed = [x for s in subs for x in s["tests"]]
    return sum(s["points"] for s in subs) == 100 and sorted(listed) == sorted(TEST_NAMES[0])


def compute_score(results, total):
    """Score out of 100, rounded down. Problems with subtasks: each subtask gives points x (share of its tests
    passed); tests that were not run (--stop) count as failed. Returns (score, [(points, got, passed, tests)])."""
    if not total:
        return 0, None
    ok = set(r[0] for r in results if r[1] == "AC")
    if not subtasks_usable():
        return 100 * len(ok) // total, None
    parts, num, den = [], 0, 1
    for sub in SUBTASKS[0]:
        t = sub["tests"]
        p = sum(1 for x in t if x in ok)
        parts.append((sub["points"], (sub["points"] * p, len(t)), p, len(t)))
        num, den = num * len(t) + sub["points"] * p * den, den * len(t)     # exact fractions, no float rounding
    return num // den, parts


def fmt_points(frac):
    """Points of one subtask: whole number, or one decimal (6.7 for 60 x 1/9)."""
    a, b = frac
    if a % b == 0:
        return str(a // b)
    tenths = (20 * a + b) // (2 * b)          # rounded to 0.1
    return f"{tenths // 10}.{tenths % 10}"


def is_sample(name):
    return name.isdecimal() and int(name) <= SAMPLE_COUNT[0]


# ----------------------------------------------------------------------------- core
def compile_source(src, outdir):
    """Compile src into outdir. Returns (exe or None, seconds, error lines, warning lines)."""
    exe = os.path.join(outdir, "prog" + (".exe" if os.name == "nt" else ""))
    src_abs = os.path.abspath(src)
    # -Wall: an uninitialized variable or an out-of-bounds index can work on the student's own compile and fail
    # here (-O2); the warning is shown after "Compiled". -Wno-sign-compare, -Wno-char-subscripts: i < v.size() and
    # count[c] are everywhere in contest code and harmless
    cmd = ["g++", "-O2", "-std=c++17", "-Wall", "-Wno-sign-compare", "-Wno-char-subscripts", "-o", exe, src_abs]
    if os.name == "nt":
        # Windows default stack is only 1 MB. -static: the program does not need libstdc++-6.dll at run time,
        # so another (incompatible) copy of that DLL earlier in PATH cannot make every test crash
        cmd[1:1] = [f"-Wl,--stack,{STACK_BYTES}", "-static"]
    inc = os.path.join(ROOT, "include")
    if os.path.isdir(inc):
        # fallback <bits/stdc++.h> for macOS (g++ = Apple clang); searched after the system headers,
        # so GNU g++ keeps using its own
        cmd[1:1] = ["-idirafter", inc]
    # English messages, plain ASCII quotes; g++'s own temp files (cc*.s) go to outdir, so they are removed
    # with it even when the compiler is killed (timeout, Ctrl-C)
    env = dict(os.environ, LC_ALL="C", LANG="C", TMPDIR=outdir)
    t0 = time.perf_counter()
    while True:
        try:
            # own process group, so that a timeout or Ctrl-C also stops cc1plus (g++ only starts it)
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
                                 start_new_session=(os.name != "nt"))
        except FileNotFoundError:
            return None, 0, ["g++ not found. Please install a C++ compiler and add it to PATH."], []
        try:
            out, _ = p.communicate(timeout=COMPILE_TIMEOUT)
        except subprocess.TimeoutExpired:
            kill_tree(p)
            p.communicate()
            return None, COMPILE_TIMEOUT, [f"The compiler did not finish within {COMPILE_TIMEOUT} s."], []
        except BaseException:                    # Ctrl-C
            kill_tree(p)
            p.wait()
            raise
        # a MinGW without static libraries ("cannot find -lstdc++"): link the usual way instead
        if p.returncode != 0 and "-static" in cmd and b"cannot find -l" in out:
            cmd.remove("-static")
            continue
        break
    dt = time.perf_counter() - t0
    text = compiler_text(out, src_abs)
    if p.returncode != 0 or not os.path.exists(exe):
        msg = text.strip().splitlines()
        if "bits/stdc++.h" in text and "not found" in text:
            msg = ["Hint: your g++ is clang (macOS), which has no <bits/stdc++.h>, and the judge's",
                   "fallback (folder include/ next to judge.py) is missing. Include the headers you need",
                   "(<iostream>, <vector>, ...) or install GNU g++.", ""] + msg
        return None, dt, msg or [f"g++ exited with code {p.returncode}"], []
    return exe, dt, [], [ln for ln in text.splitlines() if ": warning:" in ln]


def compiler_text(out, src_abs):
    """g++ output as text, without the folder of the source file."""
    try:
        text = out.decode("utf-8")
    except UnicodeDecodeError:          # e.g. Windows g++ printing a Thai path in the ANSI code page
        text = out.decode(locale.getpreferredencoding(False), "replace")
    d = os.path.dirname(src_abs)
    text = text.replace(d + os.sep, "")
    if os.name == "nt":
        text = text.replace(d.replace("\\", "/") + "/", "")
    return text


def print_warnings(st, warns, quiet=False):
    """The g++ -Wall warnings of a program that compiled."""
    if not warns:
        return
    n = len(warns)
    head = f"{n} g++ warning{'s' if n != 1 else ''}"
    if quiet:
        print("  " + st.dim(head))
        return
    print("  " + st.yellow(head) + st.dim("  (read them: such code can pass here and fail on the real grader)"))
    for ln in warns[:WARNINGS_SHOWN]:
        print("    " + st.dim(clip(ln.replace(" warning: ", " "), 100)))
    if n > WARNINGS_SHOWN:
        print("    " + st.dim(f"... {n - WARNINGS_SHOWN} more"))


def print_compile_error(st, msg):
    print(st.red(st.bold("Compilation Error")))
    rule(st)
    for ln in msg[:25]:
        print("  " + st.dim(clip(ln, 200)))
    if len(msg) > 25:
        more = [ln for ln in msg[25:] if ": error:" in ln]
        print(st.dim(f"  ... ({len(msg) - 25} more lines" + ("; the other errors:)" if more else ")")))
        for ln in more[:5]:
            print("  " + st.dim(clip(ln, 200)))


def kill_tree(p):
    """Kill a process and everything it started (g++ -> cc1plus, as, ld)."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            os.killpg(p.pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        p.kill()
    except OSError:
        pass


def raise_stack_limit():
    """Raise this process's stack limit once; the judged programs inherit it (Linux / macOS)."""
    try:
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_STACK)
        want = STACK_BYTES if hard == resource.RLIM_INFINITY else min(STACK_BYTES, hard)
        if soft != resource.RLIM_INFINITY and soft < want:
            resource.setrlimit(resource.RLIMIT_STACK, (want, hard))
    except Exception:
        pass


LAUNCH_FAILED = -1000          # returncode used when the judged program could not be started at all
LAUNCH_ERROR = [""]
UNSTARTABLE = set()           # programs that could not be started even after waiting: do not wait again
LAUNCH_WAITS = (0.05, 0.1, 0.2, 0.4, 0.8, 1.5)    # seconds between launch attempts


def start_program(exe):
    """Popen the judged program. A just-built program can be briefly locked ('Text file busy' on Linux,
    an antivirus scan of a new .exe on Windows): wait a little and try again instead of failing."""
    for wait in (LAUNCH_WAITS if exe not in UNSTARTABLE else ()) + (None,):
        try:
            return subprocess.Popen([exe], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as e:
            LAUNCH_ERROR[0] = e.strerror or str(e)
            if wait is None or not os.path.exists(exe):
                UNSTARTABLE.add(exe)
                return None
            time.sleep(wait)


def exit_code(status):
    """returncode of a waited-for POSIX child: -signal when killed by a signal."""
    return -os.WTERMSIG(status) if os.WIFSIGNALED(status) else os.WEXITSTATUS(status)


def wait_program(p, timeout):
    """Wait for the judged program like p.wait(timeout) and return its peak memory in bytes (None if unknown).
    Windows: GetProcessMemoryInfo on the handle after the exit (exact). Linux / macOS: the program's own
    high-water mark is read every millisecond while it runs (/proc VmHWM, proc_pid_rusage); ru_maxrss from
    wait4 is only a fallback, because it also counts the judge's own image before the exec."""
    if os.name == "nt":
        p.wait(timeout=timeout)
        return windows_peak_memory(p)
    read = linux_peak_memory if sys.platform.startswith("linux") else (
        mac_peak_memory if sys.platform == "darwin" else lambda pid: None)
    deadline = None if timeout is None else time.perf_counter() + timeout
    delay = 0.0002
    peak = None
    while True:
        m = read(p.pid)
        if m is not None and (peak is None or m > peak):
            peak = m
        pid, status, ru = os.wait4(p.pid, os.WNOHANG)
        if pid == p.pid:
            p.returncode = exit_code(status)
            if peak is None:
                peak = ru.ru_maxrss * (1 if sys.platform == "darwin" else 1024)      # macOS: bytes, Linux: KB
            return peak
        if deadline is not None and time.perf_counter() >= deadline:
            raise subprocess.TimeoutExpired(p.args, timeout)
        time.sleep(delay)
        delay = min(delay * 2, 0.001)


def linux_peak_memory(pid):
    """VmHWM (peak resident size) of a running process, bytes."""
    try:
        with open(f"/proc/{pid}/status", "rb") as f:
            for line in f:
                if line.startswith(b"VmHWM:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


MAC_RUSAGE = [None]     # (libproc, buffer) once loaded; False when proc_pid_rusage is not usable


def mac_peak_memory(pid):
    """ri_lifetime_max_phys_footprint of a running process (proc_pid_rusage, RUSAGE_INFO_V4), bytes."""
    if MAC_RUSAGE[0] is False:
        return None
    try:
        import ctypes
        if MAC_RUSAGE[0] is None:
            lib = ctypes.CDLL("/usr/lib/libproc.dylib")
            lib.proc_pid_rusage.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
            MAC_RUSAGE[0] = (lib, ctypes.create_string_buffer(16 + 64 * 8))
        lib, buf = MAC_RUSAGE[0]
        if lib.proc_pid_rusage(pid, 4, buf) != 0:
            return None
        fields = struct.unpack_from("<40Q", buf, 16)         # after the 16-byte uuid
        resident, lifetime_max = fields[6], fields[28]
        if 0 < lifetime_max < (1 << 44) and lifetime_max >= resident:
            return int(lifetime_max)
    except Exception:
        MAC_RUSAGE[0] = False
    return None


def windows_peak_memory(p):
    """PeakWorkingSetSize of a finished program (its handle is still open), or None."""
    try:
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (f, ctypes.c_size_t) for f in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                               "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                                               "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
        fn = ctypes.windll.psapi.GetProcessMemoryInfo
        fn.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        c = Counters()
        c.cb = ctypes.sizeof(c)
        if fn(int(p._handle), ctypes.byref(c), c.cb):
            return int(c.PeakWorkingSetSize)
    except Exception:
        pass
    return None


def run_program(exe, data, hard_limit):
    """Run exe with stdin=data. Returns (stdout bytes, returncode or None if killed, seconds, output_overflow,
    peak memory in bytes or None, last bytes of stderr)."""
    p = start_program(exe)
    if p is None:                # e.g. the .exe was removed or blocked by an antivirus program
        return b"", LAUNCH_FAILED, 0.0, False, None, b""
    t0 = time.perf_counter()
    chunks = []
    err = bytearray()
    state = {"size": 0, "overflow": False}

    def feed():
        try:
            p.stdin.write(data)
        except OSError:          # program exited / closed stdin without reading everything
            pass
        try:
            p.stdin.close()
        except OSError:
            pass

    def drain():
        while True:
            try:
                b = p.stdout.read1(1 << 16)    # returns what is available (read() would wait for 64 KB)
            except (OSError, ValueError):
                break
            if not b:
                break
            if state["size"] + len(b) > OUTPUT_LIMIT:
                state["overflow"] = True
                try:
                    p.kill()
                except OSError:
                    pass
                break
            state["size"] += len(b)
            chunks.append(b)

    def drain_err():
        while True:
            try:
                b = p.stderr.read1(1 << 16)
            except (OSError, ValueError):
                break
            if not b:
                break
            err.extend(b)
            if len(err) > 2 * STDERR_KEEP:     # keep only the end (the exception message is there)
                del err[:-STDERR_KEEP]

    tw = threading.Thread(target=feed, daemon=True)
    tr = threading.Thread(target=drain, daemon=True)
    te = threading.Thread(target=drain_err, daemon=True)
    tw.start()
    tr.start()
    te.start()
    killed = False
    peak = None
    try:
        peak = wait_program(p, hard_limit)
    except subprocess.TimeoutExpired:
        killed = True
        p.kill()
        peak = wait_program(p, None)
    finally:
        if p.poll() is None:     # e.g. Ctrl-C
            p.kill()
            p.wait()
    dt = time.perf_counter() - t0
    tr.join(5)
    te.join(5)
    tw.join(5)
    for stream, t in ((p.stdout, tr), (p.stderr, te)):
        if not t.is_alive():    # still alive only if a process started by the program keeps the pipe open
            try:
                stream.close()
            except OSError:
                pass
    return b"".join(chunks), (None if killed else p.returncode), dt, state["overflow"], peak, bytes(err[-STDERR_KEEP:])


def run_tests(exe, pdir, st, tl, show_diff, stop, quiet=False):
    ch = st.chars
    # glob.escape: the judge folder may contain [ ] (e.g. "POSN [2026]"), which glob would read as a pattern
    ins = sorted((f for f in glob.glob(os.path.join(glob.escape(tests_dir(pdir)), "*.in"))
                  if os.path.exists(f[:-3] + ".out")),
                 key=test_key)
    TEST_NAMES[0] = [os.path.basename(f)[:-3] for f in ins]
    hard = tl * 2 + 0.5
    results = []
    first_fail = None
    if not quiet:
        print(st.dim(f"  {'test':<6}{'kind':<9}{'verdict':<24}{'time':>8}"))
    for fin in ins:
        name = os.path.basename(fin)[:-3]
        with open(fin, "rb") as f:
            data = f.read()
        for attempt in range(2):
            got, code, dt, overflow, peak, err = run_program(exe, data, hard)
            if peak is not None and peak > MEM_LIMIT[0] * 1024 * 1024:
                v = "MLE"
            elif code is None and not overflow:
                v = "TLE"
            elif overflow:
                v = "WA"
            elif code != 0:
                v = "RE"
            elif dt > tl:
                v = "TLE"
            else:
                with open(fin[:-3] + ".out", "rb") as f:
                    v = "AC" if normalize(got) == normalize(f.read()) else "WA"
            # a run that finished but was a little slow is measured once more (system noise,
            # antivirus scanning a fresh .exe, ...); a killed run is not repeated
            if not (v == "TLE" and code is not None):
                break
        if v == "TLE":
            dt = max(dt, tl)
        results.append((name, v, dt, peak))
        if v != "AC" and first_fail is None:
            first_fail = (name, v, fin, got, overflow, code, peak, err)
        if quiet:       # set mode: one character per test, printed as soon as it is known
            print(st.green(ch["ok"]) if v == "AC" else getattr(st, VERDICT[v][1])(v[0]), end="", flush=True)
        else:
            label, col = VERDICT[v]
            mark = ch["ok"] if v == "AC" else ch["bad"]
            kind = "sample" if is_sample(name) else "hidden"
            tstr = f"{dt:.2f} s" if v != "TLE" else f">{tl:.1f} s"
            cell = f"{mark} {label}"
            print("  " + st.bold(name) + (" " * max(6 - len(name), 1)) + st.dim(f"{kind:<9}")
                  + getattr(st, col)(cell) + " " * (24 - len(cell)) + st.dim(f"{tstr:>8}"))
        if v != "AC" and stop:
            break
    return results, first_fail, len(ins)


INPUT_LINES = 6     # input lines shown in the failure box
COL = 26            # width of the "expected" and "your output" columns


def rel_path(p):
    """p relative to the current folder when that is shorter (e.g. ../Judge/tests/Mock_3/5/01.in)."""
    try:
        r = os.path.relpath(p)
    except ValueError:          # Windows: another drive
        return p
    return r if len(r) < len(p) else p


def show_input(st, fin):
    with open(fin, "rb") as f:
        data = f.read()
    n = data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
    if n == 0:
        print("  " + st.dim("input (empty)"))
        return
    print("  " + st.dim(f"input ({n} line{'s' if n != 1 else ''})"))
    lines = data[:20000].decode("utf-8", "replace").split("\n")
    for ln in lines[:min(n, INPUT_LINES)]:
        print("    " + clip("".join(visible_char(c) for c in ln.rstrip("\r")[:200]), WIDTH - 6))
    if n > INPUT_LINES:
        print("    " + st.dim(f"... {n - INPUT_LINES} more line{'s' if n - INPUT_LINES != 1 else ''}"))


def diagnose(exp, out, diffs):
    """One-line summary of a wrong answer."""
    le, lo = len(exp), len(out)
    plural = lambda k, w: f"{k} {w}{'s' if k != 1 else ''}"
    if not out:
        return "your program printed nothing"
    if lo < le and out == exp[:lo]:
        return f"your output stops early ({plural(le - lo, 'line')} missing)"
    if lo > le and out[:le] == exp:
        return f"{plural(lo - le, 'extra line')} at the end"
    if le == lo and all(words(a) == words(b) for a, b in zip(exp, out)):
        return "only the spaces differ (shown as \u00b7)"
    if [w for x in exp for w in words(x)] == [w for x in out for w in words(x)]:
        return "same values, different line breaks"
    if "\n".join(exp).lower() == "\n".join(out).lower():
        return "only upper/lower case differs"
    i = diffs[0]
    return f"line {i + 1} differs" if len(diffs) == 1 else f"{len(diffs)} lines differ, first at line {i + 1}"


def cell(st, s, start, show_spaces):
    """Text of one table cell (raw string s from index start) and its visible width."""
    if s is None:
        t = "(end)"
    elif s == "":
        t = "(empty line)"
    else:
        t = "".join(visible_char(c) for c in s[start:start + 2 * COL])
        if show_spaces:
            t = t.replace(" ", "_" if st.ascii else "\u00b7")
        t = clip("..." + t if start else t, COL)
    if st.ascii:
        t = to_ascii(t)
    return t, visible_len(t)


def show_table(st, exp, out, diffs, show_diff, show_spaces):
    ch = st.chars
    indent = 2 + 4 + 3          # "  " + line number + mark
    print("  " + st.dim(f"{'line':>4}   {'expected':<{COL}}  your output"))
    if not out:
        rows, marked = list(range(min(len(exp), INPUT_LINES))), set()
    else:
        marked = set(diffs[:show_diff])
        rows = sorted({r for d in marked for r in (d - 1, d) if r >= 0})
    prev = None
    for r in rows:
        if prev is not None and r > prev + 1:
            print("  " + st.dim(f"{'...':>4}"))
        prev = r
        e = exp[r] if r < len(exp) else None
        g = out[r] if r < len(out) else None
        start, caret = 0, None
        if r in marked and e is not None and g is not None:
            j = first_diff(e, g)
            if visible_len("".join(visible_char(c) for c in e[:j])) > COL - 8:
                start = max(0, j - 10)
                k = e.rfind(" ", 0, start + 1)          # start at the beginning of a value when close by
                if k != -1 and j - k <= 16:
                    start = k + 1
            head = "".join(visible_char(c) for c in g[start:j])
            if show_spaces:
                head = head.replace(" ", "_")
            caret = visible_len(to_ascii(head) if st.ascii else head) + (3 if start else 0)
            if caret > COL - 1:
                caret = None
        te, we = cell(st, e, start, show_spaces)
        if not out:
            tg, wg = ("(nothing)", 9) if r == 0 else ("", 0)
        else:
            tg, wg = cell(st, g, start, show_spaces)
        num = f"{r + 1:>4}"
        gap = " " * (COL - we + 2) if tg else ""
        if r in marked:
            line = num + " " + st.red(ch["bad"]) + " " + st.green(te) + gap + st.red(tg)
        else:
            line = st.dim(num + "   " + te + gap + tg)
        print("  " + line)
        if caret is not None:
            print(" " * (indent + COL + 2 + caret) + st.red("^"))
    if not out and len(exp) > INPUT_LINES:
        print("  " + st.dim(f"{'':>4}   ... {len(exp) - INPUT_LINES} more expected line" + ("s" if len(exp) - INPUT_LINES != 1 else "")))
    elif len(diffs) > show_diff:
        print("  " + st.dim(f"{'':>4}   ... {len(diffs) - show_diff} more differing line" + ("s" if len(diffs) - show_diff != 1 else "")))


WINDOWS_CRASHES = {0xC0000005: "access violation", 0xC00000FD: "stack overflow",
                   0xC0000094: "division by zero", 0xC0000409: "abort",
                   0xC0000374: "heap corruption (writing outside an array?)",
                   0xC000001D: "illegal instruction",
                   0xC0000135: "a DLL was not found (check the g++ folder in PATH)",
                   0xC0000139: "wrong DLL version (another libstdc++ DLL earlier in PATH)"}


def crash_reason(code):
    """' (exit code ...)' / ' (signal ...)' for a crash, or '' when nothing useful is known."""
    if code is None or code == 0:
        return ""
    if code < 0:                                # POSIX: killed by a signal
        try:
            name = signal.Signals(-code).name
        except ValueError:
            name = ""
        meaning = {"SIGSEGV": "invalid memory access", "SIGFPE": "division by zero",
                   "SIGABRT": "abort", "SIGBUS": "invalid memory access", "SIGKILL": "killed"}.get(name, "")
        return f" (signal {-code}" + (f" {name}: {meaning}" if meaning else f" {name}" if name else "") + ")"
    if os.name == "nt" and code == 3:           # MinGW abort(): uncaught exception, failed assert, .at()
        return " (exit code 3: abort)"
    if code > 255 and code in WINDOWS_CRASHES:
        return f" (exit code 0x{code:08X}: {WINDOWS_CRASHES[code]})"
    if code > 255:
        return f" (exit code 0x{code:08X})"
    return f" (exit code {code})"


def show_failure(st, first_fail, show_diff):
    if not first_fail or show_diff <= 0:
        return
    name, v, fin, got, overflow, code, peak, err = first_fail
    rule(st, f"First failure: test {name} · " + (f"sample {int(name)}" if is_sample(name) else "hidden"))
    label, col = VERDICT[v]
    exp = out = diffs = None
    if v == "WA" and overflow:
        summary = f"printed over {OUTPUT_LIMIT // (1024 * 1024)} MB and was stopped"
    elif v == "WA":
        with open(fin[:-3] + ".out", "rb") as f:
            exp = normalize(f.read())
        out = normalize(got)
        diffs = [i for i in range(max(len(exp), len(out)))
                 if (exp[i] if i < len(exp) else None) != (out[i] if i < len(out) else None)]
        summary = diagnose(exp, out, diffs)
    elif v == "TLE":
        summary = "your program did not finish in time"
    elif v == "MLE":
        summary = f"your program used {peak / (1024 * 1024):.0f} MB, the limit is {MEM_LIMIT[0]} MB"
    elif code == LAUNCH_FAILED:
        summary = f"the judge could not start your program ({LAUNCH_ERROR[0]})"
    else:
        summary = "your program crashed" + crash_reason(code)
    if st.ascii:
        summary = summary.replace("\u00b7", "_")
    print("  " + getattr(st, col)(label) + st.dim(" · " + summary))
    print()
    show_input(st, fin)
    if exp is not None:
        print()
        show_table(st, exp, out, diffs, show_diff, summary.startswith("only the spaces"))
    if v == "RE":
        show_stderr(st, err)
    print()
    print("  " + st.dim("Input  ") + rel_path(fin))


def show_stderr(st, err, keep=5):
    """The last lines the program wrote to stderr: an exception message, a failed assert, a debug print."""
    lines = [ln for ln in err.decode("utf-8", "replace").replace("\r", "").split("\n") if ln.strip()]
    if not lines:
        return
    print()
    more = f" (last {keep} of {len(lines)} lines)" if len(lines) > keep else ""
    print("  " + st.dim("your program's stderr" + more))
    for ln in lines[-keep:]:
        print("    " + st.magenta(clip("".join(visible_char(c) for c in ln[:300]), 100)))


def first_diff(a, b):
    """Index of the first differing character (block compare first: fast also for very long lines)."""
    n, k, step = min(len(a), len(b)), 0, 1 << 14
    while k < n and a[k:k + step] == b[k:k + step]:
        k += step
    while k < n and a[k] == b[k]:
        k += 1
    return min(k, n)


def words(s):
    """Split on spaces and tabs only (a no-break space or CR is a real difference, not spacing)."""
    return [w for w in s.replace("\t", " ").split(" ") if w]


def visible_char(c):
    """Show characters that are invisible or move the cursor as escapes (CR, ESC, no-break space, ...)."""
    o = ord(c)
    if 32 <= o < 127 or c == "\t":
        return c
    if c == "\r":
        return "\\r"
    if o < 32 or 127 <= o <= 159:
        return "\\x%02x" % o
    if c.isspace() or unicodedata.category(c) == "Cf":     # e.g. U+00A0, U+200B, U+FEFF
        return "\\u%04x" % o
    return c


def clip(s, n=46):
    """Cut s to at most n terminal columns."""
    s = s.replace("\t", " ")
    if visible_len(s) <= n:
        return s
    out, w = [], 0
    for c in s:
        w += char_width(c)
        if w > n - 3:
            break
        out.append(c)
    return "".join(out) + "..."


def judge_one(src, pdir, num, meta, st, tl, show_diff, stop):
    set_sample_count(meta, num)
    m = meta.get(num, {})
    name = m.get("en", os.path.basename(pdir))
    tier = m.get("tier", 0)
    label = where_in_sets(num)
    srcname = os.path.basename(src)
    if st.ascii:                       # measure what will really be printed
        name, srcname = to_ascii(name), to_ascii(srcname)
    name = clip(name, WIDTH - 4 - 9 - visible_len(label) - 2 - (5 if tier else 2))
    head = [title(st, "POSN Camp 1 · Practice Judge"),
            f"Problem  {st.bold(label)}  {name}  " + (stars(st, tier) if tier else ""),
            f"Source   {clip(srcname, WIDTH - 4 - 9)}",
            f"Limits   {tl:.1f} s · {MEM_LIMIT[0]} MB per test"]
    box(st, head, st.dim)
    print()
    print("  " + st.dim("Compiling ..."), end="" if st.tty else "\n", flush=True)
    tmp = tempfile.mkdtemp(prefix="judge_")
    try:
        exe, ct, msg, warns = compile_source(src, tmp)
        print("\r  " if st.tty else "  ", end="")
        if not exe:
            print_compile_error(st, msg)
            print()
            rule(st, "Result")
            print("  Score   " + bar(st, 0) + "  " + st.bold("0") + " / 100   " + st.red("Compilation Error"))
            rule(st)
            return 0
        print(st.green("Compiled") + st.dim(f" in {ct:.2f} s"))
        print_warnings(st, warns)
        print()
        results, first_fail, total = run_tests(exe, pdir, st, tl, show_diff, stop)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    passed = sum(1 for r in results if r[1] == "AC")
    print()
    if first_fail and show_diff > 0:
        show_failure(st, first_fail, show_diff)
        print()
    summary(st, passed, total, results, tl)
    return compute_score(results, total)[0]


def summary(st, passed, total, results, tl):
    rule(st, "Result")
    score, subparts = compute_score(results or [], total)
    print(f"  Score   {bar(st, score / 100)}  {st.bold(str(score))} / 100   " + st.dim(f"({passed}/{total} tests)"))
    if subparts:
        print("  Subtask " + "   ".join(f"{i}: {fmt_points(got)}/{pts}" + st.dim(f" ({p}/{t} tests)")
                                      for i, (pts, got, p, t) in enumerate(subparts, 1)))
    if results:
        counts = {}
        for r in results:
            counts[r[1]] = counts.get(r[1], 0) + 1
        parts = []
        for v in ("AC", "WA", "TLE", "RE", "MLE"):
            if counts.get(v):
                parts.append(getattr(st, VERDICT[v][1])(f"{v} {counts[v]}"))
        if len(results) < total:
            parts.append(st.dim(f"not run {total - len(results)}"))
        print("  Tests   " + "   ".join(parts))
        if counts.get("TLE"):
            print("  Slowest " + st.dim(f">{tl:.1f} s"))
        else:
            print("  Slowest " + st.dim(f"{max(r[2] for r in results):.2f} s"))
        peaks = [r[3] for r in results if r[3] is not None]
        if peaks:
            print("  Memory  " + st.dim(f"peak {max(peaks) / (1024 * 1024):.1f} MB · limit {MEM_LIMIT[0]} MB"))
    if total and passed == total:
        print("  " + st.green(st.bold("ACCEPTED  All tests passed. Well done!")))
    elif subparts and subparts[0][2] == subparts[0][3] and any(r[1] in ("TLE", "RE", "MLE") for r in results) and all(
            r[1] != "WA" for r in results if is_sample(r[0])):
        # all of subtask 1 passed and subtask 2 fails because the program is too slow (TLE) or crashes (RE:
        # array / memory too big for n = 10^18), typical of a simulation. A wrong answer on a sample still gets
        # FIX THE SAMPLES FIRST, and only wrong answers on hidden tests get PARTIAL.
        print("  " + st.yellow(st.bold("SUBTASK 1 DONE")) + st.dim("  now look for a pattern/formula for the big cases"))
    elif results and any(r[1] != "AC" for r in results if is_sample(r[0])):
        print("  " + st.red(st.bold("FIX THE SAMPLES FIRST")) + st.dim("  run your program on the samples in the statement"))
    elif total:
        print("  " + st.yellow(st.bold("PARTIAL")) + st.dim("  samples pass; check edge cases, limits and long long"))
    else:
        print("  " + st.red("No tests found for this problem."))
    rule(st)


def cmd_list(meta, st):
    sets = load_sets()
    box(st, [st.bold(st.cyan("POSN Camp 1 · Mock exam sets")),
             f"{len(sets)} sets · {sum(len(s['problems']) for s in sets)} problems"], st.dim)
    for s in sets:
        print()
        print("  " + st.bold(f"Set {s['set']}") + st.dim(f"  {s.get('level_en', '')}"))
        for i, n in enumerate(s["problems"], 1):
            m = meta.get(n, {})
            print(f"    {s['set']}-{i:<3} {stars(st, m.get('tier', 0))}  {m.get('en', '?')}")


TEMPLATE_WORDS = ("#include <bits/stdc++.h> using namespace std; int32_t main() { "
                  "cin.tie(0); ios::sync_with_stdio(0); return 0; }").split()


def is_template(src):
    """True if src is still the untouched 1.cpp ... 8.cpp template (whitespace ignored)."""
    try:
        with open(src, "rb") as f:
            data = f.read(4096)
    except OSError:
        return False
    return data.decode("utf-8", "replace").lstrip("﻿").split() == TEMPLATE_WORDS


def cmd_set(k, folder, meta, sets, st, tl, show_diff):
    if not (1 <= k <= len(sets)):
        print(st.red(f"Set {k} does not exist (1-{len(sets)})."))
        return 1
    if folder is not None and not os.path.isdir(folder):
        print(st.red(f"Folder not found: {folder}"))
        return 1
    s = sets[k - 1]
    probs = s["problems"]
    head = [title(st, f"POSN Camp 1 · Mock Exam Set {k}"),
            f"{s.get('level_en', '')}",
            f"{len(probs)} problems · 3 hours · {100 * len(probs)} points"]
    box(st, head, st.dim)
    for i, n in enumerate(probs, 1):
        m = meta.get(n, {})
        print(f"  Problem {i}   {stars(st, m.get('tier', 0))}  " + st.bold(m.get("en", "?")))
    if folder is None:
        print()
        if student_layout():
            print(st.dim(f"  Save your solutions as 1.cpp ... {len(probs)}.cpp in folder Mock_{k}, then run there:"))
            print(f"  {PY} ../Judge/judge.py")
        else:
            print(st.dim(f"  Save your solutions as 1.cpp ... {len(probs)}.cpp in one folder, then run:"))
            print(f"  {PY} judge.py --set {k} FOLDER")
        return 0
    scores = []
    print()
    print("  " + st.dim("legend  ") + st.green(st.chars["ok"]) + st.dim(" accepted   ") + st.red("W") + st.dim(" wrong answer   ")
          + st.yellow("T") + st.dim(" time limit   ") + st.magenta("R") + st.dim(" runtime error   ") + st.blue("M") + st.dim(" memory"))
    for i, n in enumerate(probs, 1):
        src = os.path.join(folder, f"{i}.cpp")
        print()
        rule(st, f"Problem {i} · {meta.get(n, {}).get('en', '?')}")
        if not os.path.isfile(src):
            print("  " + st.dim(f"{i}.cpp not found - skipped (0 points)"))
            scores.append(0)
            continue
        if is_template(src):
            print("  " + st.dim(f"{i}.cpp is still the empty template - skipped (0 points)"))
            scores.append(0)
            continue
        pdir, _ = find_problem(str(n), meta)
        set_sample_count(meta, n)
        if not pdir:
            print("  " + st.red(f"Test data for problem {n} not found - skipped"))
            scores.append(0)
            continue
        tmp = tempfile.mkdtemp(prefix="judge_")
        try:
            exe, _, msg, warns = compile_source(src, tmp)
            if not exe:
                print("  ", end="")
                print_compile_error(st, msg)
                print(f"  {bar(st, 0)}  {st.bold('0')} / 100")
                scores.append(0)
                continue
            print("  ", end="", flush=True)
            results, first_fail, total = run_tests(exe, pdir, st, tl, show_diff, False, quiet=True)
            print()
            print_warnings(st, warns, quiet=True)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        sc = compute_score(results, total)[0]
        scores.append(sc)
        print(f"  {bar(st, sc / 100)}  {st.bold(str(sc))} / 100")
    print()
    rule(st, "Scoreboard")
    for i, (n, sc) in enumerate(zip(probs, scores), 1):
        name = clip(meta.get(n, {}).get("en", "?"), 28)
        print(f"  Problem {i}  " + st.dim(name) + " " * (30 - len(name)) + f"{bar(st, sc / 100, 16)} {sc:>4}")
    total = sum(scores)
    print()
    full = 100 * len(probs)
    print(f"  Total   {bar(st, total / full)}  {st.bold(str(total))} / {full}")
    rule(st)
    return 0


MOCK_DIR = re.compile(r"^mock[ _-]?0*([0-9]+)$", re.IGNORECASE)


def mock_set_of(folder):
    """Set number K of a folder named Mock_K (Mock_3, mock-03, ...), else None."""
    m = MOCK_DIR.match(os.path.basename(os.path.abspath(folder).rstrip("/\\")))
    return int(m.group(1)) if m else None


def prog_name():
    """judge.py as it was typed (../Judge/judge.py), or relative to the current folder when that is shorter."""
    return rel_path(sys.argv[0]) if sys.argv[0] else "judge.py"


def not_a_mock_folder(st, folder, name):
    """The set number comes from the folder name Mock_K; explain what to do when the folder has another name."""
    base = os.path.basename(os.path.abspath(folder).rstrip("/\\"))
    print(st.red(f"Cannot tell which set this is: the folder '{base}' is not named Mock_K (e.g. Mock_3)."))
    print(st.dim("  Rename the folder to Mock_K (K = set number), or give the set yourself, e.g. for set 3:"))
    if name is None:
        print(f"  {PY} {prog_name()} --set 3 .")
    else:
        print(f"  {PY} {prog_name()} \"{name}\" 3-{name[:-4] if name[:-4].isdecimal() else 5}")
    return 1


def usage(err=None):
    if err:
        print(f"Error: {err}")
        print(f"Run '{PY} {prog_name()} --help' for usage.")
    else:
        print(__doc__.replace("python3 ", PY + " "))
    return 0 if err is None else 2


def on_stop_signal(signum, frame):
    raise KeyboardInterrupt


KNOWN_FLAGS = {"--stop", "--ascii", "--no-color", "--color", "--list", "--help", "--update", "--no-update"}


def cmd_update(st):
    """--update: check the repo now and say what happened."""
    if updater is None:
        print(st.red("updater.py is missing next to judge.py; download the package again."))
        return 1
    print("  " + st.dim("Checking for updates ..."), flush=True)
    r = updater.check(ROOT, force=True)
    if r.status == "updated":
        print("  " + st.green(st.bold(f"Judge {r.message}")))
        for name in r.files[:15]:
            print("    " + st.dim(name))
        if len(r.files) > 15:
            print("    " + st.dim(f"... {len(r.files) - 15} more"))
        return 0
    if r.status == "current":
        print("  " + st.green(r.message))
        return 0
    print("  " + st.yellow(f"No update: {r.message}"))
    return 1


def self_update(st, argv):
    """Automatic check (at most once every 10 minutes). After an update, run the new judge with the same arguments
    and return its exit code; None = nothing happened, carry on."""
    if updater is None or "--no-update" in argv or os.environ.get("JUDGE_NO_UPDATE"):
        return None
    try:
        r = updater.check(ROOT)
    except Exception:
        return None
    if r.status != "updated":
        return None
    print("  " + st.dim(f"Judge {r.message}; restarting ..."))
    env = dict(os.environ, JUDGE_NO_UPDATE="1")
    try:
        return subprocess.call([sys.executable, os.path.abspath(__file__)] + argv, env=env)
    except OSError:
        return None


def main():
    argv = sys.argv[1:]
    original_argv = list(argv)
    opts = {"--tl": "1.0", "--diff": "3", "--ml": None}
    flags = set()
    pos = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if "=" in a and a.split("=", 1)[0] in ("--tl", "--diff", "--set", "--ml"):
            a, val = a.split("=", 1)
            argv[i:i + 1] = [a, val]
        if a in ("--tl", "--diff", "--set", "--ml"):
            if i + 1 >= len(argv):
                return usage(f"{a} needs a value")
            opts[a] = argv[i + 1]
            i += 2
        elif a in ("-h", "/?"):
            flags.add("--help")
            i += 1
        elif a.startswith("--") or (len(a) > 1 and a[0] == "-" and a[1].isalpha()):
            if a not in KNOWN_FLAGS:
                return usage(f"unknown option {a}")
            flags.add(a)
            i += 1
        else:
            pos.append(a)
            i += 1
    tty = sys.stdout.isatty()
    color = "--color" in flags or ("--no-color" not in flags and tty and not os.environ.get("NO_COLOR"))
    ascii_only = "--ascii" in flags
    if not ascii_only:
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            ascii_only = True
    if os.name == "nt" and color:
        os.system("")  # enable ANSI escape codes on Windows 10+
    if ascii_only:
        sys.stdout = AsciiOut(sys.stdout)
    st = Style(color, ascii_only, tty)
    if "--update" in flags:
        return cmd_update(st)
    code = self_update(st, original_argv)
    if code is not None:
        return code
    meta = load_meta()
    if os.name != "nt":
        raise_stack_limit()     # Windows: the stack size is set when linking (compile_source)
        for sig in (signal.SIGTERM, signal.SIGHUP):     # e.g. an IDE's stop button: clean up like Ctrl-C
            signal.signal(sig, on_stop_signal)

    if "--help" in flags:
        return usage()
    # explicit checks, not assert (assert is skipped under python -O / PYTHONOPTIMIZE)
    try:
        tl = float(opts["--tl"])
    except ValueError:
        tl = -1.0
    if not 0 < tl <= 60:            # also rejects nan
        return usage(f"--tl must be a number of seconds between 0 and 60 (got {opts['--tl']})")
    try:
        show_diff = int(opts["--diff"])
    except ValueError:
        show_diff = -1
    if show_diff < 0:
        return usage(f"--diff must be a whole number >= 0 (got {opts['--diff']})")
    if opts["--ml"] is not None:
        if not opts["--ml"].isdecimal() or not 1 <= int(opts["--ml"]) <= 65536:
            return usage(f"--ml must be a number of MB between 1 and 65536 (got {opts['--ml']})")
        ML_OPTION[0] = int(opts["--ml"])
    if "--list" in flags:
        cmd_list(meta, st)
        return 0
    if "--set" in opts:
        if not opts["--set"].isdecimal():
            return usage(f"--set needs a set number (got {opts['--set']})")
        if len(pos) > 1:
            return usage("--set takes one folder")
        if pos and not shutil.which("g++"):
            print(st.red("g++ not found. Please install a C++ compiler and add it to PATH."))
            return 1
        return cmd_set(int(opts["--set"]), pos[0] if pos else None, meta, load_sets(), st, tl, show_diff)
    if not pos:
        k = mock_set_of(os.getcwd())
        if k is None:
            if glob.glob("[1-9].cpp"):  # a set folder that was copied or renamed, e.g. "Mock_3 - Copy"
                return not_a_mock_folder(st, os.getcwd(), None)
            return usage()
        pos = ["."]                     # run inside Mock_K: judge the whole set
    if len(pos) == 1:
        a = pos[0]
        if a.isdecimal() and not os.path.exists(a) and mock_set_of(os.getcwd()) is not None:
            a = pos[0] = f"{int(a)}.cpp"    # inside Mock_3: 'judge.py 5' = 'judge.py 5.cpp' (like make 5 / judge 5)
        k = mock_set_of(a) if os.path.isdir(a) else None
        if k is not None:               # judge.py Mock_3  ->  --set 3 Mock_3
            if not shutil.which("g++"):
                print(st.red("g++ not found. Please install a C++ compiler and add it to PATH."))
                return 1
            return cmd_set(k, a, meta, load_sets(), st, tl, show_diff)
        k = mock_set_of(os.path.dirname(os.path.abspath(a))) if os.path.isfile(a) else None
        name = os.path.basename(a)
        if k is not None and name.lower().endswith(".cpp") and name[:-4].isdecimal():
            pos = [a, f"{k}-{int(name[:-4])}"]      # Mock_3/5.cpp  ->  5.cpp 3-5
        elif not os.path.exists(a) and (a.lower().endswith(".cpp") or mock_set_of(os.getcwd()) is not None):
            print(st.red(f"Source file not found: {a}"))
            print(st.dim("  Check the file name (e.g. 5.cpp, not 5.cpp.txt) and that you are in the Mock_K folder."))
            return 1
        elif os.path.isfile(a) and name.lower().endswith(".cpp"):
            if k is None:               # e.g. Mock_3 - Copy/5.cpp
                return not_a_mock_folder(st, os.path.dirname(os.path.abspath(a)), name)
            print(st.red(f"Cannot tell the problem number from the file name '{name}'."))   # e.g. 5_brute.cpp
            print(st.dim(f"  Name it 1.cpp ... 8.cpp, or give the problem as K-P, e.g.:"))
            print(f"  {PY} {prog_name()} \"{name}\" {k}-5")
            return 1
        else:
            return usage("expected SOLUTION.cpp and a problem (e.g. 3-5), "
                         "or run it inside a Mock_K folder (files 1.cpp ... 8.cpp)")
    if len(pos) != 2:
        return usage("expected SOLUTION.cpp and a problem (e.g. 3-5)")
    src, parg = pos
    if os.path.isfile(parg) and (not os.path.isfile(src) or
                                 (parg.lower().endswith(".cpp") and not src.lower().endswith(".cpp"))):
        src, parg = parg, src           # arguments given in the other order
    if not os.path.isfile(src):
        print(st.red(f"Source file not found: {src}"))
        return 1
    if student_layout() and parg.isdecimal():
        k = mock_set_of(os.path.dirname(os.path.abspath(src)))
        if k is None:
            return usage(f"use K-P to name a problem (e.g. 3-{parg} for set 3, problem {parg})")
        parg = f"{k}-{int(parg)}"         # inside Mock_3: '5.cpp 5' means problem 3-5
    pdir, num = find_problem(parg, meta)
    if not pdir:
        sets = load_sets()
        print(st.red(f"Problem not found: {parg}"))
        print(st.dim(f"  Use K-P with set K = 1-{len(sets)} and problem P = 1-8 (e.g. 3-5); see --list."))
        return 1
    if not shutil.which("g++"):
        print(st.red("g++ not found. Please install a C++ compiler and add it to PATH."))
        return 1
    judge_one(src, pdir, num, meta, st, tl, show_diff, "--stop" in flags)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        pass
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
