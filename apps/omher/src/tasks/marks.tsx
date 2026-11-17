// The three task sources' marks, monochrome (the text colour; the Tasks row brightens them on hover), and the Tasks
// row's list mark.
//
// GitHub, GitLab and Linear: path data from Simple Icons 16.37.0 (https://simpleicons.org,
// cdn.jsdelivr.net/npm/simple-icons@16.37.0/icons/<slug>.svg), CC0-1.0, unaltered (the GitHub and Linear paths are
// the ones src/ui/brandIcons.tsx already carries). The marks remain their owners' trademarks; they only name where
// the tasks come from.
import type { TaskSource } from "./types";

const PATHS: Record<TaskSource, string> = {
  github: "M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12",
  gitlab: "m23.6004 9.5927-.0337-.0862L20.3.9814a.851.851 0 0 0-.3362-.405.8748.8748 0 0 0-.9997.0539.8748.8748 0 0 0-.29.4399l-2.2055 6.748H7.5375l-2.2057-6.748a.8573.8573 0 0 0-.29-.4412.8748.8748 0 0 0-.9997-.0537.8585.8585 0 0 0-.3362.4049L.4332 9.5015l-.0325.0862a6.0657 6.0657 0 0 0 2.0119 7.0105l.0113.0087.03.0213 4.976 3.7264 2.462 1.8633 1.4995 1.1321a1.0085 1.0085 0 0 0 1.2197 0l1.4995-1.1321 2.4619-1.8633 5.006-3.7489.0125-.01a6.0682 6.0682 0 0 0 2.0094-7.003z",
  linear: "M2.886 4.18A11.982 11.982 0 0 1 11.99 0C18.624 0 24 5.376 24 12.009c0 3.64-1.62 6.903-4.18 9.105L2.887 4.18ZM1.817 5.626l16.556 16.556c-.524.33-1.075.62-1.65.866L.951 7.277c.247-.575.537-1.126.866-1.65ZM.322 9.163l14.515 14.515c-.71.172-1.443.282-2.195.322L0 11.358a12 12 0 0 1 .322-2.195Zm-.17 4.862 9.823 9.824a12.02 12.02 0 0 1-9.824-9.824Z",
};

export function SourceMark({ source, size = 13 }: { source: TaskSource; size?: number }) {
  return (
    <svg className="tk-mark" data-source={source} width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" focusable="false">
      <path d={PATHS[source]} />
    </svg>
  );
}

/** A list: three short lines with a dot before each. */
export function ListIcon() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="14" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" aria-hidden="true">
      <path d="M6 4h7M6 8h7M6 12h7" />
      <circle cx="3" cy="4" r=".6" fill="currentColor" />
      <circle cx="3" cy="8" r=".6" fill="currentColor" />
      <circle cx="3" cy="12" r=".6" fill="currentColor" />
    </svg>
  );
}

/** An issue's state mark (Octicons issue-opened / issue-closed shapes, drawn as circles here). */
export function IssueMark({ state }: { state: string }) {
  return (
    <svg className="tk-issue" data-state={state} viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
      <circle cx="8" cy="8" r="6.25" />
      {state === "closed" ? <path d="M5.5 8.2l1.7 1.7 3.3-3.4" strokeLinecap="round" strokeLinejoin="round" /> : <circle cx="8" cy="8" r="1.2" fill="currentColor" stroke="none" />}
    </svg>
  );
}
