#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import signal
import time
from argparse import ArgumentParser
from pathlib import Path

from configuration import Config
from constants import ChatType
from dashboard import log_handler as dash_log
from dashboard.accounts import AccountConfig, AccountState
from dashboard.launcher import ensure_weixin_running
from dashboard.server import run_in_thread as start_dashboard
from dashboard.state import get_state

LOG = logging.getLogger("main")


def _bootstrap_dashboard(config: Config) -> int:
    dash_log.install(root_level=logging.INFO)
    port = int(config.WEIXIN.get("dashboard_port", 9090))
    start_dashboard(host="127.0.0.1", port=port)
    LOG.info(f"Dashboard 启动: http://127.0.0.1:{port}")
    return port


def _make_bot_factory(config: Config, chat_type: int):
    """Build a factory callable that the AccountManager will invoke whenever
    a user clicks 'Start' on an account in the dashboard.

    Returns: (wx_adapter, robot, order_handler) tuple — the AccountManager
    stores these on the AccountState and uses them for snapshot/cleanup.
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


def main(chat_type: int, dashboard_only: bool = False, auto_start: bool = False):
    config = Config()
    port = _bootstrap_dashboard(config)
    state = get_state()

    # Register all configured accounts
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

    # Install the factory so dashboard 'Start' buttons work
    state.accounts.set_factory(_make_bot_factory(config, chat_type))

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
