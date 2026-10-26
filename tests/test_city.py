import json
import random

import pytest

from cardgame.engine import GameState, IllegalAction
from cardgame.games.city.data import PATTERN_BY_ID, PATTERNS
from cardgame.games.city import rules
from cardgame.games.city.rules import CityExchange

G = CityExchange()


class Clock:
    """Stands in for the wall clock: by default each reading is 10 s after
    the previous one, so the waits after discards are always over."""
    def __init__(self):
        self.t = 1000.0
        self.step = 10.0

    def __call__(self):
        self.t += self.step
        return self.t


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(rules, "now", c)
    return c


def card_of(st, city, avoid=()):
    """A card of ``city`` that is still in the deck."""
    for c in st.zone("deck").cards:
        if st.attr(c, "city") == city and c not in avoid:
            return c
    raise LookupError(city)


def setup(n=3, hands=None, turn=0, options=None, money=None):
    """A main-phase state with chosen hands (other cards back in the deck)."""
    st = G.new_state(n, options, seed=1)
    for i in range(n):
        st.move_all(f"hand:{i}", "deck")
    for i, cities in (hands or {}).items():
        for city in cities:
            st.move(card_of(st, city), f"hand:{i}")
    st.private = [{} for _ in range(n)]
    st.vars.update(turn=turn, phase="main", used={"buyback": False, "buy": False, "cash": False})
    if money:
        st.vars["money"] = list(money)
    return st


def cities(st, zone):
    return sorted(st.attr(c, "city") for c in st.zone(zone).cards)


def decline_offers(st):
    """Answer every open 点炮 offer with 'no'."""
    for seat, prompt in list(G.prompts(st).items()):
        for claim in prompt.get("claims", []):
            G.act(st, seat, {"type": "dianpao", "offer": claim["offer"], "choices": []})


def play_ai(st):
    ai = G.make_ai()
    steps = 0
    while not G.is_over(st):
        p = G.prompts(st)
        seat = min(p)
        G.act(st, seat, ai.choose(G.view(st, seat), p[seat]))
        steps += 1
        assert steps < 5000
    return st


def test_setup_counts():
    st = G.new_state(3, seed=0)
    assert [len(st.zone(f"hand:{i}").cards) for i in range(3)] == [8 + 3 * (i == st.vars["turn"]) for i in range(3)]
    assert len(st.zone("deck").cards) == 96 - 24 - 3
    assert len(st.zone("removed").cards) == 3
    for i in range(3):
        kinds = sorted(st.attr(c, "kind") for c in st.zone(f"special:{i}").cards)
        assert kinds == ["buy", "buy", "tour"]
    st4 = G.new_state(4, seed=0)
    assert len(st4.zone("deck").cards) == 96 - 36 - 3 and not st4.zone("removed").cards
    assert st.vars["phase"] == "draw"


def test_patterns_table():
    assert len(PATTERNS) == 46
    assert PATTERN_BY_ID["special:长江之歌"].value == 66
    assert PATTERN_BY_ID["four:北京"].counter == {"北京": 4}
    assert PATTERN_BY_ID["province:江苏"].size == 5


def test_draw_must_discard_a_drawn_card():
    st = G.new_state(3, seed=2)
    seat = st.vars["turn"]
    drawn = st.private[seat]["drawn"]
    other = next(c for c in st.zone(f"hand:{seat}").cards if c not in drawn)
    with pytest.raises(IllegalAction):
        G.act(st, seat, {"type": "discard", "card": other})
    # other players cannot see which cards were drawn
    view = G.view(st, (seat + 1) % 3)
    assert view["private"] == {}
    assert all(c is None for c in view["zones"][f"hand:{seat}"]["cards"])
    assert not set(drawn) & set(map(int, view["cards"]))
    G.act(st, seat, {"type": "discard", "card": drawn[0]})
    assert st.zone(f"discard:{seat}").cards == [drawn[0]] and st.vars["phase"] == "main"


