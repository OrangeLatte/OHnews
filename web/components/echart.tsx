"use client";

import { useEffect, useRef } from "react";
import * as echarts from "echarts";

export function EChart({
  option,
  height = "38vh",
}: {
  option: echarts.EChartsOption;
  height?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    chart.setOption(option);
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.dispose();
    };
  }, [option]);

  return <div ref={ref} style={{ height, width: "100%" }} />;
}
