"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import CardAsk from "@/components/CardAsk";
import CountryChoice from "@/components/CountryChoice";
import EChart from "@/components/EChart";
import Flag from "@/components/Flag";
import { openAsk } from "@/lib/ai";
import { logHistory } from "@/lib/history";
import {
  type Along, type Dot, type InventionCard, type InventionChart, type InventionList, catVar, inventionChartOption, inventionsApi,
  startFor, timelineOption, yearText,
} from "@/lib/inventions";

// Inventions over time: a timeline in ten categories, a card for each invention with how it
// spread and the changes seen around it, any measure with the inventions along it, and a list.
// Explore > Inventions. Nothing here says an invention caused a change.
type Tab = "timeline" | "along" | "list";
type Range = "all" | "1700" | "1900" | "pick";
const RANGES: [Range, string][] = [["all", "All time"], ["1700", "Since 1700"], ["1900", "Since 1900"], ["pick", "Pick years"]];
const KEY = ["world", "NZL", "AUS", "GBR", "USA"];
const NOW = new Date().getFullYear();

function InventionsView() {
  const router = useRouter();
  const params = useSearchParams();
  const tab = (["along", "list"].includes(params.get("tab") ?? "") ? params.get("tab") : "timeline") as Tab;
  const id = params.get("id");
  const [d, setD] = useState<InventionList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const set = useCallback((changes: Record<string, string | null>) => {
    const p = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(changes)) if (v === null) p.delete(k); else p.set(k, v);
    const qs = p.toString();
    router.replace(qs ? `/inventions?${qs}` : "/inventions", { scroll: false });
  }, [params, router]);
  useEffect(() => { logHistory({ kind: "page", title: "Inventions", url: "/inventions", detail: "page" }); }, []);
  useEffect(() => { inventionsApi.list().then(setD).catch((e) => setError(String(e))); }, []);
  if (error) return <p className="error">Could not load the inventions: {error}</p>;
  if (!d) return <p className="muted">Loading…</p>;
  const open = (iid: string) => set({ id: iid, tab: null });
  return (
    <div className="grid sector-page">
      <div className="title-row"><h1>Inventions</h1></div>
      <p className="ink-2" style={{ marginTop: 0, maxWidth: 860 }}>{d.inventions.length} inventions from stone tools to large language models, in
        ten categories. Pick one to see how it spread and the changes in health, food, work and growth seen around the same time.
        {" "}{d.caution}</p>
      <div className="seg" role="tablist">
        {([["timeline", "Timeline"], ["along", "Changes over time"], ["list", "List"]] as [Tab, string][]).map(([t, label]) => (
          <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "on" : ""}
            onClick={() => set({ tab: t === "timeline" ? null : t })}>{label}</button>))}
      </div>
      {tab === "timeline" && <Timeline d={d} id={id} onPick={(iid) => set({ id: iid })} />}
      {tab === "along" && <AlongTab d={d} onPick={(iid) => set({ id: iid, tab: null })} />}
      {tab === "list" && <ListTab d={d} onPick={open} />}
      {tab === "timeline" && id && !id.startsWith("wd:") && <Card id={id} onPick={(iid) => set({ id: iid })} />}
      {tab === "timeline" && id?.startsWith("wd:") && <ExtraCard d={d} id={id} />}
    </div>
  );
}

