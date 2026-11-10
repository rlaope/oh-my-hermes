import type { Key } from "./index";

export const ja: Record<Key, string> = {
  // graph (the dag box view and its header)
  "graph.start": "開始ノード",
  "graph.frontier": "同じ段階",
  "graph.deps": "依存関係",
  "graph.details": "ノード詳細",
  "graph.untitled": "無題",
  "graph.accepted": "承認済み",
  "graph.finished": "完了",
  "graph.running": "実行中",
  "graph.handed": "引き渡し済み",
  "graph.failed": "失敗",
  "graph.blocked": "ブロック",
  "graph.parked": "保留",
  "graph.cancelled": "キャンセル",
  "graph.retry": "再試行",
  "graph.waiting": "待機中",
  "graph.waits.one": "{n} 件待ち",
  "graph.waits": "{n} 件待ち",
  "graph.repaired": "修復済み",
  "graph.repair": "修復",
  "graph.layer": "レイヤー {n}",
  "graph.attempt": "試行 {n}",
  "graph.more": "+{n} 件",
  "graph.all": "すべて表示 ({n})",
  "graph.fewer": "折りたたむ",
  "graph.fit": "フィット",
  "graph.reset": "配置をリセット",
  "graph.zoomIn": "拡大",
  "graph.zoomOut": "縮小",
  "graph.hint": "表示のみ · ノードをドラッグで移動 · Esc で閉じる",
  "graph.full": "全体表示",
  "graph.close": "グラフを閉じる",
  "graph.dag": "OMH / DAG",
  "graph.helpers": "Hermes / ヘルパー",
  "graph.subagents": "{agent} / サブエージェント",
  "graph.tasks.one": "タスク {n}件",
  "graph.tasks": "タスク {n}件",
  "graph.main": "main",
  "graph.run.running": "実行中",
  "graph.run.done": "完了",
  "graph.run.failed": "失敗",
  "graph.run.cancelled": "キャンセル",
  "graph.done": "完了 {done}/{total}",
  "graph.nfailed": "失敗 {n}",
  "graph.nrepaired": "修復 {n}",
  "graph.nwaiting": "待機 {n}",
  "graph.notStarted": "未開始",
  "graph.startsIn": "{t} 後に開始",
  "graph.startNow": "今すぐ開始",
  "graph.edit": "編集",
  "graph.prefill": "メッセージ欄に依頼を入れます。送信はしません。",

  // plans (the run list)
  "plans.tab": "計画",

  // skills (the composer's ./ picker)
  "skills.none": "一致するスキルなし",

  // sessions (SESSIONS in the sidebar)
  "sessions.choose": "フォルダを選択…",

  // sounds (Settings › General)
  "sounds.title": "サウンド",
};
