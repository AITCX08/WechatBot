from pathlib import Path
import pytest
from wx.contacts import ContactsBackend


FIXTURE_DB = Path(__file__).parent / "fixtures" / "sample_contact.db"


@pytest.fixture
def contacts():
    b = ContactsBackend(FIXTURE_DB)
    b.refresh()
    return b


def test_wxid_to_name_prefers_remark(contacts):
    # Alice has remark="小爱"; remark takes precedence
    assert contacts.wxid_to_name("wxid_alice") == "小爱"


def test_wxid_to_name_falls_back_to_nickname(contacts):
    assert contacts.wxid_to_name("wxid_bob") == "Bob"


def test_wxid_to_name_unknown(contacts):
    assert contacts.wxid_to_name("wxid_nobody") is None


def test_name_to_wxid_by_remark(contacts):
    assert contacts.name_to_wxid("小爱") == "wxid_alice"


def test_name_to_wxid_by_nickname(contacts):
    assert contacts.name_to_wxid("Bob") == "wxid_bob"


def test_alias_in_room_present(contacts):
    assert contacts.alias_in_room("wxid_alice", "123@chatroom") == "群里的爱丽丝"


def test_alias_in_room_fallback_to_global(contacts):
    # Bob has no chatroom-specific nickname; falls back to remark/nickname.
    assert contacts.alias_in_room("wxid_bob", "123@chatroom") == "Bob"


def test_all_contacts_returns_dict(contacts):
    all_ = contacts.all_contacts()
    assert all_["wxid_alice"] == "小爱"
    assert all_["wxid_bob"] == "Bob"
