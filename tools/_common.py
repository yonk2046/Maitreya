"""Shared utilities for SCD Engine fetch scripts.
Pure stdlib — no third-party deps.
"""

import os
import sys
import json
import subprocess
import tempfile
import urllib.request
import urllib.error
from html.parser import HTMLParser
from datetime import datetime

CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0 Safari/537.36"
)
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def log(*args, **kwargs):
    """Print to stderr so stdout stays JSON-clean."""
    print(*args, file=sys.stderr, flush=True, **kwargs)


def http_get(url, timeout=15, headers=None):
    """Simple GET with UA, returns bytes."""
    h = {"User-Agent": DEFAULT_UA}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def http_get_json(url, timeout=15):
    return json.loads(http_get(url, timeout=timeout).decode("utf-8"))


def chrome_render(url, timeout_seconds=90, virtual_time_budget_ms=10000):
    """Render a JS-heavy page with headless Chrome, return rendered HTML as str.

    Note: Chrome 132+ headless=new can take 30-60s for first-run profile init.
    Default timeout 90s gives margin. Subsequent runs are faster (~10-15s).
    """
    if not os.path.exists(CHROME_PATH):
        raise RuntimeError(f"Chrome not found at {CHROME_PATH}")
    user_data_dir = tempfile.mkdtemp(prefix="chrome-scd-")
    try:
        proc = subprocess.run(
            [
                CHROME_PATH,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-background-networking",
                "--disable-component-update",
                "--disable-default-apps",
                "--disable-sync",
                "--disable-translate",
                "--metrics-recording-only",
                "--user-data-dir=" + user_data_dir,
                f"--virtual-time-budget={virtual_time_budget_ms}",
                "--dump-dom",
                url,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout_seconds,
        )
        return proc.stdout.decode("utf-8", errors="replace")
    finally:
        # best-effort cleanup
        try:
            import shutil
            shutil.rmtree(user_data_dir, ignore_errors=True)
        except Exception:
            pass


class TableExtractor(HTMLParser):
    """Extracts all <tr><td>cells</td></tr> rows from HTML, returning list[list[str]]."""

    def __init__(self):
        super().__init__()
        self.in_tr = False
        self.in_cell = False
        self.cell_text = ""
        self.row = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.in_tr = True
            self.row = []
        elif tag in ("td", "th"):
            self.in_cell = True
            self.cell_text = ""

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.in_cell:
            self.row.append(self.cell_text.strip())
            self.in_cell = False
        elif tag == "tr" and self.in_tr:
            self.rows.append(self.row)
            self.in_tr = False

    def handle_data(self, data):
        if self.in_cell:
            self.cell_text += data


def extract_table_rows(html, min_cells=3):
    p = TableExtractor()
    p.feed(html)
    return [r for r in p.rows if any(c.strip() for c in r) and len(r) >= min_cells]


def is_etf(code):
    return isinstance(code, str) and len(code) >= 2 and code.startswith("00")


def today_str():
    return datetime.now().strftime("%Y-%m-%d")


def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def parse_int_safe(s):
    try:
        return int(str(s).replace(",", "").replace("+", "").strip())
    except (ValueError, AttributeError):
        return 0


def parse_float_safe(s):
    try:
        return float(str(s).replace(",", "").strip())
    except (ValueError, AttributeError):
        return 0.0
