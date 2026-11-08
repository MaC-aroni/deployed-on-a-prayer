import { useCallback, useEffect, useRef, useState } from "react";
import { BookOpen, ChevronDown, ChevronRight, Cog, ExternalLink, MessageSquare, Plus, Send, Sparkles, Trash2 } from "lucide-react";
import Markdown from "../components/Markdown.jsx";
import { useAuth } from "../components/Shell.jsx";
import { api, fmtAgo } from "../mac/api.js";
import { Link, navigate } from "../router.jsx";
import { cx } from "../lib.js";

// Chat: a fresh agent over the whole knowledge base. Each question spins up retrieval (the
// relevant sections and the graph's neighbourhood of what was named) and the model answers
// with citations; the sources and the agent's trace sit under every answer.

const SUGGESTIONS = [
  "What does ClaimsAdjudicationService depend on?",
  "Which approvals does a PHI data migration need?",
  "What are the naming and Terraform standards for the landing zone?",
];

function Sources({ sources }) {
  if (!sources?.length) return null;
  const cited = sources.filter((s) => s.cited);
  const shown = cited.length ? cited : sources.slice(0, 4);
  return (
    <div className="chat-sources">
      {shown.map((s) => {
        const inner = (
          <>
            <span className="mono">S{s.n}</span> {s.title} <span className="muted">› {s.heading}</span>
          </>
        );
        return s.url ? (
          <a key={s.n} className="chip chat-chip" href={s.url} target="_blank" rel="noreferrer" title={s.id}>
            {inner} <ExternalLink size={10} />
          </a>
        ) : (
          <Link key={s.n} className="chip chat-chip" to={`/knowledge/${s.page}`} title={s.id}>
            {inner}
          </Link>
        );
      })}
    </div>
  );
}

