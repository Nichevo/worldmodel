"use client";

import Link from "next/link";
import { useState } from "react";
import { validateStyleMin } from "@maplibre/maplibre-gl-style-spec";
import { get } from "@/lib/api";
import { LAYER_STYLE, layerSpec } from "@/lib/layers";
import { PLACE_LOOK, placeSpecs } from "@/lib/placeIcons";
import { landUseSpecs, LANDUSE_LAYER, portSpec, SITE_KINDS, siteSpecs } from "@/lib/siteOutlines";
import { MAP_LAYERS } from "@/lib/workspace";

// Self check: what a review does by hand, in one click, on this PC's own data. It checks every
// map layer's style against MapLibre's rules, asks every API call that needs no inputs, opens
// every page, and reads the background collectors and failing sources. Nothing is changed.

type Status = "ok" | "slow" | "fail" | "note";
type Row = { part: string; what: string; status: Status; detail: string };

// Every page without an id in its address (the smoke test in scripts/smoke.mjs opens the same).
const PAGES = ["/", "/ai", "/alike", "/api-access", "/briefing", "/cities", "/climate", "/compare", "/console", "/crises",
  "/crisiswatch", "/crowd", "/data", "/discover", "/disease", "/episodes", "/events", "/forecasts", "/find", "/glossary", "/highlights",
  "/history", "/indicators", "/land", "/languages", "/laws", "/layers", "/learn", "/live", "/long", "/military", "/outlook",
  "/pollution", "/predictions", "/prices", "/regions", "/relationships", "/religion", "/sanctions", "/sectors", "/settings",
  "/shapes", "/sources", "/space", "/spotting", "/storage", "/stories", "/todo", "/topics", "/tourism", "/transport", "/wars",
  "/zones", "/entity/NZL"];
// API calls left out: downloads, streams, tiles and anything that starts work.
// Left out: streams and downloads, and calls that wait on an outside site (land cover changes
// ask the Planetary Computer, which can take over 30 s and says nothing about this app).
const SKIP_API = /stream|events$|export|download|tiles|backup|cover-change|\.md$|\.csv$/;
const SLOW_MS = 5000;

/** Every overlay's MapLibre layer, checked against the style rules (an invalid one would not draw). */
function checkLayerStyles(): Row[] {
  const rows: Row[] = [];
  for (const m of MAP_LAYERS) {
    if (m.made || LAYER_STYLE[m.id] || m.id === LANDUSE_LAYER) continue;
    rows.push({ part: "Map layers", what: m.label, status: "fail", detail: `no style for layer "${m.id}": it can be turned on but draws nothing` });
  }
  for (const id of Object.keys(LAYER_STYLE)) {
    const lid = `ov-${id}`;
    let errors: string[];
    try {
      errors = validateStyleMin({
        version: 8, glyphs: "/fonts/{fontstack}/{range}.pbf",
        sources: { [lid]: { type: "geojson", data: { type: "FeatureCollection", features: [] } } },
        // place layers: also with symbols and real size on (the dots' paint changes and a symbol layer goes on top)
        layers: [layerSpec(id, lid), ...(PLACE_LOOK[id] ? placeSpecs(id, lid, layerSpec(id, lid)) : [])],
      }).map((e) => e.message);
    } catch (e) {
      errors = [`style could not be made: ${String((e as Error)?.message ?? e)}`];
    }
    if (errors.length) rows.push({ part: "Map layers", what: LAYER_STYLE[id].legend, status: "fail", detail: errors.slice(0, 3).join("; ") });
  }
  // Site outlines from the map detail (a vector source) and the ports' worked-out land.
  try {
    const errors = validateStyleMin({
      version: 8, glyphs: "/fonts/{fontstack}/{range}.pbf",
      sources: { "detail-x": { type: "vector", tiles: ["http://localhost/{z}/{x}/{y}.pbf"] },
        "bm-site-ports": { type: "geojson", data: { type: "FeatureCollection", features: [] } } },
      layers: [...Object.keys(SITE_KINDS).flatMap((id) => siteSpecs(id, "detail-x", "#888888")), portSpec("#888888"), ...landUseSpecs("detail-x", [])],
    }).map((e) => e.message);
    if (errors.length) rows.push({ part: "Map layers", what: "Site outlines from the map", status: "fail", detail: errors.slice(0, 3).join("; ") });
  } catch (e) {
    rows.push({ part: "Map layers", what: "Site outlines from the map", status: "fail", detail: String((e as Error)?.message ?? e) });
  }
  const n = Object.keys(LAYER_STYLE).length;
  if (!rows.length) rows.push({ part: "Map layers", what: `${n} layer styles`, status: "ok", detail: "all valid" });
  return rows;
}

