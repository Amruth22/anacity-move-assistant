# Move-in / Move-out Agentic Workflow: Design Notes

This document explains what I built, why it's shaped the way it is, and where the honest limits are. The prototype is a working two-sided flow: residents talk to an assistant that plans and files their move, and admins get a copilot that briefs them before they act.

## How I read the problem

Move-in and move-out look like form-filling problems, but they're really *policy navigation* problems. The pain is rarely "I can't fill a form". It's "I didn't know I needed 7 days' notice", "nobody told me tenants need the owner's NOC", "why was my Saturday slot rejected?". Every community answers those questions differently, and the answers change.

So the design bet is this: put the policy in one declarative place, let deterministic code enforce it, and let an LLM do what LLMs are good at, which is conversation, explanation, and judgment. The agent never *is* the policy; it's a fluent guide to it.

Two roles, two very different needs:

- **Residents** need guidance. They don't know the rules, and they shouldn't have to. A conversation beats a form here because the assistant can ask only what's relevant, explain *why* a date fails, and offer the nearest date that works.
- **Admins** need context and confidence. They already know the rules; what costs them time is assembling the picture: is the date valid, what's missing, is anything off about this one? That's a briefing problem, not a conversation problem, so the admin side is a dashboard with a one-shot copilot, not a chatbot.

The app opens on two doors, residents on one side and the community office on the other, because the two experiences genuinely are different products sharing one backend.

## The experience

**Resident side.** Behind the resident door you pick your community and yourself (no real auth, see assumptions). Each community shows its own rulebook up front: the strict high-rise and the relaxed villa community are visibly different before you even click. The assistant then knows who you are, your unit, and your tenancy type. Tell it "I want to move out this Friday" and it checks the actual policy, tells you Friday fails the notice period, and offers the earliest date that passes. It collects the required details (which differ per community: Lakeview wants a mover company, Palm Meadows wants a pet declaration), reads the plan back, and then stages the request as a draft. A confirmation card appears in the chat with the full summary, and only tapping **Confirm** files it. The assistant cannot file anything on its own. Follow-ups like "what's my status?" work in the same conversation, and the assistant talks about "your move-out on 24 August", not internal ticket numbers. Tool activity is shown as small chips ("Checking community policy") so you can see the agent working rather than guessing.

Required documents are uploaded from the "My requests" tab. Each checklist item takes a PDF or image and moves through three states: *not uploaded, awaiting review, verified*. The assistant knows these states too, so "did they get my NOC?" gets a real answer, and it points residents to the upload tab rather than pretending to accept files in chat. When the admin sends a request back for more information, the resident sees a nudge on the request with the admin's note; one tap opens the chat with a reply started, and answering resubmits the request automatically.

**Admin side.** A filterable dashboard of all requests across communities. Opening one shows the facts, documents, and timeline on the left, and the copilot on the right. The copilot starts by itself when a request is opened; no button to remember. Uploaded documents open in a new tab and each gets a per-item **Verify** button; uploads and verifications both land on the request timeline, and either one invalidates a cached copilot assessment (the facts changed, so the briefing regenerates). The briefing contains: a summary, a pass/fail row per policy rule, missing items, risk flags with severity, a recommendation (approve / reject / request more info), the reasoning, and a ready-to-send note to the resident. The three action buttons sit next to the copilot output but are wired to plain REST calls; the copilot's output is advice, never action. The actions carry their own guard rails in the API, not just the UI: rejecting or requesting info requires a note, and approving over pending checklist items requires an explicit override note.

## Architecture

```
Vite + React (TS)                FastAPI (Python)
+-------------------+            +------------------------------------+
| Resident chat  ---+-- SSE ---->| /api/chat  -> agent loop (LLM)     |
| My requests       |            |   tools --> policy.py + store      |
| Admin dashboard --+-- REST --->| /api/requests, /api/communities    |
| Copilot panel  ---+-- REST --->| /api/admin/.../copilot (LLM)       |
| Docs page         |            | in-memory store <- seed JSON       |
+-------------------+            +------------------------------------+
```

- **Model:** pluggable. `USE_MODEL` in `.env` picks the provider: GPT via the OpenAI Responses API (the running default, `gpt-5.6-luna`, chosen because it matches Claude on this workload at a markedly lower price) or Claude via the Anthropic SDK (`claude-sonnet-5`). `ANTHROPIC_MODEL` / `OPENAI_MODEL` pick the exact model, so stepping up to `gpt-5.6-sol` or `claude-opus-5` is a config edit. Both providers implement the same contract: streaming plus tool loop for chat, one structured-output call for the copilot. The frontend and the SSE protocol don't know which is running.
- **`policy.py`** is the deterministic core: notice periods, allowed days, hours, blackout dates, checklists by tenancy, earliest valid date. Pure functions, unit tested, no LLM anywhere near it.
- **`store.py`** is an in-memory store seeded from JSON at startup. It's the only owner of data shape; swapping in Postgres later means reimplementing one file.
- The frontend is served by FastAPI as static files in production, so one process is the whole deployment.

