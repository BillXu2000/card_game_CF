import asyncio

import pytest
from aiohttp.test_utils import TestClient, TestServer

from cardgame.games import GAMES, register
from cardgame.server.app import Server
from tests.duel import Duel

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def duel_game():
    register(Duel())
    yield
    GAMES.pop("duel", None)


class WS:
    def __init__(self, ws):
        self.ws = ws

    async def send(self, **msg):
        await self.ws.send_json(msg)

    async def expect(self, op, timeout=3.0, pred=lambda m: True):
        while True:
            m = await asyncio.wait_for(self.ws.receive_json(), timeout)
            if m["op"] == op and pred(m):
                return m
            if m["op"] == "error" and op != "error":
                raise AssertionError(m)


async def make_client(tmp_path, data="data"):
    server = Server(tmp_path / data, ai_speed=0)
    client = TestClient(TestServer(server.make_app()))
    await client.start_server()
    return server, client


async def connect(client, name, password=""):
    ws = WS(await client.ws_connect("/ws"))
    await ws.send(op="login", username=name, password=password)
    ok = await ws.expect("login_ok")
    await ws.expect("lobby")
    return ws, ok["token"]


async def test_login_register_and_password(tmp_path):
    server, client = await make_client(tmp_path)
    try:
        ws, token = await connect(client, "amy", "pw")
        bad = WS(await client.ws_connect("/ws"))
        await bad.send(op="login", username="amy", password="nope")
        err = await bad.expect("error")
        assert err["message"] == "密码错误"
        again = WS(await client.ws_connect("/ws"))
        await again.send(op="resume", token=token)
        assert (await again.expect("login_ok"))["username"] == "amy"
        # empty password registration works
        await connect(client, "bob", "")
        await connect(client, "bob", "")
    finally:
        await client.close()


async def test_room_game_with_ai_rollback_and_masking(tmp_path):
    server, client = await make_client(tmp_path)
    try:
        amy, _ = await connect(client, "amy")
        await amy.send(op="create", game="duel")
        room = (await amy.expect("room"))["room"]
        code = room["code"]
        assert len(code) == 4 and code.isalpha() and code.isupper()
        await amy.send(op="seat", code=code, seat=1, mode="ai")
        await amy.expect("room", pred=lambda m: m["room"]["seats"][1]["ai"])
        await amy.send(op="start", code=code)
        r = (await amy.expect("room", pred=lambda m: m["room"]["status"] == "playing"))["room"]
        view = r["view"]
        assert all(c is None for c in view["zones"]["hand:1"]["cards"])
        # AI (speed 0) answers its simultaneous prompt; we answer ours
        played = set()
        while r["status"] != "finished":
            if r["prompt"]:
                card = r["prompt"]["legal"][0]
                played.add(card)
                await amy.send(op="action", code=code, action={"type": "choose", "card": card})
            r = (await amy.expect("room", pred=lambda m: m["room"]["status"] == "finished" or (
                m["room"]["prompt"] and not played & set(m["room"]["prompt"]["legal"]))))["room"]
        assert sum(r["view"]["vars"]["scores"]) == 3
        await amy.send(op="history", code=code)
        hist = (await amy.expect("history"))["items"]
        assert hist[0]["label"] == "开始" and len(hist) == 7
        await amy.send(op="rollback", code=code, index=0)
        r = (await amy.expect("room", pred=lambda m: m["room"]["status"] == "playing"))["room"]
        assert r["view"]["vars"]["round"] == 0
        # export / import round trip
        await amy.send(op="export", code=code)
        state = (await amy.expect("export"))["state"]
        assert state["game"] == "duel"
        await amy.send(op="import", code=code, state=state)
        await amy.expect("room")
    finally:
        await client.close()


async def test_second_player_and_permissions(tmp_path):
    server, client = await make_client(tmp_path)
    try:
        amy, _ = await connect(client, "amy")
        await amy.send(op="create", game="duel")
        code = (await amy.expect("room"))["room"]["code"]
        bob, _ = await connect(client, "bob")
        await bob.send(op="join", code=code.lower())
        r = (await bob.expect("room"))["room"]
        assert r["my_seat"] == 1 and not r["is_host"]
        await bob.send(op="start", code=code)
        assert (await bob.expect("error"))["message"] == "只有房主可以这样做"
        await amy.send(op="start", code=code)
        await bob.expect("room", pred=lambda m: m["room"]["status"] == "playing")
        # bob leaves mid-game: the seat is kept and he can come back
        await bob.send(op="leave", code=code)
        await bob.expect("lobby")
        await bob.send(op="join", code=code)
        assert (await bob.expect("room"))["room"]["my_seat"] == 1
    finally:
        await client.close()