def test_draw_cash_with_all_three_drawn():
    st = setup(hands={0: ["北京"]})
    drawn = [card_of(st, c) for c in ("天津", "上海", "重庆")]
    for c in drawn:
        st.move(c, "hand:0")
    st.private[0]["drawn"] = drawn
    st.vars["phase"] = "draw"
    prompt = G.prompts(st)[0]
    assert [o["pattern"] for o in prompt["cash"]] == ["municipal"]
    G.act(st, 0, {"type": "cash", "pattern": "municipal"})
    assert st.vars["money"][0] == 24 and st.vars["used"]["cash"]
    assert cities(st, "discard:0") == sorted(["北京", "天津", "上海", "重庆"])


def test_cash_once_per_turn():
    st = setup(hands={0: ["北京", "天津", "上海", "南京"]})
    opts = {o["pattern"] for o in G.prompts(st)[0]["cash"]}
    assert opts == {"pair:北京天津", "pair:上海南京"}
    G.act(st, 0, {"type": "cash", "pattern": "pair:北京天津"})
    assert st.vars["money"][0] == 6
    assert G.prompts(st)[0]["cash"] == []
    with pytest.raises(IllegalAction):
        G.act(st, 0, {"type": "cash", "pattern": "pair:上海南京"})


def test_buyback_by_default_may_go_negative():
    st = setup(hands={0: ["北京"]}, money=[5, 0, 0])
    st.move(card_of(st, "天津"), "discard:0")
    card = G.prompts(st)[0]["buyback"][0]
    G.act(st, 0, {"type": "buyback", "card": card})
    assert st.vars["money"][0] == -5 and card in st.zone("hand:0").cards


def test_buyback_costs_10_and_needs_money():
    st = setup(hands={0: ["北京"]}, money=[5, 0, 0], options={"need_money": True})
    st.move(card_of(st, "天津"), "discard:0")
    assert G.prompts(st)[0]["buyback"] == []
    st.vars["money"][0] = 10
    card = G.prompts(st)[0]["buyback"][0]
    G.act(st, 0, {"type": "buyback", "card": card})
    assert st.vars["money"][0] == 0 and card in st.zone("hand:0").cards
    # everybody saw the card go back to the hand
    assert card in G.view(st, 1)["zones"]["hand:0"]["cards"]
    assert G.prompts(st)[0]["buyback"] == []


def test_forced_buy_pays_owner_and_flips_card():
    st = setup(hands={0: ["北京"]}, money=[8, 0, 0])
    target = card_of(st, "天津")
    st.move(target, "discard:2")
    offer = G.prompts(st)[0]["buy"]
    assert offer["max"] == 1 and target in offer["cards"]
    G.act(st, 0, {"type": "buy", "cards": [target]})
    assert st.vars["money"] == [4, 0, 4]
    assert target in st.zone("hand:0").cards
    assert sum(1 for c in st.zone("special:0").cards if st.prop(c, "used")) == 1
    assert G.prompts(st)[0]["buy"] is None


def test_four_player_buy_two():
    st = setup(n=4, hands={0: ["北京"]}, money=[10, 0, 0, 0])
    a, b = card_of(st, "天津"), card_of(st, "上海")
    st.move(a, "discard:1")
    st.move(b, "discard:3")
    G.act(st, 0, {"type": "buy", "cards": [a, b]})
    assert st.vars["money"] == [2, 4, 0, 4]


def test_dianpao_rulebook_example():
    # 十堰、中山、襄阳×2、荆州、徐州 + someone discards 广元 -> 古来要塞 and 泉岭大球
    st = setup(hands={1: ["十堰", "中山", "襄阳", "襄阳", "荆州", "徐州"], 0: ["广元"]})
    st.vars["phase"] = "tour"
    st.vars["tour"] = {"by": 2, "order": [0, 1], "idx": 0}
    G.act(st, 0, {"type": "tour", "card": st.zone("hand:0").cards[0]})
    # the tour goes on: seat 1 is asked to discard and may claim 点炮 at the same time
    prompt = G.prompts(st)[1]
    assert prompt["type"] == "tour" and len(prompt["claims"]) == 1
    claim = prompt["claims"][0]
    names = [o["pattern"] for o in claim["options"]]
    both = [names.index("special:古来要塞"), names.index("special:泉岭大球")]
    G.act(st, 1, {"type": "dianpao", "offer": claim["offer"], "choices": both})
    assert st.vars["money"][1] == 16 + 16 and st.vars["money"][0] == -16
    assert cities(st, "hand:1") == []
    assert cities(st, "discard:0") == ["广元"]
    assert st.vars["offers"] == []
    assert G.prompts(st) == {1: {"type": "tour", "by": 2, "cards": [], "fine": 6}}


