import { useCallback, useEffect, useRef, useState } from 'react'
import { api, streamChat } from '../api/client'
import type { ConfirmSummary } from '../types'

interface ChatItem {
  role: 'user' | 'agent'
  text: string
  tools: { name: string; label: string }[]
  requestId?: string | null
  confirm?: { summary: ConfirmSummary; state: 'pending' | 'confirmed' | 'declined' | 'stale' | 'failed' }
}

const STARTER_CARDS = [
  {
    title: 'Plan a move-out',
    sub: 'dates, documents, gate passes, the lot',
    send: "I'm planning to move out. Help me set it up.",
  },
  {
    title: 'Prepare a move-in',
    sub: 'what you need before the truck arrives',
    send: 'What do I need for a move-in?',
  },
  {
    title: 'Check my request',
    sub: 'status, pending items, admin notes',
    send: "What's the status of my request?",
  },
]

/** Tiny renderer for the bits of markdown the agent actually uses (bold). */
function renderInline(text: string) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g)
  return parts.map((p, i) =>
    p.startsWith('**') && p.endsWith('**') ? <strong key={i}>{p.slice(2, -2)}</strong> : p,
  )
}

export default function Chat({ residentId, onRequestCreated, greeting, prefill }: {
  residentId: string
  onRequestCreated: () => void
  greeting?: { hello: string; context: string }
  prefill?: { text: string; nonce: number }
}) {
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [sessionFailed, setSessionFailed] = useState(false)
  const [items, setItems] = useState<ChatItem[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [deciding, setDeciding] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const startSession = useCallback(() => {
    setSessionFailed(false)
    api
      .newChatSession(residentId)
      .then((r) => setSessionId(r.session_id))
      .catch(() => setSessionFailed(true))
  }, [residentId])

  useEffect(() => {
    startSession()
  }, [startSession])

  // a nudge elsewhere in the app (like "Reply to the admin") can seed the input
  useEffect(() => {
    if (prefill) {
      setInput(prefill.text)
      inputRef.current?.focus()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefill?.nonce])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [items])

  const send = async (text: string) => {
    if (!sessionId || busy || !text.trim()) return
    setBusy(true)
    setInput('')
    setItems((prev) => [
      ...prev,
      { role: 'user', text, tools: [] },
      { role: 'agent', text: '', tools: [] },
    ])

    const patchLast = (fn: (item: ChatItem) => ChatItem) =>
      setItems((prev) => prev.map((it, i) => (i === prev.length - 1 ? fn(it) : it)))

    await streamChat(sessionId, text, {
      onText: (delta) => patchLast((it) => ({ ...it, text: it.text + delta })),
      onTool: (name, label) =>
        patchLast((it) => ({ ...it, tools: [...it.tools, { name, label }] })),
      onConfirm: (summary) =>
        setItems((prev) =>
          prev.map((it, i) => {
            // a fresh card supersedes any earlier one still waiting
            if (i === prev.length - 1) return { ...it, confirm: { summary, state: 'pending' } }
            if (it.confirm?.state === 'pending') return { ...it, confirm: { ...it.confirm, state: 'stale' } }
            return it
          }),
        ),
      onDone: () => setBusy(false),
      onError: (message) => {
        patchLast((it) => ({ ...it, text: it.text || message }))
        setBusy(false)
      },
    })
  }

  const decideDraft = async (index: number, accept: boolean) => {
    if (!sessionId || deciding) return
    setDeciding(true)
    try {
      if (accept) {
        const { request_id } = await api.confirmRequest(sessionId)
        setItems((prev) =>
          prev.map((it, i) =>
            i === index
              ? { ...it, requestId: request_id, confirm: { ...it.confirm!, state: 'confirmed' } }
              : it,
          ),
        )
        onRequestCreated()
      } else {
        await api.declineRequest(sessionId)
        setItems((prev) =>
          prev.map((it, i) =>
            i === index ? { ...it, confirm: { ...it.confirm!, state: 'declined' } } : it,
          ),
        )
      }
    } catch {
      setItems((prev) =>
        prev.map((it, i) =>
          i === index ? { ...it, confirm: { ...it.confirm!, state: 'failed' } } : it,
        ),
      )
    } finally {
      setDeciding(false)
    }
  }

  return (
    <div className="chat-frame">
      <div className="chat-scroll" ref={scrollRef}>
        {items.length === 0 &&
          (greeting ? (
            <div className="greeting">
              <h3>{greeting.hello}</h3>
              <p>{greeting.context}</p>
              <div className="starter-cards">
                {STARTER_CARDS.map((s) => (
                  <button className="starter-card" key={s.title} onClick={() => send(s.send)}>
                    <b>{s.title}</b>
                    <small>{s.sub}</small>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="empty-note">
              Say hello. The assistant knows your unit, your community's rules, and your open
              requests.
            </div>
          ))}
        {items.map((item, i) => (
          <div className={`msg ${item.role}`} key={i}>
            {item.tools.length > 0 && (
              <div>
                {item.tools.map((t, j) => (
                  <span className="tool-chip" key={j}>
                    {t.label}
                  </span>
                ))}
              </div>
            )}
            {(item.text || item.role === 'user') && (
              <div className="bubble">{renderInline(item.text)}</div>
            )}
            {item.role === 'agent' && busy && i === items.length - 1 && !item.text && (
              <div className="thinking-row">
                <span className="dots">
                  <i />
                  <i />
                  <i />
                </span>
                Working on it…
              </div>
            )}
            {item.confirm && (
              <div className={`confirm-card ${item.confirm.state}`}>
                <div className="confirm-title">
                  {item.confirm.summary.type === 'move_in' ? 'Move-in' : 'Move-out'} ·{' '}
                  {item.confirm.summary.unit}
                </div>
                <div className="confirm-line">
                  {item.confirm.summary.requested_date} · {item.confirm.summary.time_window}
                </div>
                {item.confirm.summary.documents.length > 0 && (
                  <div className="confirm-line">
                    Documents you'll upload after filing: {item.confirm.summary.documents.join(', ')}
                  </div>
                )}
                {item.confirm.summary.tasks.length > 0 && (
                  <div className="confirm-line">
                    Handled with the admin desk: {item.confirm.summary.tasks.join(', ')}
                  </div>
                )}
                {item.confirm.state === 'pending' && (
                  <div className="confirm-actions">
                    <button className="confirm-yes" disabled={deciding} onClick={() => decideDraft(i, true)}>
                      {deciding ? 'Filing…' : 'Confirm & file request'}
                    </button>
                    <button className="confirm-no" disabled={deciding} onClick={() => decideDraft(i, false)}>
                      Not now
                    </button>
                  </div>
                )}
                {item.confirm.state === 'confirmed' && <div className="confirm-note">Filed ✓</div>}
                {item.confirm.state === 'declined' && <div className="confirm-note">Dismissed, nothing was filed</div>}
                {item.confirm.state === 'stale' && <div className="confirm-note">Superseded by a newer draft</div>}
                {item.confirm.state === 'failed' && (
                  <div className="confirm-note">
                    Couldn't file it. Something changed while this was waiting, ask the assistant
                    what happened.
                  </div>
                )}
              </div>
            )}
            {item.requestId && (
              <div>
                <span className="request-pill">Request created ✓ It's under Your requests now</span>
              </div>
            )}
          </div>
        ))}
      </div>

      {sessionFailed && (
        <div className="chat-fail">
          Couldn't reach the assistant. Check that the server is running, then{' '}
          <button onClick={startSession}>try again</button>.
        </div>
      )}

      <form
        className="chat-input"
        onSubmit={(e) => {
          e.preventDefault()
          send(input)
        }}
      >
        <input
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={
            sessionFailed ? 'Assistant unavailable' : busy ? 'Assistant is replying…' : 'Type a message'
          }
          disabled={busy || !sessionId}
        />
        <button type="submit" disabled={busy || !sessionId || !input.trim()}>
          Send
        </button>
      </form>
    </div>
  )
}
