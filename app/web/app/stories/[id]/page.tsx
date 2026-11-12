"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import StoryStep from "@/components/StoryStep";
import { api, type Indicator } from "@/lib/api";
import { logHistory } from "@/lib/history";
import { STORIES, storyById } from "@/stories";

// One story: a title band in its colour, then each step in turn, then where the figures come from.
// "Save as PDF" prints the whole story (the browser's print box saves a PDF).
export default function StoryPage() {
  const { id } = useParams<{ id: string }>();
  const story = storyById(id);
  const [inds, setInds] = useState<Map<string, Indicator> | null>(null);
  useEffect(() => {
    api.indicators().then((l) => setInds(new Map(l.map((i) => [i.indicator_id, i])))).catch(() => setInds(new Map()));
  }, []);
  useEffect(() => {
    if (story) logHistory({ kind: "page", title: story.title, url: `/stories/${story.id}`, detail: "story" });
  }, [story]);
  const next = useMemo(() => { const k = STORIES.findIndex((s) => s.id === id); return STORIES[(k + 1) % STORIES.length]; }, [id]);
  if (!story) return <p className="error">No story called {id}. <Link href="/stories">All stories</Link></p>;
  return (
    <article className="story" style={{ ["--story" as string]: story.colour }}>
      <header className="story-head">
        <p className="small muted" style={{ margin: 0 }}><Link href="/stories">Stories</Link></p>
        <h1 className="story-title">{story.title}</h1>
        <p className="story-blurb">{story.blurb}</p>
        <div className="story-tools no-print">
          <button onClick={() => window.print()} title="Opens the print box; choose Save as PDF to keep the whole story as one file">Save as PDF</button>
        </div>
      </header>
      {!inds ? <p className="muted">Loading…</p> : story.steps.map((s, i) => (
        <StoryStep key={i} step={s} i={i} total={story.steps.length} inds={inds} colour={story.colour} title={story.title} />
      ))}
      <footer className="story-foot">
        <p className="caption">Figures: {story.sources} Sentences are worked out from the figures each time the story opens.</p>
        {next && next.id !== story.id && <p className="no-print">Next story: <Link href={`/stories/${next.id}`}>{next.title} →</Link></p>}
      </footer>
    </article>
  );
}
