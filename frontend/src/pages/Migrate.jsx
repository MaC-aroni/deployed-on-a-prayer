import { useCallback, useEffect, useMemo, useState } from "react";
import { BookOpen, ClipboardCheck, ExternalLink, FileCode2, GitPullRequest, Github, Loader2, Rocket, Search, Sparkles, Users, Wand2 } from "lucide-react";
import Menu from "../components/Menu.jsx";
import { EmptyState, useAuth } from "../components/Shell.jsx";
import { SkeletonPage } from "../components/Skeleton.jsx";
import StatusIcon, { Pill } from "../components/StatusIcon.jsx";
import { api, fmtAgo } from "../mac/api.js";
import { Link, navigate } from "../router.jsx";
import { MODE_LABEL, runMeta } from "../status.js";
import { cx } from "../lib.js";

// Build → Migration. One card per migration: the migration.yaml files in mac-migrations (mirrored by
// the server; docs/api.md → Migrations). Each card carries the three things a person reads before
// pressing Build: the Confluence page that describes the migration (MaC writes it on request), the
// design review page Build writes for Tech Risk, and the migration.yaml itself on GitHub.

const ACTIVE = new Set(["running", "waiting", "rolling_back"]);
const MODES = ["build", "rehearse", "deploy"];

function Toast({ toast, onClose }) {
  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(onClose, 8000);
    return () => clearTimeout(id);
  }, [toast, onClose]);
  if (!toast) return null;
  return (
    <div className={cx("toast", `tone-${toast.tone}`)} role="status" onClick={onClose}>
      {toast.text}
    </div>
  );
}

// The run that best describes where a migration is: an active one, else the newest.
function headline(m) {
  if (m.active_run) return m.active_run;
  const runs = MODES.map((mode) => m.latest?.[mode]).filter(Boolean);
  if (!runs.length) return null;
  return runs.sort((a, b) => b.updated - a.updated)[0];
}

function Step({ label, run }) {
  const meta = run ? runMeta(run.status, run.mode) : null;
  return (
    <span className={cx("step-dot", `tone-${meta ? meta.tone : "grey"}`)} title={run?.reason ?? ""}>
      <span className="step-dot-mark" />
      <span className="step-dot-label">{label}</span>
      <span className="step-dot-text">{meta ? `${meta.label.toLowerCase()} · ${fmtAgo(run.updated)}` : "not yet"}</span>
    </span>
  );
}

// One attachment row: an icon, what it is, and on the right what we know about it.
function Attachment({ icon, label, meta, href, to, onClick, busy, disabled, tone, title }) {
  const inner = (
    <>
      <span className="attachment-main">
        {icon}
        <span>{label}</span>
      </span>
      <span className="attachment-meta">
        {meta}
        {href && <ExternalLink size={11} />}
      </span>
    </>
  );
  const className = cx("attachment", tone && `attachment-${tone}`, { busy });
  if (href) {
    return (
      <a className={className} href={href} target="_blank" rel="noreferrer" title={title}>
        {inner}
      </a>
    );
  }
  if (to) {
    return (
      <Link className={className} to={to} title={title}>
        {inner}
      </Link>
    );
  }
  if (onClick) {
    return (
      <button type="button" className={className} onClick={onClick} disabled={disabled || busy} title={title}>
        {inner}
      </button>
    );
  }
  return (
    <span className={cx(className, "is-empty")} title={title} aria-disabled>
      {inner}
    </span>
  );
}

