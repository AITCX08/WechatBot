#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import signal
from argparse import ArgumentParser
from pathlib import Path

from configuration import Config
from constants import ChatType
from dashboard import log_handler as dash_log
from dashboard.server import run_in_thread as start_dashboard
from dashboard.state import get_state

LOG = logging.getLogger("main")


def weather_report(robot) -> None:
    """模拟发送天气预报"""
    receivers = ["filehelper"]
    report = "这就是获取到的天气情况了"
    for r in receivers:
        robot.sendTextMsg(report, r)


def _bootstrap_dashboard(config: Config) -> int:
    dash_log.install(root_level=logging.INFO)
    port = int(config.WEIXIN.get("dashboard_port", 9090))
    start_dashboard(host="127.0.0.1", port=port)
    LOG.info(f"Dashboard 启动: http://127.0.0.1:{port}")
    return port


def main(chat_type: int, dashboard_only: bool = False):
    config = Config()
    port = _bootstrap_dashboard(config)

    state = get_state()

    if dashboard_only:
        LOG.info("Dashboard-only 模式：不启动 bot；按 Ctrl+C 退出")
        try:
            while True:
                import time
                time.sleep(60)
        except KeyboardInterrupt:
            return

    # Lazy import bot stack so the dashboard can come up even if bot deps
    # (Weixin window, sidecar) aren't yet ready.
    from base.func_report_reminder import ReportReminder
    from robot import Robot, __version__
    from wx import WxAdapter

    try:
        wcf = WxAdapter(
            weixin_exe=Path(config.WEIXIN.get("exe", "")),
            sidecar_url=config.WEIXIN.get("sidecar_url", "http://127.0.0.1:9000"),
            decrypted_db_path=Path(config.WEIXIN.get("decrypted_db_path", "")),
            decrypt_repo=Path(config.WEIXIN["sidecar_repo"]) if config.WEIXIN.get("sidecar_repo") else None,
            self_wxid=config.WEIXIN.get("self_wxid") or "filehelper",
        )
        wcf.setup()
        state.wx_adapter = wcf
    except Exception as e:
        LOG.error(f"WxAdapter 初始化失败: {e}", exc_info=True)
        LOG.error("Bot 未启动；Dashboard 仍在 http://127.0.0.1:%d，请检查 Weixin/sidecar 后重启。", port)
        # Keep dashboard alive so user can see the error in the UI.
        try:
            while True:
                import time
                time.sleep(60)
        except KeyboardInterrupt:
            return

    def handler(sig, frame):
        try:
            wcf.cleanup()
        except Exception:
            pass
        exit(0)
    signal.signal(signal.SIGINT, handler)

    robot = Robot(config, wcf, chat_type)
    state.order_handler = getattr(robot.dispatcher, "order", None)

    robot.LOG.info(f"WeChatRobot【{__version__}】成功启动···")
    robot.sendTextMsg("机器人启动成功！", "filehelper")
    robot.enableReceivingMsg()

    robot.onEveryTime("07:00", weather_report, robot=robot)
    robot.onEveryTime("07:30", robot.newsReport)
    robot.onEveryTime("16:30", ReportReminder.remind, robot=robot)
    robot.keepRunningAndBlockProcess()


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument('-c', type=int, default=0, help=f'选择模型参数序号: {ChatType.help_hint()}')
    parser.add_argument('--dashboard-only', action='store_true',
                        help='只启动 Dashboard（不启动 bot, 不连 Weixin）')
    ns = parser.parse_args()
    main(ns.c, dashboard_only=ns.dashboard_only)
