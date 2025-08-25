import React, { useMemo, useState } from "react";

const DEFAULT_KEYWORDS = [
  "Instructional Designer","Instructional Systems Designer","Learning Experience","Learning Designer",
  "Talent Development","Training","Technical Training","Training Administration",
  "Technical Trainer","Course Developer","Curriculum Designer","Training Specialist","Learning and Development"
];

const FOCUS = {
  ISD: ["instructional designer","instructional systems designer","lxd","learning experience","course developer","curriculum designer"],
  "Talent Development": ["talent development","learning and development","l&d"],
  "Technical Training": ["technical training","technical trainer","technical instructor"],
  "Training Admin": ["training administration","training coordinator","training administrator"]
};

function inferApiBase() {
  const env = import.meta.env?.VITE_API_BASE;
  if (env) return env;
  const { protocol, hostname } = window.location;
  if (hostname.endsWith(".onrender.com")) {
    const guess = protocol + "//" + hostname.replace("-web", "-api");
    return guess;
  }
  return "";
}

function FocusChips({ value, onChange }) {
  return (
    <div style={{display:"flex",gap:8,flexWrap:"wrap"}}>
      {Object.keys(FOCUS).map(k => {
        const active = value.includes(k);
        return (
          <div
            key={k}
            onClick={() => onChange(active ? value.filter(x => x !== k) : [...value, k])}
            style={{
              padding:"6px 10px",
              border:"1px solid #2c3b66",
              borderRadius:999,
              cursor:"pointer",
              background: active ? "#2b3a6a" : "#121a38"
            }}
          >
            {k}
          </div>
        );
      })}
      <button className="btn secondary" onClick={() => onChange([])}>Clear focus</button>
    </div>
  );
}

function JobCard({ job, onSave }) {
  const [status, setStatus] = useState(job.bookmark_status || "");
  const [notes, setNotes] = useState(job.bookmark_notes || "");

  const comp = (() => {
    const lo = job.comp_annual_min != null ? `$${Number(job.comp_annual_min).toLocaleString()}` : "";
    const hi = job.comp_annual_max != null ? `$${Number(job.comp_annual_max).toLocaleString()}` : "";
    if (lo && hi && lo !== hi) return `${lo} – ${hi}`;
    return lo || hi;
  })();

  return (
    <div className="job" style={{background:"#0f1530",border:"1px solid #263256",borderRadius:10,padding:14}}>
      <div style={{display:"flex",justifyContent:"space-between",gap:12,flexWrap:"wrap"}}>
        <div>
          <div style={{fontWeight:600, fontSize:16}}>
            <a href={job.url} target="_blank" rel="noreferrer">{job.title}</a>
          </div>
          <div style={{color:"#9aa3b2"}}>
            <b>{job.company}</b>
            {job.location ? ` • ${job.location}` : ""}
            {job.remote ? " • Remote" : ""}
            {job.posted_at ? ` • ${new Date(job.posted_at).toLocaleDateString()}` : ""}
          </div>
          <div style={{display:"flex",gap:8,marginTop:8,flexWrap:"wrap"}}>
            {job.pay_type ? <span style={{fontSize:12,padding:"4px 8px",borderRadius:999,background:"#1f2a4a",border:"1px solid #2c3b66"}}>{job.pay_type}</span> : null}
            {comp ? <span style={{fontSize:12,padding:"4px 8px",borderRadius:999,background:"#1f2a4a",border:"1px solid #2c3b66"}}>{comp}</span> : null}
            {job.department ? <span style={{fontSize:12,padding:"4px 8px",borderRadius:999,background:"#1f2a4a",border:"1px solid #2c3b66"}}>{job.department}</span> : null}
            {job.work_type ? <span style={{fontSize:12,padding:"4px 8px",borderRadius:999,background:"#1f2a4a",border:"1px solid #2c3b66"}}>{job.work_type}</span> : null}
          </div>
        </div>
      </div>
      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:10,marginTop:10}}>
        <select
          style={{padding:10,borderRadius:10,border:"1px solid #263256",background:"#0f1530",color:"#f3f5f7"}}
          value={status}
          onChange={e => setStatus(e.target.value)}
        >
          <option value="">—</option>
          <option>Interested</option>
          <option>Applied</option>
          <option>Interviewing</option>
          <option>Offer</option>
          <option>Rejected</option>
          <option>On Hold</option>
        </select>
        <input
          style={{padding:10,borderRadius:10,border:"1px solid #263256",background:"#0f1530",color:"#f3f5f7"}}
          placeholder="Notes…"
          value={notes}
          onChange={e => setNotes(e.target.value)}
        />
      </div>
      <div style={{marginTop:8}}>
        <button
          style={{padding:"10px 12px",borderRadius:10,background:"#3b82f6",border:"1px solid #3b82f6",color:"#fff",cursor:"pointer"}}
          onClick={() => onSave(job.url, status, notes)}
        >
          Save bookmark
        </button>
      </div>
    </div>
  );
}

