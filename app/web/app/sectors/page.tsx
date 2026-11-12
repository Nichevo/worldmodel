"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import CardAsk from "@/components/CardAsk";
import CommodityPrices from "@/components/CommodityPrices";
import CountryChoice from "@/components/CountryChoice";
import EChart from "@/components/EChart";
import Help from "@/components/Help";
import SectorsOverview from "@/components/SectorsOverview";
import { api, type SectorCard, type SectorList, type SectorsByCountry } from "@/lib/api";
import { openAsk } from "@/lib/ai";
import { amount, chapterBars, money, yearLines } from "@/lib/sectors";
import { saveSettings, useSettings } from "@/lib/settings";

// One industry across the globe, stage by stage; or one country's trade by sector.

function NoTrade() {
  return (
    <div className="card">
      <p>No trade by product stored yet. It comes from CEPII BACI, one large download (about 2 GB) during
        {" "}<code>.\refresh.bat</code>; the switch and the first year kept are in <Link href="/settings#sectors">Settings: Sectors</Link>.
        If the download is refused, save the zip into <code>var\manual\baci</code> and run <code>.\load.bat</code>.
        Production and prices show without it.</p>
    </div>
  );
}

function SectorTile({ s, onHide }: { s: SectorCard; onHide: () => void }) {
  return (
    <div className="card sector-tile">
      <div className="card-head">
        <h3><Link href={`/sectors/${s.id}`}>{s.name}</Link>{s.nz ? <span className="sector-nz" title="New Zealand has its own players in this sector"> NZ</span> : null}</h3>
        <button className="link small" onClick={onHide} title={s.hidden ? "Show this sector in the list again" : "Leave this sector off the list (Settings keeps the choice)"}>{s.hidden ? "Show" : "Hide"}</button>
      </div>
      <ol className="sector-chain small">
        {s.stages.map((st) => (
          <li key={st.id}>
            <b>{st.name}</b>
            {st.production ? <span className="ink-2"> · made most in {st.production.top_name} ({st.production.top_share}%, {st.production.year})</span> : null}
            {st.exports ? <span className="ink-2"> · trade {money(st.exports.total)}, {st.exports.top_name} sells {st.exports.top_share}%</span> : null}
          </li>
        ))}
      </ol>
      {s.feeds ? <p className="caption">Feeds: {s.feeds}</p> : null}
    </div>
  );
}

