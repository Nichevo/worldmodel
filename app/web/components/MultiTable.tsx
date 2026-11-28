"use client";

// A table of countries (rows) against any number of figures (columns), sortable by any column,
// with selected countries kept on top, optional tinting of each cell by where it stands in its
// column, and a small menu on each heading. It knows nothing of panels or indicators: give it
// TableColumns (lib/tablecols: useTableColumns loads them for indicators) and it draws them,
// so other pages and query results can use it too.
import { useMemo, useState } from "react";
import Flag from "@/components/Flag";
import { formatValue } from "@/lib/format";
import type { Cell, TableColumn } from "@/lib/tablecols";

export type TableSort = { by: string; desc: boolean }; // by: a column key, or "name"

export type TableModel = {
  columns: TableColumn[]; rows: string[]; ranks: Map<string, number>; sort: TableSort; setSort: (s: TableSort) => void;
  sortCol: TableColumn | undefined;
};

// Sorted rows and ranks for some columns. Rows are every entity any column has a figure for
// (or `only`, when given); blanks sort last; `first` (selected countries) go on top in that order.
export function useTableModel(columns: TableColumn[], names: Map<string, string>, opts: { first?: string[]; only?: string[] } = {}): TableModel {
  const [sort, setSort] = useState<TableSort>({ by: "", desc: true });
  const sortCol = columns.find((c) => c.key === sort.by) ?? (sort.by === "name" ? undefined : columns[0]);
  const { first = [], only } = opts;
  const rows = useMemo(() => {
    const ids = only ? [...only] : [...new Set(columns.flatMap((c) => [...c.values.keys()]))];
    const name = (id: string) => names.get(id) ?? id;
    const dir = sort.desc ? -1 : 1;
    ids.sort((a, b) => {
      if (!sortCol) return dir * name(a).localeCompare(name(b));
      const va = sortCol.values.get(a)?.value, vb = sortCol.values.get(b)?.value;
      if (va === undefined || vb === undefined) return va === undefined ? (vb === undefined ? name(a).localeCompare(name(b)) : 1) : -1;
      return dir * (va - vb);
    });
    if (first.length) ids.sort((a, b) => Number(first.includes(b)) - Number(first.includes(a)));
    return ids;
  }, [columns, names, sort.desc, sortCol, first.join(","), only?.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps
  const ranks = useMemo(() => {
    if (!sortCol) return new Map<string, number>();
    const ranked = [...sortCol.values.entries()].sort((a, b) => (sort.desc ? b[1].value - a[1].value : a[1].value - b[1].value));
    return new Map(ranked.map(([id], i) => [id, i + 1]));
  }, [sortCol, sort.desc]);
  return { columns, rows, ranks, sort: { by: sortCol?.key ?? "name", desc: sort.desc }, setSort, sortCol };
}

// A cell as text: the figure in its unit, a sign on changes, "*" for a projection, and the year
// when it is not the column's own (a gap filled from an earlier year).
export function cellText(c: TableColumn, v: Cell | undefined, withYear = true): string {
  if (v === undefined) return "–";
  const unit = c.unit === "points" ? "" : c.unit;
  const sign = c.change && v.value > 0 ? "+" : "";
  return `${sign}${formatValue(v.value, unit, c.decimals)}${c.change && c.unit === "points" ? " pts" : ""}${v.status === "P" ? " *" : ""}${withYear && v.year ? ` (${v.year})` : ""}`;
}

// Where each figure stands in its column, 0 (lowest) to 1 (highest), for tinting.
function standing(c: TableColumn): Map<string, number> {
  const sorted = [...c.values.entries()].sort((a, b) => a[1].value - b[1].value);
  const n = sorted.length;
  return new Map(sorted.map(([id], i) => [id, n > 1 ? i / (n - 1) : 0.5]));
}

export default function MultiTable({ model, names, selection = [], hovered = null, onHover, onRowClick, onRowDouble,
  shade = false, rowLabel = "Country", rank = true, headTools }: {
  model: TableModel; names: Map<string, string>; selection?: string[]; hovered?: string | null;
  onHover?: (id: string | null) => void; onRowClick?: (id: string, e: React.MouseEvent) => void; onRowDouble?: (id: string, e: React.MouseEvent) => void;
  shade?: boolean; rowLabel?: string; rank?: boolean;
  headTools?: (c: TableColumn, i: number) => React.ReactNode; // a small menu under a column's name
}) {
  const { columns, rows, ranks, sort, setSort } = model;
  const tints = useMemo(() => (shade ? new Map(columns.map((c) => [c.key, standing(c)])) : null), [columns, shade]);
  const head = (by: string, label: React.ReactNode, sub: string | null, cls: string, tools?: React.ReactNode) => (
    <th key={by} className={cls} aria-sort={sort.by === by ? (sort.desc ? "descending" : "ascending") : "none"}>
      <button className="th-sort" onClick={() => setSort({ by, desc: sort.by === by ? !sort.desc : by !== "name" })}
        title={by === "name" ? "Sort by name" : "Sort by this column (click again to reverse)"}>
        {label}{sort.by === by ? (sort.desc ? " ↓" : " ↑") : ""}
      </button>
      {sub && <div className="mt-sub">{sub}</div>}
      {tools}
    </th>
  );
  return (
    <table className="multi-table">
      <thead>
        <tr>
          {rank && <th className="num">Rank</th>}
          {head("name", rowLabel, null, "")}
          {columns.map((c, i) => head(c.key, c.label, [c.unit, c.year].filter(Boolean).join(" · ") || null,
            "num mt-col", headTools?.(c, i)))}
        </tr>
      </thead>
      <tbody onMouseLeave={() => onHover?.(null)}>
        {rows.map((id) => {
          const on = selection.includes(id);
          return (
            <tr key={id} className={[on ? "selected" : "", hovered === id ? "hovered" : ""].join(" ")}
              onClick={(e) => onRowClick?.(id, e)} onDoubleClick={(e) => onRowDouble?.(id, e)}
              onMouseEnter={() => onHover?.(id)} aria-selected={on}>
              {rank && <td className="num">{ranks.get(id) ?? "–"}</td>}
              <td className="mt-name"><Flag id={id} />{names.get(id) ?? id}</td>
              {columns.map((c) => {
                const v = c.values.get(id);
                const t = tints?.get(c.key)?.get(id);
                return (
                  <td key={c.key} className="num" title={v?.year ? `No ${c.year} figure: this is from ${v.year}` : undefined}
                    style={t !== undefined ? { background: `color-mix(in srgb, var(--accent) ${Math.round(4 + t * 34)}%, transparent)` } : undefined}>
                    {cellText(c, v, false)}{v?.year ? <span className="mt-year"> {v.year}</span> : null}
                  </td>
                );
              })}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