// ------------------------------------------------------------------ timeline
function Timeline({ d, id, onPick }: { d: InventionList; id: string | null; onPick: (id: string) => void }) {
  const [range, setRange] = useState<Range>("1700");
  const [pick, setPick] = useState<[number, number]>([1800, NOW]);
  const [cats, setCats] = useState<Set<string>>(new Set(d.categories.map((c) => c.id)));
  const [extras, setExtras] = useState(true);
  const [filter, setFilter] = useState("");
  const span: [number, number] = range === "all" ? [-3_400_000, NOW] : range === "1700" ? [1700, NOW] : range === "1900" ? [1900, NOW] : pick;
  const shownCats = d.categories.filter((c) => cats.has(c.id));
  const f = filter.trim().toLowerCase();
  const dots: Dot[] = useMemo(() => [
    ...d.inventions.filter((i) => !f || `${i.name} ${i.what} ${i.who ?? ""} ${i.place ?? ""}`.toLowerCase().includes(f))
      .map((i) => ({ id: i.id, name: i.name, year: i.year, category: i.category, approx: i.approx })),
    // Wikidata's extras have no category: they sit in a lane by year order, spread over the lanes shown.
    ...(extras ? d.extras.filter((x) => !f || x.name.toLowerCase().includes(f))
      .map((x, n) => ({ id: x.id, name: x.name, year: x.year, category: shownCats[n % Math.max(1, shownCats.length)]?.id ?? "", extra: true })) : []),
  ], [d, f, extras, shownCats]);
  const option = useCallback(() => timelineOption(dots, shownCats, span, range === "all", id), [dots, shownCats, span, range, id]);
  const onReady = useCallback((chart: { on: (ev: string, fn: (p: unknown) => void) => void }) => {
    chart.on("click", (p) => {
      const q = p as { data?: { id?: string } };
      if (q.data?.id) onPick(q.data.id);
    });
  }, [onPick]);
  const n = dots.filter((x) => !x.extra && x.year >= span[0] && x.year <= span[1]).length;
  const ask = () => openAsk({ title: "Inventions over time", parts: [
    { key: "data", kind: "data", label: "Inventions", text: d.inventions.map((i) => `${yearText(i.year, i.approx)} ${i.name} (${i.category_name}${i.place ? `, ${i.place}` : ""})`).join("\n") },
    { key: "description", kind: "description", label: "Note", text: d.caution }] });
  return (
    <div className="card">
      <div className="long-tools" style={{ flexWrap: "wrap", gap: 8 }}>
        <div className="seg small">
          {RANGES.map(([r, label]) => <button key={r} className={range === r ? "on" : ""} aria-pressed={range === r} onClick={() => setRange(r)}>{label}</button>)}
        </div>
        {range === "pick" && <span className="small">
          <input type="number" aria-label="From year" value={pick[0]} style={{ width: 80 }} onChange={(e) => setPick([+e.target.value, pick[1]])} /> to{" "}
          <input type="number" aria-label="To year" value={pick[1]} style={{ width: 80 }} onChange={(e) => setPick([pick[0], +e.target.value])} />
        </span>}
        <input type="search" placeholder="Filter inventions…" aria-label="Filter inventions" value={filter} onChange={(e) => setFilter(e.target.value)} style={{ width: 180 }} />
        <label className="small"><input type="checkbox" checked={extras} onChange={(e) => setExtras(e.target.checked)} /> More from Wikidata ({d.extras.length})</label>
        <CardAsk onAsk={ask} />
      </div>
      <div className="chips-row small" style={{ marginTop: 8 }}>
        {d.categories.map((c) => {
          const on = cats.has(c.id);
          return <button key={c.id} className="chip" aria-pressed={on} style={{ opacity: on ? 1 : 0.45 }}
            onClick={() => { const s = new Set(cats); if (on) s.delete(c.id); else s.add(c.id); setCats(s.size ? s : new Set(d.categories.map((x) => x.id))); }}>
            <span className="dot" style={{ background: catVar(c.id), display: "inline-block", width: 9, height: 9, borderRadius: "50%", marginRight: 5 }} />{c.name}</button>;
        })}
      </div>
      <EChart option={option} height={Math.max(260, shownCats.length * 54 + 80)} label="Timeline of inventions by category" onReady={onReady} />
      <p className="caption">{n} inventions shown. Click a dot for its card; drag the slider to zoom. Grey dots are inventions and discoveries
        Wikidata dates (in 25 or more Wikipedias), unchecked and without charts; they sit in the lanes only to spread them out.
        {range === "all" ? " Before 1500 the scale is squeezed: each step left is ten times further back." : ""}</p>
    </div>
  );
}

