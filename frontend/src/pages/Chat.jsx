import { useCallback, useEffect, useRef, useState } from "react";
import { BookOpen, Check, ChevronDown, ChevronRight, Cog, MessageSquare, Plus, Search, Send, Sparkles, Trash2, X } from "lucide-react";
import Markdown from "../components/Markdown.jsx";
import { useAuth } from "../components/Shell.jsx";
import { api, chatStream, fmtAgo } from "../mac/api.js";
import { navigate } from "../router.jsx";
import { cx } from "../lib.js";

// Chat with the MaC assistant (docs/api.md → "The assistant"): a fresh agent per question with
// read-only tools over Confluence, Jira and MaC's own runs and approvals. The conversation is
// posted whole each time; the server streams each lookup (shown as progress under the cog),
// then the answer as Markdown with links. Transcripts are kept per chat so they list in the rail.

const SUGGESTIONS = [
  "What does ClaimsAdjudicationService depend on?",
  "Which approvals does the claims migration need, and what's their status?",
  "What did the last Rehearse fail on?",
];

const TOOL_LABEL = {
  search_confluence: "Searching Confluence",
  read_confluence_page: "Reading a Confluence page",
  search_jira: "Searching Jira",
  read_jira_issue: "Reading a Jira issue",
  mac_status: "Reading MaC's runs and approvals",
};

function toolLine(t) {
  const arg = t.args ? Object.values(t.args)[0] : null;
  return (
    <>
      <span className="chat-tool-name">{TOOL_LABEL[t.name] ?? t.name}</span>
      {arg && <span className="mono muted"> · {String(arg).slice(0, 80)}</span>}
      {t.summary && <span className="muted"> · {t.summary}</span>}
    </>
  );
}

function Tools({ tools }) {
  const [open, setOpen] = useState(false);
  if (!tools?.length) return null;
  return (
    <div className="chat-trace">
      <button className="link-btn chat-trace-toggle" onClick={() => setOpen((v) => !v)}>
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />} how I answered · {tools.length} lookup{tools.length === 1 ? "" : "s"}
      </button>
      {open && (
        <ol className="chat-tools">
          {tools.map((t, i) => (
            <li key={i} className={cx("chat-tool", { bad: t.ok === false })}>
              {t.ok === false ? <X size={12} /> : <Check size={12} />} {toolLine(t)}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

const newId = () => Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4);

export default function Chat({ chatId }) {
  const { locked, health } = useAuth();
  const [chats, setChats] = useState([]);
  const [turns, setTurns] = useState([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [live, setLive] = useState([]); // tool events of the answer in flight
  const [title, setTitle] = useState(null);
  const idRef = useRef(chatId);
  const endRef = useRef(null);
  const boxRef = useRef(null);
  const noLlm = health ? !health.llm : false;

  const loadChats = useCallback(() => api.chats().then(setChats).catch(() => setChats([])), []);
  useEffect(() => {
    loadChats();
  }, [loadChats]);

  useEffect(() => {
    idRef.current = chatId;
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
  }, [turns.length, busy, live.length]);

  async function persist(nextTurns, nextTitle) {
    if (!idRef.current) {
      idRef.current = newId();
      window.history.replaceState({}, "", `/chat/${idRef.current}`);
    }
    try {
      await api.saveChat(idRef.current, nextTitle, nextTurns);
      loadChats();
    } catch {
      /* history is a convenience; the answer is on screen */
    }
  }

  async function send(text) {
    const message = (text ?? draft).trim();
    if (!message || busy) return;
    setDraft("");
    setBusy(true);
    setLive([]);
    const nextTitle = title ?? message.slice(0, 80);
    setTitle(nextTitle);
    const asked = [...turns, { role: "user", text: message, ts: Date.now() / 1000 }];
    setTurns(asked);
    const history = asked.filter((t) => t.role === "user" || t.role === "assistant").map((t) => ({ role: t.role, content: t.text }));
    const tools = [];
    let answer = null;
    let error = null;
    try {
      await chatStream(history, ({ kind, data }) => {
        if (kind === "tool") {
          tools.push(data);
          setLive([...tools]);
        } else if (kind === "answer") answer = data.content;
        else if (kind === "error") error = data.message;
      });
      if (answer == null && !error) error = "The assistant ended without an answer.";
    } catch (e) {
      error = e.detail ?? String(e);
      error = e.status === 503 || e.status === 409 ? `Can't answer here: ${error}` : e.status === 401 ? "Sign in with GitHub to use the assistant." : error;
    }
    const reply = error
      ? { role: "error", text: error, ts: Date.now() / 1000, tools }
      : { role: "assistant", text: answer, ts: Date.now() / 1000, tools, model: health?.model ?? null };
    const done = [...asked, reply];
    setTurns(done);
    setLive([]);
    setBusy(false);
    boxRef.current?.focus();
    persist(done, nextTitle);
  }

  async function remove(id, e) {
    e.stopPropagation();
    try {
      await api.deleteChat(id);
      loadChats();
      if (id === idRef.current) navigate("/chat");
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
            <button key={c.id} className={cx("chat-rail-item", { active: c.id === idRef.current })} onClick={() => navigate(`/chat/${c.id}`)} title={c.title}>
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
                <h1>Ask MaC</h1>
                <p className="muted">
                  Every question spins up a fresh agent{health?.model ? ` on ${health.model}` : ""} with read-only tools over Confluence, Jira and MaC's own runs and approvals. It looks things up, cites what it used, and can't change anything.
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
                {t.role !== "user" && (
                  <span className={cx("chat-avatar", { bad: t.role === "error" })}>
                    <Sparkles size={14} />
                  </span>
                )}
                <div className="chat-bubble">
                  {t.role === "assistant" ? <Markdown text={t.text} /> : t.role === "error" ? <span className="chat-error">{t.text}</span> : t.text}
                  {t.role !== "user" && <Tools tools={t.tools} />}
                </div>
              </div>
            ))}
            {busy && (
              <div className="chat-turn role-assistant">
                <span className="chat-avatar working">
                  <Cog size={16} className="spin" />
                </span>
                <div className="chat-bubble chat-thinking-block">
                  <div className="chat-thinking">
                    <Cog size={14} className="spin" /> {live.length ? "working through the lookups…" : "spinning up an agent…"}
                    {health?.model && <span className="mono muted"> · {health.model}</span>}
                  </div>
                  {live.length > 0 && (
                    <ol className="chat-tools live">
                      {live.map((t, i) => (
                        <li key={i} className={cx("chat-tool", { bad: t.ok === false })}>
                          <Search size={12} /> {toolLine(t)}
                        </li>
                      ))}
                    </ol>
                  )}
                  <p className="faint small">Answers can take a while: the agent reads pages and tickets before it writes.</p>
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
                <textarea ref={boxRef} rows={1} placeholder="Ask about a service, an approval, a run, a standard…" value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={onKey} disabled={busy} />
                <button className="btn btn-primary chat-send" onClick={() => send()} disabled={busy || !draft.trim()} title="Send (Enter)">
                  <Send size={14} />
                </button>
              </div>
            )}
            <p className="faint small chat-foot">Enter sends · Shift+Enter for a new line · read-only: it looks up Confluence, Jira and MaC and says when it couldn't find something</p>
          </div>
        </div>
      </section>
    </div>
  );
}
