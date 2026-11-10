import { createRoot } from "react-dom/client";
import { App } from "./app/App";
import { BridgeGate } from "./app/BridgeGate";
import { getSessions } from "./sessions/sessions";

// A reload keeps the shell (and any agent the last page started) alive: stop those before any UI exists.
void getSessions().reset();
createRoot(document.getElementById("root")!).render(
  <BridgeGate>
    <App />
  </BridgeGate>,
);
