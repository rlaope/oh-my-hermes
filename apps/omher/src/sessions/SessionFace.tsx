// A SESSIONS chat's face wherever a bot's picture would go (the Needs-you list, the typing bubble): the
// session agent's official mark in the same rounded box as the session row.
import { AgentMark } from "./AgentMark";
import { getSessions, useSessions } from "./sessions";

export function SessionFace({ chatKey, size }: { chatKey: string; size: number }) {
  useSessions(); // re-render when the session list changes
  const rec = getSessions().byKey(chatKey);
  return (
    <span className="ss-face" style={{ width: size, height: size }} data-testid="session-face">
      {rec && <AgentMark agent={rec.agent} size={Math.round(size * 0.56)} />}
    </span>
  );
}
