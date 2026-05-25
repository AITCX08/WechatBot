"""Lookup unit price per (platform, course-name)."""
from __future__ import annotations
from typing import Iterable


class PricingTable:
    """Two-level lookup: platform -> (course-name -> price | 'default').

    Schema in config.yaml:
        pricing:
          default: 5.0
          1736:
            default: 8.0
            "形势与政策": 12.0
          1800:
            default: 5.0
    """

    def __init__(self, table: dict):
        self._table = table or {}

    def resolve(self, platform, kcname) -> float:
        platform = str(platform) if platform is not None else ""
        kcname = str(kcname) if kcname is not None else ""
        plat = self._table.get(platform)
        if isinstance(plat, dict):
            if kcname in plat:
                return float(plat[kcname])
            if "default" in plat:
                return float(plat["default"])
        return float(self._table.get("default", 0.0))

    def estimate_total(self, orders: Iterable[dict]) -> float:
        return round(sum(self.resolve(o.get("platform"), o.get("kcname")) for o in orders), 2)
