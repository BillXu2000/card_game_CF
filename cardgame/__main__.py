"""Start the game server:  python -m cardgame [--listen IP] [--port N]

Listen address: --listen, else $ZEROTIER_IP, else 127.0.0.1.
"""
from __future__ import annotations

import argparse
import logging
import os

from aiohttp import web

from .server.app import Server


def main() -> None:
    ap = argparse.ArgumentParser(prog="cardgame", description="局域网卡牌游戏服务器")
    ap.add_argument("--listen", help="监听地址（默认 $ZEROTIER_IP，未设置则 127.0.0.1）")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--data", default="data", help="数据目录（用户、房间）")
    ap.add_argument("--ai-speed", type=float, default=1.0, help="AI 等待时间倍率，0 为不等待")
    args = ap.parse_args()

    host = args.listen or os.environ.get("ZEROTIER_IP") or "127.0.0.1"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    server = Server(args.data, args.ai_speed)
    print(f"服务器地址: http://{host}:{args.port}/", flush=True)
    web.run_app(server.make_app(), host=host, port=args.port, print=None)


if __name__ == "__main__":
    main()
