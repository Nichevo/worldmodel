"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import CardAsk from "@/components/CardAsk";
import EChart from "@/components/EChart";
import Flag from "@/components/Flag";
import { openAsk } from "@/lib/ai";
import {
  type Attention, type Calendar, type Nowcast, type Odds, type OddsReply, MODEL_NAMES, fmtPct, oddsOption, oddsTone,
  oddsWord, outlookApi, trackOption, viewsOption,
} from "@/lib/outlook";

// A half-circle dial, 0 to 100%.
export function OddsDial({ p, label, size = 132 }: { p: number | null; label: string; size?: number }) {
  const r = size / 2 - 10;
  const cx = size / 2, cy = size / 2;
  const a = Math.PI * (1 - Math.min(100, Math.max(0, p ?? 0)) / 100);
  const x = cx + r * Math.cos(a), y = cy - r * Math.sin(a);
  return (
    <figure className="dial" style={{ width: size }}>
      <svg viewBox={`0 0 ${size} ${size / 2 + 14}`} role="img" aria-label={`${label}: ${p === null ? "no reading" : `${p.toFixed(0)}% chance`}`}>
        <path d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`} fill="none" stroke="var(--grid)" strokeWidth="12" />
        {p !== null && <path d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${x.toFixed(1)} ${y.toFixed(1)}`} fill="none" stroke={oddsTone(p)} strokeWidth="12" />}
        <text x={cx} y={cy - 4} textAnchor="middle" fontSize="22" fontWeight="600" fill="var(--ink)">{p === null ? "–" : `${p.toFixed(0)}%`}</text>
        <text x={cx} y={cy + 12} textAnchor="middle" fontSize="11" fill="var(--muted)">{oddsWord(p)}</text>
      </svg>
      <figcaption className="small">{label}</figcaption>
    </figure>
  );
}

function driversText(o: Odds): string {
  return o.drivers.map((d) => `${d.about}: ${d.value} (${d.push > 0 ? "raises" : "lowers"} the odds)`).join("; ");
}

// The key countries' dials in a row; clicking one picks it for the chart below.
export function OddsRow({ data, pick, onPick }: { data: OddsReply; pick: string; onPick: (e: string) => void }) {
  return (
    <div className="dial-row">
      {data.countries.map((c) => (
        <button key={c.entity} className={`dial-btn${pick === c.entity ? " on" : ""}`} aria-pressed={pick === c.entity} onClick={() => onPick(c.entity)}>
          <OddsDial p={c.odds} label={c.name} />
          {c.in_recession && <span className="small warn-text">in recession now</span>}
        </button>
      ))}
    </div>
  );
}

