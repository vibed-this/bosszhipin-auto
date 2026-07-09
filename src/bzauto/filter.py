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