"""骗人游戏 (external/liar_game.txt).

* n decks of 52 cards plus some jokers each; jokers are wild.  All cards are
  dealt out as evenly as possible.
* The game is played in rounds.  The winner of the previous round (a random
  player for the first) names a rank x and leads: they must play cards face
  down claiming they are all x.  Then, clockwise, every player who has not
  passed this round either
    - passes (and can only pass for the rest of the round),
    - plays cards face down claiming they are all x, or
    - challenges the latest claim: some of its cards (all, or a third rounded
      up; the challenger picks which) are turned over.  If they are all x or
      jokers, the challenger takes every card played this round and the
      claimer wins the round; otherwise the claimer takes them and the
      challenger wins the round.
* When only one player has not passed, the cards played this round are
  discarded face down and that player wins the round.
* A player is out once their hand is empty and their last claim can no
  longer be challenged (somebody made a newer claim, the round ended without
  a challenge, or a challenge of it failed).  Players are ranked by the order
  they go out; the game ends when at most one player still holds cards.

Decisions on points the rules leave open (agreed with the user): a play has
at least ``min_play`` cards (default 1); the first play of a round is
compulsory; the latest claim may be challenged until a newer claim is made;
if the round winner is out, the next player clockwise with cards names x.
"""
from __future__ import annotations

import math

from ...engine import AI, HIDDEN, OWNER, Game, GameState, IllegalAction

RANKS = list(range(2, 15))          # 2..10, J=11, Q=12, K=13, A=14
SUITS = "SHDC"
RANK_NAME = {11: "J", 12: "Q", 13: "K", 14: "A"}


def rank_name(rank: int) -> str:
    return RANK_NAME.get(rank, str(rank))


def P(seat: int) -> str:
    return f"{{P{seat}}}"


def reveal_count(n: int, mode: str) -> int:
    return n if mode == "all" else math.ceil(n / 3)


