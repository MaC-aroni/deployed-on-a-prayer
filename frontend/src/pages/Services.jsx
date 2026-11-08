import { useCallback, useEffect, useState } from "react";
import { ChevronDown, ChevronRight, ExternalLink, Radio } from "lucide-react";
import { LiveDot, ProbeResult, liveness } from "../components/Endpoints.jsx";
import { EmptyState } from "../components/Shell.jsx";
import { SkeletonPage } from "../components/Skeleton.jsx";
import { Pill } from "../components/StatusIcon.jsx";
import { api, fmtAgo } from "../mac/api.js";
import { Link } from "../router.jsx";
import { cx } from "../lib.js";

// Active services: every endpoint a finished pipeline produced, with whether it should be live,
// what the last probe said, and a Ping button that asks AWS right now. Rows come from
// GET /api/mac/services/active (docs/planning-api.md).

export default function Services() {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [withRehearsal, setWithRehearsal] = useState(false);
  const [open, setOpen] = useState({});
  const [results, setResults] = useState({});
  const [pinging, setPinging] = useState({});

  const load = useCallback(() => api.activeServices().then((r) => (setRows(r), setError(null))).catch(setError), []);
  useEffect(() => {
    load();
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, [load]);

  if (error) return <EmptyState title="Backend unreachable" body={error.detail} />;
  if (!rows) return <SkeletonPage rows={3} cols={5} />;

  const entries = rows.flatMap((r) =>
    ["production", ...(withRehearsal ? ["rehearsal"] : [])].filter((env) => r[env]).map((env) => ({ key: `${r.migration}/${r.step}.${r.name}/${env}`, env, row: r, entry: r[env] })),
  );

  async function ping(item, probe) {
    const k = `${item.key}:${probe.name}`;
    setPinging((p) => ({ ...p, [k]: true }));
    try {
      const res = await api.probe(item.entry.run_id, item.row.step, item.row.name, probe.name);
      setResults((cur) => ({ ...cur, [item.key]: res }));
      setOpen((o) => ({ ...o, [item.key]: true }));
      load();
    } catch (e) {
      setResults((cur) => ({ ...cur, [item.key]: { ok: false, status: null, error: e.detail ?? String(e), method: probe.method, url: item.entry.value, checked: Date.now() / 1000 } }));
      setOpen((o) => ({ ...o, [item.key]: true }));
    } finally {
      setPinging((p) => ({ ...p, [k]: false }));
    }
  }

  return (
    <>
      <div className="page-head">
        <h1>Services</h1>
        <p className="muted">What the pipelines put in AWS. A finished Deploy adds its endpoints here; Ping sends a signed request and shows AWS's answer, request id included.</p>
      </div>

      <div className="metrics">
        <div className="metric">
          <span className="label">Endpoints</span>
          <span className="metric-value">{entries.length}</span>
          <span className="metric-sub">{withRehearsal ? "production and rehearsal" : "in production"}</span>
        </div>
        <div className="metric">
          <span className="label">On</span>
          <span className="metric-value">{entries.filter((i) => liveness({ ...i.entry, last_probe: results[i.key] ?? i.entry.last_probe }) === "on").length}</span>
          <span className="metric-sub">answered their last probe</span>
        </div>
        <div className="metric">
          <span className="label">Not probed</span>
          <span className="metric-value">{entries.filter((i) => liveness({ ...i.entry, last_probe: results[i.key] ?? i.entry.last_probe }) === "unknown").length}</span>
          <span className="metric-sub">live by record, never pinged</span>
        </div>
      </div>

      <div className="toolbar">
        <span className="label">Endpoints</span>
        <span className="spacer" />
        <label className="toggle-row">
          <span>Include rehearsal history</span>
          <button type="button" role="switch" aria-checked={withRehearsal} className={cx("toggle", { on: withRehearsal })} onClick={() => setWithRehearsal((v) => !v)}>
            <span className="toggle-knob" />
          </button>
        </label>
      </div>

      <div className="table services-table">
        <div className="tr th">
          <div>Status</div>
          <div>Service</div>
          <div>Endpoint</div>
          <div>Last probe</div>
          <div>Ping</div>
        </div>
        {entries.map((item) => {
          const last = results[item.key] ?? item.entry.last_probe;
          const state = liveness({ ...item.entry, last_probe: last });
          const isOpen = Boolean(open[item.key]);
          return (
            <div key={item.key} className={cx("service-row", { open: isOpen })}>
              <button type="button" className="tr row-btn" onClick={() => setOpen((o) => ({ ...o, [item.key]: !isOpen }))}>
                <div className="cell-status">
                  <LiveDot state={state} pulsing={Object.keys(pinging).some((k) => k.startsWith(item.key) && pinging[k])} />
                  {item.env === "rehearsal" && <Pill tone="grey">rehearsal</Pill>}
                </div>
                <div className="cell-title">
                  <span className="row-title">{item.row.service}</span>
                  <span className="row-meta">
                    <Link to={item.row.href} className="link mono" onClick={(e) => e.stopPropagation()}>
                      {item.row.migration}
                    </Link>
                    <span className="mono">
                      {item.row.step}.{item.row.name}
                    </span>
                  </span>
                </div>
                <div className="cell-title">
                  <a className="mono small link endpoint-url" href={item.entry.value} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} title={item.entry.value}>
                    {item.entry.value} <ExternalLink size={11} />
                  </a>
                  <span className="muted small">
                    run {item.entry.run_id} · {item.entry.run_status}
                    {!item.entry.expected_live && " · undone"}
                  </span>
                </div>
                <div className="small">
                  {last ? (
                    <>
                      <Pill tone={last.ok ? "green" : last.status ? "red" : "grey"}>{last.status ?? "no answer"}</Pill>{" "}
                      <span className="muted">
                        {last.elapsed_ms != null ? `${last.elapsed_ms} ms · ` : ""}
                        {fmtAgo(last.checked)}
                      </span>
                    </>
                  ) : (
                    <span className="faint">never</span>
                  )}
                </div>
                <div className="cell-actions" onClick={(e) => e.stopPropagation()}>
                  {item.row.probes.length === 0 && <span className="faint small">no probes declared</span>}
                  {item.row.probes.map((p) => (
                    <button key={p.name} className="btn" onClick={() => ping(item, p)} disabled={pinging[`${item.key}:${p.name}`]} title={`${p.method} ${p.path} → expect ${p.expect}`}>
                      <Radio size={13} className={pinging[`${item.key}:${p.name}`] ? "spin" : undefined} /> {p.name}
                    </button>
                  ))}
                  {isOpen ? <ChevronDown size={14} className="faint" /> : <ChevronRight size={14} className="faint" />}
                </div>
              </button>
              {isOpen && (
                <div className="service-detail">
                  <ProbeResult result={last} />
                  {!last && <p className="muted small">No probe yet. Ping one to see AWS answer.</p>}
                </div>
              )}
            </div>
          );
        })}
        {entries.length === 0 && (
          <div className="tr empty-row empty-pipelines">
            <strong>No active services yet.</strong>
            <span className="muted">A pipeline's Deploy finishing adds its endpoints here. Rehearsals are undone at the end, so they only appear with the toggle above.</span>
            <Link to="/" className="btn btn-primary">
              Pipelines
            </Link>
          </div>
        )}
      </div>
    </>
  );
}
