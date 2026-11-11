"use client";

import { useEffect, useState } from "react";
import { api, type ApiKey } from "@/lib/api";
import { JobPanel, KeyInput, useJob } from "@/components/Upkeep";

// Keys you can add: free (or optional paid) API keys, what each one adds to the app,
// where to sign up, and whether it is set in the .env file. The key itself is never shown.
export default function KeysCard() {
  const [rows, setRows] = useState<ApiKey[] | null>(null);
  const [all, setAll] = useState(false);
  const { job, start } = useJob();
  const [tested, setTested] = useState(false);
  const load = () => api.keys().then(setRows).catch(() => setRows([]));
  useEffect(() => { load(); }, []);
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
        {rows.length - missing.length} of {rows.length} set. Sign up with the link, then paste the key here and press Save: it is
        written to the <code>.env</code> file in the worldmodel folder on this computer (never shown again, never sent anywhere else),
        and works at once. <b>Test</b> fetches the source that uses it, and the result shows here.
        &quot;Used now&quot; keys switch something on straight away; &quot;wanted next&quot; ones are for later parts of the plan,
        so get them ahead; the rest are optional. All are free unless the note says otherwise.
      </p>
      {tested && <JobPanel job={job} />}
      {shown.length > 0 && (
        <div className="table-scroll">
          <table className="summary-table">
            <thead><tr><th>Key</th><th>What it adds</th><th>Get it</th><th>Set?</th><th>Paste it here</th></tr></thead>
            <tbody>
              {shown.map((k) => (
                <tr key={k.source}>
                  <td><b>{k.name}</b><div className="small muted">{k.active ? "Used now" : k.status[0].toUpperCase() + k.status.slice(1)}</div></td>
                  <td className="small">{k.unlocks}{k.limits ? <div className="muted">{k.limits}</div> : null}</td>
                  <td className="small">{k.signup ? <a href={k.signup} target="_blank" rel="noreferrer">Sign up</a> : null}{k.how ? <div className="muted">{k.how}</div> : null}</td>
                  <td className="small">{isSet(k) ? "Yes" : k.env.some((e) => e.set) ? "Partly" : "No"}
                    {k.env.some((e) => e.set) && k.active && <div><button className="link small" disabled={!!job?.running}
                      onClick={() => { setTested(true); start("refresh", [k.source]); }} title="Fetch the source that uses this key now">Test</button></div>}</td>
                  <td className="small nowrap"><KeyInput envs={k.env.map((e) => e.name)} onSaved={load} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
