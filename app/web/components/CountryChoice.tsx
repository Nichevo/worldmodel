"use client";

import { useEffect, useState } from "react";
import { api, type Entity } from "@/lib/api";

// One country: a box you can type in, with the whole list to pick from.
let cache: Promise<Entity[]> | null = null;
const countries = () => (cache ??= api.entities().then((l) => l.filter((e) => e.type === "country")
  .sort((a, b) => a.short_name.localeCompare(b.short_name))).catch(() => { cache = null; return []; }));

export default function CountryChoice({ value, onChange, label = "Country" }: { value: string; onChange: (id: string) => void; label?: string }) {
  const [list, setList] = useState<Entity[]>([]);
  const [text, setText] = useState("");
  useEffect(() => { countries().then(setList); }, []);
  useEffect(() => { setText(list.find((e) => e.entity_id === value)?.short_name ?? value); }, [value, list]);
  const pick = (t: string) => {
    setText(t);
    const hit = list.find((e) => e.short_name.toLowerCase() === t.trim().toLowerCase() || e.entity_id === t.trim().toUpperCase());
    if (hit && hit.entity_id !== value) onChange(hit.entity_id);
  };
  return (
    <label>{label}{" "}
      <input list="country-choice" value={text} onChange={(e) => pick(e.target.value)} onFocus={(e) => e.target.select()}
        style={{ width: 170 }} aria-label={label} />
      <datalist id="country-choice">{list.map((e) => <option key={e.entity_id} value={e.short_name} />)}</datalist>
    </label>
  );
}
