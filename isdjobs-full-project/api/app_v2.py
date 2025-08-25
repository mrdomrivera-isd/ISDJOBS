from __future__ import annotations
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# -------------------- FastAPI App --------------------

app = FastAPI(
    title="ISD Jobs API (Workday Only)",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Enable CORS for front-end
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------- Models --------------------

class SearchParams(BaseModel):
    keywords: List[str] = Field(default_factory=list)
    companies_config: Dict[str, List[str]] = Field(
        default_factory=lambda: {"workday": []}
    )
    wd_limit: int = 50
    wd_max_pages: int = 2

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
    page_limit: int = 50,
    max_pages: int = 2,
) -> List[Dict[str, Any]]:
    """
    Fetch jobs from a Workday CXS endpoint via POST.
    Example tenant/site: 'leidos|External|wd5'
    """
    host_candidates = [wd_host_hint] if wd_host_hint else []
    for h in ["wd5", "wd1", "wd3", "wd2"]:
        if h not in host_candidates:
            host_candidates.append(h)

    headers = {
        "User-Agent": "isdjobs/1.0",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
    }
    payload = {
        "appliedFacets": {},
        "limit": max(1, min(page_limit, 100)),
        "offset": 0,
        "searchText": search_text or ""
    }

    results: List[Dict[str, Any]] = []

    for host in host_candidates:
        base = f"https://{tenant}.{host}.myworkdayjobs.com"
        url = f"{base}/wday/cxs/{tenant}/{site}/jobs"

        try:
            offset = 0
            page = 0
            while page < max_pages:
                payload["offset"] = offset
                r = requests.post(url, json=payload, headers=headers, timeout=25)
                if r.status_code != 200:
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
                    view_url = f"{base}/{site}/job/{external_path}" if external_path else ""

                    results.append({
                        "source": "workday",
                        "company": tenant,
                        "title": title,
                        "location": location,
                        "remote": "remote" in (location or "").lower(),
                        "url": view_url,
                        "department": job.get("jobFamily") or "",
                        "work_type": "",
                        "pay_type": "",
                        "comp_annual_min": None,
                        "comp_annual_max": None,
                        "posted_at": posted_on,
                        "content_html": "",
                    })

                got = len(postings)
                offset += got
                page += 1
                if got < payload["limit"]:
                    break

            if results:
                break  # stop if this host worked
        except Exception:
            continue

    return results

# -------------------- Routes --------------------

@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "ts": datetime.utcnow().isoformat()}

@app.post("/search")
def search(params: SearchParams) -> Dict[str, Any]:
    """
    Workday-only search for pilot testing.
    """
    workday_specs = params.companies_config.get("workday", []) if params.companies_config else []
    results: List[Dict[str, Any]] = []

    # Turn keywords into a single string
    search_text = " ".join(params.keywords or []).strip()

    for spec in workday_specs:
        try:
            parts = [p.strip() for p in spec.split("|")]
            if not parts or len(parts) < 1:
                continue
            tenant = parts[0]
            site = parts[1] if len(parts) > 1 else "External"
            wd_host = parts[2] if len(parts) > 2 else None

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
            continue

    # Deduplicate by URL
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
