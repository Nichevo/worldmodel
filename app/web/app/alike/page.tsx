"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import AskButton from "@/components/AskButton";
import CountryChoice from "@/components/CountryChoice";
import EChart from "@/components/EChart";
import IndicatorSelect from "@/components/IndicatorSelect";
import WorldMap, { type Scale } from "@/components/WorldMap";
import { alikeApi, GROUP_COLORS, type Alike, type AlikePreset, type MoveAlike } from "@/lib/alike";
import { api, type Indicator } from "@/lib/api";
import { cardLinesOption, type CardLine } from "@/lib/charts";
import { formatValue } from "@/lib/format";

// Countries like this one: the nearest countries on a set of indicators in a year, how that
// changed decade by decade, and groups of countries whose figures rise and fall together.
const THIS_YEAR = new Date().getFullYear();

export default function AlikePage() {
  return <Suspense fallback={<p className="muted">Loading…</p>}><Alikes /></Suspense>;
}

function Alikes() {
  const params = useSearchParams();
  const [entity, setEntity] = useState(params.get("e") ?? "NZL");
  const [preset, setPreset] = useState(params.get("set") ?? "everything");
  const [year, setYear] = useState(Number(params.get("y")) || THIS_YEAR - 2);
  const [presets, setPresets] = useState<AlikePreset[]>([]);
  const [inds, setInds] = useState<Indicator[]>([]);
  useEffect(() => { alikeApi.presets().then(setPresets).catch(() => {}); api.indicators().then(setInds).catch(() => {}); }, []);
  useEffect(() => {
    const q = new URLSearchParams({ e: entity, set: preset, y: String(year) }).toString();
    if (q !== window.location.search.slice(1)) window.history.replaceState(null, "", `?${q}`);
  }, [entity, preset, year]);
  return (
    <div className="grid">
      <div>
        <h1>Countries like this one</h1>
        <p className="ink-2" style={{ marginTop: 0 }}>
          The countries nearest to one country on a set of figures, how that has changed since 1960, and groups of
          countries whose figures go up and down together.
        </p>
      </div>
      <div className="controls">
        <CountryChoice value={entity} onChange={setEntity} />
        <div className="seg small" role="group" aria-label="Compare on">
          {presets.map((p) => <button key={p.id} className={preset === p.id ? "on" : ""} aria-pressed={preset === p.id}
            title={p.indicators.join(", ")} onClick={() => setPreset(p.id)}>{p.name}</button>)}
        </div>
        <label className="small">Year <b>{year}</b>{" "}
          <input type="range" min={1960} max={THIS_YEAR - 1} step={1} value={year} onChange={(e) => setYear(+e.target.value)} aria-label="Year" />
        </label>
        <span className="small">
          {[1970, 1990, 2010, THIS_YEAR - 2].map((y) => <button key={y} className="link small" style={{ marginRight: 8 }} onClick={() => setYear(y)}>{y}</button>)}
        </span>
      </div>
      <Nearest entity={entity} preset={preset} year={year} inds={inds} onPick={setEntity} />
      <MoveAlikeCard inds={inds} />
    </div>
  );
}

