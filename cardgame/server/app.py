"""aiohttp application: static files + one websocket per browser tab.

Protocol (JSON objects, field ``op``):

client → server
    login {username, password}      resume {token}      logout
    lobby                           create {game, players?, options?}
    join {code}                     leave {code}        sit {code, seat}
    seat {code, seat, mode}         players {code, n}   options {code, options}
    start {code}
    action {code, action}           history {code}      rollback {code, index}
    export {code}                   import {code, state}
    close {code}

server → client
    login_ok {username, token, created}     error {message, op}
    lobby {rooms, games}                    room {room}
    room_closed {code}                      history {code, items}
    export {code, state}
"""
from __future__ import annotations

import hashlib
import json
import logging
import weakref
from pathlib import Path

from aiohttp import WSCloseCode, WSMsgType, web

from ..games import GAMES
from .auth import AuthError, Users
from .rooms import Room, RoomError, RoomManager
from .storage import Storage

log = logging.getLogger(__name__)
STATIC = Path(__file__).resolve().parent.parent / "static"


def static_version() -> str:
    """Hash of every static file; it goes into the URLs so that no cache
    (browser or a CDN in front of us) can serve stale JS/CSS after an update."""
    h = hashlib.sha256()
    for f in sorted(STATIC.rglob("*")):
        if f.is_file():
            h.update(str(f.relative_to(STATIC)).encode())
            h.update(f.read_bytes())
    return h.hexdigest()[:12]


class Client:
    def __init__(self, ws: web.WebSocketResponse):
        self.ws = ws
        self.user: str | None = None
        self.token: str | None = None
        self.room: str | None = None   # room the tab is currently looking at

    async def send(self, msg: dict) -> None:
        if not self.ws.closed:
            try:
                await self.ws.send_str(json.dumps(msg, ensure_ascii=False))
            except ConnectionError:
                pass


