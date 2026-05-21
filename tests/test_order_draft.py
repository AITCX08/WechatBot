import time
from router.order_draft import OrderDraft


def test_orderdraft_complete_true_when_all_fields_set():
    d = OrderDraft(
        school="北理工", user="18543", password="wjx",
        platform="1736", kcid="40", kcname="形势与政策",
        requester_wxid="wxid_x", created_at=int(time.time()),
    )
    assert d.is_complete()


def test_orderdraft_complete_false_when_missing():
    d = OrderDraft(
        school="北理工", user="18543", password=None,
        platform="1736", kcid="40", kcname="形势与政策",
        requester_wxid="wxid_x", created_at=0,
    )
    assert not d.is_complete()
    assert "password" in d.missing_fields()


def test_orderdraft_summary_includes_all_fields():
    d = OrderDraft(
        school="北理工", user="18543", password="wjx",
        platform="1736", kcid="40", kcname="形势与政策",
        requester_wxid="wxid_x", created_at=0,
    )
    s = d.summary_for_confirmation()
    assert "北理工" in s
    assert "18543" in s
    assert "形势与政策" in s


def test_orderdraft_expired():
    d = OrderDraft(
        school=None, user=None, password=None,
        platform=None, kcid=None, kcname=None,
        requester_wxid="x", created_at=int(time.time()) - 1000,
    )
    assert d.is_expired(timeout_sec=300)


def test_orderdraft_merge_keeps_existing_values():
    d = OrderDraft(
        school="北理工", user=None, password=None,
        platform=None, kcid=None, kcname=None,
        requester_wxid="x", created_at=0,
    )
    d.merge({"user": "18543", "school": None})
    assert d.school == "北理工"   # not overwritten by None
    assert d.user == "18543"