function Nearest({ entity, preset, year, inds, onPick }: { entity: string; preset: string; year: number; inds: Indicator[]; onPick: (id: string) => void }) {
  const [d, setD] = useState<Alike | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    const t = setTimeout(() => alikeApi.like(entity, preset, year, 12, true)
      .then((x) => { if (live) { setD(x); setError(null); } }).catch((e) => live && setError(String(e.message || e))), 150);
    return () => { live = false; clearTimeout(t); };
  }, [entity, preset, year]);
  const unit = (id: string) => inds.find((i) => i.indicator_id === id);
  const fmt = (id: string, v: number | null | undefined) => formatValue(v, unit(id)?.unit ?? "", unit(id)?.decimals ?? 1);
  const label = (id: string) => d?.indicator_names[id] ?? id;
  // Column heads and "closest on": the name without its bracketed note, cut short (the full name is the head's tooltip).
  const short = (id: string) => { const n = label(id).replace(/\s*\(.*\)\s*$/, ""); return n.length > 32 ? `${n.slice(0, 30)}…` : n; };
  if (error) return <p className="error">{error}</p>;
  if (!d) return <p className="muted">Loading…</p>;
  const cols = d.used.map((u) => u.indicator_id);
  const text = () => [
    { key: "near", kind: "data" as const, label: `Countries most like ${d.name}, ${d.year}`,
      text: [`Country\tLikeness\t${cols.map(label).join("\t")}`, `${d.name} (itself)\t\t${cols.map((c) => fmt(c, d.own[c])).join("\t")}`,
        ...d.nearest.map((r) => `${r.name}\t${r.likeness}\t${cols.map((c) => fmt(c, r.values[c])).join("\t")}`)].join("\n") },
    { key: "how", kind: "description" as const, label: "How likeness is worked out",
      text: "Each indicator is put on one scale across countries for the year (logged first when it spans more than a hundredfold), and countries are ranked by their average distance over the indicators both have. Likeness = 100 × e^(−distance)." },
    ...(d.decades ? [{ key: "dec", kind: "data" as const, label: "Nearest by decade",
      text: d.decades.map((x) => `${x.year}: ${x.nearest.map((n) => `${n.name} (${n.likeness})`).join(", ") || "too few figures"}`).join("\n") }] : []),
  ];
  return (
    <>
      <section className="card">
        <div className="card-head">
          <h3>Most like {d.name} in {d.year}</h3>
          <span className="card-actions"><AskButton title={`Countries like ${d.name}`} entity={d.entity_id} parts={text} /></span>
        </div>
        {d.note ? <p className="muted">{d.note}</p> : (
          <div className="table-scroll">
            <table className="small summary-table">
              <thead><tr><th>Country</th><th className="num" title="100 is identical on every figure; 37 is one standard step apart on average">Likeness</th>
                <th>Closest on</th>{cols.map((c) => <th key={c} className="num" title={label(c)}>{short(c)}</th>)}</tr></thead>
              <tbody>
                <tr className="muted"><td><b>{d.name}</b></td><td /><td />{cols.map((c) => <td key={c} className="num">{fmt(c, d.own[c])}</td>)}</tr>
                {d.nearest.map((r) => (
                  <tr key={r.entity_id}>
                    <td><Link href={`/entity/${r.entity_id}`}>{r.name}</Link>{" "}
                      <button className="link small" title={`Find the countries like ${r.name}`} onClick={() => onPick(r.entity_id)}>like it</button></td>
                    <td className="num">{r.likeness.toFixed(0)}</td>
                    <td className="small muted">{r.closest_on.slice(0, 2).map(short).join(", ")}</td>
                    {cols.map((c) => <td key={c} className="num">{fmt(c, r.values[c])}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="caption">
          On {d.used.length} figures, each from its main source, the latest within four years of {d.year}. Logged first: {d.used.filter((u) => u.logged).map((u) => label(u.indicator_id)).join(", ") || "none"}.
          A country needs at least six in ten of the figures to be listed.
        </p>
      </section>
      {d.decades && d.decades.length > 0 && (
        <section className="card">
          <h3>Who {d.name} was most like, decade by decade</h3>
          <div className="table-scroll">
            <table className="small summary-table">
              <thead><tr><th>Year</th><th>Nearest five</th><th className="num">Figures</th></tr></thead>
              <tbody>{d.decades.map((x) => (
                <tr key={x.year}><td>{x.year}</td>
                  <td>{x.nearest.length ? x.nearest.map((n, i) => <span key={n.entity_id}>{i ? ", " : ""}<Link href={`/entity/${n.entity_id}`}>{n.name}</Link> <span className="muted">{n.likeness.toFixed(0)}</span></span>) : <span className="muted">too few figures</span>}</td>
                  <td className="num">{x.used}</td></tr>
              ))}</tbody>
            </table>
          </div>
          <p className="caption">Fewer figures go back further, so early decades compare on less.</p>
        </section>
      )}
    </>
  );
}

function MoveAlikeCard({ inds }: { inds: Indicator[] }) {
  const router = useRouter();
  const [indicator, setIndicator] = useState("gdp_growth");
  const [start, setStart] = useState(1995);
  const [groups, setGroups] = useState(6);
  const [d, setD] = useState<MoveAlike | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [shown, setShown] = useState<number | null>(null);
  useEffect(() => {
    let live = true;
    setD(null);
    alikeApi.move(indicator, start, undefined, groups).then((x) => { if (live) { setD(x); setError(null); setShown(null); } })
      .catch((e) => live && setError(String(e.message || e)));
    return () => { live = false; };
  }, [indicator, start, groups]);
  const ind = inds.find((i) => i.indicator_id === indicator);
  const values = useMemo(() => Object.entries(d?.members ?? {}).map(([entity_id, g]) => ({ entity_id, value: g, status: "E" })), [d]);
  const scale: Scale | undefined = d ? { breaks: d.groups.slice(1).map((_, i) => i + 0.5), colors: d.groups.map((g) => GROUP_COLORS[g.group % GROUP_COLORS.length]) } : undefined;
  const option = useCallback(() => {
    const lines: CardLine[] = (d?.groups ?? []).filter((g) => shown === null || g.group === shown).map((g) => ({
      key: String(g.group), label: `Group ${g.group + 1} (${g.size})`, color: GROUP_COLORS[g.group % GROUP_COLORS.length],
      points: d!.years.flatMap((y, i) => g.line[i] === null ? [] : [[y, g.line[i] as number, "E"] as [number, number, string]]),
    }));
    return cardLinesOption(lines, { unit: "", decimals: 2, refY: { value: 0, label: "usual change" } });
  }, [d, shown]);
  const name = (e: string) => d?.names[e] ?? e;
  return (
    <section className="card">
      <div className="card-head">
        <h3>Countries that move alike{ind ? `: ${ind.name}` : ""}</h3>
        <span className="card-actions">
          {d && <AskButton title={`Countries that move alike: ${ind?.name ?? indicator}`} indicator={indicator} parts={() => [
            { key: "groups", kind: "data", label: `Groups whose yearly changes go together, ${d.start}-${d.end}`,
              text: d.groups.map((g) => `Group ${g.group + 1} (${g.size} countries, togetherness ${g.together}): ${g.countries.map(name).join(", ")}`).join("\n") },
            { key: "how", kind: "description", label: "How the groups are made",
              text: "Year-on-year changes of the indicator, each country's put on its own scale, compared country by country (correlation), then grouped with k-means on those correlations. Togetherness is the average correlation inside a group." },
          ]} />}
        </span>
      </div>
      <div className="controls small">
        <IndicatorSelect indicators={inds.filter((i) => i.enabled)} value={indicator} onChange={setIndicator} />
        <label>From <select value={start} onChange={(e) => setStart(+e.target.value)}>
          {[1960, 1970, 1980, 1990, 1995, 2000, 2005].map((y) => <option key={y} value={y}>{y}</option>)}</select></label>
        <label>Groups <select value={groups} onChange={(e) => setGroups(+e.target.value)}>
          {[3, 4, 5, 6, 8, 10].map((n) => <option key={n} value={n}>{n}</option>)}</select></label>
      </div>
      {error && <p className="error">{error}</p>}
      {!d && !error && <p className="muted">Grouping…</p>}
      {d?.note && <p className="muted">{d.note}</p>}
      {d && d.groups.length > 0 && (
        <>
          <div className="map-box">
            <WorldMap fill values={values} unit="" decimals={0} diverging={false} scale={scale} hideScale onPick={(iso3) => router.push(`/entity/${iso3}`)} />
          </div>
          <div className="chips-row small">
            <button className={`chip${shown === null ? " on" : ""}`} onClick={() => setShown(null)}>All groups</button>
            {d.groups.map((g) => (
              <button key={g.group} className={`chip${shown === g.group ? " on" : ""}`} onClick={() => setShown(shown === g.group ? null : g.group)}
                title={`Average correlation inside the group: ${g.together}`}>
                <i className="dot" style={{ background: GROUP_COLORS[g.group % GROUP_COLORS.length] }} /> Group {g.group + 1} ({g.size})</button>
            ))}
          </div>
          <EChart option={option} height={260} label="Each group's average yearly change, on a common scale" />
          <div className="small">
            {d.groups.filter((g) => shown === null || g.group === shown).map((g) => (
              <p key={g.group} style={{ margin: "4px 0" }}>
                <i className="dot" style={{ background: GROUP_COLORS[g.group % GROUP_COLORS.length] }} /> <b>Group {g.group + 1}</b>{" "}
                <span className="muted">together {g.together.toFixed(2)}</span>:{" "}
                {(shown === null ? g.countries.slice(0, 25) : g.countries).map(name).join(", ")}{shown === null && g.countries.length > 25 ? ` and ${g.countries.length - 25} more` : ""}
              </p>
            ))}
          </div>
          <p className="caption">
            Yearly changes {d.start}-{d.end}, each country&apos;s on its own scale, so a group shares the timing of its ups and downs,
            not their size. Togetherness is the average correlation inside a group (1 is in step every year). Countries with fewer than 12 years are left out.
          </p>
        </>
      )}
    </section>
  );
}
