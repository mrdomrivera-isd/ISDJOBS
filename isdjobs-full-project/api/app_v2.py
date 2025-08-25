from __future__ import annotations
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# -------------------- FastAPI app --------------------

app = FastAPI(title="ISD Jobs API (Workday Only)", version="1.0.0", docs_url="/docs", redoc_url="/redoc")

# CORS (open for pilot; tighten later if needed)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------- Models --------------------

class SearchParams(BaseModel):
    # Keep minimal fields for pilot; add more later when filters come back
    keywords: List[str] = Field(default_factory=list)
    companies_config: Dict[str, List[str]] = Field(
        default_factory=lambda: {"workday": []}
    )
    # Optional pagination tuning per request (defaults are safe)
    wd_limit: int = 100               # items per page (Workday allows 20–100 typically)
    wd_max_pages: int = 3             # stop after this many pages per tenant

class BookmarkIn(BaseModel):
    url: str
    status: str = ""
    notes: str = ""

# -------------------- Workday Fetcher --------------------

def fetch_workday(
    tenant: str,
    site: str,
    wd_host_hint: Optional[str] = None,
    search_text: str = "",
    page_limit: int = 100,
    max_pages: int = 3,
) -> List[Dict[str, Any]]:
    """
    Fetch jobs from a Workday tenant/site using the CXS endpoint via POST.
    Tries the provided wd_host_hint (e.g., 'wd5') first; if not provided,
    tries a small set of common hosts.

    Returns a normalized list of job dicts.
    """
    # Host order: hint first, then common hosts
    host_candidates = [wd_host_hint] if wd_host_hint else []
    for h in ["wd5", "wd1", "wd3", "wd2"]:
        if h not in host_candidates:
            host_candidates.append(h)

    headers = {
        "User-Agent": "isdjobs/1.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    payload = {
        "appliedFacets": {},         # add filters (facets) later as needed
        "limit": max(1, min(page_limit, 100)),
        "offset": 0,
        "searchText": search_text or ""
    }

    results: List[Dict[str, Any]] = []

    for host in [h for h in host_candidates if h]:
        base = f"https://{tenant}.{host}.myworkdayjobs.com"
        url = f"{base}/wday/cxs/{tenant}/{site}/jobs"

        try:
            offset = 0
            page = 0
            while page < max_pages:
                payload["offset"] = offset
                r = requests.post(url, json=payload, headers=headers, timeout=25)
                if r.status_code != 200:
                    # Try next host if the very first request fails; otherwise break this host
                    if page == 0:
                        break
                    else:
                        # partial success on earlier pages; stop paging this host
                        break

                data = r.json()
                postings = data.get("jobPostings") or []
                if not postings:
                    break

                for job in postings:
                    title = job.get("title") or ""
                    locs = job.get("locations") or []
                    location = ", ".join(locs) if isinstance(locs, list) else (locs or "")
                    external_path = job.get("externalPath") or ""
                    posted_on = job.get("postedOn") or ""

                    # Public view URL for the job (deep link)
                    view_url = f"{base}/{site}/job/{external_path}" if external_path else ""

                    results.append({
                        "source": "workday",
                        "company": tenant,
                        "title": title,
                        "location": location,
                        "remote": "remote" in (location or "").lower(),
                        "url": view_url,
                        "department": job.get("jobFamily") or "",
                        "work_type": "",            # can be derived from facets in a later pass
                        "pay_type": "",
                        "comp_annual_min": None,
                        "comp_annual_max": None,
                        "posted_at": posted_on,
                        "content_html": "",         # detail endpoint can be added later
                    })

                # advance pagination
                got = len(postings)
                offset += got
                page += 1

                # if we got fewer than the requested limit, likely last page
                if got < payload["limit"]:
                    break

            # If we captured any results for this host, don't try others
            if results:
                return results

        except Exception:
            # Try next host candidate
            continue

    return results

# -------------------- Routes --------------------

@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "ts": datetime.utcnow().isoformat()}

@app.post("/search")
def search(params: SearchParams) -> Dict[str, Any]:
    """
    Workday-only search for pilot:
    - Read companies_config.workday entries in form 'tenant|site|hostOptional'
    - For each, call the CXS endpoint via POST
    - Aggregate and return raw results (no filtering yet)
    """
    workday_specs = params.companies_config.get("workday", []) if params.companies_config else []
    results: List[Dict[str, Any]] = []

    # Turn keyword list into a single Workday search string
    search_text = " ".join(params.keywords or []).strip()

    for spec in workday_specs:
        try:
            parts = [p.strip() for p in spec.split("|")]
            if not parts or len(parts) < 1:
                continue
            tenant = parts[0]
            site = parts[1] if len(parts) > 1 and parts[1] else "External"
            wd_host = parts[2] if len(parts) > 2 and parts[2] else None

            jobs = fetch_workday(
                tenant=tenant,
                site=site,
                wd_host_hint=wd_host,
                search_text=search_text,
                page_limit=params.wd_limit,
                max_pages=params.wd_max_pages,
            )
            results.extend(jobs)
        except Exception:
            # Skip any tenant that errors out
            continue

    # De-duplicate by URL
    seen: set[str] = set()
    uniq: List[Dict[str, Any]] = []
    for j in results:
        u = j.get("url") or ""
        if u and u not in seen:
            seen.add(u)
            uniq.append(j)

    return {
        "results": uniq,
        "meta": {
            "count": len(uniq),
            "workday_tenants": workday_specs,
            "keywords": params.keywords,
        },
    }

# -------------------- Bookmarks (simple in-memory pilot) --------------------

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
        "updated_at": datetime.utcnow().isoformat(),
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
