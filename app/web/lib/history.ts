// The history log: what was opened and looked at, kept by the API in the user
// folder (never sent anywhere else). The API ignores entries while history is
// paused in Settings, and folds a repeat of the last entry into it.

import { api, type HistoryKind } from "@/lib/api";

const recent = new Map<string, number>(); // key -> time logged, so re-renders don't log twice

export function logHistory(entry: { kind: HistoryKind; title: string; url?: string; entity?: string; indicator?: string; detail?: string }) {
  const key = `${entry.kind}|${entry.url ?? ""}|${entry.title}`;
  const now = Date.now();
  if (now - (recent.get(key) ?? 0) < 60_000) return;
  recent.set(key, now);
  api.logHistory(entry).catch(() => {});
}
