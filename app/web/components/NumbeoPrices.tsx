"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api, type NumbeoPrices as Prices } from "@/lib/api";

// Numbeo's prices for one city or country (meal out, rent, transport, groceries,
// salary...), fetched only when the button is pressed and within the daily limit in
// Settings. The copy is kept; "Fetch again" spends another of the day's fetches.
export default function NumbeoPrices({ kind, id, place }: { kind: "cities" | "entities"; id: string; place: string }) {
  const [data, setData] = useState<Prices | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");

  useEffect(() => {
    setData(null); setError(null);
    api.numbeo(kind, id).then((d) => { setData(d); setName(d.name); }).catch((e) => setError(String(e.message || e)));
  }, [kind, id]);

  const sections = useMemo(() => {
    const out = new Map<string, { item: string; value: number }[]>();
    for (const it of data?.prices?.items ?? []) {
      if (!out.has(it.section)) out.set(it.section, []);
      out.get(it.section)!.push(it);
    }
    return [...out];
  }, [data]);

  const fetchNow = async () => {
    setBusy(true); setError(null);
    try {
      const d = await api.fetchNumbeo(kind, id, name.trim() || undefined);
      setData(d);
    } catch (e) {
      setError(String((e as Error).message || e).replace(/^\d+: /, ""));
    } finally { setBusy(false); }
  };

  const b = data?.budget;
  const p = data?.prices;
  const left = b ? Math.max(0, b.limit - b.used) : 0;
  const usd = (v: number) => `$${v.toLocaleString(undefined, { maximumFractionDigits: v < 100 ? 2 : 0 })}`;
  return (
    <div className="numbeo">
      {p ? (
        <>
          {(p.summary.single_without_rent || p.summary.family_without_rent) && (
            <div className="ind-facts">
              {p.summary.single_without_rent ? <div><b>One person, a month</b>{usd(p.summary.single_without_rent)} without rent</div> : null}
              {p.summary.family_without_rent ? <div><b>Family of four, a month</b>{usd(p.summary.family_without_rent)} without rent</div> : null}
            </div>
          )}
          <div className="numbeo-sections">
            {sections.map(([section, items]) => (
              <section key={section}>
                <h4>{section || "Prices"}</h4>
                <table className="summary-table">
                  <tbody>{items.map((it) => <tr key={it.item}><td>{it.item}</td><td className="num">{usd(it.value)}</td></tr>)}</tbody>
                </table>
              </section>
            ))}
          </div>
          <p className="caption">
            Numbeo, prices in US dollars, crowd-sourced; <a href={p.url} target="_blank" rel="noreferrer">page</a> fetched {p.fetched_at.slice(0, 10)}. <Link href="/prices">Compare with other places you have fetched</Link>.
          </p>
        </>
      ) : (
        <p className="small ink-2">
          Numbeo&apos;s list of everyday prices for {place} (a meal out, a cappuccino, rent, a monthly transport pass, salary)
          is fetched only when you ask, one page at a time.
        </p>
      )}
      <div className="chips-row small">
        <button disabled={busy || !b || left === 0} onClick={fetchNow}>
          {busy ? "Fetching…" : p ? "Fetch again from Numbeo" : "Get Numbeo prices"}
        </button>
        {b && <span className="muted">{left} of today&apos;s {b.limit} Numbeo fetches left (Settings)</span>}
      </div>
      {error && (
        <div className="small">
          <p className="error" style={{ marginBottom: 4 }}>{error}</p>
          <label className="muted">Numbeo&apos;s name for it, if different:{" "}
            <input value={name} onChange={(e) => setName(e.target.value)} style={{ width: 200 }} /></label>
        </div>
      )}
    </div>
  );
}
