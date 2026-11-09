"use client";

import { useEffect, useMemo, useState } from "react";
import { GLOSSARY, glossaryGroups } from "@/lib/glossary";

// The glossary: short notes on the terms charts use, and how to read the charts. Each
// chart's "?" note links here when it uses one of these terms.
export default function GlossaryPage() {
  const [q, setQ] = useState("");
  const [hash, setHash] = useState("");
  useEffect(() => {
    const read = () => setHash(decodeURIComponent(location.hash.slice(1)));
    read();
    window.addEventListener("hashchange", read);
    return () => window.removeEventListener("hashchange", read);
  }, []);
  useEffect(() => { if (hash) document.getElementById(hash)?.scrollIntoView({ block: "center" }); }, [hash]);
  const words = q.trim().toLowerCase();
  const groups = useMemo(() => glossaryGroups().map((g) => ({ ...g, terms: g.terms.filter((t) =>
    !words || `${t.term} ${t.text}`.toLowerCase().includes(words)) })).filter((g) => g.terms.length), [words]);
  const name = Object.fromEntries(GLOSSARY.map((t) => [t.id, t.term]));
  return (
    <div className="grid">
      <div className="title-row">
        <h1>Glossary</h1>
        <span className="muted small">The terms the charts use, and how to read them</span>
      </div>
      <input type="search" placeholder="Find a term" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Find a term"
        style={{ maxWidth: 320 }} />
      {groups.map((g) => (
        <div className="card" key={g.group}>
          <h3>{g.group}</h3>
          <dl className="glossary">
            {g.terms.map((t) => (
              <div key={t.id} id={t.id} className={hash === t.id ? "here" : ""}>
                <dt>{t.term}</dt>
                <dd>{t.text}{t.see?.length ? <span className="muted"> See also: {t.see.map((s, i) => (
                  <span key={s}>{i ? ", " : ""}<a href={`#${s}`}>{name[s] ?? s}</a></span>))}.</span> : null}</dd>
              </div>
            ))}
          </dl>
        </div>
      ))}
      {!groups.length && <p className="muted">No term matches “{q}”.</p>}
    </div>
  );
}
