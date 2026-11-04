"use client";

import { useMemo, useState } from "react";
import type { Indicator } from "@/lib/api";
import { saveSettings, useSettings } from "@/lib/settings";

// The pop-out panel on the country page: tick which charts and cards show. Saved in
// Settings (profile_charts, profile_cards_hidden), so every country page follows it.
export type ProfileCard = { key: string; title: string };

// Ready-made set-ups: charts in order, and the cards they leave out.
const READY: { name: string; charts: string[]; hidden: string[] }[] = [
  { name: "Economy", charts: ["gdp_growth", "gdp_per_capita_usd", "inflation", "unemployment", "govt_debt_gdp", "current_account_gdp"],
    hidden: ["education", "voters", "energy_mix", "energy_flow", "cities", "places", "crisiswatch"] },
  { name: "People", charts: ["pop_total", "tfr", "life_expectancy", "median_age", "pop_share_65_plus", "net_migration_rate"],
    hidden: ["debt", "housing", "energy_mix", "energy_flow", "sources_differ"] },
  { name: "Energy and climate", charts: ["renewables_share_elec", "co2_per_capita", "energy_per_capita", "sea_ice_extent_min"],
    hidden: ["migration", "education", "voters", "debt", "housing", "prices", "voting", "between"] },
  { name: "World affairs", charts: ["military_spending_gdp", "gdp_growth", "sanctions_active", "treaties_joined"],
    hidden: ["education", "housing", "prices", "energy_flow", "cities", "places"] },
];

export default function ProfilePicker({ open, onClose, indicators, charts, defaults, setCharts, cards, hidden, setHidden }: {
  open: boolean; onClose: () => void;
  indicators: Indicator[]; charts: string[]; defaults: string[]; setCharts: (ids: string[]) => void;
  cards: ProfileCard[]; hidden: string[]; setHidden: (keys: string[]) => void;
}) {
  const [q, setQ] = useState("");
  const [all, setAll] = useState(false);
  const picked = new Set(charts);
  const groups = useMemo(() => {
    const t = q.trim().toLowerCase();
    const hit = (i: Indicator) => !t || i.name.toLowerCase().includes(t) || i.indicator_id.toLowerCase().includes(t)
      || i.synonyms.some((s) => s.toLowerCase().includes(t)) || i.domain.toLowerCase().includes(t);
    const shown = indicators.filter((i) => i.available && (all || t || i.enabled || picked.has(i.indicator_id)) && hit(i)
      && !i.breakdowns.includes("age")); // age-by-sex tables have their own card (the pyramid)
    const by = new Map<string, Indicator[]>();
    for (const i of shown) by.set(i.domain || "Other", [...(by.get(i.domain || "Other") ?? []), i]);
    return [...by.entries()].sort(([a], [b]) => a.localeCompare(b))
      .map(([d, xs]) => [d, xs.sort((a, b) => a.name.localeCompare(b.name))] as const);
  }, [indicators, q, all, charts]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!open) return null;
  const toggle = (id: string) => setCharts(picked.has(id) ? charts.filter((x) => x !== id) : [...charts, id]);
  const move = (id: string, by: number) => {
    const i = charts.indexOf(id), j = i + by;
    if (i < 0 || j < 0 || j >= charts.length) return;
    const next = [...charts];
    [next[i], next[j]] = [next[j], next[i]];
    setCharts(next);
  };
  const names = new Map(indicators.map((i) => [i.indicator_id, i.name]));
  const apply = (p: { charts: string[] | string; hidden: string[] | string }) => {
    const list = (x: string[] | string) => (Array.isArray(x) ? x : x.split(",").filter(Boolean));
    saveSettings({ profile_charts: list(p.charts).join(",") || "none", profile_cards_hidden: list(p.hidden).join(",") });
  };
  return (
    <aside className="profile-picker" role="dialog" aria-label="Choose what the country page shows">
      <div className="profile-picker-head">
        <h3>Country page contents</h3>
        <span className="spacer" />
        <button className="link" onClick={onClose} aria-label="Close">×</button>
      </div>
      <p className="small muted">Saved for every country page. A chart a country has no data for says so on its page.</p>

      <SavedSetups current={{ charts: charts.join(","), hidden: hidden.join(",") }} apply={apply} />

      <h4>Cards</h4>
      <div className="picker-list">
        {cards.map((c) => (
          <label key={c.key} className="picker-row">
            <input type="checkbox" checked={!hidden.includes(c.key)}
              onChange={() => setHidden(hidden.includes(c.key) ? hidden.filter((k) => k !== c.key) : [...hidden, c.key])} />
            {c.title}
          </label>
        ))}
      </div>

      <h4>Charts shown, in order ({charts.length})</h4>
      <div className="picker-list">
        {charts.map((id, n) => (
          <div key={id} className="picker-row">
            <input type="checkbox" checked onChange={() => toggle(id)} aria-label={`Remove ${names.get(id) ?? id}`} />
            <span className="grow">{names.get(id) ?? <>{id} <span className="muted small">(no data loaded yet)</span></>}</span>
            <button className="link" disabled={n === 0} onClick={() => move(id, -1)} aria-label="Move up">↑</button>
            <button className="link" disabled={n === charts.length - 1} onClick={() => move(id, 1)} aria-label="Move down">↓</button>
          </div>
        ))}
        {!charts.length && <p className="small muted">None: tick some below.</p>}
      </div>
      <p className="small">
        <button className="link" onClick={() => setCharts(defaults)}>Back to the standard set</button>
        {" · "}<button className="link" onClick={() => { setCharts(defaults); setHidden([]); }}
          title="The standard charts and every card">Reset charts and cards</button>
        {" · "}<button className="link" onClick={() => setCharts([])}>Untick all</button>
      </p>

      <h4>Add charts</h4>
      <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search indicators (e.g. debt, wages, CO2)"
        aria-label="Search indicators" style={{ width: "100%" }} />
      <label className="small" style={{ display: "block", margin: "6px 0" }}>
        <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> Include indicators switched off on the Indicators page
      </label>
      <div className="picker-list scroll">
        {groups.map(([domain, xs]) => (
          <details key={domain} open={!!q.trim() || groups.length <= 3}>
            <summary className="small"><b>{domain}</b> <span className="muted">({xs.length})</span></summary>
            {xs.map((i) => (
              <label key={i.indicator_id} className="picker-row" title={i.description}>
                <input type="checkbox" checked={picked.has(i.indicator_id)} onChange={() => toggle(i.indicator_id)} />
                <span className="grow">{i.name}</span>
                <span className="muted small">{i.unit === "percent" ? "%" : i.unit}</span>
              </label>
            ))}
          </details>
        ))}
        {!groups.length && <p className="small muted">Nothing matches.</p>}
      </div>
    </aside>
  );
}

