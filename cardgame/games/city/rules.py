"""城市交易所 (rule book v5.5-beta), standard 3- and 4-player game.

Turn: draw 3 and discard one of them (or cash a Pattern containing all three
instead), then in any order: buy back (≤1), tour (周游列国), forced buy
(强买, ≤1), cash a Pattern (≤1), end the turn.  Every discard opens a
reaction window in which other players may claim 点炮.

Points the rule book leaves open are room options (see ``option_specs``).
"""
from __future__ import annotations

from collections import Counter

from ...engine import AI, HIDDEN, OWNER, PUBLIC, Game, GameState, IllegalAction
from .data import CITIES, PATTERN_BY_ID, PATTERNS, PROVINCE_OF, PROVINCES, Pattern

HAND_SIZE = {3: 8, 4: 9}
DRAW = 3
BUYBACK_COST = 10
BUY_PRICE = 4
TOUR_FINE = 6


def contains(have: Counter, need: Counter) -> bool:
    return all(have[c] >= n for c, n in need.items())


def cashable(hand_cities: Counter) -> list[Pattern]:
    return [p for p in PATTERNS if contains(hand_cities, p.counter)]


def claimable(hand_cities: Counter, city: str) -> list[Pattern]:
    """Patterns completed by adding one ``city`` card to the hand (点炮)."""
    out = []
    for p in PATTERNS:
        need = p.counter
        if need[city]:
            need[city] -= 1
            if contains(hand_cities, need):
                out.append(p)
    return out


def P(seat: int) -> str:
    """Player placeholder in log messages; the client shows the player's name."""
    return "{P%d}" % seat


def pattern_option(p: Pattern) -> dict:
    return {"pattern": p.id, "name": p.name, "value": p.value}


