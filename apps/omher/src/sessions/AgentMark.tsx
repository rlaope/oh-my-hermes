// The small mark of each session agent: Claude and OpenAI marks (shared with the model pill), the app's
// own mark for oh-my-hermes, the Grok mark, the official pi (pi.dev/favicon.svg) and oh-my-pi (omp.sh/favicon.svg)
// marks, OmO's icon (oh-my-openagent `.github/assets/omo-icon-light.svg`, its viewBox trimmed to the tile) and
// DeepSeek Harness's mark for DSH (deepseek-harness `apps/web/public/favicon.svg`, MIT, the file unchanged),
// and OpenCode's, Kilo Code's, Gemini CLI's, Qwen Code's, GitHub Copilot's and Cline's marks (Lobe Icons) through
// AgentIcon. Kimi Code's mark is the icon its own npm package ships (`@moonshot-ai/kimi-code` 2.6.0,
// `dist-web/favicon.ico`, its 64px image, MIT, unchanged). For a person with Hermes but not oh-my-hermes, the oh-my-hermes
// row is a plain Hermes chat and shows Hermes Agent's official mark (NousResearch/hermes-agent `assets/icon-master.svg`,
// MIT, the repo's `assets/hermes-agent-icon.png` render, unchanged).
import dshSvg from "../assets/agents/dsh.svg?raw";
import omoMark from "../assets/agents/omo.svg";
import ompMark from "../assets/agents/omp.svg";
import kimiMark from "../assets/agents/kimi-code.png";
import logo from "../assets/omher-mark.png";
import hermesMark from "../assets/agents/hermes-agent.png";
import { AgentIcon, ModelIcon } from "../ui";
import { hermesOnly, type AgentId } from "./agents";
import { useSessions } from "./sessions";

const IMG: Partial<Record<AgentId, string>> = { omp: ompMark, omo: omoMark, kimi: kimiMark };

/** The agents drawn from AgentIcon's Lobe Icons set, by its id. */
const LOBE: Partial<Record<AgentId, string>> = { opencode: "opencode", kilo: "kilo", gemini: "gemini", qwen: "qwen", copilot: "copilot", cline: "cline" };

// DeepSeek Harness's mark is one black path; drawn inline in currentColor so it shows on both themes
const DSH_PATH = /\sd="([^"]+)"/.exec(dshSvg)?.[1] ?? "";

export function AgentMark({ agent, size = 16 }: { agent: AgentId; size?: number }) {
  const box = { width: size, height: size };
  const hermes = hermesOnly(useSessions().agents);
  if (agent === "claude") return <ModelIcon model="claude" size={size} className="ag-mark" />;
  if (agent === "codex") return <ModelIcon model="codex" size={size} className="ag-mark ag-codex" />;
  if (agent === "grok") return <ModelIcon model="grok" size={size} className="ag-mark" />;
  const lobe = LOBE[agent];
  if (lobe) return <AgentIcon id={lobe} size={size} className="ag-mark" />;
  if (agent === "pi")
    // pi.dev/favicon.svg, drawn inline in currentColor so it follows the app theme (the file follows the OS)
    return (
      <svg viewBox="0 0 560 560" className="ag-mark ag-pi" style={box} data-mark="pi" aria-hidden="true">
        <path fill="currentColor" d="M420 280H280V140H0V0H420V280ZM560 560H420V280H560V560ZM140 560H0V140H140V280H280V420H140V560Z" />
      </svg>
    );
  if (agent === "dsh")
    return (
      <svg viewBox="0 0 50 50" className="ag-mark ag-pi" style={box} data-mark="dsh" aria-hidden="true">
        <path fill="currentColor" d={DSH_PATH} />
      </svg>
    );
  const img = IMG[agent];
  if (img) return <img src={img} alt="" className="ag-mark ag-img" style={box} data-mark={agent} />;
  if (hermes) return <img src={hermesMark} alt="" className="ag-mark ag-img ag-hermes" style={box} data-mark="hermes" />;
  return <img src={logo} alt="" className="ag-mark ag-img" style={box} data-mark="omh" />;
}
