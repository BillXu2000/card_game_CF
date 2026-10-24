"""Rooms: seats, the running game, history (for rollback) and AI turns.

This module knows nothing about websockets; the app layer subscribes to
``on_change`` and turns room changes into per-user messages.
"""
from __future__ import annotations

import asyncio
import logging
import random
import string
import time
from dataclasses import dataclass
from typing import Callable

from ..engine import GameState, IllegalAction
from ..games import GAMES, get_game
from .storage import Storage

log = logging.getLogger(__name__)


class RoomError(Exception):
    pass


@dataclass
class Seat:
    user: str | None = None   # human player's username
    ai: str | None = None     # AI display name

    @property
    def empty(self) -> bool:
        return self.user is None and self.ai is None

    @property
    def name(self) -> str | None:
        return self.user or self.ai

    def to_dict(self) -> dict:
        return {"user": self.user, "ai": self.ai}


class Room:
    def __init__(self, code: str, game_id: str, host: str, num_players: int, options: dict):
        self.code = code
        self.game_id = game_id
        self.game = get_game(game_id)
        self.host = host
        self.options = dict(options)
        self.seats = [Seat() for _ in range(num_players)]
        self.state: GameState | None = None
        self.history: list[dict] = []
        self.created = time.time()
        self.ai_task: asyncio.Task | None = None

    @property
    def status(self) -> str:
        if self.state is None:
            return "waiting"
        return "finished" if self.game.is_over(self.state) else "playing"

    def seat_of(self, user: str) -> int | None:
        for i, s in enumerate(self.seats):
            if s.user == user:
                return i
        return None

    def humans(self) -> list[str]:
        return [s.user for s in self.seats if s.user]

    def summary(self) -> dict:
        return {
            "code": self.code,
            "game": self.game_id,
            "game_name": self.game.name,
            "host": self.host,
            "status": self.status,
            "seats": [s.name for s in self.seats],
            "options": self.options,
        }

    def meta(self) -> dict:
        return {
            "code": self.code,
            "game": self.game_id,
            "host": self.host,
            "options": self.options,
            "seats": [s.to_dict() for s in self.seats],
            "created": self.created,
            "state": self.state.to_dict() if self.state else None,
        }