def test_dianpao_incompatible_choices_rejected():
    st = setup(hands={1: ["北京", "北京", "北京"], 0: ["北京"]})
    st.vars["phase"] = "tour"
    st.vars["tour"] = {"by": 2, "order": [0, 1], "idx": 0}
    G.act(st, 0, {"type": "tour", "card": st.zone("hand:0").cards[0]})
    claim = G.prompts(st)[1]["claims"][0]
    assert [o["pattern"] for o in claim["options"]] == ["four:北京"]
    with pytest.raises(IllegalAction):
        G.act(st, 1, {"type": "dianpao", "offer": claim["offer"], "choices": [0, 0]})
    G.act(st, 1, {"type": "dianpao", "offer": claim["offer"], "choices": []})
    assert st.vars["money"] == [0, 0, 0] and st.vars["offers"] == []


def test_dianpao_does_not_block_and_lapses_at_turn_end():
    st = setup(hands={0: ["北京"], 1: ["天津"], 2: ["天津"]})
    st.vars["phase"] = "draw"
    st.private[0]["drawn"] = list(st.zone("hand:0").cards)
    G.act(st, 0, {"type": "discard", "card": st.zone("hand:0").cards[0]})
    prompts = G.prompts(st)
    # the discarder carries on while both others hold an offer
    assert prompts[0]["type"] == "main" and "claims" not in prompts[0]
    assert prompts[1]["type"] == prompts[2]["type"] == "dianpao"
    offer = prompts[1]["claims"][0]["offer"]
    G.act(st, 1, {"type": "dianpao", "offer": offer, "choices": [0]})  # first come, first served
    assert st.vars["money"] == [-2, 4, 0]
    assert set(G.prompts(st)) == {0, 2}
    G.act(st, 0, {"type": "end"})
    assert st.vars["offers"] == [] and set(G.prompts(st)) == {1}
    with pytest.raises(IllegalAction):
        G.act(st, 2, {"type": "dianpao", "offer": offer, "choices": [0]})


def test_dianpao_offer_ends_when_card_is_bought():
    st = setup(hands={0: ["北京"], 1: ["天津"]}, money=[10, 0, 10])
    st.vars["phase"] = "draw"
    st.private[0]["drawn"] = list(st.zone("hand:0").cards)
    beijing = st.zone("hand:0").cards[0]
    G.act(st, 0, {"type": "discard", "card": beijing})
    offer = G.prompts(st)[1]["claims"][0]["offer"]
    G.act(st, 0, {"type": "buy", "cards": [beijing]})  # buys its own discard back
    assert 1 not in G.prompts(st)
    with pytest.raises(IllegalAction):
        G.act(st, 1, {"type": "dianpao", "offer": offer, "choices": [0]})


def test_tour_pays_fine_or_loops():
    st = setup(hands={1: ["北京"], 2: []})
    G.act(st, 0, {"type": "tour"})
    assert st.vars["tour"]["order"] == [1, 2, 0]  # the touring player is in the queue too
    assert G.prompts(st)[1]["type"] == "tour"
    G.act(st, 1, {"type": "tour", "card": st.zone("hand:1").cards[0]})
    # seat 2 has no cards and must pay
    assert G.prompts(st)[2]["cards"] == []
    with pytest.raises(IllegalAction):
        G.act(st, 2, {"type": "tour", "card": 0})
    G.act(st, 2, {"type": "tour", "card": None})
    assert st.vars["money"] == [6, 0, -6] and st.vars["phase"] == "main"
    assert G.prompts(st)[0]["tour"] is False


def test_tour_once_mode_nobody_pays():
    st = setup(hands={0: ["广州"], 1: ["北京"], 2: ["上海"]}, options={"tour_loop": False})
    G.act(st, 0, {"type": "tour"})
    G.act(st, 1, {"type": "tour", "card": st.zone("hand:1").cards[0]})
    G.act(st, 2, {"type": "tour", "card": st.zone("hand:2").cards[0]})
    assert G.prompts(st)[0]["type"] == "tour"  # the touring player's turn in the queue
    G.act(st, 0, {"type": "tour", "card": st.zone("hand:0").cards[0]})
    assert st.vars["phase"] == "main" and st.vars["money"] == [0, 0, 0]


