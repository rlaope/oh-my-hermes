import type { Key } from "./index";

export const zh: Record<Key, string> = {
  // graph (the dag box view)
  "graph.start": "起始节点",
  "graph.frontier": "同一阶段",
  "graph.deps": "依赖关系",
  "graph.details": "节点详情",
  "graph.tasks.one": "{n} 个任务",
  "graph.tasks": "{n} 个任务",
  "graph.done": "完成 {done}/{total}",

  // plans (the run list)
  "plans.tab": "计划",

  // skills (the composer's ./ picker)
  "skills.none": "没有匹配的技能",

  // sessions (SESSIONS in the sidebar)
  "sessions.choose": "选择文件夹…",

  // sounds (Settings › General)
  "sounds.title": "声音",
};
