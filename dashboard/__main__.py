"""Standalone dashboard launcher.

Usage:
    python -m dashboard                 # default port 9090
    python -m dashboard --port 9090
    python -m dashboard --host 0.0.0.0  # accept LAN connections

This launches ONLY the web dashboard, with no Weixin/sidecar dependency.
Useful for previewing the UI, or running the dashboard in a separate
process from the bot itself.
"""
from __future__ import annotations
import argparse
import logging
import time

from dashboard import log_handler as dash_log
from dashboard.accounts import AccountConfig
from dashboard.server import run_in_thread
from dashboard.state import get_state


def main() -> None:
    p = argparse.ArgumentParser(description="WeChatRobot Dashboard (standalone)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9090)
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    )
    dash_log.install(root_level=logging.INFO)

    run_in_thread(host=args.host, port=args.port)

    state = get_state()
    LOG = logging.getLogger("dashboard")
    LOG.info("Dashboard standalone @ http://%s:%d", args.host, args.port)
    LOG.info("Bot 未连接；UI 上 Sidecar / Weixin / 队列状态会显示离线。")
    LOG.info("Ctrl+C 退出。")

    # Demo accounts so the empty UI shows the multi-account layout.
    state.accounts.register(AccountConfig(name="demo-main", label="演示·主账号",
                                          exe=r"C:\Program Files\Tencent\Weixin\Weixin.exe"))
    state.accounts.register(AccountConfig(name="demo-support", label="演示·客服号",
                                          exe=r"C:\Program Files\Tencent\Weixin\Weixin.exe"))

    # Demo: seed some logs so the empty UI looks alive on first visit.
    state.logs.append({"ts": time.time(), "level": "INFO", "logger": "demo",
                       "message": "Dashboard 已启动 (standalone 模式，不会真的启动 Weixin)"})
    state.logs.append({"ts": time.time(), "level": "INFO", "logger": "demo",
                       "message": "若要看到真实数据，运行 python main.py -c 7"})
    state.logs.append({"ts": time.time(), "level": "WARNING", "logger": "demo",
                       "message": "Standalone 模式没注册 factory，账号 Start 按钮会报 400"})

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        LOG.info("Bye.")


if __name__ == "__main__":
    main()
