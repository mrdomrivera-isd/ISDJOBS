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

# Enable CORS for pilot testing
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------- Models --------------------

class SearchParams(BaseModel):
    zip: str = "20147"
    radius: float = 50
    include_remote: bool = True
    require_clearance: bool = True
    clearances: List[str] = Field(default_factory=list)
    salary_min: float = 0
    salary_max: float = 1000000
    pay_types: List[str] = Field(default_factory=lambda: ["hourly", "salary"])
    keywords: List[str] = Field(default_factory=list)
    companies_config: Dict[str, List[str]] = Field(default_factory=lambda: {"lever": [], "greenhouse": []})
    latitude: Optional[float] = None
    longitude: Optional[float] = None

class BookmarkIn(BaseModel):
    url: str
    status: str = ""
    notes: str = ""

# -------------------- Utility Functions --------------------

TOKEN_RE = re.compile(r"^[a-z0-9-]+$")
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

# -------------------- ATS Fetchers --------------------

def fetch_lever(company: str) -> List[Dict[str, Any]]:
    if not valid_board_token(company):
        return []
    cache_key = f"lever:{company}"
    now = time.time()
    if cache_key in CACHE and now - CACHE[cache_key]["ts"] < CACHE_TTL:
        return CACHE[cache_key]["data"]

    url = f"https://api.lever.co/v0/postings/{company}?mode=json"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception:
        return []

    jobs: List[Dict[str, Any]] = []
    for item in data:
        title = norm(item.get("text"))
        location = norm((item.get("categories") or {}).get("location"))
        department = norm((item.get("categories") or {}).get("team"))
        url_post = item.get("hostedUrl") or item.get("applyUrl") or ""
        desc_html = item.get("description") or ""

        jobs.append({
            "source": "lever",
            "company": company,
            "title": title,
            "location": location,
            "remote": "remote" in (location or "").lower(),
            "url": url_post,
            "department": department or "",
            "content_html": desc_html if isinstance(desc_html, str) else "",
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
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception:
        return []

    jobs: List[Dict[str, Any]] = []
    for item in data.get("jobs", []):
        title = norm(item.get("title"))
        location = norm((item.get("location") or {}).get("name"))
        dep = ", ".join(d.get("name") for d in (item.get("departments") or []) if d.get("name"))
        url_post = item.get("absolute_url") or ""
        content_html = item.get("content") or ""

        jobs.append({
            "source": "greenhouse",
            "company": company,
            "title": title,
            "location": location,
            "remote": "remote" in (location or "").lower(),
            "url": url_post,
            "department": dep or "",
            "content_html": content_html,
        })

    CACHE[cache_key] = {"ts": now, "data": jobs}
    return jobs

def collect_jobs(companies: Dict[str, List[str]], keywords: List[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for c in companies.get("lever", []):
        out.extend(fetch_lever(c))
    for c in companies.get("greenhouse", []):
        out.extend(fetch_greenhouse(c))
    # De-duplicate by URL
    seen, uniq = set(), []
    for j in out:
        u = j.get("url")
        if u and u not in seen:
            seen.add(u)
            uniq.append(j)
    return uniq

# -------------------- Routes --------------------

@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "ts": datetime.utcnow().isoformat()}

@app.post("/search")
def search(params: SearchParams) -> Dict[str, Any]:
    companies = params.companies_config or {"lever": [], "greenhouse": []}
    companies = {
        "lever": [c for c in companies.get("lever", []) if valid_board_token(c)],
        "greenhouse": [c for c in companies.get("greenhouse", []) if valid_board_token(c)],
    }

    # Fetch jobs without applying filters yet
    all_jobs = collect_jobs(companies, params.keywords)

    return {
        "results": all_jobs,
        "meta": {
            "count": len(all_jobs),
            "zip": params.zip,
            "radius": params.radius
        }
    }

# -------------------- Bookmarks --------------------

BOOKMARKS: Dict[str, Dict[str, Any]] = {}

@app.get("/bookmarks")
def list_bookmarks():
    return sorted(BOOKMARKS.values(), key=lambda x: x.get("updated_at", ""), reverse=True)

@app.post("/bookmarks")
def add_bookmark(bm: BookmarkIn):
    BOOKMARKS[bm.url] = {
        "url": bm.url,
        "status": bm.status,
        "notes": bm.notes,
        "updated_at": datetime.utcnow().isoformat()
    }
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
