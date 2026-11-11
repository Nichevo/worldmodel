"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import AskButton from "@/components/AskButton";
import CrowdRow from "@/components/CrowdRow";
import EChart from "@/components/EChart";
import Flag from "@/components/Flag";
import PredictDialog from "@/components/PredictDialog";
import { toast } from "@/lib/ai";
import { logHistory } from "@/lib/history";
import { callText, CATEGORY_TEXT, chanceOption, crowdApi, type CrowdComment, type CrowdDetail, pct, pred } from "@/lib/predictions";

// One crowd question: its chance over time (the site's own history and the app's saves), your
// Metaculus forecasts, events in its countries, comments, the same question on other sites,
// Follow / Hide / Watch, and Add as a prediction.

function QuestionView() {
  const key = useSearchParams().get("key") ?? "";
  const [q, setQ] = useState<CrowdDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [sort, setSort] = useState<"new" | "votes">("votes");
  const load = useCallback(() => crowdApi.question(key).then((x) => { setQ(x); setError(null); }).catch((e) => setError(String(e.message || e))), [key]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (q) logHistory({ kind: "page", title: q.title, url: `/crowd/question?key=${key}`, detail: "crowd question" }); }, [q?.question_key]); // eslint-disable-line react-hooks/exhaustive-deps
  const option = useCallback(() => (q ? chanceOption(q) : {}), [q]);
  const comments = useMemo(() => {
    const list = [...(q?.comment_list ?? [])];
    list.sort((a, b) => (sort === "votes" ? (b.votes ?? 0) - (a.votes ?? 0) : (b.created ?? "").localeCompare(a.created ?? "")));
    const top = list.filter((c) => !c.parent_id || !list.some((p) => p.comment_id === c.parent_id));
    const kids = (id: string) => list.filter((c) => c.parent_id === id);
    return { top, kids };
  }, [q, sort]);
  if (error) return <p className="error">{error}</p>;
  if (!q) return <p className="muted">Loading…</p>;
  const follow = (body: { follow?: boolean; hide?: boolean }) => crowdApi.follow(q.question_key, body).then(load);
  const watch = () => pred.addWatch({ kind: "crowd", question_key: q.question_key }).then(() => toast("Added to your watchlist")).catch((e) => toast(String(e.message || e)));
  const binary = q.kind === "binary";
  return (
    <div className="grid sector-page">
      <div className="title-row"><h1 style={{ fontSize: "1.4rem" }}>{q.title}</h1></div>
      <div className="chips-row small">
        <span className="big-number">{binary ? pct(q.chance) : q.kind === "numeric" ? (q.chance == null ? "–" : Number(q.chance.toPrecision(4))) : ""}</span>
        <span className="muted">{q.site_name} · {q.status}{q.resolution ? ` (${q.resolution})` : ""}{q.closes ? ` · closes ${q.closes.slice(0, 10)}` : ""}
          {q.forecasters ? ` · ${q.forecasters.toLocaleString()} forecasters` : ""}{q.volume ? ` · $${Math.round(q.volume).toLocaleString()} traded` : ""}
          {q.category ? ` · ${CATEGORY_TEXT[q.category] ?? q.category}` : ""}</span>
        {q.countries.map((c) => <Link key={c} href={`/entity/${c}#crowd`} className="chip"><Flag id={c} />{c}</Link>)}
        {q.indicator_id && <Link href={`/indicator/${q.indicator_id}`} className="chip">{q.indicator_id}</Link>}
      </div>
      <div className="chips-row small">
        <button onClick={() => follow({ follow: !q.followed })} title="Followed questions get their full history and comments read at each refresh, and their moves show on the Briefing">
          {q.followed ? "Unfollow" : "Follow"}</button>
        <button onClick={() => follow({ hide: !q.hidden })} title="Hidden questions leave the lists and country cards (a wrong country match, or not interesting)">
          {q.hidden ? "Unhide" : "Hide"}</button>
        {binary && <button onClick={watch}>Watch for big moves</button>}
        <button onClick={() => setAdding(true)}>Add as a prediction</button>
        {q.url && <a href={q.url} target="_blank" rel="noreferrer">Open on {q.site_name}</a>}
        <AskButton className="small" title={`Crowd question: ${q.title}`} parts={() => [
          { key: "description", kind: "description", label: "The question", text: `${q.title}\n\n${q.description ?? ""}`.slice(0, 4000) },
          { key: "data", kind: "data", label: "Chance over time", text: q.points.map((p) => `${p.at.slice(0, 10)} ${pct(p.chance)} (${p.origin})`).join("\n") },
          { key: "events", kind: "events", label: "Events in its countries", text: q.events.map((e) => `${e.start_date} ${e.entity_id}: ${e.title}`).join("\n") },
          { key: "notes", kind: "notes", label: "Comments", text: q.comment_list.slice(0, 30).map((c) => `${c.author}${c.forecast != null ? ` (forecast ${pct(c.forecast)})` : ""}: ${c.text.slice(0, 400)}`).join("\n\n") },
        ]} />
      </div>
      {q.options && q.options.length > 0 && !binary && (
        <div className="card"><h3>Options</h3><ul className="small">{q.options.map((o) => <li key={o.name}>{o.name}: {pct(o.chance)}</li>)}</ul></div>
      )}
      <div className="card">
        <h3>{binary ? "Chance of yes over time" : "Over time"}</h3>
        {q.points.length ? <EChart option={option} height={320} label="Chance over time" /> : <p className="muted">No saved chances yet.</p>}
        <p className="caption">Solid: the site&apos;s own history (read for followed and busy questions). Dashed: the chance the app saved at each refresh (only when it moved,
          or once a week). {q.mine.length ? "Dots: your Metaculus forecasts. " : ""}{q.events.length ? "Triangles: events in its countries since the question opened." : ""}</p>
      </div>
      {q.predictions.length > 0 && (
        <div className="card"><h3>In your log</h3><ul className="small">{q.predictions.map((p) => <li key={p.id}>{p.who}: {callText(p)}, made {p.made}
          {p.outcome ? `, ${p.score?.hit ? "right" : "wrong"}` : ""} <Link href="/predictions">log</Link></li>)}</ul></div>
      )}
      {q.description && <details className="card"><summary>What counts (the resolution rules)</summary><p className="small" style={{ whiteSpace: "pre-wrap" }}>{q.description}</p></details>}
      {q.similar.length > 0 && (
        <div className="card"><h3>The same question elsewhere</h3><div className="crowd-list">{q.similar.map((s) => <CrowdRow key={s.question_key} q={s} />)}</div>
          <p className="caption">Other sites&apos; questions on the same countries with the most words in common; check the rules match before comparing.</p></div>
      )}
      {q.events.length > 0 && (
        <div className="card"><h3>Events in {q.countries.join(", ")} since it opened</h3>
          <ul className="small">{q.events.slice(0, 15).map((e) => <li key={e.event_id}>{e.start_date} <Flag id={e.entity_id} /> {e.title}</li>)}</ul></div>
      )}
      <div className="card">
        <div className="card-head"><h3>Comments {q.comment_list.length ? <span className="muted small">{q.comment_list.length}</span> : null}</h3>
          {q.comment_list.length > 0 && <span className="seg small">
            <button className={sort === "votes" ? "on" : ""} onClick={() => setSort("votes")}>Most votes</button>
            <button className={sort === "new" ? "on" : ""} onClick={() => setSort("new")}>Newest</button></span>}</div>
        {!q.comment_list.length ? <p className="muted small">{q.site === "metaculus"
          ? "No comments read yet: they are read for followed and much-discussed questions at each refresh (Settings > Predictions)."
          : `${q.site_name} comments are not read; open the question on ${q.site_name} to see them.`}</p> : (
          comments.top.slice(0, 40).map((c) => <Comment key={c.comment_id} c={c} kids={comments.kids} />)
        )}
        {q.comment_list.length > 0 && <p className="caption">A comment&apos;s forecast is the author&apos;s own forecast on the question when they wrote it. Metaculus does not
          share authors&apos; track records, so a strong record cannot be shown beside a name.</p>}
      </div>
      {adding && <PredictDialog title="Add as a prediction" onClose={() => setAdding(false)} onSaved={load}
        initial={{ question: q.title, kind: binary ? "binary" : "number", who_kind: "crowd", who: q.site_name, chance: binary ? q.chance ?? undefined : undefined,
          value: !binary ? q.chance : undefined, due: (q.closes ?? "").slice(0, 10) || undefined, crowd_key: q.question_key, link: q.url,
          category: q.category, entity: q.countries[0] ?? null, indicator: q.indicator_id }} />}
    </div>
  );
}

function Comment({ c, kids }: { c: CrowdComment; kids: (id: string) => CrowdComment[] }) {
  const replies = kids(c.comment_id);
  return (
    <div className={`comment${c.parent_id ? " reply" : ""}`}>
      <div className="small"><b>{c.author}</b> <span className="muted">{c.created?.slice(0, 10)}{c.votes ? ` · ${c.votes} votes` : ""}</span>
        {c.forecast != null && <span className="chip small" title="The author's forecast when they wrote it"> forecast {pct(c.forecast)}</span>}</div>
      <div className="small" style={{ whiteSpace: "pre-wrap" }}>{c.text}</div>
      {replies.map((r) => <Comment key={r.comment_id} c={r} kids={kids} />)}
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<p className="muted">Loading…</p>}><QuestionView /></Suspense>;
}
