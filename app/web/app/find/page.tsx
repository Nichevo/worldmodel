"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import AskButton from "@/components/AskButton";
import CountryChoice from "@/components/CountryChoice";
import { KeyInput } from "@/components/Upkeep";
import { toast } from "@/lib/ai";
import { api, type Entity, type FindQuota, type FindResult, type FindStatus, type FoundDataset } from "@/lib/api";
import { useSettings } from "@/lib/settings";

// Find data: search Dateno's index of open datasets (government, statistics and research
// portals worldwide) for topics the app does not hold yet. Narrow by country and by the
// filters Dateno sends back; open a dataset, download one of its files into the found folder,
// or keep it on the wish list (To do) to become a source later. The address holds the search
// (q, country, f), so "Find data on this" links elsewhere open it filled in.

let entityCache: Promise<Entity[]> | null = null;
const entities = () => (entityCache ??= api.entities().catch(() => { entityCache = null; return []; }));

const mb = (n: number) => (n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1e3))} KB`);

function quotaText(q: FindQuota | null): string | null {
  if (!q) return null;
  const parts = [];
  if (q.day_left != null) parts.push(`${q.day_left.toLocaleString()}${q.day_limit ? ` of ${q.day_limit.toLocaleString()}` : ""} today`);
  if (q.month_left != null) parts.push(`${q.month_left.toLocaleString()}${q.month_limit ? ` of ${q.month_limit.toLocaleString()}` : ""} this month`);
  return parts.length ? `Dateno searches left: ${parts.join(", ")}` : null;
}

function FindPage() {
  const s = useSettings();
  const router = useRouter();
  const params = useSearchParams();
  const q0 = params.get("q") ?? "";
  const country = params.get("country") ?? "";
  const filters = useMemo(() => params.getAll("f"), [params]);
  const offset = Number(params.get("offset") ?? 0) || 0;
  const sort = params.get("sort") === "quality" ? "quality" : "relevance";
  const [text, setText] = useState(q0);
  const [status, setStatus] = useState<FindStatus | null>(null);
  const [res, setRes] = useState<FindResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [list, setList] = useState<Entity[]>([]);
  useEffect(() => { entities().then(setList); }, []);
  useEffect(() => setText(q0), [q0]);
  const loadStatus = useCallback(() => api.findStatus().then(setStatus).catch((e) => setErr(String(e.message || e))), []);
  useEffect(() => { loadStatus(); }, [loadStatus]);

  const place = list.find((e) => e.entity_id === country);
  const iso2 = place?.iso2 ?? null;
  const go = (patch: { q?: string; country?: string; f?: string[]; offset?: number; sort?: string }) => {
    const qs = new URLSearchParams();
    const nq = patch.q ?? q0;
    if (nq) qs.set("q", nq);
    const nc = patch.country ?? country;
    if (nc) qs.set("country", nc);
    for (const f of patch.f ?? filters) qs.append("f", f);
    const no = patch.offset ?? 0;
    if (no) qs.set("offset", String(no));
    const ns = patch.sort ?? sort;
    if (ns !== "relevance") qs.set("sort", ns);
    router.push(`/find?${qs}`);
  };

  const ready = !!status?.on && !!status.key_set;
  const asked = !!(q0 || filters.length || (country && iso2));
  useEffect(() => {
    if (!ready || !asked || (country && list.length === 0)) return;
    let live = true;
    setBusy(true);
    setErr(null);
    api.findSearch(q0, iso2, filters, offset, sort)
      .then((r) => { if (live) { setRes(r); if (r.quota) setStatus((st) => (st ? { ...st, quota: r.quota } : st)); } })
      .catch((e) => live && setErr(String(e.message || e).replace(/^\d+: /, "")))
      .finally(() => live && setBusy(false));
    return () => { live = false; };
  }, [ready, asked, q0, iso2, country, filters, offset, sort, list.length]);

  const wished = new Set((status?.wishes ?? []).map((w) => w.id));
  const wish = (d: FoundDataset) => (wished.has(d.id) ? api.findUnwish(d.id) : api.findWish(d))
    .then((r) => { setStatus((st) => (st ? { ...st, wishes: r.items } : st)); toast(wished.has(d.id) ? "Taken off the wish list" : "On the wish list (To do)"); })
    .catch((e) => toast(String(e.message || e)));

  if (!s.find_data) {
    return <div className="grid"><h1>Find data</h1>
      <p className="card">Find data is switched off. Turn it on in <Link href="/settings#find-data">Settings &gt; Find data</Link>.</p></div>;
  }
  const facetName = (key: string) => res?.facets.find((f) => f.key === key)?.name ?? key;
  return (
    <div className="grid">
      <div className="title-row">
        <h1>Find data</h1>
        {res && res.items.length > 0 && (
          <AskButton title={`Find data: ${q0}`} parts={() => [{ key: "results", kind: "data", label: "Datasets found",
            text: res.items.map((d) => `${d.title} | ${d.publisher ?? ""} | ${d.countries.map((c) => c.name).join(", ")} | ${d.formats.join(" ")} | ${d.changed ?? ""}`).join("\n") }]} />
        )}
      </div>
      <p className="ink-2" style={{ marginTop: 0 }}>
        Search open datasets from government, statistics and research portals worldwide (Dateno&apos;s index) for topics the app
        does not hold yet. Open a dataset at its publisher, download a file, or mark it &quot;Want this as a source&quot; to keep it on
        the <Link href="/todo">To do</Link> page.
      </p>
      {status && !status.key_set && (
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Add your Dateno key</h3>
          <p className="small">Sign up free at <a href="https://dateno.io/" target="_blank" rel="noreferrer">dateno.io</a> (or sign in with Google or
            GitHub), then click the blurred key in the &quot;Your API key&quot; block to copy it, and paste it here. It is saved in .env on this computer.</p>
          <KeyInput envs={[status.env]} onSaved={loadStatus} />
        </div>
      )}
      <form className="chips-row" onSubmit={(e) => { e.preventDefault(); go({ q: text.trim(), offset: 0 }); }}>
        <input type="search" value={text} onChange={(e) => setText(e.target.value)} placeholder="What are you looking for? e.g. food waste, housing consents"
          aria-label="Search for datasets" style={{ flex: "1 1 320px", minWidth: 220 }} />
        <CountryChoice value={country} onChange={(id) => go({ country: id })} label="In" />
        {country && <button type="button" className="link small" onClick={() => go({ country: "" })}>Anywhere</button>}
        <label className="small">Order <select value={sort} onChange={(e) => go({ sort: e.target.value })}>
          <option value="relevance">Best match</option><option value="quality">Best described first</option>
        </select></label>
        <button type="submit" disabled={!ready}>Search</button>
      </form>
      {country && list.length > 0 && !iso2 && (
        <p className="small muted">{place?.short_name ?? country} is not one country, so the search covers everywhere; use World region below to narrow it.</p>
      )}
      {(filters.length > 0 || res?.facets.length) ? (
        <div className="chips-row small">
          {filters.map((f) => {
            const [k, v] = [f.slice(0, f.indexOf("=")), f.slice(f.indexOf("=") + 1)];
            return <button key={f} className="pill" title="Take this filter off" onClick={() => go({ f: filters.filter((x) => x !== f) })}>
              {facetName(k)}: {v} ×</button>;
          })}
          {res?.facets.filter((fc) => fc.name !== fc.key && !(fc.key.startsWith("source.countries") && iso2)).map((fc) => (
            <select key={fc.key} value="" aria-label={`Narrow by ${fc.name}`}
              onChange={(e) => e.target.value && go({ f: [...filters, `${fc.key}=${e.target.value}`] })}>
              <option value="">{fc.name}…</option>
              {fc.values.map((v) => <option key={v.value} value={v.value}>{v.value} ({v.count.toLocaleString()})</option>)}
            </select>
          ))}
        </div>
      ) : null}
      <p className="small muted" style={{ margin: 0 }}>
        {quotaText(status?.quota ?? null) ?? (status?.key_set ? "Dateno says how many searches are left after the first one." : "")}
        {res?.from_cache ? " · This answer was kept from an earlier search, so it used none." : ""}
      </p>
      {err && <p className="error">{err}</p>}
      {busy && <p className="muted">Searching…</p>}
      {!asked && ready && <p className="muted">Type a topic, pick a country, or both.</p>}
      {res && !busy && (
        <>
          <p className="small" style={{ margin: 0 }}>
            {res.total ? `${res.total.toLocaleString()}${res.total_more ? "+" : ""} datasets` : "No datasets found. Try fewer or other words, or take a filter off."}
            {res.total > res.limit ? `; showing ${res.offset + 1}–${res.offset + res.items.length}` : ""}
          </p>
          <div className="grid" style={{ gap: 10 }}>
            {res.items.map((d) => <Result key={d.id} d={d} wished={wished.has(d.id)} wish={() => wish(d)} maxMb={status?.max_download_mb ?? 500}
              onSaved={loadStatus} />)}
          </div>
          {res.total > res.limit && (
            <div className="chips-row">
              <button disabled={res.offset === 0} onClick={() => go({ offset: Math.max(0, res.offset - res.limit) })}>Previous</button>
              <button disabled={res.offset + res.limit >= res.total} onClick={() => go({ offset: res.offset + res.limit })}>Next</button>
            </div>
          )}
        </>
      )}
      {status && status.wishes.length > 0 && (
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Wanted as sources ({status.wishes.length})</h3>
          <p className="small muted" style={{ marginTop: 0 }}>Also listed on the <Link href="/todo">To do</Link> page. Ask Claude to turn one into a source.</p>
          <ul className="small">
            {status.wishes.map((w) => (
              <li key={w.id}>{w.url ? <a href={w.url} target="_blank" rel="noreferrer">{w.title}</a> : w.title}
                {w.publisher ? ` · ${w.publisher}` : ""}{w.countries.length ? ` · ${w.countries.join(", ")}` : ""}{w.formats.length ? ` · ${w.formats.join(" ")}` : ""}
                {" "}<button className="link small" onClick={() => api.findUnwish(w.id).then((r) => setStatus({ ...status, wishes: r.items }))}>Remove</button></li>
            ))}
          </ul>
        </div>
      )}
      {status && status.found.length > 0 && (
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Downloaded</h3>
          <p className="small muted" style={{ marginTop: 0 }}>In <code>{status.found_folder}</code>, one folder per dataset with an about.json saying where it came from.</p>
          <ul className="small">
            {status.found.map((f) => <li key={f.path}>{f.folder} / <b>{f.name}</b> · {mb(f.bytes)} · {f.at.slice(0, 10)}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

function Result({ d, wished, wish, maxMb, onSaved }: { d: FoundDataset; wished: boolean; wish: () => void; maxMb: number; onSaved: () => void }) {
  const [files, setFiles] = useState(false);
  const [like, setLike] = useState<FoundDataset[] | null>(null);
  const [saving, setSaving] = useState<number | null>(null);
  const save = (n: number) => {
    setSaving(n);
    api.findDownload(d.id, n).then((r) => { toast(`Saved ${r.name} (${mb(r.bytes)})`); onSaved(); })
      .catch((e) => toast(String(e.message || e).replace(/^\d+: /, ""))).finally(() => setSaving(null));
  };
  const where = [d.publisher, d.publisher !== d.portal ? d.portal : null, d.countries.map((c) => c.name).join(", ")].filter(Boolean).join(" · ");
  return (
    <div className="card">
      <div className="card-head">
        <h3 style={{ margin: 0 }}>{d.url ? <a href={d.url} target="_blank" rel="noreferrer">{d.title}</a> : d.title}</h3>
        <span className="card-actions">
          <AskButton title={d.title} parts={() => [{ key: "dataset", kind: "data", label: "Dataset",
            text: [d.title, where, d.formats.join(" "), d.licence ?? "", d.changed ? `Updated ${d.changed}` : "", d.text].filter(Boolean).join("\n") }]} />
        </span>
      </div>
      <p className="small ink-2" style={{ margin: "2px 0" }}>
        {where}{d.changed ? ` · updated ${d.changed}` : d.created ? ` · made ${d.created}` : ""}
      </p>
      {d.text && <p className="small" style={{ margin: "4px 0" }}>{d.text}</p>}
      <div className="chips-row small">
        {d.formats.map((f) => <span key={f} className="pill">{f}</span>)}
        {d.licence && (d.licence_url ? <a href={d.licence_url} target="_blank" rel="noreferrer">{d.licence}</a> : <span>{d.licence}</span>)}
        {d.topics.slice(0, 3).map((t) => <span key={t} className="muted">{t}</span>)}
      </div>
      <div className="chips-row small" style={{ gap: "6px 16px" }}>
        {d.url && <a href={d.url} target="_blank" rel="noreferrer">Open at the publisher</a>}
        {d.files.length > 0 && <button className="link small" onClick={() => setFiles(!files)}>{files ? "Hide" : "Show"} files ({d.files.length}{d.more_files ? "+" : ""})</button>}
        <button className="link small" onClick={wish} title="Keep it on the To do page to become one of the app's sources">
          {wished ? "Wanted as a source ✓" : "Want this as a source"}</button>
        <button className="link small" onClick={() => (like ? setLike(null) : api.findSimilar(d.id).then((r) => setLike(r.items)).catch((e) => toast(String(e.message || e))))}>
          {like ? "Hide similar" : "Similar datasets"}</button>
        {d.portal_url && <a href={d.portal_url} target="_blank" rel="noreferrer" className="muted">The portal</a>}
      </div>
      {files && (
        <table className="small" style={{ marginTop: 6 }}>
          <tbody>
            {d.files.map((f) => (
              <tr key={f.n}>
                <td>{f.name}</td><td>{f.format ?? ""}</td><td>{f.size ? mb(f.size) : ""}</td>
                <td><a href={f.url} target="_blank" rel="noreferrer">Open</a></td>
                <td><button className="link small" disabled={saving !== null} onClick={() => save(f.n)}
                  title={`Download into the found folder (up to ${maxMb} MB)`}>{saving === f.n ? "Saving…" : "Download"}</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {like && (like.length === 0 ? <p className="small muted">Nothing similar found.</p> : (
        <ul className="small">{like.filter((x) => x.id !== d.id).slice(0, 8).map((x) => (
          <li key={x.id}>{x.url ? <a href={x.url} target="_blank" rel="noreferrer">{x.title}</a> : x.title}{x.publisher ? ` · ${x.publisher}` : ""}
            {x.countries.length ? ` · ${x.countries.map((c) => c.name).join(", ")}` : ""}</li>))}</ul>
      ))}
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<p className="muted">Loading…</p>}><FindPage /></Suspense>;
}
