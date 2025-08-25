from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
# ... (rest of imports)

app = FastAPI(
    title="ISD Jobs API",
    version="1.0.0",
    docs_url="/docs",      # ensure Swagger is ON
    redoc_url="/redoc"     # optional alt docs
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # OK for pilot; tighten later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"ok": True, "message": "API root. See /health and /docs."}

class SearchParams(BaseModel):
    zip: str = "20147"
    radius: float = 50
    include_remote: bool = True
    require_clearance: bool = True
    clearances: List[str] = Field(default_factory=lambda: ["TS","TS/SCI","SCI","CI Poly","FS Poly","Top Secret","Secret","Public Trust"])
    salary_min: float = 100000
    salary_max: float = 250000
    pay_types: List[str] = Field(default_factory=lambda: ["hourly","salary"])
    keywords: List[str] = Field(default_factory=lambda: ["instructional designer","training","talent development"])
    companies_config: Dict[str, List[str]] = Field(default_factory=lambda: {"lever": [], "greenhouse": []})
    latitude: Optional[float] = None
    longitude: Optional[float] = None

@app.get("/health")
def health():
    return {"ok": True, "ts": datetime.utcnow().isoformat()}

@app.post("/search")
def search(params: SearchParams):
    # Minimal stub so the UI works; returns an empty list you can build on
    return {"results": [], "meta": {"zip": params.zip, "radius": params.radius}}

# Simple in-memory bookmarks so the UI can save
BOOKMARKS: Dict[str, Dict[str, Any]] = {}

class BookmarkIn(BaseModel):
    url: str
    status: str = ""
    notes: str = ""

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