// ------------------------------------------------------------------ one invention
function Card({ id, onPick }: { id: string; onPick: (id: string) => void }) {
  const [entities, setEntities] = useState<string[] | null>(null);
  const [c, setC] = useState<InventionCard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [others, setOthers] = useState(true);
  useEffect(() => { setEntities(null); }, [id]);
  useEffect(() => {
    let live = true;
    setError(null);
    inventionsApi.card(id, entities ?? undefined).then((x) => { if (!live) return; setC(x); logHistory({ kind: "page", title: `Invention: ${x.invention.name}`, url: `/inventions?id=${id}`, detail: "invention" }); })
      .catch((e) => live && setError(String(e)));
    return () => { live = false; };
  }, [id, entities]);
  if (error) return <p className="error">{error}</p>;
  if (!c || c.invention.id !== id) return <p className="muted">Loading…</p>;
  const i = c.invention;
  const ents = c.entities;
  const ask = () => openAsk({ title: `${i.name} and the changes around it`, parts: [
    { key: "description", kind: "description", label: "Invention", text: `${i.name}, ${yearText(i.year, i.approx)}${i.place ? `, ${i.place}` : ""}${i.who ? `, ${i.who}` : ""}. ${i.what} ${i.link ?? ""}` },
    { key: "data", kind: "data", label: "Charts", text: c.charts.map((ch) => `${ch.name} (${ch.unit}): ${ch.lines.map((l) => `${l.name} ${l.points[0]?.[0]}: ${l.points[0]?.[1]}, ${l.points[l.points.length - 1]?.[0]}: ${l.points[l.points.length - 1]?.[1]}`).join("; ")}`).join("\n") },
    { key: "caution", kind: "description", label: "Note", text: c.caution }] });
  const spread = c.charts.filter((x) => x.kind === "spread");
  const related = c.charts.filter((x) => x.kind === "related");
  return (
    <div className="grid" id="invention-card">
      <div className="card">
        <div className="card-head"><h2 style={{ margin: 0 }}>{i.name}</h2>
          <span className="chip small"><span style={{ background: catVar(i.category), display: "inline-block", width: 9, height: 9, borderRadius: "50%", marginRight: 5 }} />{i.category_name}</span>
          <CardAsk onAsk={ask} /></div>
        <p className="small muted" style={{ margin: "2px 0 8px" }}>{yearText(i.year, i.approx)}{i.place ? ` · ${i.place}` : ""}{i.who ? ` · ${i.who}` : ""}</p>
        <p style={{ maxWidth: 820, marginTop: 0 }}>{i.what}{i.link ? ` ${i.link}` : ""}</p>
        <p className="small">{i.wiki && <a href={i.wiki} target="_blank" rel="noreferrer">Wikipedia</a>}
          {c.before && <> · Before it in {i.category_name.toLowerCase()}: <button className="link" onClick={() => onPick(c.before!.id)}>{c.before.name} ({yearText(c.before.year)})</button></>}
          {c.after && <> · After: <button className="link" onClick={() => onPick(c.after!.id)}>{c.after.name} ({yearText(c.after.year)})</button></>}</p>
        <div className="long-tools" style={{ flexWrap: "wrap", gap: 6 }}>
          <span className="small muted">Countries:</span>
          {ents.map((e) => <span key={e} className="chip small"><Flag id={e} />{e === "world" ? "World" : e}
            {ents.length > 1 && <button className="link" aria-label={`Remove ${e}`} onClick={() => setEntities(ents.filter((x) => x !== e))}> ×</button>}</span>)}
          {ents.length < 8 && <CountryChoice value="" label="Add a country" onChange={(e) => e && !ents.includes(e) && setEntities([...ents, e])} />}
          {entities && <button className="link small" onClick={() => setEntities(null)}>Reset</button>}
          <label className="small"><input type="checkbox" checked={others} onChange={(e) => setOthers(e.target.checked)} /> Other inventions on the charts</label>
        </div>
        <p className="caption">{c.caution}</p>
      </div>
      {spread.length > 0 && <><h3 style={{ margin: "4px 0 0" }}>How it spread</h3>
        <div className="cards-2">{spread.map((ch) => <ChartCard key={ch.series} ch={ch} c={c} others={others} onPick={onPick} />)}</div></>}
      {related.length > 0 && <><h3 style={{ margin: "4px 0 0" }}>Related changes</h3>
        <div className="cards-2">{related.map((ch) => <ChartCard key={ch.series} ch={ch} c={c} others={others} onPick={onPick} />)}</div></>}
      {!c.charts.length && <p className="muted small">No charts for this one: there are no figures from that far back.</p>}
    </div>
  );
}

