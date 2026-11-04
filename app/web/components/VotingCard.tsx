"use client";

import CardAsk from "@/components/CardAsk";
import Help from "@/components/Help";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import EChart from "@/components/EChart";
import { api, type Voting } from "@/lib/api";
import { useSavePicture } from "@/lib/cards";
import { cardLinesOption, type CardLine } from "@/lib/charts";
import { seriesColor } from "@/lib/colors";
import { when } from "@/lib/events";
import { saveSettings, useSettings } from "@/lib/settings";

// UN voting: how often the country voted with the countries (and groups) chosen in
// Settings, its voting position over time, and its Security Council seats and vetoes.
export default function VotingCard({ entity, name }: { entity: string; name: string }) {
  const s = useSettings();
  const [data, setData] = useState<Voting | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"agree" | "ideal">("agree");
  const [adding, setAdding] = useState("");
  const { onReady, save, ask } = useSavePicture();
  useEffect(() => {
    let live = true;
    api.voting(entity, s.voting_compare).then((d) => live && setData(d)).catch((e) => live && setError(String(e.message || e)));
    return () => { live = false; };
  }, [entity, s.voting_compare]);

  const lines: CardLine[] = useMemo(() => {
    if (!data) return [];
    if (view === "ideal") return [{ key: "ideal", label: `${name}: voting position`, color: seriesColor(0), points: data.ideal.map(([y, v]) => [y, v, "E"]) }];
    return data.lines.filter((l) => l.points.length).map((l, i) => ({ key: l.id, label: l.name, color: seriesColor([0, 6, 4, 2, 1, 3, 5, 7][i % 8]),
      points: l.points.map(([y, v]) => [y, v, "E"] as [number, number, string]) }));
  }, [data, view, name]);
  const option = useCallback(() => cardLinesOption(lines, view === "ideal" ? { unit: "", decimals: 2, refY: { value: 0, label: "" } }
    : { unit: "% of votes alike", decimals: 0, max: 100 }), [lines, view]);

  if (error) return <div className="card"><h3>UN voting</h3><p className="error">{error}</p></div>;
  if (!data) return null;
  const vetoes = data.council.filter((e) => e.subkind === "veto");
  const seats = data.council.filter((e) => e.subkind === "council_seat");
  const resolutions = data.council.filter((e) => e.subkind === "resolution");
  if (!data.lines.some((l) => l.points.length) && !data.ideal.length && !data.council.length) return null;
  const partners = s.voting_compare.split(",").filter(Boolean);
  const title = view === "ideal" ? `UN voting position: ${name}` : `UN General Assembly votes alike with ${name}`;
  const note = view === "ideal" ? "Ideal point from UN General Assembly votes (Bailey, Strezhnev and Voeten); higher is closer to the United States."
    : "Share of recorded UN General Assembly votes on which both voted the same way (Voeten et al.).";
  const sources = ["unga_votes"];
  return (
    <div className="card" id="voting">
      <div className="card-head">
        <h3>UN voting <Help note="voting" /></h3>
        <CardAsk onAsk={() => ask(title, note, sources, entity)} />
        <button className="link small" title="Save this chart as a picture, with its sources" onClick={() => save(title, note, sources, "un-voting", entity)}>Save picture</button>
      </div>
      <div className="chips-row small">
        <div className="seg">
          <button className={view === "agree" ? "on" : ""} aria-pressed={view === "agree"} onClick={() => setView("agree")}>Votes alike</button>
          <button className={view === "ideal" ? "on" : ""} aria-pressed={view === "ideal"} onClick={() => setView("ideal")} disabled={!data.ideal.length}>Voting position</button>
        </div>
        {view === "agree" && (
          <span>
            Compared with{" "}
            {partners.map((p) => (
              <button key={p} className="chip" title="Remove (Settings: UN voting compared with)"
                onClick={() => saveSettings({ voting_compare: partners.filter((x) => x !== p).join(",") })}>{data.lines.find((l) => l.id === p)?.name ?? p} ×</button>
            ))}
            <input value={adding} onChange={(e) => setAdding(e.target.value)} placeholder="add: AUS, GBR, nato…" size={14}
              aria-label="Add a country or group to compare with"
              onKeyDown={(e) => {
                if (e.key !== "Enter" || !adding.trim()) return;
                saveSettings({ voting_compare: [...partners, ...adding.split(",").map((x) => x.trim()).filter(Boolean)].join(",") });
                setAdding("");
              }} />
          </span>
        )}
      </div>
      {lines.length > 0 ? <EChart option={option} height={280} label={title} onReady={onReady} />
        : <p className="small muted">No General Assembly votes stored yet; a refresh loads them.</p>}
      {view === "agree" && data.closest.length > 0 && (
        <p className="small">
          <b>Voted most like {name} in {data.closest_year}:</b>{" "}
          {data.closest.map((c, i) => <span key={c.entity_id}><Link href={`/entity/${c.entity_id}`}>{c.name}</Link> {Math.round(c.value)}%{i < data.closest.length - 1 ? ", " : ""}</span>)}
          {data.furthest.length > 0 && <><br /><b>Least like:</b>{" "}
            {data.furthest.map((c, i) => <span key={c.entity_id}><Link href={`/entity/${c.entity_id}`}>{c.name}</Link> {Math.round(c.value)}%{i < data.furthest.length - 1 ? ", " : ""}</span>)}</>}
        </p>
      )}
      {(seats.length > 0 || vetoes.length > 0 || resolutions.length > 0) && (
        <details>
          <summary className="small">
            Security Council: {seats.length ? `${seats.length} elected term${seats.length > 1 ? "s" : ""}` : ""}
            {seats.length && vetoes.length ? ", " : ""}{vetoes.length ? `${vetoes.length} veto${vetoes.length > 1 ? "es" : ""}` : ""}
            {resolutions.length ? `${seats.length || vetoes.length ? ", " : ""}${resolutions.length} resolution${resolutions.length > 1 ? "s" : ""} about it` : ""}
          </summary>
          <table className="small">
            <tbody>
              {[...data.council].reverse().slice(0, 80).map((e) => (
                <tr key={e.event_id}><td className="num" style={{ whiteSpace: "nowrap" }}>{when(e)}</td>
                  <td>{e.url ? <a href={e.url} target="_blank" rel="noreferrer">{e.title}</a> : e.title}{e.detail ? <span className="muted"> {e.detail}</span> : null}</td></tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
      <p className="caption">{note} Who it is compared with is kept in Settings for every country; eu, nato and other group ids show the average over their members.</p>
    </div>
  );
}
