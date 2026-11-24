"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { STORY_GROUPS } from "@/lib/story";
import { STORIES } from "@/stories";

const KEEP = "wm.storyGroup";

// The Stories gallery: short visual stories built from the app's own figures, in groups.
export default function StoriesPage() {
  const [only, setOnly] = useState("");
  useEffect(() => { try { setOnly(window.localStorage.getItem(KEEP) ?? ""); } catch { /* storage blocked */ } }, []);
  const pick = (g: string) => { setOnly(g); try { window.localStorage.setItem(KEEP, g); } catch { /* kept for this visit */ } };
  const groups = STORY_GROUPS.map((g) => ({ ...g, stories: STORIES.filter((s) => s.group === g.id) })).filter((g) => g.stories.length);
  return (
    <div className="grid">
      <div>
        <h1>Stories</h1>
        <p className="ink-2" style={{ marginTop: 0, maxWidth: 760 }}>
          Short visual stories, each a few steps of one big chart or map and one sentence. The numbers come from your own data when
          you open a story, so each one updates itself after a refresh. Every story ends with where New Zealand sits.
        </p>
        <div className="chips-row small" role="group" aria-label="Show stories about">
          <button className={only === "" ? "on" : ""} aria-pressed={only === ""} onClick={() => pick("")}>All {STORIES.length}</button>
          {groups.map((g) => (
            <button key={g.id} className={only === g.id ? "on" : ""} aria-pressed={only === g.id} onClick={() => pick(g.id)}>{g.name} {g.stories.length}</button>
          ))}
        </div>
      </div>
      {groups.filter((g) => !only || g.id === only).map((g) => (
        <section key={g.id} className="story-group">
          <h2 className="story-group-title">{g.name}</h2>
          <div className="story-gallery">
            {g.stories.map((s) => (
              <Link key={s.id} href={`/stories/${s.id}`} className="story-card" style={{ ["--story" as string]: s.colour }}>
                <span className="story-band" />
                <span className="story-card-title">{s.title}</span>
                <span className="story-card-blurb">{s.blurb}</span>
                <span className="story-card-meta">{s.steps.length} steps</span>
              </Link>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