class Liar(Game):
    id = "liar"
    name = "骗人游戏"
    min_players = 2
    max_players = 8
    ai_names = ("小明", "小红", "小刚", "小丽", "小华", "小芳", "小军")

    def option_specs(self) -> list[dict]:
        return [
            {"key": "decks", "label": "几副牌", "type": "int", "default": 1, "min": 1, "max": 4},
            {"key": "jokers", "label": "每副牌的王", "type": "int", "default": 2, "min": 0, "max": 4},
            {"key": "reveal", "label": "质疑时翻开", "type": "choice", "default": "all",
             "choices": [["all", "全部"], ["third", "三分之一（上取整）"]]},
            {"key": "min_play", "label": "每次至少出", "type": "int", "default": 1, "min": 1, "max": 3},
        ]

    # ------------------------------------------------------------------ setup
    def setup(self, st: GameState) -> None:
        n = st.num_players
        st.add_zone("deck", visibility=HIDDEN)
        for i in range(n):
            st.add_zone(f"hand:{i}", owner=i, visibility=OWNER)
        st.add_zone("table", visibility=HIDDEN)     # earlier claims of this round
        st.add_zone("claim", visibility=HIDDEN)     # the latest claim
        st.add_zone("discard", visibility=HIDDEN)
        for _ in range(st.options["decks"]):
            for s in SUITS:
                for r in RANKS:
                    st.add_card({"suit": s, "rank": r}, "deck")
            for k in range(st.options["jokers"]):
                st.add_card({"joker": True, "color": "red" if k % 2 else "black"}, "deck")
        st.shuffle("deck")
        # deal as evenly as possible, starting from a random seat
        start = st.rng.randrange(n)
        k = 0
        while st.zone("deck").cards:
            st.draw("deck", f"hand:{(start + k) % n}")
            k += 1
        st.vars.update(
            phase="lead",
            round_no=1,
            x=None,
            turn=st.rng.randrange(n),
            passed=[False] * n,
            out=[],             # seats in the order they went out
            claims=[],          # this round: {"seat", "count"}
            last_result=None,   # how the previous round ended, for the table
            winners=None,
        )
        st.log(f"游戏开始，{P(st.vars['turn'])} 先定数字")

    # ---------------------------------------------------------------- prompts
    def prompts(self, st: GameState) -> dict[int, dict]:
        v = st.vars
        if v["phase"] == "lead":
            return {v["turn"]: {"type": "lead", "min": self._min_play(st, v["turn"])}}
        if v["phase"] == "play":
            seat = v["turn"]
            hand = len(st.zone(f"hand:{seat}").cards)
            last = v["claims"][-1]
            return {seat: {
                "type": "play",
                "x": v["x"],
                "min": st.options["min_play"],
                "can_play": hand >= st.options["min_play"],
                "challenge": {"seat": last["seat"], "count": last["count"],
                              "reveal": reveal_count(last["count"], st.options["reveal"])},
            }}
        return {}

    def _min_play(self, st: GameState, seat: int) -> int:
        # whoever leads must be able to play, even with fewer cards than min_play
        return min(st.options["min_play"], len(st.zone(f"hand:{seat}").cards))

    # ------------------------------------------------------------------ apply
    def apply(self, st: GameState, seat: int, action: dict) -> None:
        kind = action["type"]
        phase = st.vars["phase"]
        if phase == "lead" and kind == "lead":
            x = action.get("x")
            if x not in RANKS:
                raise IllegalAction("请选择一个数字")
            st.vars["x"] = x
            self._claim(st, seat, action.get("cards"), self._min_play(st, seat))
            st.vars["phase"] = "play"
        elif phase == "play" and kind == "play":
            self._claim(st, seat, action.get("cards"), st.options["min_play"])
        elif phase == "play" and kind == "pass":
            self._pass(st, seat)
        elif phase == "play" and kind == "challenge":
            self._challenge(st, seat, action.get("picks"))
        else:
            raise IllegalAction("现在不能这样做")

    def _claim(self, st: GameState, seat: int, cards, least: int) -> None:
        hand = st.zone(f"hand:{seat}").cards
        if (not isinstance(cards, list) or len(cards) < least or len(set(cards)) != len(cards)
                or any(c not in hand for c in cards)):
            raise IllegalAction(f"请选择至少 {least} 张手牌")
        v = st.vars
        # the previous claim can no longer be challenged
        if v["claims"]:
            st.move_all("claim", "table")
            self._maybe_out(st, v["claims"][-1]["seat"])
        order = list(cards)
        st.rng.shuffle(order)       # positions must not tell anything
        for c in order:
            st.move(c, "claim")
            st.forget(c)            # once face down among others, nobody can tell it apart
            st.reveal(c, [seat])
        v["claims"].append({"seat": seat, "count": len(cards)})
        st.log(f"{P(seat)} 打出 {len(cards)} 张，声称都是 {rank_name(v['x'])}")
        # the previous claimer may just have gone out, leaving nobody to answer
        if not self._last_one_standing(st):
            self._advance(st, seat)

    def _pass(self, st: GameState, seat: int) -> None:
        st.vars["passed"][seat] = True
        st.log(f"{P(seat)} pass")
        if not self._last_one_standing(st):
            self._advance(st, seat)

    def _last_one_standing(self, st: GameState) -> bool:
        """End the round if only one player is still in it (has not passed
        and is not out); the cards played are discarded."""
        v = st.vars
        left = [i for i in self._in_game(st) if not v["passed"][i]]
        if len(left) != 1:
            return False
        winner = left[0]
        n = len(st.zone("table").cards) + len(st.zone("claim").cards)
        st.move_all("claim", "table")
        for c in list(st.zone("table").cards):
            st.move(c, "discard")
            st.forget(c)
        v["last_result"] = {"type": "all_pass", "winner": winner, "discarded": n}
        st.log(f"只剩 {P(winner)} 没有 pass，桌上 {n} 张牌进入弃牌堆，{P(winner)} 赢得本轮")
        self._end_round(st, winner)
        return True

    def _challenge(self, st: GameState, seat: int, picks) -> None:
        v = st.vars
        claim = st.zone("claim").cards
        need = reveal_count(len(claim), st.options["reveal"])
        if need == len(claim):
            picks = list(range(len(claim)))
        if (not isinstance(picks, list) or len(picks) != need or len(set(picks)) != need
                or any(not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < len(claim) for i in picks)):
            raise IllegalAction(f"请选择要翻开的 {need} 张牌")
        claimer = v["claims"][-1]["seat"]
        shown = [claim[i] for i in sorted(picks)]
        everyone = range(st.num_players)
        for c in shown:
            st.reveal(c, everyone)
        truthful = all(st.cards[c].get("joker") or st.cards[c]["rank"] == v["x"] for c in shown)
        taker, winner = (seat, claimer) if truthful else (claimer, seat)
        st.move_all("claim", "table")
        n = len(st.zone("table").cards)
        for c in list(st.zone("table").cards):
            st.move(c, f"hand:{taker}")
        names = " ".join(self.card_name(st, c) for c in shown)
        v["last_result"] = {"type": "challenge", "challenger": seat, "claimer": claimer, "x": v["x"],
                            "shown": shown, "truthful": truthful, "taker": taker, "taken": n}
        st.log(f"{P(seat)} 质疑 {P(claimer)}，翻开 {names}："
               + (f"都是 {rank_name(v['x'])}！{P(seat)} 收下 {n} 张牌" if truthful
                  else f"有假！{P(claimer)} 收回 {n} 张牌"), shown=shown)
        if truthful:
            self._maybe_out(st, claimer)
        self._end_round(st, winner)

    # ---------------------------------------------------------------- helpers
    def _in_game(self, st: GameState) -> list[int]:
        return [i for i in range(st.num_players) if i not in st.vars["out"]]

    def _maybe_out(self, st: GameState, seat: int) -> None:
        if not st.zone(f"hand:{seat}").cards and seat not in st.vars["out"]:
            st.vars["out"].append(seat)
            st.log(f"{P(seat)} 出完了，第 {len(st.vars['out'])} 名")

    def _advance(self, st: GameState, seat: int) -> None:
        v = st.vars
        n = st.num_players
        for k in range(1, n + 1):
            i = (seat + k) % n
            if i not in v["out"] and not v["passed"][i]:
                v["turn"] = i
                return

    def _end_round(self, st: GameState, winner: int) -> None:
        v = st.vars
        self._maybe_out(st, winner)
        holding = self._in_game(st)
        if len(holding) <= 1:
            v["out"].extend(holding)
            v["winners"] = v["out"][:1]
            v["phase"] = "over"
            v["turn"] = None
            st.log("游戏结束：" + "，".join(f"第 {k + 1} 名 {P(s)}" for k, s in enumerate(v["out"])))
            return
        n = st.num_players
        leader = next((winner + k) % n for k in range(n) if (winner + k) % n in holding)
        v.update(phase="lead", round_no=v["round_no"] + 1, x=None, turn=leader,
                 passed=[False] * n, claims=[])
        st.log(f"第 {v['round_no']} 轮：{P(leader)} 定数字")

    def card_name(self, st: GameState, c: int) -> str:
        a = st.cards[c]
        if a.get("joker"):
            return "王"
        return {"S": "♠", "H": "♥", "D": "♦", "C": "♣"}[a["suit"]] + rank_name(a["rank"])

    # ------------------------------------------------------------------- misc
    def is_over(self, st: GameState) -> bool:
        return st.vars["phase"] == "over"

    def make_ai(self) -> AI:
        from .ai import LiarAI
        return LiarAI()

    def static_info(self) -> dict:
        return {"ranks": [[r, rank_name(r)] for r in RANKS]}

    def ai_delay(self, st: GameState, prompt: dict) -> float:
        # leave the result of a challenge on the table for a moment
        if prompt["type"] == "lead" and st.vars.get("last_result"):
            return 2.0
        return 1.0

    def describe(self, st: GameState, seat: int, action: dict) -> str:
        kind = action.get("type")
        if kind in ("lead", "play") and isinstance(action.get("cards"), list):
            x = action.get("x", st.vars.get("x"))
            return f"出 {len(action['cards'])} 张" + (f"，说是 {rank_name(x)}" if x in RANKS else "")
        return {"pass": "pass", "challenge": "质疑"}.get(kind, str(kind))
