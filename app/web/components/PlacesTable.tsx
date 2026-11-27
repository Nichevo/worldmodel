"use client";

// The map page's "Places in view" panel: every power plant (or port, airport, hospital... any map
// layer the Details pages count) in the area the map shows, or in the selected countries, as a
// table with its size, kind and the rest. Follows the map as it moves; a row's name moves the
// linked maps there. The Details page behind each layer has the whole world.

import Link from "next/link";
import { useEffect, useState } from "react";
import type { CameraBus } from "@/lib/camera";
import { csvText, fileName, saveText } from "@/lib/download";
import { fuelColour } from "@/lib/fuels";
import { layerApi, type LayerInfo, type LayerItem } from "@/lib/layerDetails";

// The layers it can list (stored dot layers), power plants first.
export const PLACE_TABLES: [id: string, label: string][] = [
  ["power_plants", "Power plants"], ["ports", "Ports (ship calls)"], ["ports_all", "Every port"], ["airports", "Airports"],
  ["hospitals", "Hospitals"], ["universities", "Universities"], ["military_bases", "Military bases"], ["lng_terminals", "LNG terminals"],
  ["heritage_sites", "Heritage sites"], ["volcanoes", "Volcanoes"], ["major_cities", "Big cities"],
];
export const PLACE_TABLE_IDS = PLACE_TABLES.map(([id]) => id);

type Got = { rows: LayerItem[]; total: number; categories?: { category: string | null; count: number; size: number }[] };
type Sort = "size" | "name";
const fmt = (v: number | null | undefined, d = 0) => (v === null || v === undefined ? "" : v.toLocaleString(undefined, { maximumFractionDigits: d }));
// a year (built 1983) without a thousands comma; other figures with one
const show = (v: unknown, key = "") => (v === null || v === undefined || v === "" ? <span className="muted">–</span>
  : typeof v === "number" ? (key === "year" || /year|built/i.test(key) ? String(v) : fmt(v, 1)) : String(v));