export function OddsChart({ o, note }: { o: Odds; note: string }) {
  const option = useCallback(() => oddsOption(o), [o]);
  const ask = () => openAsk({ title: `${o.name}: odds of a recession within a year`, entity: o.entity, parts: [
    { key: "data", kind: "data", label: "Odds and drivers", text: `${o.odds}% (${o.month}); model: ${MODEL_NAMES[o.model ?? ""] ?? ""}. Drivers: ${driversText(o)}. Recessions: ${o.recessions.map((r) => r.join(" to ")).join(", ")}.${o.yield_curve ? ` New York Fed yield-curve model: ${o.yield_curve.odds}% (gap ${o.yield_curve.spread} points, ${o.yield_curve.month}).` : ""}` },
    { key: "how", kind: "description", label: "How it is worked out", text: note }] });
  if (o.odds === null) return <p className="muted">No reading for {o.name}: it needs quarterly GDP figures (and ideally the OECD leading indicator) from refresh.bat.</p>;
  const finding = `${o.name}: a ${o.odds.toFixed(0)}% chance a recession starts within a year (${oddsWord(o.odds)})`;
  return (
    <div className="card">
      <div className="card-head"><h3>{finding}</h3><CardAsk onAsk={ask} /></div>
      <EChart option={option} height={300} label={`Odds of a recession over time, ${o.name}`} />
      <div className="drivers small">
        <b>What moves the latest reading ({o.month}):</b>
        <ul>{o.drivers.map((d) => (
          <li key={d.feature}><span style={{ color: d.push > 0 ? "var(--bad)" : "var(--good)" }}>{d.push > 0 ? "▲" : "▼"}</span> {d.about}: <b>{d.value > 0 ? "+" : ""}{d.value}{d.unit === "%" ? "%" : ` ${d.unit}`}</b>
            {" "}({d.push > 0 ? "raises" : "lowers"} the odds{Math.abs(d.push) < 0.15 ? ", a little" : ""})</li>))}</ul>
        {o.yield_curve && <p>New York Fed yield-curve model: <b>{o.yield_curve.odds.toFixed(0)}%</b>, with the 10-year yield {o.yield_curve.spread >= 0 ? "above" : "below"} the 3-month rate by {Math.abs(o.yield_curve.spread).toFixed(2)} points ({o.yield_curve.month}).</p>}
      </div>
      <p className="caption">Grey bands are recessions (two quarters running of falling GDP). Model: {MODEL_NAMES[o.model ?? ""]}. {note}</p>
    </div>
  );
}

export function NowcastCard({ entity, name, compact = false }: { entity: string; name: string; compact?: boolean }) {
  const [n, setN] = useState<Nowcast | null>(null);
  useEffect(() => {
    let live = true;
    outlookApi.nowcast(entity).then((x) => live && setN(x)).catch(() => live && setN(null));
    return () => { live = false; };
  }, [entity]);
  const option = useCallback(() => trackOption(n ?? { entity, quarter: null, estimate: null }), [n, entity]);
  if (!n) return null;
  if (n.estimate === null) return compact ? null : <div className="card"><h3>{name}</h3><p className="muted small">{n.note}</p></div>;
  const ask = () => openAsk({ title: `${name}: growth this quarter (nowcast)`, entity, parts: [
    { key: "data", kind: "data", label: "Nowcast", text: `${n.quarter}: ${n.estimate}% on the quarter (range ${n.low} to ${n.high}); last official ${n.last_quarter}: ${n.last_actual}%. ${n.gdpnow ? `GDPNow ${n.gdpnow.quarter}: ${n.gdpnow.annualised}% a year.` : ""} Track: ${(n.track ?? []).map((t) => `${t.quarter} est ${t.estimate} actual ${t.actual}`).join("; ")}` },
    { key: "how", kind: "description", label: "How", text: n.note ?? "" }] });
  return (
    <div className="card">
      <div className="card-head"><h3>{name}: growth in {n.quarter} about {fmtPct(n.estimate)}</h3><CardAsk onAsk={ask} /></div>
      <p className="big-number">{fmtPct(n.estimate)} <span className="small muted">on the quarter ({fmtPct(n.annualised)} a year)</span></p>
      <p className="small">Likely range {fmtPct(n.low)} to {fmtPct(n.high)}. Last official figure, {n.last_quarter}: <b>{fmtPct(n.last_actual)}</b>.
        {n.gdpnow && <> Atlanta Fed GDPNow for {n.gdpnow.quarter}: <b>{fmtPct(n.gdpnow.annualised)} a year</b> ({fmtPct(n.gdpnow.quarterly, 2)} on the quarter).</>}</p>
      {!compact && (n.track?.length ?? 0) > 0 && <EChart option={option} height={220} label={`Nowcast track record, ${name}`} />}
      <p className="caption">{n.note}{n.typical_error ? ` Typically off by ${n.typical_error.toFixed(2)} points.` : ""}</p>
    </div>
  );
}

