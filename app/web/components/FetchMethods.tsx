"use client";

import { useEffect, useMemo, useState } from "react";
import { api, type FetchMethod, type FetchWay, type FetchWays } from "@/lib/api";

// How each source is fetched: refresh from the site (a download, an API with a key, or web
// pages), verify.bat in your own browser, or a file you save. Automatic moves a source off a
// site that keeps refusing and back when it works again; a drop-down per source overrides it.
type Show = "notable" | "all" | "switched" | "mine" | "verify" | "file" | "pages" | "api" | "download";

const SHORT: Record<string, string> = { site: "Refresh", verify: "verify.bat", file: "Your file" };

function how(r: FetchWay): string {
  if (r.method === "site") return `Refresh: ${r.kind_label || "download"}`;
  return r.method === "verify" ? "verify.bat (your browser)" : "Your file (load.bat)";
}

function matches(r: FetchWay, show: Show): boolean {
  switch (show) {
    case "all": return true;
    case "switched": return r.choice === "auto" && r.auto !== "site" && r.can.includes("site");
    case "mine": return r.choice !== "auto";
    case "verify": case "file": return r.method === show;
    case "pages": case "api": case "download": return r.method === "site" && r.kind === show;
    default: // the ones worth a look: not a plain download, or with a choice, or failing
      return r.method !== "site" || r.kind !== "download" || r.choice !== "auto" || r.last?.status === "error"
        || r.can.length > 1;
  }
}

export default function FetchMethodsCard() {
  const [data, setData] = useState<FetchWays | null>(null);
  const [show, setShow] = useState<Show>("notable");
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api.fetchMethods().then(setData).catch(() => setData(null)); }, []);

  const counts = useMemo(() => {
    const c: Record<string, number> = { download: 0, api: 0, pages: 0, verify: 0, file: 0, switched: 0, mine: 0 };
    for (const r of data?.sources ?? []) {
      if (r.method === "site" && r.kind) c[r.kind] += 1;
      if (r.method !== "site") c[r.method] += 1;
      if (matches(r, "switched")) c.switched += 1;
      if (r.choice !== "auto") c.mine += 1;
    }
    return c;
  }, [data]);

  if (!data) return null;
  if (data.sources.length === 0) {
    return (
      <div className="card" id="fetch-methods">
        <h2 style={{ margin: 0 }}>How each source is fetched</h2>
        <p className="ink-2">Run <code>.\update.bat</code> or <code>.\refresh.bat</code> once and this list fills in.</p>
      </div>
    );
  }
  const needle = q.trim().toLowerCase();
  const rows = data.sources.filter((r) => matches(r, show)
    && (!needle || r.name.toLowerCase().includes(needle) || r.source_id.includes(needle)));

  async function choose(r: FetchWay, method: FetchMethod) {
    setBusy(r.source_id);
    setErr(null);
    try {
      const got = await api.setFetchMethod(r.source_id, method);
      setData((d) => d && { ...d, sources: d.sources.map((x) => (x.source_id === r.source_id ? got : x)) });
    } catch (e) {
      setErr(`${r.name}: ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  }

  const pill = (key: Show, label: string, n?: number) => (
    <button className={show === key ? "on" : ""} onClick={() => setShow(key)} aria-pressed={show === key}>
      {label}{n !== undefined ? ` (${n})` : ""}
    </button>
  );

  return (
    <div className="card" id="fetch-methods">
      <h2 style={{ margin: 0 }}>How each source is fetched</h2>
      <p className="ink-2" style={{ marginTop: 4 }}>
        <code>.\refresh.bat</code> gets most sources from the site: a download, an API with a key in .env, or by reading
        web pages (<code>.\scrape.bat</code> runs those straight away). Sites with an &quot;are you a person?&quot; check
        can come through <code>.\verify.bat</code> in your own browser, and some come only as a file you save
        (<code>.\load.bat</code>). On <b>Automatic</b>, a site that refuses {data.blocked_in_a_row} refreshes in a row,
        or whose download address is gone, is switched to verify.bat or your file. It is tried again when that file is
        due to be out of date, and switched back if it works. A site whose layout changed is not switched, because it
        needs a fix in the app; it shows here as &quot;layout changed&quot;.
      </p>
      <div className="seg" role="group" aria-label="Show" style={{ flexWrap: "wrap" }}>
        {pill("notable", "Worth a look")}
        {pill("all", "All", data.sources.length)}
        {pill("download", "Download", counts.download)}
        {pill("api", "API with key", counts.api)}
        {pill("pages", "Web pages", counts.pages)}
        {pill("verify", "verify.bat", counts.verify)}
        {pill("file", "Your file", counts.file)}
        {pill("switched", "Switched automatically", counts.switched)}
        {pill("mine", "Changed by you", counts.mine)}
      </div>
      <input type="search" placeholder="Find a source" value={q} onChange={(e) => setQ(e.target.value)}
        style={{ margin: "8px 0", maxWidth: 260 }} aria-label="Find a source" />
      {err && <p className="error">{err}</p>}
      <div className="table-scroll">
        <table className="summary-table">
          <thead><tr><th>Source</th><th>How it comes now</th><th>Choose</th><th>Last refresh</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.source_id}>
                <td><b>{r.name}</b><div className="small muted">{r.source_id}</div></td>
                <td className="small">
                  {how(r)}
                  {r.choice !== "auto" && <div className="muted">Chosen by you</div>}
                  {r.why && <div className="muted">Switched automatically {r.since?.slice(0, 10)}: {r.why}</div>}
                  {r.retry_from && r.method !== "site" && <div className="muted">Site tried again from {r.retry_from}</div>}
                  {r.last_kind === "changed" && r.last?.status === "error" &&
                    <div className="error">Layout changed: the site answered, but not with what the app expects</div>}
                </td>
                <td>
                  {r.can.length > 1 ? (
                    <select value={r.choice} disabled={busy === r.source_id} aria-label={`How ${r.name} is fetched`}
                      onChange={(e) => choose(r, e.target.value as FetchMethod)}>
                      <option value="auto">Automatic (now: {SHORT[r.auto]})</option>
                      {r.can.map((m) => (
                        <option key={m} value={m}>
                          {m === "site" ? `Refresh: ${r.kind_label || "download"}` : data.labels[m]}
                        </option>
                      ))}
                    </select>
                  ) : <span className="small muted">Only {SHORT[r.can[0]] ?? "one way"}</span>}
                </td>
                <td className="small">
                  {r.last ? <>{r.last.at?.slice(0, 10)}: {r.last.status}
                    {r.last.status === "error" && <div className="error">{r.last.note.slice(0, 160)}</div>}
                    {r.last.status === "skipped" && r.last.note && <div className="muted">{r.last.note.slice(0, 160)}</div>}
                  </> : <span className="muted">Not refreshed yet</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length === 0 && <p className="muted small">No sources match.</p>}
    </div>
  );
}
