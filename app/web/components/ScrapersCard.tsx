"use client";

import { useEffect, useState } from "react";
import { api, type Scrapers } from "@/lib/api";

// Sources read from web pages (the scraping tools): how each runs, what it reads, the
// setting that governs it, and how its last run went. Runs that stopped early come first.
export default function ScrapersCard() {
  const [data, setData] = useState<Scrapers | null>(null);
  useEffect(() => { api.scrapers().then(setData).catch(() => setData(null)); }, []);
  if (!data || data.sources.length === 0) return null;
  const stopped = data.sources.filter((s) => s.problem || s.last_run?.stopped).length;
  return (
    <div className="card" id="scrapers">
      <h2 style={{ margin: 0 }}>Sources read from web pages</h2>
      <p className="ink-2" style={{ marginTop: 4 }}>
        {stopped ? `${stopped} stopped early last time (see why below). ` : ""}
        These sources have no file or API to download, so the app reads their web pages, politely: at least{" "}
        {data.gap_seconds} s between pages (Settings, Gap between web pages), longer on long runs, and a stop at the
        first page that is refused or looks wrong, so nothing more is asked of that site until next time.
      </p>
      <div className="table-scroll">
        <table className="summary-table">
          <thead><tr><th>Source</th><th>How it runs</th><th>What it reads</th><th>Last run</th></tr></thead>
          <tbody>
            {data.sources.map((s) => {
              const r = s.last_run;
              return (
                <tr key={s.source_id}>
                  <td><b>{s.name}</b>{s.setting && <div className="small muted">Setting: {s.setting} = {String(s.setting_value)}</div>}</td>
                  <td className="small">{s.run}</td>
                  <td className="small">{s.reads}{s.today && <div className="muted">{s.today}</div>}</td>
                  <td className="small">
                    {r ? <>{r.at.slice(0, 16).replace("T", " ")}: {r.read} of {r.planned} page{r.planned === 1 ? "" : "s"}</>
                      : s.last_loaded ? <>Loaded {s.last_loaded.slice(0, 10)}</> : "Not run yet"}
                    {r?.stopped && <div className="error">{r.stopped}</div>}
                    {!r?.stopped && s.problem && <div className="error">{s.problem}</div>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
