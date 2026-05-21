import json
from pathlib import Path
import pytest

from router.template import TemplateMatcher


@pytest.fixture
def kw_replies(tmp_path):
    p = tmp_path / "replies.json"
    p.write_text(json.dumps({
        "你好": "你好！请问需要什么帮助？",
        "营业时间": "周一至周日 9:00-21:00",
    }, ensure_ascii=False), encoding="utf-8")
    return p


@pytest.fixture
def kw_images(tmp_path):
    p = tmp_path / "images.json"
    p.write_text(json.dumps({
        "菜单图": "images/menu.png",
    }, ensure_ascii=False), encoding="utf-8")
    return p


@pytest.fixture
def kw_menus(tmp_path):
    p = tmp_path / "menus.json"
    p.write_text(json.dumps({
        "菜单": "1. 课程查询\n2. 下单",
    }, ensure_ascii=False), encoding="utf-8")
    return p


@pytest.fixture
def tm(kw_replies, kw_images, kw_menus):
    return TemplateMatcher(
        replies_path=kw_replies, images_path=kw_images, menus_path=kw_menus
    )


def test_text_match_exact(tm):
    actions = tm.match("你好")
    assert any(a.kind == "text" and a.payload == "你好！请问需要什么帮助？" for a in actions)


def test_text_match_substring(tm):
    actions = tm.match("请问营业时间是什么时候")
    assert any(a.kind == "text" and a.payload == "周一至周日 9:00-21:00" for a in actions)


def test_image_match(tm):
    actions = tm.match("菜单图")
    assert any(a.kind == "image" and a.payload == "images/menu.png" for a in actions)


def test_menu_match(tm):
    actions = tm.match("查看菜单")
    assert any(a.kind == "menu" and a.payload == "1. 课程查询\n2. 下单" for a in actions)


def test_no_match_returns_empty(tm):
    assert tm.match("完全无关的话题") == []


def test_multiple_matches_returned(tm):
    actions = tm.match("你好 我想看菜单")
    kinds = [a.kind for a in actions]
    assert "text" in kinds
    assert "menu" in kinds