class Server:
    def __init__(self, data_dir: str | Path, ai_speed: float = 1.0):
        self.storage = Storage(data_dir)
        self.users = Users(self.storage)
        self.rooms = RoomManager(self.storage, ai_speed)
        self.rooms.on_change = self._room_changed
        self.rooms.load_all()
        self.clients: weakref.WeakSet[Client] = weakref.WeakSet()
        self._pending: set = set()

    # --------------------------------------------------------------- helpers
    def online(self, user: str) -> bool:
        return any(c.user == user for c in self.clients)

    def room_message(self, room: Room, user: str | None) -> dict:
        game = room.game
        seat = room.seat_of(user) if user else None
        prompts = game.prompts(room.state) if room.state else {}
        return {
            "op": "room",
            "room": {
                **room.summary(),
                "is_host": room.host == user,
                "option_specs": game.option_specs(),
                "static": game.static_info(),
                "min_players": game.min_players,
                "max_players": game.max_players,
                "seats": [
                    {"name": s.name, "user": s.user, "ai": s.ai is not None,
                     "online": s.ai is not None or (s.user is not None and self.online(s.user))}
                    for s in room.seats
                ],
                "my_seat": seat,
                "view": game.view(room.state, seat) if room.state else None,
                "prompt": prompts.get(seat) if seat is not None else None,
                "waiting": sorted(prompts),
                "history_len": len(room.history),
            },
        }

    def _spawn(self, coro) -> None:
        import asyncio
        t = asyncio.get_running_loop().create_task(coro)
        self._pending.add(t)
        t.add_done_callback(self._pending.discard)

    def _room_changed(self, room: Room) -> None:
        deleted = room.code not in self.rooms.rooms
        for c in list(self.clients):
            if c.user is None:
                continue
            if c.room == room.code:
                if deleted:
                    c.room = None
                    self._spawn(c.send({"op": "room_closed", "code": room.code}))
                else:
                    self._spawn(c.send(self.room_message(room, c.user)))
            elif c.room is None:
                self._spawn(c.send(self.lobby_message()))

    def _presence_changed(self, user: str) -> None:
        for room in self.rooms.rooms.values():
            if room.seat_of(user) is not None:
                self._room_changed(room)

    def lobby_message(self) -> dict:
        return {
            "op": "lobby",
            "rooms": self.rooms.list_rooms(),
            "games": [{"id": g.id, "name": g.name, "min_players": g.min_players, "max_players": g.max_players,
                       "options": g.option_specs()} for g in GAMES.values()],
        }

    # -------------------------------------------------------------- dispatch
    async def handle(self, c: Client, msg: dict) -> None:
        op = msg.get("op")
        if op == "login":
            name, token, created = self.users.login(msg.get("username"), msg.get("password"))
            await self._logged_in(c, name, token, created)
            return
        if op == "resume":
            name = self.users.resume(msg.get("token"))
            await self._logged_in(c, name, msg["token"], False)
            return
        if c.user is None:
            raise AuthError("请先登录")
        user = c.user
        code = msg.get("code")
        R = self.rooms
        if op == "logout":
            self.users.logout(c.token)
            c.user = c.token = c.room = None
            self._presence_changed(user)
        elif op == "lobby":
            c.room = None
            await c.send(self.lobby_message())
        elif op == "create":
            room = R.create(user, msg.get("game"), msg.get("players"), msg.get("options"))
            c.room = room.code
            await c.send(self.room_message(room, user))
        elif op == "join":
            room = R.get(code)
            c.room = room.code
            R.join(user, room.code)
        elif op == "leave":
            room = R.get(code)
            c.room = None
            R.leave(user, room.code)
            await c.send(self.lobby_message())
        elif op == "sit":
            R.sit(user, code, msg.get("seat"))
        elif op == "seat":
            R.set_seat(user, code, msg.get("seat"), msg.get("mode"))
        elif op == "players":
            R.set_players(user, code, msg.get("n"))
        elif op == "options":
            R.set_options(user, code, msg.get("options"))
        elif op == "start":
            R.start(user, code)
        elif op == "action":
            R.human_action(user, code, msg.get("action"))
        elif op == "history":
            await c.send({"op": "history", "code": code, "items": R.history_labels(user, code)})
        elif op == "rollback":
            R.rollback(user, code, msg.get("index"))
        elif op == "export":
            await c.send({"op": "export", "code": code, "state": R.export_state(user, code)})
        elif op == "import":
            R.import_state(user, code, msg.get("state"))
        elif op == "close":
            R.close(user, code)
        else:
            raise RoomError(f"未知请求 {op!r}")

    async def _logged_in(self, c: Client, name: str, token: str, created: bool) -> None:
        c.user, c.token = name, token
        await c.send({"op": "login_ok", "username": name, "token": token, "created": created})
        await c.send(self.lobby_message())
        self._presence_changed(name)

    # ------------------------------------------------------------- endpoints
    async def ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=16 * 1024 * 1024)
        await ws.prepare(request)
        c = Client(ws)
        self.clients.add(c)
        try:
            async for m in ws:
                if m.type != WSMsgType.TEXT:
                    continue
                try:
                    msg = json.loads(m.data)
                    if not isinstance(msg, dict):
                        raise ValueError
                except ValueError:
                    await c.send({"op": "error", "message": "消息格式错误"})
                    continue
                try:
                    await self.handle(c, msg)
                except (AuthError, RoomError) as e:
                    await c.send({"op": "error", "message": str(e), "req": msg.get("op")})
                except Exception:
                    log.exception("error handling %r", msg.get("op"))
                    await c.send({"op": "error", "message": "服务器内部错误", "req": msg.get("op")})
        finally:
            self.clients.discard(c)
            if c.user:
                self._presence_changed(c.user)
        return ws

    async def index(self, request: web.Request) -> web.Response:
        # /static/... -> /static/v/<version>/...; the modules import each other
        # by relative paths, so they all load from the versioned URL
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        html = html.replace('"/static/', f'"/static/v/{self.static_version}/')
        return web.Response(text=html, content_type="text/html", headers={"Cache-Control": "no-cache"})

    def make_app(self) -> web.Application:
        self.static_version = static_version()
        versioned = f"/static/v/{self.static_version}/"

        @web.middleware
        async def static_caching(request: web.Request, handler):
            resp = await handler(request)
            if request.path.startswith(versioned):
                # a new version gets a new URL, so these never change
                resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            elif request.path.startswith("/static/"):
                resp.headers["Cache-Control"] = "no-cache"
            return resp

        app = web.Application(middlewares=[static_caching])
        app.router.add_get("/", self.index)
        app.router.add_get("/ws", self.ws_handler)
        app.router.add_static(versioned, STATIC)

        async def old_version(request: web.Request) -> web.Response:
            # a tab opened before the last update
            raise web.HTTPFound(versioned + request.match_info["path"])

        app.router.add_get("/static/v/{ver}/{path:.*}", old_version)
        app.router.add_static("/static/", STATIC)

        async def on_startup(_app):
            self.rooms.resume_ai()

        async def on_shutdown(_app):
            # open sockets would hold the shutdown for a minute; browsers
            # reconnect on their own once the server is back
            for c in list(self.clients):
                await c.ws.close(code=WSCloseCode.GOING_AWAY, message=b"server restart")

        app.on_startup.append(on_startup)
        app.on_shutdown.append(on_shutdown)
        return app
