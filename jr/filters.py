"""Title, location, degree, requirements and salary rules. Pure functions, no network."""
import re

# ---------- location ----------
STATES = ("alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|florida|georgia|hawaii|idaho|illinois|"
          "indiana|iowa|kansas|kentucky|louisiana|maine|maryland|massachusetts|michigan|minnesota|mississippi|missouri|"
          "montana|nebraska|nevada|new hampshire|new jersey|new mexico|new york|north carolina|north dakota|ohio|oklahoma|"
          "oregon|pennsylvania|rhode island|south carolina|south dakota|tennessee|texas|utah|vermont|virginia|washington|"
          "west virginia|wisconsin|wyoming|district of columbia")
ST2 = "A[LKZR]|C[AOT]|DE|FL|GA|HI|I[ADLN]|K[SY]|LA|M[ADEINOST]|N[CDEHJMVY]|O[HKR]|PA|RI|S[CD]|T[NX]|UT|V[AT]|W[AIVY]|DC"
US_RE = re.compile(r"\b(usa|u\.s\.a?\.?|united states|any state|nationwide|us[- ]based|us only|" + STATES + r")\b|\bUS\b|\bU\.S\b", re.I)
US_CASE = re.compile(r"(?:,|-|–|\(|\bremote)\s*(?:" + ST2 + r")\b|\b(?:" + ST2 + r")\s*(?:,|-|–)\s*(?:US|USA|United States)\b")
RALEIGH = re.compile(r"\b(raleigh|durham|cary|morrisville|chapel hill|research triangle|rtp|apex|wake forest|holly springs|garner)\b", re.I)
NOT_RALEIGH = re.compile(r"\b(county durham|durham,? (uk|england|on|ontario|nh)|darlington)\b", re.I)
REMOTE = re.compile(r"\b(remote|work from home|wfh|telecommut\w*|virtual|home[- ]based|anywhere|distributed)\b", re.I)
NOT_REMOTE = re.compile(r"\b(no remote|not remote|non[- ]remote|on[- ]?site only|100% on[- ]?site|remote (not|is not) (available|an option))\b", re.I)
FOREIGN = re.compile(
    r"\b(canada|uk|u\.k\.|united kingdom|england|scotland|europe|emea|apac|latam|eu|india|germany|france|spain|ireland|poland|"
    r"brazil|mexico|australia|japan|singapore|israel|netherlands|portugal|argentina|colombia|philippines|romania|serbia|"
    r"ukraine|turkey|italy|sweden|denmark|norway|finland|hungary|czech|bulgaria|greece|macedonia|armenia|peru|chile|"
    r"costa rica|vietnam|china|korea|pakistan|egypt|nigeria|kenya|south africa|uae|dubai|malaysia|indonesia|thailand|taiwan|"
    r"new zealand|switzerland|austria|belgium|lithuania|latvia|estonia|croatia|slovakia|slovenia|puerto rico|international|"
    r"british columbia|ontario|quebec|alberta|london|berlin|paris|dublin|toronto|vancouver|montreal|bangalore|bengaluru|"
    r"hyderabad|pune|chennai|mumbai|delhi|tokyo|sydney|melbourne|amsterdam|prague|warsaw|krakow|kraków|lisbon|madrid|"
    r"barcelona|bogot[aá]|medell[ií]n|buenos aires|s[aã]o paulo|manila|kyiv|cairo|tel aviv|cet|cest|gmt|amer|martinique)\b",
    re.I)
US_NAMES = {"us", "usa", "united states", "united states of america", "u.s.", "u.s.a."}
STRONG_REMOTE_DESC = re.compile(
    r"\b(fully remote|100% remote|remote[- ]first|this (is a|role is|position is)( \w+){0,2} remote|remote (role|position|opportunity)|"
    r"work from (home|anywhere)|work remotely from anywhere in the (us|u\.s\.|united states))\b", re.I)


