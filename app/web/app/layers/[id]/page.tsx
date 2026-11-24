"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import AskButton from "@/components/AskButton";
import Flag from "@/components/Flag";
import { csvText, fileName, saveText } from "@/lib/download";
import {
  fmt, layerApi, rate, showOnMapHref, type LayerDetail, type LayerInfo, type LayerItem, type LayerRow,
} from "@/lib/layerDetails";
import { KEY_COUNTRIES } from "@/lib/topics";

// The Details page behind a map layer: how many each country (or bloc) has, per million people
// and per 10,000 km², the size total where the source gives one and how that compares with an
// official figure, the spread of sizes, and every item. A click on a country lists its items.
type Tab = "countries" | "groups" | "items" | "sizes";
const TABS: [Tab, string][] = [["countries", "By country"], ["groups", "By group"], ["items", "Every item"], ["sizes", "Sizes"]];
const GROUP_TYPES: [string, string][] = [["bloc", "Blocs"], ["alliance", "Alliances"], ["continent", "Continents"], ["subregion", "Regions"],
  ["income_group", "Income groups"], ["group", "Other groups"]];
const KEYS = KEY_COUNTRIES.map((k) => k.id);
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

function LayerPage() {
  const { id } = useParams<{ id: string }>();
  const params = useSearchParams();
  const router = useRouter();
  const tab = (TABS.find(([t]) => t === params.get("tab"))?.[0] ?? "countries") as Tab;
  const country = params.get("country") ?? "";
  const [d, setD] = useState<LayerDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    setD(null); setErr(null);
    layerApi.detail(id).then((x) => live && setD(x)).catch((e) => live && setErr(String(e.message || e)));
    return () => { live = false; };
  }, [id]);
  const go = (t: Tab, c = "") => router.replace(`/layers/${id}?tab=${t}${c ? `&country=${encodeURIComponent(c)}` : ""}`, { scroll: false });
  const mapHref = showOnMapHref(id);
  if (err) return <div className="grid"><p><Link href="/layers">All map layers</Link></p><p className="error">{err}</p></div>;
  if (!d) return <p className="muted">Counting…</p>;
  const L = d.layer;
  const title = cap(L.many);
  const t = d.totals;
  const hasSizes = d.sizes.length > 0 || d.categories.length > 0;
  return (
    <div className="grid">
      <p className="small"><Link href="/layers">All map layers</Link></p>
      <div className="title-row">
        <h1>{title}</h1>
        <span className="row small" style={{ gap: 12 }}>
          {mapHref && <Link href={mapHref}>Show on the map</Link>}
          <AskButton title={`${title} by country`} parts={() => [
            { key: "about", kind: "description", label: "What this layer is", text: `${L.description ?? title}. ${L.note}` },
            { key: "data", kind: "data", label: `${title} by country`, text: [
              `Country,Count,Per million people${L.size ? `,${L.size.label} (${L.size.unit})` : ""}`,
              ...d.countries.slice(0, 60).map((r) => `${r.name},${r.count},${r.per_m ?? ""}${L.size ? `,${r.size_total ?? ""}` : ""}`)].join("\n") }]} />
        </span>
      </div>
      <p className="ink-2" style={{ margin: 0, maxWidth: 900 }}>
        {L.source && <>From <b>{L.source}</b>{L.vintage ? ` (${L.vintage})` : ""}. </>}
        {L.note || L.description}
        {!L.size && L.kind === "stored" && " This layer has no size figure, so the page shows counts and kinds only."}
      </p>
      <div className="tiles">
        <div className="tile card"><div className="label">{cap(L.many)}</div><div className="value">{fmt(t.count)}</div>
          <div className="meta">{L.by_country && t.countries ? `in ${t.countries} ${L.group_label === "Council" ? "councils" : "countries"}` : ""}</div></div>
        {L.size && <div className="tile card"><div className="label">With a {L.size.label.toLowerCase()} figure</div>
          <div className="value">{t.count ? `${Math.round(((t.with_size ?? 0) / t.count) * 100)}%` : "–"}</div>
          <div className="meta">{fmt(t.with_size)} of {fmt(t.count)}</div></div>}
        {L.size && t.size_total !== null && t.size_total !== undefined && <div className="tile card">
          <div className="label">{L.size.total === "sum" ? `${L.size.label}, all listed` : L.size.total === "max" ? `Largest ${L.size.label.toLowerCase()}` : `Average ${L.size.label.toLowerCase()}`}</div>
          <div className="value">{fmt(t.size_total, L.size.decimals)}</div><div className="meta">{L.size.unit}</div></div>}
        {t.largest && <div className="tile card"><div className="label">Biggest</div><div className="value" style={{ fontSize: "1rem" }}>{t.largest.name}</div>
          <div className="meta">{fmt(t.largest.size, L.size?.decimals)} {L.size?.unit}{t.largest.entity_id ? ` · ${t.largest.entity_id}` : ""}</div></div>}
        {!!t.placed && <div className="tile card"><div className="label">Country worked out from the map</div><div className="value">{fmt(t.placed)}</div>
          <div className="meta">the source names no country for these</div></div>}
      </div>
      {!t.count ? (
        <p className="card">Nothing to count yet. {L.kind === "live" ? "This layer is read live; it may be switched off in Settings or have nothing happening now."
          : <>Run <code>.\refresh.bat</code>, which loads the map layers and lists their items.</>}</p>
      ) : (
        <>
          <div className="seg" role="tablist">
            {TABS.filter(([k]) => (k !== "groups" || (L.by_country && L.kind !== "trees")) && (k !== "countries" || L.by_country) && (k !== "sizes" || hasSizes))
              .map(([k, label]) => <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => go(k)}>
                {k === "countries" && L.group_label === "Council" ? "By council" : label}</button>)}
          </div>
          {country ? <Items layer={L} country={country} name={[...d.countries, ...d.groups].find((r) => r.key === country)?.name ?? country}
            onBack={() => go(tab)} />
            : tab === "items" || !L.by_country ? <Items layer={L} />
              : tab === "sizes" ? <Sizes d={d} />
                : <ByTable layer={L} rows={tab === "groups" ? d.groups : d.countries} groups={tab === "groups"} onPick={(k) => go(tab, k || "-")} />}
        </>
      )}
      {L.indicators.count && (
        <p className="caption">These counts are also figures you can show on the main page, colour the map with, compare and rank: look for
          &quot;{title} on the map&quot; in an indicator drop-down. They count only what the map layer lists.</p>
      )}
    </div>
  );
}

