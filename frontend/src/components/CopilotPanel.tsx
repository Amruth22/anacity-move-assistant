import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { CopilotAssessment } from '../types'

const RECO_LABELS: Record<string, string> = {
  approve: 'Recommends approval',
  reject: 'Recommends rejection',
  request_more_info: 'Recommends requesting more info',
}

export default function CopilotPanel({ requestId, cached, onAssessed, onUseReply }: {
  requestId: string
  cached: CopilotAssessment | null
  onAssessed: (a: CopilotAssessment) => void
  onUseReply?: (text: string) => void
}) {
  const [assessment, setAssessment] = useState<CopilotAssessment | null>(cached)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)

  const copyReply = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* clipboard can be unavailable on http; the Use as note button still works */
    }
  }

  const run = async () => {
    if (running) return // the backend dedupes too, but don't even ask twice
    setRunning(true)
    setError('')
    try {
      const result = await api.copilot(requestId)
      setAssessment(result)
      onAssessed(result)
    } catch {
      setError('The copilot could not complete the assessment. Try again in a moment.')
    } finally {
      setRunning(false)
    }
  }

  // start immediately - by the time the admin has read the request facts,
  // the briefing is usually ready (the backend dedupes concurrent runs).
  // when the server invalidates the cache (a document was verified, an action
  // was taken), `cached` comes back null and the briefing regenerates rather
  // than showing a stale recommendation.
  useEffect(() => {
    setAssessment(cached)
    if (!cached) run()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestId, cached])

  return (
    <div className="panel copilot">
      <h2>AI copilot</h2>

      {!assessment && !running && error && (
        <>
          <div className="error-note">{error}</div>
          <button className="run-btn" onClick={run}>
            Try again
          </button>
        </>
      )}

      {running && (
        <div className="thinking-row">
          <span className="dots">
            <i />
            <i />
            <i />
          </span>
          Reviewing the request against community policy…
        </div>
      )}

      {assessment && !running && (
        <>
          <div className={`reco-banner ${assessment.recommendation}`}>
            {RECO_LABELS[assessment.recommendation]}
          </div>

          <p style={{ fontSize: '0.92rem', lineHeight: 1.55, marginTop: 0 }}>{assessment.summary}</p>

          <h2>Policy findings</h2>
          {assessment.policy_findings.map((f, i) => (
            <div className={`finding ${f.status}`} key={i}>
              <span className="dot" />
              <div>
                <b>{f.rule}</b>
                <span>{f.detail}</span>
              </div>
            </div>
          ))}

          {assessment.missing_items.length > 0 && (
            <>
              <h2 style={{ marginTop: 18 }}>Still missing</h2>
              <ul className="missing-list">
                {assessment.missing_items.map((m, i) => (
                  <li key={i}>{m}</li>
                ))}
              </ul>
            </>
          )}

          {assessment.risk_flags.length > 0 && (
            <>
              <h2 style={{ marginTop: 18 }}>Risks</h2>
              {assessment.risk_flags.map((r, i) => (
                <div className={`risk ${r.severity}`} key={i}>
                  <span className="sev">{r.severity}</span> · {r.description}
                </div>
              ))}
            </>
          )}

          <h2 style={{ marginTop: 18 }}>Why</h2>
          <p style={{ fontSize: '0.9rem', lineHeight: 1.55, color: 'var(--ink-soft)', marginTop: 0 }}>
            {assessment.reasoning}
          </p>

          <h2>Suggested reply to resident</h2>
          <div className="suggested-msg">{assessment.suggested_message_to_resident}</div>
          <div className="reply-actions">
            {onUseReply && (
              <button onClick={() => onUseReply(assessment.suggested_message_to_resident)}>
                Use as note
              </button>
            )}
            <button onClick={() => copyReply(assessment.suggested_message_to_resident)}>
              {copied ? 'Copied ✓' : 'Copy'}
            </button>
          </div>
        </>
      )}
    </div>
  )
}
