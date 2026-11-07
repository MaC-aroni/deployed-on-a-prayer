import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

# backend/.env: written by deploy on the host laptop, copied from .env.example locally.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

app = FastAPI(title="deployed-on-a-prayer")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/hello")
def hello():
    return {"message": "Hello from the backend", "env": os.getenv("APP_ENV", "local")}