async def test_rooms_survive_restart(tmp_path):
    server, client = await make_client(tmp_path, "d")
    amy, _ = await connect(client, "amy", "pw")
    await amy.send(op="create", game="duel")
    code = (await amy.expect("room"))["room"]["code"]
    await amy.send(op="seat", code=code, seat=1, mode="ai")
    await amy.expect("room", pred=lambda m: m["room"]["seats"][1]["ai"])
    await amy.send(op="start", code=code)
    r = (await amy.expect("room", pred=lambda m: m["room"]["status"] == "playing"))["room"]
    seq = r["view"]["seq"]
    await client.close()

    server2, client2 = await make_client(tmp_path, "d")
    try:
        amy, _ = await connect(client2, "amy", "pw")
        await amy.send(op="join", code=code)
        r = (await amy.expect("room"))["room"]
        assert r["status"] == "playing" and r["view"]["seq"] >= seq and r["my_seat"] == 0
    finally:
        await client2.close()


async def test_import_rejects_broken_game_data(tmp_path):
    server, client = await make_client(tmp_path)
    try:
        amy, _ = await connect(client, "amy")
        await amy.send(op="create", game="duel")
        code = (await amy.expect("room"))["room"]["code"]
        await amy.send(op="seat", code=code, seat=1, mode="ai")
        await amy.expect("room", pred=lambda m: m["room"]["seats"][1]["ai"])
        await amy.send(op="start", code=code)
        await amy.expect("room", pred=lambda m: m["room"]["status"] == "playing")
        await amy.send(op="export", code=code)
        state = (await amy.expect("export"))["state"]
        del state["vars"]["round"]
        await amy.send(op="import", code=code, state=state)
        assert "无效" in (await amy.expect("error"))["message"]
        # restarting a running game is allowed for the host
        await amy.send(op="start", code=code)
        await amy.expect("room", pred=lambda m: m["room"]["history_len"] == 1)
    finally:
        await client.close()


async def test_static_files_are_versioned(tmp_path):
    server, client = await make_client(tmp_path)
    try:
        resp = await client.get("/")
        assert resp.headers["Cache-Control"] == "no-cache"
        html = await resp.text()
        prefix = f"/static/v/{server.static_version}/"
        assert f'"{prefix}js/main.js"' in html and f'"{prefix}css/style.css"' in html
        for path in ("js/main.js", "js/games/hearts.js", "data/china_map.json"):
            resp = await client.get(prefix + path)
            assert resp.status == 200
            assert "immutable" in resp.headers["Cache-Control"]
        # a tab from before an update is sent to the current files
        resp = await client.get("/static/v/0ld/js/main.js", allow_redirects=False)
        assert resp.status == 302 and resp.headers["Location"] == prefix + "js/main.js"
        resp = await client.get("/static/js/main.js")
        assert resp.status == 200 and resp.headers["Cache-Control"] == "no-cache"
    finally:
        await client.close()


async def test_room_chat(tmp_path):
    server, client = await make_client(tmp_path, "d")
    try:
        amy, _ = await connect(client, "amy")
        await amy.send(op="create", game="duel")
        code = (await amy.expect("room"))["room"]["code"]
        assert (await amy.expect("chat"))["items"] == []
        bob, _ = await connect(client, "bob")
        await bob.send(op="chat", code=code, text="hi")
        assert (await bob.expect("error"))["message"] == "请先进入房间"
        await bob.send(op="join", code=code)
        await bob.expect("chat", pred=lambda m: m["reset"])
        await bob.send(op="chat", code=code, text="  你好  ")
        for ws in (amy, bob):
            m = await ws.expect("chat", pred=lambda m: not m["reset"])
            assert [(e["user"], e["text"]) for e in m["items"]] == [("bob", "你好")]
        await bob.send(op="chat", code=code, text="   ")
        assert (await bob.expect("error"))["message"] == "消息不能为空"
        # the chat is kept with the room and sent to whoever enters it
        await client.close()
        server, client = await make_client(tmp_path, "d")
        carl, _ = await connect(client, "carl")
        await carl.send(op="join", code=code)
        m = await carl.expect("chat")
        assert m["reset"] and [e["text"] for e in m["items"]] == ["你好"]
    finally:
        await client.close()


async def test_city_ai_waits_after_its_own_discard(tmp_path):
    from cardgame.server.rooms import RoomManager
    from cardgame.server.storage import Storage
    from cardgame.games.city.rules import DISCARD_WAIT
    from tests.test_city import setup as city_state

    R = RoomManager(Storage(tmp_path), ai_speed=0)
    room = R.create("u", "city", 3)
    for i in range(3):
        R.set_seat("u", room.code, i, "ai")
    scheduled = []
    R._run_ai = lambda room, seat, seq, delay: (scheduled.append((seat, delay)), asyncio.sleep(0))[1]
    room.state = st = city_state(hands={0: ["北京"]})
    st.vars["phase"] = "draw"
    st.private[0]["drawn"] = st.zone("hand:0").cards[:1]
    R.act(room, 0, {"type": "discard", "card": st.private[0]["drawn"][0]}, "小明")
    # even at full AI speed the discarder's next move (ending the turn) waits
    seat, delay = scheduled[-1]
    assert seat == 0 and delay >= DISCARD_WAIT
