"use client";

import { useEffect, useState } from "react";
import CardAsk from "@/components/CardAsk";
import EChart from "@/components/EChart";
import { useKeys } from "@/components/PageLook";
import { openAsk } from "@/lib/ai";
import { api, type GoodsCountry, type GoodsPort, type GoodsPortDetail, type GoodsRow } from "@/lib/api";
import { cssVar } from "@/lib/colors";
import { compact } from "@/lib/format";

// Transport > Goods by port: what goes in and out of each port, by kind of goods and by partner
// country, from national statistics (Stats NZ, Eurostat, UK DfT, US Census, Australia BITRE).

const ask = (title: string, label: string, text: string) => openAsk({ title, parts: [{ key: title, kind: "data", label, text }] });
const FREQ: Record<string, string> = { M: "12 months", Q: "4 quarters", A: "year", FY: "financial year" };
const money = (v: number | null | undefined, cur: string | null) => (v == null ? "" : `${cur ? `${cur} ` : ""}${compact(v)}`);
const tonnes = (v: number | null | undefined) => (v == null ? "" : `${compact(v)} t`);
const span = (from: string, to: string, freq: string) => (freq === "FY" ? `year to June ${to.slice(0, 4)}`
  : from === to ? to.slice(0, freq === "A" ? 4 : 7) : `${from.slice(0, 7)} to ${to.slice(0, 7)}`);

function Bars({ rows, measure, currency, dir }: { rows: GoodsRow[]; measure: "value" | "tonnes"; currency: string | null; dir: "in" | "out" }) {
  const v = (r: GoodsRow) => (measure === "value" ? (dir === "in" ? r.in_v : r.out_v) : (dir === "in" ? r.in_t : r.out_t)) ?? 0;
  const list = rows.filter((r) => v(r) > 0).sort((a, b) => v(b) - v(a)).slice(0, 12);
  const total = rows.reduce((s, r) => s + v(r), 0);
  if (!list.length) return <p className="small muted">Nothing {dir === "in" ? "coming in" : "going out"} stored.</p>;
  return (
    <div className="lbars">{list.map((r) => (
      <div key={r.id} className="lbar"><span className="lbar-name" title={r.name}>{r.name}</span>
        <span className="lbar-track"><span style={{ width: `${Math.max(1, (100 * v(r)) / v(list[0]))}%` }} /></span>
        <span className="mono">{measure === "value" ? money(v(r), null) : tonnes(v(r))}</span>
        <span className="mono muted">{total ? `${Math.round((100 * v(r)) / total)}%` : ""}</span></div>))}</div>
  );
}

