"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import AskButton from "@/components/AskButton";
import { api, type NewsArticle, type NewsPreview, type WatchHit } from "@/lib/api";
import { useEntityNames } from "@/lib/flags";

// A news item on the map, opened large: the place, headline, picture, summary, related reports,
// when and where it came from, and the other news kept about the same country in the map's
// time window, stepped through with the arrows (or the arrow keys).
// Pictures and summaries come from the feeds; for the item on show, the article's own page is
// read once for the picture and summary it offers link previews (Settings > Briefing and the map: Read article pages).

const SOURCE_KIND: Record<string, string> = {
  feeds: "News feed", wikipedia: "Wikipedia Current events", reliefweb: "ReliefWeb (UN)", gdelt: "GDELT",
};

const previews = new Map<string, Promise<NewsPreview>>();
function previewOf(url: string): Promise<NewsPreview> {
  if (!previews.has(url)) {
    const p = api.newsPreview(url);
    p.catch(() => previews.delete(url));
    previews.set(url, p);
  }
  return previews.get(url)!;
}

const same = (a: NewsArticle, b: NewsArticle) => (!!a.url && a.url === b.url) || a.headline === b.headline;

// The article behind a map mark, then the other reports merged into it, then the rest of the country's news.
export function articlesFor(hit: WatchHit, more: NewsArticle[]): NewsArticle[] {
  const first: NewsArticle = {
    key: hit.key, source: hit.source ?? null, outlet: hit.outlet ?? hit.outlets[0] ?? null, date: hit.date, time: hit.time,
    headline: hit.headline, detail: hit.detail, url: hit.url, image: hit.image, tone: hit.tone, entities: hit.entities,
  };
  const out = [first];
  for (const a of [...(hit.articles ?? []), ...more]) if (!out.some((o) => same(o, a))) out.push(a);
  return out;
}

function when(a: NewsArticle): { day: string; utc: string | null; local: string | null } {
  const day = new Date(`${a.date}T12:00:00Z`).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  if (!a.time) return { day, utc: null, local: null };
  const t = new Date(a.time);
  if (Number.isNaN(t.getTime())) return { day, utc: null, local: null };
  return {
    day: t.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }),
    utc: t.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit", timeZone: "UTC" }),
    local: t.toLocaleString(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" }),
  };
}

const host = (u: string | null | undefined) => {
  try { return u ? new URL(u).hostname.replace(/^www\./, "") : ""; } catch { return ""; }
};

// "The Guardian, world" -> "GW": a stand-in picture for reports that came without one.
const initials = (s: string) => s.split(/[\s,]+/).filter((w) => w && !/^(the|of|and)$/i.test(w)).map((w) => w[0]).join("").slice(0, 3).toUpperCase();