export function CalendarList({ data, showCountry = true }: { data: Calendar; showCountry?: boolean }) {
  const days = [...new Set(data.items.map((r) => r.nz_date))];
  if (!data.items.length) return <p className="muted">No releases in this window.</p>;
  return (
    <div className="cal-list">
      {days.map((d) => (
        <section key={d} className={`cal-day${d === data.today ? " today" : ""}`}>
          <h3 className="cal-date">{new Date(`${d}T12:00:00`).toLocaleDateString("en-NZ", { weekday: "long", day: "numeric", month: "long" })}{d === data.today ? " (today)" : ""}</h3>
          <ul>
            {data.items.filter((r) => r.nz_date === d).map((r) => (
              <li key={`${r.country}-${r.title}-${r.date}`} className={r.past ? "muted" : ""}>
                <span className="cal-time">{r.nz_time.slice(-5)}</span>
                {showCountry && <Flag id={r.country} />}
                <span className="chip small">{r.kind_name}</span>
                <a href={r.url} target="_blank" rel="noreferrer">{r.title}</a>
                {r.period && <span className="small muted"> · {r.period}</span>}
                {r.estimated && <span className="small muted" title="Worked out from the publisher's usual timing: the week is right more often than the day"> · date estimated</span>}
                {r.expected && <span className="small"> · app nowcast <b>{fmtPct(r.expected.value)}</b></span>}
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

export function AttentionCard({ entity, name }: { entity: string; name: string }) {
  const [a, setA] = useState<Attention | null>(null);
  useEffect(() => {
    let live = true;
    outlookApi.attention(entity).then((x) => live && setA(x)).catch(() => live && setA(null));
    return () => { live = false; };
  }, [entity]);
  const option = useCallback(() => viewsOption(a ?? { entity, points: [] }), [a, entity]);
  if (!a || (!a.points.length && !a.note)) return null;
  if (!a.points.length) return <div className="card"><h3>Wikipedia attention</h3><p className="muted small">{a.note}</p></div>;
  const ratio = a.ratio ?? 1;
  const finding = ratio >= 1.5 ? `${name}: read ${ratio.toFixed(1)} times as much as usual this week`
    : ratio <= 0.7 ? `${name}: read less than usual this week` : `${name}: read about as much as usual this week`;
  const ask = () => openAsk({ title: `${name}: Wikipedia attention`, entity, parts: [
    { key: "data", kind: "data", label: "Views a day", text: `${a.points.map(([d, v]) => `${d} ${v}`).join("; ")}. Usual ${a.usual}. Spikes: ${(a.spikes ?? []).map((s) => `${s.day} ${s.times}x`).join(", ") || "none"}.` }] });
  return (
    <div className="card" id="attention">
      <div className="card-head"><h3>{finding}</h3><span><CardAsk onAsk={ask} /> <Link className="small" href="/outlook?tab=attention">Most read</Link></span></div>
      <EChart option={option} height={200} label={`Wikipedia views a day, ${name}`} />
      {(a.spikes?.length ?? 0) > 0 && <p className="small">Spikes: {a.spikes!.map((s) => `${s.day.slice(5)} (${s.times}× usual)`).join(", ")}. A spike usually means something is happening there; check the news for those days.</p>}
      <p className="caption">Daily readers of the English Wikipedia article &quot;{a.article}&quot; over 90 days (people, not bots), from Wikimedia. The dashed line is the usual level (the median of the four weeks before).{a.note ? ` ${a.note}` : ""}</p>
    </div>
  );
}

// The country page's Outlook card: the odds and the nowcast in two lines.
export function OutlookCard({ entity, name }: { entity: string; name: string }) {
  const [o, setO] = useState<Odds | null>(null);
  const [n, setN] = useState<Nowcast | null>(null);
  useEffect(() => {
    let live = true;
    outlookApi.odds([entity]).then((x) => live && setO(x.countries[0] ?? null)).catch(() => {});
    outlookApi.nowcast(entity).then((x) => live && setN(x)).catch(() => {});
    return () => { live = false; };
  }, [entity]);
  if ((!o || o.odds === null) && (!n || n.estimate === null)) return null;
  const ask = () => openAsk({ title: `${name}: the economic outlook`, entity, parts: [
    { key: "data", kind: "data", label: "Odds and nowcast", text: `${o?.odds !== null && o ? `Recession odds ${o.odds}% (${o.month}); ${driversText(o)}.` : ""} ${n?.estimate !== null && n ? `Nowcast ${n.quarter}: ${n.estimate}% (range ${n.low} to ${n.high}).` : ""}` }] });
  return (
    <div className="card" id="outlook">
      <div className="card-head"><h3>Outlook</h3><span><CardAsk onAsk={ask} /> <Link className="small" href={`/outlook?country=${entity}`}>More</Link></span></div>
      <div className="outlook-mini">
        {o && o.odds !== null && <OddsDial p={o.odds} label="recession within a year" size={116} />}
        <div className="small">
          {o && o.odds !== null && <p>Chance a recession starts within a year: <b style={{ color: oddsTone(o.odds) }}>{o.odds.toFixed(0)}%</b> ({oddsWord(o.odds)}){o.in_recession ? "; in one now" : ""}.
            {o.drivers[0] && <> Biggest push: {o.drivers[0].about} ({o.drivers[0].push > 0 ? "up" : "down"}).</>}</p>}
          {n && n.estimate !== null && <p>Growth this quarter ({n.quarter}): about <b>{fmtPct(n.estimate)}</b>, likely {fmtPct(n.low)} to {fmtPct(n.high)}.
            {n.gdpnow && <> GDPNow: {fmtPct(n.gdpnow.annualised)} a year.</>}</p>}
        </div>
      </div>
      <p className="caption">Simple, explained models from the OECD leading indicator, central bank rates and GDP; not forecasts to bet on.</p>
    </div>
  );
}

// The Briefing's two lines: what comes out this week, and which countries people read about yesterday.
export function BriefComingUp() {
  const [d, setD] = useState<Calendar | null>(null);
  useEffect(() => { outlookApi.calendar(undefined, 7).then(setD).catch(() => setD(null)); }, []);
  const next = d?.items.filter((r) => !r.past) ?? [];
  if (!next.length) return null;
  return (
    <div className="brief-keys">
      <h3 className="brief-group-head">Coming up this week</h3>
      <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
        {next.slice(0, 10).map((r) => <li key={`${r.country}-${r.title}-${r.date}`}><Flag id={r.country} />{r.nz_time}: {r.title}{r.expected ? ` (nowcast ${fmtPct(r.expected.value)})` : ""}</li>)}
      </ul>
      <Link href="/outlook?tab=calendar" className="small">Release calendar</Link>
    </div>
  );
}

export function BriefMostRead() {
  const [d, setD] = useState<import("@/lib/outlook").AttentionTop | null>(null);
  useEffect(() => { outlookApi.attentionTop().then(setD).catch(() => setD(null)); }, []);
  const jumps = d?.key.filter((k) => (k.ratio ?? 0) >= 1.5) ?? [];
  if (!d || (!d.countries.length && !jumps.length)) return null;
  return (
    <div className="brief-keys">
      <h3 className="brief-group-head">Most read on Wikipedia{d.day ? `, ${d.day}` : ""}</h3>
      <div className="chips-row small">
        {d.countries.slice(0, 8).map((c) => <Link key={c.entity} href={`/entity/${c.entity}#attention`} className="chip"><Flag id={c.entity} />{c.name} #{c.rank}</Link>)}
      </div>
      {jumps.length > 0 && <p className="small">Read more than usual this week: {jumps.map((k) => `${k.name} (${k.ratio!.toFixed(1)}×)`).join(", ")}.</p>}
      <p className="caption">Country articles among the day&apos;s 1,000 most read. <Link href="/outlook?tab=attention">More</Link></p>
    </div>
  );
}