function PortDetail({ k }: { k: string }) {
  const [d, setD] = useState<GoodsPortDetail | null>(null);
  const [err, setErr] = useState(false);
  const [dir, setDir] = useState<"in" | "out">("out");
  useEffect(() => { setD(null); setErr(false); api.goodsPort(k).then(setD).catch(() => setErr(true)); }, [k]);
  if (err) return <p className="small muted">No goods stored for this port.</p>;
  if (!d) return <p className="muted">Loading…</p>;
  const unit = d.measure === "value" ? d.currency ?? "" : "tonnes";
  const window = span(d.from, d.to, d.freq);
  const years = d.years;
  const colors = ["--series-1", "--series-2", "--series-3", "--series-4", "--series-5", "--series-6", "--series-7", "--series-8"];
  return (
    <div className="grid two">
      <div className="card" style={{ gridColumn: "1 / -1" }}>
        <div className="card-head"><span className="small ink-2">{d.name}: goods in and out each year ({d.measure === "value" ? `value, ${d.currency}` : "tonnes"})</span>
          <CardAsk onAsk={() => ask(`Goods through ${d.name}`, "Year, in tonnes, out tonnes, in value, out value",
            years.map((y) => `${y.year}${y.full ? "" : " (part)"}\t${y.in_t ?? ""}\t${y.out_t ?? ""}\t${y.in_v ?? ""}\t${y.out_v ?? ""}`).join("\n"))} /></div>
        {years.length > 1 || d.mix.rows.length ? (
          <EChart height={300} label={`Goods through ${d.name}`} option={() => {
            const ys = [...new Set(d.mix.rows.map((r) => r.year))].sort();
            const useMix = d.mix.keys.length > 1 && ys.length;
            return {
              tooltip: { trigger: "axis", valueFormatter: (v) => (typeof v === "number" ? compact(v) : String(v ?? "")) },
              legend: { type: "scroll", top: 0, textStyle: { color: cssVar("--ink-2") } },
              grid: { left: 56, right: 16, top: 40, bottom: 28 },
              xAxis: { type: "category", data: (useMix ? ys : years.map((y) => y.year)).map((y) => `${y}${years.find((x) => x.year === y)?.full === false ? "*" : ""}`),
                axisLabel: { color: cssVar("--ink-2") } },
              yAxis: { type: "value", name: unit, axisLabel: { color: cssVar("--ink-2"), formatter: (v: number) => compact(v) },
                splitLine: { lineStyle: { color: cssVar("--border") } } },
              series: useMix
                ? d.mix.keys.map((g, i) => ({ type: "bar", stack: "g", name: g.name, itemStyle: { color: cssVar(g.id === "other" ? "--muted" : colors[i % colors.length]) },
                  data: ys.map((y) => d.mix.rows.find((r) => r.year === y && r.id === g.id)?.v ?? 0) }))
                : (["in", "out"] as const).map((w, i) => ({ type: "bar", name: w === "in" ? "In" : "Out", itemStyle: { color: cssVar(colors[i]) },
                  data: years.map((y) => (d.measure === "value" ? (w === "in" ? y.in_v : y.out_v) : (w === "in" ? y.in_t : y.out_t)) ?? 0) })),
            };
          }} />
        ) : null}
        <p className="caption">{d.mix.keys.length > 1 ? "Biggest kinds of goods in and out together, the rest summed. " : ""}
          * part of a year. Source: {d.source}{d.freq === "FY" ? " (financial years to June)" : ""}.
          {d.kind === "air" ? " An airport: goods flown in and out." : ""}</p>
      </div>
      <div className="card">
        <div className="card-head"><span className="small ink-2">What goes {dir === "out" ? "out" : "in"}, {window}</span>
          <CardAsk onAsk={() => ask(`Goods at ${d.name}`, `Goods, ${dir === "in" ? "in" : "out"} (${unit})`,
            d.goods.map((g) => `${g.name}\t${d.measure === "value" ? (dir === "in" ? g.in_v : g.out_v) ?? "" : (dir === "in" ? g.in_t : g.out_t) ?? ""}`).join("\n"))} /></div>
        <div className="seg small" role="tablist">{(["out", "in"] as const).map((w) => (
          <button key={w} className={dir === w ? "on" : ""} onClick={() => setDir(w)}>{w === "out" ? "Going out" : "Coming in"}</button>))}</div>
        {d.goods.length ? <Bars rows={d.goods} measure={d.measure} currency={d.currency} dir={dir} />
          : <p className="small muted">{d.source} gives only totals for this port.</p>}
        <p className="caption">{d.measure === "value" ? `Value in ${d.currency}` : "Tonnes"}; share of all goods {dir === "out" ? "leaving" : "arriving"}.</p>
      </div>
      <div className="card">
        <div className="card-head"><span className="small ink-2">Where it goes to and comes from, {window}</span>
          <CardAsk onAsk={() => ask(`Partners of ${d.name}`, "Country, in, out", d.partners.map((p) => `${p.name}\t${p.in_t ?? p.in_v ?? ""}\t${p.out_t ?? p.out_v ?? ""}`).join("\n"))} /></div>
        {d.partners.length ? <Bars rows={d.partners} measure={d.partners.some((p) => p.in_v || p.out_v) ? "value" : "tonnes"} currency={d.currency} dir={dir} />
          : <p className="small muted">{d.source} gives no partner countries for this port.</p>}
        <p className="caption">Country goods were {dir === "out" ? "sent to" : "loaded in or came from"}; the switch on the left picks out or in.</p>
      </div>
    </div>
  );
}

