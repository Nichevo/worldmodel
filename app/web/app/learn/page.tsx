"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import IndicatorSelect from "@/components/IndicatorSelect";
import GuessDraw from "@/components/learn/GuessDraw";
import { api, type Entity, type Indicator, type LearnPage, type Quiz } from "@/lib/api";
import { formatValue } from "@/lib/format";
import { logHistory } from "@/lib/history";
import { setTour } from "@/lib/tour";

// Learn: draw your guess, a quiz made from the app's own figures, and guided tours round the app.
type Tab = "guess" | "quiz" | "tours";
const TABS: [Tab, string][] = [["guess", "Draw your guess"], ["quiz", "Quiz"], ["tours", "Guided tours"]];
const INTRO: Record<Tab, string> = {
  guess: "The line stops partway. Draw where you think it went, then see the real line and how close you came. Pick one of the ready-made charts or any country and figure.",
  quiz: "Questions made fresh from the figures in the app: which of two countries is higher, which of four is highest, did a figure go up or down. Every answer shows the real figures.",
  tours: "Short walks round the app. Each stop opens a page, points at a card and says what it shows; Back and Next sit at the bottom of the window.",
};

function LearnView() {
  const router = useRouter();
  const params = useSearchParams();
  const [tab, setTab] = useState<Tab>((params.get("tab") as Tab) || "guess");
  const [page, setPage] = useState<LearnPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const go = (t: Tab) => { setTab(t); router.replace(`/learn?tab=${t}`, { scroll: false }); };
  const reload = () => api.learn().then(setPage).catch((e) => setError(String(e.message || e)));
  useEffect(() => { reload(); logHistory({ kind: "page", title: "Learn", url: "/learn", detail: "page" }); }, []);
  if (error) return <div className="grid"><h1>Learn</h1><p className="error">{error}</p></div>;
  return (
    <div className="grid">
      <div className="title-row"><h1>Learn</h1></div>
      <div className="seg" role="tablist">{TABS.map(([t, label]) => <button key={t} role="tab" aria-selected={tab === t}
        className={tab === t ? "on" : ""} onClick={() => go(t)}>{label}</button>)}</div>
      <p className="ink-2" style={{ marginTop: 0, maxWidth: 860 }}>{INTRO[tab]}</p>
      {!page ? <p className="muted">Loading…</p> : <>
        {tab === "guess" && <GuessTab page={page} onScored={reload} />}
        {tab === "quiz" && <QuizTab page={page} onDone={reload} />}
        {tab === "tours" && <ToursTab page={page} />}
      </>}
    </div>
  );
}

function GuessTab({ page, onScored }: { page: LearnPage; onScored: () => void }) {
  const [i, setI] = useState(0);
  const [own, setOwn] = useState<{ entity: string; indicator: string; hide_from: number } | null>(null);
  const [countries, setCountries] = useState<Entity[]>([]);
  const [indicators, setIndicators] = useState<Indicator[]>([]);
  const [pick, setPick] = useState({ entity: "NZL", indicator: "pop_total", hide_from: 2000 });
  useEffect(() => {
    api.entities("country").then((x) => setCountries([...x].sort((a, b) => (a.short_name || a.name).localeCompare(b.short_name || b.name)))).catch(() => {});
    api.indicators().then(setIndicators).catch(() => {});
  }, []);
  const preset = page.guesses[i];
  const g = own ?? preset;
  const done = page.record.guesses;
  const mean = done.length ? Math.round(done.reduce((s, x) => s + x.score, 0) / done.length) : null;
  return (
    <div className="learn-cols">
      <div className="card">
        {g && <GuessDraw key={`${g.entity}-${g.indicator}-${g.hide_from}`} entity={g.entity} indicator={g.indicator} hideFrom={g.hide_from}
          ask={own ? undefined : preset?.ask} onScored={onScored} />}
        <div className="chips-row small" style={{ marginTop: 8 }}>
          {!own && <>
            <button disabled={i === 0} onClick={() => setI(i - 1)}>Previous chart</button>
            <span className="muted">{i + 1} of {page.guesses.length}</span>
            <button disabled={i >= page.guesses.length - 1} onClick={() => setI(i + 1)}>Next chart</button>
          </>}
          {own && <button className="link small" onClick={() => setOwn(null)}>Back to the ready-made charts</button>}
        </div>
      </div>
      <div className="card">
        <h3>Pick your own</h3>
        <div className="chips-row small">
          <label>Country{" "}
            <select value={pick.entity} onChange={(e) => setPick({ ...pick, entity: e.target.value })}>
              {countries.map((c) => <option key={c.entity_id} value={c.entity_id}>{c.short_name || c.name}</option>)}
            </select>
          </label>
          <IndicatorSelect indicators={indicators} value={pick.indicator} onChange={(id) => setPick({ ...pick, indicator: id })} />
          <label>Hide from{" "}
            <input type="number" min={1900} max={2030} value={pick.hide_from} style={{ width: 80 }}
              onChange={(e) => setPick({ ...pick, hide_from: +e.target.value })} />
          </label>
          <button onClick={() => setOwn({ ...pick })}>Draw it</button>
        </div>
        <h3>Your record</h3>
        {done.length ? <p className="small">{done.length} {done.length === 1 ? "chart" : "charts"} drawn, average score {mean} out of 100.
          Last: {done.slice(-5).reverse().map((x) => `${x.entity} ${x.indicator} ${x.score}`).join(", ")}.</p>
          : <p className="small muted">Nothing drawn yet. Scores are kept on this PC only.</p>}
      </div>
    </div>
  );
}