def test_tour_touring_player_stops_for_free():
    st = setup(hands={0: ["广州"], 1: ["北京", "成都"], 2: ["上海"]})
    G.act(st, 0, {"type": "tour"})
    G.act(st, 1, {"type": "tour", "card": st.zone("hand:1").cards[0]})
    G.act(st, 2, {"type": "tour", "card": st.zone("hand:2").cards[0]})
    G.act(st, 0, {"type": "tour", "card": None})  # paying oneself: the tour just ends
    assert st.vars["phase"] == "main" and st.vars["money"] == [0, 0, 0] and st.vars["tour"] is None


def test_game_ends_when_deck_empty():
    st = setup(hands={0: ["北京"]})
    st.move_all("deck", "removed")
    G.act(st, 0, {"type": "end"})
    assert G.is_over(st) and G.prompts(st) == {}


def test_ai_full_games_and_roundtrip():
    for n in (3, 4):
        for seed in range(5):
            st = play_ai(G.new_state(n, seed=seed))
            assert len(st.zone("deck").cards) == 0
            total = sum(len(z.cards) for z in st.zones.values())
            assert total == 108
    st = G.new_state(3, seed=9)
    rng = random.Random(0)
    for _ in range(40):
        p = G.prompts(st)
        seat = min(p)
        G.act(st, seat, G.make_ai().choose(G.view(st, seat), p[seat]))
    d = json.loads(json.dumps(st.to_dict()))
    a, b = st, GameState.from_dict(d)
    play_ai(a)
    play_ai(b)
    assert a.vars["money"] == b.vars["money"]
    assert rng  # keep linters quiet about the unused rng


def test_options_are_cleaned():
    st = G.new_state(3, {"start_money": 20, "bogus": 1, "tour_loop": "yes"}, seed=0)
    assert st.options["start_money"] == 20 and st.options["tour_loop"] is True and "bogus" not in st.options
    assert st.vars["money"] == [20, 20, 20]


# ------------------------------------------------------------------ 斗地主
def landlord_state(seed=3):
    st = G.new_state(3, {"mode": "landlord"}, seed=seed)
    assert st.vars["phase"] == "bid"
    return st


def test_landlord_bidding_and_setup():
    st = landlord_state()
    assert [len(st.zone(f"hand:{i}").cards) for i in range(3)] == [4, 4, 4]
    bonus = list(st.zone("bonus").cards)
    first, second = st.vars["bid"]["order"][:2]
    assert list(G.prompts(st)) == [first]
    G.act(st, first, {"type": "bid", "take": False})
    G.act(st, second, {"type": "bid", "take": True})
    v = st.vars
    assert v["landlord"] == second and v["turn"] == second and v["phase"] == "draw"
    assert all(c in st.zone(f"hand:{second}").cards for c in bonus)
    assert len(st.private[second]["drawn"]) == 4
    kinds = sorted(st.attr(c, "kind") for c in st.zone(f"special:{second}").cards)
    assert kinds == ["buy", "buy", "buy"]
    assert [st.attr(c, "kind") for c in st.zone("special:farmers").cards] == ["tour"]
    farmers = [i for i in range(3) if i != second]
    assert all(v["discard_of"][i] == "discard:farmers" for i in farmers)


def test_nobody_bids_redeals():
    st = landlord_state()
    for seat in list(st.vars["bid"]["order"]):
        G.act(st, seat, {"type": "bid", "take": False})
    assert st.vars["phase"] == "bid" and st.vars["landlord"] is None
    assert len(st.zone("bonus").cards) == 4 and len(st.zone("deck").cards) == 96 - 16