type SortKey = "name" | "count" | "per_m" | "per_10k_km2" | "with_size" | "size_total" | "size_per_1000" | "official0" | "coverage0";

function ByTable({ layer, rows, groups, onPick }: { layer: LayerInfo; rows: LayerRow[]; groups: boolean; onPick: (key: string) => void }) {
  const [sort, setSort] = useState<SortKey>("count");
  const [down, setDown] = useState(true);
  const [filter, setFilter] = useState("");
  const [types, setTypes] = useState<string>("bloc");
  const [keyFirst, setKeyFirst] = useState(true);
  const [all, setAll] = useState(false);
  const S = layer.size;
  const sums = S?.total === "sum";
  const val = (r: LayerRow, k: SortKey): number | string | null => k === "name" ? r.name : k === "official0" ? r.official[0]?.value ?? null
    : k === "coverage0" ? r.official[0]?.coverage ?? null : (r[k] as number | null);
  const shown = useMemo(() => {
    let out = rows.filter((r) => !groups || r.type === types);
    if (filter) out = out.filter((r) => r.name.toLowerCase().includes(filter.toLowerCase()));
    out = [...out].sort((a, b) => {
      const x = val(a, sort), y = val(b, sort);
      if (x === null && y === null) return 0;
      if (x === null) return 1;
      if (y === null) return -1;
      const c = typeof x === "string" ? x.localeCompare(String(y)) : x - (y as number);
      return down ? -c : c;
    });
    if (keyFirst && !groups) {
      const keys = out.filter((r) => r.entity_id && KEYS.includes(r.entity_id));
      out = [...keys, ...out.filter((r) => !keys.includes(r))];
    }
    return out;
  }, [rows, groups, types, filter, sort, down, keyFirst]); // eslint-disable-line react-hooks/exhaustive-deps
  const max = Math.max(1, ...shown.map((r) => r.count));
  const head = (k: SortKey, label: string, title?: string) => (
    <th style={{ textAlign: k === "name" ? "left" : "right", cursor: "pointer", whiteSpace: "nowrap" }} title={title}
      aria-sort={sort === k ? (down ? "descending" : "ascending") : undefined}
      onClick={() => { if (sort === k) setDown(!down); else { setSort(k); setDown(k !== "name"); } }}>
      {label}{sort === k ? (down ? " ▼" : " ▲") : ""}</th>
  );
  const csv = () => {
    const h = [layer.group_label, "Count", "Per million people", "Per 10,000 km2", ...(S ? [`With ${S.label.toLowerCase()}`, `${S.label} (${S.unit})`] : []),
      ...(sums ? [`${S!.label} per 1,000 people`] : []), ...layer.official.flatMap((o) => [o.label, ...(o.coverage ? ["Coverage"] : [])]), "Largest"];
    saveText(csvText(h, shown.map((r) => [r.name, r.count, r.per_m, r.per_10k_km2, ...(S ? [r.with_size, r.size_total] : []),
      ...(sums ? [r.size_per_1000] : []), ...layer.official.flatMap((o, i) => [r.official[i]?.value ?? null, ...(o.coverage ? [r.official[i]?.coverage ?? null] : [])]),
      r.largest?.name ?? ""])), `${fileName(layer.id, groups ? "by-group" : "by-country")}.csv`);
  };
  const isCouncil = layer.group_label === "Council";
  return (
    <div className="card">
      <div className="chips-row small">
        {groups && <label>Groups <select value={types} onChange={(e) => setTypes(e.target.value)}>
          {GROUP_TYPES.filter(([t]) => rows.some((r) => r.type === t)).map(([t, l]) => <option key={t} value={t}>{l}</option>)}</select></label>}
        <input type="search" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder={groups ? "Filter groups" : `Filter ${isCouncil ? "councils" : "countries"}`}
          aria-label="Filter the list" />
        {!groups && !isCouncil && <label><input type="checkbox" checked={keyFirst} onChange={(e) => setKeyFirst(e.target.checked)} /> NZ, Australia, UK, US first</label>}
        <button className="link small" onClick={csv}>Download CSV</button>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table className="small">
          <thead><tr>
            {head("name", groups ? "Group" : layer.group_label)}
            {head("count", cap(layer.many.split(" (")[0]))}
            {!isCouncil && head("per_m", "Per million people")}
            {!isCouncil && head("per_10k_km2", "Per 10,000 km²", "Per 10,000 square kilometres of land")}
            {S && head("with_size", `With ${S.label.toLowerCase()}`)}
            {S && head("size_total", S.total === "sum" ? `${S.label} listed` : S.total === "max" ? `Largest ${S.label.toLowerCase()}` : `Average ${S.label.toLowerCase()}`, S.unit)}
            {sums && !isCouncil && head("size_per_1000", `${S!.label} per 1,000 people`)}
            {layer.official.map((o, i) => [
              <th key={`o${i}`} style={{ textAlign: "right", cursor: "pointer" }} onClick={() => { setSort(i === 0 ? "official0" : sort); setDown(true); }} title={o.label}>{o.label}</th>,
              o.coverage ? <th key={`c${i}`} style={{ textAlign: "right", cursor: "pointer" }} onClick={() => { setSort("coverage0"); setDown(true); }}
                title={`How much of the official figure the map layer lists`}>Coverage{sort === "coverage0" ? (down ? " ▼" : " ▲") : ""}</th> : null,
            ])}
            <th style={{ textAlign: "left" }}>Largest</th>
          </tr></thead>
          <tbody>
            {(all ? shown : shown.slice(0, 60)).map((r) => (
              <tr key={r.key || "-"} className={r.entity_id && KEYS.includes(r.entity_id) && keyFirst && !groups ? "key" : ""}>
                <td style={{ whiteSpace: "nowrap" }}>
                  <button className="link" onClick={() => onPick(r.key)} title={`List the ${layer.many} here`}>
                    {r.entity_id && /^[A-Z]{3}$/.test(r.entity_id) && !isCouncil ? <Flag id={r.entity_id} /> : null}{r.name}</button>
                </td>
                <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                  <span className="bar-in" style={{ display: "inline-block", width: Math.max(2, (60 * r.count) / max), height: 8, marginRight: 6,
                    background: "var(--series-1)", opacity: 0.55, borderRadius: 2, verticalAlign: "middle" }} />{fmt(r.count)}</td>
                {!isCouncil && <td style={{ textAlign: "right" }}>{rate(r.per_m)}</td>}
                {!isCouncil && <td style={{ textAlign: "right" }}>{rate(r.per_10k_km2)}</td>}
                {S && <td style={{ textAlign: "right" }}>{fmt(r.with_size)}</td>}
                {S && <td style={{ textAlign: "right" }}>{fmt(r.size_total, S.decimals)}</td>}
                {sums && !isCouncil && <td style={{ textAlign: "right" }}>{rate(r.size_per_1000)}</td>}
                {layer.official.map((o, i) => [
                  <td key={`o${i}`} style={{ textAlign: "right" }}>{fmt(r.official[i]?.value)}</td>,
                  o.coverage ? <td key={`c${i}`} style={{ textAlign: "right", fontWeight: 600, color: coverColour(r.official[i]?.coverage) }}>
                    {r.official[i]?.coverage === null || r.official[i]?.coverage === undefined ? "–" : `${Math.round(r.official[i]!.coverage! * 100)}%`}</td> : null,
                ])}
                <td className="muted" style={{ whiteSpace: "nowrap", maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis" }}>
                  {r.largest ? `${r.largest.name} (${fmt(r.largest.size, S?.decimals)})` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {shown.length > 60 && <button className="link small" onClick={() => setAll(!all)}>{all ? "Show the first 60" : `Show all ${shown.length}`}</button>}
      <p className="caption">
        Click a column to sort, a name to list its {layer.many}. {layer.official.some((o) => o.coverage) && <>Coverage is what the layer lists as a share
          of the official figure: low coverage means the map&apos;s source is thin there, not that the country has few. </>}
        {layer.official.some((o) => !o.coverage) && <>{layer.official.filter((o) => !o.coverage).map((o) => o.label).join(", ")} counts more than this layer
          does, so it is shown beside it for scale only. </>}
        {layer.country_from === "place" && "The country is worked out from where each item sits. "}
        Per million people uses the UN&apos;s population for this year; per area, the World Bank&apos;s land area.
      </p>
    </div>
  );
}

const coverColour = (c: number | null | undefined) =>
  c === null || c === undefined ? undefined : c >= 0.75 ? "var(--good, #2f9e44)" : c >= 0.4 ? "var(--warn, #e8a200)" : "var(--bad, #c92a2a)";

function Items({ layer, country, name, onBack }: { layer: LayerInfo; country?: string; name?: string; onBack?: () => void }) {
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<"size" | "name">(layer.size ? "size" : "name");
  const [rows, setRows] = useState<LayerItem[] | null>(null);
  const [total, setTotal] = useState(0);
  const [limit, setLimit] = useState(200);
  useEffect(() => {
    let live = true;
    const t = setTimeout(() => layerApi.items(layer.id, { country, q: q.trim() || undefined, sort, limit })
      .then((r) => { if (live) { setRows(r.rows); setTotal(r.total); } }).catch(() => live && setRows([])), q ? 250 : 0);
    return () => { live = false; clearTimeout(t); };
  }, [layer.id, country, q, sort, limit]);
  const S = layer.size;
  const csv = () => layerApi.items(layer.id, { country, q: q.trim() || undefined, sort, limit: 5000 }).then((r) => saveText(csvText(
    ["Name", "Country", ...(S ? [`${S.label} (${S.unit})`] : []), ...(layer.category ? [layer.category] : []), ...layer.fields.map((f) => f.label),
      "Latitude", "Longitude", "Link"],
    r.rows.map((x) => [x.name, x.group ?? x.country_names.join("; "), ...(S ? [x.size] : []), ...(layer.category ? [x.category] : []),
      ...layer.fields.map((f) => (x.fields[f.key] ?? null) as string | number | null), x.lat, x.lon, x.url])), `${fileName(layer.id, country || "all")}.csv`));
  return (
    <div className="card">
      <div className="card-head">
        <h3>{country ? `${cap(layer.many)} in ${country === "-" ? "no country (at sea or not placed)" : name}` : `Every ${layer.one}`}
          {rows && <span className="muted small"> · {fmt(total)}</span>}</h3>
        {onBack && <button className="link small" onClick={onBack}>Back to the table</button>}
      </div>
      <div className="chips-row small">
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Find a ${layer.one}`} aria-label={`Find a ${layer.one}`} />
        {S && <div className="seg">{(["size", "name"] as const).map((s) => <button key={s} className={sort === s ? "on" : ""} aria-pressed={sort === s}
          onClick={() => setSort(s)}>{s === "size" ? `Biggest ${S.label.toLowerCase()} first` : "By name"}</button>)}</div>}
        <button className="link small" onClick={csv}>Download CSV</button>
      </div>
      {!rows ? <p className="muted small">Loading…</p> : !rows.length ? <p className="muted small">None.</p> : (
        <div style={{ overflowX: "auto" }}>
          <table className="small">
            <thead><tr>
              <th>Name</th>{!country || country.length > 3 ? <th>{layer.group_label}</th> : null}
              {S && <th style={{ textAlign: "right" }}>{S.label}{S.unit && S.unit !== S.label.toLowerCase() ? ` (${S.unit})` : ""}</th>}
              {layer.category && <th>{layer.category}</th>}
              {layer.fields.map((f) => <th key={f.key}>{f.label}</th>)}
              <th></th>
            </tr></thead>
            <tbody>{rows.map((r) => (
              <tr key={r.item_id}>
                <td>{r.url ? <a href={r.url} target="_blank" rel="noreferrer">{r.name}</a> : r.name}</td>
                {!country || country.length > 3 ? <td style={{ whiteSpace: "nowrap" }}>{r.group ?? r.country_names.join(", ")}
                  {r.placed ? <span className="muted" title="Worked out from where it sits"> *</span> : null}</td> : null}
                {S && <td style={{ textAlign: "right" }}>{r.size === null ? <span className="muted">–</span> : fmt(r.size, S.decimals)}</td>}
                {layer.category && <td>{r.category ?? <span className="muted">–</span>}</td>}
                {layer.fields.map((f) => <td key={f.key}>{show(r.fields[f.key])}</td>)}
                <td style={{ whiteSpace: "nowrap" }}><a className="small" href={`https://www.openstreetmap.org/?mlat=${r.lat}&mlon=${r.lon}#map=12/${r.lat}/${r.lon}`}
                  target="_blank" rel="noreferrer" title="Where it is (OpenStreetMap)">Where</a></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
      {rows && total > rows.length && <button className="link small" onClick={() => setLimit(limit + 500)}>Show more ({fmt(total - rows.length)} left)</button>}
      <p className="caption">&quot;–&quot; means the source gives no figure. {rows?.some((r) => r.placed) && "* country worked out from where it sits. "}
        {layer.kind === "lines" && "A line counts for every country it touches; its full length is shown."}</p>
    </div>
  );
}

const show = (v: unknown) => {
  if (v === null || v === undefined || v === "") return <span className="muted">–</span>;
  if (typeof v === "number") return Math.abs(v) < 1 && v !== 0 ? `${+(v * 100).toFixed(1)}%` : fmt(v, 1);
  if (v === true || v === 1) return "Yes";
  return String(v);
};

function Sizes({ d }: { d: LayerDetail }) {
  const L = d.layer;
  const max = Math.max(1, ...d.sizes.map((s) => s.count), ...d.categories.map((c) => c.count));
  return (
    <div className="grid two">
      {d.sizes.length > 0 && <div className="card">
        <h3>By {L.size!.label.toLowerCase()} ({L.size!.unit})</h3>
        <table className="small"><tbody>{d.sizes.map((s) => (
          <tr key={s.label}><td style={{ whiteSpace: "nowrap" }}>{s.label}</td>
            <td style={{ width: "60%" }}><span style={{ display: "block", height: 12, width: `${(100 * s.count) / max}%`, background: "var(--series-2)",
              opacity: s.missing ? 0.3 : 0.8, borderRadius: 2 }} /></td>
            <td style={{ textAlign: "right" }}>{fmt(s.count)}</td></tr>
        ))}</tbody></table>
      </div>}
      {d.categories.length > 0 && <div className="card">
        <h3>By {L.category!.toLowerCase()}</h3>
        <table className="small"><thead><tr><th>{L.category}</th><th style={{ textAlign: "right" }}>{cap(L.many.split(" (")[0])}</th>
          {L.size?.total === "sum" && <th style={{ textAlign: "right" }}>{L.size.label} ({L.size.unit})</th>}</tr></thead>
          <tbody>{d.categories.map((c) => (
            <tr key={c.label}><td>{c.label}</td>
              <td style={{ textAlign: "right" }}><span style={{ display: "inline-block", height: 8, width: Math.max(2, (60 * c.count) / max), marginRight: 6,
                background: "var(--series-3)", opacity: 0.7, borderRadius: 2, verticalAlign: "middle" }} />{fmt(c.count)}</td>
              {L.size?.total === "sum" && <td style={{ textAlign: "right" }}>{fmt(c.size_total, L.size.decimals)}</td>}</tr>
          ))}</tbody></table>
      </div>}
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<p className="muted">Loading…</p>}><LayerPage /></Suspense>;
}

