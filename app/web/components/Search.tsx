"use client";

import { useEffect, useRef, useState } from "react";
import { api, type SearchHit } from "@/lib/api";

type Props = {
  placeholder: string;
  kinds?: ("entity" | "indicator")[];
  onPick: (hit: SearchHit) => void;
};

// Type-ahead over entity and indicator names and synonyms (the API's /search).
export default function Search({ placeholder, kinds, onPick }: Props) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (q.trim().length < 2) {
      setHits([]);
      return;
    }
    const t = setTimeout(() => {
      api.search(q.trim())
        .then((r) => setHits(kinds ? r.filter((h) => kinds.includes(h.kind)) : r))
        .catch(() => setHits([]));
    }, 150);
    return () => clearTimeout(t);
  }, [q, kinds]);

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const pick = (h: SearchHit) => {
    onPick(h);
    setQ("");
    setOpen(false);
  };

  return (
    <div className="search" ref={box}>
      <input
        type="search"
        value={q}
        placeholder={placeholder}
        style={{ width: "100%" }}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" && hits[0]) pick(hits[0]);
        }}
        aria-label={placeholder}
      />
      {open && hits.length > 0 && (
        <div className="results" role="listbox">
          {hits.map((h) => (
            <button key={`${h.kind}:${h.id}`} onClick={() => pick(h)} role="option" aria-selected={false}>
              {h.name} <span className="muted small">{h.detail.replace("_", " ")}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
