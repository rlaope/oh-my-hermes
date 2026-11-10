// Stroke icons used by the shell (copied from the sketch).
const s = { fill: "none", stroke: "currentColor" } as const;

export const PlusIcon = ({ size = 15 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...s} strokeWidth="2"><path d="M12 5v14M5 12h14" /></svg>
);
export const SearchIcon = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" {...s} strokeWidth="2.2"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
);
export const CalendarIcon = () => (
  <svg viewBox="0 0 24 24" {...s} strokeWidth="1.8"><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M3 10h18M8 3v4M16 3v4" /></svg>
);
export const GridIcon = () => (
  <svg viewBox="0 0 24 24" {...s} strokeWidth="1.8"><rect x="4" y="4" width="7" height="7" rx="1.5" /><rect x="13" y="4" width="7" height="7" rx="1.5" /><rect x="4" y="13" width="7" height="7" rx="1.5" /><rect x="13" y="13" width="7" height="7" rx="1.5" /></svg>
);
export const GearIcon = ({ size }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...s} strokeWidth="1.8"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-2.8 1.2V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-2.9-1.2l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.7 1.7 0 0 0 3.2 14H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.2-2.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 2.9-1.2V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 2.9 1.2l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0 1.2 2.9H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" /></svg>
);
export const ChevronDown = ({ size = 9 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...s} strokeWidth="2.6"><path d="m6 9 6 6 6-6" /></svg>
);
export const ChevronRight = ({ size = 10 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...s} strokeWidth="2.6"><path d="m9 6 6 6-6 6" /></svg>
);
export const ArrowUp = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" {...s} strokeWidth="2.6"><path d="M12 19V5M5 12l7-7 7 7" /></svg>
);
export const StopIcon = () => (
  <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="5" width="14" height="14" rx="2" /></svg>
);
export const CloseIcon = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" {...s} strokeWidth="2.2"><path d="M6 6l12 12M18 6 6 18" /></svg>
);
/** A terminal window with a prompt: the session header's "Open in Terminal". */
export const TerminalIcon = ({ size = 14 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...s} strokeWidth="1.9" aria-hidden="true"><rect x="3" y="4.5" width="18" height="15" rx="2.5" /><path d="m7.5 10 2.5 2.5-2.5 2.5M12.5 15.5h4" /></svg>
);
/** A speech bubble: back to the chat from the terminal view. */
export const ChatIcon = ({ size = 14 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...s} strokeWidth="1.9" aria-hidden="true"><path d="M5 5.5h14a1.5 1.5 0 0 1 1.5 1.5v8.5A1.5 1.5 0 0 1 19 17h-8l-4.5 3.5V17H5a1.5 1.5 0 0 1-1.5-1.5V7A1.5 1.5 0 0 1 5 5.5z" /></svg>
);
/** Two corners pulling apart: open something at full size (the plan's full view). */
export const ExpandIcon = ({ size = 14 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...s} strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M14 4h6v6M10 20H4v-6M20 4l-6.5 6.5M4 20l6.5-6.5" /></svg>
);
