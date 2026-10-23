"""Hearts with the rules of Microsoft Hearts in Windows XP.

* 4 players, 13 cards each.  Pass 3 cards: left, right, across, no pass.
* The holder of 2♣ leads it.  Players must follow suit.
* No point card (heart, Q♠) on the first trick, unless the hand is all
  hearts (or 12 hearts + Q♠): then a heart may be played.
* Hearts cannot be led until a heart has been played, unless the leader
  has nothing but hearts.  Q♠ does not break hearts.
* Hearts 1 point each, Q♠ 13.  Taking all 26 ("shooting the moon") gives
  the other three players 26 each instead.
* The game ends when somebody has 100 or more; lowest score wins.

Seats are numbered clockwise; play passes to seat + 1, which sits on a
player's left.
"""
from __future__ import annotations

from ...engine import AI, HIDDEN, OWNER, PUBLIC, Game, GameState, IllegalAction

SUITS = "CDSH"
SUIT_NAME = {"C": "♣", "D": "♦", "S": "♠", "H": "♥"}
RANK_NAME = {11: "J", 12: "Q", 13: "K", 14: "A"}
PASS_DIRS = ("left", "right", "across", "hold")
PASS_OFFSET = {"left": 1, "right": 3, "across": 2}
PASS_NAME = {"left": "左", "right": "右", "across": "对家"}


def card_id(suit: str, rank: int) -> int:
    return SUITS.index(suit) * 13 + rank - 2


TWO_CLUBS = card_id("C", 2)
QUEEN_SPADES = card_id("S", 12)


