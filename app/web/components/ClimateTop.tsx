"use client";

import { useCallback } from "react";
import CardAsk from "@/components/CardAsk";
import EChart from "@/components/EChart";
import { openAsk } from "@/lib/ai";
import type { ClimateHeadlines, SeriesRow } from "@/lib/api";
import { linesOption } from "@/lib/charts";
import { entityVar, sparkPath } from "@/lib/look";

// The top of the Climate page: a strip of headline figures, then on the Overview the world
// against your country with the finding as the title, records and firsts in the newest figures,
// and your key countries side by side.

// the server's topic for a record or tile -> the page's view
export const HEAD_VIEW: Record<string, string> = { warming: "world", ice: "ice", country: "country", enso: "enso", storms: "storms" };
const TONE: Record<string, string> = { warm: "var(--c-gbr)", cold: "var(--c-usa)", home: "var(--c-nzl)", enso: "var(--c-aus)", neutral: "var(--ink-2)" };

export function ClimateStrip({ h, onGo }: { h: ClimateHeadlines | null; onGo: (view: string) => void }) {
  if (!h?.heads.length) return null;
  const W = 120, H = 28;
  return (
    <div className="climate-strip">
      {h.heads.map((x) => (
        <button key={x.id} className="card tile htile climate-head" onClick={() => onGo(HEAD_VIEW[x.tab] ?? x.tab)} title={`${x.label}: open its tab`}>
          <span className="label">{x.label}</span>
          <span className="value">{x.value}</span>
          {x.spark.length > 1 && (
            <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden>
              <path d={sparkPath(x.spark.map((v, i) => [i, v] as [number, number]), W, H)} fill="none" stroke={TONE[x.tone] ?? TONE.neutral}
                strokeWidth={1.6} vectorEffect="non-scaling-stroke" />
            </svg>
          )}
          <span className="meta">{x.note}</span>
        </button>
      ))}
    </div>
  );
}

export function ClimateOverviewTab({ h, onGo }: { h: ClimateHeadlines | null; onGo: (view: string) => void }) {
  const rows: SeriesRow[] = (h?.lines ?? []).flatMap((l) => l.points.map(([y, v]) => ({ entity_id: l.id, indicator_id: "temp_anomaly", period: String(y), value: v,
    status: "E" as const, source_id: "", vintage: "", is_aggregate: false, coverage: null })));
  const opt = useCallback(() => {
    const o = linesOption([{ id: "temp_anomaly", name: "Temperature against 1951-1980", unit: "°C", decimals: 2, rows }], (h?.lines ?? []).map((l) => ({ id: l.id, name: l.name })));
    return { ...o, dataZoom: [{ type: "inside" }] };
  }, [h]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!h) return <p className="muted">Loading…</p>;
  const ask = (title: string, label: string, text: string) => openAsk({ title, parts: [{ key: title, kind: "data", label, text }] });
  return (
    <>
      <div className="grid two">
        {h.lines.length > 0 && (
          <div className="card">
            <div className="card-head"><span className="small ink-2">Temperature against 1951-1980</span>
              <CardAsk onAsk={() => ask(h.finding || "World temperature", "Temperature against 1951-1980 (°C)",
                ["Year\t" + h.lines.map((l) => l.name).join("\t"), ...[...new Set(h.lines.flatMap((l) => l.points.map((p) => p[0])))].sort().map((y) =>
                  `${y}\t${h.lines.map((l) => l.points.find((p) => p[0] === y)?.[1] ?? "").join("\t")}`)].join("\n"))} /></div>
            <h3 className="finding">{h.finding || "Temperature against 1951-1980"}</h3>
            <EChart option={opt} height={260} label="World and home temperature" />
            <p className="caption">Each year against the 1951-1980 average. World: NASA GISTEMP; countries: Our World in Data (Copernicus ERA5). Scroll on the chart to zoom.</p>
          </div>
        )}
        <div className="card">
          <div className="card-head"><span className="small ink-2">Records and firsts in the newest figures</span>
            <CardAsk onAsk={() => ask("Climate records and firsts", "Records in the newest figures", h.records.map((r) => `${r.level === "record" ? "Record" : "10+ years"}: ${r.text}`).join("\n"))} /></div>
          {h.records.length === 0 && <p className="small muted">Nothing in the newest figures is a record, or the highest or lowest for ten years or more.</p>}
          <ul className="climate-records">
            {h.records.map((r) => (
              <li key={r.text}>
                <i className={r.level} aria-label={r.level === "record" ? "record" : "highest or lowest in 10+ years"} />
                <span>{r.text}</span>
                <button className="link small" onClick={() => onGo(HEAD_VIEW[r.tab] ?? r.tab)}>Open</button>
              </li>
            ))}
          </ul>
          <p className="caption"><i className="dot record" /> a record high or low · <i className="dot decade" /> the highest or lowest in 10 years or more. Worked out from the stored figures at each refresh.</p>
        </div>
      </div>
      {h.compare.length > 0 && <KeyCountries h={h} />}
    </>
  );
}

export function KeyCountries({ h }: { h: ClimateHeadlines }) {
  const ids = h.keys;
  const color = (id: string) => entityVar(id, Math.max(0, ids.indexOf(id)));
  const names = new Map(h.compare.flatMap((c) => c.rows.map((r) => [r.entity_id, r.name] as const)));
  return (
    <div className="card">
      <div className="card-head"><span className="small ink-2">{names.get(h.home) ?? h.home} against {ids.slice(1).map((i) => names.get(i) ?? i).join(", ")}</span>
        <CardAsk onAsk={() => openAsk({ title: "Key countries on climate", parts: [{ key: "k", kind: "data", label: "Key countries",
          text: h.compare.map((c) => `${c.title}\n` + c.rows.map((r) => `${r.name}\t${r.text}\t(${r.year})`).join("\n")).join("\n\n") }] })} /></div>
      <div className="climate-compare">
        {h.compare.map((c) => {
          const top = Math.max(...c.rows.map((r) => Math.abs(r.value)), 1e-9);
          return (
            <div key={c.id} className="cc-block">
              <b className="small">{c.title}</b>
              {c.rows.map((r) => (
                <div key={r.entity_id} className="cc-row" title={`${r.name}: ${r.text} (${r.year})${r.note ? `. ${r.note}` : ""}`}>
                  <span className={r.entity_id === h.home ? "strong" : ""}>{r.name}</span>
                  <span className="cc-track"><span style={{ width: `${Math.max(1, (Math.abs(r.value) / top) * 100)}%`, background: color(r.entity_id) }} /></span>
                  <span className="mono">{r.text}</span>
                </div>
              ))}
              {c.note && <span className="caption">{c.note}</span>}
            </div>
          );
        })}
      </div>
    </div>
  );
}
