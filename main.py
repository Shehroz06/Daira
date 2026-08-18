"""Diara — FastAPI entrypoint.

Endpoints:
    GET    /                -> static frontend
    POST   /chat            -> NDJSON streaming chat response
    GET    /health          -> status of index + providers
    GET    /chats           -> list saved chats (id, title, updated_at)
    GET    /chats/{chat_id} -> one chat's full transcript
    DELETE /chats/{chat_id} -> delete a chat

Run:  uvicorn main:app --reload
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

# Must run before any os.getenv() call below (and before numpy is imported
# transitively via diara -> rag) for .env values to take effect.
load_dotenv(Path(__file__).resolve().parent / ".env")

_num_threads = os.getenv("DIARA_NUM_THREADS", "").strip()
if _num_threads:
    for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ.setdefault(_var, _num_threads)

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import chat_store, diara
from app.llm import LLM_PROVIDER, OLLAMA_MODEL, gemini_available
from app.rag import index

logging.basicConfig(
    level=logging.DEBUG if os.getenv("DIARA_DEBUG", "").lower() in ("1", "true") else logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("diara.main")

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    index.load()
    try:
        chat_store.init_db()
    except Exception:
        logger.exception("Failed to initialize chat_store DB; chat history will be unavailable")
    yield


app = FastAPI(title="Diara — Legal AI Consultant", lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: str = Field("default", max_length=100)


@app.post("/chat")
async def chat(req: ChatRequest):
    """Stream the answer as NDJSON events (meta, chunk, debug, error)."""

    def event_stream():
        try:
            for event in diara.chat(req.message, req.session_id):
                yield json.dumps(event, ensure_ascii=False) + "\n"
        except Exception:
            # Controlled error — never leak a stack trace to the client.
            logger.exception("Unhandled error in chat pipeline")
            yield json.dumps({
                "type": "error",
                "message": "An internal error occurred. Please try again.",
            }) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@app.get("/chats")
async def list_chats():
    return {"chats": chat_store.list_chats()}


@app.get("/chats/{chat_id}")
async def get_chat(chat_id: str):
    chat = chat_store.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat


@app.delete("/chats/{chat_id}")
async def delete_chat(chat_id: str):
    if not chat_store.delete_chat(chat_id):
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"status": "ok"}


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "documents": len(index.docs),
        "vector_search": index.embed_ok,
        "provider_mode": LLM_PROVIDER,
        "gemini_configured": gemini_available(),
        "ollama_model": OLLAMA_MODEL,
    }


@app.get("/")
async def root():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
