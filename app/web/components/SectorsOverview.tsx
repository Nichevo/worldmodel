"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import CardAsk from "@/components/CardAsk";
import Help from "@/components/Help";
import { api, type PriceItem, type SectorList, type SectorOverview } from "@/lib/api";
import { openAsk } from "@/lib/ai";
import { sparkPath } from "@/lib/look";
import { change, groupVar, priceName, priceUnit, priceValue } from "@/lib/prices";
import { money } from "@/lib/sectors";
import { useSettings } from "@/lib/settings";

// The Sectors front page: headline figures, this month's prices, world trade by sector
// group, where New Zealand counts, and every sector as a tile with its own figures.

const ord = (k: number) => {
  const s = ["th", "st", "nd", "rd"], v = k % 100;
  return `${k}${s[(v - 20) % 10] ?? s[v] ?? s[0]}`;
};
const pctSince = (now: number, then: number) => (then ? Math.round(100 * (now / then - 1)) : null);

function Spark({ values, w = 88, h = 24, color }: { values: number[]; w?: number; h?: number; color: string }) {
  const d = sparkPath(values.map((v, i) => [i, v] as [number, number]), w, h);
  if (!d) return <svg width={w} height={h} aria-hidden="true" />;
  const end = d.split(/[ML]/).filter(Boolean).at(-1)!.split(",").map(Number);
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Last five years">
      <path d={d} fill="none" stroke={color} strokeWidth={1.6} strokeLinejoin="round" />
      <circle cx={end[0]} cy={end[1]} r={2.3} fill={color} />
    </svg>
  );
}

function PriceRow({ p, color, onOpen }: { p: PriceItem; color: string; onOpen: (id: string) => void }) {
  const c = change(p.y1);
  return (
    <button className="sx-price" onClick={() => onOpen(p.id)}
      title={`${priceName(p.name)}: ${priceValue(p.value)} ${p.unit}, ${p.date}. Ten-year range ${priceValue(p.low10)} to ${priceValue(p.high10)}. Open on the Commodity prices tab.`}>
      <span className="nm">{priceName(p.name)} <span className="muted small">{priceUnit(p.unit)}</span></span>
      <Spark values={p.spark} w={72} color={color} />
      <span className="v">{priceValue(p.value)}</span>
      <span className={`c ${c.cls}`}>{c.text}</span>
      <span className="sx-range" aria-label={`${p.pos10}% of the way from its ten-year low to its high`}><span style={{ left: `${p.pos10}%` }} /></span>
    </button>
  );
}

const SORTS = { group: "By group", trade: "Biggest trade", growth: "Fastest growing trade", move: "Biggest price move a year",
  concentrated: "Most concentrated", nz: "New Zealand's share" } as const;

