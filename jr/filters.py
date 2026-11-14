"""Title, location, degree, requirements and salary rules. Pure functions, no network."""
import re

# ---------- location ----------
STATES = ("alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|florida|georgia|hawaii|idaho|illinois|"
          "indiana|iowa|kansas|kentucky|louisiana|maine|maryland|massachusetts|michigan|minnesota|mississippi|missouri|"
          "montana|nebraska|nevada|new hampshire|new jersey|new mexico|new york|north carolina|north dakota|ohio|oklahoma|"
          "oregon|pennsylvania|rhode island|south carolina|south dakota|tennessee|texas|utah|vermont|virginia|washington|"
          "west virginia|wisconsin|wyoming|district of columbia")
ST2 = "A[LKZR]|C[AOT]|DE|FL|GA|HI|I[ADLN]|K[SY]|LA|M[ADEINOST]|N[CDEHJMVY]|O[HKR]|PA|RI|S[CD]|T[NX]|UT|V[AT]|W[AIVY]|DC"
US_RE = re.compile(r"\b(usa|u\.s\.a?\.?|united states|any state|nationwide|us[- ]based|us only|us states|" + STATES + r")\b|\bUS\b|\bU\.S\b", re.I)
AMBIG = {"DE", "IN", "CA", "CO", "AR", "IL", "ID", "MA", "PA", "ME", "AL", "GA", "SC", "MD", "MT", "NE", "TN"}   # also country codes
_CITY_ST = re.compile(r"([A-Za-z.]+)\s*,\s*(" + ST2 + r")\b")
_REM_ST = re.compile(r"(?:[Rr]emote|REMOTE|[Vv]irtual)\s*(?:,|-|–|/|\(|\s)\s*(" + ST2 + r")\b")
_ST_US = re.compile(r"\b(?:" + ST2 + r")\s*,\s*(?:US|USA)\b")
_3PART = re.compile(r",\s*[A-Z]{2},\s*([A-Z]{2})(?:,|\s|$)")
FOREIGN_CODE = re.compile(r"\b(MX|SG|GB|BR|PH|TR|JP|KR|CN|AU|NZ|IE|NL|PL|ES|FR|IT|SE|CH|AT|BE|PT|RO|UA|ZA|AE|TH|VN|MY|HK|TW|THB|EUR)\b")
RALEIGH = re.compile(r"\b(raleigh|durham|cary|morrisville|chapel hill|research triangle|rtp|apex|wake forest|holly springs|garner)\b", re.I)
NOT_RALEIGH = re.compile(r"\b(county durham|durham,? (uk|england|on|ontario|nh)|darlington)\b", re.I)
REMOTE = re.compile(r"\b(remote|work from home|wfh|telecommut\w*|virtual|home[- ]based|anywhere|distributed)\b", re.I)
NOT_REMOTE = re.compile(r"\b(no remote|not (a )?remote|non[- ]remote|on[- ]?site only|100% on[- ]?site|remote (not|is not) (available|an option))\b", re.I)
FOREIGN = re.compile(
    r"\b(canada|uk|u\.k\.|united kingdom|england|scotland|europe|emea|apac|latam|eu|india|germany|deutschland|france|spain|ireland|"
    r"poland|brazil|brasil|mexico|méxico|australia|japan|singapore|israel|netherlands|portugal|argentina|colombia|philippines|"
    r"romania|serbia|ukraine|turkey|türkiye|italy|sweden|denmark|norway|finland|hungary|czech|bulgaria|greece|macedonia|armenia|"
    r"peru|chile|costa rica|vietnam|china|korea|pakistan|egypt|nigeria|kenya|south africa|uae|dubai|malaysia|indonesia|thailand|"
    r"taiwan|new zealand|switzerland|austria|belgium|lithuania|latvia|estonia|croatia|slovakia|slovenia|puerto rico|international|"
    r"british columbia|ontario|quebec|alberta|london|berlin|munich|münchen|paris|dublin|toronto|vancouver|montreal|bangalore|"
    r"bengaluru|hyderabad|pune|chennai|mumbai|delhi|tokyo|sydney|melbourne|amsterdam|prague|warsaw|krakow|kraków|lisbon|madrid|"
    r"barcelona|bogot[aá]|medell[ií]n|buenos aires|s[aã]o paulo|manila|kyiv|cairo|tel aviv|guadalajara|ciudad de m[eé]xico|"
    r"cet|cest|gmt|amer|martinique|m/w/d|m/f/d)\b", re.I)