function Trace({ trace, model }) {
  const [open, setOpen] = useState(false);
  if (!trace?.length) return null;
  return (
    <div className="chat-trace">
      <button className="link-btn chat-trace-toggle" onClick={() => setOpen((v) => !v)}>
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />} how I answered {model && <span className="mono muted">· {model}</span>}
      </button>
      {open && (
        <ol className="trace">
          {trace.map((t, i) => (
            <li key={i} className={cx("trace-line", `k-${t.phase}`)}>
              <span className="trace-kind">{t.phase}</span>
              <p>{t.text}</p>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

export default function Chat({ chatId }) {
  const { locked, health } = useAuth();
  const [chats, setChats] = useState([]);
  const [turns, setTurns] = useState([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [title, setTitle] = useState(null);
  const endRef = useRef(null);
  const boxRef = useRef(null);
  const noLlm = health ? !health.llm : false;

  const loadChats = useCallback(() => api.chats().then(setChats).catch(() => setChats([])), []);
  useEffect(() => {
    loadChats();
  }, [loadChats]);

  useEffect(() => {
    if (!chatId) {
      setTurns([]);
      setTitle(null);
      return;
    }
    let alive = true;
    api
      .chatDetail(chatId)
      .then((c) => alive && (setTurns(c.turns), setTitle(c.title)))
      .catch(() => alive && navigate("/chat"));
    return () => {
      alive = false;
    };
  }, [chatId]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns.length, busy]);

  async function send(text) {
    const message = (text ?? draft).trim();
    if (!message || busy) return;
    setDraft("");
    setBusy(true);
    setTurns((t) => [...t, { role: "user", text: message, ts: Date.now() / 1000 }]);
    try {
      const r = await api.chat(message, chatId);
      setTurns((t) => [...t, { role: "assistant", text: r.reply, ts: Date.now() / 1000, sources: r.sources, trace: r.trace, model: r.model }]);
      setTitle(r.title);
      loadChats();
      if (!chatId) window.history.replaceState({}, "", `/chat/${r.chat_id}`);
    } catch (e) {
      setTurns((t) => [...t, { role: "error", text: e.detail ?? String(e), status: e.status, ts: Date.now() / 1000 }]);
    } finally {
      setBusy(false);
      boxRef.current?.focus();
    }
  }

  async function remove(id, e) {
    e.stopPropagation();
    try {
      await api.deleteChat(id);
      loadChats();
      if (id === chatId) navigate("/chat");
    } catch {
      /* the list refresh tells */
    }
  }

  const onKey = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  return (
    <div className="chat">
      <aside className="chat-rail">
        <button className="btn btn-primary chat-new" onClick={() => navigate("/chat")}>
          <Plus size={14} /> New chat
        </button>
        <div className="chat-rail-list">
          {chats.map((c) => (
            <button key={c.id} className={cx("chat-rail-item", { active: c.id === chatId })} onClick={() => navigate(`/chat/${c.id}`)} title={c.title}>
              <MessageSquare size={13} className="muted" />
              <span className="chat-rail-title">{c.title}</span>
              <span className="muted small">{fmtAgo(c.updated)}</span>
              <span className="icon-btn chat-rail-del" role="button" title="Delete" onClick={(e) => remove(c.id, e)}>
                <Trash2 size={12} />
              </span>
            </button>
          ))}
          {chats.length === 0 && <p className="muted small" style={{ padding: "8px 12px" }}>No chats yet.</p>}
        </div>
      </aside>

      <section className="chat-main">
        <div className="chat-scroll">
          <div className="chat-column">
            {turns.length === 0 && !busy && (
              <div className="chat-empty">
                <span className="chat-empty-mark">
                  <Sparkles size={22} />
                </span>
                <h1>Ask the knowledge base</h1>
                <p className="muted">
                  Every question spins up a fresh agent with the whole knowledge base{health?.model ? ` and ${health.model}` : ""}. Answers cite the pages they came from.
                </p>
                <div className="chat-suggestions">
                  {SUGGESTIONS.map((q) => (
                    <button key={q} className="chat-suggestion" onClick={() => send(q)} disabled={noLlm}>
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {title && turns.length > 0 && <h1 className="chat-title">{title}</h1>}
            {turns.map((t, i) => (
              <div key={i} className={cx("chat-turn", `role-${t.role}`)}>
                {t.role === "assistant" && (
                  <span className="chat-avatar">
                    <Sparkles size={14} />
                  </span>
                )}
                <div className="chat-bubble">
                  {t.role === "assistant" ? <Markdown text={t.text} /> : t.role === "error" ? <span className="chat-error">{t.status === 409 ? "Can't answer here: " : "Something went wrong: "}{t.text}</span> : t.text}
                  {t.role === "assistant" && <Sources sources={t.sources} />}
                  {t.role === "assistant" && <Trace trace={t.trace} model={t.model} />}
                </div>
              </div>
            ))}
            {busy && (
              <div className="chat-turn role-assistant">
                <span className="chat-avatar working">
                  <Cog size={16} className="spin" />
                </span>
                <div className="chat-bubble chat-thinking">
                  <Cog size={14} className="spin" /> spinning up an agent over the knowledge base{health?.model ? ` · ${health.model}` : ""}…
                </div>
              </div>
            )}
            <div ref={endRef} />
          </div>
        </div>

        <div className="chat-composer-wrap">
          <div className="chat-column">
            {noLlm ? (
              <div className="chat-composer disabled">
                <BookOpen size={16} className="muted" />
                <span className="muted small">No LLM is configured here: set MAC_LLM_API_KEY (or NVIDIA_API_KEY) in backend/.env and restart the backend to chat.</span>
              </div>
            ) : (
              <div className={cx("chat-composer", { hint: locked })}>
                <textarea ref={boxRef} rows={1} placeholder="Ask about a service, a standard, an approval, a migration…" value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={onKey} disabled={busy} />
                <button className="btn btn-primary chat-send" onClick={() => send()} disabled={busy || !draft.trim()} title="Send (Enter)">
                  <Send size={14} />
                </button>
              </div>
            )}
            <p className="faint small chat-foot">Enter sends · Shift+Enter for a new line · answers come only from the knowledge base and say when it doesn't know</p>
          </div>
        </div>
      </section>
    </div>
  );
}
