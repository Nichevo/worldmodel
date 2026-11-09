// Shared bits of the Briefing: the build last seen there (so the app can open on the
// Briefing once after each refresh), and month names.

export const BRIEFING_SEEN = "wm.briefingBuild";

export function monthName(m: string): string {
  const [y, mo] = m.split("-").map(Number);
  return new Date(Date.UTC(y, mo - 1, 1)).toLocaleString("en-NZ", { month: "long", year: "numeric", timeZone: "UTC" });
}
