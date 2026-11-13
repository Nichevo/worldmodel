"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import CardAsk from "@/components/CardAsk";
import { openAsk } from "@/lib/ai";
import { CATEGORY_TEXT, crowdApi, type CrowdQ, pct, pred, type Prediction, type ScoreRow } from "@/lib/predictions";
import { useSettings } from "@/lib/settings";

// Crowd questions by topic: a card per topic with the busiest open questions, the crowd's odds as a
// bar, your own forecast as a gold mark when you made one, and the move this week; then your scorecard.

type Group = { id: string; name: string; qs: CrowdQ[] };

export function OddsRow({ q, mine }: { q: CrowdQ; mine?: number | null }) {
  const p = q.kind === "binary" ? q.chance : q.options?.[0]?.chance ?? null;
  const ch = q.change;
  return (
    <div className="odds-row">
      <Link href={`/crowd/question?key=${encodeURIComponent(q.question_key)}`}>{q.title}</Link>
      <div className="odds-line">
        <span className="odds-bar" title={q.kind === "binary" ? "The crowd's chance of yes" : `Leading option: ${q.options?.[0]?.name ?? ""}`}>
          <span style={{ width: `${(p ?? 0) * 100}%` }} />
          {mine != null && <i style={{ left: `${mine * 100}%` }} title={`Your forecast: ${pct(mine)}`} />}
        </span>
        <span className="mono strong">{pct(p)}</span>
        <span className={`mono small ${ch == null || ch === 0 ? "muted" : ch > 0 ? "tone-good" : "tone-bad"}`} title="Change over the last week">
          {ch == null ? "" : `${ch > 0 ? "▲" : ch < 0 ? "▼" : ""} ${Math.abs(Math.round(ch * 100))} pts`}</span>
      </div>
      <span className="small muted">{q.kind !== "binary" && q.options?.[0] ? `${q.options[0].name} leads · ` : ""}{q.site_name}
        {q.forecasters ? ` · ${q.forecasters.toLocaleString()} forecasters` : q.volume ? ` · $${Math.round(q.volume).toLocaleString()} traded` : ""}
        {q.closes ? ` · closes ${q.closes.slice(0, 10)}` : ""}</span>
    </div>
  );
}

export default function CrowdTopics({ onMore }: { onMore: (category: string, country: string) => void }) {
  const s = useSettings();
  const home = (s.discover_key_countries || "NZL").split(",")[0] || "NZL";
  const [cats, setCats] = useState<Record<string, string>>({});
  const [groups, setGroups] = useState<Group[] | null>(null);
  const [topic, setTopic] = useState("");
  const [homeName, setHomeName] = useState(home);
  const [mine, setMine] = useState<Map<string, number>>(new Map());
  const [loaded, setLoaded] = useState(true);
  useEffect(() => {
    pred.list({ who: "you" }).then((l) => setMine(new Map(l.items.filter((p) => p.crowd_key && p.chance != null).map((p) => [p.crowd_key!, p.chance!])))).catch(() => {});
  }, []);
  useEffect(() => {
    let live = true;
    crowdApi.list({ limit: 1 }).then(async (first) => {
      if (!live) return;
      setLoaded(first.loaded);
      setCats(first.categories);
      const want: [string, string, Record<string, string | number>][] = [
        [home, "", { country: home }], ...Object.keys(first.categories).map((c) => [c, first.categories[c] ?? CATEGORY_TEXT[c] ?? c, { category: c }] as [string, string, Record<string, string>])];
      const got = await Promise.all(want.map(([id, name, f]) => crowdApi.list({ ...f, status: "open", sort: "busy", limit: 4 })
        .then((l) => ({ id, name, qs: l.items })).catch(() => ({ id, name, qs: [] as CrowdQ[] }))));
      if (!live) return;
      const named = got.map((g) => (g.id === home ? { ...g, name: g.qs[0] ? homeName : home } : g));
      setGroups(named.filter((g) => g.qs.length));
    }).catch(() => setGroups([]));
    return () => { live = false; };
  }, [home]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    import("@/lib/api").then(({ api }) => api.entities()).then((l) => setHomeName(l.find((e) => e.entity_id === home)?.short_name ?? home)).catch(() => {});
  }, [home]);
  const shown = useMemo(() => (groups ?? []).map((g) => (g.id === home ? { ...g, name: homeName } : g)).filter((g) => !topic || g.id === topic), [groups, topic, home, homeName]);
  if (!loaded) return null;
  return (
    <>
      <div className="chips-row" role="group" aria-label="Topic">
        {[["", "All"], [home, homeName], ...Object.entries(cats)].map(([id, name]) => (
          <button key={id || "all"} className={`chip-btn${topic === id ? " on" : ""}`} aria-pressed={topic === id} onClick={() => setTopic(id)}>{name}</button>
        ))}
      </div>
      {!groups ? <p className="muted">Loading…</p> : (
        <div className="crowd-topics">
          {shown.map((g) => (
            <section key={g.id} className="card">
              <div className="card-head"><b>{g.name}</b>
                <span className="card-actions">
                  <CardAsk onAsk={() => openAsk({ title: `Crowd forecasts: ${g.name}`, parts: [{ key: g.id, kind: "data", label: "Questions, chance now, change this week",
                    text: g.qs.map((q) => `${q.title} | ${pct(q.chance)} | ${q.change ?? ""} | ${q.site_name}`).join("\n") }] })} />
                  <button className="link small" onClick={() => onMore(g.id === home ? "" : g.id, g.id === home ? home : "")}>More</button>
                </span></div>
              {g.qs.map((q) => <OddsRow key={q.question_key} q={q} mine={mine.get(q.question_key)} />)}
            </section>
          ))}
        </div>
      )}
      <p className="caption">Blue bar: the crowd&apos;s chance of yes. Gold mark: your own forecast, when you made one (Predict on the question&apos;s page). Right: the change in a week.</p>
      <Scorecard />
    </>
  );
}

