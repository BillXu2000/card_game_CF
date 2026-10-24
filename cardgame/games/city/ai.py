"""城市交易所 computer player.

Decisions are driven by the *potential* of a hand: every Pattern contributes
its value discounted by how many cards are still missing.  The AI keeps the
cards with the highest potential, cashes Patterns as soon as it can, buys or
buys back a card when that completes a Pattern, claims every 点炮 it can and
uses 周游列国 in its last round.  In 斗地主 mode it bids for the landlord
when the revealed cards add enough potential.  It only looks at its own masked view.
"""
from __future__ import annotations

from collections import Counter
from itertools import combinations

from ...engine import AI
from .data import PATTERN_BY_ID, PATTERNS
from .rules import BUYBACK_COST, TOUR_FINE

# chance-like weight of a Pattern that misses 0, 1, 2, 3 cards
MISSING_WEIGHT = (1.0, 0.3, 0.08, 0.02)


def potential(cities: Counter) -> float:
    total = 0.0
    for p in PATTERNS:
        missing = sum(max(0, n - cities[c]) for c, n in p.need)
        if missing < len(MISSING_WEIGHT):
            total += p.value * MISSING_WEIGHT[missing]
    return total


def best_cash(cities: Counter, options: list[dict]) -> dict | None:
    """The cash option maximising value + potential of the remaining hand."""
    best, best_score = None, None
    for o in options:
        rest = cities - PATTERN_BY_ID[o["pattern"]].counter
        score = o["value"] + potential(rest)
        if best_score is None or score > best_score:
            best, best_score = o, score
    return best


class CityAI(AI):
    def choose(self, view: dict, prompt: dict) -> dict:
        self.view = view
        self.seat = view["seat"]
        self.hand = [c for c in view["zones"][f"hand:{self.seat}"]["cards"] if c is not None]
        if prompt.get("claims"):
            return self._claim(prompt["claims"][0])  # 点炮 offers first, then the normal flow
        return getattr(self, f"_{prompt['type']}")(prompt)

    # ---- helpers
    def city(self, card: int) -> str:
        return self.view["cards"][card]["city"]

    def cities(self, cards) -> Counter:
        return Counter(self.city(c) for c in cards)

    def loss(self, card: int) -> float:
        """Potential lost by giving ``card`` away."""
        h = self.cities(self.hand)
        return potential(h) - potential(h - Counter([self.city(card)]))

    def money(self) -> int:
        return self.view["vars"]["money"][self.seat]

    # ---- prompts
    def _draw(self, prompt: dict) -> dict:
        if prompt["cash"]:
            return {"type": "cash", "pattern": best_cash(self.cities(self.hand), prompt["cash"])["pattern"]}
        card = min(prompt["drawn"], key=lambda c: (self.loss(c), c))
        return {"type": "discard", "card": card}

    def _main(self, prompt: dict) -> dict:
        hand = self.cities(self.hand)
        if prompt["cash"]:
            return {"type": "cash", "pattern": best_cash(hand, prompt["cash"])["pattern"]}
        cash_open = not self.view["vars"]["used"]["cash"]
        # buy back / buy a card if it lets us cash a Pattern this turn
        if cash_open and prompt["buyback"]:
            pick = self._completing(prompt["buyback"], BUYBACK_COST + 8)
            if pick is not None:
                return {"type": "buyback", "card": pick}
        if cash_open and prompt["buy"]:
            offer = prompt["buy"]
            pick = self._completing_set(offer["cards"], offer["max"], offer["price"])
            if pick:
                return {"type": "buy", "cards": pick}
        if prompt["tour"] and self._last_round():
            return {"type": "tour"}
        return {"type": "end"}

    def _completing(self, cards: list[int], cost: int) -> int | None:
        hand = self.cities(self.hand)
        best, gain = None, 0.0
        for c in cards:
            h = hand + Counter([self.city(c)])
            values = [p.value for p in PATTERNS if all(h[x] >= n for x, n in p.need)]
            g = max(values, default=0) - cost
            if g > gain:
                best, gain = c, g
        return best

    def _completing_set(self, cards: list[int], max_n: int, price: int) -> list[int] | None:
        hand = self.cities(self.hand)
        best, gain = None, 0.0
        for n in range(1, max_n + 1):
            if self.view["options"].get("need_money") and self.money() < price * n:
                break
            for combo in combinations(cards, n):
                h = hand + self.cities(combo)
                values = [p.value for p in PATTERNS if all(h[x] >= k for x, k in p.need)]
                g = max(values, default=0) - price * n - 6
                if g > gain:
                    best, gain = list(combo), g
        return best

    def _last_round(self) -> bool:
        deck = len(self.view["zones"]["deck"]["cards"])
        return deck < 3 * self.view["num_players"]

    def _claim(self, claim: dict) -> dict:
        """Claim the most valuable set of compatible Patterns (or decline)."""
        opts = claim["options"]
        hand = self.cities(self.hand)
        best, best_value = [], 0
        idx = range(len(opts))
        for n in range(1, min(len(opts), 4) + 1):
            for combo in combinations(idx, n):
                need = Counter()
                for i in combo:
                    o = opts[i]
                    need += PATTERN_BY_ID[o["pattern"]].counter - Counter([self.view["cards"][o["card"]]["city"]])
                if all(hand[c] >= k for c, k in need.items()):
                    value = sum(opts[i]["gain"] for i in combo)
                    if value > best_value:
                        best, best_value = list(combo), value
        return {"type": "dianpao", "offer": claim["offer"], "choices": best}

    def _bid(self, prompt: dict) -> dict:
        """Become the landlord when the revealed cards add enough potential."""
        hand = self.cities(self.hand)
        gain = potential(hand + self.cities(prompt["bonus"])) - potential(hand)
        return {"type": "bid", "take": gain >= 15}

    def _give(self, prompt: dict) -> dict:
        card = min(prompt["cards"], key=lambda c: (self.loss(c), c))
        return {"type": "give", "card": card}

    def _tour(self, prompt: dict) -> dict:
        if not prompt["cards"]:
            return {"type": "tour", "card": None}
        card = min(prompt["cards"], key=lambda c: (self.loss(c), c))
        # on our own tour, stopping costs nothing: only go round again with a useless card
        limit = 1.5 if prompt["by"] == self.seat else TOUR_FINE * 0.8
        if self.loss(card) < limit:
            return {"type": "tour", "card": card}
        return {"type": "tour", "card": None}