// Named set-ups: ready-made ones, and your own (saved in Settings, so every browser on this PC shares them).
function SavedSetups({ current, apply }: { current: { charts: string; hidden: string };
  apply: (p: { charts: string[] | string; hidden: string[] | string }) => void }) {
  const s = useSettings();
  const [name, setName] = useState("");
  const own = s.profile_saved ?? {};
  const store = (next: Record<string, { charts: string; hidden: string }>) => saveSettings({ profile_saved: next });
  return (
    <>
      <h4>Set-ups</h4>
      <div className="chips-row small">
        <span className="muted">Ready-made:</span>
        {READY.map((r) => <button key={r.name} className="chip" onClick={() => apply(r)} title={`Charts: ${r.charts.join(", ")}`}>{r.name}</button>)}
      </div>
      <div className="chips-row small">
        <span className="muted">Yours:</span>
        {Object.keys(own).map((n) => (
          <span key={n} className="chip">
            <button className="link" onClick={() => apply(own[n])} title="Use this set-up">{n}</button>
            {" "}<button className="link" aria-label={`Delete ${n}`} title="Delete" onClick={() => {
              const next = { ...own };
              delete next[n];
              store(next);
            }}>×</button>
          </span>
        ))}
        {!Object.keys(own).length && <span className="muted">none yet</span>}
      </div>
      <div className="chips-row small">
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Name this set-up" aria-label="Name for this set-up" maxLength={40} />
        <button disabled={!name.trim()} onClick={() => { store({ ...own, [name.trim()]: current }); setName(""); }}>Save as</button>
      </div>
    </>
  );
}
