/** 前端句级多色标注：五框架中文关键词高亮（与 oh_pipeline.rules 词表同源子集）。 */

const FRAME_WORDS: Record<string, string[]> = {
  loss: ["衰退", "损失", "下跌", "暴跌", "裁员", "恶化", "风险", "危机", "下滑", "萎缩", "低迷", "失败", "流失"],
  gain: ["增长", "改善", "复苏", "上涨", "提振", "回暖", "超预期", "扩张", "反弹", "利好", "创新高"],
  responsibility: ["政策", "监管", "措施", "责任", "应对", "干预", "改革", "计划", "警告", "指责"],
  conflict: ["对抗", "升级", "关税", "制裁", "争端", "冲突", "博弈", "威胁", "摩擦", "谈判破裂"],
  human_interest: ["民众", "家庭", "工人", "居民", "生活", "就业", "民生", "投资者", "储户"],
};

export type Segment = { text: string; frame: string | null };

/** 把文本切分为带框架着色的片段（贪心匹配，重叠取最长）。 */
export function highlightFrames(text: string): Segment[] {
  const hits: { start: number; end: number; frame: string }[] = [];
  for (const [frame, words] of Object.entries(FRAME_WORDS)) {
    for (const w of words) {
      let idx = text.indexOf(w);
      while (idx !== -1) {
        hits.push({ start: idx, end: idx + w.length, frame });
        idx = text.indexOf(w, idx + w.length);
      }
    }
  }
  hits.sort((a, b) => (a.start - b.start) || (b.end - a.end));
  const segs: Segment[] = [];
  let pos = 0;
  for (const h of hits) {
    if (h.start < pos) continue;
    if (h.start > pos) segs.push({ text: text.slice(pos, h.start), frame: null });
    segs.push({ text: text.slice(h.start, h.end), frame: h.frame });
    pos = h.end;
  }
  if (pos < text.length) segs.push({ text: text.slice(pos), frame: null });
  return segs;
}

export const FRAME_BG: Record<string, string> = {
  loss: "#b3543f1a",
  gain: "#5e8a5e1a",
  responsibility: "#b08d3e1a",
  conflict: "#8a6fae1a",
  human_interest: "#5e83a81a",
};

export const FRAME_TEXT: Record<string, string> = {
  loss: "#b3543f",
  gain: "#5e8a5e",
  responsibility: "#b08d3e",
  conflict: "#8a6fae",
  human_interest: "#5e83a8",
};

export const FRAME_ZH: Record<string, string> = {
  loss: "损失",
  gain: "收益",
  responsibility: "责任",
  conflict: "冲突",
  human_interest: "人情味",
  other: "其他",
};
