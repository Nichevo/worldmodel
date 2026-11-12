"use client";

import { useEffect, useRef, useState } from "react";

export type MoreItem = { label: string; onClick: () => void; title?: string; on?: boolean; hidden?: boolean };

// The "…" button that holds a card's less-used actions (forecast, predict, keep, save, copy),
// so a card shows only Ask AI and this. Closes on a pick, a click elsewhere or Escape.
export default function MoreMenu({ items, label = "More actions" }: { items: MoreItem[]; label?: string }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", esc); };
  }, [open]);
  const shown = items.filter((i) => !i.hidden);
  if (!shown.length) return null;
  return (
    <span className="more" ref={box}>
      <button className="small" aria-label={label} title={label} aria-expanded={open} aria-haspopup="menu" onClick={() => setOpen(!open)}>…</button>
      {open && (
        <span className="more-menu" role="menu">
          {shown.map((i) => (
            <button key={i.label} role="menuitem" className={i.on ? "on" : ""} title={i.title} aria-pressed={i.on}
              onClick={() => { setOpen(false); i.onClick(); }}>{i.label}</button>
          ))}
        </span>
      )}
    </span>
  );
}