US_NAMES = {"us", "usa", "united states", "united states of america", "u.s.", "u.s.a."}
STRONG_REMOTE_DESC = re.compile(
    r"\b(fully remote|100% remote|remote[- ]first|this (is a|role is|position is)( \w+){0,2} remote|remote (role|position|opportunity)|"
    r"work remotely from anywhere in the (us|u\.s\.|united states))\b", re.I)
US_DESC = re.compile(
    r"(?i)\b((anywhere|located|based|resid\w+|live|living|candidates?|applicants?|remote(ly)?|work(ing)?) (with)?in the (contiguous |continental |lower 48 )?"
    r"(united states|u\.s\.a?\.?|usa?\b)|(authorized|eligible|eligibility|authorization) to work in the (united states|u\.s\.a?\.?|usa?\b)|"
    r"(u\.s\.|us|usa)[- ]based (candidates?|applicants?|remote|only)|remote \(?(us|usa|u\.s\.|united states)\b)")
_GENERIC = re.compile(r"(?i)remote|work from home|wfh|virtual|anywhere|worldwide|global|worker|role|work|position|n/?a|full[- ]?time|only|based|location|not specified|unavailable")


_TITLE_US = re.compile(r"\b(?:US|USA|U\.S\.?|United States)\b")


def us_evidence(t):
    if US_RE.search(t) or _ST_US.search(t):
        return True
    for m in _CITY_ST.finditer(t):
        if m.group(1).lower() not in ("remote", "virtual", "hybrid", "wfh", "telework"):
            return True
        if m.group(2) not in AMBIG:
            return True
    return any(m.group(1) not in AMBIG for m in _REM_ST.finditer(t))


def _one(text, country, remote_flag, title):
    """Classify one location. Returns 'ok' | 'raleigh' | 'check' | 'uscity' | 'usonly' | 'drop'."""
    t = (text or "").strip()
    c = (country or "").strip().lower()
    is_us_c = c in US_NAMES
    us = is_us_c or us_evidence(t) or bool(_TITLE_US.search(title or ""))
    three = _3PART.search(t)
    foreign = (bool(c) and not is_us_c) or (bool(three) and three.group(1) != "US" and not is_us_c) or \
              ((bool(FOREIGN.search(t)) or bool(FOREIGN_CODE.search(t)) or bool(FOREIGN.search(title or ""))) and not us)
    if foreign:
        return "drop"
    if RALEIGH.search(t) and not NOT_RALEIGH.search(t):
        return "raleigh"
    remote = (remote_flag is True or bool(REMOTE.search(t)) or bool(REMOTE.search(title or ""))) \
        and not NOT_REMOTE.search(t) and not NOT_REMOTE.search(title or "")
    if remote and us:
        return "ok"
    if remote:
        rest = re.sub(r"[^a-z]", "", _GENERIC.sub(" ", t.lower()))
        return "check" if not rest else "drop"         # a place we cannot recognise is not evidence of the US
    if us:
        bare = re.sub(r"[^a-z]", "", t.lower()) in ("", "us", "usa", "unitedstates", "unitedstatesofamerica")
        return "usonly" if bare else "uscity"
    return "drop"


def classify(locs, remote_flag=None, title="", desc_text=""):
    """locs: list of (text, country). Returns (kind, why). kind: 'ok' | 'check' | 'drop'."""
    locs = [(t, c) for t, c in (locs or []) if (t or c)] or [("", "")]
    denied = bool(desc_text and NOT_REMOTE.search(desc_text[:400]))
    if denied:
        remote_flag = False
    res = [_one(t, c, remote_flag, title) for t, c in locs]
    if "raleigh" in res:
        return "ok", "Raleigh area"
    if "ok" in res:
        return "ok", ""
    if "check" in res:
        if desc_text and not denied and US_DESC.search(desc_text[:8000]):
            return "ok", ""                               # location only says "Remote", the description names the US
        return "check", "Remote, but country not stated"
    if "usonly" in res and not denied and desc_text and STRONG_REMOTE_DESC.search(desc_text[:6000]):
        return "ok", ""                                   # "United States" + the description itself says the role is remote
    if "usonly" in res and not denied and not desc_text:
        return "check", "US location, remote not confirmed"
    if "uscity" in res and not denied and desc_text and STRONG_REMOTE_DESC.search(desc_text[:6000]):
        return "check", "Office city listed, but the description says remote"
    return "drop", ""


