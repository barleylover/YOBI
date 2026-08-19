import { useState } from "react";
import { Activity, Database, RefreshCw, ShieldAlert } from "lucide-react";
import { api } from "../lib/api";

const modes = ["normal", "force_genai_timeout", "force_payment_failure", "force_fallback"];

export function DemoControlPage() {
  const [token, setToken] = useState("");
  const [status, setStatus] = useState<Awaited<ReturnType<typeof api.demoStatus>> | null>(null);
  const [message, setMessage] = useState("Enter the rehearsal token, then load safe status.");
  const [busy, setBusy] = useState(false);

  async function loadStatus() {
    setBusy(true);
    try {
      setStatus(await api.demoStatus(token));
      setMessage("Status refreshed. No secret or raw user data is displayed.");
    } catch {
      setMessage("Status is protected. Check the rehearsal token and try again.");
    } finally {
      setBusy(false);
    }
  }

  async function changeMode(mode: string) {
    setBusy(true);
    try {
      await api.setFailureMode(token, mode);
      setMessage(`Failure mode changed to ${mode}.`);
      setStatus(await api.demoStatus(token));
    } catch {
      setMessage("The mode was not changed. Check the protected token.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="v2-screen subtle">
      <div className="v2-body" style={{ gap: 14, maxWidth: 430 }}>
        <div className="v2-heading">
          <h1>Demo control</h1>
          <p>This unlinked page exposes only safe health state and deterministic failure injection.</p>
        </div>
        <section className="v2-summary-card">
          <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 13, fontWeight: 600, color: "var(--text-default)" }}>
            Rehearsal token
            <div className="v2-search-field bordered">
              <input type="password" autoComplete="off" value={token} onChange={(event) => setToken(event.target.value)} />
            </div>
          </label>
          <button className="v2-cta compact secondary" disabled={busy} onClick={() => void loadStatus()}>
            <RefreshCw size={16} style={{ marginRight: 8 }} /> Load safe status
          </button>
          <p className="v2-status" role="status">{message}</p>
        </section>
        {status && (
          <section className="v2-summary-card" style={{ gap: 10 }}>
            {[
              [<Activity size={18} key="i" />, "API", status.api],
              [<Database size={18} key="i" />, "Database", String(status.database.backend ?? "unknown")],
              [<ShieldAlert size={18} key="i" />, "GenAI", status.genai],
              [<Database size={18} key="i" />, "Catalog", String(status.database.catalog_version ?? "unknown")],
              [<RefreshCw size={18} key="i" />, "Last seed", String(status.database.last_seed_time ?? "unknown")],
            ].map(([icon, label, value]) => (
              <div className="v2-price-row" key={String(label)}>
                <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>{icon} {label}</span>
                <strong>{value}</strong>
              </div>
            ))}
          </section>
        )}
        <section className="v2-summary-card">
          <strong style={{ fontSize: 14 }}>Failure mode</strong>
          <div className="v2-chip-grid">
            {modes.map((mode) => (
              <button
                key={mode}
                disabled={busy}
                className={status?.fallback_mode === mode ? "v2-chip selected" : "v2-chip"}
                onClick={() => void changeMode(mode)}
              >
                {mode.replaceAll("_", " ")}
              </button>
            ))}
          </div>
          <p className="v2-status">Synthetic demo controls only. No real payment, restaurant, or courier action occurs.</p>
        </section>
      </div>
    </main>
  );
}