export default function SectorsOverview({ list, openPrices, openGroup }: {
  list: SectorList; openPrices: (ids: string[]) => void; openGroup: (group: string) => void }) {
  const s = useSettings();
  const [d, setD] = useState<SectorOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<keyof typeof SORTS>("group");
  useEffect(() => { api.sectorsOverview().then(setD).catch((e) => setError(String(e.message || e))); }, []);
  const hidden = useMemo(() => new Set((s.sectors_hidden || "").split(",").filter(Boolean)), [s.sectors_hidden]);
  const tiles = useMemo(() => {
    if (!d) return [];
    const words = q.trim().toLowerCase();
    const order = Object.keys(list.groups);
    const rows = list.sectors.filter((x) => !hidden.has(x.id) && (!words || `${x.name} ${x.feeds} ${x.stages.map((t) => t.name).join(" ")}`.toLowerCase().includes(words)))
      .map((x) => ({ card: x, o: d.sectors[x.id] }));
    const by: Record<string, (r: (typeof rows)[number]) => number> = {
      group: (r) => order.indexOf(r.card.group) * 1000 + list.sectors.indexOf(r.card),
      trade: (r) => -(r.o?.trade?.value ?? 0),
      growth: (r) => -(r.o?.trade ? pctSince(r.o.trade.value, r.o.trade.then) ?? -999 : -999),
      move: (r) => -Math.abs(r.o?.price?.y1 ?? 0),
      concentrated: (r) => -(r.o?.makers?.rows[0]?.share ?? 0),
      nz: (r) => -(r.o?.nz?.share ?? 0),
    };
    return rows.sort((a, b) => by[sort](a) - by[sort](b));
  }, [d, list, hidden, q, sort]);
  if (error) return <p className="error">{error}</p>;
  if (!d) return <p className="muted">Loading…</p>;
  const wt = d.heads.world_trade;
  const askBoard = () => openAsk({ title: "Commodity prices this month", page: "/sectors",
    parts: [{ key: "data", kind: "data", label: "Price board", text: d.board.map((g) => `${g.name}:\n` + g.items.map((p) =>
      `  ${priceName(p.name)} ${priceValue(p.value)} ${p.unit} (${p.date}); a year: ${p.y1 ?? "?"}%; five years: ${p.y5 ?? "?"}%; ten-year range ${priceValue(p.low10)}-${priceValue(p.high10)}`).join("\n")).join("\n") }] });
  const askTrade = () => openAsk({ title: "World goods trade by sector group", page: "/sectors",
    parts: [{ key: "data", kind: "data", label: "Trade by group", text: d.trade_groups.map((g) =>
      `${g.name}: ${money(g.value)} in ${g.year} (${money(g.then)} in ${g.since}); top sellers ${g.top.map((t) => `${t.name} ${t.share}%`).join(", ")}`).join("\n") }] });
  const askNz = () => openAsk({ title: "Where New Zealand counts in world trade", entity: "NZL", page: "/sectors",
    parts: [{ key: "data", kind: "data", label: "New Zealand's biggest world shares", text: d.nz.map((z) =>
      `${z.name} (${z.stage}): ${z.share}% of world exports, ${ord(z.rank)} of ${z.of}, ${z.year}; price over a year ${z.price_y1 ?? "?"}%`).join("\n") }] });
  const maxTrade = Math.max(1, ...d.trade_groups.map((g) => g.value));
  return (
    <>
      <div className="sx-heads">
        {wt ? (
          <div className="card"><span className="lbl">World goods trade</span><span className="big">{money(wt.value).replace("US$ ", "$")}</span>
            <span className="small muted">{wt.year}, {change(pctSince(wt.value, wt.then)).text} since {wt.then_year}</span></div>
        ) : null}
        {d.heads.rises[0] ? (
          <div className="card"><span className="lbl">Biggest price rise this year</span>
            <span className="big">{priceName(d.heads.rises[0].name)} <span className="sx-up">{change(d.heads.rises[0].y1).text}</span></span>
            <span className="small muted">then {d.heads.rises.slice(1).map((p) => `${priceName(p.name).toLowerCase()} ${change(p.y1).text}`).join(", ")}</span></div>
        ) : null}
        {d.heads.falls[0] ? (
          <div className="card"><span className="lbl">Biggest price fall this year</span>
            <span className="big">{priceName(d.heads.falls[0].name)} <span className="sx-down">{change(d.heads.falls[0].y1).text}</span></span>
            <span className="small muted">then {d.heads.falls.slice(1).map((p) => `${priceName(p.name).toLowerCase()} ${change(p.y1).text}`).join(", ")}</span></div>
        ) : null}
        {d.heads.concentrated[0] ? (
          <div className="card"><span className="lbl">Most concentrated</span>
            <span className="big"><Link href={`/sectors/${d.heads.concentrated[0].sector}`}>{d.heads.concentrated[0].name}</Link></span>
            <span className="small muted">{d.heads.concentrated[0].top.name} makes {d.heads.concentrated[0].top.share}% of the world&apos;s {d.heads.concentrated[0].stage.toLowerCase()}</span></div>
        ) : null}
      </div>

      {d.board.length ? (
        <div className="card">
          <div className="card-head">
            <h3>Prices this month <span className="muted small">· line: last five years · bar: where today sits between its ten-year low and high</span> <Help note="sectors_prices" /></h3>
            <span className="chips-row small"><button className="link small" onClick={() => openPrices([])}>All prices</button><CardAsk onAsk={askBoard} /></span>
          </div>
          <div className="sx-board">
            {d.board.map((g) => {
              const color = groupVar(g.sector_group ?? g.id);
              const idx = g.index ? change(g.index.y1) : null;
              return (
                <div key={g.id} style={{ ["--sg" as string]: color }}>
                  <div className="sx-group-head">
                    <span className="dot" />
                    <b>{g.sector_group ? <a href="#" onClick={(e) => { e.preventDefault(); openGroup(g.sector_group!); }}>{g.name}</a> : g.name}</b>
                    {g.index && idx ? <button className="link idx" onClick={() => openPrices([g.index!.id])}>index <span className={idx.cls}>{idx.text}</span> on a year</button> : null}
                  </div>
                  {g.items.map((p) => <PriceRow key={p.id} p={p} color={color} onOpen={(id) => openPrices([id])} />)}
                </div>
              );
            })}
          </div>
          <p className="caption">Change against the same month a year ago. World Bank Pink Sheet (nominal US$){d.board.some((g) => g.id === "nz") ? ", FAO food price index and ANZ commodity price index" : ""}.
            Click a price to open it on the Commodity prices tab.</p>
        </div>
      ) : (
        <div className="card"><p>No commodity prices stored yet. They come from the World Bank Pink Sheet during <code>.\refresh.bat</code>.</p></div>
      )}

      <div className="grid two">
        <div className="card">
          <div className="card-head"><h3>World goods trade by sector group</h3><CardAsk onAsk={askTrade} /></div>
          <div className="sx-bars">
            {d.trade_groups.map((g) => {
              const c = change(pctSince(g.value, g.then));
              return (
                <div className="sx-bar" key={g.id} style={{ ["--sg" as string]: groupVar(g.id) }}>
                  <a href="#" onClick={(e) => { e.preventDefault(); openGroup(g.id); }}>{g.name}</a>
                  <span className="track"><span style={{ width: `${(100 * g.value) / maxTrade}%` }} /></span>
                  <span className="v">{money(g.value).replace("US$ ", "$").replace(" trillion", " trn").replace(" billion", " bn")}</span>
                  <span className="note"><span className={c.cls}>{c.text}</span> since {g.since} · {g.top.map((t) => `${t.name} ${t.share}%`).join(", ")}</span>
                </div>
              );
            })}
          </div>
          <p className="caption">Exports in the latest BACI year, every stage of every sector in the group added up (ore and metal both count), so groups overlap
            less than they look. Top sellers are shares of the group.</p>
        </div>
        <div className="card">
          <div className="card-head"><h3>Where New Zealand counts</h3><CardAsk onAsk={askNz} /></div>
          {d.nz.length ? (
            <>
              {d.nz.map((z) => {
                const c = change(z.price_y1);
                return (
                  <div className="sx-nz" key={z.sector}>
                    <span><Link href={`/sectors/${z.sector}?country=NZL`}>{z.name}</Link> <span className="muted small">{z.stage}</span></span>
                    <span className="v">{z.share.toFixed(1)}%</span>
                    <span className="small muted" style={{ textAlign: "right" }}>{ord(z.rank)} of {z.of}</span>
                    <span className={`v ${c.cls}`} title="The sector's price over the past year">{c.text}</span>
                  </div>
                );
              })}
              <p className="caption">New Zealand&apos;s biggest shares of world exports, with the sector&apos;s price over the past year.</p>
            </>
          ) : <p className="muted">No trade by product stored yet (CEPII BACI).</p>}
        </div>
      </div>

      <div className="chips-row small" style={{ justifyContent: "space-between" }}>
        <h2 style={{ margin: 0 }}>Every sector at a glance</h2>
        <span className="chips-row small">
          <input type="search" placeholder="Find a sector or product" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Find a sector" />
          <label>Sort <select value={sort} onChange={(e) => setSort(e.target.value as keyof typeof SORTS)}>
            {Object.entries(SORTS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          {hidden.size ? <span className="muted">{hidden.size} hidden (Every sector tab)</span> : null}
        </span>
      </div>
      <div className="sx-tiles">
        {tiles.map(({ card, o }) => {
          const color = groupVar(card.group);
          const tr = o?.trade;
          const tc = tr ? change(pctSince(tr.value, tr.then)) : null;
          const pc = o?.price ? change(o.price.y1) : null;
          const mk = o?.makers;
          return (
            <div className="card sx-tile" key={card.id} style={{ ["--sg" as string]: color }}>
              <span className="stripe" />
              <div className="hd">
                <Link href={`/sectors/${card.id}`}>{card.name}</Link>
                <span className="grp">{list.groups[card.group]}</span>
                <span className="tools">{card.nz ? <span className="sector-nz" title="New Zealand has its own players in this sector">NZ</span> : null}</span>
              </div>
              <div className="two">
                <div>
                  <div className="k">World exports{tr ? `, ${tr.year}` : ""}</div>
                  <div className="n">{tr ? money(tr.value).replace("US$ ", "$").replace(" trillion", " trn").replace(" billion", " bn").replace(" million", " m") : "–"}</div>
                  {tr && tc ? <div className="k"><span className={tc.cls}>{tc.text}</span> since {tr.since}</div> : null}
                </div>
                <div>
                  {o?.price ? (
                    <button className="link" style={{ padding: 0, textAlign: "left" }} onClick={() => openPrices([o.price!.id])} title="Open on the Commodity prices tab">
                      <div className="k">{priceName(o.price.name)}, 5 years</div>
                      <Spark values={o.price.spark} w={120} h={22} color={color} />
                      {pc ? <div className="k"><span className={pc.cls}>{pc.text}</span> on a year</div> : null}
                    </button>
                  ) : <div className="k">No price series</div>}
                </div>
              </div>
              {mk && mk.rows.length ? (
                <div className="makers">
                  <span className="k">Who makes the most ({mk.stage.toLowerCase()}, {mk.year})</span>
                  <span className="stack">
                    {mk.rows.map((r, i) => <span key={r.entity_id} style={{ width: `${r.share ?? 0}%`, opacity: [1, 0.62, 0.36][i] }} />)}
                  </span>
                  <span>{mk.rows.map((r) => `${r.name} ${r.share}%`).join(", ")}</span>
                </div>
              ) : <div className="chain">{card.stages.map((st) => st.name).join(" → ")}</div>}
              <div className="nzline">New Zealand: {o?.nz
                ? `${ord(o.nz.rank)} of ${o.nz.of} ${o.nz.what === "exports" ? "sellers" : "makers"} of ${o.nz.stage.toLowerCase()}, ${o.nz.share.toFixed(1)}% of the world`
                : "no exports or production recorded"}</div>
            </div>
          );
        })}
      </div>
    </>
  );
}
