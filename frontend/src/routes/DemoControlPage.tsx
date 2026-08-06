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
    <main className="center-page">
      <section className="control-card">
        <p className="eyebrow">Rehearsal only</p>
        <h1>Demo control</h1>
        <p>This unlinked page exposes only safe health state and deterministic failure injection.</p>
        <label className="control-token">Rehearsal token<input type="password" autoComplete="off" value={token} onChange={(event) => setToken(event.target.value)} /></label>
        <button className="secondary-button full" disabled={busy} onClick={() => void loadStatus()}><RefreshCw size={16} /> Load safe status</button>
        <p className="control-message" role="status">{message}</p>
        {status && (
          <div className="control-status">
            <article><Activity size={18} /><strong>API</strong><span>{status.api}</span></article>
            <article><Database size={18} /><strong>Database</strong><span>{String(status.database.backend ?? "unknown")}</span></article>
            <article><ShieldAlert size={18} /><strong>GenAI</strong><span>{status.genai}</span></article>
            <article><Database size={18} /><strong>Catalog</strong><span>{String(status.database.catalog_version ?? "unknown")}</span></article>
            <article><RefreshCw size={18} /><strong>Last seed</strong><span>{String(status.database.last_seed_time ?? "unknown")}</span></article>
          </div>
        )}
        <fieldset className="failure-modes"><legend>Failure mode</legend>{modes.map((mode) => <button key={mode} disabled={busy} className={status?.fallback_mode === mode ? "active" : ""} onClick={() => void changeMode(mode)}>{mode.replaceAll("_", " ")}</button>)}</fieldset>
        <small>Synthetic demo controls only. No real payment, restaurant, or courier action occurs.</small>
      </section>
    </main>
  );
}
