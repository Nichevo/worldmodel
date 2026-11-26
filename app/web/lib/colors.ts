// Chart colours come from CSS variables in globals.css, so light and dark
// mode each use their own validated steps. Read them at draw time.

import { useCallback, useSyncExternalStore } from "react";

export function cssVar(name: string): string {
  if (typeof window === "undefined") return "";
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

// Theme colours for markup (SVG fills, inline styles). cssVar() gives "" on the server and the
// real colour in the browser, so markup drawn with it during the first render does not match
// the server's and React reports a hydration error. useCss() hands out a reader that gives ""
// (so the fallbacks after `||` apply) until hydration is over, then the real colours, and
// draws again when light/dark mode changes. Charts drawn in effects can keep calling cssVar.
let themeVersion = 1;
const themeSubs = new Set<() => void>();
let themeWatching = false;
function watchTheme(onChange: () => void) {
  themeSubs.add(onChange);
  if (!themeWatching && typeof window !== "undefined") {
    themeWatching = true;
    const bump = () => { themeVersion += 1; themeSubs.forEach((f) => f()); };
    window.matchMedia?.("(prefers-color-scheme: dark)").addEventListener?.("change", bump);
    new MutationObserver(bump).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "class"] });
  }
  return () => { themeSubs.delete(onChange); };
}

/** 0 on the server and while hydrating; a number that changes with the theme afterwards. */
export function useThemeVersion(): number {
  return useSyncExternalStore(watchTheme, () => themeVersion, () => 0);
}

/** A cssVar() that is safe to call while rendering markup (see above). */
export function useCss(): (name: string) => string {
  const v = useThemeVersion();
  return useCallback((name: string) => (v ? cssVar(name) : ""), [v]);
}

export function seriesColor(i: number): string {
  return cssVar(`--series-${(i % 8) + 1}`);
}

// Seven-step sequential blue ramp (light to dark) for magnitudes.
export function sequentialRamp(): string[] {
  return [1, 2, 3, 4, 5, 6, 7].map((i) => cssVar(`--seq-${i}`));
}

// Diverging red (below zero) to blue (above zero) around a grey middle; the map
// drops the middle step so zero is a boundary, not a class.
export function divergingRamp(): string[] {
  return ["--div-neg-3", "--div-neg-2", "--div-neg-1", "--div-mid", "--div-pos-1", "--div-pos-2", "--div-pos-3"].map(cssVar);
}

// Indicators whose sign matters get a diverging scale centred on zero.
export const DIVERGING = new Set(["gdp_growth", "pop_growth_rate", "net_migration", "net_migration_rate"]);

// The same colour as a CSS reference, for markup rendered on the server too.
export function seriesVar(i: number): string {
  return `var(--series-${(i % 8) + 1})`;
}
