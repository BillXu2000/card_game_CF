"""Rules-module interface shared by all games.

A game is a stateless object; all state lives in a GameState.  The engine
loop is:

    prompts = game.prompts(st)          # {seat: prompt} – who must decide what
    game.act(st, seat, action)          # validate + apply one decision

Several seats may have prompts at once (simultaneous decisions such as
passing cards in Hearts, or reaction windows such as 点炮 in 城市交易所).
A prompt is a JSON dict with at least a ``type``; actions are JSON dicts
whose ``type`` answers the prompt.
"""
from __future__ import annotations

from typing import Any

from .state import GameState, IllegalAction


class AI:
    """An automated player.  It only receives the masked view of its seat."""

    def choose(self, view: dict, prompt: dict) -> dict:
        raise NotImplementedError


class Game:
    id: str = ""
    name: str = ""
    min_players: int = 2
    max_players: int = 2
    ai_names: tuple[str, ...] = ()

    def option_specs(self) -> list[dict]:
        """Options shown when creating a room:
        ``{"key", "label", "type": "bool"|"int"|"choice", "default", "choices"?: [[value, label], ...]}``"""
        return []

    def default_options(self) -> dict:
        return {o["key"]: o["default"] for o in self.option_specs()}

    def clean_options(self, options: dict | None) -> dict:
        """Defaults overridden by valid values from ``options``; unknown keys dropped."""
        out = self.default_options()
        for spec in self.option_specs():
            v = (options or {}).get(spec["key"])
            if spec["type"] == "bool" and isinstance(v, bool):
                out[spec["key"]] = v
            elif spec["type"] == "int" and isinstance(v, int) and not isinstance(v, bool):
                out[spec["key"]] = max(spec.get("min", v), min(spec.get("max", v), v))
            elif spec["type"] == "choice" and v in [c[0] for c in spec["choices"]]:
                out[spec["key"]] = v
        return out

    def new_state(self, num_players: int, options: dict | None = None, seed: int | None = None) -> GameState:
        if not self.min_players <= num_players <= self.max_players:
            raise ValueError(f"{self.name} needs {self.min_players}-{self.max_players} players")
        st = GameState(self.id, num_players, self.clean_options(options), seed)
        self.setup(st)
        return st

    # ---- to implement --------------------------------------------------
    def setup(self, st: GameState) -> None:
        raise NotImplementedError

    def prompts(self, st: GameState) -> dict[int, dict]:
        raise NotImplementedError

    def apply(self, st: GameState, seat: int, action: dict) -> None:
        raise NotImplementedError

    def is_over(self, st: GameState) -> bool:
        raise NotImplementedError

    def make_ai(self) -> AI:
        raise NotImplementedError

    # ---- optional hooks -------------------------------------------------
    def view(self, st: GameState, seat: int | None) -> dict:
        return st.view(seat)

    def static_info(self) -> dict:
        """Constant game data the client needs (e.g. reference tables)."""
        return {}

    def ai_delay(self, st: GameState, prompt: dict) -> float:
        """Seconds an AI waits before answering ``prompt`` (pacing for humans)."""
        return 0.8

    def describe(self, st: GameState, seat: int, action: dict) -> str:
        """Short label for the history list."""
        return action.get("type", "?")

    # ---- driver ---------------------------------------------------------
    def act(self, st: GameState, seat: int, action: Any) -> None:
        if not isinstance(action, dict) or not isinstance(action.get("type"), str):
            raise IllegalAction("动作格式错误")
        prompt = self.prompts(st).get(seat)
        if prompt is None:
            raise IllegalAction("现在不是你的回合")
        self.apply(st, seat, action)
        st.seq += 1
