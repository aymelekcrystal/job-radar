"""Shared helpers: HTTP, dates, money, HTML -> text lines."""
import html, json, re, threading, time
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import requests

UA = {"User-Agent": "job-radar/2.0 (personal job alert bot; github.com/aymelekcrystal/job-radar)"}
NOW = datetime.now(timezone.utc)
ET = ZoneInfo("America/New_York")
_local = threading.local()


def session():
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
        _local.s.headers.update(UA)
    return _local.s


MAX_SECONDS, MAX_BYTES = 90, 60_000_000


class NotFound(Exception):
    pass


def http(url, method="GET", retries=2, timeout=30, **kw):
    """GET/POST with small backoff. Raises NotFound on 404/410, RuntimeError on other failures."""
    last = None
    for attempt in range(retries + 1):
        try:
            r = session().request(method, url, timeout=(10, timeout), stream=True, **kw)
            body, start = [], time.time()
            for chunk in r.iter_content(65536):          # hard limits: a slow or huge answer cannot stall a scan
                body.append(chunk)
                if time.time() - start > MAX_SECONDS or sum(map(len, body)) > MAX_BYTES:
                    r.close()
                    raise requests.ReadTimeout("answer too slow or too large")
            r._content, r._content_consumed = b"".join(body), True
        except requests.RequestException as ex:
            last = f"{type(ex).__name__}"
            time.sleep(1.5 * (attempt + 1))
            continue
        if r.status_code in (404, 410):
            raise NotFound(url)
        if r.status_code in (429, 500, 502, 503, 504):
            last = f"HTTP {r.status_code}"
            time.sleep(3 * (attempt + 1))
            continue
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code}")
        return r
    raise RuntimeError(last or "failed")


def iso(v):
    """Any date (epoch s/ms, ISO, RFC822, 'November 10, 2026') -> UTC ISO string, or ''."""
    if v in (None, "", "None", "nan", "NaT"):
        return ""
    try:
        if isinstance(v, datetime):
            d = v
        elif isinstance(v, (int, float)) or str(v).isdigit():
            n = float(v)
            d = datetime.fromtimestamp(n / 1000 if n > 1e11 else n, timezone.utc)
        else:
            s = str(v).strip().replace(" UTC", "+00:00")
            try:
                d = datetime.fromisoformat(s.replace("Z", "+00:00"))
            except ValueError:
                try:
                    d = parsedate_to_datetime(s)
                except Exception:
                    d = datetime.strptime(s, "%B %d, %Y")
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).isoformat(timespec="seconds")
    except Exception:
        return ""


def age_hours(s, now=None):
    if not s:
        return None
    return ((now or NOW) - datetime.fromisoformat(s)).total_seconds() / 3600


def money(lo, hi, cur="$", per=""):
    try:
        lo, hi = float(lo or 0), float(hi or 0)
    except (TypeError, ValueError):
        return ""
    if not lo and not hi:
        return ""
    f = lambda n: f"{cur}{n:,.0f}" if n >= 1000 else f"{cur}{n:,.2f}".replace(".00", "")
    out = f"{f(lo)} – {f(hi)}" if lo and hi and lo != hi else f(lo or hi)
    return f"{out} / {per}" if per else out


_BLOCK = re.compile(r"<\s*(br|/p|/div|/h[1-6]|/li|/ul|/ol|/tr|/section|/table)[^>]*>", re.I)
_LI = re.compile(r"<\s*li[^>]*>", re.I)
_HEAD = re.compile(r"<\s*h[1-6][^>]*>", re.I)
_TAG = re.compile(r"<[^>]+>")
_BULLET = re.compile(r"^\s*(?:[•·▪●◦■□\-–—*]|\d{1,2}[.)])\s+")


_FLAT_HEAD = re.compile(
    r"\s(?=(?:Basic|Minimum|Required|Preferred|Desired|Additional|Key|Job|Essential|Core)?\s?"
    r"(?:Qualifications|Requirements|Responsibilities|Skills|Education|Experience|Duties|Benefits|Overview)(?: Include| and Experience| & Experience)?\s?:)"
    r"|\s(?=(?:What You(?:'ll| Will) (?:Do|Need|Bring)|What We(?:'re| Are) Looking For|Who You Are|About (?:You|Us|the Role|The Role)|"
    r"Nice to Have|Must Haves?|Position Overview|Job Description|Why Join)\b)")


def _flat(s):
    """A description flattened to one line: break before section names and between sentences."""
    s = _FLAT_HEAD.sub("\n## ", s)
    s = re.sub(r"(## [^\n:]{3,60}):\s", r"\1\n", s)
    s = re.sub(r"(?<=[a-z0-9\)])([.!?;])\s+(?=[A-Z0-9])", r"\1\n", s)
    return s


def to_lines(text):
    """HTML or plain text -> list of clean lines. Bullets start with '• ', headings with '## '."""
    if not text:
        return []
    s = str(text)
    if "&lt;" in s and "<" not in s.replace("&lt;", ""):
        s = html.unescape(s)                      # Greenhouse double-encodes its HTML
    elif "&lt;p" in s or "&lt;li" in s or "&lt;div" in s:
        s = html.unescape(s)
    if "<" not in s and "\n" not in s.strip() and len(s) > 400:
        s = _flat(s)
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s)
    s = _LI.sub("\n• ", s)
    s = _HEAD.sub("\n## ", s)
    s = _BLOCK.sub("\n", s)
    s = _TAG.sub(" ", s)
    s = html.unescape(s).replace("\xa0", " ").replace("\u200b", "")
    out = []
    for ln in s.split("\n"):
        ln = re.sub(r"[ \t\r\f\v]+", " ", ln).strip()
        if not ln or ln in ("•", "##"):
            continue
        if not ln.startswith(("• ", "## ")) and _BULLET.match(ln):
            ln = "• " + _BULLET.sub("", ln)
        out.append(ln)
    return out


def ld_jobposting(page_html):
    """Extract a schema.org JobPosting object from a page's ld+json, or None."""
    for m in re.finditer(r'(?is)<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', page_html or ""):
        try:
            d = json.loads(m.group(1).strip())
        except Exception:
            continue
        stack = d if isinstance(d, list) else [d]
        for o in stack:
            if isinstance(o, dict) and "@graph" in o:
                stack.extend(o["@graph"])
            if isinstance(o, dict) and "JobPosting" in str(o.get("@type")):
                return o
    return None