def test_farmer_gives_card_and_shares_pile():
    st = landlord_state()
    lord = st.vars["bid"]["order"][0]
    G.act(st, lord, {"type": "bid", "take": True})
    G.act(st, lord, {"type": "discard", "card": st.private[lord]["drawn"][0]})
    decline_offers(st)
    G.act(st, lord, {"type": "end"})  # the landlord does not give a card
    farmer = st.vars["turn"]
    partner = G.partner(st, farmer)
    assert farmer != lord and partner not in (None, lord, farmer)
    G.act(st, farmer, {"type": "discard", "card": st.private[farmer]["drawn"][0]})
    decline_offers(st)
    assert len(st.zone("discard:farmers").cards) == 1
    G.act(st, farmer, {"type": "end"})
    assert st.vars["phase"] == "give" and G.prompts(st)[farmer]["to"] == partner
    gift = st.zone(f"hand:{farmer}").cards[0]
    G.act(st, farmer, {"type": "give", "card": gift})
    assert gift in st.zone(f"hand:{partner}").cards
    assert gift in G.view(st, farmer)["zones"][f"hand:{partner}"]["cards"]
    assert gift not in G.view(st, lord)["zones"][f"hand:{partner}"]["cards"]
    assert st.vars["turn"] == partner


def test_landlord_buy_price_and_no_dianpao_penalty():
    st = landlord_state()
    lord = st.vars["bid"]["order"][0]
    G.act(st, lord, {"type": "bid", "take": True})
    farmer = (lord + 1) % 3
    # a farmer's discard in the shared pile is paid to that farmer
    c = card_of(st, "北京")
    st.move(c, "discard:farmers")
    st.set_prop(c, "by", farmer)
    st.vars.update(phase="main", money=[10, 10, 10])
    offer = G.prompts(st)[lord]["buy"]
    assert offer["price"] == 2 and c in offer["cards"]
    G.act(st, lord, {"type": "buy", "cards": [c]})
    assert st.vars["money"][lord] == 8 and st.vars["money"][farmer] == 12
    # 点炮 costs the discarder nothing in this mode
    st.zone(f"hand:{farmer}").cards[:] = []
    for i in range(3):
        for x in list(st.zone(f"hand:{i}").cards):
            st.move(x, "deck")
    st.move(card_of(st, "天津"), f"hand:{farmer}")
    st.move(c, "deck")
    st.move(c, f"hand:{lord}")
    st.vars["phase"] = "tour"
    st.vars["tour"] = {"by": (lord + 2) % 3, "order": [lord, farmer], "idx": 0}
    G.act(st, lord, {"type": "tour", "card": c})
    claim = G.prompts(st)[farmer]["claims"][0]
    opts = claim["options"]
    assert opts[0]["pattern"] == "pair:北京天津" and opts[0]["cost"] == 0
    G.act(st, farmer, {"type": "dianpao", "offer": claim["offer"], "choices": [0]})
    assert st.vars["money"][lord] == 8 and st.vars["money"][farmer] == 16


def test_landlord_mode_needs_three_players():
    with pytest.raises(ValueError):
        G.new_state(4, {"mode": "landlord"}, seed=0)


def test_landlord_ai_games():
    for seed in range(5):
        st = play_ai(G.new_state(3, {"mode": "landlord"}, seed=seed))
        assert st.vars["landlord"] is not None and st.vars["winners"]
        assert sum(len(z.cards) for z in st.zones.values()) == 108


def test_china_map_matches_game_data():
    from pathlib import Path

    from cardgame.games.city.data import CITIES

    path = Path(__file__).resolve().parent.parent / "cardgame" / "static" / "data" / "china_map.json"
    m = json.loads(path.read_text(encoding="utf-8"))
    assert set(m["cities"]) == set(CITIES)
    assert {"main", "yrd", "prd", "locator"} <= set(m["views"])
    games = {p["game"] for p in m["provinces"] if p["game"]}
    assert games == {"直辖市", "江苏", "湖北", "四川", "广东"}
    assert m["yangtze"] and m["dashes"] and set(m["railways"]) == {"jinghu", "chengxiang"}
    # every city lies inside the main view
    x, y, w, h = m["views"]["main"]
    assert all(x < cx < x + w and y < cy < y + h for cx, cy in m["cities"].values())


def test_migrate_state_from_blocking_dianpao_version():
    st = setup(hands={0: ["北京"], 1: ["天津"]})
    d = st.to_dict()
    # what the previous version saved: no offers, a blocking 点炮 phase
    del d["vars"]["offers"], d["vars"]["next_offer"]
    d["vars"]["phase"] = "dianpao"
    d["vars"]["pending"] = {"by": 0, "cards": [], "eligible": [1], "resume": "main"}
    d["private"][1]["dianpao_choice"] = []
    old = G.migrate(GameState.from_dict(d))
    assert old.vars["phase"] == "main" and old.vars["offers"] == [] and "pending" not in old.vars
    assert G.prompts(old)[0]["type"] == "main"


