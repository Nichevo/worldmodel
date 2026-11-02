"use client";

import { useEffect, useState } from "react";
import { api, type ManualFile } from "@/lib/api";

// Files you download yourself: sources whose sites need a sign-in or turn programs
// away. Those with something to do now come first, with a link, which file to save,
// the folder to save it in and the command that loads it.
export default function ManualFilesCard() {
  const [rows, setRows] = useState<ManualFile[] | null>(null);
  const [all, setAll] = useState(false);
  useEffect(() => { api.manualFiles().then(setRows).catch(() => setRows([])); }, []);
  if (!rows || rows.length === 0) return null;
  const todo = rows.filter((r) => r.todo);
  const shown = all ? rows : todo;
  return (
    <div className="card" id="manual">
      <div className="card-head">
        <h2 style={{ margin: 0 }}>Files you download yourself</h2>
        <button className="link small" onClick={() => setAll(!all)}>{all ? "Only what needs doing" : `Show all ${rows.length}`}</button>
      </div>
      <p className="ink-2" style={{ marginTop: 4 }}>
        {todo.length === 0 ? "Nothing to do now. " : `${todo.length} to do. `}
        Save each file in its folder under <code>var\manual</code>, keeping the name the site gives it, then
        run <code>.\load.bat</code> (every folder) or the command shown. &quot;By hand&quot; sources are never downloaded for you;
        the others only need a file when their site refuses a refresh.
      </p>
      {shown.length > 0 && (
        <div className="table-scroll">
          <table className="summary-table">
            <thead><tr><th>Source</th><th>What to do</th><th>Folder and command</th><th>Last loaded</th></tr></thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.source_id}>
                  <td><b>{r.name}</b><div className="small muted">{r.by_hand ? "By hand" : "When the site refuses"} · {r.cadence}</div></td>
                  <td>
                    {r.todo && <div className={r.todo === "load" ? "small" : "small error"} style={{ fontWeight: 600 }}>{r.why}</div>}
                    <div className="small">{r.what}</div>
                    <a className="small" href={r.get} target="_blank" rel="noreferrer">{r.todo === "load" ? "Source site" : "Download page"} ↗</a>
                  </td>
                  <td className="small"><code>{r.folder}</code><br /><code>{r.command}</code>
                    {r.files.length > 0 && <div className="muted">In folder: {r.files.join(", ")}</div>}</td>
                  <td className="small nowrap">{r.last_loaded ? r.last_loaded.slice(0, 10) : "Never"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
