"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import EChart from "@/components/EChart";
import { api, type ComparedIndicator, type Divergence, type Entity, type SourceComparison } from "@/lib/api";
import { sourcesOption } from "@/lib/charts";
import { formatValue } from "@/lib/format";
import { logHistory } from "@/lib/history";

// Source comparison: where an indicator comes from more than one source (UN and
// World Bank population, IMF and World Bank growth), the sources side by side for
// one country, and the countries where they disagree most.
export default function SourcesPage() {
  return (
    <Suspense fallback={<p className="muted">Loading…</p>}>
      <Sources />
    </Suspense>
  );
}

const pct = (r: number | null) => (r === null ? "" : `${(r * 100).toFixed(r < 0.1 ? 1 : 0)}%`);

function Sources() {
  const params = useSearchParams();
  const [indicators, setIndicators] = useState<ComparedIndicator[] | null>(null);
  const [indicator, setIndicator] = useState(params.get("ind") ?? "");
  const [entity, setEntity] = useState(params.get("e") ?? "");
  const [countries, setCountries] = useState<Entity[]>([]);
  const [cmp, setCmp] = useState<SourceComparison | null>(null);
  const [rows, setRows] = useState<Divergence[] | null>(null);
  const [onlyDiffering, setOnlyDiffering] = useState(params.get("all") !== "1");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.comparedIndicators().then((l) => {
      setIndicators(l);
      setIndicator((cur) => (cur && l.some((i) => i.indicator_id === cur) ? cur : l.find((i) => i.indicator_id === "gdp_growth")?.indicator_id ?? l[0]?.indicator_id ?? ""));
    }).catch((e) => setError(String(e.message || e)));
    api.entities("country").then((c) => setCountries(c.sort((a, b) => a.short_name.localeCompare(b.short_name)))).catch(() => {});
  }, []);

  useEffect(() => {
    if (!indicator) return;
    setRows(null);
    api.divergence({ indicator, flagged: onlyDiffering, limit: 1000 }).then((r) => {
      setRows(r);
      setEntity((cur) => cur || r[0]?.entity_id || "NZL");
    }).catch((e) => setError(String(e.message || e)));
  }, [indicator, onlyDiffering]);

  useEffect(() => {
    if (!indicator || !entity) return;
    api.compareSources(indicator, entity).then(setCmp).catch((e) => setError(String(e.message || e)));
  }, [indicator, entity]);

  const info = indicators?.find((i) => i.indicator_id === indicator);
  const query = useMemo(() => new URLSearchParams({ ind: indicator, e: entity, ...(onlyDiffering ? {} : { all: "1" }) }).toString(),
    [indicator, entity, onlyDiffering]);
  useEffect(() => {
    if (!indicator || !entity) return;
    if (query !== window.location.search.slice(1)) window.history.replaceState(null, "", `?${query}`);
    const t = setTimeout(() => logHistory({ kind: "page", title: `Sources compared: ${info?.name ?? indicator}, ${cmp?.name ?? entity}`,
      url: `/sources?${query}`, entity, indicator, detail: "sources" }), 3000);
    return () => clearTimeout(t);
  }, [query, indicator, entity, info?.name, cmp?.name]);

  const decimals = rows?.[0]?.decimals ?? 1;
  const unit = info?.unit ?? "";
  const differing = useMemo(() => [...new Set((cmp?.differences ?? []).filter((d) => d.flagged).map((d) => d.year))], [cmp]);
  const option = useMemo(() => (cmp && cmp.indicator === indicator ? () => sourcesOption(cmp.sources, differing, unit, decimals) : null),
    [cmp, differing, unit, decimals, indicator]);
  const domains = useMemo(() => [...new Set((indicators ?? []).map((i) => i.domain))], [indicators]);

  if (error) return <p className="error">{error}</p>;
  if (indicators && !indicators.length) {
    return (
      <div>
        <h1>Sources compared</h1>
        <p className="ink-2">No indicator has two sources with data yet. Run a refresh to load the World Bank indicators beside the UN and IMF figures.</p>
      </div>
    );
  }

  return (
    <div className="grid">
      <div>
        <h1>Sources compared</h1>
        <p className="ink-2" style={{ marginTop: 0 }}>
          Where two sources publish the same figure, how far apart they are. The first source is the one maps and charts use;
          the others are drawn dashed. Shaded years differ by more than 5% (or, for percentages, by more than a point and 10%).
        </p>
        <div className="src-row" style={{ gap: 8, flexWrap: "wrap" }}>
          <select value={indicator} onChange={(e) => setIndicator(e.target.value)} aria-label="Indicator" style={{ maxWidth: "100%" }}>
            {domains.map((d) => (
              <optgroup key={d} label={d[0].toUpperCase() + d.slice(1)}>
                {indicators!.filter((i) => i.domain === d).map((i) => (
                  <option key={i.indicator_id} value={i.indicator_id}>{i.name} ({i.differing} of {i.countries} differ)</option>
                ))}
              </optgroup>
            ))}
          </select>
          <select value={entity} onChange={(e) => setEntity(e.target.value)} aria-label="Country" style={{ maxWidth: "100%" }}>
            {countries.map((c) => <option key={c.entity_id} value={c.entity_id}>{c.short_name}</option>)}
          </select>
          {info && <span className="small ink-2">{info.sources.map((s) => s.name).join(" vs ")}</span>}
        </div>
      </div>

      <div className="card">
        <h3>{info?.name ?? indicator}: {cmp?.name ?? entity}</h3>
        {option ? <EChart option={option} height={340} label={`${info?.name ?? indicator} for ${cmp?.name ?? entity}, by source`} />
          : <p className="muted">Loading…</p>}
        {cmp && !cmp.differences.length && <p className="caption">These sources have no years in common for this country.</p>}
        <p className="caption">
          <Link href={`/entity/${entity}`}>{cmp?.name ?? entity}</Link> · values as each source published them; the first
          source&apos;s projections continue past its last estimate.
        </p>
      </div>

      <div className="card">
        <div className="src-row" style={{ justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
          <h3 style={{ margin: 0 }}>{onlyDiffering ? "Countries where the sources differ" : "Every country compared"}</h3>
          <label className="small">
            <input type="checkbox" checked={onlyDiffering} onChange={(e) => setOnlyDiffering(e.target.checked)} /> Only those that differ
          </label>
        </div>
        <p className="caption">Each country&apos;s latest year with figures from both sources, biggest gap first. Click a row to chart it.</p>
        {!rows ? <p className="muted">Loading…</p> : !rows.length ? <p className="muted">The sources agree everywhere.</p> : (
          <div style={{ overflowX: "auto" }}>
            <table className="click-rows">
              <thead>
                <tr><th>Country</th><th className="num">Year</th><th className="num">{rows[0].source_a_name}</th>
                  <th className="num">Other source</th><th className="num">Gap</th><th className="num">Apart</th></tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={`${r.entity_id}-${r.source_b}`} className={r.entity_id === entity ? "on" : ""} onClick={() => setEntity(r.entity_id)}>
                    <td>{r.entity_name}</td>
                    <td className="num">{r.year}</td>
                    <td className="num">{formatValue(r.value_a, r.unit, r.decimals)}</td>
                    <td className="num" title={r.source_b_name}>{formatValue(r.value_b, r.unit, r.decimals)}</td>
                    <td className="num">{r.diff > 0 ? "+" : ""}{formatValue(r.diff, r.unit, r.decimals)}</td>
                    <td className="num">{r.flagged ? <b>{pct(r.rel)}</b> : pct(r.rel)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
