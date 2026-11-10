import { createRoot } from "react-dom/client";
import { App } from "./app/App";
import { BridgeGate } from "./app/BridgeGate";
import { getSessions } from "./sessions/sessions";
import { resolveTheme } from "./app/theme";
import { readTheme } from "./state/store";

// The gate (first run, connecting, retry) is drawn before <App> mounts and sets the theme: give it the person's
// theme too, or a light-theme user's first screen is dark.
document.documentElement.dataset.theme = resolveTheme(readTheme());

// A reload keeps the shell (and any agent the last page started) alive: stop those before any UI exists.
void getSessions().reset();
createRoot(document.getElementById("root")!).render(
  <BridgeGate>
    <App />
  </BridgeGate>,
);
