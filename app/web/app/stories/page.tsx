"use client";

import Link from "next/link";
import { STORIES } from "@/stories";

// The Stories gallery: short visual stories built from the app's own figures.
export default function StoriesPage() {
  return (
    <div className="grid">
      <div>
        <h1>Stories</h1>
        <p className="ink-2" style={{ marginTop: 0, maxWidth: 760 }}>
          Short visual stories, each a few steps of one big chart or map and one sentence. The numbers come from your own data when
          you open a story, so each one updates itself after a refresh. Every story ends with where New Zealand sits.
        </p>
      </div>
      <div className="story-gallery">
        {STORIES.map((s) => (
          <Link key={s.id} href={`/stories/${s.id}`} className="story-card" style={{ ["--story" as string]: s.colour }}>
            <span className="story-band" />
            <span className="story-card-title">{s.title}</span>
            <span className="story-card-blurb">{s.blurb}</span>
            <span className="story-card-meta">{s.steps.length} steps</span>
          </Link>
        ))}
      </div>
    </div>
  );
}
