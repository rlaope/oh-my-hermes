// The small mark of each session agent: Claude and OpenAI marks (shared with the model pill), the app's
// own mark for oh-my-hermes, and plain letter marks for pi and oh-my-pi.
import logo from "../assets/omher-mark.png";
import { ModelIcon } from "../ui";
import type { AgentId } from "./agents";

export function AgentMark({ agent, size = 16 }: { agent: AgentId; size?: number }) {
  const box = { width: size, height: size };
  if (agent === "claude") return <ModelIcon model="claude" size={size} className="ag-mark" />;
  if (agent === "codex") return <ModelIcon model="codex" size={size} className="ag-mark ag-codex" />;
  if (agent === "omh") return <img src={logo} alt="" className="ag-mark ag-img" style={box} data-mark="omh" />;
  return (
    <span className="ag-mark ag-letter" style={{ ...box, fontSize: Math.round(size * (agent === "pi" ? 0.72 : 0.5)) }} data-mark={agent} aria-hidden="true">
      {agent === "pi" ? "π" : "oπ"}
    </span>
  );
}
