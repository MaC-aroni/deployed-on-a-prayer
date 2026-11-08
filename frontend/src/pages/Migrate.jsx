import { useCallback, useEffect, useMemo, useState } from "react";
import { BookOpen, ExternalLink, GitBranch, Github, Plus, Rocket, Scale, Sparkles, Trash2, Wand2 } from "lucide-react";
import Menu from "../components/Menu.jsx";
import { EmptyState, useAuth } from "../components/Shell.jsx";
import { SkeletonPage } from "../components/Skeleton.jsx";
import { Pill } from "../components/StatusIcon.jsx";
import { api, fmtAgo } from "../mac/api.js";
import { Link, navigate } from "../router.jsx";
import { runMeta } from "../status.js";
import { cx } from "../lib.js";

// Build → Migration. Every candidate shows first: the services the knowledge base documents, and
// every repository in the org. Each has two doors, its Confluence page and its GitHub repo.
// "Launch agent" on a service runs Learn (if needed) → detect or write migration.yaml → Build;
// "Learn" on an undocumented repo writes its knowledge page and raises a review ticket.

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

function Step({ label, status, text }) {
  return (
    <span className={cx("step-dot", `tone-${status}`)}>
      <span className="step-dot-mark" />
      <span className="step-dot-label">{label}</span>
      {text && <span className="step-dot-text">{text}</span>}
    </span>
  );
}

// The two doors: the Confluence page (or the console's copy of it) and the GitHub repository.
function Doors({ pageUrl, pageId, repoUrl, learn, create, busy = false, size = "sm", stop = true }) {
  const onClick = stop ? (e) => e.stopPropagation() : undefined;
  return (
    <span className={cx("doors", size)}>
      {pageUrl ? (
        <a className="btn door" href={pageUrl} target="_blank" rel="noreferrer" onClick={onClick} title="Open the Confluence page">
          <BookOpen size={14} /> Confluence <ExternalLink size={11} />
        </a>
      ) : pageId && create ? (
        <button type="button" className="btn door door-learn" onClick={(e) => (onClick?.(e), create())} disabled={busy} title="Create this page in Confluence and link it here from now on">
          <BookOpen size={14} /> {busy ? "Creating…" : "Create in Confluence"}
        </button>
      ) : pageId ? (
        <Link className="btn door" to={`/knowledge/${pageId}`} onClick={onClick} title="Confluence isn't configured here: open the console's copy of the page">
          <BookOpen size={14} /> Page
        </Link>
      ) : learn ? (
        <button type="button" className="btn door door-learn" onClick={(e) => (onClick?.(e), learn())} disabled={busy} title="Launch an agent to write this repository's knowledge page and raise a review ticket">
          <Sparkles size={14} /> {busy ? "Launching…" : "Learn"}
        </button>
      ) : (
        <span className="btn door" aria-disabled>
          <BookOpen size={14} /> no page
        </span>
      )}
      {repoUrl ? (
        <a className="btn door" href={repoUrl} target="_blank" rel="noreferrer" onClick={onClick} title="Open the repository on GitHub">
          <Github size={14} /> GitHub <ExternalLink size={11} />
        </a>
      ) : (
        <span className="btn door" aria-disabled>
          <Github size={14} /> no repo
        </span>
      )}
    </span>
  );
}

