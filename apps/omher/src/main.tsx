import { createRoot } from "react-dom/client";
import { App } from "./app/App";
import { BridgeGate } from "./app/BridgeGate";
import { getSessions } from "./sessions/sessions";
import { bootResume } from "./app/resumeBoot";
import { startTermLinks } from "./sessions/termLinkOpen";
import { resolveTheme } from "./app/theme";
import { readTheme } from "./state/store";
import { learnThisHost } from "./terminal/host";

// The gate (first run, connecting, retry) is drawn before <App> mounts and sets the theme: give it the person's
// theme too, or a light-theme user's first screen is dark.
document.documentElement.dataset.theme = resolveTheme(readTheme());

// A reload keeps the shell (and any agent the last page started) alive: stop those before any UI exists.
void getSessions().reset();
// This computer's name, once, before any terminal starts: OSC 7 from it counts as local in every terminal.
void learnThisHost();
// Then put back what was open before omher last closed (an update restart, a quit, a crash); the sessions that
// continue by themselves start once that reset is done.
bootResume();
// omher://terminal/<id> links opened from outside: the ones waiting, then each new one (after the list is back)
startTermLinks();
createRoot(document.getElementById("root")!).render(
  <BridgeGate>
    <App />
  </BridgeGate>,
);
