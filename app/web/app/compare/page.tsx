"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import ChartCard from "@/components/ChartCard";
import Search from "@/components/Search";
import { api, type Entity, type Indicator, type SeriesRow } from "@/lib/api";
import { seriesColor } from "@/lib/colors";
import { formatValue } from "@/lib/format";

const MAX = 8; // one categorical colour each; more would need folding or small multiples

function Compare() {
  const router = useRouter();
  const params = useSearchParams();
  const ids = useMemo(() => (params.get("ids") || "NZL,AUS").split(",").filter(Boolean).slice(0, MAX), [params]);
  const indicatorId = params.get("indicator") || "tfr";
  const [entities, setEntities] = useState<Entity[]>([]);
  const [indicators, setIndicators] = useState<Indicator[]>([]);
  const [latest, setLatest] = useState<SeriesRow[]>([]);

  useEffect(() => {
    api.entities().then(setEntities);
    api.indicators().then((l) => setIndicators(l.filter((i) => i.available && !i.breakdowns)));
  }, []);

  const names = useMemo(() => new Map(entities.map((e) => [e.entity_id, e.short_name])), [entities]);
  const named = useMemo(() => ids.map((id) => ({ id, name: names.get(id) ?? id })), [ids, names]);
  const indicator = indicators.find((i) => i.indicator_id === indicatorId);

  const update = (next: string[], ind = indicatorId) =>
    router.replace(`/compare?ids=${next.join(",")}&indicator=${ind}`);

  useEffect(() => {
    if (!indicator) return;
    api.series(indicator.indicator_id, ids).then((rows) => {
      const last = new Map<string, SeriesRow>();
      for (const r of rows) if (r.status === "E") last.set(r.entity_id, r);
      setLatest([...last.values()].sort((a, b) => b.value - a.value));
    });
  }, [indicator, ids]);

  return (
    <div className="grid">
      <div>
        <h1>Compare</h1>
        <p className="ink-2" style={{ marginTop: 0 }}>Pick up to {MAX} countries, regions or blocs and one indicator.</p>
      </div>
      <div className="controls">
        <label>
          Indicator{" "}
          <select value={indicatorId} onChange={(e) => update(ids, e.target.value)}>
            {indicators.map((i) => <option key={i.indicator_id} value={i.indicator_id}>{i.name}</option>)}
          </select>
        </label>
        <div style={{ width: 280 }}>
          <Search
            placeholder={ids.length >= MAX ? `Up to ${MAX} at once` : "Add a country, region or bloc"}
            kinds={["entity"]}
            onPick={(h) => ids.length < MAX && !ids.includes(h.id) && update([...ids, h.id])}
          />
        </div>
      </div>
      <div>
        {named.map((e, i) => (
          <span className="chip" key={e.id}>
            <span className="swatch" style={{ background: seriesColor(i) }} />
            <Link href={`/entity/${e.id}`}>{e.name}</Link>
            <button aria-label={`Remove ${e.name}`} onClick={() => update(ids.filter((x) => x !== e.id))}>×</button>
          </span>
        ))}
      </div>
      {indicator && named.length > 0 && <ChartCard indicator={indicator} entities={named} height={380} />}
      {indicator && latest.length > 0 && (
        <div className="card">
          <h3>Latest estimate, ranked</h3>
          <table>
            <thead><tr><th>#</th><th>Name</th><th className="num">{indicator.name}</th><th className="num">Year</th></tr></thead>
            <tbody>
              {latest.map((r, i) => (
                <tr key={r.entity_id}>
                  <td>{i + 1}</td>
                  <td><Link href={`/entity/${r.entity_id}`}>{names.get(r.entity_id) ?? r.entity_id}</Link></td>
                  <td className="num">{formatValue(r.value, indicator.unit, indicator.decimals)}</td>
                  <td className="num">{r.period}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function ComparePage() {
  return (
    <Suspense fallback={<p className="muted">Loading…</p>}>
      <Compare />
    </Suspense>
  );
}