def _one(text, country, remote_flag, title):
    """Classify one location. Returns 'ok' | 'raleigh' | 'check' | 'uscity' | 'usonly' | 'drop'."""
    t = (text or "").strip()
    c = (country or "").strip().lower()
    is_us_c = c in US_NAMES
    foreign_c = bool(c) and not is_us_c
    foreign = foreign_c or (bool(FOREIGN.search(t)) and not (is_us_c or US_RE.search(t) or US_CASE.search(t)))
    if foreign:
        return "drop"
    if RALEIGH.search(t) and not NOT_RALEIGH.search(t):
        return "raleigh"
    us = is_us_c or bool(US_RE.search(t) or US_CASE.search(t))
    remote = (remote_flag is True or bool(REMOTE.search(t)) or bool(REMOTE.search(title or ""))) and not NOT_REMOTE.search(t)
    if remote and us:
        return "ok"
    if remote:
        return "check"
    if us:
        bare = re.sub(r"[^a-z]", "", t.lower()) in ("", "us", "usa", "unitedstates", "unitedstatesofamerica")
        return "usonly" if bare else "uscity"
    return "drop"


def classify(locs, remote_flag=None, title="", desc_text=""):
    """locs: list of (text, country). Returns (kind, why). kind: 'ok' | 'check' | 'drop'."""
    locs = [(t, c) for t, c in (locs or []) if (t or c)] or [("", "")]
    res = [_one(t, c, remote_flag, title) for t, c in locs]
    if "raleigh" in res:
        return "ok", "Raleigh area"
    if "ok" in res:
        return "ok", ""
    if "check" in res:
        return "check", "Remote, but country not stated"
    strong = bool(desc_text and STRONG_REMOTE_DESC.search(desc_text[:6000]))
    if "usonly" in res:
        return ("check", "US location, remote not confirmed") if (strong or remote_flag is True or not desc_text) else ("drop", "")
    if "uscity" in res and strong:
        return "check", "Office location listed, description mentions remote"
    return "drop", ""


# ---------- title ----------
class Titles:
    def __init__(self, cfg):
        j = lambda k: re.compile("|".join(f"(?:{p})" for p in cfg.get(k) or ["(?!)"]), re.I)
        self.inc, self.hard, self.soft, self.strong = j("include"), j("exclude"), j("exclude_soft"), j("strong")
        self.ai = j("ai_terms")
        self.skip = {s.lower() for s in cfg.get("skip_companies", [])}

    def ok(self, title):
        t = title or ""
        if not self.inc.search(t) or self.hard.search(t):
            return False
        return not self.soft.search(t) or bool(self.strong.search(t))

    def is_ai(self, title):
        return bool(self.ai.search(title or ""))


# ---------- degree ----------
DEG = re.compile(r"(?i)\bbachelor|\bbaccalaureate|\bundergraduate degree|\bmaster'?s?\s+(?:degree|of|in)\b|\bdoctorate\b|\bdegree\b|"
                 r"(?-i:\b(?:BS|BA|BSc|B\.S\.?|B\.A\.?|MS|M\.S\.?|MSc|PhD|Ph\.D\.?)\b(?=\s*(?:/|or\b|in\b|degree|,|\()))")
DEG_NOISE = re.compile(r"(?i)\b(high|some|certain|greater|large|significant|varying)\s+degrees?\b|\bdegrees? of\b|\d+[- ]degree|\bMS (office|sql|excel|word|teams|azure|dynamics|project|access)\b")
ALT = re.compile(
    r"(?i)equivalent|\bor\b[^.;]{0,60}\bexperience|experience[^.;]{0,40}(substitut|in lieu|considered|accepted)|in lieu|"
    r"\bprefer(red|ably|ence)?\b|\ba plus\b|nice[- ]to[- ]have|desir(ed|able)|\bbonus\b|not required|\boptional\b|\bideally\b|"
    r"\bor\s+\d+\+?\s*(years|yrs)|\bor (related|relevant|comparable|commensurate|similar|practical)\b[^.;]{0,30}(experience|training)|"
    r"\bstrongly? preferred|\bhelpful\b|\bbeneficial\b|pursuing")
PREF_HEAD = re.compile(r"(?i)prefer|nice[- ]to[- ]have|bonus|plus|desir|extra|stand ?out|good to have|ideal")


def is_heading(ln):
    if ln.startswith("## "):
        return True
    if ln.startswith("• ") or len(ln) > 80:
        return False
    return ln.endswith(":") or (len(ln) < 60 and not re.search(r"[.!?]$", ln) and len(ln.split()) <= 8)