export default function App() {
  const [apiBase, setApiBase] = useState(inferApiBase());
  const [zip, setZip] = useState("20147");
  const [radius, setRadius] = useState(50);
  const [lat, setLat] = useState(null);
  const [lon, setLon] = useState(null);
  const [requireClearance, setRequireClearance] = useState(true);
  const [salaryMin, setSalaryMin] = useState(100000);
  const [salaryMax, setSalaryMax] = useState(180000);
  const [payType, setPayType] = useState("");
  const [focus, setFocus] = useState([]);
  const [query, setQuery] = useState("");
  const [remoteOnly, setRemoteOnly] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [results, setResults] = useState([]);

  const useMyLocation = () => {
    if (!navigator.geolocation) { setError("Geolocation not supported"); return; }
    navigator.geolocation.getCurrentPosition(
      (pos) => { setLat(pos.coords.latitude); setLon(pos.coords.longitude); setError(""); },
      (err) => setError(err.message || "Unable to get location"),
      { enableHighAccuracy: true, timeout: 10000 }
    );
  };

  const runSearch = async () => {
    if (!apiBase) { setError("API Base is empty. Set it above or define VITE_API_BASE in Render."); return; }
    setLoading(true); setError("");
    try {
      const body = {
        zip,
        radius: Number(radius),
        include_remote: true,
        require_clearance: requireClearance,
        clearances: ["TS","TS/SCI","SCI","CI Poly","FS Poly","Top Secret","Secret","Public Trust"],
        salary_min: Number(salaryMin),
        salary_max: Number(salaryMax),
        pay_types: payType ? [payType] : ["hourly","salary"],
        latitude: lat,
        longitude: lon,
        keywords: DEFAULT_KEYWORDS,
        // Start with one safe Greenhouse board; add more later
        companies_config: { lever: [], greenhouse: ["anduril-industries"] }
      };
      const res = await fetch(apiBase.replace(/\/$/, "") + "/search", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(body)
      });
      if (!res.ok) throw new Error("API " + res.status);
      const data = await res.json();
      setResults(data.results || []);
    } catch (e) {
      setError(e.message || "Search failed");
    } finally {
      setLoading(false);
    }
  };

  const filtered = useMemo(() => {
    const q = (query || "").toLowerCase();
    return (results || []).filter(r => {
      const hay = `${r.title} ${r.company} ${r.department} ${r.location}`.toLowerCase();
      if (q && !hay.includes(q)) return false;
      if (remoteOnly && !r.remote) return false;
      if (payType && (r.pay_type || "") !== payType) return false;
      if (focus.length) {
        const hit = focus.some(key => (FOCUS[key] || []).some(kw => hay.includes(kw)));
        if (!hit) return false;
      }
      return true;
    });
  }, [results, query, remoteOnly, payType, focus]);

  const saveBookmark = async (url, status, notes) => {
    if (!apiBase) { setError("Set API Base first"); return; }
    try {
      const res = await fetch(apiBase.replace(/\/$/, "") + "/bookmarks", {
        method: "PATCH",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ url, status, notes })
      });
      if (res.status === 404) {
        await fetch(apiBase.replace(/\/$/, "") + "/bookmarks", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({ url, status, notes })
        });
      }
    } catch (e) {
      setError(e.message || "Bookmark failed");
    }
  };

  return (
    <div className="container" style={{maxWidth:1100, margin:"0 auto", padding:24}}>
      <h1 style={{marginBottom:8}}>ID/Talent Jobs — Pilot</h1>
      <p style={{color:"#9aa3b2", marginTop:0}}>
        API Base auto-fills from <code>VITE_API_BASE</code> or tries to infer <code>-api</code> from your Render URL.
        Defaults: ZIP 20147, 50 miles, ≥$100k.
      </p>

      <div className="card" style={{marginBottom:16, background:"#11182e", border:"1px solid #1e2747", borderRadius:14, padding:16}}>
        <div className="row" style={{display:"grid", gap:12, gridTemplateColumns:"repeat(12, minmax(0,1fr))", alignItems:"end"}}>
          <div style={{gridColumn:"span 6"}}>
            <label style={{color:"#9aa3b2"}}>API Base</label>
            <input
              style={{padding:10,borderRadius:10,border:"1px solid #263256",background:"#0f1530",color:"#f3f5f7", width:"100%"}}
              placeholder="https://your-api.onrender.com"
              value={apiBase}
              onChange={e => setApiBase(e.target.value)}
            />
          </div>
          <div style={{gridColumn:"span 2"}}>
            <label style={{color:"#9aa3b2"}}>ZIP</label>
            <input
              style={{padding:10,borderRadius:10,border:"1px solid #263256",background:"#0f1530",color:"#f3f5f7", width:"100%"}}
              value={zip}
              onChange={e => setZip(e.target.value)}
            />
          </div>
          <div style={{gridColumn:"span 2"}}>
            <label style={{color:"#9aa3b2"}}>Radius (mi)</label>
            <input
              style={{padding:10,borderRadius:10,border:"1px solid #263256",background:"#0f1530",color:"#f3f5f7", width:"100%"}}
              type="number"
              value={radius}
              onChange={e => setRadius(Number(e.target.value || 0))}
            />
          </div>
          <div style={{gridColumn:"span 2"}}>
            <label style={{color:"#9aa3b2"}}>Clearance</label>
            <select
              style={{padding:10,borderRadius:10,border:"1px solid #263256",background:"#0f1530",color:"#f3f5f7", width:"100%"}}
              value={requireClearance ? "1" : "0"}
              onChange={e => setRequireClearance(e.target.value === "1")}
            >
              <option value="1">Required</option>
              <option value="0">Not required</option>
            </select>
          </div>

          <div style={{gridColumn:"span 6"}}>
            <label style={{color:"#9aa3b2"}}>Salary Min (USD)</label>
            <input
              style={{padding:10,borderRadius:10,border:"1px solid #263256",background:"#0f1530",color:"#f3f5f7", width:"100%"}}
              type="number"
              value={salaryMin}
              onChange={e => setSalaryMin(Number(e.target.value || 0))}
            />
          </div>
          <div style={{gridColumn:"span 4"}}>
            <label style={{color:"#9aa3b2"}}>Salary Max (USD)</label>
            <input
              style={{padding:10,borderRadius:10,border:"1px solid #263256",background:"#0f1530",color:"#f3f5f7", width:"100%"}}
              type="number"
              value={salaryMax}
              onChange={e => setSalaryMax(Number(e.target.value || 0))}
            />
          </div>
          <div style={{gridColumn:"span 2"}}>
            <label style={{color:"#9aa3b2"}}>Pay Type</label>
            <select
              style={{padding:10,borderRadius:10,border:"1px solid #263256",background:"#0f1530",color:"#f3f5f7", width:"100%"}}
              value={payType}
              onChange={e => setPayType(e.target.value)}
            >
              <option value="">Any</option>
              <option value="salary">Salary</option>
              <option value="hourly">Hourly</option>
            </select>
          </div>

          <div style={{gridColumn:"span 6"}}>
            <label style={{color:"#9aa3b2"}}>Focus</label>
            <div style={{marginTop:6}}>
              <FocusChips value={focus} onChange={setFocus} />
            </div>
          </div>
          <div style={{gridColumn:"span 6"}}>
            <label style={{color:"#9aa3b2"}}>Search (title/company)</label>
            <input
              style={{padding:10,borderRadius:10,border:"1px solid #263256",background:"#0f1530",color:"#f3f5f7", width:"100%"}}
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="e.g. Instructional Designer"
            />
          </div>
          <div style={{gridColumn:"span 6"}}>
            <button
              style={{padding:"10px 12px",borderRadius:10,background:"#1f2937",border:"1px solid #374151",color:"#f3f5f7",cursor:"pointer"}}
              onClick={() => setSalaryMin(100000)}
            >
              Use my default (≥$100k)
            </button>
            <button
              style={{padding:"10px 12px",borderRadius:10,background:"#1f2937",border:"1px solid #374151",color:"#f3f5f7",cursor:"pointer", marginLeft:8}}
              onClick={useMyLocation}
            >
              Use my location
            </button>
            {lat && lon ? (
              <span style={{color:"#9aa3b2", marginLeft:8}}>
                Lat {lat.toFixed(4)} Lon {lon.toFixed(4)}
              </span>
            ) : null}
          </div>
          <div style={{gridColumn:"span 6", textAlign:"right"}}>
            <button
              style={{padding:"10px 12px",borderRadius:10,background:"#3b82f6",border:"1px solid #3b82f6",color:"#fff",cursor:"pointer"}}
              onClick={runSearch}
              disabled={loading}
            >
              {loading ? "Searching…" : "Search via API"}
            </button>
          </div>
        </div>
        {error ? <div style={{color:"#fecaca", marginTop:8}}>{error}</div> : null}
      </div>

      <div className="list" style={{display:"grid", gap:12}}>
        {filtered.length === 0 ? (
          <div style={{color:"#9aa3b2"}}>No results yet. Set API Base and run a search.</div>
        ) : null}
        {filtered.map(job => (
          <JobCard key={job.url} job={job} onSave={saveBookmark} />
        ))}
      </div>
    </div>
  );
}
