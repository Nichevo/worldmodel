"use client";

import { useEffect, useState } from "react";
import { api, type Texts, type WikiImage, type Wikipedia } from "@/lib/api";

// The Wikipedia introduction and pictures (fetched once a month at most, within the
// daily limit in Settings) and the Wikidata facts box for a country.
export default function CountryAbout({ entity }: { entity: string }) {
  const [wiki, setWiki] = useState<Wikipedia | null>(null);
  const [facts, setFacts] = useState<Texts | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setWiki(null);
    setFacts(null);
    setError(null);
    api.wikipedia(entity).then(setWiki).catch((e) => setError(String(e.message || e)));
    api.texts(entity, "wikidata").then(setFacts).catch(() => setFacts(null));
  }, [entity]);

  const page = wiki?.page;
  const factFields = facts?.sections.find((s) => s.section === "Facts")?.fields ?? [];
  const links = facts?.sections.find((s) => s.section === "Links")?.fields ?? [];
  const item = links.find((l) => l.field_key === "item")?.content;
  if (!wiki && !error) return <div className="card"><h3>About</h3><p className="muted small">Loading…</p></div>;
  if (!page && factFields.length === 0) {
    return wiki?.message || error ? <p className="small ink-2">{wiki?.message ?? error}</p> : null;
  }
  const photo = page?.images.find((i) => i.role === "photo" && i.src);
  const small = page?.images.filter((i) => i.role !== "photo" && i.src) ?? [];

  return (
    <div className="card about">
      <div className="about-text">
        <h3>About{page?.description ? <span className="small ink-2"> · {page.description}</span> : null}</h3>
        {page ? (
          <>
            {page.extract.split(/\n+/).filter(Boolean).map((p, i) => <p key={i}>{p}</p>)}
            <p className="caption">
              {page.url && <><a href={page.url} target="_blank" rel="noreferrer">Read more on Wikipedia</a> · </>}
              {page.licence} · copy from {page.fetched_at.slice(0, 10)}, refreshed monthly
              {wiki?.status === "stale" ? " (due for a refresh)" : ""}
            </p>
          </>
        ) : (
          <p className="small ink-2">{wiki?.message ?? error ?? "No Wikipedia introduction stored yet."}</p>
        )}
        {wiki?.message && page && <p className="caption">{wiki.message}</p>}
      </div>
      <div className="about-side">
        {photo && <Picture img={photo} wide />}
        {small.length > 0 && <div className="about-small">{small.map((i) => <Picture key={i.role} img={i} />)}</div>}
        {factFields.length > 0 && (
          <>
            <dl className="facts-box">
              {factFields.map((f) => (
                <div key={f.field_key}>
                  <dt>{f.field}</dt>
                  <dd>{f.field_key === "P856" ? <a href={f.content.split("; ")[0]} target="_blank" rel="noreferrer">{f.content.split("; ")[0]}</a> : f.content}</dd>
                </div>
              ))}
            </dl>
            <p className="caption">
              Facts from {item ? <a href={`https://www.wikidata.org/wiki/${item}`} target="_blank" rel="noreferrer">Wikidata</a> : "Wikidata"} (CC0), updated monthly.
            </p>
          </>
        )}
      </div>
    </div>
  );
}

const ROLE: Record<string, string> = { photo: "", flag: "Flag", map: "Location" };

function Picture({ img, wide }: { img: WikiImage; wide?: boolean }) {
  const credit = [img.artist, img.licence].filter(Boolean).join(" · ");
  return (
    <figure className={wide ? "about-photo" : "about-thumb"}>
      <img src={img.src!} alt={ROLE[img.role] || img.file} loading="lazy" />
      <figcaption className="caption">
        {ROLE[img.role] ? `${ROLE[img.role]} · ` : ""}
        {img.page_url ? <a href={img.page_url} target="_blank" rel="noreferrer">{credit || "Wikimedia Commons"}</a> : credit}
      </figcaption>
    </figure>
  );
}
