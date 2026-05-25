#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import logging
import signal
import threading
import time
from argparse import ArgumentParser
from pathlib import Path

from configuration import Config
from constants import ChatType
from dashboard import log_handler as dash_log
from dashboard.accounts import AccountConfig, AccountState, AccountStatus
from dashboard.launcher import ensure_weixin_running
from dashboard.server import run_in_thread as start_dashboard
from dashboard.state import get_state
from router.notifier import Notifier
from router.pricing import PricingTable
from router.reporter import Reporter

LOG = logging.getLogger("main")

RUNTIME_ACCOUNTS_FILE = Path("data/runtime_accounts.json")


def _load_runtime_accounts() -> list[dict]:
    """Read accounts created via the dashboard UI (in addition to config.yaml)."""
    if not RUNTIME_ACCOUNTS_FILE.exists():
        return []
    try:
        return json.loads(RUNTIME_ACCOUNTS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        LOG.warning("failed to read %s: %s", RUNTIME_ACCOUNTS_FILE, e)
        return []


def _make_persister(config_names: set[str]):
    """Build a persistence callback that writes only dynamically-added accounts
    (i.e. those NOT in config.yaml) to data/runtime_accounts.json."""
    def persist(all_cfgs: list[AccountConfig]) -> None:
        RUNTIME_ACCOUNTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        dynamic = [
            {
                "name": c.name, "label": c.label, "exe": c.exe,
                "sidecar_url": c.sidecar_url, "sidecar_repo": c.sidecar_repo,
                "decrypted_db_path": c.decrypted_db_path, "self_wxid": c.self_wxid,
            }
            for c in all_cfgs if c.name not in config_names
        ]
        RUNTIME_ACCOUNTS_FILE.write_text(
            json.dumps(dynamic, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        LOG.info("persisted %d runtime accounts → %s", len(dynamic), RUNTIME_ACCOUNTS_FILE)
    return persist


def _bootstrap_dashboard(config: Config) -> int:
    dash_log.install(root_level=logging.INFO)
    port = int(config.WEIXIN.get("dashboard_port", 9090))
    start_dashboard(host="127.0.0.1", port=port)
    LOG.info(f"Dashboard 启动: http://127.0.0.1:{port}")
    return port


def _make_bot_factory(config: Config, chat_type: int, notifier=None):
    """Build a factory callable that the AccountManager will invoke whenever
    a user clicks 'Start' on an account in the dashboard.

    Returns: (wx_adapter, robot, order_handler) tuple — the AccountManager
    stores these on the AccountState and uses them for snapshot/cleanup.

    The optional `notifier` is captured via closure and wired into each
    per-account OrderHandler after the Robot is constructed.
    """
    # Import bot stack lazily so dashboard can run even without these deps.
    from robot import Robot
    from wx import WxAdapter

    def factory(acc_cfg: AccountConfig, acc_state: AccountState):
        LOG.info("[%s] launching Weixin: %s", acc_cfg.name, acc_cfg.exe)
        ensure_weixin_running(
            acc_cfg.exe,
            spawn_if_missing=True,
            login_timeout_sec=int(config.WEIXIN.get("login_timeout_sec", 120)),
        )

        LOG.info("[%s] setting up WxAdapter", acc_cfg.name)
        wcf = WxAdapter(
            weixin_exe=Path(acc_cfg.exe),
            sidecar_url=acc_cfg.sidecar_url,
            decrypted_db_path=Path(acc_cfg.decrypted_db_path) if acc_cfg.decrypted_db_path else Path("./wx/decrypted/contact.db"),
            decrypt_repo=Path(acc_cfg.sidecar_repo) if acc_cfg.sidecar_repo else None,
            self_wxid=acc_cfg.self_wxid or "filehelper",
        )
        wcf.setup()

        LOG.info("[%s] building Robot + Dispatcher + OrderHandler", acc_cfg.name)
        robot = Robot(config, wcf, chat_type)

        # Use a per-account audit log so multi-account orders don't collide
        try:
            audit_path = Path(f"logs/audit/orders-{acc_cfg.name}.jsonl")
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            oh = getattr(robot.dispatcher, "order", None)
            if oh is not None:
                oh.audit_log_path = audit_path
                # v2: per-account notifier wiring (notifier captured from outer scope)
                if notifier is not None:
                    oh.notifier = notifier
                    oh.account_name = acc_cfg.name
        except Exception as e:
            LOG.warning("[%s] could not switch audit path: %s", acc_cfg.name, e)

        robot.sendTextMsg("机器人已启动 ✅", "filehelper")
        robot.enableReceivingMsg()
        # Schedule daily jobs only once (first account); avoid duplicate fires.
        if acc_cfg.name == "default" or acc_state.config.name == get_state().accounts.names()[0]:
            robot.onEveryTime("07:30", robot.newsReport)

        order_handler = getattr(robot.dispatcher, "order", None)
        return wcf, robot, order_handler

    return factory


def _schedule_daily_reports(state, reporter, fh_cfg: dict) -> None:
    """Background thread: push each account's daily report at the configured HH:MM."""
    import schedule

    report_time = (fh_cfg.get("daily_report_time") if isinstance(fh_cfg, dict) else None) or "22:00"

    def _push_for_all():
        for acc in state.accounts.all():
            if acc.status.value != "running":
                continue
            try:
                rep = reporter.aggregate(account=acc.name, window="today")
                text = reporter.render_text(rep)
                adapter = acc.wx_adapter
                if adapter is not None:
                    adapter.send_text(text, "filehelper")
                    LOG.info("daily report pushed to %s", acc.name)
            except Exception as e:
                LOG.warning("daily report for %s failed: %s", acc.name, e)

    schedule.every().day.at(report_time).do(_push_for_all)

    def _runner():
        while True:
            try:
                schedule.run_pending()
            except Exception as e:
                LOG.warning("schedule.run_pending crashed: %s", e)
            time.sleep(30)

    t = threading.Thread(target=_runner, name="DailyReportScheduler", daemon=True)
    t.start()
    LOG.info("daily report scheduled at %s", report_time)


def main(chat_type: int, dashboard_only: bool = False, auto_start: bool = False):
    config = Config()
    port = _bootstrap_dashboard(config)
    state = get_state()

    # Register accounts from config.yaml
    config_names: set[str] = set()
    for inst in config.WEIXIN_INSTANCES:
        cfg = AccountConfig(
            name=inst.get("name", "default"),
            label=inst.get("label", inst.get("name", "default")),
            exe=inst.get("exe", ""),
            sidecar_url=inst.get("sidecar_url", "http://127.0.0.1:5678"),
            sidecar_repo=inst.get("sidecar_repo", ""),
            decrypted_db_path=inst.get("decrypted_db_path", ""),
            self_wxid=inst.get("self_wxid", ""),
        )
        state.accounts.register(cfg)
        config_names.add(cfg.name)

    # Then register accounts added at runtime via the dashboard UI
    for inst in _load_runtime_accounts():
        if inst.get("name") in config_names:
            continue   # config.yaml takes precedence
        cfg = AccountConfig(
            name=inst.get("name", ""),
            label=inst.get("label", inst.get("name", "")),
            exe=inst.get("exe", ""),
            sidecar_url=inst.get("sidecar_url", "http://127.0.0.1:5678"),
            sidecar_repo=inst.get("sidecar_repo", ""),
            decrypted_db_path=inst.get("decrypted_db_path", ""),
            self_wxid=inst.get("self_wxid", ""),
        )
        state.accounts.register(cfg)

    # Wire persistence callback (writes only dynamic accounts to the runtime file)
    state.accounts.set_persistence(_make_persister(config_names))

    # ---- v2 wiring: shared notifier + reporter ----
    pricing = PricingTable(getattr(config, "PRICING", {}) or {})
    reporter = Reporter(audit_dir=Path("logs/audit"), pricing=pricing)

    fh_cfg = config.LLM.get("filehelper", {}) if isinstance(config.LLM, dict) else {}
    if not isinstance(fh_cfg, dict):
        fh_cfg = {}
    quiet = tuple(fh_cfg.get("quiet_hours", ())) if fh_cfg.get("quiet_hours") else ()

    def _adapter_for(account_name: str):
        s = state.accounts.get(account_name)
        return s.wx_adapter if s else None

    notifier = Notifier(
        adapter_lookup=_adapter_for,
        cooldown_sec=int(fh_cfg.get("cooldown_sec", 300)),
        quiet_hours=quiet,
    )

    def _on_status_change(name: str, status):
        if status == AccountStatus.RUNNING:
            notifier.emit(name, "online", {})
        elif status == AccountStatus.STOPPED:
            notifier.emit(name, "offline", {})

    state.accounts.set_on_status_change(_on_status_change)
    LOG.info("notifier ready (cooldown=%ds quiet_hours=%s)",
             notifier._cooldown_sec, quiet or "off")

    # ---- v2: daily report scheduler ----
    _schedule_daily_reports(state, reporter, fh_cfg)

    # Install the factory so dashboard 'Start' buttons work
    state.accounts.set_factory(_make_bot_factory(config, chat_type, notifier=notifier))

    LOG.info("注册账号: %s", ", ".join(state.accounts.names()))
    LOG.info("Dashboard: http://127.0.0.1:%d  →  在网页上点 '启动' 即可逐个上线", port)

    if dashboard_only:
        LOG.info("dashboard-only 模式：不自动拉起任何账号")
    elif auto_start:
        LOG.info("auto-start 模式：尝试启动所有账号")
        for name in state.accounts.names():
            state.accounts.start(name)

    def handler(sig, frame):
        LOG.info("收到 SIGINT，正在停止所有账号...")
        for name in state.accounts.names():
            try:
                state.accounts.stop(name)
            except Exception:
                pass
        time.sleep(1.0)
        exit(0)
    signal.signal(signal.SIGINT, handler)

    # Block forever; everything else runs in background threads.
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument('-c', type=int, default=0, help=f'选择模型参数序号: {ChatType.help_hint()}')
    parser.add_argument('--dashboard-only', action='store_true',
                        help='只启动 Dashboard, 不注册启动函数')
    parser.add_argument('--auto-start', action='store_true',
                        help='启动后立即尝试拉起所有账号（默认是等用户在网页上手动点）')
    ns = parser.parse_args()
    main(ns.c, dashboard_only=ns.dashboard_only, auto_start=ns.auto_start)