export function GoodsView({ initial }: { initial?: string }) {
  const home = useKeys().split(",")[0] || "NZL";
  const [cs, setCs] = useState<GoodsCountry[] | null>(null);
  const [country, setCountry] = useState<string>("");
  const [ports, setPorts] = useState<GoodsPort[] | null>(null);
  const [key, setKey] = useState<string>(initial ?? "");
  const [filter, setFilter] = useState("");
  const [showAir, setShowAir] = useState(false);
  useEffect(() => {
    api.goodsCountries().then(async (l) => {
      setCs(l);
      const fromKey = initial ? await api.goodsPort(initial).then((d) => d.entity_id).catch(() => "") : "";
      setCountry((c) => c || fromKey || (l.find((x) => x.entity_id === home) ?? l[0])?.entity_id || "");
    }).catch(() => setCs([]));
  }, [home, initial]);
  useEffect(() => {
    if (!country) return;
    setPorts(null);
    api.goodsPorts(country).then((ps) => { setPorts(ps); setKey((k) => (k && ps.some((p) => p.key === k) ? k : ps.find((p) => p.kind === "sea")?.key ?? ps[0]?.key ?? "")); })
      .catch(() => setPorts([]));
  }, [country]);
  if (!cs) return <p className="muted">Loading…</p>;
  if (!cs.length) return (
    <div className="card"><h3>Goods by port</h3><p>Nothing stored yet. Run <code>.\update.bat</code> then <code>.\refresh.bat</code> (Settings: Transport, Goods by port).
      US ports need a free <code>CENSUS_API_KEY</code> in Settings: Keys.</p></div>);
  const shown = (ports ?? []).filter((p) => (showAir || p.kind === "sea") && p.name.toLowerCase().includes(filter.toLowerCase()));
  const valueCol = (ports ?? []).some((p) => p.in_v || p.out_v);
  const cur = ports?.find((p) => p.currency)?.currency ?? null;
  return (
    <>
      <div className="chips-row small">
        <label className="small">Country{" "}
          <select value={country} onChange={(e) => { setKey(""); setCountry(e.target.value); }} aria-label="Country">
            {cs.map((c) => <option key={c.entity_id} value={c.entity_id}>{c.name} ({c.ports} ports)</option>)}</select></label>
        <input placeholder="Filter ports" value={filter} onChange={(e) => setFilter(e.target.value)} style={{ width: 140 }} aria-label="Filter ports" />
        {(ports ?? []).some((p) => p.kind === "air") ? <label className="small"><input type="checkbox" checked={showAir} onChange={(e) => setShowAir(e.target.checked)} /> Airports too</label> : null}
      </div>
      <div className="card">
        <div className="card-head"><span className="small ink-2">Ports of {cs.find((c) => c.entity_id === country)?.name ?? country}, busiest first (last {FREQ[ports?.[0]?.freq ?? "A"] ?? "year"} stored)</span>
          <CardAsk onAsk={() => ask(`Ports of ${country}`, "Port, tonnes in, tonnes out, value in, value out",
            (ports ?? []).map((p) => `${p.name}\t${p.in_t ?? ""}\t${p.out_t ?? ""}\t${p.in_v ?? ""}\t${p.out_v ?? ""}`).join("\n"))} /></div>
        {!ports ? <p className="muted">Loading…</p> : (
          <div style={{ maxHeight: 280, overflowY: "auto" }}>
            <table className="small"><thead><tr><th>Port</th><th className="num">Tonnes in</th><th className="num">Tonnes out</th>
              {valueCol ? <><th className="num">Value in</th><th className="num">Value out</th></> : null}<th>Period</th></tr></thead>
              <tbody>{shown.map((p) => (
                <tr key={p.key} className={p.key === key ? "on" : ""} style={{ cursor: "pointer" }} onClick={() => setKey(p.key)}>
                  <td>{p.name}{p.kind === "air" ? <span className="muted"> (air)</span> : null}</td>
                  <td className="num">{tonnes(p.in_t)}</td><td className="num">{tonnes(p.out_t)}</td>
                  {valueCol ? <><td className="num">{money(p.in_v, cur)}</td><td className="num">{money(p.out_v, cur)}</td></> : null}
                  <td className="muted">{span(p.from, p.to, p.freq)}</td></tr>))}</tbody></table>
          </div>)}
        <p className="caption">From {cs.find((c) => c.entity_id === country)?.sources.join(", ")}. Click a port for its goods and partners.</p>
      </div>
      {key ? <PortDetail k={key} /> : null}
    </>
  );
}

// A link from a PortWatch port to its goods, when national statistics have the port.
export function GoodsLink({ portId, name }: { portId: string; name: string }) {
  const [keys, setKeys] = useState<string[]>([]);
  useEffect(() => { api.goodsFor(portId).then(setKeys).catch(() => setKeys([])); }, [portId]);
  if (!keys.length) return null;
  return <p className="small"><a href={`/transport?tab=goods&port=${encodeURIComponent(keys[0])}`}>What goods go through {name}, and where to</a></p>;
}
