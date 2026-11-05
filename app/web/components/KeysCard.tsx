"use client";

import { useEffect, useState } from "react";
import { api, type ApiKey } from "@/lib/api";

// Keys you can add: free (or optional paid) API keys, what each one adds to the app,
// where to sign up, and whether it is set in the .env file. The key itself is never shown.
export default function KeysCard() {
  const [rows, setRows] = useState<ApiKey[] | null>(null);
  const [all, setAll] = useState(false);
  useEffect(() => { api.keys().then(setRows).catch(() => setRows([])); }, []);
  if (!rows || rows.length === 0) return null;
  const isSet = (k: ApiKey) => k.env.every((e) => e.set);
  const missing = rows.filter((k) => !isSet(k));
  const shown = all ? rows : missing;
  return (
    <div className="card" id="keys">
      <div className="card-head">
        <h2 style={{ margin: 0 }}>Keys you can add</h2>
        <button className="link small" onClick={() => setAll(!all)}>{all ? "Only those not set" : `Show all ${rows.length}`}</button>
      </div>
      <p className="ink-2" style={{ marginTop: 4 }}>
        {rows.length - missing.length} of {rows.length} set. Sign up with the link, then add a line such as
        {" "}<code>EIA_API_KEY=your-key</code> to the <code>.env</code> file in the worldmodel folder (beside start.bat) and
        restart with <code>.\start.bat</code>. &quot;Used now&quot; keys switch something on straight away; &quot;wanted next&quot; ones are
        needed for the next parts of the plan, so get them ahead; the rest are optional. All are free unless the note says otherwise.
      </p>
      {shown.length > 0 && (
        <div className="table-scroll">
          <table className="summary-table">
            <thead><tr><th>Key</th><th>What it adds</th><th>Get it</th><th>In .env as</th><th>Set?</th></tr></thead>
            <tbody>
              {shown.map((k) => (
                <tr key={k.source}>
                  <td><b>{k.name}</b><div className="small muted">{k.active ? "Used now" : k.status[0].toUpperCase() + k.status.slice(1)}</div></td>
                  <td className="small">{k.unlocks}{k.limits ? <div className="muted">{k.limits}</div> : null}</td>
                  <td className="small">{k.signup ? <a href={k.signup} target="_blank" rel="noreferrer">Sign up</a> : null}{k.how ? <div className="muted">{k.how}</div> : null}</td>
                  <td className="small">{k.env.map((e) => <div key={e.name}><code>{e.name}</code></div>)}</td>
                  <td className="small">{isSet(k) ? "Yes" : k.env.some((e) => e.set) ? "Partly" : "No"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
