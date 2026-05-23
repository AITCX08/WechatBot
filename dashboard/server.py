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
from pydantic import BaseModel, Field

from dashboard.accounts import AccountConfig
from dashboard.state import BotState, get_state


class AccountCreate(BaseModel):
    name: str = Field(..., pattern=r"^[a-zA-Z0-9_\-]{1,32}$",
                      description="账号唯一标识；只能用字母/数字/_/-")
    label: str = ""
    exe: str = ""
    sidecar_url: str = "http://127.0.0.1:5678"
    sidecar_repo: str = ""
    decrypted_db_path: str = ""
    self_wxid: str = ""

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
    def api_pending_orders(account: Optional[str] = None):
        items = []
        handlers = []
        if account:
            acc = state.accounts.get(account)
            if acc and acc.order_handler is not None:
                handlers.append((account, acc.order_handler))
        else:
            for acc in state.accounts.all():
                if acc.order_handler is not None:
                    handlers.append((acc.name, acc.order_handler))
            if state.order_handler is not None and not handlers:
                handlers.append(("default", state.order_handler))
        for acc_name, oh in handlers:
            try:
                for wxid, draft in oh._pending.items():  # type: ignore[attr-defined]
                    items.append({
                        "account": acc_name,
                        "wxid": wxid,
                        **draft.to_dict(),
                    })
            except Exception:
                pass
        return {"items": items}

    # ---- accounts ----
    @app.get("/api/accounts")
    def api_accounts():
        return {"items": state.accounts.snapshot_all()}

    @app.post("/api/accounts")
    def api_account_create(body: AccountCreate):
        if state.accounts.get(body.name) is not None:
            raise HTTPException(400, f"账号 '{body.name}' 已存在")
        # Fill in sensible defaults for blank fields
        decrypted = body.decrypted_db_path or f"./wx/decrypted/{body.name}/contact.db"
        cfg = AccountConfig(
            name=body.name,
            label=body.label or body.name,
            exe=body.exe,
            sidecar_url=body.sidecar_url,
            sidecar_repo=body.sidecar_repo,
            decrypted_db_path=decrypted,
            self_wxid=body.self_wxid,
        )
        state.accounts.register(cfg, persist=True)
        return {"ok": True, "msg": f"账号 '{body.name}' 已添加"}

    @app.delete("/api/accounts/{name}")
    def api_account_delete(name: str):
        ok, msg = state.accounts.unregister(name)
        if not ok:
            raise HTTPException(400, msg)
        return {"ok": True, "msg": msg}

    @app.post("/api/accounts/{name}/start")
    def api_account_start(name: str):
        ok, msg = state.accounts.start(name)
        if not ok:
            raise HTTPException(400, msg)
        return {"ok": True, "msg": msg}

    @app.post("/api/accounts/{name}/stop")
    def api_account_stop(name: str):
        ok, msg = state.accounts.stop(name)
        if not ok:
            raise HTTPException(400, msg)
        return {"ok": True, "msg": msg}

    @app.post("/api/accounts/{name}/pause")
    async def api_account_pause(name: str, req: Request):
        reason = ""
        try:
            body = await req.json()
            reason = (body or {}).get("reason", "")
        except Exception:
            pass
        ok, msg = state.accounts.pause(name, reason)
        if not ok:
            raise HTTPException(400, msg)
        return {"ok": True, "msg": msg}

    @app.post("/api/accounts/{name}/resume")
    def api_account_resume(name: str):
        ok, msg = state.accounts.resume(name)
        if not ok:
            raise HTTPException(400, msg)
        return {"ok": True, "msg": msg}

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
