"""职位过滤工具 — 采集与投递共用的黑名单匹配。"""
from __future__ import annotations


def match_blacklist(text: str, keywords: list[str]) -> str | None:
    """若 text 包含黑名单任一关键字则返回该关键字，否则 None。"""
    if not keywords or not text:
        return None
    haystack = text.casefold()
    for kw in keywords:
        k = kw.strip()
        if k and k.casefold() in haystack:
            return k
    return None


def match_city_blacklist(location: str | list[str] | None, keywords: list[str]) -> str | None:
    """城市黑名单完整匹配。

    城市取 location 的第一段（"杭州·滨江区" → "杭州"，或 list[0]）。
    只有当城市名与黑名单条目**完全相等**时才命中（大小写不敏感）。
    """
    if not keywords or not location:
        return None
    if isinstance(location, list):
        city = location[0] if location else ""
    else:
        # 支持 "杭州·xx" 或 "杭州"
        parts = [p.strip() for p in str(location).split("\u00B7") if p.strip()]
        city = parts[0] if parts else ""
    if not city:
        return None
    city_norm = city.strip()
    city_lower = city_norm.casefold()
    for kw in keywords:
        k = kw.strip()
        if k and k.casefold() == city_lower:
            return k
    return None