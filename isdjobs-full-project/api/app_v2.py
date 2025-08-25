from __future__ import annotations
import os, re, time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Optional: geocoding & distance
try:
    from geopy.geocoders import Nominatim
    from geopy.distance import geodesic
except Exception:
    Nominatim = None
    geodesic = None

app = FastAPI(title="ISD Jobs API", version="2.0.0", docs_url="/docs", redoc_url="/redoc")

# CORS (open for pilot; tighten later)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------- Models --------------------

DEFAULT_CLEARANCES = [
    "ts/sci", "ts / sci", "top secret", "ts",
    "sci", "ci poly", "fs poly", "full scope poly",
    "secret", "public trust", "security clearance"
]

DEFAULT_KEYWORDS = [
    "instructional designer","instructional systems designer","learning experience",
    "learning designer","talent development","l&d","training",
    "technical training","training administration","technical trainer",
    "course developer","curriculum designer","training specialist",
    "learning and development"
]

class SearchParams(BaseModel):
    zip: str = "20147"
    radius: float = 50
    include_remote: bool = True
    require_clearance: bool = True
    clearances: List[str] = Field(default_factory=lambda: DEFAULT_CLEARANCES)
    salary_min: float = 100000
    salary_max: float = 1000000
    pay_types: List[str] = Field(default_factory=lambda: ["hourly", "salary"])
    keywords: List[str] = Field(default_factory=lambda: DEFAULT_KEYWORDS)
    companies_config: Dict[str, List[str]] = Field(default_factory=lambda: {"lever": [], "greenhouse": []})
    latitude: Optional[float] = None
    longitude: Optional[float] = None

class BookmarkIn(BaseModel):
    url: str
    status: str = ""
    notes: str = ""

# -------------------- Utilities --------------------

TOKEN_RE = re.compile(r"^[a-z0-9-]+$")
HOURS_PER_YEAR = 2080.0
CACHE: Dict[str, Dict[str, Any]] = {}
CACHE_TTL = 120  # seconds

def valid_board_token(t: str) -> bool:
    return bool(t) and bool(TOKEN_RE.match(t))