## Agent design

**The resident agent** runs a manual tool loop over the provider API. Eight tools:

| Tool | What it does |
|---|---|
| `get_community_policy` | Returns the community's policy config (the agent is told to never quote rules from memory) |
| `get_my_units` | The resident's unit and tenancy type |
| `validate_move_request` | Runs the deterministic checks; returns every violation plus the earliest valid date |
| `get_required_checklist` | Documents, deposit, and extra fields for *this* resident (owner vs tenant differ) |
| `create_move_request` | Stages a draft and puts a confirmation card in the chat; it cannot file |
| `update_move_request` | Changes date, window, or details on an existing request; a reply to a needs-info request resubmits it |
| `cancel_move_request` | Withdraws an open request after the resident confirms they mean it |
| `get_my_requests` | Status, timeline, document states, and pending items for follow-up questions |

Design decisions worth calling out:

- **Code does truth, the model does language.** All date math and rule checks live in `policy.py`. The model's job is to relay, explain, and ask good follow-up questions. This is the main hallucination defense: there's no way to "talk the agent into" a wrong deadline, because the deadline never comes from the model.
- **The trust boundary is server-side.** Tool executors receive the resident and community from the server session, never from model arguments. The model physically cannot read another unit's data, no matter what the user types. Prompt injection can change the agent's tone; it can't cross a tenant boundary.
- **The autonomy boundary is physical, not prompted.** `create_move_request` writes a pending draft onto the server session and nothing else. The only code path that files a request is the `/api/chat/confirm` endpoint, which fires when the resident taps the card. At that moment the server re-runs the full validation atomically (the date rules again, duplicate requests, elevator slot conflicts), so a draft that went stale while the resident hesitated is caught at the last second. A model that skips steps, or a prompt injection that tries to rush the flow, hits the same wall: there is no tool that files.
- **Beyond that, the agent guides freely and never decides.** Approve or reject belongs to the admin, full stop. The natural next step up the autonomy ladder would be a per-community `auto_approve_if_clean` flag in config; the architecture supports it, and it belongs in config precisely because communities will disagree about it.

**The admin copilot deliberately isn't an agent.** By assessment time the server already has every fact, so it runs the policy checks itself and hands the model *verified findings* plus the raw request in a single structured-output call (JSON schema enforced by the API). One round trip, no loop failure modes, and a clean split: the pass/fail rows come from code; the model contributes the summary, risk judgment, recommendation, and the drafted reply. The result is cached on the request and invalidated whenever an admin action changes the facts.

## The scalability story

Everything community-specific lives in `communities.json`: notice periods, allowed days and hours, blackout dates, deposits, document checklists split by owner/tenant, custom intake fields, and a free-text `agent_notes` that the management team can use to teach the agent local quirks ("residents confuse the society NOC with the builder NOC").

Both the tools and the system prompt are built from this config at runtime. The two seeded communities prove the point: Lakeview Heights (7-day notice, weekdays only, a 10,000 rupee deposit, elevator booking) and Palm Meadows (2-day notice, any day, no deposit, pet declaration) run the same code with visibly different behavior. Onboarding community #3 is a JSON file.

The honest boundary: config covers rule *parameters*. A genuinely new rule *type*, like "moves need a committee vote" or "deposit scales with floor", needs a new check in `policy.py` and possibly a new field in the schema. The claim is "new community, zero code change", not "new kind of rule, zero code change".

## Assumptions

- **No authentication.** The entry doors and persona picker stand in for login. Real ANACITY has accounts; identity would come from the auth layer and feed the same session mechanism.
- **Document files live on local disk** (`backend/uploads/`), 5 MB cap, PDF/image only, one file per checklist item. Metadata sits on the in-memory record, so a server restart orphans previously uploaded files, consistent with the in-memory store assumption. Production would move both to object storage plus a database. There is no virus scanning or content verification beyond MIME type; an admin eyeballs the document before verifying, which is the same trust model societies use today.
- **In-memory store.** Restart wipes state (seed data returns). Deliberate for a prototype; the swap boundary is `store.py`.
- **Single worker.** Chat sessions live in process memory, so uvicorn runs with one worker. Production would move sessions to Redis and scale horizontally.
- **Seeded "today".** Validation uses the real current date in the community's timezone, so seeded requests age naturally.

