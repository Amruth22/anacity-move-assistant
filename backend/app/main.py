from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .routers import admin, chat, communities, documents, requests

app = FastAPI(title="ANACITY Move Assistant", docs_url="/api/swagger")

# CORS is only needed for the Vite dev server; same-origin in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(communities.router)
app.include_router(requests.router)
app.include_router(chat.router)
app.include_router(admin.router)
app.include_router(documents.router)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EXPLANATION = REPO_ROOT / "EXPLANATION.md"
DIST = REPO_ROOT / "frontend" / "dist"


@app.get("/api/docs-content", response_class=PlainTextResponse)
def docs_content():
    if EXPLANATION.exists():
        return EXPLANATION.read_text(encoding="utf-8")
    return "Explanation document not found."


# Serve the built frontend when it exists (production). In dev, Vite serves
# itself on :5173 and proxies /api here.
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        candidate = DIST / path
        if path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(DIST / "index.html")