function MigrationCard({ m, health, locked, busy, onBuild, onDescribe, onPublish }) {
  const head = headline(m);
  const hm = head ? runMeta(head.status, head.mode) : null;
  const page = m.page;
  const pageDate = page?.written ? new Date(page.written * 1000).toLocaleDateString([], { month: "short", day: "numeric" }) : null;
  const madeBy = page?.generated ? `written by MaC${page.model ? ` (${page.model.split("/").pop()})` : ""}${pageDate ? ` on ${pageDate}` : ""}` : "in Confluence";
  const pipelineHref = `/migrations/${encodeURIComponent(m.name)}`;
  const noConfluence = health ? !health.confluence : false;

  let confluence;
  if (page?.writing) {
    confluence = <Attachment icon={<Loader2 size={14} className="spin" />} label="Confluence page" meta="MaC is writing it…" to={`/agents/${page.writing}`} tone="violet" title="An agent is reading the repositories and the knowledge base and writing the page. Click to watch." />;
  } else if (page?.url) {
    confluence = <Attachment icon={<BookOpen size={14} />} label="Confluence page" meta={<span className={cx({ "made-by": page.generated })}>{page.generated && <Sparkles size={11} />} {madeBy}</span>} href={page.url} title={`${page.title} · opens Confluence`} />;
  } else if (page?.local && noConfluence) {
    confluence = <Attachment icon={<BookOpen size={14} />} label="Confluence page" meta={<span className="made-by"><Sparkles size={11} /> written by MaC · console copy</span>} to={`/knowledge/${page.id}`} title="Confluence isn't configured here, so the console shows the page MaC wrote" />;
  } else if (page?.local) {
    confluence = <Attachment icon={<BookOpen size={14} />} label="Create in Confluence" meta="page written, not published yet" onClick={() => onPublish(page.id)} busy={busy === `publish:${m.name}`} tone="violet" title="MaC wrote the page; publish it to Confluence and link it here" />;
  } else {
    confluence = <Attachment icon={<Sparkles size={14} />} label="Generate Confluence page" meta={busy === `describe:${m.name}` ? "starting…" : "an agent reads GitHub and the knowledge base"} onClick={() => onDescribe(m)} busy={busy === `describe:${m.name}`} tone="violet" title="No page describes this migration yet. An agent reads migration.yaml, the repositories it runs and the knowledge base it cites, writes the page and publishes it to Confluence." />;
  }

  const design = m.design_page?.url ? (
    <Attachment icon={<ClipboardCheck size={14} />} label="Design review page" meta={m.design_page.current ? "written by Build" : "outdated · the next Build rewrites it"} href={m.design_page.url} tone={m.design_page.current ? undefined : "amber"} title="The design document Build wrote for the Tech Risk ticket" />
  ) : (
    <Attachment icon={<ClipboardCheck size={14} />} label="Design review page" meta="written when you Build" title="Build asks the LLM to write the Tech Risk design page and links it from the ticket" />
  );

  const yaml = m.source?.url ? (
    <Attachment icon={<FileCode2 size={14} />} label="migration.yaml" meta={m.source.repo?.split("/").pop() ?? "GitHub"} href={m.source.url} title={`${m.source.repo}/${m.source.path} on GitHub`} />
  ) : (
    <Attachment icon={<FileCode2 size={14} />} label="migration.yaml" meta={m.source?.path ?? m.path} title="This file is read from the server's disk; it isn't on GitHub" />
  );

  const building = busy === `build:${m.name}`;
  const active = m.active_run && ACTIVE.has(m.active_run.status);
  const primary = active
    ? { label: `${MODE_LABEL[m.active_run.mode]} in progress · open`, icon: <Wand2 size={14} />, onClick: () => navigate(`${pipelineHref}?run=${m.active_run.id}`), title: "A run is in progress; open the pipeline" }
    : { label: "Build Migration Pipeline", icon: <Rocket size={14} />, onClick: () => onBuild(m), title: "Build: validate the spec, lock the commits, check guardrails, raise the approvals, write the design page, terraform plan" };

  return (
    <article className={cx("card service-card migration-card", { invalid: m.valid === false })}>
      <header className="card-head">
        <div className="card-title">
          <strong>{m.service ?? m.name}</strong>
          <span className="muted">
            <span className="mono">{m.name}</span>
            {m.owner_team && (
              <>
                {" · "}
                <Users size={11} /> {m.owner_team}
              </>
            )}
          </span>
        </div>
        {m.valid === false ? (
          <Pill tone="red" title={m.problems?.join("; ")}>
            <StatusIcon status="failed" size={14} /> invalid spec
          </Pill>
        ) : hm ? (
          <Pill tone={hm.tone} title={head.reason ?? ""}>
            <StatusIcon status={hm.icon} size={14} /> {MODE_LABEL[head.mode]} {hm.label.toLowerCase()}
          </Pill>
        ) : (
          <Pill tone="grey">not built yet</Pill>
        )}
        <Menu
          label={`More for ${m.name}`}
          items={[
            { label: "Build Migration Pipeline", detail: "validate · lock · approvals · plan", icon: <Rocket size={14} />, onClick: () => onBuild(m), disabled: Boolean(active) },
            { label: "Open pipeline", detail: "the DAG, runs and approvals", icon: <Wand2 size={14} />, onClick: () => navigate(pipelineHref) },
            { separator: true },
            { label: page?.url || page?.local ? "Rewrite the Confluence page" : "Generate the Confluence page", detail: "an agent reads GitHub and Confluence", icon: <Sparkles size={14} />, onClick: () => onDescribe(m), disabled: Boolean(page?.writing) },
            ...(page?.url ? [{ label: "Open the Confluence page", icon: <BookOpen size={14} />, onClick: () => window.open(page.url, "_blank", "noreferrer") }] : []),
            ...(page?.id ? [{ label: "Page as the console shows it", icon: <BookOpen size={14} />, onClick: () => navigate(`/knowledge/${page.id}`) }] : []),
            ...(m.design_page?.url ? [{ label: "Open the design review page", icon: <ClipboardCheck size={14} />, onClick: () => window.open(m.design_page.url, "_blank", "noreferrer") }] : []),
            ...(m.source?.url ? [{ label: "migration.yaml on GitHub", icon: <Github size={14} />, onClick: () => window.open(m.source.url, "_blank", "noreferrer") }] : []),
          ]}
        />
      </header>

      <p className="card-body">{m.description ?? (m.problems?.length ? m.problems.join("; ") : "")}</p>

      {m.valid !== false && (
        <>
          <div className="repo-list">
            {(m.stages ?? []).map((s) => (
              <span key={s} className="stage-chip">
                {s}
              </span>
            ))}
            <span className="muted small">
              {m.steps} steps · {m.approvals} approvals{m.breakpoints?.length ? ` · ${m.breakpoints.length} breakpoint${m.breakpoints.length === 1 ? "" : "s"}` : ""} · {m.target?.region}
            </span>
          </div>

          <div className="attachments">
            {confluence}
            {design}
            {yaml}
          </div>

          <div className="stepper">
            {MODES.map((mode) => (
              <Step key={mode} label={MODE_LABEL[mode]} run={m.latest?.[mode]} />
            ))}
          </div>

          <footer className="card-foot">
            <button className={cx("btn btn-primary", { hint: locked })} onClick={primary.onClick} disabled={building} title={primary.title}>
              {building ? <Loader2 size={14} className="spin" /> : primary.icon} {building ? "Starting Build…" : primary.label}
            </button>
            <Link to={pipelineHref} className="btn btn-secondary">
              <Wand2 size={14} /> Open pipeline
            </Link>
          </footer>
        </>
      )}
      {m.valid === false && (
        <footer className="card-foot">
          <Link to={pipelineHref} className="btn btn-secondary">
            See the problems
          </Link>
        </footer>
      )}
    </article>
  );
}

