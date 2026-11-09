// The small mark of each session agent: Claude and OpenAI marks (shared with the model pill), the app's
// own mark for oh-my-hermes, the Grok mark, and the official pi (pi.dev/favicon.svg) and
// oh-my-pi (omp.sh/favicon.svg) marks.
import ompMark from "../assets/agents/omp.svg";
import logo from "../assets/omher-mark.png";
import { ModelIcon } from "../ui";
import type { AgentId } from "./agents";

export function AgentMark({ agent, size = 16 }: { agent: AgentId; size?: number }) {
  const box = { width: size, height: size };
  if (agent === "claude") return <ModelIcon model="claude" size={size} className="ag-mark" />;
  if (agent === "codex") return <ModelIcon model="codex" size={size} className="ag-mark ag-codex" />;
  if (agent === "grok") return <ModelIcon model="grok" size={size} className="ag-mark" />;
  if (agent === "pi")
    // pi.dev/favicon.svg, drawn inline in currentColor so it follows the app theme (the file follows the OS)
    return (
      <svg viewBox="0 0 560 560" className="ag-mark ag-pi" style={box} data-mark="pi" aria-hidden="true">
        <path fill="currentColor" d="M420 280H280V140H0V0H420V280ZM560 560H420V280H560V560ZM140 560H0V140H140V280H280V420H140V560Z" />
      </svg>
    );
  if (agent === "omp") return <img src={ompMark} alt="" className="ag-mark ag-img" style={box} data-mark="omp" />;
  return <img src={logo} alt="" className="ag-mark ag-img" style={box} data-mark="omh" />;
}
