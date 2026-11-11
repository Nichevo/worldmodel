"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import CardAsk from "@/components/CardAsk";
import NatureEvents from "@/components/NatureEvents";
import { LatestTable, latestText } from "@/components/PollutionCard";
import { api, type NatureCountry } from "@/lib/api";
import { openAsk } from "@/lib/ai";

// A country's nature: what is being lost (threatened species, the Red List Index, tree cover),
// what is arriving (introduced species, watched pests, animal disease), and what is recovering
// (protected land and sea, species coming back, restoration).

const LOSING = ["red_list_index", "red_list_index_owid", "iucn_threatened", "iucn_cr", "iucn_ex", "threatened_mammals", "threatened_birds",
  "threatened_fish_wdi", "threatened_plants_wdi", "tree_cover_loss"];
const ARRIVING = ["introduced_species", "watched_pests_present", "animal_disease_outbreaks"];
const RECOVERING = ["protected_land_share", "protected_sea_share", "protected_total_share", "kba_land_protected", "kba_fresh_protected",
  "kba_sea_protected", "forest_area_share"];
const CAT: Record<string, string> = { EX: "Extinct", EW: "Extinct in the wild", CR: "Critically endangered" };

export default function NatureCard({ entity, name, showLink = true }: { entity: string; name: string; showLink?: boolean }) {
  const [d, setD] = useState<NatureCountry | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    api.natureCountry(entity).then((r) => live && setD(r)).catch((e) => live && setError(String(e.message || e)));
    return () => { live = false; };
  }, [entity]);
  if (error) return <div className="card"><h3>Nature</h3><p className="error">{error}</p></div>;
  if (!d) return null;
  const has = (ids: string[]) => ids.some((i) => d.latest[i]);
  const pests = d.pests.filter((p) => p.here);
  if (showLink && !has([...LOSING, ...ARRIVING, ...RECOVERING]) && !d.events.length && !d.comebacks.length && !d.restoration.length) return null;
  const ask = () => openAsk({ title: `${name}: nature`, entity, parts: [
    { key: "data", kind: "data", label: "Latest nature figures", text: latestText([...LOSING, ...ARRIVING, ...RECOVERING], d.latest, d.names) },
    { key: "species", kind: "data", label: "Species named", text: d.species.map((s) => `${s.scientific_name}: ${CAT[s.category] ?? s.category}`).join("\n") },
    { key: "pests", kind: "data", label: "Watched pests", text: pests.map((p) => `${p.name}: ${p.here?.present ? "present" : "absent"} (${p.here?.statuses.join("; ")})`).join("\n") },
    { key: "events", kind: "data", label: "Disease and pest events", text: d.events.map((e) => `${e.start_date?.slice(0, 7)} ${e.title}`).join("\n") },
    { key: "recovering", kind: "description", label: "Comebacks and restoration",
      text: [...d.comebacks.map((c) => `${c.name}: from ${c.from} to ${c.to}. ${c.how}`), ...d.restoration.map((r) => `${r.name} (${r.start}): ${r.what}`)].join("\n") }] });
  return (
    <div className="card" id="nature-card">
      <div className="card-head"><h3>Nature</h3><span><CardAsk onAsk={ask} />{showLink ? <> <Link className="small" href={`/climate?tab=nature&country=${entity}`}>Nature tab</Link></> : null}</span></div>
      <div className="grid two">
        <div>
          <h4>Being lost</h4>
          <LatestTable ids={LOSING} latest={d.latest} names={d.names} />
          {d.species.length ? (
            <details><summary className="small">{d.species.length} species extinct or critically endangered here (IUCN)</summary>
              <ul className="small">{d.species.slice(0, 200).map((s) => <li key={s.scientific_name}>
                {s.url ? <a href={s.url} target="_blank" rel="noreferrer"><i>{s.scientific_name}</i></a> : <i>{s.scientific_name}</i>} · {CAT[s.category] ?? s.category}
                {s.year ? <span className="muted"> ({s.year})</span> : null}</li>)}</ul></details>
          ) : null}
        </div>
        <div>
          <h4>Arriving</h4>
          <LatestTable ids={ARRIVING} latest={d.latest} names={d.names} />
          {pests.length ? (
            <table className="small"><thead><tr><th>Watched pest</th><th>Here?</th></tr></thead>
              <tbody>{pests.map((p) => <tr key={p.code}><td title={p.note}>{p.name}</td>
                <td className={p.here?.present ? "neg" : ""}>{p.here?.statuses.join("; ")}</td></tr>)}</tbody></table>
          ) : <p className="small muted">Where watched pests are found comes from EPPO (needs EPPO_API_KEY; see Data status: Keys you can add).</p>}
        </div>
        <div>
          <h4>Recovering</h4>
          <LatestTable ids={RECOVERING} latest={d.latest} names={d.names} />
          {d.comebacks.length ? <ul className="nature-list small">{d.comebacks.map((c) => <li key={c.name}><a href={c.url} target="_blank" rel="noreferrer"><b>{c.name}</b></a>:
            from {c.from} to {c.to}. <span className="muted">{c.how}</span></li>)}</ul> : null}
          {d.restoration.length ? <ul className="nature-list small">{d.restoration.map((r) => <li key={r.name}><a href={r.url} target="_blank" rel="noreferrer"><b>{r.name}</b></a> ({r.start}): {r.what}</li>)}</ul> : null}
        </div>
        <div>
          <h4>Disease and pest arrivals</h4>
          <NatureEvents events={d.events} limit={15} />
        </div>
      </div>
    </div>
  );
}
