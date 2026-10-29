// Chart colours come from CSS variables in globals.css, so light and dark
// mode each use their own validated steps. Read them at draw time.

export function cssVar(name: string): string {
  if (typeof window === "undefined") return "";
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
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
