"use client";

import Link from "next/link";
import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import AskButton from "@/components/AskButton";
import EChart from "@/components/EChart";
import { api, type NumbeoCompare } from "@/lib/api";
import { cssVar, seriesColor } from "@/lib/colors";
import { logHistory } from "@/lib/history";

// Numbeo prices side by side for every city and country fetched so far: one column per
// place, one row per item, each compared with the first place picked; and a bar chart of
// one item across all of them.
export default function PricesPage() {
  const [data, setData] = useState<NumbeoCompare | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<string[] | null>(null);
  const [item, setItem] = useState<string>("");
  const [section, setSection] = useState("");
  const [year, setYear] = useState<number | undefined>();
  const [since, setSince] = useState<number | undefined>();
  useEffect(() => {
    api.numbeoCompare({ year, since }).then((d) => {
      setData(d);
      setPicked((p) => p ?? d.places.slice(0, 6).map((x) => `${x.kind}:${x.id}`));
      setItem((i) => i || d.items.find((x) => /meal.*inexpensive/i.test(x.item))?.item || d.items[0]?.item || "");
    }).catch((e) => setError(String(e.message || e)));
  }, [year, since]);
  useEffect(() => { logHistory({ kind: "page", title: "Compare prices", url: "/prices" }); }, []);
  const key = (p: NumbeoCompare["places"][number]) => `${p.kind}:${p.id}`;
  const shown = useMemo(() => (data && picked ? picked.map((k) => data.places.find((p) => key(p) === k)).filter(Boolean) : []) as NumbeoCompare["places"], [data, picked]);
  const sections = useMemo(() => [...new Set((data?.items ?? []).map((i) => i.section))], [data]);
  const usd = (v: number | undefined) => (v === undefined ? "–" : `$${v.toLocaleString(undefined, { maximumFractionDigits: v < 100 ? 2 : 0 })}`);

  const all = data?.places.filter((p) => p.values[item] !== undefined).sort((a, b) => a.values[item] - b.values[item]) ?? [];
  const option = useCallback(() => ({
    backgroundColor: "transparent",
    textStyle: { fontFamily: "system-ui, -apple-system, 'Segoe UI', sans-serif", color: cssVar("--ink-2") },
    grid: { left: 8, right: 40, top: 8, bottom: 8, containLabel: true },
    tooltip: { trigger: "axis" as const, axisPointer: { type: "shadow" as const }, backgroundColor: cssVar("--surface"), borderColor: cssVar("--border"),
      textStyle: { color: cssVar("--ink") }, valueFormatter: (v: unknown) => usd(v as number) },
    xAxis: { type: "value" as const, axisLabel: { color: cssVar("--muted"), formatter: (v: number) => `$${v}` }, splitLine: { lineStyle: { color: cssVar("--border") } } },
    yAxis: { type: "category" as const, data: all.map((p) => p.name), axisLabel: { color: cssVar("--ink-2") } },
    series: [{ type: "bar" as const, data: all.map((p) => ({ value: p.values[item], itemStyle: { color: picked?.includes(key(p)) ? seriesColor(0) : cssVar("--muted") } })),
      label: { show: true, position: "right" as const, formatter: (x: { value?: unknown }) => usd(x.value as number), color: cssVar("--ink-2"), fontSize: 11 } }],
  }), [all, item, picked]); // eslint-disable-line react-hooks/exhaustive-deps

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p className="muted">Loading…</p>;
  const toggle = (k: string) => setPicked((p) => (p ?? []).includes(k) ? (p ?? []).filter((x) => x !== k) : [...(p ?? []), k]);
  const base = shown[0];
  const rows = data.items.filter((i) => !section || i.section === section);
  const csv = () => ["Item," + shown.map((p) => `"${p.name}"`).join(","),
    ...rows.map((i) => `"${i.item}",` + shown.map((p) => p.values[i.item] ?? "").join(","))].join("\n");

  return (
    <div className="grid">
      <div className="title-row">
        <h1 style={{ marginBottom: 4 }}>Compare prices</h1>
        <AskButton title="Numbeo prices compared" parts={() => [{ key: "data", kind: "data", label: "Prices in US$ (Numbeo)", text: csv() }]} />
      </div>
      <p className="ink-2" style={{ marginTop: 0 }}>
        Every city and country whose Numbeo prices you have fetched (the &quot;Get Numbeo prices&quot; button on a city or country page).
        Prices in US dollars, crowd-sourced, as of the date each page was fetched. Every fetch is kept under its year
        (the last one in a year stands for it), so you can look back or see how prices moved.
      </p>
      <div className="chips-row small">
        <label>Prices from <select value={year ?? ""} onChange={(e) => setYear(e.target.value ? Number(e.target.value) : undefined)}>
          <option value="">the latest fetch of each place</option>
          {data.years.map((y) => <option key={y} value={y}>{y}</option>)}
        </select></label>
        <label>Show the change since <select value={since ?? ""} onChange={(e) => setSince(e.target.value ? Number(e.target.value) : undefined)}>
          <option value="">(no change; compare places)</option>
          {data.years.map((y) => <option key={y} value={y}>{y}</option>)}
        </select></label>
        {data.years.length < 2 && <span className="muted">Fetch a place again next year to compare years.</span>}
      </div>
      {data.places.length === 0 && <p className="muted">No Numbeo pages fetched yet. Open a city from <Link href="/cities">Cities</Link> and press &quot;Get Numbeo prices&quot;.</p>}
      {data.places.length > 0 && (
        <>
          <div className="chips-row small">
            <span className="ink-2">Places:</span>
            {data.places.map((p) => (
              <button key={key(p)} className={`chip ${picked?.includes(key(p)) ? "" : "off"}`} aria-pressed={picked?.includes(key(p))} onClick={() => toggle(key(p))}
                title={`Fetched ${p.fetched_at?.slice(0, 10)}`}>{p.name}</button>
            ))}
          </div>
          <section className="card">
            <div className="chips-row small">
              <label>Item <select value={item} onChange={(e) => setItem(e.target.value)} style={{ maxWidth: 420 }}>
                {data.items.map((i) => <option key={i.item} value={i.item}>{i.item}</option>)}
              </select></label>
            </div>
            <EChart option={option} height={Math.max(160, all.length * 26 + 30)} label={`${item} by place`} />
            <p className="caption">Every place fetched, cheapest first; the ones picked above in colour.</p>
          </section>
          {shown.length > 0 && (
            <section className="card">
              <div className="chips-row small">
                <label>Section <select value={section} onChange={(e) => setSection(e.target.value)}>
                  <option value="">All</option>
                  {sections.map((x) => <option key={x} value={x}>{x}</option>)}
                </select></label>
                {since ? <span className="muted">Percentages show each price&apos;s change since {since} (none where that place was not fetched in {since}).</span>
                  : shown.length > 1 && <span className="muted">Percentages compare each place with {base.name}.</span>}
              </div>
              <div style={{ overflowX: "auto" }}>
                <table className="summary-table price-compare">
                  <thead><tr><th>Item</th>{shown.map((p) => <th key={key(p)} className="num">{p.name}</th>)}</tr></thead>
                  <tbody>
                    {rows.map((i, n) => (
                      <Fragment key={i.item}>
                        {(n === 0 || rows[n - 1].section !== i.section) && <tr><td colSpan={shown.length + 1}><b>{i.section}</b></td></tr>}
                        <tr>
                          <td>{i.item}</td>
                          {shown.map((p, j) => {
                            const v = p.values[i.item];
                            const b = since ? p.before?.[i.item] : j > 0 ? base.values[i.item] : undefined;
                            const d = v !== undefined && b ? (v / b - 1) * 100 : null;
                            return <td key={key(p)} className="num">{usd(v)}{d !== null && Math.abs(d) >= 1 &&
                              <span className={`small ${d < 0 ? "cheaper" : "dearer"}`}> {d > 0 ? "+" : ""}{d.toFixed(0)}%</span>}</td>;
                          })}
                        </tr>
                      </Fragment>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="caption">Source: Numbeo. Each column links to its page: {shown.map((p, i) => <span key={key(p)}>{i > 0 && " · "}<a href={p.url ?? "#"} target="_blank" rel="noreferrer">{p.name}</a></span>)}</p>
            </section>
          )}
        </>
      )}
    </div>
  );
}
