"""城市交易所 (rule book v5.5-beta), standard 3- and 4-player game.

Turn: draw 3 and discard one of them (or cash a Pattern containing all three
instead), then in any order: buy back (≤1), tour (周游列国), forced buy
(强买, ≤1), cash a Pattern (≤1), end the turn.  Every discard gives the
players who could use it a 点炮 offer.  Offers do not block the game: the
player whose turn it is keeps playing while others claim or decline, and
offers lapse when the turn ends or the card leaves the discard pile.

Points the rule book leaves open are room options (see ``option_specs``).
"""
from __future__ import annotations

from collections import Counter

from ...engine import AI, HIDDEN, OWNER, PUBLIC, Game, GameState, IllegalAction
from .data import CITIES, COPIES, PATTERN_BY_ID, PATTERNS, PROVINCE_OF, PROVINCES, Pattern

HAND_SIZE = {3: 8, 4: 9}
DRAW = 3
BUYBACK_COST = 10
BUY_PRICE = 4
TOUR_FINE = 6
# 斗地主 mode (rule book 3.2)
LANDLORD_HAND = 4
LANDLORD_BONUS = 4
LANDLORD_DRAW = 4
LANDLORD_BUY_PRICE = 2
FARMERS = "farmers"


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
            {"key": "mode", "label": "模式", "type": "choice", "default": "standard",
             "choices": [["standard", "标准"], ["landlord", "斗地主（3 人）"]]},
            {"key": "landlord_score", "label": "斗地主胜负", "type": "choice", "default": "sum",
             "choices": [["sum", "地主 vs 农民合计"], ["each", "各自比较"]]},
            {"key": "start_money", "label": "初始货币", "type": "int", "default": 0, "min": 0, "max": 1000},
            {"key": "need_money", "label": "回购、强买需要钱够", "type": "bool", "default": False,
             "help": "不勾选时余额可以因回购、强买变成负数；罚款（点炮、出游）总是可以扣成负数"},
            {"key": "buy_self", "label": "强买可以买自己的弃牌", "type": "bool", "default": True},
            {"key": "tour_loop", "label": "出游循环询问直到有人不弃牌", "type": "bool", "default": True,
             "help": "关闭后只问一圈，所有人都弃牌则无人付钱"},
            {"key": "cash_dianpao", "label": "兑现放入弃牌区的牌也可被点炮", "type": "bool", "default": False},
            {"key": "draw_cash_counts", "label": "摸牌阶段直接兑现计入本回合兑现次数", "type": "bool", "default": True},
        ]

    # ------------------------------------------------------------------ setup
    def setup(self, st: GameState) -> None:
        n = st.num_players
        landlord = st.options["mode"] == "landlord"
        if landlord and n != 3:
            raise ValueError("斗地主模式需要 3 人")
        st.add_zone("deck", visibility=HIDDEN)
        st.add_zone("removed", visibility=PUBLIC)
        for i in range(n):
            st.add_zone(f"hand:{i}", owner=i, visibility=OWNER)
            st.add_zone(f"special:{i}", owner=i, visibility=PUBLIC)
            st.add_zone(f"discard:{i}", owner=i, visibility=PUBLIC)
        for city in CITIES:
            for _ in range(COPIES):
                st.add_card({"kind": "city", "city": city, "province": PROVINCE_OF[city]}, "deck")
        tours = [st.add_card({"kind": "tour", "name": "周游列国"}, "removed") for _ in range(4)]
        buys = [st.add_card({"kind": "buy", "name": "强买"}, "removed") for _ in range(8)]
        if not landlord:
            for i in range(n):
                st.move(tours[i], f"special:{i}")
                st.move(buys[2 * i], f"special:{i}")
                st.move(buys[2 * i + 1], f"special:{i}")
        st.shuffle("deck")
        first = st.rng.randrange(n)
        st.vars.update(
            money=[st.options["start_money"]] * n,
            first=first,
            turn=None,
            turn_no=0,
            phase=None,
            used={},
            drawn_count=0,
            offers=[],        # open 点炮 offers, see _open_offer
            next_offer=0,
            tour=None,
            cash_count=[0] * n,
            dianpao_count=[0] * n,
            winners=None,
            last_discard=None,
            landlord=None,
            discard_of=[f"discard:{i}" for i in range(n)],
            special_of=[f"special:{i}" for i in range(n)],
        )
        if landlord:
            st.add_zone("bonus", visibility=PUBLIC)
            st.add_zone(f"discard:{FARMERS}", visibility=PUBLIC)
            st.add_zone(f"special:{FARMERS}", visibility=PUBLIC)
            self._deal_landlord(st)
            return
        for i in range(n):
            st.draw("deck", f"hand:{i}", HAND_SIZE[n])
        st.log(f"游戏开始，{P(first)} 先行动")
        self._begin_turn(st, first)

    # ---------------------------------------------------------- 斗地主 setup
    def _deal_landlord(self, st: GameState) -> None:
        n = st.num_players
        for i in range(n):
            st.draw("deck", f"hand:{i}", LANDLORD_HAND)
        st.draw("deck", "bonus", LANDLORD_BONUS)
        first = st.vars["first"]
        st.vars["bid"] = {"order": [(first + k) % n for k in range(n)], "idx": 0}
        st.vars["phase"] = "bid"
        st.log(f"每人摸 {LANDLORD_HAND} 张，翻开牌堆顶 {LANDLORD_BONUS} 张；从 {P(first)} 开始依次决定是否当地主")

    def _act_bid(self, st: GameState, seat: int, take) -> None:
        if not isinstance(take, bool):
            raise IllegalAction("请选择是否当地主")
        v = st.vars
        b = v["bid"]
        if not take:
            st.log(f"{P(seat)} 不当地主")
            b["idx"] += 1
            if b["idx"] < len(b["order"]):
                return
            # nobody wants it: shuffle everything back and deal again
            st.log("没有人当地主，重新洗牌发牌")
            for i in range(st.num_players):
                st.move_all(f"hand:{i}", "deck")
            st.move_all("bonus", "deck")
            st.shuffle("deck")
            v["first"] = (v["first"] + 1) % st.num_players
            self._deal_landlord(st)
            return
        v["bid"] = None
        v["landlord"] = seat
        st.move_all("bonus", f"hand:{seat}")
        farmers = [i for i in range(st.num_players) if i != seat]
        for i in farmers:
            v["discard_of"][i] = f"discard:{FARMERS}"
            v["special_of"][i] = f"special:{FARMERS}"
        removed = st.zone("removed").cards
        buys = [c for c in removed if st.attr(c, "kind") == "buy"][:3]
        tour = next(c for c in removed if st.attr(c, "kind") == "tour")
        for c in buys:
            st.move(c, f"special:{seat}")
        st.move(tour, f"special:{FARMERS}")
        st.log(f"{P(seat)} 成为地主，获得翻开的 {LANDLORD_BONUS} 张牌")
        self._begin_turn(st, seat)

    def _act_give(self, st: GameState, seat: int, card) -> None:
        if card not in self.hand(st, seat):
            raise IllegalAction("只能交出自己的手牌")
        to = self.partner(st, seat)
        st.move(card, f"hand:{to}")
        st.reveal(card, [seat])
        st.log(f"{P(seat)} 交给 {P(to)} 一张牌")
        self._end_turn(st)

    # -------------------------------------------------------------- helpers
    def hand(self, st: GameState, seat: int) -> list[int]:
        return st.zone(f"hand:{seat}").cards

    def cities(self, st: GameState, cards) -> Counter:
        return Counter(st.attr(c, "city") for c in cards)

    def landlord_mode(self, st: GameState) -> bool:
        return st.options.get("mode") == "landlord"

    def discard_zone(self, st: GameState, seat: int) -> str:
        return st.vars["discard_of"][seat]

    def partner(self, st: GameState, seat: int) -> int | None:
        """The other farmer in 斗地主 mode."""
        lord = st.vars.get("landlord")
        if lord is None or seat == lord:
            return None
        return next(i for i in range(st.num_players) if i not in (seat, lord))

    def discarded_by(self, st: GameState, card: int) -> int:
        """Who discarded a card lying in a discard pile (shared piles record it)."""
        by = st.prop(card, "by")
        return by if by is not None else st.zone(st.where(card)).owner

    def unused(self, st: GameState, seat: int, kind: str) -> list[int]:
        return [c for c in st.zone(st.vars["special_of"][seat]).cards
                if st.attr(c, "kind") == kind and not st.prop(c, "used")]

    def buy_price(self, st: GameState) -> int:
        return LANDLORD_BUY_PRICE if self.landlord_mode(st) else BUY_PRICE

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
        n_draw = LANDLORD_DRAW if seat == v.get("landlord") else DRAW
        drawn = st.draw("deck", f"hand:{seat}", n_draw)
        st.private[seat]["drawn"] = drawn
        v["drawn_count"] = len(drawn)
        st.log(f"{P(seat)} 的回合：摸 {len(drawn)} 张牌（牌堆剩 {len(st.zone('deck').cards)} 张）")
        v["phase"] = "draw" if drawn else "main"

    def _end_turn(self, st: GameState) -> None:
        v = st.vars
        seat = v["turn"]
        st.private[seat].pop("drawn", None)
        v["offers"] = []  # 点炮 offers not taken during the turn lapse
        if not st.zone("deck").cards:
            lord = v.get("landlord")
            if lord is not None and st.options["landlord_score"] == "sum":
                farmers = [i for i in range(st.num_players) if i != lord]
                team = sum(v["money"][i] for i in farmers)
                v["teams"] = {"landlord": v["money"][lord], "farmers": team}
                v["winners"] = [lord] if v["money"][lord] > team else farmers if team > v["money"][lord] \
                    else list(range(st.num_players))
            else:
                best = max(v["money"])
                v["winners"] = [i for i, m in enumerate(v["money"]) if m == best]
            v["phase"] = "over"
            v["turn"] = None
            st.log("牌堆已空，游戏结束")
            return
        self._begin_turn(st, (seat + 1) % st.num_players)

    # --------------------------------------------------------------- prompts
    def prompts(self, st: GameState) -> dict[int, dict]:
        out = self._flow_prompts(st)
        # 点炮 offers are answered alongside the normal flow
        for seat in range(st.num_players):
            claims = self._claims(st, seat)
            if not claims:
                continue
            if seat in out:
                out[seat] = {**out[seat], "claims": claims}
            else:
                out[seat] = {"type": "dianpao", "claims": claims}
        return out

    def _flow_prompts(self, st: GameState) -> dict[int, dict]:
        v = st.vars
        phase = v["phase"]
        seat = v["turn"]
        if phase == "draw":
            drawn = st.private[seat]["drawn"]
            return {seat: {"type": "draw", "drawn": list(drawn), "cash": self._draw_cash_options(st, seat)}}
        if phase == "main":
            return {seat: self._main_prompt(st, seat)}
        if phase == "tour":
            t = v["tour"]
            r = t["order"][t["idx"]]
            return {r: {"type": "tour", "by": t["by"], "cards": list(self.hand(st, r)), "fine": TOUR_FINE}}
        if phase == "bid":
            b = v["bid"]
            return {b["order"][b["idx"]]: {"type": "bid", "bonus": list(st.zone("bonus").cards)}}
        if phase == "give":
            return {seat: {"type": "give", "to": self.partner(st, seat), "cards": list(self.hand(st, seat))}}
        return {}

    def _claims(self, st: GameState, seat: int) -> list[dict]:
        """Open 点炮 offers ``seat`` can still take."""
        out = []
        for offer in st.vars["offers"]:
            if seat in offer["eligible"] and seat not in offer["answered"]:
                options = self._dianpao_options(st, seat, offer)
                if options:
                    out.append({"offer": offer["id"], "by": offer["by"], "cards": self._live_cards(st, offer),
                                "options": options})
        return out

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
            p["buyback"] = list(st.zone(self.discard_zone(st, seat)).cards)
        price = self.buy_price(st)
        if not v["used"]["buy"] and self.unused(st, seat, "buy") and (money >= price or not o["need_money"]):
            own = self.discard_zone(st, seat)
            zones = dict.fromkeys(v["discard_of"])  # distinct piles, in seat order
            cards = [c for z in zones if z != own or o["buy_self"] for c in st.zone(z).cards]
            if cards:
                p["buy"] = {"max": 2 if st.num_players == 4 else 1, "price": price, "cards": cards}
        p["tour"] = bool(self.unused(st, seat, "tour"))
        return p

    def _live_cards(self, st: GameState, offer: dict) -> list[int]:
        """Offered cards still lying in the pile they were discarded to."""
        return [c for c in offer["cards"] if st.where(c) == offer["zone"]]

    def _dianpao_options(self, st: GameState, seat: int, offer: dict) -> list[dict]:
        hand = self.cities(st, self.hand(st, seat))
        out = []
        for c in self._live_cards(st, offer):
            for p in claimable(hand, st.attr(c, "city")):
                out.append({"card": c, **pattern_option(p), "gain": p.value * 2 // 3, "cost": self._dianpao_cost(st, p)})
        return out

    def _dianpao_cost(self, st: GameState, p: Pattern) -> int:
        return 0 if self.landlord_mode(st) else p.value // 3

    # ----------------------------------------------------------------- apply
    def apply(self, st: GameState, seat: int, action: dict) -> None:
        phase = st.vars["phase"]
        kind = action["type"]
        if kind == "dianpao" and phase != "over":
            return self._act_dianpao(st, seat, action.get("offer"), action.get("choices"))
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
        elif phase == "tour" and kind == "tour":
            return self._act_tour_response(st, seat, action.get("card"))
        elif phase == "bid" and kind == "bid":
            return self._act_bid(st, seat, action.get("take"))
        elif phase == "give" and kind == "give":
            return self._act_give(st, seat, action.get("card"))
        raise IllegalAction("现在不能这样做")

    # draw phase
    def _act_draw_discard(self, st, seat, card) -> None:
        if card not in st.private[seat]["drawn"]:
            raise IllegalAction("只能弃置本回合摸到的牌")
        st.vars["phase"] = "main"
        self._discard(st, seat, card)

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
        st.set_prop(card, "by", None)
        st.move(card, f"hand:{seat}")
        st.reveal(card, range(st.num_players))
        st.log(f"{P(seat)} 花 {BUYBACK_COST} 元回购了 {self.card_name(st, card)}")

    def _act_buy(self, st, seat, action) -> None:
        cards = action.get("cards")
        offer = self._main_prompt(st, seat)["buy"]
        if (offer is None or not isinstance(cards, list) or not 1 <= len(cards) <= offer["max"]
                or len(set(cards)) != len(cards) or any(c not in offer["cards"] for c in cards)):
            raise IllegalAction("不能强买这些牌")
        price = offer["price"]
        if st.options["need_money"] and st.vars["money"][seat] < price * len(cards):
            raise IllegalAction("钱不够")
        st.vars["used"]["buy"] = True
        st.set_prop(self.unused(st, seat, "buy")[0], "used", True)
        for c in cards:
            owner = self.discarded_by(st, c)
            self._pay(st, seat, owner, price)
            st.set_prop(c, "by", None)
            st.move(c, f"hand:{seat}")
            st.reveal(c, range(st.num_players))
            st.log(f"{P(seat)} 强买了 {P(owner)} 的 {self.card_name(st, c)}，付 {price} 元")

    def _act_tour(self, st, seat, action) -> None:
        cards = self.unused(st, seat, "tour")
        if not cards:
            raise IllegalAction("没有可用的周游列国")
        st.set_prop(cards[0], "used", True)
        n = st.num_players
        # from the next player round the table, the touring player included (last)
        st.vars["tour"] = {"by": seat, "order": [(seat + k) % n for k in range(1, n + 1)], "idx": 0}
        st.vars["phase"] = "tour"
        st.log(f"{P(seat)} 发动【周游列国】")

    def _act_end(self, st, seat, action) -> None:
        if self.partner(st, seat) is not None and self.hand(st, seat):
            st.vars["phase"] = "give"  # 农民回合结束时交给另一位农民一张牌
            return
        self._end_turn(st)

    # tour responses
    def _act_tour_response(self, st, seat, card) -> None:
        v = st.vars
        t = v["tour"]
        if card is None:
            if seat == t["by"]:
                st.log(f"{P(seat)} 不弃牌（付给自己），周游列国结束")
            else:
                self._pay(st, seat, t["by"], TOUR_FINE)
                st.log(f"{P(seat)} 不弃牌，交给 {P(t['by'])} {TOUR_FINE} 元")
            v["tour"] = None
            v["phase"] = "main"
            return
        if card not in self.hand(st, seat):
            raise IllegalAction("只能弃置自己的手牌")
        t["idx"] += 1
        if t["idx"] == len(t["order"]):
            if st.options["tour_loop"]:
                t["idx"] = 0
            else:
                v["tour"] = None
                v["phase"] = "main"
                st.log("所有人都弃了牌，周游列国结束")
        self._discard(st, seat, card)

    # ------------------------------------------------------ discard & claims
    def _put_discard(self, st: GameState, seat: int, card: int) -> None:
        zone = self.discard_zone(st, seat)
        st.move(card, zone)
        if st.zone(zone).owner is None:
            st.set_prop(card, "by", seat)

    def _discard(self, st: GameState, seat: int, card: int) -> None:
        self._put_discard(st, seat, card)
        st.vars["last_discard"] = {"card": card, "by": seat}
        st.log(f"{P(seat)} 弃置 {self.card_name(st, card)}")
        self._open_offer(st, seat, [card])

    def _open_offer(self, st: GameState, by: int, cards: list[int]) -> None:
        """Let every player who could use ``cards`` claim 点炮, without pausing the game."""
        v = st.vars
        offer = {"id": v["next_offer"], "by": by, "cards": list(cards), "zone": st.where(cards[0]),
                 "eligible": [], "answered": []}
        n = st.num_players
        offer["eligible"] = [(by + k) % n for k in range(1, n) if self._dianpao_options(st, (by + k) % n, offer)]
        if offer["eligible"]:
            v["next_offer"] += 1
            v["offers"].append(offer)

    def _choice_allocation(self, st: GameState, seat: int, offer: dict, choices) -> list[tuple[dict, Counter]]:
        opts = self._dianpao_options(st, seat, offer)
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

    def _act_dianpao(self, st, seat, offer_id, choices) -> None:
        offer = next((o for o in st.vars["offers"] if o["id"] == offer_id), None)
        if offer is None or seat not in offer["eligible"] or seat in offer["answered"]:
            raise IllegalAction("这次点炮机会已经过去了")
        if not self._dianpao_options(st, seat, offer):
            raise IllegalAction("已经不能点炮了")
        by = offer["by"]
        for o, need in self._choice_allocation(st, seat, offer, choices):
            for c in self._allocate(st, seat, need):
                self._put_discard(st, seat, c)
            pat = PATTERN_BY_ID[o["pattern"]]
            cost = self._dianpao_cost(st, pat)
            self._pay(st, by, None, cost)
            self._pay(st, None, seat, pat.value * 2 // 3)
            st.vars["dianpao_count"][by] += 1
            st.log(f"{P(by)} 点炮：{P(seat)} 用 {self.card_name(st, o['card'])} 兑现 {pat.name}，"
                   f"{P(seat)} +{pat.value * 2 // 3}，" + (f"{P(by)} -{cost}" if cost else "弃牌者不扣钱"))
        offer["answered"].append(seat)
        if set(offer["answered"]) >= set(offer["eligible"]):
            st.vars["offers"].remove(offer)

    def _cash(self, st: GameState, seat: int, pat: Pattern, prefer=()) -> None:
        cards = self._allocate(st, seat, pat.counter, prefer)
        for c in cards:
            self._put_discard(st, seat, c)
        self._pay(st, None, seat, pat.value)
        st.vars["cash_count"][seat] += 1
        st.log(f"{P(seat)} 兑现 {pat.name}，获得 {pat.value} 元")
        if st.options["cash_dianpao"]:
            self._open_offer(st, seat, cards)

    # ------------------------------------------------------------------- misc
    def is_over(self, st: GameState) -> bool:
        return st.vars["phase"] == "over"

    def make_ai(self) -> AI:
        from .ai import CityAI
        return CityAI()

    def migrate(self, st: GameState) -> GameState:
        v = st.vars
        if "offers" not in v:
            # before 点炮 offers existed, a discard opened a blocking "dianpao" phase
            pending = v.pop("pending", None)
            if v.get("phase") == "dianpao":
                v["phase"] = (pending or {}).get("resume", "main")
            for p in st.private:
                p.pop("dianpao_choice", None)
            v["offers"] = []
            v["next_offer"] = 0
        return st

    def static_info(self) -> dict:
        return {
            "provinces": PROVINCES,
            "copies": COPIES,
            "patterns": [{"id": p.id, "name": p.name, "value": p.value, "need": dict(p.need)} for p in PATTERNS],
        }

    def ai_delay(self, st: GameState, prompt: dict) -> float:
        if prompt.get("claims"):
            return 0.6
        return {"tour": 0.8, "give": 0.8}.get(prompt["type"], 1.0)

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
        if kind == "bid":
            return "当地主" if action.get("take") else "不当地主"
        return {"buyback": "回购", "buy": "强买", "end": "结束回合", "dianpao": "点炮响应", "give": "交牌"}.get(kind, str(kind))
