from router.pricing import PricingTable


def _table():
    return PricingTable({
        "default": 5.0,
        "1736": {
            "default": 8.0,
            "形势与政策": 12.0,
            "马克思主义基本原理": 10.0,
        },
        "1800": {
            "default": 5.0,
        },
    })


def test_resolve_exact_match():
    t = _table()
    assert t.resolve("1736", "形势与政策") == 12.0


def test_resolve_falls_back_to_platform_default():
    t = _table()
    assert t.resolve("1736", "未列出的课") == 8.0


def test_resolve_falls_back_to_global_default():
    t = _table()
    assert t.resolve("9999", "anything") == 5.0


def test_resolve_with_empty_table():
    t = PricingTable({})
    assert t.resolve("any", "any") == 0.0


def test_resolve_with_only_global_default():
    t = PricingTable({"default": 7.5})
    assert t.resolve("any", "any") == 7.5


def test_resolve_handles_none_inputs():
    t = _table()
    assert t.resolve(None, None) == 5.0


def test_estimate_total_sums_resolved_prices():
    t = _table()
    orders = [
        {"platform": "1736", "kcname": "形势与政策"},   # 12
        {"platform": "1736", "kcname": "其他"},          # 8 (platform default)
        {"platform": "9999", "kcname": "no plat"},       # 5 (global default)
    ]
    assert t.estimate_total(orders) == 25.0
