/** The thread bubble with a + in it: every "new thread" entry (sidebar row, bot row +, row menu, `./thread` picker). */
export function NewThreadIcon({ size = 16 }: { size?: number }) {
  return (
    <svg className="nt-ic" width={size} height={size} viewBox="0 0 16 16" aria-hidden="true">
      <path d="M3.2 2.5h9.6a1.7 1.7 0 0 1 1.7 1.7v5.6a1.7 1.7 0 0 1-1.7 1.7H7.4L4.5 13.8v-2.3H3.2a1.7 1.7 0 0 1-1.7-1.7V4.2a1.7 1.7 0 0 1 1.7-1.7Z" fill="none" stroke="currentColor" strokeWidth="1.25" strokeLinejoin="round" />
      <path d="M8 4.8v4.4M5.8 7h4.4" fill="none" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" />
    </svg>
  );
}
