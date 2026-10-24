import json
import random

import pytest

from cardgame.engine import GameState, IllegalAction
from cardgame.games.city.data import PATTERN_BY_ID, PATTERNS
from cardgame.games.city.rules import CityExchange

G = CityExchange()


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
    assert st.zone(f"discard:{seat}").cards == [drawn[0]] or st.vars["phase"] == "dianpao"


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


def test_buyback_costs_10_and_needs_money():
    st = setup(hands={0: ["北京"]}, money=[5, 0, 0])
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
    assert st.vars["phase"] == "dianpao"
    prompts = G.prompts(st)
    assert set(prompts) == {1}
    names = [o["pattern"] for o in prompts[1]["options"]]
    both = [names.index("special:古来要塞"), names.index("special:泉岭大球")]
    G.act(st, 1, {"type": "dianpao", "choices": both})
    assert st.vars["money"][1] == 16 + 16 and st.vars["money"][0] == -16
    assert cities(st, "hand:1") == []
    assert cities(st, "discard:0") == ["广元"]
    assert st.vars["phase"] == "tour" and G.prompts(st) == {1: G.prompts(st)[1]}


def test_dianpao_incompatible_choices_rejected():
    st = setup(hands={1: ["北京", "北京", "北京"], 0: ["北京"]})
    st.vars["phase"] = "tour"
    st.vars["tour"] = {"by": 2, "order": [0, 1], "idx": 0}
    G.act(st, 0, {"type": "tour", "card": st.zone("hand:0").cards[0]})
    opts = G.prompts(st)[1]["options"]
    assert [o["pattern"] for o in opts] == ["four:北京"]
    with pytest.raises(IllegalAction):
        G.act(st, 1, {"type": "dianpao", "choices": [0, 0]})
    G.act(st, 1, {"type": "dianpao", "choices": []})
    assert st.vars["money"] == [0, 0, 0]


def test_tour_pays_fine_or_loops():
    st = setup(hands={1: ["北京"], 2: []})
    G.act(st, 0, {"type": "tour"})
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
    st = setup(hands={1: ["北京"], 2: ["上海"]}, options={"tour_loop": False})
    G.act(st, 0, {"type": "tour"})
    G.act(st, 1, {"type": "tour", "card": st.zone("hand:1").cards[0]})
    G.act(st, 2, {"type": "tour", "card": st.zone("hand:2").cards[0]})
    assert st.vars["phase"] == "main" and st.vars["money"] == [0, 0, 0]


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
