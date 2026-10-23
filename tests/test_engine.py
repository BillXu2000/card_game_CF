import json

import pytest

from cardgame.engine import GameState, IllegalAction
from tests.duel import Duel


def test_view_masks_hidden_cards():
    g = Duel()
    st = g.new_state(2, seed=1)
    v0 = g.view(st, 0)
    own = st.zone("hand:0").cards
    other = st.zone("hand:1").cards
    assert v0["zones"]["hand:0"]["cards"] == own
    assert v0["zones"]["hand:1"]["cards"] == [None] * 3
    assert v0["zones"]["deck"]["cards"] == [None] * 0 or all(c is None for c in v0["zones"]["deck"]["cards"])
    assert set(v0["cards"]) == set(own)
    # nothing about the opponent's cards leaks anywhere in the serialised view
    text = json.dumps(v0)
    for c in other:
        assert f'"{c}"' not in text
    spectator = g.view(st, None)
    assert spectator["cards"] == {}


def test_simultaneous_prompts_and_known_cards():
    g = Duel()
    st = g.new_state(2, seed=2)
    assert set(g.prompts(st)) == {0, 1}
    c0 = st.zone("hand:0").cards[0]
    g.act(st, 0, {"type": "choose", "card": c0})
    assert set(g.prompts(st)) == {1}
    assert g.view(st, 1)["zones"]["chosen:0"]["cards"] == [None]
    with pytest.raises(IllegalAction):
        g.act(st, 0, {"type": "choose", "card": st.zone("hand:0").cards[0]})
    st.reveal(c0, [1])
    assert g.view(st, 1)["zones"]["chosen:0"]["cards"] == [c0]


def test_roundtrip_and_determinism():
    g = Duel()
    st = g.new_state(2, seed=3)
    st.set_prop(0, "face_down", True)
    st.reveal(st.zone("hand:1").cards[0], [0])
    d = st.to_dict()
    copy = GameState.from_dict(json.loads(json.dumps(d)))
    assert copy.to_dict() == d
    # rng state survives the round-trip
    assert copy.rng.random() == st.rng.random()


def test_full_game_with_ai():
    g = Duel()
    st = g.new_state(2, seed=4)
    ai = g.make_ai()
    while not g.is_over(st):
        for seat, prompt in g.prompts(st).items():
            g.act(st, seat, ai.choose(g.view(st, seat), prompt))
    assert sum(st.vars["scores"]) == 3
    assert g.prompts(st) == {}


def test_from_dict_rejects_inconsistent_state():
    g = Duel()
    d = g.new_state(2, seed=5).to_dict()
    d["zones"]["hand:0"]["cards"].append(d["zones"]["hand:1"]["cards"][0])
    with pytest.raises(ValueError):
        GameState.from_dict(d)
