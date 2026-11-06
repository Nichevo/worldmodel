"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import CardAsk from "@/components/CardAsk";
import EChart from "@/components/EChart";
import { api, type FxData } from "@/lib/api";
import { useSavePicture } from "@/lib/cards";
import { datedLines } from "@/lib/markets";
import { saveSettings, useSettings } from "@/lib/settings";

// A country's currency against its main trading partners' currencies, day by day: as
// rates (one partner at a time, so each keeps its own scale), indexed to 100 at the start
// (all together), or the BIS trade-weighted index. Partners are its biggest trading
// partners unless chosen here (kept in Settings).
type View = "rate" | "index" | "twi";

export default function CurrencyCard({ entity, name }: { entity: string; name: string }) {
  const settings = useSettings();
  const saved = settings.fx_partners?.[entity] ?? "";
  const [view, setView] = useState<View>("index");
  const [from, setFrom] = useState<number | null>(null);
  const [to, setTo] = useState<number | null>(null);
  const [shown, setShown] = useState<string | null>(null);
  const [data, setData] = useState<FxData | null>(null);
  const { onReady, save, ask } = useSavePicture();
  useEffect(() => {
    let live = true;
    api.fx(entity, { partners: saved || undefined, start: from ?? undefined, end: to ?? undefined, mode: view === "index" ? "index" : "rate" })
      .then((d) => live && setData(d)).catch(() => live && setData(null));
    return () => { live = false; };
  }, [entity, saved, from, to, view]);
  const own = data?.currency ?? "";
  const pick = data?.partners.find((p) => p.entity_id === shown) ?? data?.partners[0];
  const option = useCallback(() => {
    if (!data) return {};
    if (view === "twi") return datedLines(data.twi.map((t) => ({ name: `${t.name} trade-weighted`, points: t.points })), "2020 = 100", 1, { base: 100 });
    if (view === "index") return datedLines(data.partners.map((p) => ({ name: p.currency ?? p.name, points: p.points })), "start = 100", 1, { base: 100 });
    return datedLines(pick ? [{ name: `${pick.currency} per ${own}`, points: pick.points }] : [], pick ? `${pick.currency} per ${own}` : "", 4);
  }, [data, view, pick, own]);
  const years = useMemo(() => {
    if (!data?.first_year || !data.last_date) return [];
    const last = +data.last_date.slice(0, 4);
    return Array.from({ length: last - data.first_year + 1 }, (_, i) => data.first_year! + i);
  }, [data?.first_year, data?.last_date]);
  if (!data || !data.currency || (!data.partners.some((p) => p.points.length) && !data.twi.length)) return null;
  const ids = data.partners.map((p) => p.entity_id);
  const setPartners = (next: string[]) => saveSettings({ fx_partners: { ...(settings.fx_partners ?? {}), [entity]: next.join(",") } });
  const reset = () => { const rest = { ...(settings.fx_partners ?? {}) }; delete rest[entity]; saveSettings({ fx_partners: rest }); };
  const change = (pts: [string, number][]) => (pts.length > 1 ? 100 * (pts[pts.length - 1][1] / pts[0][1] - 1) : null);
  const title = view === "twi" ? `Trade-weighted exchange rate: ${name}` : `${data.currency_name} against ${view === "rate" && pick ? pick.currency_name : "its partners"}`;
  const note = view === "index" ? "Units of each partner's currency one unit buys, set to 100 on the first day shown: above 100, it buys more than then."
    : view === "twi" ? "BIS broad effective exchange rate, monthly: nominal, and real (after inflation at home and abroad)." : "";
  const sources = ["ecb_fx", "fed_h10", ...(view === "twi" ? ["bis"] : [])];
  return (
    <div className="card" id="currency">
      <div className="card-head">
        <h3>Currency: {data.currency_name} ({own})</h3>
        <span>
          <CardAsk onAsk={() => ask(title, note, sources, entity)} />{" "}
          <button className="link small" title="Save this chart as a picture, with its sources" onClick={() => save(title, note, sources, "currency", view, entity)}>Save picture</button>
        </span>
      </div>
      <div className="chips-row small">
        <div className="seg" role="group" aria-label="Show">
          <button className={view === "index" ? "on" : ""} aria-pressed={view === "index"} onClick={() => setView("index")}>Indexed</button>
          <button className={view === "rate" ? "on" : ""} aria-pressed={view === "rate"} onClick={() => setView("rate")}>Rates</button>
          <button className={view === "twi" ? "on" : ""} aria-pressed={view === "twi"} disabled={!data.twi.length} onClick={() => setView("twi")}
            title={data.twi.length ? "" : "Needs the BIS effective exchange rates (refresh)"}>Trade-weighted</button>
        </div>
        <label>From <select value={from ?? data.start ?? ""} onChange={(e) => setFrom(+e.target.value)}>
          {years.filter((y) => y <= (to ?? data.end ?? 9999)).map((y) => <option key={y} value={y}>{y}</option>)}</select></label>
        <label>to <select value={to ?? data.end ?? ""} onChange={(e) => setTo(+e.target.value)}>
          {years.filter((y) => y >= (from ?? data.start ?? 0)).map((y) => <option key={y} value={y}>{y}</option>)}</select></label>
      </div>
      {view !== "twi" && (
        <div className="chips-row small">
          {data.partners.map((p) => (
            <span key={p.entity_id} className={`chip${view === "rate" && pick?.entity_id === p.entity_id ? " on" : ""}`}>
              <button className="link" onClick={() => { setShown(p.entity_id); setView("rate"); }} title={`${p.currency_name} (${p.name})`}>{p.currency}</button>
              <button aria-label={`Remove ${p.currency}`} title="Remove" onClick={() => setPartners(ids.filter((x) => x !== p.entity_id))}>×</button>
            </span>
          ))}
          <select value="" aria-label="Add a currency" onChange={(e) => e.target.value && setPartners([...ids, e.target.value])}>
            <option value="">Add a currency…</option>
            {data.choices.filter((c) => !ids.includes(c.entity_id)).map((c) => <option key={c.entity_id} value={c.entity_id}>{c.currency}: {c.currency_name}</option>)}
          </select>
          {!data.default_partners && <button className="link" onClick={reset}>Back to top trading partners</button>}
        </div>
      )}
      <EChart option={option} height={280} label={title} onReady={onReady} />
      {view !== "twi" && (
        <table className="small">
          <thead><tr><th>Currency</th><th className="num">{view === "index" ? "Index now" : `1 ${own} buys`}</th><th className="num">Change since {data.start}</th></tr></thead>
          <tbody>
            {data.partners.filter((p) => p.points.length).map((p) => {
              const last = p.points[p.points.length - 1], c = change(p.points);
              return (
                <tr key={p.entity_id}>
                  <td>{p.currency_name} ({p.name})</td>
                  <td className="num">{view === "index" ? last[1].toFixed(1) : `${last[1].toLocaleString(undefined, { maximumSignificantDigits: 4 })} ${p.currency}`}</td>
                  <td className="num">{c == null ? "" : `${c > 0 ? "+" : ""}${c.toFixed(1)}%`}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      <p className="caption">
        {data.default_partners ? "Partners: the country's biggest trading partners (BACI), one per currency; add or remove them above. " : "Partners chosen by you (kept in Settings). "}
        Rates from the ECB (working days since 1999) and the US Federal Reserve H.10 (since 1971), worked out through the US dollar.
        {data.step === "week" ? " Each point is the week's last rate." : data.step === "month" ? " Each point is the month's last rate." : ""} {note}
      </p>
    </div>
  );
}