function SectorsList({ list, focus }: { list: SectorList; focus?: string }) {
  const s = useSettings();
  // opened from a group on the overview: bring that group into view
  useEffect(() => {
    if (focus) document.getElementById(`group-${focus}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [focus]);
  const [showHidden, setShowHidden] = useState(false);
  const [q, setQ] = useState("");
  const hidden = useMemo(() => new Set((s.sectors_hidden || "").split(",").filter(Boolean)), [s.sectors_hidden]);
  const toggle = (id: string) => {
    const next = new Set(hidden);
    if (next.has(id)) next.delete(id); else next.add(id);
    saveSettings({ sectors_hidden: [...next].join(",") });
  };
  // A whole group at once (say, food): hides every sector in it, or shows them all again.
  const toggleGroup = (g: string) => {
    const ids = list.sectors.filter((x) => x.group === g).map((x) => x.id);
    const next = new Set(hidden);
    const allHidden = ids.every((id) => next.has(id));
    ids.forEach((id) => (allHidden ? next.delete(id) : next.add(id)));
    saveSettings({ sectors_hidden: [...next].join(",") });
  };
  const words = q.trim().toLowerCase();
  const shown = list.sectors.map((x) => ({ ...x, hidden: hidden.has(x.id) }))
    .filter((x) => (showHidden || !x.hidden) && (!words || `${x.name} ${x.feeds} ${x.stages.map((t) => t.name).join(" ")}`.toLowerCase().includes(words)));
  return (
    <>
      {!list.has_trade ? <NoTrade /> : null}
      <div className="chips-row small">
        <input type="search" placeholder="Find a sector or product" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Find a sector" />
        {hidden.size ? <label><input type="checkbox" checked={showHidden} onChange={(e) => setShowHidden(e.target.checked)} /> Show the {hidden.size} hidden</label> : null}
      </div>
      {Object.entries(list.groups).map(([g, name]) => {
        const here = shown.filter((x) => x.group === g);
        if (!here.length) return null;
        const allHidden = list.sectors.filter((x) => x.group === g).every((x) => hidden.has(x.id));
        return (
          <section key={g} id={`group-${g}`}>
            <h2>{name} <button className="link small" onClick={() => toggleGroup(g)}
              title="Hidden sectors stay loaded and keep their trade figures; they are only left off this list">
              {allHidden ? "Show this group" : "Hide this group"}</button></h2>
            <div className="grid three">{here.map((x) => <SectorTile key={x.id} s={x} onHide={() => toggle(x.id)} />)}</div>
          </section>
        );
      })}
    </>
  );
}

function pct(v: number | null) {
  return v === null || v === undefined ? "" : `${v > 0 ? "+" : ""}${v.toFixed(0)}%`;
}

function ByCountry({ country, setCountry }: { country: string; setCountry: (c: string) => void }) {
  const [since, setSince] = useState<number | undefined>(undefined);
  const [data, setData] = useState<SectorsByCountry | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sort, setSort] = useState<"exports" | "imports" | "balance">("exports");
  useEffect(() => {
    let live = true;
    api.sectorsByCountry({ country, since }).then((d) => { if (live) { setData(d); setError(null); } }).catch((e) => live && setError(String(e.message || e)));
    return () => { live = false; };
  }, [country, since]);
  const bars = useCallback(() => chapterBars(data?.chapters ?? []), [data]);
  const totals = useCallback(() => yearLines([
    { name: "Exports", points: (data?.totals ?? []).map((t) => [t[0], t[1]] as [number, number]) },
    { name: "Imports", points: (data?.totals ?? []).map((t) => [t[0], t[2]] as [number, number]) }], "US dollars"), [data]);
  const economy = useCallback(() => yearLines((data?.economy ?? []).map((e) => ({ name: e.name, points: e.points })), "% of GDP"), [data]);
  if (error) return <p className="error">{error}</p>;
  if (!data) return <p className="muted">Loading…</p>;
  const rows = [...data.chapters].sort((a, b) => sort === "balance" ? b.balance - a.balance : (b[sort] ?? 0) - (a[sort] ?? 0));
  const ask = () => openAsk({ title: `${data.name}: trade by sector, ${data.year}`, entity: country,
    parts: [{ key: "data", kind: "data", label: "Trade by chapter", text: data.chapters.slice(0, 40).map((c) => `${c.name}: exports ${money(c.exports)}, imports ${money(c.imports)}`).join("\n") }] });
  return (
    <>
      <div className="chips-row small">
        <CountryChoice value={country} onChange={setCountry} />
        <label>Change since <select value={data.since ?? ""} onChange={(e) => setSince(+e.target.value)}>
          {data.years.filter((y) => !data.year || y < data.year).map((y) => <option key={y} value={y}>{y}</option>)}
        </select></label>
        <span className="muted">Latest year {data.year ?? "none"}</span>
      </div>
      {!data.chapters.length ? <NoTrade /> : (
        <>
          <div className="grid two">
            <div className="card">
              <div className="card-head"><h3>What {data.name} sells and buys, {data.year} <Help note="sectors_country" /></h3>
                <CardAsk onAsk={ask} /></div>
              <EChart option={bars} height={460} label={`${data.name} exports and imports by product group`} />
            </div>
            <div className="card">
              <h3>Goods trade over the years</h3>
              <EChart option={totals} height={220} label={`${data.name} goods trade over time`} />
              {data.economy.length ? (<>
                <h3>The economy at home <Help note="sectors_economy" /></h3>
                <EChart option={economy} height={200} label={`${data.name} value added by broad sector`} />
              </>) : null}
            </div>
          </div>
          <div className="card">
            <div className="card-head"><h3>By product group (HS chapter)</h3>
              <div className="seg small" role="group" aria-label="Sort by">
                {(["exports", "imports", "balance"] as const).map((k) => <button key={k} className={sort === k ? "on" : ""} aria-pressed={sort === k} onClick={() => setSort(k)}>{k[0].toUpperCase() + k.slice(1)}</button>)}
              </div></div>
            <div style={{ overflowX: "auto", maxHeight: 560 }}>
              <table className="small">
                <thead><tr><th>Group</th><th className="num">Exports</th><th className="num">since {data.since}</th><th>Main buyers</th>
                  <th className="num">Imports</th><th className="num">since {data.since}</th><th>Main sellers</th><th className="num">Balance</th></tr></thead>
                <tbody>{rows.map((c) => (
                  <tr key={c.chapter}>
                    <td>{c.name} <span className="muted">{c.chapter}</span></td>
                    <td className="num">{c.exports ? money(c.exports) : ""}</td><td className="num">{pct(c.exports_change)}</td>
                    <td>{c.export_partners.slice(0, 3).map((p) => p.name).join(", ")}</td>
                    <td className="num">{c.imports ? money(c.imports) : ""}</td><td className="num">{pct(c.imports_change)}</td>
                    <td>{c.import_partners.slice(0, 3).map((p) => p.name).join(", ")}</td>
                    <td className={`num ${c.balance < 0 ? "neg" : ""}`}>{money(c.balance)}</td>
                  </tr>))}</tbody>
              </table>
            </div>
            <p className="caption">Goods only (no services). Main buyers and sellers are the top partners in the latest two years.
              Source: CEPII BACI, HS 1992 chapters, current US dollars.</p>
          </div>
        </>
      )}
      {data.stages.length ? (
        <div className="card">
          <h3>Where {data.name} stands in each sector</h3>
          <div style={{ overflowX: "auto", maxHeight: 480 }}>
            <table className="small">
              <thead><tr><th>Sector</th><th>Stage</th><th className="num">Production</th><th className="num">World rank</th>
                <th className="num">Exports</th><th className="num">World rank</th><th className="num">Imports</th></tr></thead>
              <tbody>{data.stages.map((r) => (
                <tr key={r.stage}>
                  <td><Link href={`/sectors/${r.sector}?stage=${r.stage}&country=${country}`}>{r.sector_name}</Link></td><td>{r.name}</td>
                  <td className="num">{r.production ? `${amount(r.production.value, r.unit)} (${r.production.share?.toFixed(1)}%)` : ""}</td>
                  <td className="num">{r.production ? `${r.production.rank} of ${r.production.of}` : ""}</td>
                  <td className="num">{r.exports ? `${money(r.exports.value)} (${r.exports.share?.toFixed(1)}%)` : ""}</td>
                  <td className="num">{r.exports ? `${r.exports.rank} of ${r.exports.of}` : ""}</td>
                  <td className="num">{r.imports ? money(r.imports.value) : ""}</td>
                </tr>))}</tbody>
            </table>
          </div>
          <p className="caption">Biggest world shares first. Shares are of the countries with figures in that year.</p>
        </div>
      ) : null}
    </>
  );
}

type Tab = "overview" | "sectors" | "prices" | "country";
const TABS: [Tab, string][] = [["overview", "Overview"], ["sectors", "Every sector"], ["prices", "Commodity prices"], ["country", "By country"]];

function SectorsPage() {
  const router = useRouter();
  const params = useSearchParams();
  const first = params.get("tab");
  const [tab, setTab] = useState<Tab>(TABS.some(([t]) => t === first) ? (first as Tab) : "overview");
  const [country, setCountry] = useState(params.get("country") ?? "NZL");
  const [ids, setIdsState] = useState<string[]>((params.get("ids") ?? "").split(",").filter(Boolean));
  const [focus, setFocus] = useState<string | undefined>(params.get("group") ?? undefined);
  const [list, setList] = useState<SectorList | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.sectors().then(setList).catch((e) => setError(String(e.message || e))); }, []);
  const url = (t: Tab, c: string, i: string[], g?: string) =>
    t === "country" ? `/sectors?tab=country&country=${c}` : t === "prices" ? `/sectors?tab=prices${i.length ? `&ids=${i.join(",")}` : ""}`
      : t === "sectors" ? `/sectors?tab=sectors${g ? `&group=${g}` : ""}` : "/sectors";
  const go = (t: Tab, c = country, i = ids, g?: string) => {
    setTab(t);
    setCountry(c);
    setIdsState(i);
    setFocus(g);
    router.replace(url(t, c, i, g), { scroll: false });
    if (t !== "sectors" || !g) window.scrollTo({ top: 0 });
  };
  if (error) return <p className="error">{error}</p>;
  if (!list) return <p className="muted">Loading…</p>;
  return (
    <div className="grid sector-page">
      <div className="title-row"><h1>Sectors</h1> <Help note="sectors" /></div>
      <div className="seg" role="tablist">
        {TABS.map(([t, label]) => (
          <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "on" : ""} onClick={() => go(t)}>{label}</button>
        ))}
      </div>
      {tab === "overview" ? <SectorsOverview list={list} openPrices={(i) => go("prices", country, i)} openGroup={(g) => go("sectors", country, ids, g)} />
        : tab === "sectors" ? <SectorsList list={list} focus={focus} />
        : tab === "prices" ? <CommodityPrices ids={ids} setIds={(i) => { setIdsState(i); router.replace(url("prices", country, i), { scroll: false }); }} />
        : <ByCountry country={country} setCountry={(c) => go("country", c)} />}
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<p className="muted">Loading…</p>}><SectorsPage /></Suspense>;
}