SW = [r"selenium", r"playwright", r"cypress", r"appium", r"test automation|automat(ed|ion) test", r"api test", r"postman|rest ?assured",
      r"\bsoftware\b", r"\bsdlc\b", r"\bagile\b|\bscrum\b", r"\bjira\b", r"\bpython\b", r"\bjava(script)?\b|typescript", r"ci/cd|jenkins|github|gitlab",
      r"regression", r"test (cases?|plans?|scripts?)", r"web application|mobile app", r"\bllm\b|machine learning", r"\bsql\b", r"\bsdet\b"]
NONSW = [r"\bc?gmp\b", r"\bfda\b", r"iso ?13485|iso ?9001|as9100", r"manufactur", r"sterili", r"pharma", r"\bcapa\b", r"batch record",
         r"six sigma", r"supplier quality", r"gd&t", r"clinical trial", r"laborator", r"assembly line|production floor", r"\bppap\b|\bfmea\b",
         r"calibration", r"nuclear", r"welding", r"chemical", r"call (center|centre)|call monitoring", r"food safety"]
SW = [re.compile(p, re.I) for p in SW]
NONSW = [re.compile(p, re.I) for p in NONSW]


_TEST_TITLE = re.compile(r"(?i)\b(qa|qe|sdet|test|tester|testing|quality|eval\w*)\b")
_TEST_WORDS = [re.compile(p, re.I) for p in (r"selenium", r"playwright", r"cypress", r"appium", r"test automation|automated test",
               r"test (cases?|plans?|scripts?|framework)", r"regression", r"\bqa\b", r"quality assurance", r"\bsdet\b", r"unit tests?|integration tests?")]


def testing_role(title, text):
    """'Automation Engineer' without a testing word in the title must be about testing in its description."""
    if _TEST_TITLE.search(title or "") or not re.search(r"(?i)\bautomation (engineer|developer)\b", title or ""):
        return True
    return sum(bool(p.search(text or "")) for p in _TEST_WORDS) >= 3


def software_role(strong, text):
    """Generic titles ('Quality Engineer') must look like software work in the description."""
    if strong or not text:
        return True
    sw, non = sum(bool(p.search(text)) for p in SW), sum(bool(p.search(text)) for p in NONSW)
    return sw >= 1 and sw > non


# ---------- title ----------
class Titles:
    def __init__(self, cfg):
        j = lambda k: re.compile("|".join(f"(?:{p})" for p in cfg.get(k) or ["(?!)"]), re.I)
        self.inc, self.hard, self.soft, self.strong = j("include"), j("exclude"), j("exclude_soft"), j("strong")
        self.ai = j("ai_terms")
        self.ece_inc, self.ece_exc = j("ece_include"), j("ece_exclude")
        self.skip = {s.lower() for s in cfg.get("skip_companies", [])}

    def qa(self, title):
        """The main target: software testing / QA / AI evaluation titles."""
        t = title or ""
        if not self.inc.search(t) or self.hard.search(t):
            return False
        return not self.soft.search(t) or bool(self.strong.search(t))

    def ece(self, title):
        """Neighbouring roles for the "Ece" tab (support, solutions, implementation, analyst, product owner ...)."""
        t = title or ""
        return bool(self.ece_inc.search(t)) and not self.hard.search(t) and not self.ece_exc.search(t)

    def ok(self, title):
        return self.qa(title) or self.ece(title)

    def is_strong(self, title):
        return bool(self.strong.search(title or ""))

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
    bullets = any(l.startswith("• ") for l in lines)
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
        if mode == "req" and (ln.startswith("• ") or not bullets):
            best.append(ln[2:].strip() if ln.startswith("• ") else ln)
    if not best:
        best = [ln[2:].strip() for ln in lines if ln.startswith("• ") and REQ_LINE.search(ln)]
    if not best and not bullets:
        best = [ln for ln in lines if not is_heading(ln) and REQ_LINE.search(ln) and len(ln) < 400][:limit]
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


