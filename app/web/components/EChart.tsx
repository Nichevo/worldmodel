"use client";

import * as echarts from "echarts";
import { useEffect, useRef } from "react";

// Thin wrapper: one ECharts instance per element, resized with its box, and
// redrawn when the colour scheme changes (options are built from CSS variables).
export default function EChart({ option, height = 300, label }: { option: () => echarts.EChartsOption; height?: number | string; label: string }) {
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!el.current) return;
    chart.current = echarts.init(el.current, undefined, { renderer: "svg" });
    const ro = new ResizeObserver(() => chart.current?.resize());
    ro.observe(el.current);
    return () => {
      ro.disconnect();
      chart.current?.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    const draw = () => chart.current?.setOption(option(), true);
    draw();
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener("change", draw);
    return () => mq.removeEventListener("change", draw);
  }, [option]);

  return <div ref={el} style={{ width: "100%", height }} role="img" aria-label={label} />;
}