function QuizTab({ page, onDone }: { page: LearnPage; onDone: () => void }) {
  const [topic, setTopic] = useState("all");
  const [familiar, setFamiliar] = useState(true);
  const [quiz, setQuiz] = useState<Quiz | null>(null);
  const [at, setAt] = useState(0);
  const [picked, setPicked] = useState<string | null>(null);
  const [right, setRight] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const start = () => {
    setError(null); setAt(0); setPicked(null); setRight(0); setQuiz(null);
    api.quiz(topic === "all" ? undefined : topic, undefined, familiar).then(setQuiz).catch((e) => setError(String(e.message || e)));
  };
  useEffect(start, [topic, familiar]); // eslint-disable-line react-hooks/exhaustive-deps
  const q = quiz?.questions[at];
  const finished = !!quiz && at >= quiz.questions.length;
  useEffect(() => {
    if (finished && quiz?.questions.length) api.quizScore(topic, right, quiz.questions.length).then(onDone).catch(() => {});
  }, [finished]); // eslint-disable-line react-hooks/exhaustive-deps
  const rounds = page.record.quiz;
  const fmt = useMemo(() => (v: number | null) => (v == null || !q ? "" : formatValue(v, q.unit, q.decimals)), [q]);
  return (
    <div className="learn-cols">
      <div className="card quiz">
        <div className="chips-row small">
          <label>Topic{" "}
            <select value={topic} onChange={(e) => setTopic(e.target.value)}>
              <option value="all">Everything mixed</option>
              {page.topics.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </label>
          <label title="Off: every country of a million people or more"><input type="checkbox" checked={familiar}
            onChange={(e) => setFamiliar(e.target.checked)} /> Familiar countries only</label>
          <button className="link small" onClick={start}>New questions</button>
        </div>
        {error && <p className="error">{error}</p>}
        {quiz && !quiz.questions.length && <p className="muted">No questions could be made: the warehouse has too few figures for this topic yet.</p>}
        {q && <>
          <div className="small muted">Question {at + 1} of {quiz!.questions.length} · score {right}</div>
          <h3 className="quiz-q">{q.question}</h3>
          <div className="quiz-choices">
            {q.choices.map((c) => {
              const state = picked == null ? "" : c.id === q.answer ? "right" : c.id === picked ? "wrong" : "";
              return (
                <button key={c.id} className={`quiz-choice ${state}`} disabled={picked != null}
                  onClick={() => { setPicked(c.id); if (c.id === q.answer) setRight(right + 1); }}>
                  <span>{c.label}</span>
                  {picked != null && q.kind !== "risefall" && <span className="num">{fmt(c.value)}</span>}
                </button>
              );
            })}
          </div>
          {picked != null && <>
            <p className="small">
              <b>{picked === q.answer ? "Right." : "Not this time."}</b>{" "}
              {q.kind === "risefall" && q.values ? `It went from ${fmt(q.values[0][1])} in ${q.values[0][0]} to ${fmt(q.values[1][1])} in ${q.values[1][0]}.`
                : `${q.choices.find((c) => c.id === q.answer)?.label} had ${fmt(q.choices.find((c) => c.id === q.answer)?.value ?? null)} in ${q.year}.`}
              {" "}<a href={`/indicator/${q.indicator_id}`} className="muted">{q.indicator}</a>
              <span className="muted"> · source {q.source_id}</span>
            </p>
            <button className="primary" onClick={() => { setAt(at + 1); setPicked(null); }}>
              {at + 1 < quiz!.questions.length ? "Next question" : "See my score"}</button>
          </>}
        </>}
        {finished && quiz!.questions.length > 0 && <>
          <h3>{right} out of {quiz!.questions.length}</h3>
          <button className="primary" onClick={start}>Another round</button>
        </>}
      </div>
      <div className="card">
        <h3>Your rounds</h3>
        {rounds.length ? <table className="summary-table small"><tbody>
          {rounds.slice(-10).reverse().map((r) => <tr key={r.at}><td>{new Date(r.at).toLocaleString("en-NZ", { dateStyle: "medium", timeStyle: "short" })}</td>
            <td>{page.topics.find((t) => t.id === r.topic)?.name ?? "Everything mixed"}</td><td className="num">{r.right} / {r.asked}</td></tr>)}
        </tbody></table> : <p className="small muted">No rounds yet. Scores are kept on this PC only.</p>}
      </div>
    </div>
  );
}

function ToursTab({ page }: { page: LearnPage }) {
  const router = useRouter();
  return (
    <div className="cards-2">
      {page.tours.map((t) => (
        <div key={t.id} className="card">
          <h3>{t.name}</h3>
          <ol className="small ink-2">{t.stops.map((s, i) => <li key={i}>{s.text}</li>)}</ol>
          <button className="primary" onClick={() => { setTour({ tour: t, step: 0 }); router.push(t.stops[0].path); }}>Start the tour</button>
        </div>
      ))}
    </div>
  );
}

export default function LearnPageView() {
  return <Suspense><LearnView /></Suspense>;
}