def discard_state(clock, think_time=30):
    """Seat 0 has just discarded 北京, which seat 1 can 点炮; the clock stands still."""
    st = setup(hands={0: ["北京"], 1: ["北京", "北京", "北京"], 2: ["上海"]}, options={"think_time": think_time})
    st.vars["phase"] = "draw"
    st.private[0]["drawn"] = list(st.zone("hand:0").cards)
    clock.step = 0
    G.act(st, 0, {"type": "discard", "card": st.zone("hand:0").cards[0]})
    return st


def test_only_dianpao_in_the_seconds_after_a_discard(clock):
    st = discard_state(clock)
    with pytest.raises(IllegalAction, match="等待点炮"):
        G.act(st, 0, {"type": "end"})
    clock.t += rules.DISCARD_WAIT - 0.5
    with pytest.raises(IllegalAction):
        G.act(st, 0, {"type": "end"})
    assert G.ai_wait(st, 0, G.prompts(st)[0]) == pytest.approx(0.5)
    assert G.ai_wait(st, 1, G.prompts(st)[1]) == 0          # 点炮 is never held up
    clock.t += 1
    G.act(st, 0, {"type": "end"})
    assert st.vars["turn"] == 1


def test_think_holds_the_others_until_the_thinker_is_done(clock):
    st = discard_state(clock)
    # seat 2 cannot 点炮 but may 长考 all the same, and only once per discard
    assert G.view(st, 2)["hold"]["can_think"] and not G.view(st, 0)["hold"]["can_think"]
    G.act(st, 2, {"type": "think"})
    with pytest.raises(IllegalAction):
        G.act(st, 2, {"type": "think"})
    with pytest.raises(IllegalAction):
        G.act(st, 1, {"type": "think"})                      # one 长考 at a time
    clock.t += 20
    with pytest.raises(IllegalAction, match="长考中"):
        G.act(st, 0, {"type": "end"})
    assert G.view(st, 0)["hold"]["think"] == {"seat": 2, "left": pytest.approx(10)}
    G.act(st, 2, {"type": "think_end"})
    G.act(st, 1, {"type": "think"})                          # now seat 1 may
    claim = G.prompts(st)[1]["claims"][0]
    G.act(st, 1, {"type": "dianpao", "offer": claim["offer"], "choices": [0]})  # ends the 长考
    G.act(st, 0, {"type": "end"})


def test_think_runs_out_and_lapses_with_the_turn(clock):
    st = discard_state(clock)
    G.act(st, 1, {"type": "think"})
    clock.t += 30.1
    assert G.view(st, 0)["hold"]["think"] is None
    G.act(st, 0, {"type": "end"})
    with pytest.raises(IllegalAction):
        G.act(st, 2, {"type": "think"})                      # the discard can no longer be claimed


def test_who_can_dianpao_is_not_shown(clock):
    st = discard_state(clock)
    assert G.prompts(st).keys() == {0, 1}
    assert G.waiting(st, G.prompts(st)) == [0]
    assert st.vars["offers"] and "offers" not in G.view(st, 2)["vars"]


def test_dianpao_again_with_the_same_card_until_declined():
    # one 成都 completes 成都重庆 with each of three 重庆
    st = setup(hands={0: ["成都"], 1: ["重庆", "重庆", "重庆"]})
    st.vars["phase"] = "draw"
    st.private[0]["drawn"] = list(st.zone("hand:0").cards)
    G.act(st, 0, {"type": "discard", "card": st.zone("hand:0").cards[0]})
    for k in range(2):
        claim = G.prompts(st)[1]["claims"][0]
        assert [o["pattern"] for o in claim["options"]] == ["pair:成都重庆"]
        G.act(st, 1, {"type": "dianpao", "offer": claim["offer"], "choices": [0]})
    assert cities(st, "hand:1") == ["重庆"] and st.vars["money"][1] == 2 * 4
    claim = G.prompts(st)[1]["claims"][0]
    G.act(st, 1, {"type": "dianpao", "offer": claim["offer"], "choices": []})   # 不点炮
    assert 1 not in G.prompts(st) and st.vars["offers"] == []


