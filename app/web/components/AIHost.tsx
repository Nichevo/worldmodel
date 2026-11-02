"use client";

import { useEffect, useRef, useState } from "react";
import AskAI from "@/components/AskAI";
import { keep, onToast, openAsk, type AskPart } from "@/lib/ai";
import type { NewHighlight } from "@/lib/api";
import { useSettings } from "@/lib/settings";

// Lives once in the layout: the Ask AI box, the short confirmations ("Kept in
// Highlights."), and the menu that appears over selected text (Settings: Local AI,
// "Menu on selected text").
export default function AIHost() {
  return (
    <>
      <AskAI />
      <HighlightMenu />
      <Toasts />
    </>
  );
}

function Toasts() {
  const [items, setItems] = useState<{ id: number; text: string }[]>([]);
  useEffect(() => onToast((text) => {
    const id = Date.now() + Math.random();
    setItems((xs) => [...xs.slice(-2), { id, text }]);
    setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), 3500);
  }), []);
  if (!items.length) return null;
  return <div className="toasts" role="status">{items.map((x) => <div key={x.id} className="toast">{x.text}</div>)}</div>;
}

// The country (or other entity) the page is about, from its address.
export function pageEntity(): string | undefined {
  const m = location.pathname.match(/^\/entity\/([^/]+)/);
  return m ? decodeURIComponent(m[1]) : undefined;
}

// The heading of the card (or page) the selection sits in, to name what it is from.
function headingFor(node: Node | null): string {
  let el: HTMLElement | null = node instanceof HTMLElement ? node : node?.parentElement ?? null;
  while (el) {
    if (el.classList.contains("card")) {
      const h = el.querySelector("h2, h3");
      if (h?.textContent) return h.textContent.replace(/\s*\?$/, "").trim();
    }
    el = el.parentElement;
  }
  return document.querySelector("main h1")?.textContent?.trim() || document.title;
}

function HighlightMenu() {
  const s = useSettings();
  const [at, setAt] = useState<{ x: number; y: number; text: string; from: string } | null>(null);
  const menu = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!s.highlight_menu) { setAt(null); return; }
    const up = (e: MouseEvent | KeyboardEvent) => {
      if (menu.current && e.target instanceof Node && menu.current.contains(e.target)) return;
      setTimeout(() => {
        const sel = window.getSelection();
        const text = sel?.toString().trim() ?? "";
        const anchor = sel?.anchorNode ?? null;
        const inside = anchor instanceof Node ? (anchor instanceof HTMLElement ? anchor : anchor.parentElement) : null;
        // Not inside the Ask AI box, form fields or the menu itself.
        if (!sel || sel.isCollapsed || text.length < 3 || !inside || inside.closest(".ask-ai, input, textarea, select, .hl-menu, nav")) {
          setAt(null);
          return;
        }
        const r = sel.getRangeAt(0).getBoundingClientRect();
        setAt({ x: Math.min(window.innerWidth - 220, Math.max(8, r.left + r.width / 2 - 100)), y: r.top > 48 ? r.top - 40 : r.bottom + 8,
          text: text.slice(0, 20_000), from: headingFor(anchor) });
      }, 0);
    };
    const hide = () => setAt(null);
    document.addEventListener("mouseup", up);
    document.addEventListener("keyup", up);
    window.addEventListener("scroll", hide, true);
    return () => {
      document.removeEventListener("mouseup", up);
      document.removeEventListener("keyup", up);
      window.removeEventListener("scroll", hide, true);
    };
  }, [s.highlight_menu]);

  if (!at) return null;
  const entity = pageEntity();
  const parts: AskPart[] = [
    { key: "highlight", kind: "highlight", label: `Highlighted text (from "${at.from}")`, text: at.text },
    { key: "page", kind: "page", label: "Page", text: `${document.title}: ${at.from}` },
  ];
  const item: NewHighlight = { kind: "text", title: at.from, text: at.text, entities: entity ? [entity] : [] };
  return (
    <div ref={menu} className="hl-menu" style={{ left: at.x, top: at.y }} role="menu">
      {s.ai_enabled && <button role="menuitem" onClick={() => { openAsk({ title: at.from, parts, entity }); setAt(null); }}>Ask AI</button>}
      <button role="menuitem" onClick={async () => { await keep(item); setAt(null); window.getSelection()?.removeAllRanges(); }}>Save highlight</button>
    </div>
  );
}
