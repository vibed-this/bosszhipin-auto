import asyncio
import json
import logging

from bzauto.server import start_server, TabSession

log = logging.getLogger("main")


def print_tab_ready(msg: dict) -> None:
    print(
        f"\n[+] 标签就绪  chromeTabId={msg.get('chromeTabId')}  "
        f"source={msg.get('source')}  "
        f"{msg.get('title', '')}  {msg.get('url', '')}"
    )


def print_tab_changed(msg: dict) -> None:
    print(
        f"\n[*] 标签变化  chromeTabId={msg.get('chromeTabId')}  "
        f"changes={msg.get('changes', {})}"
    )


def print_tab_gone(msg: dict) -> None:
    print(
        f"\n[-] 标签消失  chromeTabId={msg.get('chromeTabId')}  "
        f"source={msg.get('source')}  "
        f"{msg.get('title', '')}  {msg.get('url', '')}"
    )


def print_execution_result(msg: dict) -> None:
    cid = msg.get("id", "")[:8]
    if msg.get("error"):
        print(f"\n[!] 执行出错 [{cid}]  {msg['error']}")
    else:
        data = json.dumps(msg["data"], ensure_ascii=False, default=str)
        print(f"\n[✓] 执行完成 [{cid}]  {data[:120]}")


async def main() -> None:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("boss").setLevel(logging.DEBUG)

    session = TabSession()

    session.on("tab_ready", print_tab_ready)
    session.on("tab_changed", print_tab_changed)
    session.on("tab_gone", print_tab_gone)
    session.on("execution_result", print_execution_result)

    print("等待扩展连接...\n")
    await start_server()
    await asyncio.Event().wait()


def cli_main() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
