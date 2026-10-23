"""Registry of available games."""
from __future__ import annotations

from ..engine import Game

GAMES: dict[str, Game] = {}


def register(game: Game) -> Game:
    GAMES[game.id] = game
    return game


def get_game(game_id: str) -> Game:
    return GAMES[game_id]


def _load_builtin() -> None:
    from .hearts import Hearts
    register(Hearts())


_load_builtin()
