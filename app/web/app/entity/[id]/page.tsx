"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import ChartCard from "@/components/ChartCard";
import Pyramid from "@/components/Pyramid";
import { api, type EntityDetail, type Indicator, type ProfileRow } from "@/lib/api";
import { formatValue, SOURCE_LABEL, SOURCE_SHORT } from "@/lib/format";
import { logHistory } from "@/lib/history";

const CHARTS: { id: string; kind?: "line" | "bar" }[] = [
  { id: "pop_total" },
  { id: "tfr" },
  { id: "life_expectancy" },
  { id: "median_age" },
  { id: "pop_share_65_plus" },
  { id: "old_age_dependency_ratio" },
  { id: "net_migration_rate" },
  { id: "gdp_growth", kind: "bar" },
  { id: "gdp_per_capita_usd" },
];

const TYPE_LABEL: Record<string, string> = {
  country: "Country or area", historical_country: "Former state", world: "World", continent: "Continent",
  subregion: "UN sub-region", intermediate_region: "UN region", bloc: "Bloc", alliance: "Alliance", group: "Group",
};

export default function EntityPage() {
  const { id } = useParams<{ id: string }>();
  const [entity, setEntity] = useState<EntityDetail | null>(null);
  const [profile, setProfile] = useState<ProfileRow[]>([]);
  const [indicators, setIndicators] = useState<Indicator[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setEntity(null);
    api.entity(id).then((e) => {
      setEntity(e);
      logHistory({ kind: "page", title: e.short_name, url: `/entity/${e.entity_id}`, entity: e.entity_id, detail: "profile" });
    }).catch((e) => setError(String(e.message || e)));
    api.profile(id).then(setProfile).catch(() => setProfile([]));
  }, [id]);
  useEffect(() => {
    api.indicators().then(setIndicators);
  }, []);

  const named = useMemo(() => (entity ? [{ id: entity.entity_id, name: entity.short_name }] : []), [entity]);
  const byId = useMemo(() => new Map(indicators.map((i) => [i.indicator_id, i])), [indicators]);

  if (error) return <p className="error">{error}</p>;
  if (!entity) return <p className="muted">Loading…</p>;
  const isGroup = !["country", "historical_country"].includes(entity.type);

  return (
    <div className="grid">
      <div>
        <h1>{entity.short_name}</h1>
        <div className="ink-2">
          {TYPE_LABEL[entity.type] ?? entity.type}
          {entity.name !== entity.short_name ? ` · ${entity.name}` : ""}
          {entity.valid_to ? ` · existed until ${entity.valid_to}` : ""}
          {!entity.valid_to && (entity.type === "country" || entity.type === "world") && (
            <> · <Link href={`/forecasts?e=${entity.entity_id}`}>Population what-if</Link>
              {" · "}<Link href={`/forecasts?e=${entity.entity_id}&tab=track`}>IMF track record</Link></>
          )}
        </div>
        {entity.description && <p className="ink-2 small">{entity.description}</p>}
        {entity.groups.length > 0 && (
          <div style={{ marginTop: 8 }}>
            {entity.groups.map((g) => (
              <Link key={g.entity_id} href={`/entity/${g.entity_id}`} className="chip">{g.short_name}</Link>
            ))}
          </div>
        )}
        {entity.successions.length > 0 && (
          <p className="small ink-2">
            {entity.successions.map((s, i) => (
              <span key={i}>
                {s.predecessor_id === entity.entity_id
                  ? <>Succeeded by <Link href={`/entity/${s.successor_id}`}>{s.successor_id}</Link></>
                  : <>Formed from <Link href={`/entity/${s.predecessor_id}`}>{s.predecessor_id}</Link></>}
                {` (${s.kind}, ${s.date})`}{i < entity.successions.length - 1 ? "; " : ""}
              </span>
            ))}
          </p>
        )}
        <p style={{ marginTop: 8 }}>
          <Link href={`/compare?ids=${entity.entity_id}`}>Compare with others →</Link>
        </p>
      </div>

      {profile.length > 0 && (
        <div className="tiles">
          {profile.map((p) => (
            <div className="card tile" key={p.indicator_id}>
              <div className="label">{p.name}</div>
              <div className="value">{formatValue(p.value, p.unit, p.decimals)}</div>
              <div className="meta">{p.period} · {SOURCE_SHORT[p.source_id] ?? p.source_id}{p.is_aggregate ? " · built from members" : ""}</div>
            </div>
          ))}
        </div>
      )}

      {isGroup && entity.members.length > 0 && (
        <div className="card">
          <h3>Members today ({entity.members.length})</h3>
          <div>
            {entity.members.map((m) => (
              <Link key={m.entity_id} href={`/entity/${m.entity_id}`} className="chip">{m.short_name}</Link>
            ))}
          </div>
          {entity.membership_history.length > 0 && (
            <details style={{ marginTop: 8 }}>
              <summary className="small">Membership changes over time</summary>
              <table>
                <thead><tr><th>Member</th><th>Joined</th><th>Left</th></tr></thead>
                <tbody>
                  {entity.membership_history.map((m, i) => (
                    <tr key={i}><td>{m.short_name}</td><td>{m.valid_from ?? ""}</td><td>{m.valid_to ?? ""}</td></tr>
                  ))}
                </tbody>
              </table>
            </details>
          )}
          <p className="caption">Group values are built from the members of each year, so a 1990 value uses the members of 1990.</p>
        </div>
      )}

      <div className="grid two">
        {CHARTS.map((c) => {
          const ind = byId.get(c.id);
          return ind && ind.available ? <ChartCard key={c.id} indicator={ind} entities={named} kind={c.kind} /> : null;
        })}
        {byId.get("pop_by_age_sex")?.available && (
          <div className="card">
            <h3>Population by age and sex</h3>
            <Pyramid entity={entity.entity_id} name={entity.short_name} />
            <p className="caption">Source: {SOURCE_LABEL.un_wpp}. Five-year age groups on 1 July.</p>
          </div>
        )}
      </div>
    </div>
  );
}
