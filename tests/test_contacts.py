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
    # Alice has remark="小爱"; remark takes precedence over nick_name.
    assert contacts.wxid_to_name("wxid_alice") == "小爱"


def test_wxid_to_name_falls_back_to_nick_name(contacts):
    # Bob has no remark; falls back to nick_name.
    assert contacts.wxid_to_name("wxid_bob") == "Bob"


def test_wxid_to_name_unknown(contacts):
    assert contacts.wxid_to_name("wxid_nobody") is None


def test_name_to_wxid_by_remark(contacts):
    assert contacts.name_to_wxid("小爱") == "wxid_alice"


def test_name_to_wxid_by_nick_name(contacts):
    assert contacts.name_to_wxid("Bob") == "wxid_bob"


def test_alias_in_room_falls_back_to_global(contacts):
    # Real Weixin 4.x has NO chatroom_member_nickname table, so per-room
    # display name degrades to the global contact name (remark > nick_name).
    assert contacts.alias_in_room("wxid_alice", "123@chatroom") == "小爱"
    assert contacts.alias_in_room("wxid_bob", "123@chatroom") == "Bob"


def test_alias_in_room_unknown_returns_wxid(contacts):
    # Unknown member, unknown room → returns the wxid itself (last-resort).
    assert contacts.alias_in_room("wxid_ghost", "123@chatroom") == "wxid_ghost"


def test_all_contacts_returns_dict(contacts):
    all_ = contacts.all_contacts()
    assert all_["wxid_alice"] == "小爱"
    assert all_["wxid_bob"] == "Bob"


def test_real_schema_no_type_column_loads_clean(contacts):
    # Regression guard: real `contact` has no `type` column and there is no
    # chatroom_member_nickname table; refresh() must not raise on that schema.
    assert "wxid_alice" in contacts.all_contacts()
