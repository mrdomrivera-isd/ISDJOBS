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

export default function App(){
  const [apiBase, setApiBase] = useState(inferApiBase());
  const [zip, setZip] = useState("20147");
  const [radius, setRadius] = useState(50);
  const [requireClearance, setRequireClearance] = useState(true);
  const [salaryMin, setSalaryMin] = useState(100000);
  const [salaryMax, setSalaryMax] = useState(180000);
  const [focus, setFocus] = useState([]);
  const [query, setQuery] = useState("");
  const [remoteOnly, setRemoteOnly] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [results, setResults] = useState([]);

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
        keywords: DEFAULT_KEYWORDS
      };
      const res = await fetch(apiBase.replace(/\/$/,"") + "/search", {
        method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(body)
      });
      if (!res.ok) throw new Error("API " + res.status);
      const data = await res.json();
      setResults(data.results || []);
    } catch(e) {
      setError(e.message || "Search failed");
    } finally {
      setLoading(false);
    }
  };

  const filtered = useMemo(()=>{
    const q = (query||"").toLowerCase();
    return (results||[]).filter(r=>{
      const hay = `${r.title} ${r.company} ${r.department} ${r.location}`.toLowerCase();
      if (q && !hay.includes(q)) return false;
      if (remoteOnly && !r.remote) return false;
      if (focus.length){
        const hit = focus.some(key => (FOCUS[key]||[]).some(kw => hay.includes(kw)));
        if (!hit) return false;
      }
      return true;
    });
  },[results, query, remoteOnly, focus]);

  return (
    <div style={{padding:"20px",maxWidth:"1000px",margin:"0 auto"}}>
      <h1>ID/Talent Jobs — Pilot</h1>
      <div style={{marginBottom:"10px"}}>
        <label>API Base</label>
        <input style={{width:"100%",padding:"8px"}} placeholder="https://your-api.onrender.com" value={apiBase} onChange={e=>setApiBase(e.target.value)} />
      </div>
      <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:"10px",marginBottom:"10px"}}>
        <div>
          <label>ZIP</label>
          <input style={{width:"100%"}} value={zip} onChange={e=>setZip(e.target.value)} />
        </div>
        <div>
          <label>Radius (mi)</label>
          <input style={{width:"100%"}} type="number" value={radius} onChange={e=>setRadius(Number(e.target.value||0))} />
        </div>
        <div>
          <label>Salary Min</label>
          <input style={{width:"100%"}} type="number" value={salaryMin} onChange={e=>setSalaryMin(Number(e.target.value||0))} />
        </div>
        <div>
          <label>Salary Max</label>
          <input style={{width:"100%"}} type="number" value={salaryMax} onChange={e=>setSalaryMax(Number(e.target.value||0))} />
        </div>
      </div>
      <div style={{marginBottom:"10px"}}>
        <label>Focus</label>
        <div style={{display:"flex",gap:"8px",flexWrap:"wrap"}}>
          {Object.keys(FOCUS).map(k => {
            const active = focus.includes(k);
            return (
              <div key={k}
                onClick={()=> active ? setFocus(focus.filter(x=>x!==k)) : setFocus([...focus,k])}
                style={{padding:"6px 10px",border:"1px solid #555",borderRadius:"20px",cursor:"pointer",background:active?"#2b3a6a":"#121a38"}}>
                {k}
              </div>
            );
          })}
          <button onClick={()=>setFocus([])}>Clear</button>
        </div>
      </div>
      <div style={{marginBottom:"10px"}}>
        <button onClick={()=>setSalaryMin(100000)}>Use my default ≥$100k</button>
        <button style={{marginLeft:"10px"}} onClick={runSearch} disabled={loading}>
          {loading ? "Searching…" : "Search via API"}
        </button>
      </div>
      {error && <div style={{color:"red",marginBottom:"10px"}}>{error}</div>}
      <div>
        {filtered.length===0 && !loading && <div>No results yet. Set API Base and run a search.</div>}
        {filtered.map((job)=>(
          <div key={job.url} style={{border:"1px solid #444",padding:"10px",marginBottom:"8px",borderRadius:"8px"}}>
            <a href={job.url} target="_blank" rel="noreferrer" style={{fontWeight:"bold"}}>{job.title}</a>
            <div>{job.company} • {job.location} {job.remote && "(Remote)"}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