## Testing

52 pytest tests cover the parts where wrongness is silent:

- **Policy engine:** notice boundary (exactly N days passes, N-1 fails), disallowed weekdays, blackout dates, hours windows, past and garbage dates, multiple simultaneous violations, earliest valid date skipping weekends *and* blackouts, checklists differing by tenancy, custom fields where False is an answer but absence isn't.
- **Tools:** a resident can't act on someone else's unit; invalid dates are rejected even when the tool is called directly (the model can't bypass validation); creating stages a draft and files nothing; without a session nothing can be filed at all; duplicate open requests are blocked; results are scoped to the requesting resident.
- **Lifecycle:** the needs-info round trip (reply resubmits, admin can ask twice), updates re-validate dates and are owner-only, a window-only update keeps the original submission's notice standing, cancelling blocks further edits, completed requests can't be cancelled, and the confirm step re-checks elevator availability and duplicates at filing time, including against requests approved after the draft was staged.
- **Admin guard rails:** reject and request-info require a note, approving over pending checklist items requires an override note, status transitions are enforced (no approving a rejected request), and admin actions invalidate the cached copilot briefing.
- **Documents:** upload attaches the file and logs the timeline, the wrong resident gets a 403, non-PDF/image types are rejected, verify requires a file first, verified items can't be silently replaced, closed requests take no uploads.

On top of that, the demo script I ran end to end: (1) resident at the strict community asks for a too-early Friday, the agent explains the notice period and offers the earliest valid date; (2) completes intake and confirms the card, the request appears in both resident and admin views; (3) the same conversation at the relaxed community hits different rules with zero code difference; (4) the copilot briefs a request with missing documents and recommends requesting info with a sensible drafted reply; (5) the resident replies from the nudge and the request resubmits; (6) adversarial: asking the agent to waive the deposit or show another unit's requests is declined, and the tools make it impossible anyway.

## Failure recovery

What happens when things go wrong, in rough order of likelihood:

- **The model API errors mid-chat.** The SSE stream emits an `error` event with a friendly message instead of dying silently; the conversation survives and the resident just sends again. Session history is only extended, never corrupted, because tool results are appended in complete units.
- **The copilot call fails.** The panel shows the error and a retry; nothing about the request record changes until an assessment actually returns.
- **The model calls a tool wrongly** (bad date, someone else's unit, skipped validation). Every executor validates its own inputs and returns a structured error the model can recover from conversationally; the filing step re-runs the full policy check regardless of what the model did before.
- **The resident confirms a stale draft.** Between staging and tapping Confirm, the world can change: another request gets approved, the elevator slot fills. The confirm endpoint re-validates atomically and returns a clear failure instead of filing a broken request.
- **The process crashes.** systemd restarts it (`Restart=on-failure`). Seed data returns, in-flight chat sessions are lost: an accepted cost of the in-memory prototype, and the first thing the production path fixes.

## Limitations and trade-offs

- **Latency.** A chat turn with two tool rounds takes a few seconds; streaming hides most of it. The copilot call runs at low reasoning effort (its inputs are pre-verified, so deep thinking buys nothing; measured, not assumed) and takes about 10 seconds, dominated by generating the briefing itself. It starts automatically when the admin opens a request, so by the time they've read the facts it's usually waiting for them, and it's cached until the facts change. Concurrent opens of the same request share one in-flight call.
- **TLS terminates at CloudFront.** The public URL is HTTPS via a CloudFront distribution with caching disabled; the hop from CloudFront to the EC2 origin is plain HTTP on the instance port. Production would put certificates on a load balancer and close the origin port to the world. SSE streams through CloudFront correctly, which was verified by watching tokens arrive progressively; a buffering proxy is the classic way this breaks silently.
- **The model can still phrase things imperfectly** even with correct facts. The containment is that facts come from tools; the wording risk is cosmetic, not transactional.
- **Conversation history is trimmed, not compacted.** Very long chats lose early context. Fine for this use case; server-side compaction is the upgrade path.
- **One request per unit per type** at a time: a simplification that matches how societies actually operate but would need revisiting for corporate rentals.

## Production path

In rough priority order: real auth feeding the session identity; Postgres behind `store.py` and Redis for sessions; document upload with storage; notifications (the timeline is already the event source to hang them on); per-community autonomy settings (`auto_approve_if_clean`); observability on the agent loop (tool-call traces, token usage per session; the data is already structured for it); and an admin-facing config editor so community managers maintain `communities.json` themselves, which is the point of the whole design.
