import os
import random
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# backend/.env for local dev. On Fly, keys arrive as Fly secrets (real env vars).
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from . import auth, mac_api, planning_api  # noqa: E402 - read env vars, so after load_dotenv

app = FastAPI(title="deployed-on-a-prayer")
app.include_router(auth.router)  # before the frontend catch-all below
app.include_router(mac_api.router)
app.include_router(planning_api.router)  # the Planner and knowledge graph over HTTP (docs/planning-api.md)

EXCUSES = [
    "It worked on my laptop. My laptop has since entered witness protection.",
    "The deploy succeeded spiritually.",
    "That's not a bug, it's an undocumented feature we're saving as a surprise.",
    "We were going to write tests, but the code looked really confident.",
    "It's not down. It's taking a strategic nap.",
    "The frontend and backend are currently not on speaking terms.",
    "We prayed, the pipeline went green, and we've agreed not to ask questions.",
    "Someone pushed to main. We don't know who. We have suspicions.",
    "It's 3 a.m., so every bug is officially a feature now.",
    "Cache invalidation is hard, so we've decided to simply believe.",
    "The code is self-documenting. It mostly says 'help'.",
    "We didn't break production. We just discovered where it was fragile.",
]


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/hello")
def hello():
    return {"message": "Hello from the backend", "env": os.getenv("APP_ENV", "local")}


@app.get("/api/excuse")
def excuse():
    return {"excuse": random.choice(EXCUSES)}


# In prod (the Docker image) the built frontend sits next to the backend and is served from here.
# Locally there's usually no build, and Vite serves the frontend instead.
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        if path.startswith("api/"):
            raise HTTPException(status_code=404)
        return FileResponse(DIST / "index.html")
