// The omher.app preview entry: the real omher UI on an in-page host with staged data (see host.ts, story.ts).
import "./boot";
import { createRoot } from "react-dom/client";
import { App } from "../src/app/App";
import { getSessions } from "../src/sessions/sessions";
import { resolveTheme } from "../src/app/theme";
import { readTheme } from "../src/state/store";
import { installGuards } from "./guard";
import { startStory } from "./story";
import "./preview.css";

document.documentElement.dataset.theme = resolveTheme(readTheme());
void getSessions().reset();
createRoot(document.getElementById("root")!).render(<App />);
installGuards();
void startStory();
