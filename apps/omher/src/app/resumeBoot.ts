// Wires resume.ts into the running app: at boot, put back the drafts and the SESSIONS list saved before omher
// last closed (the store puts back the bot, panel and Plans view itself, once the bot list is known); after that,
// save a fresh snapshot a moment after anything it holds changes, when the page goes away, and right before an
// update restarts omher. Nothing is saved until the boot has put the old snapshot back, so a slow start never
// overwrites it with an empty one.
import { getStore, type AppState } from "../state/store";
import { getSessions } from "../sessions/sessions";
import { allDrafts, loadDrafts, onDraftChange } from "./drafts";
import { buildResume, parseResume, RESUME_KEY, type ResumeSnap, type SavedMsg } from "./resume";

const DEBOUNCE_MS = 400;

let booted = false;
let live = false;
let previous: ResumeSnap | null = null;
let timer: ReturnType<typeof setTimeout> | null = null;

function read(): ResumeSnap | null {
  try {
    return parseResume(localStorage.getItem(RESUME_KEY));
  } catch {
    return null;
  }
}

function snapshot(): ResumeSnap {
  const st: AppState = getStore().getState();
  const ss = getSessions();
  const list = ss.getState().list;
  const snap = buildResume(
    {
      bot: st.selectedBot,
      bots: st.bots.map((b) => b.name),
      view: st.ui.view,
      session: st.ui.session,
      panelOpen: st.ui.panelOpen,
      panelTab: st.ui.panelTab,
      runsFull: st.ui.runsFull,
      runId: st.ui.runId,
      drafts: allDrafts(),
      sessions: list.map((r) => ({
        id: r.id,
        agent: r.agent,
        cwd: r.cwd,
        startedAt: r.startedAt,
        view: r.view,
        // a paused one was running before the last restart and still waits for Resume
        running: r.status === "running" || r.status === "starting" || !!r.paused,
        ...(r.status === "failed" ? { failed: true } : {}),
        ...(r.exitCode !== undefined ? { exitCode: r.exitCode } : {}),
        ...(r.error ? { error: r.error } : {}),
        ...(r.agentSession ? { agentSession: r.agentSession } : {}),
        ...(r.account ? { account: r.account } : {}),
        ...(r.bot ? { bot: r.bot } : {}),
        ...(r.model ? { model: r.model } : {}),
      })),
      messages: (id) => {
        const key = ss.chatKey(id);
        const chat = key ? st.chats[key] : undefined;
        return chat?.messages as SavedMsg[] | undefined;
      },
    },
    Date.now(),
  );
  // no bot list (the bridge is not up): keep the bot, panel and drafts the last snapshot had
  if (st.bots.length === 0 && previous) {
    const { bot, panelOpen, panelTab, runsFull, runId } = previous;
    return { ...snap, bot, panelOpen, panelTab, runsFull, runId, drafts: { ...previous.drafts, ...snap.drafts } };
  }
  return snap;
}

/** Write the snapshot now (the update button calls this right before it restarts omher). */
export function saveResumeNow(): void {
  if (!live) return;
  if (timer) {
    clearTimeout(timer);
    timer = null;
  }
  try {
    const snap = snapshot();
    localStorage.setItem(RESUME_KEY, JSON.stringify(snap));
    previous = snap;
  } catch {
    /* no storage, or full: the next change tries again */
  }
}

function schedule(): void {
  if (!live || timer) return;
  timer = setTimeout(() => {
    timer = null;
    saveResumeNow();
  }, DEBOUNCE_MS);
}

/** Once per page load, before the app renders. */
export function bootResume(): void {
  if (booted) return;
  booted = true;
  previous = read();
  if (previous) {
    loadDrafts(previous.drafts);
    getSessions().restore(previous.sessions);
  } else {
    getSessions().restore([]);
  }
  void getStore().resumed.then(() => {
    live = true;
    getStore().subscribe(schedule);
    getSessions().subscribe(schedule);
    onDraftChange(schedule);
    window.addEventListener("beforeunload", saveResumeNow);
    window.addEventListener("pagehide", saveResumeNow);
    saveResumeNow();
  });
}