function Scorecard() {
  const [rows, setRows] = useState<ScoreRow[] | null>(null);
  const [items, setItems] = useState<Prediction[]>([]);
  useEffect(() => {
    pred.scorecard().then((r) => setRows(r.rows)).catch(() => setRows([]));
    pred.list({ who: "you" }).then((l) => setItems(l.items)).catch(() => {});
  }, []);
  const you = rows?.find((r) => r.kind === "you");
  const crowd = rows?.filter((r) => r.kind === "crowd" && r.brier != null).sort((a, b) => b.brier_n - a.brier_n)[0];
  if (!you && !items.length) return null;
  const sure = you?.calibration.filter((c) => c.forecast >= 0.65 && c.n >= 3).sort((a, b) => b.n - a.n)[0];
  const month = new Date(Date.now() + 31 * 86_400_000).toISOString().slice(0, 10);
  const due = items.filter((p) => p.state !== "settled" && p.due <= month);
  const calib = sure ? (sure.observed < sure.forecast - 0.07 ? "Too sure" : sure.observed > sure.forecast + 0.07 ? "Not sure enough" : "Well judged") : "–";
  const tiles = [
    { label: "Settled", value: String(you?.settled ?? 0), note: `of ${you?.n ?? items.length} made` },
    { label: "Your Brier score", value: you?.brier != null ? you.brier.toFixed(2) : "–", note: `lower is better${crowd ? ` · ${crowd.name} ${crowd.brier!.toFixed(2)}` : ""}` },
    { label: "Calibration", value: calib, note: sure ? `your ${Math.round(sure.forecast * 100)}% calls came true ${Math.round(sure.observed * 100)}% of the time` : "needs a few more settled calls" },
    { label: "Due in the next month", value: String(due.length), note: due.slice(0, 3).map((p) => p.question.slice(0, 28)).join(", ") || "none" },
  ];
  return (
    <section className="card">
      <div className="card-head"><b>Your predictions · scorecard</b><Link className="small" href="/predictions">Open the log</Link></div>
      <div className="target-tiles">
        {tiles.map((t) => (
          <div key={t.label} className="htile score-tile">
            <span className="label">{t.label}</span><span className="value">{t.value}</span><span className="meta">{t.note}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