function ChartCard({ ch, c, others, onPick }: { ch: InventionChart; c: InventionCard; others: boolean; onPick: (id: string) => void }) {
  const i = c.invention;
  const option = useCallback(() => inventionChartOption(ch.lines, ch.unit, { year: i.year, name: i.name, category: i.category }, ch.others, others, startFor(i.year)),
    [ch, i, others]);
  const onReady = useCallback((chart: { on: (ev: string, fn: (p: unknown) => void) => void }) => {
    chart.on("click", (p) => {
      const q = p as { componentType?: string; data?: { url?: string } };
      if (q.componentType === "markLine" && q.data?.url) onPick(q.data.url);
    });
  }, [onPick]);
  const ask = () => openAsk({ title: `${ch.name} around ${i.name} (${yearText(i.year)})`, parts: [
    { key: "data", kind: "data", label: ch.name, text: ch.lines.map((l) => `${l.name}: ${l.points.map(([y, v]) => `${y} ${v}`).join(", ")}`).join("\n").slice(0, 6000) },
    { key: "caution", kind: "description", label: "Note", text: c.caution }] });
  const missing = !ch.lines.length;
  return (
    <div className="card">
      <div className="card-head"><h3>{ch.name}{ch.unit ? <span className="small muted"> ({ch.unit})</span> : null}</h3>
        {!missing && <CardAsk onAsk={ask} />}
        {!ch.series.startsWith("long:") && <Link className="small" href={`/indicator/${ch.series}`}>Open</Link>}</div>
      {missing ? <p className="muted small">No figures loaded for this yet{ch.series.startsWith("long:") ? " (run .\\refresh.bat to fetch the long-run series)" : ""}.</p>
        : <EChart option={option} height={250} label={`${ch.name} around ${i.name}`} onReady={onReady} />}
      <p className="caption">{ch.source ? `${ch.source}. ` : ""}{i.year < Math.min(...ch.lines.map((l) => l.points[0]?.[0] ?? Infinity)) ? `${i.name} (${yearText(i.year, i.approx)}) came before these figures start.` : `Dashed line: ${i.name} (${yearText(i.year, i.approx)}).`}{others && ch.others.length ? " Dotted lines: other inventions linked to this chart (click to open)." : ""}</p>
    </div>
  );
}

function ExtraCard({ d, id }: { d: InventionList; id: string }) {
  const x = d.extras.find((e) => e.id === id);
  if (!x) return null;
  return (
    <div className="card">
      <div className="card-head"><h2 style={{ margin: 0 }}>{x.name}</h2></div>
      <p className="small muted">{yearText(x.year)} · from Wikidata (articles in {x.links} Wikipedias), unchecked{x.where ? ` · ${x.where}` : ""}</p>
      <p className="small">Wikidata gives this a date of discovery or invention but not which figures relate to it, so there are no charts.
        {" "}<a href={x.url} target="_blank" rel="noreferrer">Read about it</a></p>
    </div>
  );
}

