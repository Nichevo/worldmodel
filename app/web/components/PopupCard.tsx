"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import EChart from "@/components/EChart";
import { api, type Indicator, type Popup } from "@/lib/api";
import { miniOption } from "@/lib/charts";
import { seriesVar } from "@/lib/colors";
import { formatValue } from "@/lib/format";
import { logHistory } from "@/lib/history";

// A country's card: its value, rank among countries and change over ten years,
// with a small chart against its region and the world. Opened by clicking a
// country in a panel (a popup, which can be pinned) or kept on the side panel's
// pinboard. Tabs switch between the indicators the panels show.
type Props = {
  entity: string;
  indicator: Indicator;
  year: number | null; // the panel's year; null = the indicator's latest estimate
  tabs?: Indicator[]; // other indicators to offer as tabs
  variant?: "popup" | "board";
  pinned?: boolean;
  selected?: boolean;
  onClose: () => void;
  onPin?: () => void;
  onSelect?: () => void;
  onBoard?: (indicator: string) => void;
};

export function ordinal(n: number): string {
  const t = n % 100;
  return `${n}${t >= 11 && t <= 13 ? "th" : (["th", "st", "nd", "rd"][n % 10] ?? "th")}`;
}

// The year to show an indicator in: the panel's year held to the indicator's range.
function yearFor(ind: Indicator, year: number | null): number | null {
  if (ind.first_year === null || ind.last_year === null) return null;
  if (year === null) return ind.last_estimate_year ?? ind.last_year;
  return Math.min(ind.last_year, Math.max(ind.first_year, year));
}

export default function PopupCard({
  entity, indicator, year, tabs = [], variant = "popup", pinned = false, selected = false, onClose, onPin, onSelect, onBoard,
}: Props) {
  const all = [indicator, ...tabs.filter((t) => t.indicator_id !== indicator.indicator_id)];
  const [tab, setTab] = useState(indicator.indicator_id);
  useEffect(() => setTab(indicator.indicator_id), [indicator.indicator_id]);
  const ind = all.find((i) => i.indicator_id === tab) ?? indicator;
  const y = yearFor(ind, year);
  const [data, setData] = useState<Popup | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (y === null) return;
    let live = true;
    setError(null);
    popupData(entity, ind.indicator_id, y).then((d) => live && setData(d)).catch((e) => live && setError(String(e.message || e)));
    return () => { live = false; };
  }, [entity, ind.indicator_id, y]);

  useEffect(() => {
    if (variant !== "popup" || !data || data.entity !== entity) return;
    logHistory({ kind: "page", title: data.name, url: `/entity/${entity}`, entity, indicator: ind.indicator_id, detail: "popup" });
  }, [variant, data?.name, entity]);

  const shown = data && data.entity === entity && data.indicator === ind.indicator_id ? data : null;
  const option = useCallback(() => miniOption([
    { label: shown?.name ?? entity, points: shown?.series.entity ?? [] },
    { label: shown?.region?.name ?? "", points: shown?.series.region ?? [] },
    { label: "World", points: shown?.series.world ?? [] },
  ], ind.unit, ind.decimals, shown?.year ?? y ?? 0), [shown, ind, y, entity]);

  const unit = ind.unit === "percent" ? "points" : ind.unit;
  const change = shown?.change10;
  return (
    <div className={`popup-card ${variant}`} role="dialog" aria-label={`${shown?.name ?? entity}: ${ind.name}`}>
      <div className="popup-head">
        <b>{shown?.name ?? entity}</b>
        {shown?.region && <span className="muted small"> · {shown.region.name}</span>}
        <span className="spacer" />
        {pinned && <span className="pin-mark" title="Pinned">📌</span>}
        <button className="x" onClick={onClose} aria-label={variant === "board" ? "Remove from the pinboard" : "Close"}>×</button>
      </div>
      {variant === "popup" && all.length > 1 && (
        <div className="popup-tabs" role="tablist">
          {all.map((i) => (
            <button key={i.indicator_id} role="tab" aria-selected={i.indicator_id === tab} className={i.indicator_id === tab ? "on" : ""}
              onClick={() => setTab(i.indicator_id)} title={i.name}>{i.name}</button>
          ))}
        </div>
      )}
      <div className="popup-name small ink-2">{ind.name}{y !== null ? `, ${shown?.year ?? y}` : ""}</div>
      {error && <p className="error small">{error}</p>}
      {shown && (
        <>
          <div className="popup-value">
            <b>{formatValue(shown.value, ind.unit, ind.decimals)}</b>
            {shown.status === "P" && <span className="chip" title="The source's projection">proj.</span>}
          </div>
          <div className="popup-facts small">
            {shown.rank !== null && <span>{ordinal(shown.rank)} of {shown.of}</span>}
            {change && (
              <span title={`Change since ${change.from_year}`}>
                {change.value > 0 ? "+" : ""}{formatValue(change.value, unit === "points" ? "" : unit, ind.decimals)}
                {unit === "points" ? " pts" : ""} since {change.from_year}
              </span>
            )}
          </div>
          {shown.series.entity.length > 1 && (
            <>
              <div className="popup-chart"><EChart option={option} height={variant === "board" ? 90 : 120} label={`${ind.name}: ${shown.name}, its region and the world`} /></div>
              <div className="popup-legend small muted">
                <span><i style={{ background: seriesVar(0) }} />{shown.name}</span>
                {shown.region && shown.series.region.length > 0 && <span><i style={{ background: seriesVar(1) }} />{shown.region.name}</span>}
                {shown.series.world.length > 0 && <span><i style={{ background: "var(--muted)" }} />World</span>}
              </div>
            </>
          )}
        </>
      )}
      <div className="popup-actions">
        {onPin && <button className="small" onClick={onPin}>{pinned ? "Unpin" : "Pin"}</button>}
        {onSelect && <button className="small" onClick={onSelect}>{selected ? "Deselect" : "Select"}</button>}
        <Link className="small" href={`/entity/${entity}`}>Profile</Link>
        {onBoard && <button className="small" onClick={() => onBoard(ind.indicator_id)} title="Keep this card on the pinboard beside the panels">To side panel</button>}
      </div>
    </div>
  );
}

const cache = new Map<string, Promise<Popup>>();
function popupData(entity: string, indicator: string, year: number): Promise<Popup> {
  const key = `${entity}|${indicator}|${year}`;
  if (!cache.has(key)) {
    const p = api.popup(entity, indicator, year);
    p.catch(() => cache.delete(key));
    cache.set(key, p);
  }
  return cache.get(key)!;
}
