"use client";

import type { ECharts, EChartsOption } from "echarts";
import { useCallback, useRef, useState } from "react";
import { cssVar } from "@/lib/colors";
import { axisYear } from "@/lib/long";

// Zooming a long history chart's years: a slider under the chart (drag either end or the
// middle), dragging the chart itself to move along (unless the chart's clicks pick a year), and Shift + mouse wheel to zoom.
// The years in view are kept in a ref, not state, so redrawing the chart (new countries,
// the Play button) keeps the zoom instead of snapping back, and dragging is never cut off
// by a redraw. "Whole range" shows only while zoomed in.
export function useYearZoom({ pan = true }: { pan?: boolean } = {}) {
  const span = useRef<[number, number] | null>(null);
  const chart = useRef<ECharts | null>(null);
  const [zoomed, setZoomed] = useState(false);

  const attach = useCallback((c: ECharts) => {
    chart.current = c;
    c.on("datazoom", () => {
      const dz = (c.getOption().dataZoom as { start?: number; end?: number; startValue?: number; endValue?: number }[] | undefined)?.[0];
      if (!dz) return;
      const whole = (dz.start ?? 0) <= 0.01 && (dz.end ?? 100) >= 99.99;
      span.current = whole || dz.startValue === undefined || dz.endValue === undefined ? null : [dz.startValue, dz.endValue];
      setZoomed(!whole);
    });
  }, []);

  const apply = useCallback((o: EChartsOption, label: (v: number) => string = axisYear): EChartsOption => {
    const s = span.current;
    const at = s ? { startValue: s[0], endValue: s[1] } : {};
    return {
      ...o,
      grid: { ...(o.grid as object), bottom: 40 },
      dataZoom: [
        { type: "slider", xAxisIndex: 0, filterMode: "none", realtime: false, height: 18, bottom: 6, left: 72, right: 56, brushSelect: false, ...at,
          labelFormatter: (v: number) => label(Math.round(v)), borderColor: cssVar("--border"), textStyle: { color: cssVar("--muted") } },
        { type: "inside", xAxisIndex: 0, filterMode: "none", zoomOnMouseWheel: "shift", moveOnMouseWheel: false, moveOnMouseMove: pan, ...at },
      ],
    } as EChartsOption;
  }, [pan]);

  const reset = useCallback(() => {
    span.current = null;
    setZoomed(false);
    const c = chart.current;
    if (c && !c.isDisposed()) c.dispatchAction({ type: "dataZoom", start: 0, end: 100 });
  }, []);

  const tools = (
    <span className="small muted">
      Drag the bar under the chart to zoom into years{zoomed ? <>; <button className="link small" onClick={reset}>whole range</button></> : null}
    </span>
  );
  return { attach, apply, reset, tools };
}
