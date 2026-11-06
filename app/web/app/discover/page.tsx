"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import FindCard, { KIND_LABEL } from "@/components/FindCard";
import { api, type DiscoverFeed, type DiscoverTab, type Find } from "@/lib/api";
import { toast } from "@/lib/ai";
import { useSettings } from "@/lib/settings";

// Discover: interesting things the app finds in its own figures after each refresh (records,
// big movers, turning points, overtakes, outliers, sources that disagree, forecast changes,
// links from the relationship scan, new figures), and a News tab of major world news.
// Your Interesting / Not interesting ratings tune what rises to the top.
const TABS: [DiscoverTab, string][] = [["finds", "Finds"], ["news", "News"], ["interesting", "Interesting"], ["hidden", "Hidden"]];
const PAGE = 40;

function DiscoverPage() {
  const router = useRouter();
  const params = useSearchParams();
  const s = useSettings();
  const tab = (params.get("tab") as DiscoverTab) || "finds";
  const f = (k: string) => params.get(k) ?? "";
  const [feed, setFeed] = useState<DiscoverFeed | null>(null);
  const [items, setItems] = useState<Find[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState(f("q"));
  const [busy, setBusy] = useState(false);
  const seen = useRef(false);
  const set = (patch: Record<string, string>) => {
    const next = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(patch)) { if (v) next.set(k, v); else next.delete(k); }
    router.replace(`/discover?${next}`, { scroll: false });
  };
  const query = { tab, category: f("category") || undefined, kind: f("kind") || undefined, tone: f("tone") || undefined,
    entity: f("entity") || undefined, tag: f("tag") || undefined, q: f("q") || undefined, sort: f("sort") || undefined, new: f("new") || undefined };
  const load = (offset = 0) => api.discover({ ...query, limit: PAGE, offset }).then((d) => {
    setFeed(d); setItems((old) => (offset ? [...old, ...d.items] : d.items)); setError(null);
    if (!seen.current) { seen.current = true; api.discoverSeen().catch(() => undefined); }
    return d;
  }).catch((e) => setError(String(e.message || e)));
  useEffect(() => { load(0); }, [params.toString()]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { const t = setTimeout(() => q !== f("q") && set({ q }), 300); return () => clearTimeout(t); }, [q]); // eslint-disable-line react-hooks/exhaustive-deps
  // The News tab fetches when it is due (Settings: how often), then shows what came in.
  useEffect(() => {
    if (tab !== "news" || !feed?.news.on) return;
    if (feed.news.due && !feed.news.running) api.newsFetch().then(() => setTimeout(() => load(0), 1500)).catch(() => undefined);
  }, [tab, feed?.news.due]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (tab !== "news" || !feed?.news.running) return;
    const t = setInterval(() => load(0), 4000);
    return () => clearInterval(t);
  }, [tab, feed?.news.running]); // eslint-disable-line react-hooks/exhaustive-deps
  const change = (n: Find) => {
    const leaves = (tab === "finds" || tab === "news") && n.rating < 0 || tab === "interesting" && n.rating <= 0 || tab === "hidden" && n.rating >= 0 && !n.never;
    setItems((old) => (leaves ? old.filter((x) => x.key !== n.key) : old.map((x) => (x.key === n.key ? n : x))));
    if (n.rating < 0 && tab !== "hidden") toast("Hidden: it is on the Hidden tab if you change your mind.");
  };
  const never = async (kind: string, on = true) => {
    await api.discoverNever(kind, on);
    toast(on ? `${KIND_LABEL[kind] ?? kind} finds hidden; show them again from the Hidden tab.` : `${KIND_LABEL[kind] ?? kind} finds shown again.`);
    load(0);
  };
  const rescan = async () => {
    setBusy(true);
    try { const r = await api.discoverRescan(); toast(`${r.finds} finds on this build.`); await load(0); } catch (e) { toast(String((e as Error).message || e)); }
    setBusy(false);
  };
  const names = feed?.names ?? {};
  const facet = (k: keyof DiscoverFeed["facets"]) => Object.entries(feed?.facets[k] ?? {}).sort((a, b) => b[1] - a[1]);
  const ai = !!s.ai_enabled;
  return (
    <div className="grid">
      <div>
        <h1 style={{ marginBottom: 4 }}>Discover</h1>
        <p className="ink-2" style={{ marginTop: 0 }}>
          Things the app noticed in its own figures after the last refresh: records, big moves, turning points, overtakes and more, each with
          the numbers behind it. Mark what is <b>Interesting</b> or <b>Not interesting</b> and the feed learns what you like.
          {feed && feed.new_count > 0 && <> <b>{feed.new_count} new</b> since your last visit.</>}
        </p>
      </div>
      <div className="chips-row small">
        <div className="seg" role="tablist" aria-label="Tab">
          {TABS.map(([t, label]) => <button key={t} role="tab" className={tab === t ? "on" : ""} aria-selected={tab === t} onClick={() => set({ tab: t === "finds" ? "" : t, kind: "" })}>{label}</button>)}
        </div>
        <input type="search" placeholder="Search headlines and tags" value={q} onChange={(e) => setQ(e.target.value)} style={{ minWidth: 200 }} />
        <select value={f("category")} onChange={(e) => set({ category: e.target.value })} aria-label="Category">
          <option value="">Every category</option>
          {(feed?.categories ?? []).map((c) => <option key={c} value={c} disabled={!feed?.facets.categories[c]}>{c} ({feed?.facets.categories[c] ?? 0})</option>)}
        </select>
        {tab !== "news" && (
          <select value={f("kind")} onChange={(e) => set({ kind: e.target.value })} aria-label="Kind of find">
            <option value="">Every kind</option>
            {facet("kinds").map(([k, n]) => <option key={k} value={k}>{feed?.kinds[k] ?? k} ({n})</option>)}
          </select>
        )}
        <select value={f("tone")} onChange={(e) => set({ tone: e.target.value })} aria-label="Tone">
          <option value="">Any tone</option>
          <option value="good">▲ Good news ({feed?.facets.tones.good ?? 0})</option>
          <option value="bad">▼ Bad news ({feed?.facets.tones.bad ?? 0})</option>
          <option value="neutral">– Neutral ({feed?.facets.tones.neutral ?? 0})</option>
        </select>
        <select value={f("entity")} onChange={(e) => set({ entity: e.target.value })} aria-label="Country">
          <option value="">Every country</option>
          {facet("entities").map(([e, n]) => <option key={e} value={e}>{names[e] ?? e} ({n})</option>)}
        </select>
        <select value={f("tag")} onChange={(e) => set({ tag: e.target.value })} aria-label="Tag" style={{ maxWidth: 220 }}>
          <option value="">Every tag</option>
          {facet("tags").map(([t, n]) => <option key={t} value={t}>{t} ({n})</option>)}
        </select>
        <select value={f("sort")} onChange={(e) => set({ sort: e.target.value })} aria-label="Sort">
          <option value="">Most interesting</option>
          <option value="newest">Newest</option>
          <option value="key">Your key countries first</option>
        </select>
        <label><input type="checkbox" checked={f("new") === "1"} onChange={(e) => set({ new: e.target.checked ? "1" : "" })} /> New only</label>
      </div>
      {error && <p className="error">{error}</p>}
      {tab === "news" && feed && <NewsStatus feed={feed} onFetch={async () => { await api.newsFetch(true).catch((e) => toast(String(e.message || e))); load(0); }} />}
      {tab === "hidden" && feed && feed.never.length > 0 && (
        <p className="small">Kinds you never see: {feed.never.map((k) => (
          <span key={k} className="chip">{feed.kinds[k] ?? k}<button aria-label={`Show ${k} again`} title="Show again" onClick={() => never(k, false)}>×</button></span>))}</p>
      )}
      {!feed ? <p className="muted">Loading…</p> : items.length === 0 ? (
        <p className="muted">{tab === "interesting" ? "Nothing marked Interesting yet." : tab === "hidden" ? "Nothing hidden." : tab === "news"
          ? (feed.news.on ? (feed.news.running ? "Fetching the news…" : "No news yet.") : <>News is switched off in <Link href="/settings#discover">Settings</Link>.</>)
          : <>No finds on this build{Object.values(query).some((v) => v && v !== tab) ? " with these filters" : ""}. The next <code>.\refresh.bat</code> fills the feed, or <button className="link" disabled={busy} onClick={rescan}>look now</button>.</>}</p>
      ) : (
        <div className="finds">
          {items.map((x) => <FindCard key={x.key} f={x} names={names} ai={ai} why={!!s.discover_ai} onChange={change} onTag={(t) => set({ tag: t })} onNever={(k) => never(k)} />)}
        </div>
      )}
      {feed && items.length < feed.total && <p><button onClick={() => load(items.length)}>Show more ({feed.total - items.length} left)</button></p>}
      <p className="caption">
        Each find comes from a simple check on the figures switched on (Indicators page), with a score for how unusual it is; your key countries
        ({s.discover_key_countries?.split(",").map((k) => names[k] ?? k).join(", ")}) are lifted. Tone follows whether the figure is better higher or lower
        (set your own in <Link href="/settings#discover">Settings</Link>); contested ones such as migration or house prices are neutral.
        Build {feed?.build_id}. <button className="link" disabled={busy} onClick={rescan}>{busy ? "Looking…" : "Look again now"}</button>
      </p>
    </div>
  );
}

function NewsStatus({ feed, onFetch }: { feed: DiscoverFeed; onFetch: () => void }) {
  const n = feed.news;
  if (!n.on) return <p className="small muted">News is switched off (<Link href="/settings#discover">Settings</Link>).</p>;
  const errs = Object.entries(n.errors);
  return (
    <div className="small">
      {n.running ? <span>Fetching the news (GDELT is read slowly, a few seconds a request)…</span>
        : <span className="muted">Last fetched {n.finished_at ? new Date(n.finished_at).toLocaleString() : "never"}. </span>}
      {!n.running && <button className="link" onClick={onFetch}>Fetch now</button>}
      {errs.length > 0 && <ul className="error">{errs.map(([src, e]) => <li key={src}>{src}: {e.error} ({new Date(e.at).toLocaleString()})</li>)}</ul>}
      <span className="muted"> From Wikipedia&apos;s Current events, GDELT news counts, and the news feeds chosen in Settings. Headlines link to the original.</span>
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<p className="muted">Loading…</p>}><DiscoverPage /></Suspense>;
}