export default function NewsPanel({ hit, start, end, onClose }: {
  hit: WatchHit; start: string; end: string; onClose: () => void;
}) {
  const name = useEntityNames();
  const [more, setMore] = useState<NewsArticle[] | null>(null);
  const [moreError, setMoreError] = useState<string | null>(null);
  const [idx, setIdx] = useState(0);
  const [pv, setPv] = useState<Record<string, NewsPreview>>({});
  const [badImg, setBadImg] = useState<Record<string, true>>({});

  useEffect(() => {
    let live = true;
    setIdx(0);
    setMore(null);
    setMoreError(null);
    api.newsAbout(hit.entity_id, start, end).then((r) => live && setMore(r.items))
      .catch((e) => live && (setMore([]), setMoreError(String(e.message || e))));
    return () => { live = false; };
  }, [hit.key, hit.entity_id, start, end]);

  const list = useMemo(() => articlesFor(hit, more ?? []), [hit, more]);
  const a = list[Math.min(idx, list.length - 1)];
  const p = a.url ? pv[a.url] : undefined;

  useEffect(() => {
    const url = a.url;
    if (!url || pv[url]) return;
    let live = true;
    previewOf(url).then((r) => live && setPv((m) => ({ ...m, [url]: r }))).catch(() => {});
    return () => { live = false; };
  }, [a.url]); // eslint-disable-line react-hooks/exhaustive-deps

  const go = (d: number) => setIdx((i) => (i + d + list.length) % list.length);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)) return;
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowRight") go(1);
      else if (e.key === "ArrowLeft") go(-1);
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }); // eslint-disable-line react-hooks/exhaustive-deps

  const picOf = (x: NewsArticle) => {
    const u = x.image || (x.url ? pv[x.url]?.image : undefined);
    return u && !badImg[u] ? u : null;
  };
  const pic = picOf(a);
  const detail = a.detail ?? "";
  const summary = p?.description && p.description.length > detail.length + 20 && a.source !== "wikipedia" ? p.description : detail;
  const wikiContext = a.source === "wikipedia" && detail ? detail : null;
  const wikiSummary = a.source === "wikipedia" ? p?.description : null;
  const t = when(a);
  // Wikipedia's line points at a news site's article: name that site once its page has been read.
  const outlet = a.source === "wikipedia" ? p?.site ?? host(a.url) ?? a.outlet : a.outlet ?? p?.site ?? null;
  const kind = a.source ? SOURCE_KIND[a.source] ?? a.source : null;
  const isFirst = idx === 0;
  const related = isFirst
    ? list.slice(1).filter((x) => (hit.articles ?? []).some((h) => same(h, x)) && x.url)
    : [];
  const place = hit.place ? `${hit.place.lat.toFixed(1)}, ${hit.place.lon.toFixed(1)}` : null;
  const country = name(hit.entity_id);
  const others = (a.entities ?? []).filter((e) => e !== hit.entity_id).slice(0, 4);

  return (
    <div className="news-panel" role="dialog" aria-label={`News: ${a.headline}`}>
      <div className="news-main">
        <div className="news-top">
          <div className="news-chips">
            <Link className="news-chip" href={`/entity/${hit.entity_id}`} title="This country's page">{country}</Link>
            {others.map((e) => <Link key={e} className="news-chip" href={`/entity/${e}`}>{name(e)}</Link>)}
            {isFirst && (place
              ? <span className="news-chip place" title={`Placed at ${hit.place!.name}, a city the report names`}>{hit.place!.name} · {place}</span>
              : <span className="news-chip place" title="No city named, so the mark sits at the country's centre">Country centre</span>)}
            {isFirst && hit.words.map((w) => <span key={w} className="news-chip word" title="Your watch word (Settings > Briefing and the map)">“{w}”</span>)}
            {isFirst && <span className={`news-chip ${hit.confirmed ? "good" : ""}`}
              title={hit.confirmed ? "A dataset holds a matching event" : "Reported in the news, not yet confirmed by a dataset"}>
              {hit.confirmed ? `Confirmed: ${hit.confirmed_by ?? "a dataset has it"}` : "Not yet confirmed"}</span>}
          </div>
          <div className="news-nav">
            <span className="small muted">{idx + 1} of {list.length}{more === null ? "…" : ""}</span>
            <button onClick={() => go(-1)} disabled={list.length < 2} aria-label="Previous article" title="Previous (←)">‹</button>
            <button onClick={() => go(1)} disabled={list.length < 2} aria-label="Next article" title="Next (→)">›</button>
            <button onClick={onClose} aria-label="Close" title="Close (Esc)">×</button>
          </div>
        </div>
        <h2 className="news-headline">
          {a.url ? <a href={a.url} target="_blank" rel="noreferrer">{a.headline}</a> : a.headline}
        </h2>
        {wikiSummary && p?.title && <p className="small muted" style={{ marginTop: -6 }}>Source article: {p.title}</p>}
        <div className={`news-body ${pic ? "" : "no-pic"}`}>
          {pic && <a className="news-pic" href={a.url ?? pic} target="_blank" rel="noreferrer">
            <img src={pic} alt="" referrerPolicy="no-referrer" loading="lazy" onError={() => setBadImg((m) => ({ ...m, [pic]: true }))} />
          </a>}
          <div className="news-text">
            {wikiContext && <p className="small muted">Part of: {wikiContext}</p>}
            {summary && !wikiContext && <p>{summary}</p>}
            {wikiSummary && <p>{wikiSummary}</p>}
            {!summary && !wikiSummary && <p className="muted">{a.url && !p ? "Reading the article's summary…"
              : p?.off ? "No summary came with this item (reading article pages is off in Settings)."
              : p?.error ? `No summary came with this item, and the article page could not be read (${p.error}).`
              : "No summary came with this item."}</p>}
            {related.length > 0 && (
              <details className="news-related">
                <summary>Also reported by ({related.length})</summary>
                <ul>{related.map((x) => (
                  <li key={x.key}><a href={x.url!} target="_blank" rel="noreferrer">{x.outlet ?? host(x.url)}</a>: {x.headline}</li>
                ))}</ul>
              </details>
            )}
            <div className="news-meta">
              <span title="Day of the report">{t.day}</span>
              {t.utc && <span title={`Your time: ${t.local}`}>{t.utc} UTC · {t.local} your time</span>}
              {outlet && <span className="news-chip" title="Who reported it">{outlet}</span>}
              {kind && kind !== outlet && <span className="news-chip kind" title="How the app found it">{kind}</span>}
              {a.url && <span className="muted">{host(a.url)}</span>}
            </div>
            <div className="news-actions">
              {a.url && <a className="news-open" href={a.url} target="_blank" rel="noreferrer">Open article ↗</a>}
              <Link className="link small" href={`/entity/${hit.entity_id}`}>{country}: country page</Link>
              <Link className="link small" href={`/discover?tab=news&entity=${hit.entity_id}`}>All news</Link>
              <AskButton title={a.headline} entity={hit.entity_id} parts={() => [{
                key: "news", kind: "page", label: "News item",
                text: `${a.headline}\n${a.outlet ?? ""} ${a.date}${a.url ? ` ${a.url}` : ""}\n${summary || wikiSummary || ""}`,
              }]} />
            </div>
          </div>
        </div>
      </div>
      <aside className="news-more">
        <h3>More about {country}</h3>
        <p className="small muted" style={{ margin: "0 0 6px" }}>{start} to {end}</p>
        {moreError && <p className="error small">{moreError}</p>}
        <ol>
          {list.map((x, i) => {
            const im = picOf(x);
            const w = when(x);
            return (
              <li key={x.key}>
                <button className={i === idx ? "on" : ""} onClick={() => setIdx(i)} aria-current={i === idx}>
                  {im ? <img src={im} alt="" referrerPolicy="no-referrer" loading="lazy" onError={() => setBadImg((m) => ({ ...m, [im]: true }))} />
                    : <span className="news-thumb">{initials(x.outlet ?? x.source ?? "?")}</span>}
                  <span className="news-more-text">
                    <span className="news-more-head">{x.headline}</span>
                    <span className="small muted">{w.day}{w.utc ? ` ${w.utc} UTC` : ""}{x.outlet ? ` · ${x.outlet}` : ""}</span>
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      </aside>
    </div>
  );
}
