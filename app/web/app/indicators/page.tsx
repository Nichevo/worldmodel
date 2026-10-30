"use client";

import { Fragment, useEffect, useMemo, useState } from "react";
import ChartCard from "@/components/ChartCard";
import Ratios from "@/components/Ratios";
import WorldMap from "@/components/WorldMap";
import { api, type Indicator } from "@/lib/api";
import { DIVERGING } from "@/lib/colors";
import { SOURCE_SHORT } from "@/lib/format";
import { logHistory } from "@/lib/history";

// Every indicator from every source, with a switch for whether it appears in the
// panel menus. Details and a preview (map and world chart) open under each row.
// Switched-off indicators keep their data; they are only hidden from menus.
const PAGE = 150;
const WORLD = [{ id: "world", name: "World" }];

export default function IndicatorsPage() {
  const [all, setAll] = useState<Indicator[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [domain, setDomain] = useState("");
  const [source, setSource] = useState("");
  const [state, setState] = useState<"" | "on" | "off" | "nodata">("");
  const [open, setOpen] = useState<string | null>(null);
  const [shown, setShown] = useState(PAGE);
  const [busy, setBusy] = useState(false);

  const load = () => api.indicators().then(setAll).catch((e) => setError(String(e.message || e)));
  useEffect(() => { load(); }, []);

  const domains = useMemo(() => [...new Set((all ?? []).map((i) => i.domain))].sort(), [all]);
  const sources = useMemo(() => [...new Set((all ?? []).flatMap((i) => i.sources.map((s) => s.source_id)))].sort(), [all]);
  const list = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (all ?? []).filter((i) =>
      (!domain || i.domain === domain) &&
      (!source || i.sources.some((s) => s.source_id === source)) &&
      (state === "" || (state === "on" ? i.enabled : state === "off" ? !i.enabled : !i.available)) &&
      (!needle || [i.name, i.indicator_id, i.description, ...i.synonyms].join(" ").toLowerCase().includes(needle)));
  }, [all, q, domain, source, state]);
  useEffect(() => setShown(PAGE), [q, domain, source, state]);

  const flip = async (changes: Record<string, boolean>) => {
    setBusy(true);
    setAll((cur) => cur?.map((i) => (i.indicator_id in changes ? { ...i, enabled: changes[i.indicator_id] } : i)) ?? cur);
    try {
      await api.switchIndicators(changes);
      const ids = Object.keys(changes);
      const on = Object.values(changes).filter(Boolean).length;
      const name = ids.length === 1 ? (all?.find((i) => i.indicator_id === ids[0])?.name ?? ids[0]) : `${ids.length} indicators`;
      logHistory({ kind: "indicator", title: `${on ? "Switched on" : "Switched off"} ${name}`, url: "/indicators",
        indicator: ids.length === 1 ? ids[0] : undefined });
    } catch (e) {
      setError(String((e as Error).message || e));
      load();
    } finally {
      setBusy(false);
    }
  };
  const flipAll = (on: boolean) => {
    const targets = list.filter((i) => i.enabled !== on);
    if (!targets.length) return;
    if (!window.confirm(`Switch ${on ? "on" : "off"} the ${targets.length} indicators listed?`)) return;
    flip(Object.fromEntries(targets.map((i) => [i.indicator_id, on])));
  };
  const reset = async () => {
    if (!window.confirm("Put every indicator back to its default switch?")) return;
    await api.resetIndicators().catch((e) => setError(String(e.message || e)));
    load();
  };

  const onCount = (all ?? []).filter((i) => i.enabled).length;
  return (
    <div className="grid">
      <div>
        <h1>Indicators</h1>
        <p className="ink-2" style={{ marginTop: 0 }}>
          {all ? `${all.length} indicators, ${onCount} switched on.` : "Loading…"} Switched-on indicators appear in the panel menus;
          switching one off only hides it there, its data stays. Click a row for details and a preview.
        </p>
      </div>
      {all && <Ratios indicators={all} changed={(id) => { load(); if (id) { setDomain("Your ratios"); setOpen(id); } }} />}
      <div className="controls">
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search names and descriptions" aria-label="Search indicators" style={{ width: 260 }} />
        <select value={domain} onChange={(e) => setDomain(e.target.value)} aria-label="Topic">
          <option value="">All topics</option>
          {domains.map((d) => <option key={d} value={d}>{d[0].toUpperCase() + d.slice(1)}</option>)}
        </select>
        <select value={source} onChange={(e) => setSource(e.target.value)} aria-label="Source">
          <option value="">All sources</option>
          {sources.map((s) => <option key={s} value={s}>{SOURCE_SHORT[s] ?? s}</option>)}
        </select>
        <select value={state} onChange={(e) => setState(e.target.value as typeof state)} aria-label="Switch">
          <option value="">On and off</option>
          <option value="on">Switched on</option>
          <option value="off">Switched off</option>
          <option value="nodata">No data loaded</option>
        </select>
        <span className="spacer" />
        <button className="small" disabled={busy} onClick={() => flipAll(true)}>All listed on</button>
        <button className="small" disabled={busy} onClick={() => flipAll(false)}>All listed off</button>
        <button className="small link" onClick={reset}>Reset to defaults</button>
      </div>
      {error && <p className="error">{error}</p>}
      <div className="card">
        <div className="table-scroll">
          <table className="indicators">
            <thead>
              <tr>
                <th>On</th><th>Indicator</th><th>Topic</th><th>Unit</th><th>Years</th><th>Latest estimate</th>
                <th className="num">Countries</th><th>Source</th>
              </tr>
            </thead>
            <tbody>
              {list.slice(0, shown).map((i) => {
                const isOpen = open === i.indicator_id;
                const src = i.sources[0];
                return (
                  <Fragment key={i.indicator_id}>
                    <tr className="clickable" onClick={() => setOpen(isOpen ? null : i.indicator_id)} aria-expanded={isOpen}>
                      <td onClick={(e) => e.stopPropagation()}>
                        <input type="checkbox" checked={i.enabled} onChange={(e) => flip({ [i.indicator_id]: e.target.checked })}
                          aria-label={`Show ${i.name} in menus`} disabled={busy} />
                      </td>
                      <td><b>{i.name}</b>{i.default_on !== i.enabled && <span className="small muted"> (changed)</span>}
                        {i.breakdowns && <div className="small muted">by {i.breakdowns.replace(/\|/g, ", ")}; shown in pyramids</div>}</td>
                      <td>{i.domain}</td>
                      <td className="small">{i.unit}</td>
                      <td className="nowrap">{i.first_year !== null ? `${i.first_year}–${i.last_year}` : <span className="muted">no data</span>}</td>
                      <td>{i.last_estimate_year ?? "–"}</td>
                      <td className="num">{i.countries || "–"}</td>
                      <td className="small">{src ? (src.source_name ?? SOURCE_SHORT[src.source_id] ?? src.source_id) : "–"}
                        {i.sources.length > 1 && <span className="muted"> +{i.sources.length - 1}</span>}</td>
                    </tr>
                    {isOpen && (
                      <tr className="detail">
                        <td colSpan={8}><Details indicator={i} /></td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
        {list.length > shown && (
          <p className="small"><button onClick={() => setShown(shown + PAGE)}>Show more</button> <span className="muted">{shown} of {list.length} shown</span></p>
        )}
        {all && list.length === 0 && <p className="muted">No indicators match.</p>}
      </div>
    </div>
  );
}

function Details({ indicator: i }: { indicator: Indicator }) {
  const year = i.last_estimate_year ?? i.last_year;
  const [values, setValues] = useState<{ entity_id: string; value: number; status: string }[]>([]);
  useEffect(() => {
    if (year === null || i.breakdowns) return;
    api.map(i.indicator_id, year).then(setValues).catch(() => setValues([]));
  }, [i.indicator_id, year, i.breakdowns]);
  return (
    <div className="indicator-detail">
      <div>
        <p style={{ marginTop: 0 }}>{i.description || <span className="muted">No description.</span>}</p>
        <dl className="facts small">
          <dt>Id</dt><dd><code>{i.indicator_id}</code></dd>
          <dt>Unit</dt><dd>{i.unit}{i.decimals !== undefined ? `, ${i.decimals} decimals` : ""}</dd>
          <dt>Regions and blocs</dt><dd>{i.agg_method ? `computed from countries (${i.agg_method})` : "as published"}</dd>
          {i.synonyms.length > 0 && <><dt>Also called</dt><dd>{i.synonyms.join(", ")}</dd></>}
          {i.sources.map((s) => (
            <Fragment key={s.source_id}>
              <dt>{s.rank === 1 ? "Source" : `Source ${s.rank}`}</dt>
              <dd>{s.source_name ?? s.source_id}: series <code>{s.series}</code>{s.licence ? `. Licence: ${s.licence}` : ""}{s.notes ? `. ${s.notes}` : ""}</dd>
            </Fragment>
          ))}
        </dl>
      </div>
      {i.available && !i.breakdowns && year !== null && (
        <div className="previews">
          <div className="preview-map">
            <WorldMap values={values} unit={i.unit} decimals={i.decimals} diverging={DIVERGING.has(i.indicator_id)} onPick={() => {}} />
            <p className="caption">{year}, {values.length} countries.</p>
          </div>
          <ChartCard indicator={i} entities={WORLD} height={200} />
        </div>
      )}
    </div>
  );
}
