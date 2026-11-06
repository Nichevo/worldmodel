"use client";

import { useState } from "react";
import { api, GRADE_TEXT, TYPE_TEXT, type Grade, type IndicatorQuality, type QualityScore } from "@/lib/api";
import { setStar } from "@/lib/quality";

export const SCORE_TEXT: Record<QualityScore, string> = {
  history: "History", up_to_date: "Up to date", coverage: "Coverage", standing: "Source standing",
  health: "Dataset health", definition: "Standard or exploratory",
};
export const SCORE_ORDER: QualityScore[] = ["history", "up_to_date", "coverage", "standing", "health", "definition"];

// A grade badge with six small bars (one per score); hovering says why each score is what it is.
export function QualityBadge({ q }: { q: IndicatorQuality | undefined }) {
  if (!q) return null;
  const why = SCORE_ORDER.map((k) => `${SCORE_TEXT[k]}: ${q.scores[k]} of 5. ${q.notes[k]}`).join("\n");
  return (
    <span title={`Grade ${q.grade} (${GRADE_TEXT[q.grade]})${q.overridden ? `, set by you (worked out: ${q.worked_grade})` : ""}\n${why}`}>
      <span className={`grade grade-${q.grade}`}>{q.grade}{q.overridden ? "*" : ""}</span>
      <span className="qbars" aria-hidden>
        {SCORE_ORDER.map((k) => <span key={k} style={{ height: `${(q.scores[k] / 5) * 100}%` }} />)}
      </span>
    </span>
  );
}

// The Quality card on an indicator's page (and under its row on the Indicators page): each
// score with its reason, the grade, a star, and a choice to set the grade yourself.
export function QualityCard({ id, q, changed }: { id: string; q: IndicatorQuality | undefined; changed?: (q: IndicatorQuality) => void }) {
  const [cur, setCur] = useState<IndicatorQuality | undefined>(q);
  const [error, setError] = useState<string | null>(null);
  const shown = cur ?? q;
  if (!shown) return null;
  const save = async (change: { grade?: Grade | null; starred?: boolean }) => {
    try {
      if (change.starred !== undefined) {
        await setStar(id, change.starred); // also tells the drop-downs
        const next = { ...shown, starred: change.starred };
        setCur(next);
        changed?.(next);
        return;
      }
      const next = await api.setQuality(id, change);
      setCur(next);
      changed?.(next);
    } catch (e) {
      setError(String((e as Error).message || e));
    }
  };
  return (
    <div className="card">
      <div className="card-head">
        <h3>Quality: grade <span className={`grade grade-${shown.grade}`}>{shown.grade}</span> {GRADE_TEXT[shown.grade].toLowerCase()}</h3>
        <button className="isel-star" aria-pressed={shown.starred} onClick={() => save({ starred: !shown.starred })}
          title="A starred indicator stays in every drop-down whatever its grade">{shown.starred ? "★ Starred" : "☆ Star"}</button>
      </div>
      <table className="small">
        <tbody>
          {SCORE_ORDER.map((k) => (
            <tr key={k}>
              <td>{SCORE_TEXT[k]}</td>
              <td style={{ width: 90 }}><span className="qbars" style={{ height: 10 }}>
                {[1, 2, 3, 4, 5].map((n) => <span key={n} style={{ height: "100%", opacity: n <= shown.scores[k] ? 0.9 : 0.15 }} />)}
              </span> {shown.scores[k]}</td>
              <td className="muted">{shown.notes[k]}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="small">
        Measured as: {TYPE_TEXT[shown.type]}. Grade{" "}
        <select value={shown.overridden ? shown.grade : ""} onChange={(e) => save({ grade: (e.target.value || null) as Grade | null })}
          aria-label="Set the grade yourself">
          <option value="">as worked out ({shown.worked_grade})</option>
          {(Object.keys(GRADE_TEXT) as Grade[]).map((g) => <option key={g} value={g}>{g}: {GRADE_TEXT[g]} (set by you)</option>)}
        </select>
        {" "}<span className="muted">Yours stays through refreshes.</span>
      </p>
      <p className="caption">Worked out at each refresh from the figures held: source standing and the standard-or-exploratory score count most,
        then history and how up to date, then coverage and the checks. New, pilot or rough figures are never graded above C.</p>
      {error && <p className="error small">{error}</p>}
    </div>
  );
}
