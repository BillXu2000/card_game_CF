"""Computer player for 骗人游戏.

It only uses its own view: its hand, the cards it has seen (its own plays,
cards turned over in challenges and still known to be in somebody's hand),
the public claims and everybody's card count.

* Leading: name the rank it holds most of (jokers fill in) and play those.
* Following: play its real x cards (jokers when it would otherwise empty its
  hand or has nothing else), sometimes slipping in a fake; with no x it
  bluffs a card or two now and then, more readily when the pile is small.
* Challenging: certainly when the claim needs more x than can exist; else
  it estimates the chance the claimer really held that many x (a leader named
  x looking at their hand, so leads are believed more; later claims are drawn
  from the cards it cannot see, less the x earlier claims took) and weighs it
  against the pile size, the claimer about to go out, and how many cards a
  challenge turns over.
"""
from __future__ import annotations

import math
import random

from ...engine import AI
from .rules import RANKS

BLUFF_RATE = 0.35   # assumed chance a player without the cards bluffs anyway


def is_x(card: dict, x: int) -> bool:
    return bool(card.get("joker")) or card.get("rank") == x


def hypergeom_at_least(pool: int, good: int, draws: int, k: int) -> float:
    """P(at least k good items when drawing ``draws`` from ``pool`` holding ``good``)."""
    if k <= 0:
        return 1.0
    draws = min(draws, pool)
    if good < k or draws < k:
        return 0.0
    total = math.comb(pool, draws)
    return sum(math.comb(good, i) * math.comb(pool - good, draws - i)
               for i in range(k, min(good, draws) + 1)) / total


class LiarAI(AI):
    def __init__(self, rng: random.Random | None = None):
        self.rng = rng or random.Random()

    def choose(self, view: dict, prompt: dict) -> dict:
        self.view = view
        self.me = view["seat"]
        self.cards = view["cards"]
        self.hand = list(view["zones"][f"hand:{self.me}"]["cards"])
        if prompt["type"] == "lead":
            return self._lead(prompt)
        x = prompt["x"]
        ch = prompt["challenge"]
        if self._should_challenge(x, ch):
            picks = self.rng.sample(range(ch["count"]), ch["reveal"])
            return {"type": "challenge", "picks": picks}
        if prompt["can_play"]:
            play = self._follow(x, prompt["min"])
            if play:
                return {"type": "play", "cards": play}
        return {"type": "pass"}

    # ------------------------------------------------------------ knowledge
    def _rank(self, cid: int) -> int | None:
        c = self._card(cid)
        return None if c.get("joker") else c["rank"]

    def _card(self, cid: int) -> dict:
        return self.cards.get(cid) or self.cards.get(str(cid))

    def _x_total(self) -> int:
        o = self.view["options"]
        return o["decks"] * (4 + o["jokers"])

    def _x_unseen(self, x: int) -> tuple[int, int]:
        """(cards I cannot see, x-like cards among them): the claimer's hand
        before the claim was drawn from these, as far as I can tell."""
        unseen = seen_x = 0
        for z in self.view["zones"].values():
            for cid in z["cards"]:
                if cid is None:
                    unseen += 1
                elif is_x(self._card(cid), x):
                    seen_x += 1
        return unseen, max(0, self._x_total() - seen_x)

    # -------------------------------------------------------------- decide
    def _lead(self, prompt: dict) -> dict:
        counts = {r: 0 for r in RANKS}
        jokers = []
        for cid in self.hand:
            r = self._rank(cid)
            if r is None:
                jokers.append(cid)
            else:
                counts[r] += 1
        x = max(RANKS, key=lambda r: (counts[r], self.rng.random()))
        play = [cid for cid in self.hand if self._rank(cid) == x]
        if len(play) + len(jokers) == len(self.hand):
            play += jokers                       # go out
        elif not play:
            play = jokers[:1]
        if len(play) < prompt["min"]:
            rest = [cid for cid in self.hand if cid not in play]
            play += self.rng.sample(rest, prompt["min"] - len(play))
        return {"type": "lead", "x": x, "cards": play}

    def _follow(self, x: int, least: int) -> list[int] | None:
        real = [cid for cid in self.hand if self._rank(cid) == x]
        jokers = [cid for cid in self.hand if self._rank(cid) is None]
        others = [cid for cid in self.hand if cid not in real and cid not in jokers]
        pile = sum(len(self.view["zones"][z]["cards"]) for z in ("table", "claim"))
        claimed = sum(c["count"] for c in self.view["vars"]["claims"])
        # the more x already claimed this round, the likelier a challenge
        risky = claimed + 1 > 0.7 * self._x_total()
        if not others:
            return real + jokers if len(real) + len(jokers) >= least else None
        play = list(real)
        if not play and jokers and self.rng.random() < 0.5:
            play = jokers[:1]
        if play:
            # a fake slipped in among true cards
            if self.rng.random() < 0.25 and pile < 8 and not risky:
                play.append(self._junk(others))
        elif not risky and self.rng.random() < (0.45 if pile < 6 else 0.2):
            play = [self._junk(others)]
            if len(others) > 1 and self.rng.random() < 0.3:
                play.append(self._junk([c for c in others if c not in play]))
        if not play:
            return None                          # pass
        if len(play) < least:
            rest = [cid for cid in self.hand if cid not in play]
            if len(rest) < least - len(play):
                return None
            play += self.rng.sample(rest, least - len(play))
        return play

    def _junk(self, cards: list[int]) -> int:
        """A card to bluff with: one of the ranks it holds fewest of."""
        counts: dict[int | None, int] = {}
        for cid in self.hand:
            counts[self._rank(cid)] = counts.get(self._rank(cid), 0) + 1
        return min(cards, key=lambda cid: (counts[self._rank(cid)], self.rng.random()))

    def _should_challenge(self, x: int, ch: dict) -> bool:
        claimer, count = ch["seat"], ch["count"]
        zones = self.view["zones"]
        unseen, x_left = self._x_unseen(x)
        if count > x_left:
            return True                          # cannot all be x
        # earlier claims by others this round used up x too, if they were true
        earlier = sum(c["count"] for c in self.view["vars"]["claims"][:-1] if c["seat"] != self.me)
        x_left = max(0, round(x_left - 0.6 * earlier))
        their_hand = zones[f"hand:{claimer}"]["cards"]
        hand_after = len(their_hand)
        # the claimer's cards before playing that I can't see
        held = sum(1 for cid in their_hand if cid is None) + count
        if len(self.view["vars"]["claims"]) == 1:
            # the leader picked x looking at their hand: likely their best rank
            p_true = 0.8 if count <= max(2, x_left // 2) else 0.55
        else:
            # people mostly claim x when they have it: a claim is a lie only
            # if they lacked the cards *and* chose to bluff
            has = hypergeom_at_least(unseen, x_left, held, count)
            p_true = has / (has + (1 - has) * BLUFF_RATE) if has else 0.0
        # with a partial check a lie may survive: assume about half are fake
        fakes = max(1, count // 2)
        k = ch["reveal"]
        p_catch = 1.0 if k >= count else 1 - math.comb(count - fakes, k) / math.comb(count, k)
        p_win = (1 - p_true) * p_catch
        pile = len(zones["table"]["cards"]) + count
        threshold = 0.45 + min(pile, 20) * 0.005
        if hand_after == 0:
            threshold -= 0.25                    # they would go out
        if len(self.hand) <= 2:
            threshold += 0.1                     # don't throw away a near finish
        return p_win > threshold
