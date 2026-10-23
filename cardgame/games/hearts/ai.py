"""Hearts computer player in the style of the Windows XP opponents.

Microsoft never published the XP players' logic, so this is a heuristic
player built to behave like them: it passes dangerous cards (Q♠, A♠/K♠
without enough low spades, high hearts) and tries to void short suits,
ducks under the highest card whenever it can, dumps Q♠ as soon as it is
safe, leads low spades to smoke out the queen, occasionally shoots the moon
with a strong hand, and tries to stop an opponent who is shooting.

It only uses information from its own masked view: its hand, the cards it
passed, and the public trick history.
"""
from __future__ import annotations

from ...engine import AI
from .rules import QUEEN_SPADES, SUITS, card_id, points_of, rank_of, suit_of

ACE_SPADES = card_id("S", 14)
KING_SPADES = card_id("S", 13)


class Knowledge:
    """What the AI can deduce from its view."""

    def __init__(self, view: dict):
        v = view["vars"]
        self.me: int = view["seat"]
        self.vars = v
        self.hand: list[int] = list(view["zones"][f"hand:{self.me}"]["cards"])
        self.trick: list[int] = list(view["zones"]["trick"]["cards"])
        self.trick_seats: list[int] = list(v.get("trick_seats") or [])
        self.trick_no: int = v.get("trick_no", 0)
        self.points_taken: list[int] = list(v.get("points_taken") or [0, 0, 0, 0])
        self.played: set[int] = set(self.trick)
        self.voids: list[set[str]] = [set() for _ in range(4)]
        for t in v.get("tricks") or []:
            self._observe(t["cards"], t["seats"])
        self._observe(self.trick, self.trick_seats)
        self.unseen = set(range(52)) - self.played - set(self.hand)
        self.my_played = {c for t in v.get("tricks") or [] for c, s in zip(t["cards"], t["seats"]) if s == self.me}
        self.my_played |= {c for c, s in zip(self.trick, self.trick_seats) if s == self.me}

    def _observe(self, cards: list[int], seats: list[int]) -> None:
        if not cards:
            return
        led = suit_of(cards[0])
        for c, s in zip(cards, seats):
            self.played.add(c)
            if suit_of(c) != led:
                self.voids[s].add(led)

    # ---- helpers
    def queen_out(self) -> bool:
        """Q♠ is still in some other player's hand."""
        return QUEEN_SPADES in self.unseen

    def higher_unseen(self, card: int) -> list[int]:
        s, r = suit_of(card), rank_of(card)
        return [u for u in self.unseen if suit_of(u) == s and rank_of(u) > r]

    def suit_unseen(self, suit: str) -> list[int]:
        return [u for u in self.unseen if suit_of(u) == suit]

    def count(self, suit: str) -> int:
        return sum(1 for c in self.hand if suit_of(c) == suit)

    def players_after_me(self) -> list[int]:
        n = 3 - len(self.trick)
        return [(self.me + k) % 4 for k in range(1, n + 1)]

    def current_winner(self) -> tuple[int | None, int]:
        """(seat, rank) currently winning the trick."""
        if not self.trick:
            return None, 0
        led = suit_of(self.trick[0])
        best = max((c for c in self.trick if suit_of(c) == led), key=rank_of)
        return self.trick_seats[self.trick.index(best)], rank_of(best)

    def moon_threat(self) -> int | None:
        """An opponent who has taken every point so far and enough of them."""
        takers = [i for i in range(4) if self.points_taken[i] > 0]
        if len(takers) != 1 or takers[0] == self.me:
            return None
        t = takers[0]
        pts = self.points_taken[t]
        if pts >= 14 or (pts >= 8 and self.trick_no >= 6) or (pts >= 5 and self.trick_no >= 9):
            return t
        return None

    def shooting(self) -> bool:
        """Whether this AI is (still) trying to shoot the moon."""
        if any(self.points_taken[i] for i in range(4) if i != self.me):
            return False
        start = self.hand + sorted(self.my_played)
        return moon_hand(start)


def moon_hand(cards: list[int]) -> bool:
    """A hand strong enough to try for all 26 points."""
    hearts = [rank_of(c) for c in cards if suit_of(c) == "H"]
    if len(hearts) < 6 or not {14, 13, 12} <= set(hearts):
        return False
    spades = {rank_of(c) for c in cards if suit_of(c) == "S"}
    if 12 in spades and not ({13, 14} & spades):
        return False  # the queen alone would be lost to A♠/K♠
    losers = sum(1 for c in cards if suit_of(c) != "H" and rank_of(c) <= 9)
    return losers <= 2


class HeartsAI(AI):
    def choose(self, view: dict, prompt: dict) -> dict:
        kind = prompt["type"]
        if kind == "pass":
            hand = view["zones"][f"hand:{view['seat']}"]["cards"]
            return {"type": "pass", "cards": choose_pass(hand, prompt["count"])}
        if kind == "play":
            k = Knowledge(view)
            return {"type": "play", "card": choose_play(k, prompt["legal"])}
        return {"type": "continue"}


# ----------------------------------------------------------------- passing
def choose_pass(hand: list[int], count: int = 3) -> list[int]:
    if moon_pass_hand(hand):
        # keep the winners, pass the lowest losers
        losers = sorted((c for c in hand if suit_of(c) != "H"), key=rank_of)
        return _unique(losers + sorted(hand, key=rank_of))[:count]
    by_suit = {s: sorted(rank_of(c) for c in hand if suit_of(c) == s) for s in SUITS}
    low_spades = sum(1 for r in by_suit["S"] if r < 12)

    def danger(c: int) -> float:
        s, r = suit_of(c), rank_of(c)
        if c == QUEEN_SPADES:
            return 100 if low_spades < 4 else 0
        if s == "S":
            if r > 12:
                return 80 + r if low_spades < 4 else r - 6
            return r - 14  # low spades protect against the queen
        if s == "H":
            return r + 4 if r >= 10 else r - 4
        score = float(r)
        n = len(by_suit[s])
        if n <= 3:
            score += (4 - n) * 3  # help to void a short suit
        if c == card_id("C", 2):
            score -= 20
        return score

    return sorted(hand, key=lambda c: (-danger(c), -rank_of(c)))[:count]


