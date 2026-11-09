// Every agent mark at sidebar (22px) and list (16px) sizes, on the app's own theme tokens.
import { createRoot } from "react-dom/client";
import "../src/theme/tokens.css";
import "../src/theme/base.css";
import { AGENT_IDS, AgentIcon, agentIcon } from "../src/ui/AgentIcon";

const theme = new URLSearchParams(location.search).get("theme") === "light" ? "light" : "dark";
document.documentElement.dataset.theme = theme;

function Grid() {
  return (
    <div style={{ padding: 24, background: "var(--bg)", color: "var(--ink)", minHeight: "100%" }}>
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 14 }}>Agent marks · {theme}</div>
      <div data-testid="agent-grid" style={{ display: "grid", gridTemplateColumns: "repeat(6, 132px)", gap: 8 }}>
        {[...AGENT_IDS, "zed"].map((id) => (
          <div key={id} data-testid={`agent-cell-${id}`}
            style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 10px", borderRadius: 6, background: "var(--raise)" }}>
            <AgentIcon id={id} size={22} />
            <AgentIcon id={id} size={16} />
            <span style={{ fontSize: 12, color: "var(--muted)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {agentIcon(id).title}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<Grid />);