export default function Migrate() {
  const { locked, health } = useAuth();
  const noLlm = health ? !health.llm : false;
  const llmHint = noLlm ? "No LLM is configured here: set MAC_LLM_API_KEY (or NVIDIA_API_KEY) in backend/.env and restart" : undefined;
  const [data, setData] = useState(null);
  const [adding, setAdding] = useState(false);
  const [repoUrl, setRepoUrl] = useState("");
  const [plans, setPlans] = useState([]);
  const [error, setError] = useState(null);
  const [toast, setToast] = useState(null);
  const [busy, setBusy] = useState(null); // service name, repo full_name, or "ingest"
  const [withPr, setWithPr] = useState(false);

  const load = useCallback(
    () =>
      Promise.all([api.services(), api.plans().catch(() => [])])
        .then(([d, p]) => {
          setData(d);
          setPlans(p);
          setError(null);
        })
        .catch(setError),
    [],
  );
  useEffect(() => {
    load();
  }, [load]);

  const closeToast = useCallback(() => setToast(null), []);
  const fail = (e) => setToast({ tone: e.status === 409 ? "amber" : e.status === 401 ? "blue" : "red", text: e.detail ?? String(e) });

  async function launch(key, fn, to) {
    setBusy(key);
    try {
      const run = await fn();
      navigate(to(run));
    } catch (e) {
      fail(e);
      setBusy(null);
    }
  }
  const learnAll = () => launch("ingest", () => api.ingest(), (r) => `/agents/${r.id}`);
  const learnRepo = (repo) => launch(repo.full_name, () => api.learn(repo.full_name), (r) => `/agents/${r.id}`);
  const plan = (svc, opts = {}) => launch(svc.name, () => api.plan({ service: svc.name, pr: withPr, build: true, ...opts }), (r) => `/migrate/${r.id}`);
  const addRepo = (e) => {
    e?.preventDefault();
    if (!repoUrl.trim()) return;
    launch("add-repo", () => api.addRepo(repoUrl.trim()), (r) => `/agents/${r.id}`);
  };
  async function removeRepo(r) {
    try {
      await api.removeRepo(r.full_name);
      load();
    } catch (err) {
      fail(err);
    }
  }
  async function createPage(pageId) {
    setBusy(`page:${pageId}`);
    try {
      const res = await api.publishKnowledge(pageId);
      setToast({ tone: "green", text: `Confluence page created: ${res.url}` });
      await load();
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  }

  const planById = useMemo(() => Object.fromEntries(plans.map((p) => [p.run_id, p])), [plans]);

  if (error) return <EmptyState title="Backend unreachable" body={error.detail} />;
  if (!data) return <SkeletonPage rows={4} cols={4} />;

  const learnedLine = data.ingested ? `learned ${fmtAgo(data.graph_updated)}` : "not learned yet";
  const repoUrlOf = (full) => data.repos.find((r) => r.full_name.toLowerCase() === full.toLowerCase())?.url ?? `https://github.com/${full}`;

  return (
    <>
      <Toast toast={toast} onClose={closeToast} />

      <div className="page-head">
        <h1>Migration</h1>
        <p className="muted">
          Pick what to migrate. The agent learns the knowledge base, finds or writes the migration.yaml, renders the pipeline and starts Build. Knowledge base · {data.knowledge.pages} pages
          {data.knowledge.generated ? ` (${data.knowledge.generated} written by MaC)` : ""} · {learnedLine}.
        </p>
      </div>

      <div className="toolbar">
        <span className="label">Services in the knowledge base</span>
        <span className="spacer" />
        <label className="toggle-row">
          <span>Also open a PR</span>
          <button type="button" role="switch" aria-checked={withPr} className={cx("toggle", { on: withPr })} onClick={() => setWithPr((v) => !v)}>
            <span className="toggle-knob" />
          </button>
        </label>
        <button className={cx("btn btn-secondary", { hint: locked })} onClick={learnAll} disabled={busy === "ingest" || noLlm} title={llmHint ?? "Launch the agents that read the whole knowledge base into the graph"}>
          <BookOpen size={14} /> {busy === "ingest" ? "Launching…" : data.ingested ? "Re-learn knowledge base" : "Learn knowledge base"}
        </button>
      </div>

      <div className="cards">
        {data.services.map((svc) => {
          const latestPlanId = svc.plans[0];
          const latestPlan = latestPlanId ? planById[latestPlanId] : null;
          const build = latestPlan?.latest?.build;
          const learnStatus = svc.learned ? "green" : svc.generated ? "amber" : "grey";
          const planStatus = svc.migration || latestPlanId ? "green" : "grey";
          const buildMeta = build ? runMeta(build.status, "build") : null;
          const primary = svc.migration
            ? { label: "Open pipeline", onClick: () => navigate(`/migrations/${encodeURIComponent(svc.migration)}`), icon: <Wand2 size={14} />, title: "A reviewed migration.yaml exists" }
            : latestPlanId
              ? { label: "Open pipeline", onClick: () => navigate(`/plans/${latestPlanId}`), icon: <Wand2 size={14} />, title: "The plan the agent wrote" }
              : { label: "Launch agent", onClick: () => plan(svc), icon: <Rocket size={14} />, needsLlm: true, title: svc.learned ? "Detect or write migration.yaml, then Build" : "Learn the knowledge base, detect or write migration.yaml, then Build" };
          return (
            <article className="card service-card" key={svc.name}>
              <header className="card-head card-head-btn" role="button" tabIndex={0} onClick={primary.onClick} onKeyDown={(e) => e.key === "Enter" && primary.onClick()} title={primary.label}>
                <div className="card-title">
                  <strong>{svc.name}</strong>
                  <span className="muted">{svc.team ?? "owner unknown"}</span>
                </div>
                {svc.generated && (
                  <Pill tone="amber" title="MaC wrote this page from the repository; a person reviews it">
                    under review{svc.review?.ticket ? ` · ${svc.review.ticket}` : ""}
                  </Pill>
                )}
                <Menu
                  label={`More for ${svc.name}`}
                  items={[
                    { label: "Launch agent", detail: "learn · detect or plan · build", icon: <Rocket size={14} />, onClick: () => plan(svc) },
                    { label: "Plan again", detail: withPr ? "fresh migration.yaml, opens a PR" : "fresh migration.yaml, no Build", icon: <Sparkles size={14} />, onClick: () => plan(svc, { reuse: false, build: false }) },
                    { label: data.ingested ? "Re-learn knowledge base" : "Learn knowledge base", detail: "ingest only", icon: <BookOpen size={14} />, onClick: learnAll },
                    ...(svc.plans.length > 1 ? svc.plans.slice(1, 4).map((id) => ({ label: `Open plan ${id}`, onClick: () => navigate(`/plans/${id}`) })) : []),
                  ]}
                />
              </header>
              {svc.description && <p className="card-body">{svc.description}</p>}
              <div className="repo-list">
                {svc.repos.length === 0 && <span className="muted small">no repositories documented</span>}
                {svc.repos.map((r) => (
                  <a className="stage-chip chip-link" key={r} href={repoUrlOf(r)} target="_blank" rel="noreferrer" title={r}>
                    <GitBranch size={11} /> {r.split("/").pop()}
                  </a>
                ))}
              </div>
              <div className="stepper">
                <Step label="Learn" status={learnStatus} text={svc.learned ? "graph ready" : svc.generated ? "page under review" : "knowledge base"} />
                <Step label="Plan" status={planStatus} text={svc.migration ? "yaml found" : latestPlan ? `${latestPlan.iterations ?? "?"} attempt${latestPlan.iterations === 1 ? "" : "s"}` : "detect or write"} />
                <Step label="Build" status={buildMeta ? buildMeta.tone : "grey"} text={buildMeta ? buildMeta.label.toLowerCase() : "runner"} />
              </div>
              <Doors pageUrl={svc.page_url} pageId={svc.page} repoUrl={svc.repos[0] ? repoUrlOf(svc.repos[0]) : null} create={health?.confluence && svc.page ? () => createPage(svc.page) : null} busy={busy === `page:${svc.page}`} size="lg" stop={false} />
              <footer className="card-foot">
                <button className={cx("btn btn-primary", { hint: locked })} onClick={primary.onClick} disabled={busy === svc.name || busy === "ingest" || (primary.needsLlm && noLlm)} title={primary.needsLlm && llmHint ? llmHint : primary.title}>
                  {primary.icon} {busy === svc.name ? "Launching…" : primary.label}
                </button>
                {svc.approvers.length > 0 && <span className="muted small">approvers: {svc.approvers.join(", ")}</span>}
                {svc.plans.length > 0 && (
                  <span className="muted small">
                    {svc.plans.length} plan{svc.plans.length === 1 ? "" : "s"}
                  </span>
                )}
              </footer>
            </article>
          );
        })}
        {data.services.length === 0 && <EmptyState title="No services in the knowledge base" body="No page carries the `service` label. Learn a repository below, or check demo-data/confluence." />}
      </div>

      <div className="toolbar" style={{ marginTop: 32 }}>
        <span className="label">Repositories</span>
        <span className="spacer" />
        <span className="muted small">{data.repos.length} repositories · pipelines start from the services above · Learn writes a page for an undocumented repo</span>
        <button className={cx("btn btn-secondary", { hint: locked })} onClick={() => setAdding((v) => !v)} title="Add a public GitHub repository by URL; an agent checks its licence">
          <Plus size={14} /> Add repository
        </button>
      </div>
      {adding && (
        <form className="add-repo" onSubmit={addRepo}>
          <Github size={16} className="muted" />
          <input className="filter-input add-repo-input" placeholder="https://github.com/owner/name" value={repoUrl} onChange={(e) => setRepoUrl(e.target.value)} autoFocus aria-label="Repository URL" />
          <button type="submit" className={cx("btn btn-primary", { hint: locked })} disabled={busy === "add-repo" || !repoUrl.trim()}>
            <Scale size={14} /> {busy === "add-repo" ? "Launching…" : "Add and check licence"}
          </button>
          <span className="muted small">Public repositories only. {health?.llm ? "Nemotron" : "An SPDX rule"} classifies the licence; anything not clearly fine raises a review ticket.</span>
        </form>
      )}
      {data.repos_error && <p className="muted small">{data.repos_error}</p>}
      {data.repos.length > 0 && (
        <div className="table repos-table">
          {data.repos.map((r) => {
            const svc = r.service ? data.services.find((s) => s.name === r.service) : null;
            const learning = busy === r.full_name;
            return (
              <div className={cx("tr repo-row", { documented: Boolean(svc) })} key={r.full_name}>
                <div className="cell-title">
                  <span className="row-title">{r.name}</span>
                  <span className="muted small">{r.description || "no description"}</span>
                </div>
                <div className="muted small">{r.pushed_at ? `pushed ${fmtAgo(r.pushed_at)}` : ""}</div>
                <div className="cell-pills">
                  {svc ? (
                    <Pill tone={svc.learned ? "green" : svc.generated ? "amber" : "grey"}>
                      {svc.generated ? "under review · " : "part of "}
                      {svc.name}
                    </Pill>
                  ) : (
                    <span className="faint small">not in the knowledge base</span>
                  )}
                  {r.licence && (
                    <a className={cx("pill", `tone-${r.licence.risk === "ok" ? "green" : r.licence.risk === "blocked" ? "red" : "amber"}`, "pill-link")} href={r.licence.ticket_url ?? r.url} target="_blank" rel="noreferrer" title={r.licence.reason ?? ""}>
                      <Scale size={11} /> {r.licence.spdx ?? "no licence"} · {r.licence.risk}
                      {r.licence.ticket ? ` · ${r.licence.ticket}` : ""}
                    </a>
                  )}
                  {r.custom && <Pill tone="grey">added by hand</Pill>}
                </div>
                <div className="cell-actions">
                  <Doors pageUrl={r.page_url} pageId={r.page} repoUrl={r.url} learn={svc ? null : noLlm ? null : () => learnRepo(r)} create={health?.confluence && r.page ? () => createPage(r.page) : null} busy={learning || busy === `page:${r.page}`} size="md" stop={false} />
                  {r.custom && (
                    <button className="icon-btn" title="Remove from the list" onClick={() => removeRepo(r)}>
                      <Trash2 size={14} />
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}