def moon_pass_hand(hand: list[int]) -> bool:
    hearts = {rank_of(c) for c in hand if suit_of(c) == "H"}
    if len(hearts) < 7 or not {14, 13, 12} <= hearts:
        return False
    losers = sum(1 for c in hand if suit_of(c) != "H" and rank_of(c) <= 9)
    return losers <= 5


def _unique(cards: list[int]) -> list[int]:
    seen, out = set(), []
    for c in cards:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


# ----------------------------------------------------------------- playing
def choose_play(k: Knowledge, legal: list[int]) -> int:
    if len(legal) == 1:
        return legal[0]
    if k.shooting():
        return _shoot(k, legal)
    if not k.trick:
        return _lead(k, legal)
    if suit_of(legal[0]) == suit_of(k.trick[0]):  # holding the led suit means legal is that suit only
        return _follow(k, legal)
    return _discard(k, legal)


def _lead(k: Knowledge, legal: list[int]) -> int:
    queen_out = k.queen_out()
    have_queen = QUEEN_SPADES in k.hand

    def risk(c: int) -> float:
        s, r = suit_of(c), rank_of(c)
        others = k.suit_unseen(s)
        higher = k.higher_unseen(c)
        value = float(r)
        if not others:
            value += 100  # nobody can follow: we win and eat whatever is discarded
        elif not higher:
            value += 60   # a sure winner
        if s == "S":
            if queen_out and r < 12:
                value -= 8      # smoke out the queen
            if queen_out and r > 12:
                value += 80     # A♠/K♠ would catch the queen
            if c == QUEEN_SPADES:
                value += 70
            if have_queen and r < 12:
                value += 2
        elif s == "H":
            value += 3
        n = k.count(s)
        if s != "S" and n <= 2:
            value -= (3 - n) * 2   # head for a void
        # opponents known to be void will discard points if we win
        if any(s in k.voids[p] for p in range(4) if p != k.me) and higher:
            value += 4
        return value

    return min(legal, key=lambda c: (risk(c), rank_of(c)))


def _follow(k: Knowledge, legal: list[int]) -> int:
    led = suit_of(k.trick[0])
    winner, high = k.current_winner()
    trick_pts = sum(points_of(c) for c in k.trick)
    last = len(k.trick) == 3
    under = [c for c in legal if rank_of(c) < high]
    over = [c for c in legal if rank_of(c) > high]
    over_no_q = [c for c in over if c != QUEEN_SPADES]

    # dump the queen under a higher spade
    if led == "S" and QUEEN_SPADES in under:
        return QUEEN_SPADES

    threat = k.moon_threat()
    if threat is not None and winner == threat and over:
        # stop a moon: take the trick if it is cheap
        cheap = [c for c in over if c != QUEEN_SPADES] or over
        if trick_pts <= 4 or last:
            return min(cheap, key=rank_of)

    if last:
        if trick_pts == 0 and over_no_q and led != "H":
            return max(over_no_q, key=rank_of)  # free trick: shed a high card
        if under:
            return max(under, key=rank_of)
        return max(over_no_q or over, key=rank_of)

    if under:
        if led == "S" and k.queen_out():
            safe = [c for c in under if rank_of(c) < 12]
            if safe:
                return max(safe, key=rank_of)
        return max(under, key=rank_of)

    # we have to go over
    if led == "S" and k.queen_out():
        return min(over, key=rank_of)
    if trick_pts > 0 or led == "H":
        return min(over_no_q or over, key=rank_of)
    later_void = any(led in k.voids[p] for p in k.players_after_me())
    if not later_void and k.trick_no < 4:
        return max(over_no_q or over, key=rank_of)
    return min(over_no_q or over, key=rank_of)


def _discard(k: Knowledge, legal: list[int]) -> int:
    threat = k.moon_threat()
    winner, _ = k.current_winner()
    if threat is not None and winner == threat:
        safe = [c for c in legal if points_of(c) == 0]
        if safe:
            return max(safe, key=rank_of)

    queen_out = k.queen_out()

    def value(c: int) -> float:
        s, r = suit_of(c), rank_of(c)
        if c == QUEEN_SPADES:
            return 1000
        if s == "S" and r > 12 and queen_out:
            return 500 + r
        v = float(r)
        if s == "H":
            v += 4
        n = k.count(s)
        if n <= 2:
            v += 3  # finish voiding the suit
        return v

    return max(legal, key=lambda c: (value(c), rank_of(c)))


def _shoot(k: Knowledge, legal: list[int]) -> int:
    """Play to take every trick that has (or may get) points."""
    if not k.trick:
        sure = [c for c in legal if not k.higher_unseen(c)]
        if sure:
            # cash hearts last only if they are certain; otherwise lead other winners first
            return max(sure, key=lambda c: (suit_of(c) != "H", rank_of(c)))
        return max(legal, key=rank_of)
    led = suit_of(k.trick[0])
    _, high = k.current_winner()
    if all(suit_of(c) == led for c in legal):
        over = [c for c in legal if rank_of(c) > high]
        if over:
            return max(over, key=rank_of)
        return min(legal, key=rank_of)
    non_points = [c for c in legal if points_of(c) == 0]
    return min(non_points or legal, key=rank_of)