def suit_of(card: int) -> str:
    return SUITS[card // 13]


def rank_of(card: int) -> int:
    return card % 13 + 2


def points_of(card: int) -> int:
    if card == QUEEN_SPADES:
        return 13
    return 1 if suit_of(card) == "H" else 0


def card_name(card: int) -> str:
    r = rank_of(card)
    return SUIT_NAME[suit_of(card)] + RANK_NAME.get(r, str(r))


def pass_direction(hand_no: int) -> str:
    return PASS_DIRS[hand_no % 4]


def legal_plays(hand: list[int], trick: list[int], trick_no: int, hearts_broken: bool) -> list[int]:
    """Cards a player may play; ``trick`` holds the cards already played."""
    if not trick:
        if trick_no == 0:
            return [TWO_CLUBS] if TWO_CLUBS in hand else list(hand)
        if not hearts_broken:
            non_hearts = [c for c in hand if suit_of(c) != "H"]
            if non_hearts:
                return non_hearts
        return list(hand)
    led = suit_of(trick[0])
    follow = [c for c in hand if suit_of(c) == led]
    if follow:
        return follow
    if trick_no == 0:
        safe = [c for c in hand if points_of(c) == 0]
        if safe:
            return safe
        hearts = [c for c in hand if suit_of(c) == "H"]
        if hearts:
            return hearts
    return list(hand)


def trick_winner(trick: list[int], seats: list[int]) -> int:
    led = suit_of(trick[0])
    best = max((c for c in trick if suit_of(c) == led), key=rank_of)
    return seats[trick.index(best)]


class Hearts(Game):
    id = "hearts"
    name = "红心大战"
    min_players = max_players = 4
    ai_names = ("Pauline", "Michele", "Ben")

    def default_options(self) -> dict:
        return {"end_score": 100}

    # ------------------------------------------------------------------ setup
    def setup(self, st: GameState) -> None:
        st.add_zone("deck", visibility=HIDDEN)
        for i in range(4):
            st.add_zone(f"hand:{i}", owner=i, visibility=OWNER)
            st.add_zone(f"pass:{i}", owner=i, visibility=OWNER)
            st.add_zone(f"won:{i}", owner=i, visibility=PUBLIC)
        st.add_zone("trick", visibility=PUBLIC)
        for s in SUITS:
            for r in range(2, 15):
                st.add_card({"suit": s, "rank": r}, "deck")
        st.vars.update(
            hand_no=0,
            scores=[0, 0, 0, 0],
            score_history=[],
            last_hand=None,
            winners=None,
        )
        self._deal(st)

    def _deal(self, st: GameState) -> None:
        for i in range(4):
            st.move_all(f"won:{i}", "deck")
            st.move_all(f"hand:{i}", "deck")
            st.move_all(f"pass:{i}", "deck")
        st.move_all("trick", "deck")
        st.shuffle("deck")
        for _ in range(13):
            for i in range(4):
                st.draw("deck", f"hand:{i}")
        for p in st.private:
            p.clear()
        d = pass_direction(st.vars["hand_no"])
        st.vars.update(
            pass_dir=d,
            trick_no=0,
            turn=None,
            leader=None,
            trick_seats=[],
            hearts_broken=False,
            tricks=[],
            points_taken=[0, 0, 0, 0],
            last_trick=None,
            acks=None,
        )
        st.log(f"第 {st.vars['hand_no'] + 1} 局开始" + (f"，向{PASS_NAME[d]}传三张牌" if d != "hold" else "，本局不传牌"))
        if d == "hold":
            self._start_play(st)
        else:
            st.vars["phase"] = "pass"

    def _start_play(self, st: GameState) -> None:
        leader = int(st.where(TWO_CLUBS).split(":")[1])
        st.vars.update(phase="play", turn=leader, leader=leader)

    # ---------------------------------------------------------------- prompts
    def prompts(self, st: GameState) -> dict[int, dict]:
        v = st.vars
        phase = v["phase"]
        if phase == "pass":
            to = PASS_OFFSET[v["pass_dir"]]
            return {i: {"type": "pass", "count": 3, "direction": v["pass_dir"], "to": (i + to) % 4}
                    for i in range(4) if not st.zone(f"pass:{i}").cards}
        if phase == "play":
            seat = v["turn"]
            return {seat: {"type": "play", "legal": self.legal(st, seat)}}
        if phase == "score":
            return {i: {"type": "continue"} for i in range(4) if not v["acks"][i]}
        return {}

    def legal(self, st: GameState, seat: int) -> list[int]:
        v = st.vars
        return legal_plays(st.zone(f"hand:{seat}").cards, st.zone("trick").cards, v["trick_no"], v["hearts_broken"])

    # ------------------------------------------------------------------ apply
    def apply(self, st: GameState, seat: int, action: dict) -> None:
        kind = action["type"]
        phase = st.vars["phase"]
        if phase == "pass" and kind == "pass":
            self._apply_pass(st, seat, action.get("cards"))
        elif phase == "play" and kind == "play":
            self._apply_play(st, seat, action.get("card"))
        elif phase == "score" and kind == "continue":
            self._apply_continue(st, seat)
        else:
            raise IllegalAction("现在不能这样做")

    def _apply_pass(self, st: GameState, seat: int, cards) -> None:
        hand = st.zone(f"hand:{seat}").cards
        if (not isinstance(cards, list) or len(cards) != 3 or len(set(cards)) != 3
                or any(c not in hand for c in cards)):
            raise IllegalAction("请选择三张手牌")
        for c in cards:
            st.move(c, f"pass:{seat}")
        if any(not st.zone(f"pass:{i}").cards for i in range(4)):
            return
        offset = PASS_OFFSET[st.vars["pass_dir"]]
        moves = [(i, (i + offset) % 4, list(st.zone(f"pass:{i}").cards)) for i in range(4)]
        for src, dst, cs in moves:
            for c in cs:
                st.move(c, f"hand:{dst}")
                st.reveal(c, [src])
            st.private[src]["passed"] = {"to": dst, "cards": cs}
            st.private[dst]["received"] = {"from": src, "cards": cs}
            st.log("你收到了 " + " ".join(card_name(c) for c in cs), to=[dst])
        self._start_play(st)

    def _apply_play(self, st: GameState, seat: int, card) -> None:
        if card not in self.legal(st, seat):
            raise IllegalAction("不能出这张牌")
        v = st.vars
        st.move(card, "trick")
        v["trick_seats"].append(seat)
        if suit_of(card) == "H" and not v["hearts_broken"]:
            v["hearts_broken"] = True
        trick = st.zone("trick").cards
        if len(trick) < 4:
            v["turn"] = (seat + 1) % 4
            return
        winner = trick_winner(trick, v["trick_seats"])
        pts = sum(points_of(c) for c in trick)
        record = {"leader": v["leader"], "cards": list(trick), "seats": list(v["trick_seats"]), "winner": winner}
        v["tricks"].append(record)
        v["last_trick"] = record
        v["points_taken"][winner] += pts
        st.move_all("trick", f"won:{winner}")
        v["trick_seats"] = []
        v["trick_no"] += 1
        v["turn"] = v["leader"] = winner
        if v["trick_no"] == 13:
            self._end_hand(st)

    def _end_hand(self, st: GameState) -> None:
        v = st.vars
        pts = list(v["points_taken"])
        moon = next((i for i in range(4) if pts[i] == 26), None)
        if moon is not None:
            pts = [0 if i == moon else 26 for i in range(4)]
            st.log(f"座位 {moon + 1} 全收（射月）！其他玩家各得 26 分", moon=moon)
        v["scores"] = [a + b for a, b in zip(v["scores"], pts)]
        v["score_history"].append(pts)
        v["last_hand"] = {"points": pts, "moon": moon}
        v["turn"] = v["leader"] = None
        if max(v["scores"]) >= st.options.get("end_score", 100):
            low = min(v["scores"])
            v["winners"] = [i for i in range(4) if v["scores"][i] == low]
            v["phase"] = "over"
            st.log("游戏结束")
        else:
            v["phase"] = "score"
            v["acks"] = [False] * 4

    def _apply_continue(self, st: GameState, seat: int) -> None:
        v = st.vars
        v["acks"][seat] = True
        if all(v["acks"]):
            v["hand_no"] += 1
            self._deal(st)

    # ------------------------------------------------------------------- misc
    def is_over(self, st: GameState) -> bool:
        return st.vars["phase"] == "over"

    def make_ai(self) -> AI:
        from .ai import HeartsAI
        return HeartsAI()

    def ai_delay(self, st: GameState, prompt: dict) -> float:
        if prompt["type"] == "play":
            # leave a finished trick on the table for a moment
            return 1.6 if not st.zone("trick").cards and st.vars["tricks"] else 0.8
        return 0.6

    def describe(self, st: GameState, seat: int, action: dict) -> str:
        kind = action.get("type")
        if kind == "play" and isinstance(action.get("card"), int) and 0 <= action["card"] < 52:
            return f"出 {card_name(action['card'])}"
        return {"pass": "传牌", "continue": "继续"}.get(kind, str(kind))