// ------------------------------------------------------------------ changes over time
function AlongTab({ d, onPick }: { d: InventionList; onPick: (id: string) => void }) {
  const [series, setSeries] = useState("long:life_expectancy");
  const [cats, setCats] = useState<string[]>(["medicine"]);
  const [entities, setEntities] = useState<string[]>(KEY);
  const [a, setA] = useState<Along | null>(null);
  useEffect(() => {
    let live = true;
    setA(null);
    inventionsApi.along(series, entities, cats).then((x) => live && setA(x)).catch(() => live && setA(null));
    return () => { live = false; };
  }, [series, cats, entities]);
  const measures = [...d.measures].sort((x, y) => x.name.localeCompare(y.name));
  const option = useCallback(() => inventionChartOption(a?.lines ?? [], a?.unit ?? "", null, a?.inventions ?? [], true), [a]);
  const onReady = useCallback((chart: { on: (ev: string, fn: (p: unknown) => void) => void }) => {
    chart.on("click", (p) => {
      const q = p as { componentType?: string; data?: { url?: string } };
      if (q.componentType === "markLine" && q.data?.url) onPick(q.data.url);
    });
  }, [onPick]);
  const shown = (a?.inventions ?? []).filter((i) => {
    const pts = a?.lines.flatMap((l) => l.points.map((p) => p[0])) ?? [];
    return pts.length && i.year >= Math.min(...pts) && i.year <= Math.max(...pts);
  });
  return (
    <div className="card">
      <div className="long-tools" style={{ flexWrap: "wrap", gap: 8 }}>
        <label className="small">Measure{" "}
          <select value={series} onChange={(e) => setSeries(e.target.value)} aria-label="Measure">
            {measures.map((m) => <option key={m.series} value={m.series}>{m.name}{m.unit ? ` (${m.unit})` : ""}</option>)}
          </select></label>
        <span className="small muted">Countries:</span>
        {entities.map((e) => <span key={e} className="chip small"><Flag id={e} />{e === "world" ? "World" : e}
          {entities.length > 1 && <button className="link" aria-label={`Remove ${e}`} onClick={() => setEntities(entities.filter((x) => x !== e))}> ×</button>}</span>)}
        {entities.length < 8 && <CountryChoice value="" label="Add a country" onChange={(e) => e && !entities.includes(e) && setEntities([...entities, e])} />}
      </div>
      <div className="chips-row small" style={{ marginTop: 8 }}>
        <span className="small muted">Inventions from:</span>
        {d.categories.map((c) => {
          const on = cats.includes(c.id);
          return <button key={c.id} className="chip" aria-pressed={on} style={{ opacity: on ? 1 : 0.45 }}
            onClick={() => setCats(on ? cats.filter((x) => x !== c.id) : [...cats, c.id])}>
            <span style={{ background: catVar(c.id), display: "inline-block", width: 9, height: 9, borderRadius: "50%", marginRight: 5 }} />{c.name}</button>;
        })}
      </div>
      {!a ? <p className="muted">Loading…</p> : !a.lines.length ? <p className="muted small">No figures loaded for {a.name} yet.</p> : <>
        <EChart option={option} height={340} label={`${a.name} with inventions marked`} onReady={onReady} />
        <p className="small">{shown.length ? <>Along it: {shown.map((i, n) => <span key={i.id}>{n ? ", " : ""}
          <button className="link" style={{ fontWeight: i.linked ? 600 : 400 }} onClick={() => onPick(i.id)}>{i.name}</button> ({yearText(i.year)})</span>)}.</> : "No inventions from these categories fall in these years."}</p>
        <p className="caption">{a.source ? `${a.source}. ` : ""}Dotted lines mark inventions (bolder: ones whose card has this chart). {a.caution}</p>
      </>}
    </div>
  );
}

// ------------------------------------------------------------------ list
function ListTab({ d, onPick }: { d: InventionList; onPick: (id: string) => void }) {
  const [filter, setFilter] = useState("");
  const [cat, setCat] = useState("all");
  const f = filter.trim().toLowerCase();
  const shown = d.inventions.filter((i) => (cat === "all" || i.category === cat)
    && (!f || `${i.name} ${i.what} ${i.who ?? ""} ${i.place ?? ""}`.toLowerCase().includes(f)));
  return (
    <div className="card">
      <div className="long-tools" style={{ flexWrap: "wrap", gap: 8 }}>
        <input type="search" placeholder="Filter…" aria-label="Filter the list" value={filter} onChange={(e) => setFilter(e.target.value)} style={{ width: 200 }} />
        <select value={cat} onChange={(e) => setCat(e.target.value)} aria-label="Category">
          <option value="all">All categories</option>
          {d.categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <span className="small muted">{shown.length} of {d.inventions.length}</span>
      </div>
      <div className="ep-scroll"><table className="small summary-table">
        <thead><tr><th>When</th><th>Invention</th><th>Category</th><th>Where</th><th>Who</th><th>Charts</th></tr></thead>
        <tbody>{shown.map((i) => (
          <tr key={i.id}><td className="num">{yearText(i.year, i.approx)}</td>
            <td><button className="link" onClick={() => onPick(i.id)}><b>{i.name}</b></button><div className="muted">{i.what}</div></td>
            <td><span style={{ background: catVar(i.category), display: "inline-block", width: 8, height: 8, borderRadius: "50%", marginRight: 5 }} />{i.category_name}</td>
            <td>{i.where && <Flag id={i.where} />}{i.place ?? ""}</td><td>{i.who ?? ""}</td>
            <td className="num">{i.spread.length + i.related.filter((s) => !i.spread.includes(s)).length}</td></tr>))}</tbody>
      </table></div>
    </div>
  );
}

export default function InventionsPage() {
  return <Suspense fallback={<p className="muted">Loading…</p>}><InventionsView /></Suspense>;
}