def norm(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

def strip_html(text: Optional[str]) -> str:
    if not text:
        return ""
    try:
        return BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    except Exception:
        return norm(text)

def parse_money(s: str) -> Optional[float]:
    try:
        return float(str(s).replace(",", "").strip())
    except Exception:
        return None

def to_annual_from_hourly(v: float) -> float:
    return v * HOURS_PER_YEAR

def extract_compensation_annual(text: str) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """
    Look for ranges like $60-$80/hr or $120,000 - $150,000/yr and return annualized comp.
    """
    t = text or ""
    money = r"\$?\s*([0-9]{2,3}(?:,[0-9]{3})*(?:\.[0-9]+)?)"
    sep = r"\s*(?:-|to|–|—)\s*"

    hr = re.search(money + sep + money + r"\s*/\s*(?:hr|hour)", t, re.I)
    if hr:
        lo = parse_money(hr.group(1)); hi = parse_money(hr.group(2))
        if lo and hi: return to_annual_from_hourly(min(lo,hi)), to_annual_from_hourly(max(lo,hi)), "hourly"

    hr1 = re.search(money + r"\s*/\s*(?:hr|hour)", t, re.I)
    if hr1:
        v = parse_money(hr1.group(1))
        if v: return to_annual_from_hourly(v), to_annual_from_hourly(v), "hourly"

    yr = re.search(money + sep + money + r"\s*/\s*(?:yr|year|annum|annually|per year)", t, re.I)
    if yr:
        lo = parse_money(yr.group(1)); hi = parse_money(yr.group(2))
        if lo and hi: return min(lo,hi), max(lo,hi), "salary"

    yr1 = re.search(money + r"\s*/\s*(?:yr|year|annum|annually|per year)", t, re.I)
    if yr1:
        v = parse_money(yr1.group(1))
        if v: return v, v, "salary"

    if re.search(r"\bhourly\b|\b/ ?hr\b", t, re.I):
        return None, None, "hourly"
    if re.search(r"\bsalary\b|\bper year\b", t, re.I):
        return None, None, "salary"

    return None, None, None

def title_matches(title: str, department: Optional[str], keywords: List[str]) -> bool:
    hay = f"{title} | {department or ''}".lower()
    return any(k.lower() in hay for k in keywords) if keywords else True

def clearance_matches(texts: List[str], allow_list: Optional[List[str]], require: bool) -> bool:
    if not require:
        return True
    joined = " | ".join((t or "").lower() for t in texts if t)
    keys = (allow_list or DEFAULT_CLEARANCES)
    return any(k.lower() in joined for k in keys)

def geocode_zip(zip_code: str) -> Optional[Tuple[float, float]]:
    if not Nominatim:
        return None
    try:
        loc = Nominatim(user_agent="isd_jobs_api").geocode(zip_code, timeout=10)
        if loc:
            return (loc.latitude, loc.longitude)
    except Exception:
        pass
    return None

# -------------------- ATS fetchers --------------------

def fetch_lever(company: str) -> List[Dict[str, Any]]:
    if not valid_board_token(company):
        return []
    cache_key = f"lever:{company}"
    now = time.time()
    if cache_key in CACHE and now - CACHE[cache_key]["ts"] < CACHE_TTL:
        return CACHE[cache_key]["data"]

    url = f"https://api.lever.co/v0/postings/{company}?mode=json"
    try:
        r = requests.get(url, timeout=25)
        r.raise_for_status()
        data = r.json()
    except Exception:
        return []

    jobs: List[Dict[str, Any]] = []
    for item in data:
        title = norm(item.get("text"))
        location = norm((item.get("categories") or {}).get("location"))
        department = norm((item.get("categories") or {}).get("team"))
        work_type = norm((item.get("categories") or {}).get("commitment"))
        url_post = item.get("hostedUrl") or item.get("applyUrl") or ""
        posted_ms = item.get("createdAt")
        posted_iso = None
        if posted_ms:
            try:
                posted_iso = datetime.utcfromtimestamp(int(posted_ms)/1000).isoformat()
            except Exception:
                posted_iso = None
        desc_html = item.get("description") or item.get("lists") or item.get("additional")
        blob = " | ".join([title, department or "", location or "", strip_html(desc_html)])
        lo, hi, ptype = extract_compensation_annual(blob)

        jobs.append({
            "source": "lever",
            "company": company,
            "title": title,
            "location": location,
            "remote": "remote" in (location or "").lower(),
            "url": url_post,
            "department": department or "",
            "work_type": work_type or "",
            "posted_at": posted_iso or "",
            "content_html": desc_html if isinstance(desc_html, str) else "",
            "pay_type": ptype or "",
            "comp_annual_min": lo,
            "comp_annual_max": hi,
        })

    CACHE[cache_key] = {"ts": now, "data": jobs}
    return jobs

def fetch_greenhouse(company: str) -> List[Dict[str, Any]]:
    if not valid_board_token(company):
        return []
    cache_key = f"greenhouse:{company}"
    now = time.time()
    if cache_key in CACHE and now - CACHE[cache_key]["ts"] < CACHE_TTL:
        return CACHE[cache_key]["data"]

    url = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true"
    try:
        r = requests.get(url, timeout=25)
        r.raise_for_status()
        data = r.json()
    except Exception:
        return []

    jobs: List[Dict[str, Any]] = []
    for item in data.get("jobs", []):
        title = norm(item.get("title"))
        location = norm((item.get("location") or {}).get("name"))
        dep = ", ".join(d.get("name") for d in (item.get("departments") or []) if d.get("name"))
        work_type = ""
        for m in (item.get("metadata") or []):
            try:
                if str(m.get("name")).lower() in {"employment type","employment_type","commitment"}:
                    work_type = norm(m.get("value"))
                    break
            except Exception:
                pass
        url_post = item.get("absolute_url") or ""
        posted_iso = item.get("updated_at") or item.get("created_at") or ""
        content_html = item.get("content") or ""
        blob = " | ".join([title, dep or "", location or "", strip_html(content_html)])
        lo, hi, ptype = extract_compensation_annual(blob)

        jobs.append({
            "source": "greenhouse",
            "company": company,
            "title": title,
            "location": location,
            "remote": "remote" in (location or "").lower(),
            "url": url_post,
            "department": dep or "",
            "work_type": work_type or "",
            "posted_at": posted_iso,
            "content_html": content_html,
            "pay_type": ptype or "",
            "comp_annual_min": lo,
            "comp_annual_max": hi,
        })

    CACHE[cache_key] = {"ts": now, "data": jobs}
    return jobs

def collect_jobs(companies: Dict[str, List[str]], keywords: List[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for c in companies.get("lever", []):
        out.extend(fetch_lever(c))
    for c in companies.get("greenhouse", []):
        out.extend(fetch_greenhouse(c))
    # de-dupe by URL
    seen, uniq = set(), []
    for j in out:
        u = j.get("url")
        if u and u not in seen:
            seen.add(u)
            uniq.append(j)
    return uniq

# -------------------- Filtering --------------------

def inside_radius(origin: Tuple[float,float], location_name: str, radius: float) -> bool:
    if not geodesic or not Nominatim:
        # If geopy unavailable, skip strict radius filtering (treat as outside)
        return False
    try:
        geo = Nominatim(user_agent="isd_jobs_api_item").geocode(location_name, timeout=8)
        if not geo:
            return False
        miles = geodesic(origin, (geo.latitude, geo.longitude)).miles
        return miles <= radius
    except Exception:
        return False

def apply_filters(jobs: List[Dict[str, Any]], params: SearchParams) -> List[Dict[str, Any]]:
    # origin
    origin = None
   geo_available = (geodesic is not None) and (Nominatim is not None)
if params.latitude is not None and params.longitude is not None:
    origin = (params.latitude, params.longitude)
elif geo_available:
    origin = geocode_zip(params.zip)

skip_radius = (not geo_available) or (origin is None)

    kept: List[Dict[str, Any]] = []
    for j in jobs:
        # title/department keyword check
        if not title_matches(j.get("title",""), j.get("department",""), params.keywords):
            continue

        # clearance check (title + department + location + description)
        if not clearance_matches(
            [j.get("title",""), j.get("department",""), j.get("location",""), strip_html(j.get("content_html",""))],
            params.clearances, params.require_clearance
        ):
            continue

        # remote / radius (robust)
if params.include_remote and j.get("remote"):
    pass  # allow if remote
elif skip_radius:
    pass  # cannot geocode → keep job
else:
    loc = j.get("location")
    if not loc or not inside_radius(origin, loc, params.radius):
        continue

        # salary overlap
        lo = j.get("comp_annual_min")
        hi = j.get("comp_annual_max") if j.get("comp_annual_max") is not None else lo
        pay_type = (j.get("pay_type") or "").lower()

        # If pay_type filter is provided, respect it
        if params.pay_types and pay_type and pay_type not in [p.lower() for p in params.pay_types]:
            continue

        if lo is not None:
            if hi is None: hi = lo
            if (hi < params.salary_min) or (lo > params.salary_max):
                continue
        # If comp is unknown, let it through (UI can filter further)
        kept.append(j)

    # Rank: higher min comp first, then posted date, then company
    kept.sort(key=lambda r: (-(r.get("comp_annual_min") or 0), r.get("posted_at") or "", r.get("company") or ""))
    return kept

# -------------------- Routes --------------------

@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "ts": datetime.utcnow().isoformat()}

@app.post("/search")
def search(params: SearchParams) -> Dict[str, Any]:
    companies = params.companies_config or {"lever": [], "greenhouse": []}
    # drop any invalid tokens
    companies = {
        "lever": [c for c in companies.get("lever", []) if valid_board_token(c)],
        "greenhouse": [c for c in companies.get("greenhouse", []) if valid_board_token(c)],
    }
    all_jobs = collect_jobs(companies, params.keywords)
    filtered = apply_filters(all_jobs, params)
    # shape response for UI
    rows = [{
        "source": j.get("source",""),
        "company": j.get("company",""),
        "title": j.get("title",""),
        "location": j.get("location",""),
        "remote": bool(j.get("remote")),
        "department": j.get("department",""),
        "work_type": j.get("work_type",""),
        "pay_type": j.get("pay_type",""),
        "comp_annual_min": j.get("comp_annual_min"),
        "comp_annual_max": j.get("comp_annual_max"),
        "posted_at": j.get("posted_at",""),
        "url": j.get("url",""),
    } for j in filtered]
    return {"results": rows, "meta": {"count": len(rows), "zip": params.zip, "radius": params.radius}}

# ----- Bookmarks (in-memory for pilot) -----
BOOKMARKS: Dict[str, Dict[str, Any]] = {}

@app.get("/bookmarks")
def list_bookmarks():
    return sorted(BOOKMARKS.values(), key=lambda x: x.get("updated_at",""), reverse=True)

@app.post("/bookmarks")
def add_bookmark(bm: BookmarkIn):
    BOOKMARKS[bm.url] = {"url": bm.url, "status": bm.status, "notes": bm.notes,
                         "updated_at": datetime.utcnow().isoformat()}
    return BOOKMARKS[bm.url]

@app.patch("/bookmarks")
def update_bookmark(bm: BookmarkIn):
    if bm.url not in BOOKMARKS:
        raise HTTPException(status_code=404, detail="Bookmark not found")
    rec = BOOKMARKS[bm.url]
    rec["status"] = bm.status
    rec["notes"] = bm.notes
    rec["updated_at"] = datetime.utcnow().isoformat()
    return rec
