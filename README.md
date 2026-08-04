# ANACITY Move Assistant

A working prototype of an agentic move-in / move-out workflow for residential communities. Residents plan and file their move by talking to an AI assistant; admins review requests with an AI copilot that briefs them before they act.

**Live demo:** https://d24qp4whfkpey8.cloudfront.net
**Video walkthrough (4 min, narrated):** https://anacity-demo-792026110642.s3.amazonaws.com/anacity-demo.mp4

**Design notes, architecture and reasoning live in [EXPLANATION.md](./EXPLANATION.md)**, also rendered inside the app at `/docs`.

## Stack

- **Backend:** FastAPI, streaming chat over SSE, in-memory store seeded with two demo communities.
- **LLM:** pluggable provider, chosen in `.env`. The default is `USE_MODEL=openai`, running `gpt-5.6-luna` over the OpenAI Responses API: it matches the alternative on this workload and costs a fraction as much. `USE_MODEL=anthropic` switches the same code to Claude via the Anthropic SDK (`claude-sonnet-5`, or `claude-opus-5`). Model names are plain env vars (`ANTHROPIC_MODEL` / `OPENAI_MODEL`), so switching provider or model is an `.env` edit and a restart, no code change.
- **Frontend:** Vite + React + TypeScript, served as static files by FastAPI in production.

## Run it locally

You need Python 3.10+ and Node 18+.

```bash
# backend
cd backend
python -m venv venv
venv/Scripts/pip install -r requirements.txt        # Windows
# venv/bin/pip install -r requirements.txt          # Linux/macOS
cp .env.example .env                                 # then set USE_MODEL and the matching API key
venv/Scripts/python -m uvicorn app.main:app --port 8000

# frontend (second terminal), dev server proxies /api to :8000
cd frontend
npm install
npm run dev                                          # open http://localhost:5173
```

Or run it the way production does, as one process:

```bash
cd frontend && npm run build && cd ..
cd backend && venv/Scripts/python -m uvicorn app.main:app --port 8000
# open http://localhost:8000
```

## Tests

```bash
cd backend
venv/Scripts/python -m pytest
```

52 tests cover the deterministic policy engine (notice periods, blackout dates, checklists by tenancy, earliest valid date), the agent tools (tenant isolation, server-side re-validation, duplicate guards), the staged-draft confirmation flow, document upload and verification, and the full request lifecycle including the needs-info round trip and elevator slot conflicts.

## Try this demo path

1. Take the resident door, pick **Priya Nair** at Lakeview Heights (the strict wing), and tell the assistant you want to move out this Friday. Watch it explain the notice period and offer the earliest date that works.
2. Give it a valid date, let it collect the details, and tap **Confirm** on the card it stages. Nothing is filed until you do. The request appears under **Your requests**, where documents are uploaded.
3. Switch to the **admin desk** and open the new request. The copilot briefs it on its own: policy findings checked by code, missing items, a recommendation, and a drafted reply. Use **Request info**, then switch back to Priya to see the nudge and answer it. Her reply resubmits the request automatically.
4. Pick a Palm Meadows resident and start the same conversation: same code, visibly different rules (2-day notice, no deposit, pet declaration). That contrast is the scalability story.

## Deploy (EC2)

```bash
./deploy/deploy.sh          # builds the frontend, rsyncs to the server, restarts the service
```

One-time server setup (venv, `.env` with the API key, systemd unit, opening port 8000) is documented at the top of `deploy/deploy.sh`. The API key lives only in `/home/ec2-user/anacity/backend/.env` on the server (`chmod 600`); it is never committed, and the deploy script explicitly excludes it. HTTPS is provided by a CloudFront distribution in front of the instance.
