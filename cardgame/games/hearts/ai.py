"""Hearts computer player."""
from __future__ import annotations

from ...engine import AI
from .rules import rank_of


class HeartsAI(AI):
    def choose(self, view: dict, prompt: dict) -> dict:
        kind = prompt["type"]
        if kind == "pass":
            hand = [c for c in view["zones"][f"hand:{view['seat']}"]["cards"]]
            return {"type": "pass", "cards": sorted(hand, key=rank_of)[-3:]}
        if kind == "play":
            return {"type": "play", "card": min(prompt["legal"], key=rank_of)}
        return {"type": "continue"}
