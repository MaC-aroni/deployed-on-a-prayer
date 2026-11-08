import { useEffect, useState } from "react";
import { Copy, ExternalLink, Radio } from "lucide-react";
import { Pill } from "./StatusIcon.jsx";
import { api, fmtAgo, fmtTime } from "../mac/api.js";
import { cx } from "../lib.js";

// The outputs a pipeline declared (docs/api.md → "Outputs and probes"), with the latest value
// per environment and a button per probe. A probe sends one signed request to the URL this run
// recorded and shows AWS's answer: the request id is the proof it came from AWS.

export function liveness(env) {
  if (!env) return "none";
  if (!env.expected_live || env.run_status === "cancelled" || env.run_status === "undone") return "off";
  if (env.last_probe) return env.last_probe.ok ? "on" : "off";
  return "unknown";
}

const LIVE = {
  on: { tone: "green", label: "on" },
  off: { tone: "grey", label: "off" },
  unknown: { tone: "amber", label: "not probed" },
  none: { tone: "grey", label: "no value yet" },
};

export function LiveDot({ state, pulsing }) {
  const m = LIVE[state] ?? LIVE.none;
  return (
    <span className={cx("live-state", `tone-${m.tone}`, { pulsing })} title={m.label}>
      <span className="live-state-dot" />
      {m.label}
    </span>
  );
}

export function ProbeResult({ result }) {
  if (!result) return null;
  const body = result.body == null ? null : typeof result.body === "string" ? result.body : JSON.stringify(result.body, null, 2);
  return (
    <div className={cx("probe-result", result.ok ? "ok" : "bad")}>
      <div className="probe-line">
        <Pill tone={result.ok ? "green" : result.status ? "red" : "grey"}>{result.status ?? "no answer"}</Pill>
        <span className="mono small">{result.method} {result.url}</span>
        {result.elapsed_ms != null && <span className="small muted">{result.elapsed_ms} ms</span>}
        {result.request_id && (
          <span className="small muted" title="AWS Lambda request id: proof the answer came from AWS">
            req {result.request_id}
          </span>
        )}
        {result.served_by_aws && <Pill tone="green">served by AWS</Pill>}
        <span className="small faint">{fmtTime(result.checked)}</span>
      </div>
      {result.error && <p className="small" style={{ color: "var(--bad)" }}>{result.error}</p>}
      {body && <pre className="log yaml probe-body">{body}</pre>}
      {result.curl && (
        <div className="probe-curl">
          <code className="mono small">{result.curl}</code>
          <button className="icon-btn" title="Copy curl" onClick={() => navigator.clipboard?.writeText(result.curl)}>
            <Copy size={13} />
          </button>
        </div>
      )}
    </div>
  );
}

export function ProbeButton({ runId, step, output, probe, onResult, disabled }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  async function ping() {
    setBusy(true);
    setErr(null);
    try {
      onResult(await api.probe(runId, step, output, probe.name));
    } catch (e) {
      setErr(e.detail ?? String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <span className="probe-btn">
      <button className={cx("btn", { busy })} onClick={ping} disabled={busy || disabled} title={`${probe.method} ${probe.path} → expect ${probe.expect}`}>
        <Radio size={13} className={busy ? "spin" : undefined} /> {busy ? "Pinging…" : `Ping ${probe.name}`}
      </button>
      {err && <span className="small" style={{ color: "var(--bad)" }}>{err}</span>}
    </span>
  );
}

function EnvRow({ env, label, entry, onResult }) {
  if (!entry) return null;
  const state = liveness(entry);
  return (
    <div className="endpoint-env">
      <div className="endpoint-env-head">
        <span className="label">{label}</span>
        <LiveDot state={state} />
        <a className="mono small link endpoint-url" href={entry.value} target="_blank" rel="noreferrer" title={entry.value}>
          {entry.value} <ExternalLink size={11} />
        </a>
        <button className="icon-btn" title="Copy URL" onClick={() => navigator.clipboard?.writeText(entry.value)}>
          <Copy size={13} />
        </button>
        <span className="small muted">
          run {entry.run_id} · {entry.run_status}
          {!entry.expected_live && " · undone, the URL is history"}
        </span>
      </div>
    </div>
  );
}

export default function Endpoints({ endpoints = [], run }) {
  const [results, setResults] = useState({}); // `${env}:${step}.${name}` -> last probe answer
  const [history, setHistory] = useState([]);
  const runId = run?.id;

  useEffect(() => {
    if (!runId) return setHistory([]);
    let alive = true;
    api.probes(runId).then((h) => alive && setHistory(h)).catch(() => alive && setHistory([]));
    return () => {
      alive = false;
    };
  }, [runId, results]);

  if (!endpoints.length) {
    return (
      <div className="empty">
        <h2>No outputs declared</h2>
        <p>A step declares `outputs` (for example the deployed service's URL) and `probes` that prove it answers. This pipeline declares none.</p>
      </div>
    );
  }

  return (
    <div className="endpoints">
      {endpoints.map((e) => (
        <article className="card endpoint-card" key={`${e.step}.${e.name}`}>
          <header className="card-head">
            <div className="card-title">
              <strong className="mono">
                {e.step}.{e.name}
              </strong>
              <span className="muted">{e.description}</span>
            </div>
            <span className="muted small">
              {e.probes.length} probe{e.probes.length === 1 ? "" : "s"}
            </span>
          </header>
          {!e.production && !e.rehearsal && <p className="card-body muted">No value yet: it appears when a Rehearse or Deploy runs this step.</p>}
          {["production", "rehearsal"].map((env) => {
            const entry = e[env];
            if (!entry) return null;
            const key = `${env}:${e.step}.${e.name}`;
            return (
              <div key={env} className="endpoint-block">
                <EnvRow env={env} label={env} entry={entry} />
                <div className="probe-row">
                  {e.probes.map((p) => (
                    <ProbeButton key={p.name} runId={entry.run_id} step={e.step} output={e.name} probe={p} onResult={(r) => setResults((cur) => ({ ...cur, [key]: r }))} />
                  ))}
                  {!entry.expected_live && <span className="small faint">expect 403: AWS refuses a URL that no longer exists</span>}
                </div>
                <ProbeResult result={results[key]} />
              </div>
            );
          })}
        </article>
      ))}

      {run && (
        <section className="report-section">
          <h3>Probe history · {run.mode} {run.id}</h3>
          {history.length === 0 ? (
            <p className="muted small">No probes sent for this run yet.</p>
          ) : (
            <table className="report-table">
              <tbody>
                {history.map((h, i) => (
                  <tr key={i}>
                    <td>
                      <Pill tone={h.ok ? "green" : h.status ? "red" : "grey"}>{h.status ?? "—"}</Pill>
                    </td>
                    <td className="mono">
                      {h.step}.{h.output} · {h.probe}
                    </td>
                    <td className="muted">{h.elapsed_ms != null ? `${h.elapsed_ms} ms` : h.error}</td>
                    <td className="mono muted">{h.request_id ?? ""}</td>
                    <td className="muted">{fmtAgo(h.checked)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}
    </div>
  );
}