class RoomManager:
    def __init__(self, storage: Storage, ai_speed: float = 1.0):
        self.storage = storage
        self.rooms: dict[str, Room] = {}
        self.ai_speed = ai_speed
        self.on_change: Callable[[Room], None] = lambda room: None

    # ----------------------------------------------------------- persistence
    def _meta_path(self, code: str) -> str:
        return f"rooms/{code}.json"

    def _hist_path(self, code: str) -> str:
        return f"rooms/{code}.history.jsonl"

    def save(self, room: Room) -> None:
        self.storage.save_json(self._meta_path(room.code), room.meta())

    def load_all(self) -> None:
        for p in sorted(self.storage.path("rooms").glob("*.json")):
            code = p.stem
            try:
                m = self.storage.load_json(self._meta_path(code))
                room = Room(code, m["game"], m["host"], len(m["seats"]), m.get("options", {}))
                room.seats = [Seat(s.get("user"), s.get("ai")) for s in m["seats"]]
                room.created = m.get("created", time.time())
                if m.get("state"):
                    room.state = GameState.from_dict(m["state"])
                    room.history = self.storage.load_jsonl(self._hist_path(code))
                    if not room.history or room.history[-1]["state"]["seq"] != room.state.seq:
                        room.history.append(self._snapshot(room, "恢复"))
                self.rooms[code] = room
            except Exception:
                log.exception("failed to load room %s", code)

    def resume_ai(self) -> None:
        for room in self.rooms.values():
            self._schedule_ai(room)

    # ---------------------------------------------------------------- helpers
    def get(self, code: object) -> Room:
        room = self.rooms.get(code.strip().upper()) if isinstance(code, str) else None
        if room is None:
            raise RoomError("房间不存在")
        return room

    def _new_code(self) -> str:
        while True:
            code = "".join(random.choices(string.ascii_uppercase, k=4))
            if code not in self.rooms:
                return code

    def _require_host(self, room: Room, user: str) -> None:
        if room.host != user:
            raise RoomError("只有房主可以这样做")

    def _changed(self, room: Room) -> None:
        self.save(room)
        self.on_change(room)

    def _snapshot(self, room: Room, label: str) -> dict:
        return {"label": label, "time": time.time(), "state": room.state.to_dict()}

    def _record(self, room: Room, label: str) -> None:
        snap = self._snapshot(room, label)
        room.history.append(snap)
        self.storage.append_jsonl(self._hist_path(room.code), snap)

    def _ai_name(self, room: Room) -> str:
        used = {s.name for s in room.seats}
        for n in room.game.ai_names:
            if n not in used:
                return n
        i = 1
        while f"AI{i}" in used:
            i += 1
        return f"AI{i}"

    # -------------------------------------------------------------- lobby ops
    def list_rooms(self) -> list[dict]:
        return [r.summary() for r in sorted(self.rooms.values(), key=lambda r: -r.created)]

    def create(self, user: str, game_id: object, num_players: object = None, options: object = None) -> Room:
        if game_id not in GAMES:
            raise RoomError("未知的游戏")
        game = get_game(game_id)
        n = num_players if isinstance(num_players, int) else game.min_players
        if not game.min_players <= n <= game.max_players:
            raise RoomError(f"{game.name} 需要 {game.min_players}-{game.max_players} 人")
        room = Room(self._new_code(), game_id, user, n, game.clean_options(options if isinstance(options, dict) else {}))
        room.seats[0].user = user
        self.rooms[room.code] = room
        self._changed(room)
        return room

    def join(self, user: str, code: object) -> Room:
        """Enter a room; take a free seat if the game has not started."""
        room = self.get(code)
        if room.seat_of(user) is None and room.state is None:
            for s in room.seats:
                if s.empty:
                    s.user = user
                    break
        self._changed(room)
        return room

    def sit(self, user: str, code: object, seat: object) -> Room:
        """Take an empty seat (before start) or replace an AI (any time)."""
        room = self.get(code)
        if not isinstance(seat, int) or not 0 <= seat < len(room.seats):
            raise RoomError("座位无效")
        s = room.seats[seat]
        if s.user is not None:
            raise RoomError("座位已有人")
        if s.empty and room.state is not None:
            raise RoomError("游戏已开始")
        old = room.seat_of(user)
        if old is not None:
            if room.state is not None:
                raise RoomError("游戏进行中不能换座位")
            room.seats[old].user = None
        s.user, s.ai = user, None
        self._changed(room)
        return room

    def leave(self, user: str, code: object) -> None:
        """Leave a room.  Before the game starts the seat is freed; during a
        game the seat is kept so the player can come back."""
        room = self.get(code)
        i = room.seat_of(user)
        if room.state is None and i is not None:
            room.seats[i].user = None
        if room.host == user:
            others = [u for u in room.humans() if u != user]
            if others:
                room.host = others[0]
            elif room.state is None:
                self._delete(room)
                return
        self._changed(room)

    def _delete(self, room: Room) -> None:
        if room.ai_task:
            room.ai_task.cancel()
        self.rooms.pop(room.code, None)
        self.storage.delete(self._meta_path(room.code))
        self.storage.delete(self._hist_path(room.code))
        self.on_change(room)

    # --------------------------------------------------------------- host ops
    def close(self, user: str, code: object) -> Room:
        room = self.get(code)
        self._require_host(room, user)
        self._delete(room)
        return room

    def set_seat(self, user: str, code: object, seat: object, mode: object) -> Room:
        room = self.get(code)
        self._require_host(room, user)
        if not isinstance(seat, int) or not 0 <= seat < len(room.seats):
            raise RoomError("座位无效")
        s = room.seats[seat]
        if mode == "ai":
            if s.ai is None:
                s.user, s.ai = None, self._ai_name(room)
        elif mode == "empty":
            if room.state is not None:
                raise RoomError("游戏进行中只能把座位交给 AI")
            s.user = s.ai = None
        else:
            raise RoomError("未知操作")
        self._changed(room)
        self._schedule_ai(room)
        return room

    def set_players(self, user: str, code: object, n: object) -> Room:
        room = self.get(code)
        self._require_host(room, user)
        if room.state is not None:
            raise RoomError("游戏已开始")
        game = room.game
        if not isinstance(n, int) or not game.min_players <= n <= game.max_players:
            raise RoomError(f"{game.name} 需要 {game.min_players}-{game.max_players} 人")
        if any(not s.empty for s in room.seats[n:]):
            raise RoomError("请先清空多余的座位")
        room.seats = (room.seats + [Seat() for _ in range(n)])[:n]
        self._changed(room)
        return room

    def set_options(self, user: str, code: object, options: object) -> Room:
        room = self.get(code)
        self._require_host(room, user)
        if room.status == "playing":
            raise RoomError("游戏进行中不能修改选项")
        room.options = room.game.clean_options({**room.options, **(options if isinstance(options, dict) else {})})
        self._changed(room)
        return room

    def start(self, user: str, code: object) -> Room:
        room = self.get(code)
        self._require_host(room, user)
        if any(s.empty for s in room.seats):
            raise RoomError("还有空座位（可以设为 AI）")
        try:
            st = room.game.new_state(len(room.seats), room.options, seed=random.getrandbits(64))
        except ValueError as e:
            raise RoomError(str(e)) from None
        self._cancel_ai(room)
        room.state = st
        room.history = []
        self.storage.delete(self._hist_path(room.code))
        self._record(room, "开始")
        self._changed(room)
        self._schedule_ai(room)
        return room

    def rollback(self, user: str, code: object, index: object) -> Room:
        room = self.get(code)
        self._require_host(room, user)
        if not isinstance(index, int) or not 0 <= index < len(room.history):
            raise RoomError("历史记录无效")
        room.state = GameState.from_dict(room.history[index]["state"])
        room.history = room.history[: index + 1]
        self.storage.write_jsonl(self._hist_path(room.code), room.history)
        self._cancel_ai(room)
        self._changed(room)
        self._schedule_ai(room)
        return room

    def export_state(self, user: str, code: object) -> dict:
        room = self.get(code)
        self._require_host(room, user)
        if room.state is None:
            raise RoomError("游戏尚未开始")
        return room.state.to_dict()

    def import_state(self, user: str, code: object, data: object) -> Room:
        room = self.get(code)
        self._require_host(room, user)
        if any(s.empty for s in room.seats):
            raise RoomError("还有空座位（可以设为 AI）")
        try:
            st = GameState.from_dict(data)  # type: ignore[arg-type]
        except Exception as e:
            raise RoomError(f"JSON 无效：{e}") from None
        if st.game != room.game_id:
            raise RoomError("JSON 属于另一种游戏")
        if st.num_players != len(room.seats):
            raise RoomError(f"JSON 需要 {st.num_players} 个座位")
        try:
            room.game.prompts(st)
            for seat in [None, *range(st.num_players)]:
                room.game.view(st, seat)
        except Exception as e:
            raise RoomError(f"JSON 中的游戏数据无效：{e!r}") from None
        self._cancel_ai(room)
        room.state = st
        self._record(room, "导入")
        self._changed(room)
        self._schedule_ai(room)
        return room

    def history_labels(self, user: str, code: object) -> list[dict]:
        room = self.get(code)
        self._require_host(room, user)
        return [{"index": i, "label": h["label"], "time": h["time"]} for i, h in enumerate(room.history)]

    # ------------------------------------------------------------ game moves
    def act(self, room: Room, seat: int, action: object, by: str) -> None:
        if room.state is None:
            raise RoomError("游戏尚未开始")
        new = room.state.copy()
        try:
            label = room.game.describe(new, seat, action) if isinstance(action, dict) else "?"
            room.game.act(new, seat, action)
        except IllegalAction as e:
            raise RoomError(str(e)) from None
        room.state = new
        self._record(room, f"{by}：{label}")
        self._changed(room)
        self._schedule_ai(room)

    def human_action(self, user: str, code: object, action: object) -> Room:
        room = self.get(code)
        seat = room.seat_of(user)
        if seat is None:
            raise RoomError("你没有座位")
        self.act(room, seat, action, user)
        return room

    # -------------------------------------------------------------------- AI
    def _cancel_ai(self, room: Room) -> None:
        if room.ai_task and not room.ai_task.done():
            room.ai_task.cancel()
        room.ai_task = None

    def _schedule_ai(self, room: Room) -> None:
        if room.state is None or room.game.is_over(room.state):
            return
        if room.ai_task and not room.ai_task.done():
            return  # the running task re-checks the state when it wakes up
        prompts = room.game.prompts(room.state)
        seats = [s for s in sorted(prompts) if room.seats[s].ai]
        if not seats:
            return
        seat = seats[0]
        delay = room.game.ai_delay(room.state, prompts[seat]) * self.ai_speed
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # no loop yet (e.g. while loading); resume_ai() will start it
        room.ai_task = loop.create_task(self._run_ai(room, seat, room.state.seq, delay))

    async def _run_ai(self, room: Room, seat: int, seq: int, delay: float) -> None:
        await asyncio.sleep(delay)
        room.ai_task = None
        if self.rooms.get(room.code) is not room or room.state is None:
            return
        st = room.state
        prompt = room.game.prompts(st).get(seat)
        if st.seq == seq and prompt is not None and room.seats[seat].ai:
            try:
                action = room.game.make_ai().choose(room.game.view(st, seat), prompt)
                self.act(room, seat, action, room.seats[seat].ai)
                return  # act() schedules the next AI move
            except Exception:
                log.exception("AI failed in room %s seat %d", room.code, seat)
                return
        self._schedule_ai(room)