def test_dianpao_offer_closes_when_nothing_is_left_to_claim():
    st = setup(hands={0: ["成都"], 1: ["重庆"]})
    st.vars["phase"] = "draw"
    st.private[0]["drawn"] = list(st.zone("hand:0").cards)
    G.act(st, 0, {"type": "discard", "card": st.zone("hand:0").cards[0]})
    claim = G.prompts(st)[1]["claims"][0]
    G.act(st, 1, {"type": "dianpao", "offer": claim["offer"], "choices": [0]})
    assert 1 not in G.prompts(st) and st.vars["offers"] == []


def test_played_cards_stay_on_the_table_until_the_next_turn():
    st = setup(hands={0: ["北京", "成都", "重庆"], 1: ["天津"]})
    beijing, chengdu, chongqing = st.zone("hand:0").cards
    st.vars["phase"] = "draw"
    st.private[0]["drawn"] = [beijing]
    G.act(st, 0, {"type": "discard", "card": beijing})
    claim = G.prompts(st)[1]["claims"][0]
    G.act(st, 1, {"type": "dianpao", "offer": claim["offer"], "choices": [0]})
    G.act(st, 0, {"type": "cash", "pattern": "pair:成都重庆"})
    v = st.vars
    assert v["played"][0] == [{"type": "discard", "cards": [beijing]},
                              {"type": "cash", "cards": [chengdu, chongqing], "pattern": "pair:成都重庆"}]
    assert v["played"][1] == [{"type": "dianpao", "cards": st.zone("discard:1").cards, "card": beijing,
                               "from": 0, "pattern": "pair:北京天津"}]
    assert [(e["type"], e["money"]) for e in v["events"]] == [("dianpao", [[1, 4], [0, -2]]), ("cash", [[0, 6]])]
    G.act(st, 0, {"type": "end"})
    # a new turn: its events start afresh, the new player's cards leave the table
    assert v["events"] == [] and v["played"][1] == [] and len(v["played"][0]) == 2
    for seat in (1, 2):
        G.act(st, seat, {"type": "discard", "card": st.private[seat]["drawn"][0]})
        decline_offers(st)
        G.act(st, seat, {"type": "end"})
    assert v["turn"] == 0 and v["played"][0] == [] and len(v["played"][1]) == 1


def test_think_lasts_while_the_thinker_can_still_dianpao(clock):
    st = setup(hands={0: ["成都"], 1: ["重庆", "重庆"]})
    st.vars["phase"] = "draw"
    st.private[0]["drawn"] = list(st.zone("hand:0").cards)
    clock.step = 0
    G.act(st, 0, {"type": "discard", "card": st.zone("hand:0").cards[0]})
    G.act(st, 1, {"type": "think"})
    claim = G.prompts(st)[1]["claims"][0]
    G.act(st, 1, {"type": "dianpao", "offer": claim["offer"], "choices": [0]})
    assert G.view(st, 0)["hold"]["think"]["seat"] == 1     # may 点炮 again: still thinking
    clock.t += rules.DISCARD_WAIT
    with pytest.raises(IllegalAction, match="长考中"):
        G.act(st, 0, {"type": "end"})
    G.act(st, 1, {"type": "dianpao", "offer": claim["offer"], "choices": []})   # 不点炮
    assert G.view(st, 0)["hold"]["think"] is None
    G.act(st, 0, {"type": "end"})


def test_think_without_time_limit_by_default(clock):
    st = discard_state(clock, think_time=0)
    assert G.view(st, 2)["hold"]["think_time"] == 0
    G.act(st, 2, {"type": "think"})
    clock.t += 3600
    assert G.view(st, 0)["hold"]["think"] == {"seat": 2, "left": None}
    assert G.blocked_for(st, 0) == float("inf")
    with pytest.raises(IllegalAction, match="等 TA 结束"):
        G.act(st, 0, {"type": "end"})
    G.ai_takes_over(st, 2)                    # an AI never ends it, so it ends here
    G.act(st, 0, {"type": "end"})
