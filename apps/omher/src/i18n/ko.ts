import type { Key } from "./index";

export const ko: Record<Key, string> = {
  // graph (the dag box view)
  "graph.start": "시작 노드",
  "graph.frontier": "같은 단계",
  "graph.deps": "의존 관계",
  "graph.details": "노드 상세",
  "graph.tasks.one": "작업 {n}개",
  "graph.tasks": "작업 {n}개",
  "graph.done": "완료 {done}/{total}",

  // plans (the run list)
  "plans.tab": "계획",

  // skills (the composer's ./ picker)
  "skills.none": "일치하는 스킬 없음",

  // sessions (SESSIONS in the sidebar)
  "sessions.choose": "폴더 선택…",

  // sounds (Settings › General)
  "sounds.title": "소리",
};
