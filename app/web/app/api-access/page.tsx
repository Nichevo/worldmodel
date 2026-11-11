"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { toast } from "@/lib/ai";
import { apiAccess, type ApiAccess } from "@/lib/api";
import { saveSettings, useSettings } from "@/lib/settings";

// The public API: its switch, keys for other PCs, the log of calls, and examples to copy for
// a browser, PowerShell, Python, Excel and an AI assistant (MCP).
export default function ApiPage() {
  const s = useSettings();
  const [d, setD] = useState<ApiAccess | null>(null);
  const [name, setName] = useState("");
  const [made, setMade] = useState<{ name: string; key: string } | null>(null);
  const load = () => apiAccess.get().then(setD).catch(() => {});
  useEffect(() => { load(); }, [s.api_public_on]);
  const origin = typeof window === "undefined" ? "http://localhost:3030" : window.location.origin;
  const base = `${origin}/api/public/v1`;
  const lan = typeof window !== "undefined" && !["localhost", "127.0.0.1", "[::1]"].includes(window.location.hostname);
  const keyArg = made ? made.key : "wm_…";
  const examples: { title: string; note?: string; code: string }[] = [
    { title: "In a browser", code: `${base}/data?indicator=gdp_growth&entities=NZL,AUS&from=2000\n${base}/chart.svg?indicator=inflation&entities=NZL,AUS,GBR,USA&from=1990\n${base}/forecast?indicator=inflation&entity=NZL` },
    { title: "PowerShell", code: lan
      ? `Invoke-RestMethod "${base}/data?indicator=gdp_growth&entities=NZL" -Headers @{Authorization="Bearer ${keyArg}"}`
      : `Invoke-RestMethod "${base}/data?indicator=gdp_growth&entities=NZL"\nInvoke-WebRequest "${base}/data?indicator=gdp_growth&format=csv" -OutFile growth.csv` },
    { title: "Python", note: "The client is installed with the app (worldmodel conda environment). On another PC: pip install it from the app's client folder.",
      code: `import worldmodel_client as wm\n${lan ? `wm.connect("${origin}", key="${keyArg}")\n` : ""}df = wm.data("gdp_growth", ["NZL", "AUS"], start=2000)   # a DataFrame when pandas is installed\nwm.forecast("inflation", "NZL")                        # p10 / p50 / p90 by year\nwm.chart("gdp_growth", ["NZL", "AUS"], path="growth.svg")\nwm.alike("NZL", preset="economy")\nwm.synthetic("NZL", "inflation", 1990)` },
    { title: "Excel", note: "Data > Get Data > From Web, paste the address, then Load. Refresh pulls the latest figures.",
      code: `${base}/data?indicator=gdp_growth&entities=NZL,AUS,GBR,USA&format=csv` },
    { title: "AI assistant (MCP)", note: "Claude Desktop: Settings > Developer > Edit config, add this, restart it. On another PC, install the client there first and use its own path.",
      code: JSON.stringify({ mcpServers: { worldmodel: { command: d?.mcp_command ?? "worldmodel-mcp",
        ...(lan ? { env: { WORLDMODEL_URL: origin, WORLDMODEL_KEY: keyArg } } : {}) } } }, null, 2) },
  ];
  const copy = (t: string) => navigator.clipboard?.writeText(t).then(() => toast("Copied")).catch(() => toast("Could not copy; select it and press Ctrl+C"));
  return (
    <div className="grid">
      <div>
        <h1>API</h1>
        <p className="ink-2" style={{ marginTop: 0 }}>
          Use the app&apos;s data from your own scripts, Python, Excel or an AI assistant. Only this PC and your home network can reach it;
          nothing is opened to the internet. Every call is listed below.
        </p>
      </div>
      <section className="card">
        <div className="card-head">
          <h3>Public API is {s.api_public_on ? "on" : "off"}</h3>
          <label className="switch">
            <input type="checkbox" checked={s.api_public_on} onChange={(e) => saveSettings({ api_public_on: e.target.checked })} aria-label="Public API" />
            <span>{s.api_public_on ? "On" : "Off"}</span>
          </label>
        </div>
        <p className="small" style={{ margin: "4px 0" }}>
          {s.api_public_on
            ? <>Address: <code>{base}</code>. From this PC no key is needed. Other PCs need a key (below), at most {s.api_daily_limit.toLocaleString()} calls a day each (<Link href="/settings#api-access">change</Link>).</>
            : "Off: scripts, the Python client, the MCP server and Copy API link get a message saying it is switched off. The app's own pages work as before."}
        </p>
        <p className="small muted" style={{ margin: "4px 0" }}>
          Every call with its options: <a href="/api/docs#/Public%20API" target="_blank" rel="noreferrer">interactive docs</a> (try each call in the browser).
          Each chart card&apos;s Copy API link gives the address of its figures.
        </p>
      </section>
      <section className="card">
        <h3>Keys for other PCs</h3>
        {made && (
          <div className="warn-note small">
            <p style={{ margin: "4px 0" }}>Key for <b>{made.name}</b>, shown only now: <code>{made.key}</code>{" "}
              <button className="link small" onClick={() => copy(made.key)}>Copy</button></p>
            <p style={{ margin: "4px 0" }}>Send it as <code>Authorization: Bearer {made.key.slice(0, 7)}…</code>. The examples below now include it.</p>
          </div>
        )}
        {d && d.keys.length > 0 ? (
          <table className="small summary-table">
            <thead><tr><th>Name</th><th>Starts</th><th>Made</th><th>Last used</th><th className="num">Today</th><th className="num">All</th><th /></tr></thead>
            <tbody>{d.keys.map((k) => (
              <tr key={k.id}><td>{k.name}</td><td><code>{k.start}…</code></td><td>{k.made.slice(0, 10)}</td><td>{k.last_used?.slice(0, 16).replace("T", " ") ?? "never"}</td>
                <td className="num">{k.today}</td><td className="num">{k.total}</td>
                <td><button className="link small" onClick={() => apiAccess.revoke(k.id).then(load)} title="The key stops working at once">Take back</button></td></tr>
            ))}</tbody>
          </table>
        ) : <p className="small muted">No keys yet. This PC needs none.</p>}
        <div className="chips-row small">
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Which PC or script, e.g. Laptop" aria-label="Key name" style={{ width: 220 }} />
          <button disabled={!name.trim()} onClick={() => apiAccess.make(name).then((k) => { setMade(k); setName(""); load(); }).catch((e) => toast(String(e.message || e)))}>Make a key</button>
        </div>
      </section>
      <section className="card">
        <h3>Examples</h3>
        {examples.map((x) => (
          <div key={x.title} style={{ marginBottom: 12 }}>
            <div className="card-head"><b className="small">{x.title}</b><button className="link small" onClick={() => copy(x.code)}>Copy</button></div>
            {x.note && <p className="small muted" style={{ margin: "2px 0" }}>{x.note}</p>}
            <pre className="code-block">{x.code}</pre>
          </div>
        ))}
        <p className="small muted">
          Calls: <code>/countries</code>, <code>/indicators</code>, <code>/search</code>, <code>/data</code> (json or csv, <code>as_of</code> for figures as known on a date),
          {" "}<code>/forecast</code>, <code>/chart.svg</code>, <code>/events</code>, <code>/crowd</code>, <code>/predictions</code> (read and add),
          {" "}<code>/alike</code>, <code>/synthetic</code>.
        </p>
      </section>
      <section className="card">
        <h3>Recent calls</h3>
        {d && d.recent.length > 0 ? (
          <div className="table-scroll">
            <table className="small summary-table">
              <thead><tr><th>When</th><th>Who</th><th>From</th><th>Call</th><th className="num">Answer</th></tr></thead>
              <tbody>{d.recent.map((c, i) => (
                <tr key={i} className={c.status >= 400 ? "warn" : ""}><td>{c.at.slice(0, 19).replace("T", " ")}</td><td>{c.who}</td><td>{c.from}</td>
                  <td><code>{c.path.replace("/api/public/v1", "")}{c.query ? `?${c.query}` : ""}</code></td>
                  <td className="num">{c.status === 200 ? "ok" : c.status === 429 ? "over limit" : c.status === 401 ? "no key" : c.status}</td></tr>
              ))}</tbody>
            </table>
          </div>
        ) : <p className="small muted">No calls yet.</p>}
        <button className="link small" onClick={load}>Look again</button>
      </section>
    </div>
  );
}