async function timed(url: string, ms = 30_000): Promise<{ status: number; ms: number; text: string }> {
  const ctl = new AbortController();
  const t0 = performance.now();
  const timer = setTimeout(() => ctl.abort(), ms);
  try {
    const r = await fetch(url, { signal: ctl.signal });
    const text = await r.text();
    return { status: r.status, ms: performance.now() - t0, text };
  } catch (e) {
    return { status: 0, ms: performance.now() - t0, text: (e as Error).name === "AbortError" ? `no answer in ${ms / 1000} s` : String(e) };
  } finally {
    clearTimeout(timer);
  }
}

async function inBatches<T>(items: T[], size: number, fn: (x: T) => Promise<void>) {
  for (let i = 0; i < items.length; i += size) await Promise.all(items.slice(i, i + size).map(fn));
}

async function checkApi(progress: (s: string) => void): Promise<Row[]> {
  type Spec = { paths: Record<string, { get?: { parameters?: { required?: boolean; in: string }[] } }> };
  const spec = await fetch("/api/openapi.json").then((r) => r.json() as Promise<Spec>);
  const urls = Object.entries(spec.paths)
    .filter(([p, v]) => p.startsWith("/api/v1/") && v.get && !p.includes("{") && !SKIP_API.test(p)
      && !(v.get.parameters ?? []).some((x) => x.required))
    .map(([p]) => p);
  const rows: Row[] = [];
  let done = 0;
  await inBatches(urls, 6, async (u) => {
    const r = await timed(u);
    done += 1;
    progress(`API ${done} of ${urls.length}`);
    // 400, 403 and 404 are the app's own answers (switched off, needs an input, nothing there yet);
    // 503 is an outside service or file not there (said in the detail); the rest is breakage.
    if (r.status === 503) {
      rows.push({ part: "API", what: u, status: "note", detail: `not available: ${r.text.slice(0, 200)}` });
    } else if (r.status === 0 || r.status >= 500) {
      rows.push({ part: "API", what: u, status: "fail", detail: `${r.status ? `HTTP ${r.status}: ` : ""}${r.text.slice(0, 200)}` });
    } else if (r.ms > SLOW_MS) {
      rows.push({ part: "API", what: u, status: "slow", detail: `${(r.ms / 1000).toFixed(1)} s, ${(r.text.length / 1e6).toFixed(1)} MB` });
    }
  });
  rows.sort((a, b) => a.what.localeCompare(b.what));
  return [{ part: "API", what: `${urls.length} calls`, status: rows.some((r) => r.status === "fail") ? "fail" : "ok",
    detail: `${rows.filter((r) => r.status === "fail").length} failed, ${rows.filter((r) => r.status === "slow").length} slow (over ${SLOW_MS / 1000} s)` }, ...rows];
}

async function checkPages(progress: (s: string) => void): Promise<Row[]> {
  const rows: Row[] = [];
  let done = 0;
  await inBatches(PAGES, 4, async (p) => {
    const r = await timed(p, 60_000);
    done += 1;
    progress(`Pages ${done} of ${PAGES.length}`);
    if (r.status !== 200) rows.push({ part: "Pages", what: p, status: "fail", detail: r.status ? `HTTP ${r.status}` : r.text });
    else if (r.ms > 2 * SLOW_MS) rows.push({ part: "Pages", what: p, status: "slow", detail: `${(r.ms / 1000).toFixed(1)} s` });
  });
  return [{ part: "Pages", what: `${PAGES.length} pages`, status: rows.some((r) => r.status === "fail") ? "fail" : "ok",
    detail: `${rows.filter((r) => r.status === "fail").length} failed` }, ...rows];
}

async function checkCollectors(): Promise<Row[]> {
  const rows: Row[] = [];
  const hour = Date.now() / 1000 - 3600;
  try {
    const p = await get<{ collecting: boolean; last: number | null; planes?: number; world_note?: string | null; route_note?: string | null }>("/live/planes/status");
    const age = p.last ? (Date.now() / 1000 - p.last) / 60 : null;
    rows.push({ part: "Collectors", what: "Planes", status: !p.collecting ? "note" : age !== null && age < 60 ? "ok" : "fail",
      detail: !p.collecting ? "not collecting (Settings > Transport)" : `${(p.planes ?? 0).toLocaleString()} planes saved; last ${age === null ? "never" : `${Math.round(age)} min ago`}${p.world_note ? `. ${p.world_note}` : ""}` });
  } catch (e) {
    rows.push({ part: "Collectors", what: "Planes", status: "fail", detail: String((e as Error).message ?? e) });
  }
  try {
    const s = await get<{ collecting: boolean; connected: boolean; error: string | null; ships?: number }>("/live/ships/status");
    const sw = await get<{ rows: { start: number; what: string; why: string | null }[] }>("/live/ships/sweeps", { days: 1 });
    const drops = sw.rows.filter((r) => r.what === "connection" && r.start >= hour);
    rows.push({ part: "Collectors", what: "Ships", status: !s.collecting ? "note" : s.error || drops.length > 6 ? "fail" : drops.length > 2 ? "slow" : "ok",
      detail: !s.collecting ? "not collecting (Settings > Transport)"
        : `${(s.ships ?? 0).toLocaleString()} ships saved; ${s.connected ? "connected" : "not connected"}; ${drops.length} dropped connection${drops.length === 1 ? "" : "s"} in the last hour`
          + (s.error ? `. ${s.error}` : drops[0]?.why ? ` (latest: ${drops[0].why})` : "") });
  } catch (e) {
    rows.push({ part: "Collectors", what: "Ships", status: "fail", detail: String((e as Error).message ?? e) });
  }
  try {
    const w = await get<{ on: boolean; run: string | null; error: string; note: string }>("/weather/status");
    rows.push({ part: "Collectors", what: "Weather forecast", status: !w.on ? "note" : w.error ? "fail" : w.run ? "ok" : "slow",
      detail: !w.on ? "switched off" : w.error || (w.run ? `run ${w.run}` : w.note || "no forecast yet") });
  } catch (e) {
    rows.push({ part: "Collectors", what: "Weather forecast", status: "fail", detail: String((e as Error).message ?? e) });
  }
  return rows;
}

