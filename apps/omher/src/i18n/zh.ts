import type { Key } from "./index";

export const zh: Record<Key, string> = {
  // graph (the dag box view and its header)
  "graph.start": "起始节点",
  "graph.frontier": "同一阶段",
  "graph.deps": "依赖关系",
  "graph.details": "节点详情",
  "graph.untitled": "未命名",
  "graph.accepted": "已接受",
  "graph.finished": "完成",
  "graph.running": "运行中",
  "graph.handed": "已分派",
  "graph.failed": "失败",
  "graph.blocked": "受阻",
  "graph.parked": "搁置",
  "graph.cancelled": "已取消",
  "graph.retry": "重试",
  "graph.waiting": "等待中",
  "graph.waits.one": "等待 {n} 项",
  "graph.waits": "等待 {n} 项",
  "graph.repaired": "已修复",
  "graph.repair": "修复",
  "graph.layer": "第 {n} 层",
  "graph.attempt": "第 {n} 次尝试",
  "graph.more": "+{n} 项",
  "graph.all": "显示全部 {n} 项",
  "graph.fewer": "收起",
  "graph.fit": "适应",
  "graph.reset": "重置布局",
  "graph.zoomIn": "放大",
  "graph.zoomOut": "缩小",
  "graph.hint": "仅查看 · 拖动节点可移动 · Esc 关闭",
  "graph.full": "全屏视图",
  "graph.close": "关闭图",
  "graph.dag": "OMH / DAG",
  "graph.helpers": "Hermes / 助手",
  "graph.subagents": "{agent} / 子代理",
  "graph.tasks.one": "{n} 个任务",
  "graph.tasks": "{n} 个任务",
  "graph.main": "main",
  "graph.run.running": "运行中",
  "graph.run.done": "已完成",
  "graph.run.failed": "失败",
  "graph.run.cancelled": "已取消",
  "graph.done": "完成 {done}/{total}",
  "graph.nfailed": "{n} 项失败",
  "graph.nrepaired": "{n} 项已修复",
  "graph.nwaiting": "{n} 项等待",
  "graph.notStarted": "未开始",
  "graph.startsIn": "{t} 后开始",
  "graph.startNow": "立即开始",
  "graph.edit": "编辑",
  "graph.prefill": "会把请求放入消息框，不会发送。",

  // plans (the run list)
  "plans.tab": "计划",

  // skills (the composer's ./ picker)
  "skills.none": "没有匹配的技能",

  // sessions (SESSIONS in the sidebar)
  "sessions.choose": "选择文件夹…",

  // sounds (Settings › General)
  "sounds.title": "声音",
};
