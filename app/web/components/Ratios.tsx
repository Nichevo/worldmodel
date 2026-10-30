"use client";

import { useEffect, useState } from "react";
import Search from "@/components/Search";
import { api, type Indicator, type Ratio } from "@/lib/api";

// Your own ratios: one indicator divided by another (times 100, 1,000...), country
// by country and year by year. Each becomes an indicator like any other, under the
// topic "Your ratios", kept only on this computer (var\user\ratios.json).
const MULTIPLIERS = [1, 100, 1000, 1e6];
const EMPTY = { name: "", numerator: "", denominator: "", multiplier: 1, unit: "", decimals: 2, description: "" };

export default function Ratios({ indicators, changed }: { indicators: Indicator[]; changed: (id?: string) => void }) {
  const [list, setList] = useState<Ratio[]>([]);
  const [form, setForm] = useState<typeof EMPTY | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const names = new Map(indicators.map((i) => [i.indicator_id, i]));
  const load = () => api.ratios().then(setList).catch(() => setList([]));
  useEffect(() => { load(); }, []);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form) return;
    try {
      const r = editing ? await api.changeRatio(editing, form) : await api.addRatio(form);
      setForm(null);
      setEditing(null);
      setError(null);
      await load();
      changed(r.id);
    } catch (err) {
      setError(String((err as Error).message || err));
    }
  };
  const remove = async (r: Ratio) => {
    if (!window.confirm(`Delete your ratio "${r.name}"? Charts and layouts that use it will show nothing for it.`)) return;
    await api.deleteRatio(r.id).catch((e) => setError(String(e.message || e)));
    await load();
    changed();
  };
  const part = (k: "numerator" | "denominator", label: string) => {
    const ind = form && form[k] ? names.get(form[k]) : undefined;
    return (
      <label className="small">{label}
        <div className="ratio-part">
          {ind ? <span className="chip">{ind.name}{ind.unit ? <span className="muted"> · {ind.unit}</span> : null}
            <button type="button" aria-label={`Change the ${label.toLowerCase()}`} onClick={() => setForm({ ...form!, [k]: "" })}>×</button></span>
            : <Search placeholder="Find an indicator" kinds={["indicator"]}
              onPick={(h) => !h.id.startsWith("my_") && setForm((f) => (f ? { ...f, [k]: h.id } : f))} />}
        </div>
      </label>
    );
  };
  const formula = (r: { numerator: string; denominator: string; multiplier: number }) =>
    `${names.get(r.numerator)?.name ?? r.numerator} ÷ ${names.get(r.denominator)?.name ?? r.denominator}${r.multiplier !== 1 ? ` × ${r.multiplier.toLocaleString()}` : ""}`;

  return (
    <div className="card" id="ratios">
      <div className="card-head">
        <h3>Your ratios <span className="small ink-2">· {list.length}</span></h3>
        {!form && <button className="small" onClick={() => { setForm({ ...EMPTY }); setEditing(null); }}>Make a ratio</button>}
      </div>
      {list.length === 0 && !form && (
        <p className="small ink-2">Divide one indicator by another, such as household debt by GDP or military spending by education spending.
          The result works on maps, charts, tables, scatters and pictures like any other indicator.</p>
      )}
      {list.length > 0 && (
        <table className="small">
          <tbody>
            {list.map((r) => (
              <tr key={r.id}>
                <td><b>{r.name}</b>{r.unit ? <span className="muted"> · {r.unit}</span> : null}</td>
                <td className="ink-2">{formula(r)}</td>
                <td className="num">
                  <button className="link" onClick={() => { setForm({ ...EMPTY, ...r }); setEditing(r.id); }}>Edit</button>
                  {" · "}<button className="link" onClick={() => remove(r)}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {form && (
        <form className="ratio-form" onSubmit={save}>
          <label className="small">Name
            <input required maxLength={80} value={form.name} placeholder="Household debt to GDP" onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </label>
          {part("numerator", "Top (divided)")}
          {part("denominator", "Bottom (divided by)")}
          <label className="small">Times
            <select value={MULTIPLIERS.includes(form.multiplier) ? form.multiplier : "other"}
              onChange={(e) => setForm({ ...form, multiplier: e.target.value === "other" ? 10 : +e.target.value })}>
              {MULTIPLIERS.map((m) => <option key={m} value={m}>{m.toLocaleString()}{m === 100 ? " (a percentage)" : ""}</option>)}
              <option value="other">Other…</option>
            </select>
            {!MULTIPLIERS.includes(form.multiplier) && (
              <input type="number" step="any" value={form.multiplier} onChange={(e) => setForm({ ...form, multiplier: +e.target.value })} aria-label="Multiplier" />
            )}
          </label>
          <label className="small">Unit
            <input maxLength={30} value={form.unit} placeholder="% of GDP" onChange={(e) => setForm({ ...form, unit: e.target.value })} />
          </label>
          <label className="small">Decimals
            <input type="number" min={0} max={6} value={form.decimals} onChange={(e) => setForm({ ...form, decimals: +e.target.value })} />
          </label>
          {form.numerator && form.denominator && <p className="small ink-2">{formula(form)}, for each country and year where both have a value.</p>}
          <div>
            <button type="submit" disabled={!form.name || !form.numerator || !form.denominator}>{editing ? "Save changes" : "Make it"}</button>
            {" "}<button type="button" className="link" onClick={() => { setForm(null); setEditing(null); setError(null); }}>Cancel</button>
          </div>
          {error && <p className="error small">{error}</p>}
        </form>
      )}
      <p className="caption">Kept only on this computer (var\user\ratios.json). Each part uses its first-ranked source; a projection on
        either side makes the ratio a projection. Pictures credit both sources.</p>
    </div>
  );
}