async function checkSources(): Promise<Row[]> {
  type H = { source_id: string; name: string; state: string; failing: string | null };
  const got = await get<H[] | { sources: H[] }>("/source-health");
  const all = Array.isArray(got) ? got : got.sources ?? [];
  const bad = all.filter((s) => s.state === "failing");
  return [{ part: "Sources", what: `${all.length} sources`, status: bad.length ? "slow" : "ok", detail: `${bad.length} failing` },
    ...bad.map((s) => ({ part: "Sources", what: s.name || s.source_id, status: "fail" as Status, detail: String(s.failing ?? "").slice(0, 240) }))];
}

const LABEL: Record<Status, string> = { ok: "OK", slow: "Slow", fail: "Problem", note: "Note" };

export default function SelfCheckPage() {
  const [rows, setRows] = useState<Row[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [doneAt, setDoneAt] = useState<string | null>(null);
  const [onlyBad, setOnlyBad] = useState(true);

  const run = async () => {
    setRows([]);
    setDoneAt(null);
    const add = (r: Row[]) => setRows((cur) => [...cur, ...r]);
    const step = async (name: string, fn: () => Promise<Row[]> | Row[]) => {
      setBusy(name);
      try { add(await fn()); } catch (e) { add([{ part: name, what: name, status: "fail", detail: `the check itself failed: ${String((e as Error).message ?? e)}` }]); }
    };
    await step("Map layers", checkLayerStyles);
    await step("Collectors", checkCollectors);
    await step("Sources", checkSources);
    await step("API", () => checkApi(setBusy));
    await step("Pages", () => checkPages(setBusy));
    setBusy(null);
    setDoneAt(new Date().toLocaleString());
  };

  const shown = onlyBad ? rows.filter((r) => r.status !== "ok" || /^\d/.test(r.what)) : rows;
  const problems = rows.filter((r) => r.status === "fail").length;
  const report = () => rows.map((r) => `${LABEL[r.status]}\t${r.part}\t${r.what}\t${r.detail}`).join("\n");

  return (
    <div className="grid">
      <div>
        <h1>Self check</h1>
        <p className="ink-2" style={{ marginTop: 0 }}>
          Checks this PC&apos;s app the way a review would: every map layer&apos;s style, every API call that needs no inputs, every page,
          the ship, plane and weather collectors, and the failing sources. Nothing is changed. Takes a minute or two.
          Back to <Link href="/data">Data status</Link>.
        </p>
      </div>
      <div className="controls">
        <button onClick={run} disabled={!!busy}>{busy ? `Checking… ${busy}` : rows.length ? "Check again" : "Run the self check"}</button>
        <label className="small"><input type="checkbox" checked={onlyBad} onChange={(e) => setOnlyBad(e.target.checked)} /> Only what needs a look</label>
        {doneAt && (
          <button onClick={() => navigator.clipboard?.writeText(report()).catch(() => {})} title="Copy the whole report, to paste into a message">Copy report</button>
        )}
      </div>
      {doneAt && (
        <p role="status" data-selfcheck={problems ? "problems" : "ok"} className={problems ? "error" : "ink-2"}>
          {problems ? `${problems} problem${problems === 1 ? "" : "s"} found` : "No problems found"} (checked {doneAt}).
        </p>
      )}
      {rows.length > 0 && (
        <table>
          <thead><tr><th>Result</th><th>Part</th><th>What</th><th>Detail</th></tr></thead>
          <tbody>
            {shown.map((r, i) => (
              <tr key={`${r.part}-${r.what}-${i}`}>
                <td className={r.status === "fail" ? "error" : r.status === "slow" ? "ink-2" : "muted"}>{LABEL[r.status]}</td>
                <td>{r.part}</td><td>{r.what}</td><td className="small">{r.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