def degree(lines):
    """'required' | 'alt' | 'none' | 'unknown' (no text)."""
    if not lines:
        return "unknown"
    pref, seen, n = False, False, len(lines)
    for i, ln in enumerate(lines):
        if is_heading(ln):
            pref = bool(PREF_HEAD.search(ln))
            if not DEG.search(ln):
                continue
        if not DEG.search(ln) or (DEG_NOISE.search(ln) and not re.search(r"(?i)bachelor|master|B\.?S\b|PhD", ln)):
            continue
        seen = True
        ctx = ln + " " + (lines[i + 1] if i + 1 < n and lines[i + 1].lower().lstrip("• ").startswith(("or ", "and/or ")) else "")
        if pref or ALT.search(ctx):
            continue
        return "required"
    return "alt" if seen else "none"


# ---------- requirements ----------
REQ_HEAD = re.compile(
    r"(?i)requirement|qualification|what you('ll| will)? (need|bring|have)|what we('re| are) looking for|who you are|about you|"
    r"you (have|are|bring|might be)|must[- ]have|skills|experience|your (background|profile|expertise)|minimum|basic|"
    r"you('ll| will) need|what you offer|you should have|ideal candidate|we('d| would) love|criteria")
STOP_HEAD = re.compile(
    r"(?i)responsibilit|what you('ll| will) (do|be doing|work on)|benefit|perks|about (us|the (company|team|role))|compensation|"
    r"equal opportunity|why (join|us|work)|what we offer|the role|your (role|impact|mission)|duties|day[- ]to[- ]day|salary|pay range|location")
REQ_LINE = re.compile(r"(?i)\b(\d\+? ?(years|yrs)|experience (with|in|using|testing)|proficien|knowledge of|familiar|hands[- ]on|"
                      r"degree|bachelor|strong (understanding|background|experience)|expertise in|ability to)\b")


def requirements(lines, limit=4, width=150):
    best, cur, mode = [], None, None
    for ln in lines:
        if is_heading(ln):
            h = ln.lstrip("# ").strip()
            if PREF_HEAD.search(h) and not re.search(r"(?i)requir|minimum|basic|must", h):
                mode = "pref"
            elif REQ_HEAD.search(h) and not STOP_HEAD.search(h):
                mode = "req"
            else:
                mode = "other"
            continue
        if mode == "req" and ln.startswith("• "):
            best.append(ln[2:].strip())
    if not best:
        best = [ln[2:].strip() for ln in lines if ln.startswith("• ") and REQ_LINE.search(ln)]
    out, seen = [], set()
    for b in best:
        b = re.sub(r"\s+", " ", b).strip(" ;.")
        if len(b) < 12 or b.lower() in seen:
            continue
        seen.add(b.lower())
        out.append(b if len(b) <= width else b[:width - 1].rsplit(" ", 1)[0] + "…")
        if len(out) >= limit:
            break
    return out


# ---------- salary ----------
_N = r"(\d{2,3}(?:,\d{3})(?:\.\d{2})?|\d{2,3}(?:\.\d)?\s?[kK])"
SAL_Y = re.compile(r"\$\s?" + _N + r"\s*(?:USD)?\s*(?:-|–|—|to|and)\s*\$?\s?" + _N)
SAL_H = re.compile(r"\$\s?(\d{2,3}(?:\.\d{1,2})?)\s*(?:-|–|—|to)\s*\$?\s?(\d{2,3}(?:\.\d{1,2})?)\s*(?:/|per|an|a)\s*(?:hr|hour)", re.I)


def _num(s):
    s = s.replace(",", "").strip()
    return float(s[:-1]) * 1000 if s[-1] in "kK" else float(s)


def salary_from(text):
    t = text or ""
    m = SAL_Y.search(t)
    if m:
        lo, hi = _num(m.group(1)), _num(m.group(2))
        if 20000 <= lo <= hi <= 900000:
            return f"${lo:,.0f} – ${hi:,.0f}"
    m = SAL_H.search(t)
    if m:
        return f"${m.group(1)} – ${m.group(2)} / hour"
    return ""
