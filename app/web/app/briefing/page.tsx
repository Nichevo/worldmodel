"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import BriefCard, { CardGroup } from "@/components/BriefCard";
import Flag from "@/components/Flag";
import { api, type BriefCard as Card, type Briefing } from "@/lib/api";
import { BRIEFING_SEEN, monthName } from "@/lib/briefing";
import { useSettings } from "@/lib/settings";

// The Briefing: what is new since the last refresh, in four lanes. Happening (CrisisWatch's
// month, news that names a watch word, events of the last days, top news), Found (Discover's
// best finds), Due (things coming up) and Yours (what you kept, and your key countries).
// Every item is the same card with the same buttons.
const DAYS: [number, string][] = [[1, "Today"], [7, "7 days"], [30, "30 days"]];

export default function BriefingPage() {
  const s = useSettings();
  const [b, setB] = useState<Briefing | null>(null);
  const [days, setDays] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fetching, setFetching] = useState(false);
  const load = (d: number | null) => api.briefing(d ?? undefined).then((x) => { setB(x); setError(null); return x; })
    .catch((e) => setError(String(e.message || e)));
  useEffect(() => {
    load(days).then((x) => {
      if (!x) return;
      try { window.localStorage.setItem(BRIEFING_SEEN, x.build_id); } catch { /* storage blocked */ }
    });
  }, [days]); // eslint-disable-line react-hooks/exhaustive-deps
  // Fetch the news (forced: even if it is not due), wait for it, look again for finds, reload the lanes.
  // The fetch runs in the background (GDELT alone takes a minute or more): ask every 5 s whether it
  // has finished, for up to 3 minutes, then reload the lanes once.
  const [step, setStep] = useState<string | null>(null);
  const refresh = (force: boolean, rescan: boolean) => {
    if (fetching) return;
    setFetching(true);
    setStep("Fetching news…");
    let tries = 0;
    const finish = async () => {
      if (rescan) { setStep("Looking again for finds…"); await api.discoverRescan().catch(() => undefined); }
      setStep("Reloading…");
      await load(days);
      setFetching(false);
      setStep(null);
    };
    const poll = () => api.newsFetch().then((st) => {
      if (st.running && ++tries < 36) setTimeout(poll, 5000);
      else finish();
    }).catch(() => finish());
    api.newsFetch(force).then(() => setTimeout(poll, 5000)).catch(() => finish());
  };
  // News is fetched when it is due (Settings > Discover: how often), then the lanes reload.
  useEffect(() => {
    if (b?.news_due && !fetching) refresh(false, false);
  }, [b?.news_due]); // eslint-disable-line react-hooks/exhaustive-deps

  if (error) return <p className="error">{error}</p>;
  if (!b) return <p className="muted">Loading…</p>;
  const by = (g: string | null) => b.lanes.happening.filter((c) => c.group === g);
  const cw = by("crisiswatch");
  const watch = by("watch");
  const news = by("news");
  const crowdMoves = by("crowd");
  const alerts = by("alert");
  const events = b.lanes.happening.filter((c) => c.kind === "event");
  const nothing = Object.values(b.lanes).every((l) => l.length === 0);
  return (
    <div className="briefing">
      <div className="title-row">
        <h1>Briefing</h1>
        <span className="muted small">since {b.since}</span>
        <div className="seg" role="group" aria-label="How far back">
          {DAYS.map(([d, label]) => (
            <button key={d} className={(days ?? b.days) === d ? "on" : ""} aria-pressed={(days ?? b.days) === d} onClick={() => setDays(d)}>{label}</button>
          ))}
        </div>
        <span className="spacer" />
        {fetching && <span className="muted small" role="status">{step ?? "Fetching news…"}</span>}
        <button className="small" disabled={fetching} onClick={() => refresh(true, true)}
          title="Fetch the news now, look again for finds, and reload the lanes. Data from the sources still comes from refresh.bat.">Refresh now</button>
        <Link href="/?w=30d" className="small">See it on the map</Link>
        <Link href="/settings#briefing" className="small muted" title="What the app opens on, how far back, watch words">Settings</Link>
      </div>
      {nothing && <p className="muted">Nothing new yet. Run <code>.\refresh.bat</code>, or open Discover &gt; News to fetch the news.</p>}
      <div className="brief-lanes">
        <section className="brief-lane" aria-label="Happening">
          <h2>Happening</h2>
          <CardGroup title={b.crisiswatch_month ? `CrisisWatch, ${monthName(b.crisiswatch_month)}` : "CrisisWatch"} cards={cw} names={b.names}
            note={<p className="caption">Situations that got worse, better or have a conflict risk alert this month. <Link href="/crisiswatch">The month on a map</Link></p>} />
          <CardGroup title="Reported in the news" cards={watch} names={b.names}
            note={<p className="caption">News naming a watch word (<Link href="/settings#watch-words">edit the words</Link>). Marked confirmed once a dataset has the event too.</p>} />
          <CardGroup title="Events" cards={events} names={b.names} />
          <CardGroup title="Top news" cards={news} names={b.names} />
          <CardGroup title="Your watchlist" cards={alerts} names={b.names}
            note={<p className="caption">Lines crossed, crowd chances that jumped, IMF forecasts revised. <Link href="/predictions?tab=watchlist">Edit the watchlist</Link></p>} />
          <CardGroup title="Crowd: biggest moves" cards={crowdMoves} names={b.names}
            note={<p className="caption">Questions on your key countries or that you follow, moving at least {s.crowd_move_points} points. <Link href="/crowd?tab=moves">All moves</Link></p>} />
          {!b.lanes.happening.length && <p className="muted small">Nothing in the last {b.days} days.</p>}
        </section>
        <Lane title="Found" cards={b.lanes.found} names={b.names} empty="No finds yet: Discover looks after each refresh." more={<Link href="/discover" className="small">All finds in Discover</Link>} />
        <Lane title="Due" cards={b.lanes.due} names={b.names} empty="Nothing dated in the next 60 days." compact
          more={<Link href="/predictions" className="small">Your predictions</Link>} />
        <section className="brief-lane" aria-label="Yours">
          <h2>Yours</h2>
          {b.key_countries.length > 0 && (
            <div className="brief-keys">
              <h3 className="brief-group-head">Latest on your key countries</h3>
              <div className="chips-row small">
                {b.key_countries.map((id) => (
                  <Link key={id} href={`/entity/${id}#latest`} className="chip"><Flag id={id} />{b.names[id] ?? id}</Link>
                ))}
              </div>
              <p className="caption">Key countries are set in Settings &gt; Discover.</p>
            </div>
          )}
          {b.lanes.yours.length > 0 && <h3 className="brief-group-head">Kept lately</h3>}
          {b.lanes.yours.map((c) => <BriefCard key={c.key} card={c} names={b.names} compact />)}
          <Link href="/highlights" className="small">All highlights</Link>
        </section>
      </div>
      {s.start_page !== "map" && (
        <p className="caption">The app opens here {s.start_page === "briefing" ? "every time" : "after each refresh"}; Settings &gt; Briefing changes that.</p>
      )}
    </div>
  );
}

function Lane({ title, cards, names, empty, more, compact = false }: { title: string; cards: Card[]; names: Record<string, string>; empty: string; more?: React.ReactNode; compact?: boolean }) {
  return (
    <section className="brief-lane" aria-label={title}>
      <h2>{title}</h2>
      {cards.length === 0 && <p className="muted small">{empty}</p>}
      {cards.map((c) => <BriefCard key={c.key} card={c} names={names} compact={compact} />)}
      {more}
    </section>
  );
}
