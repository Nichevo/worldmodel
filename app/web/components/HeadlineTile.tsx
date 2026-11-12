import Link from "next/link";
import type { ProfileRow } from "@/lib/api";
import { formatValue, SOURCE_SHORT } from "@/lib/format";
import { changeTone, sparkPath } from "@/lib/look";

// A headline figure: the big number, the change since the year before (green when better,
// red when worse, grey when neither way is better), a ten-year sparkline and the world rank.
export default function HeadlineTile({ p, entity }: { p: ProfileRow; entity: string }) {
  const trend = p.trend ?? [];
  const prev = trend.length > 1 ? trend[trend.length - 2] : null;
  const delta = prev ? p.value - prev[1] : 0;
  const tone = changeTone(delta, p.better);
  const pct = prev && prev[1] ? (delta / Math.abs(prev[1])) * 100 : null;
  // Rates and shares change in points; levels change in per cent.
  const inPoints = /percent|%|per 1,000|per woman|years/.test(p.unit) || p.unit === "";
  const same = !!prev && formatValue(Math.abs(delta), p.unit, p.decimals) === formatValue(0, p.unit, p.decimals);
  const chg = !prev ? null : same ? "no change" : inPoints
    ? `${delta >= 0 ? "▲" : "▼"} ${formatValue(Math.abs(delta), p.unit, p.decimals)}`
    : pct !== null ? `${delta >= 0 ? "▲" : "▼"} ${Math.abs(pct).toFixed(Math.abs(pct) < 10 ? 1 : 0)}%` : null;
  const W = 92, H = 26;
  const path = sparkPath(trend, W, H);
  const last = trend.length ? trend[trend.length - 1] : null;
  return (
    <Link href={`/indicator/${p.indicator_id}?e=${entity}`} className="card tile htile" style={{ color: "inherit", textDecoration: "none" }}
      title={`${p.name}: open the indicator page`}>
      <div className="label">{p.name}</div>
      <div className="value">{formatValue(p.value, p.unit, p.decimals)}</div>
      <div className="row">
        {chg ? <span className={`chg ${same ? "flat" : tone}`} title={`Change since ${prev![0]}`}>{chg}</span> : <span />}
        {path && (
          <svg width={W} height={H} aria-hidden>
            <path d={path} fill="none" stroke="var(--ink-2)" strokeWidth={1.4} />
            {last && <circle cx={W - 2} cy={(() => { const ys = trend.map((t) => t[1]); const lo = Math.min(...ys), hi = Math.max(...ys); return H - 2 - ((last[1] - lo) / (hi - lo || 1)) * (H - 4); })()} r={2.4}
              fill={tone === "good" ? "var(--good)" : tone === "bad" ? "var(--bad)" : "var(--ink)"} />}
          </svg>
        )}
      </div>
      <div className="row">
        <span className="meta">{p.period} · {SOURCE_SHORT[p.source_id] ?? p.source_id}{p.is_aggregate ? " · from members" : ""}</span>
        {p.rank ? <span className="rank" title="Among countries, highest first, in the same year">#{p.rank} of {p.of}</span> : null}
      </div>
    </Link>
  );
}
