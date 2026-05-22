from __future__ import annotations
import asyncio
import json
import threading
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from dashboard.state import BotState, get_state

HERE = Path(__file__).parent
TEMPLATES_DIR = HERE / "templates"
STATIC_DIR = HERE / "static"


def create_app(state: Optional[BotState] = None) -> FastAPI:
    """Build a FastAPI app bound to the given BotState (or the singleton)."""
    state = state or get_state()
    app = FastAPI(title="WeChatRobot Dashboard", version="1.0")

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # ---- root ----
    @app.get("/", response_class=HTMLResponse)
    def index():
        idx = TEMPLATES_DIR / "index.html"
        if not idx.exists():
            return HTMLResponse("<h1>Dashboard template missing</h1>", status_code=500)
        return HTMLResponse(idx.read_text(encoding="utf-8"))

    # ---- status ----
    @app.get("/api/status")
    def api_status():
        return state.snapshot()

    # ---- pause / resume ----
    @app.post("/api/pause")
    async def api_pause(req: Request):
        reason = ""
        try:
            body = await req.json()
            reason = (body or {}).get("reason", "")
        except Exception:
            pass
        state.pause(reason)
        return {"ok": True, "paused": True, "reason": state.pause_reason}

    @app.post("/api/resume")
    def api_resume():
        state.resume()
        return {"ok": True, "paused": False}

    # ---- logs ----
    @app.get("/api/logs")
    def api_logs(
        n: int = Query(200, ge=1, le=2000),
        level: Optional[str] = None,
        q: Optional[str] = None,
        since_seq: int = 0,
    ):
        rows = state.logs.snapshot(since_seq=since_seq)
        rows = [(seq, entry) for seq, entry in rows]
        if level:
            level_u = level.upper()
            rows = [(s, e) for s, e in rows if e.get("level") == level_u]
        if q:
            qq = q.lower()
            rows = [(s, e) for s, e in rows if qq in e.get("message", "").lower()]
        if len(rows) > n:
            rows = rows[-n:]
        return {
            "items": [{"seq": s, **e} for s, e in rows],
            "last_seq": state.logs.last_seq,
        }

    # ---- messages ----
    @app.get("/api/messages")
    def api_messages(
        n: int = Query(100, ge=1, le=500),
        q: Optional[str] = None,
        since_seq: int = 0,
    ):
        rows = state.messages.snapshot(since_seq=since_seq)
        if q:
            qq = q.lower()
            rows = [(s, e) for s, e in rows if qq in str(e.get("content", "")).lower()
                    or qq in str(e.get("sender", "")).lower()]
        if len(rows) > n:
            rows = rows[-n:]
        return {
            "items": [{"seq": s, **e} for s, e in rows],
            "last_seq": state.messages.last_seq,
        }

    # ---- audit / orders ----
    @app.get("/api/audit")
    def api_audit(
        n: int = Query(100, ge=1, le=500),
        event: Optional[str] = None,
        since_seq: int = 0,
    ):
        rows = state.audit.snapshot(since_seq=since_seq)
        if event:
            rows = [(s, e) for s, e in rows if e.get("event") == event]
        if len(rows) > n:
            rows = rows[-n:]
        return {
            "items": [{"seq": s, **e} for s, e in rows],
            "last_seq": state.audit.last_seq,
        }

    # ---- contacts (uses adapter if available) ----
    @app.get("/api/contacts")
    def api_contacts(q: Optional[str] = None, n: int = Query(50, ge=1, le=500)):
        adapter = state.wx_adapter
        if adapter is None:
            return {"items": [], "total": 0, "note": "wx adapter not initialized"}
        try:
            all_ = adapter._contacts.all_contacts()  # type: ignore[attr-defined]
        except Exception as e:
            raise HTTPException(500, f"contacts fetch failed: {e}")
        rows = list(all_.items())
        if q:
            qq = q.lower()
            rows = [(wxid, name) for wxid, name in rows
                    if qq in wxid.lower() or qq in (name or "").lower()]
        total = len(rows)
        rows = rows[:n]
        return {
            "items": [{"wxid": wxid, "name": name} for wxid, name in rows],
            "total": total,
        }

    # ---- pending orders ----
    @app.get("/api/orders/pending")
    def api_pending_orders():
        oh = state.order_handler
        if oh is None:
            return {"items": []}
        items = []
        try:
            for wxid, draft in oh._pending.items():  # type: ignore[attr-defined]
                items.append({
                    "wxid": wxid,
                    **draft.to_dict(),
                })
        except Exception:
            pass
        return {"items": items}

    # ---- SSE stream ----
    @app.get("/api/events")
    async def api_events(request: Request):
        async def gen():
            last_log = 0
            last_msg = 0
            last_audit = 0
            try:
                while True:
                    if await request.is_disconnected():
                        break

                    # Status frame every cycle
                    snap = state.snapshot()
                    yield "event: status\ndata: " + json.dumps(snap) + "\n\n"

                    # Incremental logs
                    new_logs = state.logs.snapshot(since_seq=last_log)
                    if new_logs:
                        last_log = new_logs[-1][0]
                        payload = [{"seq": s, **e} for s, e in new_logs[-50:]]
                        yield "event: logs\ndata: " + json.dumps(payload, ensure_ascii=False) + "\n\n"

                    # Incremental messages
                    new_msgs = state.messages.snapshot(since_seq=last_msg)
                    if new_msgs:
                        last_msg = new_msgs[-1][0]
                        payload = [{"seq": s, **e} for s, e in new_msgs[-50:]]
                        yield "event: messages\ndata: " + json.dumps(payload, ensure_ascii=False) + "\n\n"

                    # Incremental audit
                    new_audit = state.audit.snapshot(since_seq=last_audit)
                    if new_audit:
                        last_audit = new_audit[-1][0]
                        payload = [{"seq": s, **e} for s, e in new_audit[-50:]]
                        yield "event: audit\ndata: " + json.dumps(payload, ensure_ascii=False) + "\n\n"

                    await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                return

        return StreamingResponse(gen(), media_type="text/event-stream")

    return app


def run_in_thread(host: str = "127.0.0.1", port: int = 9090) -> threading.Thread:
    """Start uvicorn in a daemon thread so the bot main loop is not blocked."""
    import uvicorn

    app = create_app()
    config = uvicorn.Config(
        app, host=host, port=port, log_level="warning", access_log=False
    )
    server = uvicorn.Server(config)

    def _run():
        # uvicorn must own its event loop; runs in this thread.
        server.run()

    t = threading.Thread(target=_run, name="DashboardServer", daemon=True)
    t.start()
    # Give it a moment to bind so the first request after launch doesn't 404.
    time.sleep(0.3)
    return t