class CityExchange(Game):
    id = "city"
    name = "城市交易所"
    min_players = 3
    max_players = 4
    ai_names = ("小明", "小红", "小刚", "小丽")

    def option_specs(self) -> list[dict]:
        return [
            {"key": "start_money", "label": "初始货币", "type": "int", "default": 0, "min": 0, "max": 1000},
            {"key": "need_money", "label": "回购、强买需要钱够", "type": "bool", "default": True,
             "help": "关闭后余额可以因回购、强买变成负数；罚款（点炮、出游）总是可以扣成负数"},
            {"key": "buy_self", "label": "强买可以买自己的弃牌", "type": "bool", "default": True},
            {"key": "tour_loop", "label": "出游循环询问直到有人不弃牌", "type": "bool", "default": True,
             "help": "关闭后只问一圈，所有人都弃牌则无人付钱"},
            {"key": "cash_dianpao", "label": "兑现放入弃牌区的牌也可被点炮", "type": "bool", "default": False},
            {"key": "draw_cash_counts", "label": "摸牌阶段直接兑现计入本回合兑现次数", "type": "bool", "default": True},
        ]

    # ------------------------------------------------------------------ setup
    def setup(self, st: GameState) -> None:
        n = st.num_players
        st.add_zone("deck", visibility=HIDDEN)
        st.add_zone("removed", visibility=PUBLIC)
        for i in range(n):
            st.add_zone(f"hand:{i}", owner=i, visibility=OWNER)
            st.add_zone(f"special:{i}", owner=i, visibility=PUBLIC)
            st.add_zone(f"discard:{i}", owner=i, visibility=PUBLIC)
        for city in CITIES:
            for _ in range(4):
                st.add_card({"kind": "city", "city": city, "province": PROVINCE_OF[city]}, "deck")
        tours = [st.add_card({"kind": "tour", "name": "周游列国"}, "removed") for _ in range(4)]
        buys = [st.add_card({"kind": "buy", "name": "强买"}, "removed") for _ in range(8)]
        for i in range(n):
            st.move(tours[i], f"special:{i}")
            st.move(buys[2 * i], f"special:{i}")
            st.move(buys[2 * i + 1], f"special:{i}")
        st.shuffle("deck")
        for i in range(n):
            st.draw("deck", f"hand:{i}", HAND_SIZE[n])
        first = st.rng.randrange(n)
        st.vars.update(
            money=[st.options["start_money"]] * n,
            first=first,
            turn=None,
            turn_no=0,
            phase=None,
            used={},
            drawn_count=0,
            pending=None,
            tour=None,
            cash_count=[0] * n,
            dianpao_count=[0] * n,
            winners=None,
        )
        st.log(f"游戏开始，{P(first)} 先行动")
        self._begin_turn(st, first)

    # -------------------------------------------------------------- helpers
    def hand(self, st: GameState, seat: int) -> list[int]:
        return st.zone(f"hand:{seat}").cards

    def cities(self, st: GameState, cards) -> Counter:
        return Counter(st.attr(c, "city") for c in cards)

    def unused(self, st: GameState, seat: int, kind: str) -> list[int]:
        return [c for c in st.zone(f"special:{seat}").cards
                if st.attr(c, "kind") == kind and not st.prop(c, "used")]

    def card_name(self, st: GameState, card: int) -> str:
        a = st.cards[card]
        return a.get("city") or a.get("name")

    def _allocate(self, st: GameState, seat: int, need: Counter, prefer=()) -> list[int]:
        """Pick hand cards matching ``need``, preferring cards in ``prefer``."""
        hand = sorted(self.hand(st, seat), key=lambda c: c not in prefer)
        out, left = [], Counter(need)
        for c in hand:
            city = st.attr(c, "city")
            if left[city] > 0:
                left[city] -= 1
                out.append(c)
        if +left:
            raise IllegalAction("手牌不足以组成该 Pattern")
        return out

    def _pay(self, st: GameState, src: int | None, dst: int | None, amount: int) -> None:
        if src is not None:
            st.vars["money"][src] -= amount
        if dst is not None:
            st.vars["money"][dst] += amount

    # ----------------------------------------------------------------- turns
    def _begin_turn(self, st: GameState, seat: int) -> None:
        v = st.vars
        v.update(turn=seat, turn_no=v["turn_no"] + 1, used={"buyback": False, "buy": False, "cash": False})
        drawn = st.draw("deck", f"hand:{seat}", DRAW)
        st.private[seat]["drawn"] = drawn
        v["drawn_count"] = len(drawn)
        st.log(f"{P(seat)} 的回合：摸 {len(drawn)} 张牌（牌堆剩 {len(st.zone('deck').cards)} 张）")
        v["phase"] = "draw" if drawn else "main"

    def _end_turn(self, st: GameState) -> None:
        v = st.vars
        seat = v["turn"]
        st.private[seat].pop("drawn", None)
        if not st.zone("deck").cards:
            best = max(v["money"])
            v["winners"] = [i for i, m in enumerate(v["money"]) if m == best]
            v["phase"] = "over"
            v["turn"] = None
            st.log("牌堆已空，游戏结束")
            return
        self._begin_turn(st, (seat + 1) % st.num_players)

    # --------------------------------------------------------------- prompts
    def prompts(self, st: GameState) -> dict[int, dict]:
        v = st.vars
        phase = v["phase"]
        seat = v["turn"]
        if phase == "draw":
            drawn = st.private[seat]["drawn"]
            return {seat: {"type": "draw", "drawn": list(drawn), "cash": self._draw_cash_options(st, seat)}}
        if phase == "main":
            return {seat: self._main_prompt(st, seat)}
        if phase == "dianpao":
            p = v["pending"]
            return {s: {"type": "dianpao", "cards": list(p["cards"]), "by": p["by"],
                        "options": self._dianpao_options(st, s)}
                    for s in p["eligible"] if "dianpao_choice" not in st.private[s]}
        if phase == "tour":
            t = v["tour"]
            r = t["order"][t["idx"]]
            return {r: {"type": "tour", "by": t["by"], "cards": list(self.hand(st, r)), "fine": TOUR_FINE}}
        return {}

    def _draw_cash_options(self, st: GameState, seat: int) -> list[dict]:
        drawn_need = self.cities(st, st.private[seat]["drawn"])
        hand = self.cities(st, self.hand(st, seat))
        return [pattern_option(p) for p in cashable(hand) if contains(p.counter, drawn_need)]

    def _main_prompt(self, st: GameState, seat: int) -> dict:
        v, o = st.vars, st.options
        money = v["money"][seat]
        p: dict = {"type": "main", "cash": [], "buyback": [], "buy": None, "tour": False}
        if not v["used"]["cash"]:
            p["cash"] = [pattern_option(x) for x in cashable(self.cities(st, self.hand(st, seat)))]
        if not v["used"]["buyback"] and (money >= BUYBACK_COST or not o["need_money"]):
            p["buyback"] = list(st.zone(f"discard:{seat}").cards)
        if not v["used"]["buy"] and self.unused(st, seat, "buy") and (money >= BUY_PRICE or not o["need_money"]):
            cards = [c for i in range(st.num_players) if i != seat or o["buy_self"]
                     for c in st.zone(f"discard:{i}").cards]
            if cards:
                p["buy"] = {"max": 2 if st.num_players == 4 else 1, "price": BUY_PRICE, "cards": cards}
        p["tour"] = bool(self.unused(st, seat, "tour"))
        return p

    def _dianpao_options(self, st: GameState, seat: int) -> list[dict]:
        hand = self.cities(st, self.hand(st, seat))
        out = []
        for c in st.vars["pending"]["cards"]:
            for p in claimable(hand, st.attr(c, "city")):
                out.append({"card": c, **pattern_option(p), "gain": p.value * 2 // 3, "cost": p.value // 3})
        return out

    # ----------------------------------------------------------------- apply
    def apply(self, st: GameState, seat: int, action: dict) -> None:
        phase = st.vars["phase"]
        kind = action["type"]
        if phase == "draw":
            if kind == "discard":
                return self._act_draw_discard(st, seat, action.get("card"))
            if kind == "cash":
                return self._act_draw_cash(st, seat, action.get("pattern"))
        elif phase == "main":
            handler = {"cash": self._act_cash, "buyback": self._act_buyback, "buy": self._act_buy,
                       "tour": self._act_tour, "end": self._act_end}.get(kind)
            if handler:
                return handler(st, seat, action)
        elif phase == "dianpao" and kind == "dianpao":
            return self._act_dianpao(st, seat, action.get("choices"))
        elif phase == "tour" and kind == "tour":
            return self._act_tour_response(st, seat, action.get("card"))
        raise IllegalAction("现在不能这样做")

    # draw phase
    def _act_draw_discard(self, st, seat, card) -> None:
        if card not in st.private[seat]["drawn"]:
            raise IllegalAction("只能弃置本回合摸到的牌")
        st.vars["phase"] = "main"
        self._discard(st, seat, card, resume="main")

    def _act_draw_cash(self, st, seat, pid) -> None:
        if pid not in {o["pattern"] for o in self._draw_cash_options(st, seat)}:
            raise IllegalAction("不能这样兑现")
        st.vars["phase"] = "main"
        if st.options["draw_cash_counts"]:
            st.vars["used"]["cash"] = True
        self._cash(st, seat, PATTERN_BY_ID[pid], prefer=st.private[seat]["drawn"])

    # main phase
    def _act_cash(self, st, seat, action) -> None:
        pid = action.get("pattern")
        if st.vars["used"]["cash"]:
            raise IllegalAction("本回合已经兑现过")
        if pid not in PATTERN_BY_ID or not contains(self.cities(st, self.hand(st, seat)), PATTERN_BY_ID[pid].counter):
            raise IllegalAction("手牌不能组成该 Pattern")
        st.vars["used"]["cash"] = True
        self._cash(st, seat, PATTERN_BY_ID[pid])

    def _act_buyback(self, st, seat, action) -> None:
        card = action.get("card")
        if card not in self._main_prompt(st, seat)["buyback"]:
            raise IllegalAction("不能回购这张牌")
        st.vars["used"]["buyback"] = True
        self._pay(st, seat, None, BUYBACK_COST)
        st.move(card, f"hand:{seat}")
        st.reveal(card, range(st.num_players))
        st.log(f"{P(seat)} 花 {BUYBACK_COST} 元回购了 {self.card_name(st, card)}")

    def _act_buy(self, st, seat, action) -> None:
        cards = action.get("cards")
        offer = self._main_prompt(st, seat)["buy"]
        if (offer is None or not isinstance(cards, list) or not 1 <= len(cards) <= offer["max"]
                or len(set(cards)) != len(cards) or any(c not in offer["cards"] for c in cards)):
            raise IllegalAction("不能强买这些牌")
        if st.options["need_money"] and st.vars["money"][seat] < BUY_PRICE * len(cards):
            raise IllegalAction("钱不够")
        st.vars["used"]["buy"] = True
        st.set_prop(self.unused(st, seat, "buy")[0], "used", True)
        for c in cards:
            owner = st.zone(st.where(c)).owner
            self._pay(st, seat, owner, BUY_PRICE)
            st.move(c, f"hand:{seat}")
            st.reveal(c, range(st.num_players))
            st.log(f"{P(seat)} 强买了 {P(owner)} 的 {self.card_name(st, c)}，付 {BUY_PRICE} 元")

    def _act_tour(self, st, seat, action) -> None:
        cards = self.unused(st, seat, "tour")
        if not cards:
            raise IllegalAction("没有可用的周游列国")
        st.set_prop(cards[0], "used", True)
        n = st.num_players
        st.vars["tour"] = {"by": seat, "order": [(seat + k) % n for k in range(1, n)], "idx": 0}
        st.vars["phase"] = "tour"
        st.log(f"{P(seat)} 发动【周游列国】")

    def _act_end(self, st, seat, action) -> None:
        self._end_turn(st)

    # tour responses
    def _act_tour_response(self, st, seat, card) -> None:
        v = st.vars
        t = v["tour"]
        if card is None:
            self._pay(st, seat, t["by"], TOUR_FINE)
            st.log(f"{P(seat)} 不弃牌，交给 {P(t['by'])} {TOUR_FINE} 元")
            v["tour"] = None
            v["phase"] = "main"
            return
        if card not in self.hand(st, seat):
            raise IllegalAction("只能弃置自己的手牌")
        t["idx"] += 1
        resume = "tour"
        if t["idx"] == len(t["order"]):
            if st.options["tour_loop"]:
                t["idx"] = 0
            else:
                v["tour"] = None
                resume = "main"
                st.log("所有人都弃了牌，周游列国结束")
        v["phase"] = resume
        self._discard(st, seat, card, resume=resume)

    # ------------------------------------------------------ discard & claims
    def _discard(self, st: GameState, seat: int, card: int, resume: str) -> None:
        st.move(card, f"discard:{seat}")
        st.log(f"{P(seat)} 弃置 {self.card_name(st, card)}")
        self._open_window(st, seat, [card], resume)

    def _open_window(self, st: GameState, by: int, cards: list[int], resume: str) -> None:
        v = st.vars
        v["pending"] = {"by": by, "cards": cards, "eligible": [], "resume": resume}
        n = st.num_players
        eligible = [(by + k) % n for k in range(1, n) if self._dianpao_options(st, (by + k) % n)]
        if not eligible:
            v["pending"] = None
            return
        v["pending"]["eligible"] = eligible
        v["phase"] = "dianpao"

    def _choice_allocation(self, st: GameState, seat: int, choices) -> list[tuple[dict, list[int]]]:
        opts = self._dianpao_options(st, seat)
        if (not isinstance(choices, list) or len(set(choices)) != len(choices)
                or any(not isinstance(i, int) or not 0 <= i < len(opts) for i in choices)):
            raise IllegalAction("选择无效")
        total = Counter()
        chosen = []
        for i in choices:
            o = opts[i]
            need = PATTERN_BY_ID[o["pattern"]].counter
            need[st.attr(o["card"], "city")] -= 1
            total += need
            chosen.append((o, need))
        if not contains(self.cities(st, self.hand(st, seat)), total):
            raise IllegalAction("这些 Pattern 不能同时用你的手牌组成")
        return chosen

    def _act_dianpao(self, st, seat, choices) -> None:
        self._choice_allocation(st, seat, choices)  # validate now
        st.private[seat]["dianpao_choice"] = list(choices)
        p = st.vars["pending"]
        if any("dianpao_choice" not in st.private[s] for s in p["eligible"]):
            return
        for s in p["eligible"]:  # already in order after the discarder
            picks = st.private[s].pop("dianpao_choice")
            for o, need in self._choice_allocation(st, s, picks):
                cards = self._allocate(st, s, need)
                for c in cards:
                    st.move(c, f"discard:{s}")
                pat = PATTERN_BY_ID[o["pattern"]]
                self._pay(st, p["by"], None, pat.value // 3)
                self._pay(st, None, s, pat.value * 2 // 3)
                st.vars["dianpao_count"][p["by"]] += 1
                st.log(f"{P(p['by'])} 点炮：{P(s)} 用 {self.card_name(st, o['card'])} 兑现 {pat.name}，"
                       f"{P(s)} +{pat.value * 2 // 3}，{P(p['by'])} -{pat.value // 3}")
        st.vars["phase"] = p["resume"]
        st.vars["pending"] = None

    def _cash(self, st: GameState, seat: int, pat: Pattern, prefer=()) -> None:
        cards = self._allocate(st, seat, pat.counter, prefer)
        for c in cards:
            st.move(c, f"discard:{seat}")
        self._pay(st, None, seat, pat.value)
        st.vars["cash_count"][seat] += 1
        st.log(f"{P(seat)} 兑现 {pat.name}，获得 {pat.value} 元")
        if st.options["cash_dianpao"]:
            self._open_window(st, seat, cards, st.vars["phase"])

    # ------------------------------------------------------------------- misc
    def is_over(self, st: GameState) -> bool:
        return st.vars["phase"] == "over"

    def make_ai(self) -> AI:
        from .ai import CityAI
        return CityAI()

    def static_info(self) -> dict:
        return {
            "provinces": PROVINCES,
            "patterns": [{"id": p.id, "name": p.name, "value": p.value, "need": dict(p.need)} for p in PATTERNS],
        }

    def ai_delay(self, st: GameState, prompt: dict) -> float:
        return {"dianpao": 0.6, "tour": 0.8}.get(prompt["type"], 1.0)

    def describe(self, st: GameState, seat: int, action: dict) -> str:
        kind = action.get("type")
        card = action.get("card")
        if kind == "discard" and isinstance(card, int) and card in st.cards:
            return f"弃置 {self.card_name(st, card)}"
        if kind == "cash" and action.get("pattern") in PATTERN_BY_ID:
            return f"兑现 {PATTERN_BY_ID[action['pattern']].name}"
        if kind == "tour":
            if st.vars["phase"] == "main":
                return "发动周游列国"
            return f"弃置 {self.card_name(st, card)}" if isinstance(card, int) and card in st.cards else "付钱"
        return {"buyback": "回购", "buy": "强买", "end": "结束回合", "dianpao": "点炮响应"}.get(kind, str(kind))
