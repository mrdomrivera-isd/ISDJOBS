import React from 'react'
import { createRoot } from 'react-dom/client'

function App() {
  return <div style={{padding:20}}>Job Tracker Web UI is running ✅</div>;
}

createRoot(document.getElementById('root')).render(<App />)