export function PlacesTable({ layer, setLayer, cameraBus, group, selection, names }: {
  layer: string; setLayer: (id: string) => void; cameraBus?: CameraBus; group: string; selection: string[]; names: Map<string, string>;
}) {
  const id = PLACE_TABLE_IDS.includes(layer) ? layer : "power_plants";
  const [info, setInfo] = useState<LayerInfo | null>(null);
  const [got, setGot] = useState<Got | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [where, setWhere] = useState<"view" | "selected" | "all">(() => {
    try { return (localStorage.getItem("wm-places-where") as "view" | "selected" | "all") || "view"; } catch { return "view"; }
  });
  const [box, setBox] = useState(cameraBus?.lastView ?? "");
  useEffect(() => cameraBus?.onView(setBox), [cameraBus]);
  const [kinds, setKinds] = useState<string[]>([]);
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<Sort>("size");
  const [limit, setLimit] = useState(300);
  const pick = (w: typeof where) => { setWhere(w); try { localStorage.setItem("wm-places-where", w); } catch { /* not kept */ } };
  const area = where === "view" ? box : "";
  const countries = where === "selected" && selection.length ? selection.join(",") : undefined;

  useEffect(() => {
    let live = true;
    setInfo(null);
    setKinds([]);
    layerApi.detail(id).then((d) => live && setInfo(d.layer)).catch(() => live && setInfo(null));
    return () => { live = false; };
  }, [id]);

  const ask = (n: number) => ({ box: area || undefined, country: countries, category: kinds.length ? kinds.join(",") : undefined,
    q: q.trim() || undefined, sort, limit: n });
  useEffect(() => {
    let live = true;
    const t = setTimeout(() => layerApi.items(id, ask(limit))
      .then((r) => { if (live) { setGot(r); setError(null); } })
      .catch((e) => live && setError(String(e?.message ?? e))), q ? 250 : 120);
    return () => { live = false; clearTimeout(t); };
  }, [id, area, countries, kinds.join(","), q, sort, limit]); // eslint-disable-line react-hooks/exhaustive-deps

  const S = info?.size ?? null;
  const fuels = id === "power_plants";
  const toggleKind = (k: string) => setKinds((cur) => (cur.includes(k) ? cur.filter((x) => x !== k) : [...cur, k]));
  const goTo = (r: LayerItem) => cameraBus?.publish(`places-${group}`, group, { center: [r.lon, r.lat], zoom: 13 });
  const csv = () => layerApi.items(id, ask(5000)).then((r) => saveText(csvText(
    ["Name", "Country", ...(S ? [`${S.label} (${S.unit})`] : []), ...(info?.category ? [info.category] : []), ...(info?.fields ?? []).map((f) => f.label),
      "Latitude", "Longitude"],
    r.rows.map((x) => [x.name, x.country_names.join("; "), ...(S ? [x.size] : []), ...(info?.category ? [x.category] : []),
      ...(info?.fields ?? []).map((f) => (x.fields[f.key] ?? null) as string | number | null), x.lat, x.lon])),
    `${fileName(id, where === "view" ? "in-view" : where === "selected" ? selection.join("-") : "all")}.csv`));
  const label = PLACE_TABLES.find(([x]) => x === id)?.[1] ?? id;
  const many = (info?.many ?? label).toLowerCase();
  const sizeSum = got?.categories?.reduce((a, c) => a + c.size, 0) ?? 0;

  return (
    <div className="places-panel" style={{ padding: "4px 8px", overflow: "auto", height: "100%" }}>
      <div className="chips-row small" style={{ marginBottom: 6, gap: 8, flexWrap: "wrap", display: "flex", alignItems: "center" }}>
        <select value={id} onChange={(e) => setLayer(e.target.value)} aria-label="Which places">
          {PLACE_TABLES.map(([x, l]) => <option key={x} value={x}>{l}</option>)}
        </select>
        <div className="seg" role="group" aria-label="Where">
          {cameraBus && <button className={where === "view" ? "on" : ""} aria-pressed={where === "view"} onClick={() => pick("view")}
            title="Only those inside the area the map shows (the map you moved last); the table follows the map as you pan and zoom">In the map view</button>}
          <button className={where === "selected" ? "on" : ""} aria-pressed={where === "selected"} onClick={() => pick("selected")}
            disabled={!selection.length} title={selection.length ? `Only those in ${selection.map((s) => names.get(s) ?? s).join(", ")}` : "Select countries (or a group) on the map first"}>
            In the selected countries</button>
          <button className={where === "all" ? "on" : ""} aria-pressed={where === "all"} onClick={() => pick("all")}>Whole world</button>
        </div>
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find by name or kind" aria-label="Find by name or kind" style={{ width: 150 }} />
        {S && <div className="seg">{(["size", "name"] as const).map((s) => <button key={s} className={sort === s ? "on" : ""} aria-pressed={sort === s}
          onClick={() => setSort(s)}>{s === "size" ? `Biggest first` : "By name"}</button>)}</div>}
        <button className="link small" onClick={csv}>Download CSV</button>
        <Link className="small" href={`/layers/${id}`}>Details page</Link>
      </div>

      {got?.categories && got.categories.length > 1 && (
        <div className="small" style={{ display: "flex", flexWrap: "wrap", gap: "4px 6px", marginBottom: 6 }} aria-label={`${info?.category ?? "Kind"} in this area`}>
          {got.categories.map((c) => {
            const k = c.category ?? "";
            const on = kinds.includes(k);
            return (
              <button key={k} className={`chip${on ? " on" : ""}`} aria-pressed={on} onClick={() => toggleKind(k)}
                title={`Show only ${k || "those with no kind given"} (click more to add them; click again to take off)`}
                style={{ display: "inline-flex", alignItems: "center", gap: 4, opacity: kinds.length && !on ? 0.55 : 1 }}>
                {fuels && <i style={{ width: 10, height: 10, borderRadius: 2, background: fuelColour(c.category), display: "inline-block" }} />}
                {c.category ?? "Not given"} <span className="muted">{fmt(c.count)}{S && c.size ? ` · ${fmt(c.size)} ${S.unit}` : ""}
                  {S && sizeSum && c.size ? ` (${Math.round((100 * c.size) / sizeSum)}%)` : ""}</span>
              </button>
            );
          })}
          {kinds.length > 0 && <button className="link small" onClick={() => setKinds([])}>All kinds</button>}
        </div>
      )}

      {error ? <p className="small" role="alert">Could not read the list: {error}</p>
        : !got ? <p className="muted small">Loading…</p>
        : !got.rows.length ? <p className="muted small">{where === "view" ? `No ${many} in the map view. Move or zoom the map out.` : `No ${many} here.`}
          {" "}(If none show anywhere, a refresh has not loaded the layer yet.)</p>
        : (
          <>
            <p className="small" style={{ margin: "2px 0 6px" }}><b>{fmt(got.total)}</b> {got.total === 1 ? (info?.one ?? many) : many}{where === "view" ? " in the map view" : where === "selected" ? " in the selected countries" : ""}
              {S && sizeSum ? <>, <b>{fmt(sizeSum)}</b> {S.unit} together{kinds.length ? " (all kinds)" : ""}</> : null}</p>
            <table className="small">
              <thead><tr>
                <th>Name</th><th>Country</th>
                {S && <th style={{ textAlign: "right" }}>{S.label}{S.unit && S.unit !== S.label.toLowerCase() ? ` (${S.unit})` : ""}</th>}
                {info?.category && <th>{info.category}</th>}
                {(info?.fields ?? []).map((f) => <th key={f.key}>{f.label}</th>)}
                <th></th>
              </tr></thead>
              <tbody>{got.rows.map((r) => (
                <tr key={r.item_id}>
                  <td>{cameraBus ? <button className="link" onClick={() => goTo(r)} title="Move the linked maps there">{r.name}</button> : r.name}</td>
                  <td style={{ whiteSpace: "nowrap" }}>{r.country_names.join(", ")}</td>
                  {S && <td style={{ textAlign: "right" }}>{r.size === null ? <span className="muted">–</span> : fmt(r.size, S.decimals)}</td>}
                  {info?.category && <td style={{ whiteSpace: "nowrap" }}>
                    {fuels && <i style={{ width: 9, height: 9, borderRadius: 2, background: fuelColour(r.category), display: "inline-block", marginRight: 5 }} />}
                    {r.category ?? <span className="muted">–</span>}</td>}
                  {(info?.fields ?? []).map((f) => <td key={f.key}>{show(r.fields[f.key], f.key)}</td>)}
                  <td style={{ whiteSpace: "nowrap" }}><a className="small" href={`https://www.openstreetmap.org/?mlat=${r.lat}&mlon=${r.lon}#map=15/${r.lat}/${r.lon}`}
                    target="_blank" rel="noreferrer" title="Where it is (OpenStreetMap)">Where</a></td>
                </tr>
              ))}</tbody>
            </table>
            {got.total > got.rows.length && <button className="link small" onClick={() => setLimit(limit + 500)}>Show more ({fmt(got.total - got.rows.length)} left)</button>}
            <p className="caption">&quot;–&quot; means the source gives no figure.{info?.note ? ` ${info.note}` : ""}
              {cameraBus ? " Click a name to move the linked maps there (Links > Map position)." : ""}</p>
          </>
        )}
    </div>
  );
}
