"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { api, type Entity } from "@/lib/api";

// Pick countries and whole groups (continents, regions, blocs, income groups): a box you
// can type in, with a drop-down list to browse when you don't know the name. Picks show as
// chips; a group stands for its member countries.
export type Place = { id: string; name: string; group: boolean };

const GROUP_TYPES: Record<string, string> = {
  world: "World", continent: "Continents", subregion: "Regions", intermediate_region: "Regions",
  bloc: "Blocs and alliances", alliance: "Blocs and alliances", group: "Blocs and alliances", income_group: "Income groups",
};
const SECTIONS = ["World", "Continents", "Regions", "Blocs and alliances", "Income groups", "Countries"];

let cache: Promise<Entity[]> | null = null;
const allEntities = () => (cache ??= api.entities().catch(() => { cache = null; return []; }));

export default function PlacePicker({ value, onChange, placeholder = "All countries" }:
  { value: Place[]; onChange: (p: Place[]) => void; placeholder?: string }) {
  const [list, setList] = useState<Entity[]>([]);
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const [at, setAt] = useState(0);
  const box = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => { allEntities().then(setList); }, []);
  useEffect(() => {
    const close = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const picked = new Set(value.map((p) => p.id));
  const options = useMemo(() => {
    const t = text.trim().toLowerCase();
    const hit = (e: Entity) => !t || e.short_name.toLowerCase().includes(t) || e.name.toLowerCase().includes(t)
      || (e.iso3 ?? "").toLowerCase() === t;
    const rank = (e: Entity) => (t && e.short_name.toLowerCase().startsWith(t) ? 0 : 1);
    const out: { section: string; e: Entity }[] = [];
    for (const section of SECTIONS) {
      const these = list.filter((e) => (section === "Countries" ? e.type === "country" : GROUP_TYPES[e.type] === section))
        .filter((e) => hit(e) && !picked.has(e.entity_id))
        .sort((a, b) => rank(a) - rank(b) || a.short_name.localeCompare(b.short_name));
      these.forEach((e) => out.push({ section, e }));
    }
    return out;
  }, [list, text, value]); // eslint-disable-line react-hooks/exhaustive-deps

  const add = (e: Entity) => {
    onChange([...value, { id: e.entity_id, name: e.short_name, group: e.type !== "country" && e.type !== "historical_country" }]);
    setText(""); setAt(0); input.current?.focus();
  };
  const key = (ev: React.KeyboardEvent) => {
    if (ev.key === "ArrowDown") { ev.preventDefault(); setOpen(true); setAt((i) => Math.min(i + 1, options.length - 1)); }
    else if (ev.key === "ArrowUp") { ev.preventDefault(); setAt((i) => Math.max(i - 1, 0)); }
    else if (ev.key === "Enter" && open && options[at]) { ev.preventDefault(); add(options[at].e); }
    else if (ev.key === "Escape") setOpen(false);
    else if (ev.key === "Backspace" && !text && value.length) onChange(value.slice(0, -1));
  };

  return (
    <div className="place-picker" ref={box}>
      <div className="place-box" onClick={() => { input.current?.focus(); setOpen(true); }}>
        {value.map((p) => (
          <span key={p.id} className={`chip place ${p.group ? "group" : ""}`} title={p.group ? "A group: its member countries' events" : undefined}>
            {p.name}
            <button className="link" aria-label={`Remove ${p.name}`} onClick={(e) => { e.stopPropagation(); onChange(value.filter((x) => x.id !== p.id)); }}>×</button>
          </span>
        ))}
        <input ref={input} value={text} placeholder={value.length ? "Add more" : placeholder} aria-label="Countries and groups"
          onChange={(e) => { setText(e.target.value); setOpen(true); setAt(0); }} onFocus={() => setOpen(true)} onKeyDown={key} />
        <button className="link caret" aria-label="Show the list" onClick={(e) => { e.stopPropagation(); setOpen(!open); input.current?.focus(); }}>▾</button>
      </div>
      {open && (
        <div className="place-list" role="listbox">
          {options.length === 0 && <div className="muted small" style={{ padding: 6 }}>Nothing matches.</div>}
          {options.map((o, i) => (
            <div key={o.e.entity_id}>
              {(i === 0 || options[i - 1].section !== o.section) && <div className="place-section">{o.section}</div>}
              <div role="option" aria-selected={i === at} className={`place-option ${i === at ? "on" : ""}`}
                onMouseEnter={() => setAt(i)} onMouseDown={(e) => { e.preventDefault(); add(o.e); }}>
                {o.e.short_name}{o.e.iso3 && o.section === "Countries" ? <span className="muted small"> {o.e.iso3}</span> : null}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
