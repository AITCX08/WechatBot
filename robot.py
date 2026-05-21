# -*- coding: utf-8 -*-
import pexpect
import subprocess
import logging
import json
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from queue import Empty
from threading import Thread
from base.func_zhipu import ZhiPu
from Lexxue_api import ck, xd, cs
from wx import WxAdapter as Wcf
from wx import WxMsg
from router.dispatch import Dispatcher
from router.template import TemplateMatcher

from base.func_bard import BardAssistant
from base.func_chatglm import ChatGLM
from base.func_chatgpt import ChatGPT
from base.func_chengyu import cy
from base.func_news import News
from base.func_tigerbot import TigerBot
from base.func_xinghuo_web import XinghuoWeb
from configuration import Config
from constants import ChatType
from job_mgmt import Job

__version__ = "39.0.10.1"


class NullOrderHandler:
    """Placeholder until OrderHandler is added in Phase 4."""

    def is_pending_for(self, wxid: str) -> bool:
        return False

    def looks_like_order_intent(self, text: str) -> bool:
        return False

    def on_user_reply(self, msg) -> None:
        pass

    def handle_new_order_message(self, msg) -> None:
        pass


class Robot(Job):
    """个性化自己的机器人
    """

    def __init__(self, config: Config, wcf: Wcf, chat_type: int) -> None:
        self.wcf = wcf
        self.config = config
        self.LOG = logging.getLogger("Robot")
        self.wxid = self.wcf.get_self_wxid()
        self.allContacts = self.getAllContacts()
        self.chitchat_data = self.load_json_data()
        self.chitchat_images = self.load_json_images()
        self.chitchat_menu = self.load_json_menu()

        deepseek = True
        if deepseek:
            print("使用deepseek模型")
            self.chat = DeepSeek(self.config.DEEPSEEK)
        else:
            if ChatType.is_in_chat_types(chat_type):
                if chat_type == ChatType.DEEPSEEK.value and self.value_check(self.config.DEEPSEEK):
                    self.chat = DeepSeek(self.config.DEEPSEEK)
                elif chat_type == ChatType.TIGER_BOT.value and TigerBot.value_check(self.config.TIGERBOT):
                    self.chat = TigerBot(self.config.TIGERBOT)
                elif chat_type == ChatType.CHATGPT.value and ChatGPT.value_check(self.config.CHATGPT):
                    self.chat = ChatGPT(self.config.CHATGPT)
                elif chat_type == ChatType.XINGHUO_WEB.value and XinghuoWeb.value_check(self.config.XINGHUO_WEB):
                    self.chat = XinghuoWeb(self.config.XINGHUO_WEB)
                elif chat_type == ChatType.CHATGLM.value and ChatGLM.value_check(self.config.CHATGLM):
                    self.chat = ChatGLM(self.config.CHATGLM)
                elif chat_type == ChatType.BardAssistant.value and BardAssistant.value_check(self.config.BardAssistant):
                    self.chat = BardAssistant(self.config.BardAssistant)
                elif chat_type == ChatType.ZhiPu.value and ZhiPu.value_check(self.config.ZHIPU):
                    self.chat = ZhiPu(self.config.ZHIPU)
                else:
                    self.LOG.warning("未配置模型")
                    self.chat = None
            else:
                print("未使用模型")
                if TigerBot.value_check(self.config.TIGERBOT):
                    self.chat = TigerBot(self.config.TIGERBOT)
                elif ChatGPT.value_check(self.config.CHATGPT):
                    self.chat = ChatGPT(self.config.CHATGPT)
                elif XinghuoWeb.value_check(self.config.XINGHUO_WEB):
                    self.chat = XinghuoWeb(self.config.XINGHUO_WEB)
                elif ChatGLM.value_check(self.config.CHATGLM):
                    self.chat = ChatGLM(self.config.CHATGLM)
                elif BardAssistant.value_check(self.config.BardAssistant):
                    self.chat = BardAssistant(self.config.BardAssistant)
                elif ZhiPu.value_check(self.config.ZhiPu):
                    self.chat = ZhiPu(self.config.ZhiPu)
                else:
                    self.LOG.warning("未配置模型")
                    self.chat = None

        self.LOG.info(f"已选择: {self.chat}")

        self.template_matcher = TemplateMatcher(
            replies_path=Path("关键词回复.json"),
            images_path=Path("关键词发图.json"),
            menus_path=Path("菜单格式.json"),
        )
        self.dispatcher = Dispatcher(
            wx=self.wcf,
            template_matcher=self.template_matcher,
            order_handler=NullOrderHandler(),   # replaced in Phase 4
            llm=self.chat,
            groups_allowed=set(self.config.GROUPS or []),
        )

    @staticmethod
    def value_check(args: dict) -> bool:
        if args:
            return all(value is not None for key, value in args.items() if key != 'proxy')
        return False

    def toAt(self, msg: WxMsg) -> bool:
        """处理被 @ 消息
        :param msg: 微信消息结构
        :return: 处理状态，`True` 成功，`False` 失败
        """
        return self.toChitchat(msg)

    def toChengyu(self, msg: WxMsg) -> bool:
        """
        处理成语查询/接龙消息
        :param msg: 微信消息结构
        :return: 处理状态，`True` 成功，`False` 失败
        """
        status = False
        texts = re.findall(r"^([#|?|？])(.*)$", msg.content)
        # [('#', '天天向上')]
        if texts:
            flag = texts[0][0]
            text = texts[0][1]
            if flag == "#":  # 接龙
                if cy.isChengyu(text):
                    rsp = cy.getNext(text)
                    if rsp:
                        self.sendTextMsg(rsp, msg.roomid)
                        status = True
            elif flag in ["?", "？"]:  # 查词
                if cy.isChengyu(text):
                    rsp = cy.getMeaning(text)
                    if rsp:
                        self.sendTextMsg(rsp, msg.roomid)
                        status = True

        return status

    def load_json_data(self):
        try:
            with open('关键词回复.json', 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading chitchat data: {e}")
            return {}

    def load_json_images(self):
        try:
            with open('关键词发图.json', 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading chitchat images: {e}")
            return {}

    def load_json_menu(self):
        try:
            with open('菜单格式.json', 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading chitchat menu: {e}")
            return {}

    def get_response(self, msg: str):
        msg_str = str(msg)

        for keyword, response in self.chitchat_data.items():
            if keyword in msg_str:
                return response
        # return "机器人未能找到匹配的回复，请您等待客服的回复吧~"

    def get_response_from_data(self, msg_str):
        responses = []
        for keyword, response in self.chitchat_data.items():
            if keyword in msg_str:
                responses.append(response)
        return responses

    def get_image_from_images(self, msg_str):
        image_paths = []
        for keyword, image_path in self.chitchat_images.items():
            if keyword in msg_str:
                image_paths.append(image_path)
        return image_paths

    def get_menu_from_menu(self, msg_str):
        menus = []
        for keyword, menu_format in self.chitchat_menu.items():
            if keyword in msg_str:
                menus.append(menu_format)
        return menus

    def chat_bot(self, msg: str):
        msg_str = str(msg)

        if msg_str == "#获取课程列表":
            return None
        else:
            return self.get_response(msg_str)

    def toChitchat(self, msg: WxMsg) -> bool:
        """闲聊，接入 ChatGPT
        """
        msg_str = str(msg.content)
        sent_message = False

        if not self.chat:  # 没接 ChatGPT，固定回复
            responses = self.get_response_from_data(msg_str)
            for response in responses:
                if msg.from_group():
                    self.sendTextMsg(response, msg.roomid, msg.sender)
                else:
                    self.sendTextMsg(response, msg.sender)
                sent_message = True

            image_paths = self.get_image_from_images(msg_str)
            for image_path in image_paths:
                if msg.from_group():
                    self.sendImageMsg(image_path, msg.roomid)
                else:
                    self.sendImageMsg(image_path, msg.sender)
                sent_message = True

            menus = self.get_menu_from_menu(msg_str)
            for menu_format in menus:
                if msg.from_group():
                    self.sendTextMsg(menu_format, msg.roomid, msg.sender)
                else:
                    self.sendTextMsg(menu_format, msg.sender)
                sent_message = True

            if not sent_message:
                return False
        else:  # 接了 ChatGPT，智能回复
            q = re.sub(r"@.*?[\u2005|\s]", "", msg.content).replace(" ", "")
            response = self.chat.get_answer(q, (msg.roomid if msg.from_group() else msg.sender))

            if response:
                if msg.from_group():
                    self.sendTextMsg(response, msg.roomid, msg.sender)
                else:
                    self.sendTextMsg(response, msg.sender)
                return True
            else:
                self.LOG.error(f"无法从 ChatGPT 获得答案")
                return False

        return True

    def processMsg(self, msg: WxMsg) -> None:
        """当接收到消息的时候，会调用本方法。如果不实现本方法，则打印原始消息。
        此处可进行自定义发送的内容,如通过 msg.content 关键字自动获取当前天气信息，并发送到对应的群组@发送者
        群号：msg.roomid  微信ID：msg.sender  消息内容：msg.content
        content = "xx天气信息为："
        receivers = msg.roomid
        self.sendTextMsg(content, receivers, msg.sender)
        """
        self.dispatcher.handle(msg)

    def onMsg(self, msg: WxMsg) -> int:
        try:
            self.LOG.info(msg)  # 打印信息
            self.processMsg(msg)
        except Exception as e:
            self.LOG.error(e)

        return 0

    def enableRecvMsg(self) -> None:
        self.wcf.enable_recv_msg(self.onMsg)

    def enableReceivingMsg(self) -> None:
        def innerProcessMsg(wcf: Wcf):
            while wcf.is_receiving_msg():
                try:
                    msg = wcf.get_msg()
                    self.LOG.info(msg)
                    self.processMsg(msg)
                except Empty:
                    continue  # Empty message
                except Exception as e:
                    self.LOG.error(f"Receiving message error: {e}")

        self.wcf.enable_receiving_msg()
        Thread(target=innerProcessMsg, name="GetMessage", args=(self.wcf,), daemon=True).start()

    def sendTextMsg(self, msg: str, receiver: str, at_list: str = "") -> None:
        """ 发送消息
        :param msg: 消息字符串
        :param receiver: 接收人wxid或者群id
        :param at_list: 要@的wxid, @所有人的wxid为：notify@all
        """
        # msg 中需要有 @ 名单中一样数量的 @
        ats = ""
        if at_list:
            if at_list == "notify@all":  # @所有人
                ats = " @所有人"
            else:
                wxids = at_list.split(",")
                for wxid in wxids:
                    # 根据 wxid 查找群昵称
                    ats += f" @{self.wcf.get_alias_in_chatroom(wxid, receiver)}"

        # {msg}{ats} 表示要发送的消息内容后面紧跟@，例如 北京天气情况为：xxx @张三
        if ats == "":
            self.LOG.info(f"To {receiver}: {msg}")
            self.wcf.send_text(f"{msg}", receiver, at_list)
        else:
            self.LOG.info(f"To {receiver}: {ats}\r{msg}")
            self.wcf.send_text(f"{ats}\n\n{msg}", receiver, at_list)

    def sendImageMsg(self, image_path: str, receiver: str) -> None:
        """ 发送图片
        :param image_path: 图片路径或URL
        :param receiver: 接收人wxid或者群id
        """
        try:
            status = self.wcf.send_image(image_path, receiver)
            if status == 0:
                self.LOG.info(f"Sent image to {receiver}: {image_path}")
            else:
                self.LOG.error(f"Failed to send image to {receiver}: {image_path}, status code: {status}")
        except Exception as e:
            self.LOG.error(f"Failed to send image to {receiver}: {e}")

    def getAllContacts(self) -> dict:
        """
        获取联系人（包括好友、公众号、服务号、群成员……）
        格式: {"wxid": "NickName"}
        """
        contacts = self.wcf.query_sql("MicroMsg.db", "SELECT UserName, NickName FROM Contact;")
        return {contact["UserName"]: contact["NickName"] for contact in contacts}

    def keepRunningAndBlockProcess(self) -> None:
        """
        保持机器人运行，不让进程退出
        """
        while True:
            self.runPendingJobs()
            time.sleep(1)

    def autoAcceptFriendRequest(self, msg: WxMsg) -> None:
        try:
            xml = ET.fromstring(msg.content)
            v3 = xml.attrib["encryptusername"]
            v4 = xml.attrib["ticket"]
            scene = int(xml.attrib["scene"])
            self.wcf.accept_new_friend(v3, v4, scene)

        except Exception as e:
            self.LOG.error(f"同意好友出错：{e}")

    def sayHiToNewFriend(self, msg: WxMsg) -> None:
        nickName = re.findall(r"你已添加了(.*)，现在可以开始聊天了。", msg.content)
        if nickName:
            # 添加了好友，更新好友列表
            self.allContacts[msg.sender] = nickName[0]
            self.sendTextMsg(f"你好鸭同学 需要什么业务呢", msg.sender)

    def newsReport(self) -> None:
        receivers = self.config.NEWS
        if not receivers:
            return

        news = News().get_important_news()
        for r in receivers:
            self.sendTextMsg(news, r)


# 添加DeepSeek类定义（假设）
class DeepSeek:
    def __init__(self, config):
        self.config = None

    @classmethod
    def get_answer(cls, question, context=None):
        print('使用deepseek生成中.....')

        # 构建命令
        command = ['ollama', 'run', 'deepseek-r1:7b']

        # 启动子进程，并指定编码为UTF-8
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')

        # 发送问题到模型
        stdout, stderr = process.communicate(input=question)

        if process.returncode != 0:
            print(f"Error running model: {stderr}")
            return None

        # 去除 <think></think> 标签
        cleaned_output = stdout.replace('<think>\n\n</think>\n', '').strip()

        return cleaned_output


# print(DeepSeek.get_answer(question='你好'))