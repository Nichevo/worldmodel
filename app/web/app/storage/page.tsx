"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import CardAsk from "@/components/CardAsk";
import EChart from "@/components/EChart";
import { api, type StorageItem, type StorageSeries } from "@/lib/api";
import { useSavePicture } from "@/lib/cards";
import { formatValue } from "@/lib/format";
import { dayLabel, storageClock, storageLines } from "@/lib/markets";
import { saveSettings, useSettings } from "@/lib/settings";

// Storage: how full Europe's gas storage is, US oil and gas stocks week by week, and oil and
// gas stocks by country month by month (New Zealand's through JODI), this year set against the
// range and average of the years before. Drawn as a clock (January at the top) or as lines.
function StoragePage() {
  const router = useRouter();
  const params = useSearchParams();
  const settings = useSettings();
  const [list, setList] = useState<StorageItem[] | null>(null);
  const [data, setData] = useState<StorageSeries | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [events, setEvents] = useState(true);
  const { onReady, save, ask } = useSavePicture();
  useEffect(() => { api.storageList().then(setList).catch((e) => setError(String(e.message || e))); }, []);
  const key = params.get("s");
  const item = useMemo(() => {
    if (!list?.length) return null;
    const [ind, ent] = (key ?? "").split(":");
    return list.find((x) => x.indicator_id === ind && x.entity_id === ent)
      ?? list.find((x) => x.indicator_id === "gas_storage_fill" && x.entity_id === "eu")
      ?? list.find((x) => x.entity_id === "NZL") ?? list[0];
  }, [list, key]);
  useEffect(() => {
    if (!item) return;
    let live = true;
    api.storageSeries(item.indicator_id, item.entity_id, settings.storage_years).then((d) => live && setData(d)).catch((e) => live && setError(String(e.message || e)));
    return () => { live = false; };
  }, [item, settings.storage_years]);
  const style = settings.storage_chart ?? "clock";
  const option = useCallback(() => (data ? (style === "clock" ? storageClock(data, events) : storageLines(data, events)) : {}), [data, style, events]);
  const groups = useMemo(() => [...new Set((list ?? []).map((x) => x.group))], [list]);
  if (error) return <p className="error">{error}</p>;
  if (!list) return <p className="muted">Loading…</p>;
  if (!list.length) {
    return (
      <div>
        <h1>Storage</h1>
        <p>No storage figures yet. They come from four free sources: GIE (European gas storage, needs the free GIE_API_KEY), the US EIA
          (weekly US stocks, needs EIA_API_KEY), and JODI (oil and gas stocks by country, no key). Add the keys to <code>.env</code> (see
          {" "}<Link href="/data">Data status</Link>, Keys you can add), then run <code>.\refresh.bat</code>.</p>
      </div>
    );
  }
  const go = (x: StorageItem) => router.replace(`/storage?s=${x.indicator_id}:${x.entity_id}`, { scroll: false });
  const fmt = (v: number | null | undefined) => (v == null ? "" : data?.unit === "percent" ? `${v.toFixed(1)}%`
    : `${formatValue(v, data?.unit ?? "", data?.decimals ?? 1)} ${data?.unit ?? ""}`);
  const diff = (a: number | null | undefined, b: number | null | undefined) => {
    if (a == null || b == null || !b) return "";
    const pct = data?.unit === "percent" ? `${(a - b) > 0 ? "+" : ""}${(a - b).toFixed(1)} points` : `${a > b ? "+" : ""}${(100 * (a / b - 1)).toFixed(1)}%`;
    return pct;
  };
  const title = data ? `${data.name}: ${data.entity_name}, ${data.year} against ${data.years_back.length} years before` : "";
  const note = data ? `Latest ${data.latest.date}: ${fmt(data.latest.value)}; ${data.years_back.length}-year average for this time of year ${fmt(data.latest.average)}.` : "";
  return (
    <div className="grid">
      <div className="title-row"><h1>Storage</h1></div>
      <div className="grid two" style={{ gridTemplateColumns: "minmax(220px, 300px) 1fr" }}>
        <div className="card">
          {groups.map((g) => (
            <div key={g}>
              <h4>{g}</h4>
              <ul className="small plain" style={{ listStyle: "none", paddingLeft: 0 }}>
                {list.filter((x) => x.group === g).map((x) => {
                  const on = item?.indicator_id === x.indicator_id && item?.entity_id === x.entity_id;
                  return <li key={`${x.indicator_id}:${x.entity_id}`}><button className={`link${on ? " on" : ""}`} style={{ textAlign: "left" }} aria-pressed={on} onClick={() => go(x)}>
                    {on ? <b>{x.entity_name}: {x.name}</b> : `${x.entity_name}: ${x.name}`}</button></li>;
                })}
              </ul>
            </div>
          ))}
        </div>
        <div className="card">
          <div className="card-head">
            <h3>{data ? `${data.name}: ${data.entity_name}` : "…"}</h3>
            <span>
              <CardAsk onAsk={() => ask(title, note, [data?.indicator_id.startsWith("jodi") ? "jodi" : data?.indicator_id.startsWith("us_") ? "eia" : "gie_agsi"], data?.entity_id)} />{" "}
              <button className="link small" onClick={() => save(title, note, [], "storage", data?.indicator_id ?? "", data?.entity_id ?? "")}>Save picture</button>
            </span>
          </div>
          <div className="chips-row small">
            <div className="seg" role="group" aria-label="Chart style">
              <button className={style === "clock" ? "on" : ""} aria-pressed={style === "clock"} onClick={() => saveSettings({ storage_chart: "clock" })}>Clock</button>
              <button className={style === "lines" ? "on" : ""} aria-pressed={style === "lines"} onClick={() => saveSettings({ storage_chart: "lines" })}>Lines</button>
            </div>
            <label>Years in the band <select value={settings.storage_years ?? 5} onChange={(e) => saveSettings({ storage_years: +e.target.value })}>
              {[3, 5, 10, 15].map((n) => <option key={n} value={n}>{n}</option>)}</select></label>
            <label><input type="checkbox" checked={events} onChange={(e) => setEvents(e.target.checked)} /> Events</label>
          </div>
          {data && (
            <>
              <div className="tiles">
                <div className="tile"><div className="label">Latest ({data.latest.date})</div><div className="value">{fmt(data.latest.value)}</div></div>
                <div className="tile"><div className="label">Against the {data.years_back.length}-year average</div><div className="value">{diff(data.latest.value, data.latest.average) || "—"}</div>
                  <div className="small muted">average {fmt(data.latest.average)}</div></div>
                <div className="tile"><div className="label">Against a year before</div><div className="value">{diff(data.latest.value, data.latest.year_ago) || "—"}</div>
                  <div className="small muted">{fmt(data.latest.year_ago)}</div></div>
              </div>
              <EChart option={option} height={style === "clock" ? 520 : 400} label={title} onReady={onReady} />
              {events && data.events.length > 0 && (
                <details><summary className="small">{data.events.length} event{data.events.length > 1 ? "s" : ""} in {data.year}</summary>
                  <ul className="small">{data.events.map((e) => <li key={e.date + e.title}><b>{dayLabel(e.day)}</b> {e.title}</li>)}</ul></details>
              )}
              <p className="caption">
                {style === "clock" ? "January at the top, going round clockwise; the further out, the more in storage. " : ""}
                The shaded band runs from the lowest to the highest value at that time of year in {data.years_back[0]}–{data.years_back[data.years_back.length - 1]},
                the dashed line is their average. {data.frequency === "M" ? "Month-end stocks. " : data.frequency === "W" ? "End of each week. " : "Each gas day. "}
                Sources: {data.indicator_id.startsWith("jodi") ? "JODI Oil and JODI Gas World Databases" : data.indicator_id.startsWith("us_") ? "US Energy Information Administration" : "Gas Infrastructure Europe, AGSI+ and ALSI"}.
                Choose the style and years in Settings or here.
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<p className="muted">Loading…</p>}><StoragePage /></Suspense>;
}