export default function Migrate() {
  const { locked, health } = useAuth();
  const noLlm = health ? !health.llm : false;
  const [rows, setRows] = useState(null);
  const [source, setSource] = useState(null);
  const [error, setError] = useState(null);
  const [toast, setToast] = useState(null);
  const [busy, setBusy] = useState(null);
  const [q, setQ] = useState("");
  const [planning, setPlanning] = useState(false);
  const [service, setService] = useState("");
  const [services, setServices] = useState([]);

  const load = useCallback(
    () =>
      Promise.all([api.migrations(), api.migrationsSource().catch(() => null)])
        .then(([m, s]) => {
          setRows(m);
          setSource(s);
          setError(null);
        })
        .catch(setError),
    [],
  );
  useEffect(() => {
    load();
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, [load]);
  useEffect(() => {
    if (!planning || services.length) return;
    api
      .services()
      .then((d) => setServices(d.services.map((s) => s.name)))
      .catch(() => {});
  }, [planning, services.length]);

  const closeToast = useCallback(() => setToast(null), []);
  const fail = (e) => setToast({ tone: e.status === 409 ? "amber" : e.status === 401 ? "blue" : "red", text: e.detail ?? String(e) });

  async function build(m) {
    setBusy(`build:${m.name}`);
    try {
      const run = await api.start(m.name, "build");
      navigate(`/migrations/${encodeURIComponent(m.name)}?run=${run.id}`);
    } catch (e) {
      fail(e);
      setBusy(null);
    }
  }
  async function describe(m) {
    setBusy(`describe:${m.name}`);
    try {
      const run = await api.describe(m.name);
      navigate(`/agents/${run.id}`);
    } catch (e) {
      fail(e);
      setBusy(null);
    }
  }
  async function publish(pageId, name) {
    setBusy(`publish:${name}`);
    try {
      const res = await api.publishKnowledge(pageId);
      setToast({ tone: "green", text: `Confluence page created: ${res.url}` });
      await load();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(null);
    }
  }
  async function plan(e) {
    e?.preventDefault();
    if (!service.trim()) return;
    setBusy("plan");
    try {
      const run = await api.plan({ service: service.trim(), build: false, pr: true });
      navigate(`/migrate/${run.id}`);
    } catch (err) {
      fail(err);
      setBusy(null);
    }
  }

  const shown = useMemo(
    () => (rows ?? []).filter((m) => !q || `${m.name} ${m.service ?? ""} ${m.owner_team ?? ""}`.toLowerCase().includes(q.toLowerCase())),
    [rows, q],
  );

  if (error) return <EmptyState title="Backend unreachable" body={error.detail} />;
  if (!rows) return <SkeletonPage rows={3} cols={3} />;

  const documented = rows.filter((m) => m.page?.url || m.page?.local).length;
  const reviewed = rows.filter((m) => m.design_page?.url).length;
  const deployed = rows.filter((m) => m.latest?.deploy?.status === "succeeded").length;
  const repoLabel = source?.repo ?? "the migrations folder";
  const syncLine = source?.repo
    ? source.synced
      ? `mirrored from ${source.repo} ${fmtAgo(source.synced)}${source.error ? ` · last check failed: ${source.error}` : ""}`
      : source.error
        ? `${source.repo} couldn't be read yet (${source.error}) · showing the bundled examples`
        : `mirroring ${source.repo}…`
    : `read from ${source?.dir ?? "disk"}`;

  return (
    <>
      <Toast toast={toast} onClose={closeToast} />

      <div className="page-head">
        <h1>Migration</h1>
        <p className="muted">
          Every migration is a <span className="mono">migration.yaml</span> in{" "}
          {source?.url ? (
            <a className="link" href={source.url} target="_blank" rel="noreferrer">
              {repoLabel} <ExternalLink size={11} />
            </a>
          ) : (
            repoLabel
          )}
          , reviewed and merged like code. Each card has the Confluence page that describes it, the design review page Build writes, and the file itself. Build Migration Pipeline runs it.
        </p>
      </div>

      <div className="metrics">
        <div className="metric">
          <span className="label">Migrations</span>
          <span className="metric-value">{rows.length}</span>
          <span className="metric-sub">{syncLine}</span>
        </div>
        <div className="metric">
          <span className="label">Described</span>
          <span className="metric-value">{documented}</span>
          <span className="metric-sub">with a Confluence page · {rows.length - documented} to generate</span>
        </div>
        <div className="metric">
          <span className="label">Design reviews</span>
          <span className="metric-value">{reviewed}</span>
          <span className="metric-sub">design pages written by Build</span>
        </div>
        <Link to="/services" className="metric metric-link" title="Open Services">
          <span className="label">Deployed</span>
          <span className="metric-value">{deployed}</span>
          <span className="metric-sub">with a passing Deploy · see Services</span>
        </Link>
      </div>

      <div className="toolbar">
        <label className="filter">
          <Search size={15} />
          <input placeholder="Filter migrations" value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
        <span className="spacer" />
        <button className={cx("btn btn-secondary", { hint: locked })} onClick={() => setPlanning((v) => !v)} disabled={noLlm} title={noLlm ? "No LLM is configured here" : "Nemotron plans a new migration.yaml from the knowledge base and opens a PR into mac-migrations"}>
          <GitPullRequest size={14} /> Plan a new migration
        </button>
      </div>
      {planning && (
        <form className="add-repo" onSubmit={plan}>
          <Sparkles size={16} className="muted" />
          <input className="filter-input add-repo-input" list="mac-services" placeholder="Service to migrate, e.g. ClaimsAdjudicationService" value={service} onChange={(e) => setService(e.target.value)} autoFocus aria-label="Service name" />
          <datalist id="mac-services">
            {services.map((s) => (
              <option key={s} value={s} />
            ))}
          </datalist>
          <button type="submit" className={cx("btn btn-primary", { hint: locked })} disabled={busy === "plan" || !service.trim()}>
            <Sparkles size={14} /> {busy === "plan" ? "Launching…" : "Plan and open a PR"}
          </button>
          <span className="muted small">The planner reads the knowledge base, writes migration.yaml, validates it, and opens a pull request into {repoLabel}. It shows here once merged.</span>
        </form>
      )}

      <div className="cards migration-cards">
        {shown.map((m) => (
          <MigrationCard key={m.name} m={m} health={health} locked={locked} busy={busy} onBuild={build} onDescribe={describe} onPublish={(pageId) => publish(pageId, m.name)} />
        ))}
      </div>
      {shown.length === 0 && rows.length > 0 && <EmptyState title="No migrations match" body="Clear the filter to see them all." />}
      {rows.length === 0 && (
        <EmptyState title="No migrations yet" body={`Nothing under migrations/ in ${repoLabel}. Plan one above: the planner opens a pull request, and the migration appears here once it's merged.`} />
      )}
    </>
  );
}
