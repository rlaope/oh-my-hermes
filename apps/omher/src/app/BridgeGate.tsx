// While the Tauri shell's bridge is not up, say so on one centred screen instead of an empty app.
// Outside Tauri (browser dev, e2e against the mock) there is no shell to ask and the app renders directly.
import { useCallback, useEffect, useState, type ReactNode } from "react";
import "./gate.css";

export type BridgeState = { state: "ready" | "starting" | "failed"; error?: string };

const inTauri = () => typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

async function call<T>(cmd: string): Promise<T> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<T>(cmd);
}

export function BridgeGate({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<BridgeState | null>(inTauri() ? null : { state: "ready" });
  const [retrying, setRetrying] = useState(false);

  useEffect(() => {
    if (!inTauri() || status?.state === "ready") return;
    let alive = true;
    const poll = async () => {
      try {
        const s = await call<BridgeState>("bridge_status");
        if (alive) setStatus(s);
      } catch (e) {
        if (alive) setStatus({ state: "failed", error: String(e) });
      }
    };
    void poll();
    const h = setInterval(poll, 500);
    return () => {
      alive = false;
      clearInterval(h);
    };
  }, [status?.state === "ready"]);

  const retry = useCallback(async () => {
    setRetrying(true);
    setStatus({ state: "starting" });
    try {
      await call<void>("bridge_retry");
    } catch (e) {
      setStatus({ state: "failed", error: String(e) });
    } finally {
      setRetrying(false);
    }
  }, []);

  if (status?.state === "ready") return <>{children}</>;

  const failed = status?.state === "failed";
  return (
    <div className="gate" data-testid="bridge-gate" data-state={status?.state ?? "starting"}>
      <div className="gate-box">
        <div className="gate-title">{failed ? "omher can’t reach Hermes" : "Starting omher…"}</div>
        {failed && (
          <>
            <p className="gate-error" data-testid="bridge-error">
              {status?.error || "The local bridge did not start."}
            </p>
            <button type="button" className="gate-retry" data-testid="bridge-retry" disabled={retrying} onClick={retry}>
              Retry
            </button>
          </>
        )}
      </div>
    </div>
  );
}