def tidy_salary(s):
    """'71600.00 to 116550.00' -> '$71,600 – $116,550'. Leaves already formatted text alone."""
    s = (s or "").strip()
    if not s or "$" in s or re.search(r"[€£¥]|[A-Z]{3}", s.replace("USD", "")):
        return s if "$" in s else ""
    n = [float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*(?:\.\d+)?", s)]
    n = [x for x in n if x >= 1000]
    if not n:
        return ""
    return f"${n[0]:,.0f} – ${n[1]:,.0f}" if len(n) > 1 and n[1] > n[0] else f"${n[0]:,.0f}"


# ---------- "Ece" tab: do the requirements describe testing work? ----------
_QA_LINE = re.compile(
    r"(?i)\btest(s|ing|ed|er|ers|able|ability)?\b|\b(qa|sqa|sdet|qe|uat|stlc)\b|\bquality (assurance|engineering|gates?|metrics|standards)\b|"
    r"\bautomation (frameworks?|suites?|scripts?|tools?)\b|\bselenium\b|\bplaywright\b|\bcypress\b|\bappium\b|\bwebdriver\w*|\btestng\b|\bjunit\b|"
    r"\bpytest\b|\bcucumber\b|\bpostman\b|\brest[- ]?assured\b|\bjmeter\b|\btestrail\b|\bzephyr\b|\bxray\b|\bvalidation\b|\bverification\b|"
    r"\bdefects?\b|\bbugs?\b|\bregression\b|\b(llm|model|ai|prompt|rag|agent)s? (evaluat\w+|evals?)\b|\bevaluation (system|methodolog\w+|framework|pipeline|harness|tooling|dataset)s?\b|"
    r"\bevals\b|\bhallucinat\w+|\bred[- ]team\w*|\bgolden sets?\b|\brelease readiness\b")
_NOT_QA = re.compile(r"(?i)\ba/b test\w*|\btest and learn\b|\b(drug|background|skills?|aptitude|typing|covid) test\w*|\bcontest\w*|\btestimon\w+")
_TESTWORD = _QA_LINE
_OTHER_JOB = re.compile(
    r"(?i)\b\d+\s*\+?\s*(?:-\s*\d+\s*\+?\s*)?(?:years?|yrs?)[^.;:]{0,70}\b(customer (support|success|service)|technical support|support (experience|role|engineer\w*)|"
    r"account management|pre-?sales|sales (experience|engineer\w*)|(program|project|product|people) management|software (development|engineering)|"
    r"(front|back)[- ]?end|full[- ]?stack|system administration|sysadmin|devops|solutions? (engineer\w*|architect\w*)|"
    r"data (engineering|science)|business analy\w+|machine learning|ml engineering|cyber ?security|security (engineering|operations)|"
    r"help ?desk|it support|technical writing|scrum master|recruit\w+|legal|law|clinical|nursing|teaching)\b")
_DEV_LINE = re.compile(
    r"(?i)\b((front|back)[- ]?end development|full[- ]?stack (development|engineer\w*|developer)|proficien\w+ (in|with) (react|angular|vue|next\.js)|"
    r"(react|angular|vue|aem|salesforce|sharepoint|\.net|java|python) (forms )?(development|developer) experience|software architecture)\b")


def ece_fit(lines):
    """True when the requirements of a posting describe software-testing work a QA automation engineer does:
    testing shows up in at least two requirement lines and a third of them, no line asks for years in another
    profession, and it is not a development job. Unreadable requirements are not a fit."""
    req = requirements(lines, limit=60, width=10000)
    if len(req) < 3:
        req = [ln[2:].strip() for ln in lines if ln.startswith("• ")]
    if len(req) < 3:
        return False
    qa = [l for l in req if _QA_LINE.search(_NOT_QA.sub(" ", l))]
    if len(qa) < 2 or len(qa) / len(req) < 0.25:
        return False
    for l in req:
        if not _TESTWORD.search(l) and (_OTHER_JOB.search(l) or _DEV_LINE.search(l)):
            return False
    return True
