import { Fragment, useCallback, useEffect, useState } from "react";
import { Bot, ChevronDown, ChevronRight, ExternalLink, RefreshCw } from "lucide-react";
import { EmptyState } from "./Shell.jsx";
import { Pill } from "./StatusIcon.jsx";
import { api, fmtAgo } from "../mac/api.js";
import { cx } from "../lib.js";

// The Cost tab: what the migration costs on AWS, worked out by code from Terraform's plan, the
// usage figures in Confluence and AWS's prices, with the source of every number
// (docs/api.md, "Cost estimate"). The server does the maths; this only shows it.

export function fmtUsd(v) {
  if (v == null) return "—";
  if (v > 0 && v < 0.01) return "< $0.01";
  return `$${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

// The table shows a tiered price by its first tier; the full tiers are in the row's sources.
function shortRate(rate = "") {
  const i = rate.indexOf(", then ");
  return i < 0 ? rate : `${rate.slice(0, i)}, then tiered`;
}

function fmtQty(v) {
  if (v == null) return "";
  return v.toLocaleString(undefined, { maximumFractionDigits: v < 10 ? 4 : 1 });
}

// "deploy_service/aws_lambda_function.service" -> { step: "deploy_service", address: "aws_lambda_function.service" }
function splitSubject(subject = "") {
  const i = subject.indexOf("/");
  return i < 0 ? { step: "", address: subject } : { step: subject.slice(0, i), address: subject.slice(i + 1) };
}

// The figure that's missing, in words: "deploy_service/…service:avg_billed_duration_ms" -> "avg billed duration ms"
function missingLabel(missing = "") {
  const metric = missing.includes(":") ? missing.slice(missing.lastIndexOf(":") + 1) : missing;
  return metric.replaceAll("_", " ");
}

// The cost line for the header chip and the tab count; null when there's nothing to show.
export function costOf(run) {
  const c = run?.report?.cost;
  return c && (c.status === "complete" || c.status === "partial") ? c : null;
}

function Source({ input }) {
  const s = input.source ?? {};
  if (s.kind === "confluence") {
    return (
      <div className="cost-src">
        <span className="cost-tag tag-confluence">Confluence</span>
        <span>
          <q>{s.quote}</q>{" "}
          <span className="faint">
            · {s.url ? (
              <a className="link" href={s.url} target="_blank" rel="noreferrer">
                {s.page} › {s.heading} <ExternalLink size={11} />
              </a>
            ) : (
              <>
                {s.page} › {s.heading}
              </>
            )}
            {input.as_written ? ` · ${input.name.replaceAll("_", " ")} = ${input.as_written.replaceAll("_", " ")}` : ""}
          </span>
        </span>
      </div>
    );
  }
  if (s.kind === "terraform") {
    return (
      <div className="cost-src">
        <span className="cost-tag tag-terraform">Terraform</span>
        <span className="mono">
          {s.step} · {s.address}.{s.attribute} = {String(input.value)}
          {s.note && <span className="faint"> ({s.note})</span>}
        </span>
      </div>
    );
  }
  return (
    <div className="cost-src">
      <span className="cost-tag tag-rule">AWS rule</span>
      <span>
        {s.url ? (
          <a className="link" href={s.url} target="_blank" rel="noreferrer">
            {s.text} <ExternalLink size={11} />
          </a>
        ) : (
          s.text
        )}
      </span>
    </div>
  );
}

function PriceSource({ price }) {
  if (!price) return null;
  return (
    <div className="cost-src">
      <span className="cost-tag tag-price">AWS price</span>
      <span className="mono">
        {price.rate} · SKU {price.sku} · effective {String(price.effective_date ?? "").slice(0, 10)} ·{" "}
        {price.source === "snapshot" ? "saved copy of the Price List" : "Price List, fetched live"}
        {price.offer_url && (
          <>
            {" "}
            <a className="link" href={price.offer_url} target="_blank" rel="noreferrer">
              offer file <ExternalLink size={11} />
            </a>
          </>
        )}
      </span>
    </div>
  );
}

function Lines({ title, lines }) {
  const [open, setOpen] = useState(null);
  if (!lines?.length) return null;
  return (
    <section className="report-section">
      <h3>{title}</h3>
      <div className="cost-table-wrap">
        <table className="report-table cost-table">
          <thead>
            <tr>
              <th />
              <th>What</th>
              <th>Resource</th>
              <th>How it's worked out</th>
              <th>AWS price</th>
              <th className="num">USD</th>
            </tr>
          </thead>
          <tbody>
            {lines.map((line) => {
              const { step, address } = splitSubject(line.subject);
              const isOpen = open === line.id;
              const toggle = () => setOpen(isOpen ? null : line.id);
              return (
                <Fragment key={line.id}>
                  <tr className={cx("cost-row", { open: isOpen })} onClick={toggle} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && toggle()} aria-expanded={isOpen}>
                    <td className="cost-caret">{isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</td>
                    <td>{line.what}</td>
                    <td>
                      <span className="mono">{address}</span>
                      <div className="faint small">{step}</div>
                    </td>
                    <td className="mono cost-formula">{line.formula}</td>
                    <td className="small" title={line.price?.rate}>{shortRate(line.price?.rate)}</td>
                    <td className="num">{fmtUsd(line.usd)}</td>
                  </tr>
                  {isOpen && (
                    <tr className="cost-sources-row">
                      <td />
                      <td colSpan={5}>
                        <div className="cost-sources">
                          {(line.inputs ?? []).map((input, i) => (
                            <Source key={i} input={input} />
                          ))}
                          <PriceSource price={line.price} />
                          <div className="faint small">
                            Quantity: {fmtQty(line.quantity)} {line.unit}
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default function CostPanel({ name, build, onReadUsage, readDisabled, readHint }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  // The estimate recalculated now (new usage figures show up without another Build); the
  // Build's own report.cost is the fallback while it loads or if the call fails.
  const load = useCallback(async () => {
    if (!build) return;
    setLoading(true);
    try {
      setData(await api.cost(name));
      setError(null);
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }, [name, build]);

  useEffect(() => {
    load();
  }, [load, build?.updated]);

  if (!build) {
    return <EmptyState title="No Build yet" body="Build records what Terraform will create. Then the usage reader finds the figures in Confluence, and the cost is worked out here." />;
  }

  const view = data?.estimate ?? build.report?.cost;
  const readButton = (
    <button className="btn" onClick={onReadUsage} disabled={readDisabled} title={readHint}>
      <Bot size={14} className="ai-mark" /> Read usage figures
    </button>
  );

  if (!view || view.status === "unavailable") {
    return (
      <EmptyState title="No cost estimate yet" body={view?.reason ?? error?.detail ?? "Build again to calculate it."}>
        <div className="toolbar" style={{ justifyContent: "center" }}>
          {readButton}
        </div>
      </EmptyState>
    );
  }

  const partial = view.status === "partial";
  const savings = view.savings && !view.savings.partial ? view.savings : null;
  const missing = [...(view.unpriced ?? []), ...(view.unknown_resources ?? [])];
  const usage = data?.usage;

  return (
    <div className="report cost">
      <div className="report-head">
        <Pill tone={partial ? "amber" : "green"}>{partial ? "Partial estimate" : "Complete estimate"}</Pill>
        <span className="muted small">
          Worked out by code from Build {data?.build ?? build.id}'s Terraform plan, the usage figures in Confluence
          {usage?.read_at ? ` (read ${fmtAgo(usage.read_at)}${usage.model ? ` by ${usage.model}` : ""})` : ""} and AWS's prices.
        </span>
        <div className="toolbar cost-actions">
          {readButton}
          <button className="btn" onClick={load} disabled={loading} title="Recalculate with the latest figures and prices">
            <RefreshCw size={14} /> Recalculate
          </button>
        </div>
      </div>

      <div className="metrics cost-metrics">
        <div className="metric">
          <span className="metric-sub">AWS per month</span>
          <span className="metric-value">{fmtUsd(view.monthly_usd)}</span>
          <span className="metric-sub">{partial ? "for what can be priced so far" : `${fmtUsd(view.yearly_usd)} a year`}</span>
        </div>
        <div className="metric">
          <span className="metric-sub">One-time</span>
          <span className="metric-value">{fmtUsd(view.one_time_usd)}</span>
          <span className="metric-sub">{view.one_time?.length ? view.one_time.map((l) => l.what).join(", ") : "nothing documented"}</span>
        </div>
        <div className="metric">
          <span className="metric-sub">On-prem today</span>
          <span className="metric-value">{view.onprem ? fmtUsd(view.onprem.monthly_usd) : "—"}</span>
          <span className="metric-sub">{view.onprem ? `per month, ${view.onprem.items.length} cost lines from Finance` : "no on-prem costs documented"}</span>
        </div>
        <div className={cx("metric", { "metric-held": !savings })}>
          <span className="metric-sub">Saving</span>
          {savings ? (
            <>
              <span className="metric-value">{fmtUsd(savings.yearly_usd)}</span>
              <span className="metric-sub">a year · {savings.percent}% less than today</span>
            </>
          ) : (
            <>
              <span className="metric-value metric-pending">{view.onprem ? "Shown when complete" : "—"}</span>
              <span className="metric-sub">
                {view.onprem ? `${missing.length} item${missing.length === 1 ? "" : "s"} not priced yet, so no saving is claimed` : "needs today's costs in Confluence"}
              </span>
            </>
          )}
        </div>
      </div>

      {missing.length > 0 && (
        <div className="banner tone-amber cost-missing">
          <div>
            <strong>Not priced yet.</strong> MaC never guesses a figure; it asks the owner instead.
            <ul className="plain">
              {(view.unpriced ?? []).map((u, i) => (
                <li key={`u${i}`}>
                  <span className="mono">{splitSubject(u.subject).address}</span>: {missingLabel(u.missing)}
                  {u.question?.ticket ? (
                    <>
                      {" · "}
                      <a href={u.question.url} target="_blank" rel="noreferrer">
                        asked in {u.question.ticket} <ExternalLink size={11} />
                      </a>
                    </>
                  ) : u.question?.status ? (
                    <span className="faint"> · {u.question.status}</span>
                  ) : null}
                </li>
              ))}
              {(view.unknown_resources ?? []).map((u, i) => (
                <li key={`k${i}`}>
                  <span className="mono">{splitSubject(u.subject).address}</span>: {u.reason}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      <Lines title="Every month" lines={view.lines} />
      <Lines title="Once" lines={view.one_time} />

      {view.onprem && (
        <section className="report-section">
          <h3>What it costs today, on-prem</h3>
          <table className="report-table">
            <tbody>
              {view.onprem.items.map((item, i) => (
                <tr key={i}>
                  <td>{item.label}</td>
                  <td className="small">
                    <q>{item.source?.quote}</q>
                    <div className="faint">
                      {item.source?.url ? (
                        <a className="link" href={item.source.url} target="_blank" rel="noreferrer">
                          {item.source.page} › {item.source.heading} <ExternalLink size={11} />
                        </a>
                      ) : (
                        `${item.source?.page ?? ""} › ${item.source?.heading ?? ""}`
                      )}
                    </div>
                  </td>
                  <td className="mono small faint">{item.formula}</td>
                  <td className="num">{fmtUsd(item.usd_per_month)}/mo</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {view.free?.length > 0 && (
        <section className="report-section">
          <h3>No charge</h3>
          <ul className="plain small">
            {view.free.map((f, i) => (
              <li key={i}>
                <span className="mono">{splitSubject(f.subject).address}</span>
                <span className="muted">
                  {" "}
                  · {f.reason} ·{" "}
                  <a className="link" href={f.url} target="_blank" rel="noreferrer">
                    AWS <ExternalLink size={11} />
                  </a>
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {view.notes?.length > 0 && (
        <ul className="plain small faint cost-notes">
          {view.notes.map((n, i) => (
            <li key={i}>{n}</li>
          ))}
        </ul>
      )}
      {error && <p className="small" style={{ color: "var(--bad)" }}>Couldn't recalculate: {error.detail ?? String(error)}. Showing the Build's estimate.</p>}
    </div>
  );
}
