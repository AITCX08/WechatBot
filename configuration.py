#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging.config
import os
import shutil

import yaml


class Config(object):
    def __init__(self) -> None:
        self.reload()

    def _load_config(self) -> dict:
        pwd = os.path.dirname(os.path.abspath(__file__))
        try:
            with open(f"{pwd}/config.yaml", "rb") as fp:
                yconfig = yaml.safe_load(fp)
        except FileNotFoundError:
            shutil.copyfile(f"{pwd}/config.yaml.template", f"{pwd}/config.yaml")
            with open(f"{pwd}/config.yaml", "rb") as fp:
                yconfig = yaml.safe_load(fp)

        return yconfig

    def reload(self) -> None:
        yconfig = self._load_config()
        logging.config.dictConfig(yconfig["logging"])
        self.GROUPS = yconfig["groups"]["enable"]
        self.NEWS = yconfig["news"]["receivers"]
        self.REPORT_REMINDERS = yconfig["report_reminder"]["receivers"]

        ai = True
        if ai == True:
            self.DEEPSEEK = yconfig.get("deepseek", {})
            self.CHATGPT = yconfig.get("chatgpt", {})
            self.TIGERBOT = yconfig.get("tigerbot", {})
            self.XINGHUO_WEB = yconfig.get("xinghuo_web", {})
            self.CHATGLM = yconfig.get("chatglm", {})
            self.BardAssistant = yconfig.get("bard", {})
            self.ZhiPu = yconfig.get("zhipu", {})
        else:
            self.DEEPSEEK = None
            self.CHATGPT = None
            self.TIGERBOT = None
            self.XINGHUO_WEB = None
            self.CHATGLM = None
            self.BardAssistant = None
            self.ZhiPu = None

        self.WEIXIN = yconfig.get("weixin", {})
        self.LEXUE = yconfig.get("lexue", {})
        order_safety_defaults = {
            "dry_run": True,
            "confirm_timeout_sec": 300,
            "max_extract_rounds": 3,
            "daily_limit": 50,
            "per_user_cooldown_sec": 60,
        }
        order_safety_defaults.update(yconfig.get("order_safety", {}))
        self.ORDER_SAFETY = order_safety_defaults
        self.LLM = yconfig.get("llm", {})
