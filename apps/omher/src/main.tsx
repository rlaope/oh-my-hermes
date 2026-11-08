import { createRoot } from "react-dom/client";
import { App } from "./app/App";
import { BridgeGate } from "./app/BridgeGate";
createRoot(document.getElementById("root")!).render(
  <BridgeGate>
    <App />
  </BridgeGate>,
);
