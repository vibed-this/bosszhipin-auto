#!/usr/bin/env python3
"""从 Boss 直聘官方接口拉取最新城市列表，并输出可直接粘贴到 CityPickerDialog 的 CITY_TREE。

用法:
    python scripts/fetch_boss_cities.py
"""
from __future__ import annotations

import json
import sys

import requests

URL = "https://www.zhipin.com/wapi/zpgeek/common/data/city/site.json"


def fetch_city_tree() -> list[dict]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    resp = requests.get(URL, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    zp_data = data.get("zpData", {})
    site_list = zp_data.get("siteList", [])

    tree: list[dict] = []
    for prov in site_list:
        pname = (prov.get("name") or "").strip()
        subs = prov.get("subLevelModelList") or []
        children = []
        for sub in subs:
            cname = (sub.get("name") or "").strip()
            if cname and cname != pname:
                children.append(cname)
        tree.append({"name": pname, "children": children})
    return tree


def main():
    try:
        tree = fetch_city_tree()
    except Exception as e:
        print(f"拉取失败: {e}", file=sys.stderr)
        sys.exit(1)

    print("# 自动生成的城市树数据（直接复制到 ui/config_dialog.py 的 CITY_TREE）")
    print("CITY_TREE = [")
    for entry in tree:
        name = entry["name"]
        children = entry["children"]
        if children:
            ch_str = json.dumps(children, ensure_ascii=False)
            print(f'    {{"name": "{name}", "children": {ch_str}}},')
        else:
            print(f'    {{"name": "{name}", "children": []}},')
    print("]")


if __name__ == "__main__":
    main()
