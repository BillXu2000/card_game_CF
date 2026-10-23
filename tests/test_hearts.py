import json
import random

import pytest

from cardgame.engine import GameState, IllegalAction
from cardgame.games.hearts.rules import (
    QUEEN_SPADES, TWO_CLUBS, Hearts, card_id, legal_plays, points_of, rank_of, suit_of, trick_winner,
)

G = Hearts()
C = card_id


def random_action(st, seat, prompt, rng):
    if prompt["type"] == "pass":
        return {"type": "pass", "cards": rng.sample(st.zone(f"hand:{seat}").cards, 3)}
    if prompt["type"] == "play":
        return {"type": "play", "card": rng.choice(prompt["legal"])}
    return {"type": "continue"}


def play_random(seed, until=None):
    rng = random.Random(seed)
    st = G.new_state(4, seed=seed)
    while not G.is_over(st):
        if until and until(st):
            break
        prompts = G.prompts(st)
        seat = rng.choice(sorted(prompts))
        G.act(st, seat, random_action(st, seat, prompts[seat], rng))
    return st


def test_deal_and_pass_directions():
    st = G.new_state(4, seed=1)
    assert all(len(st.zone(f"hand:{i}").cards) == 13 for i in range(4))
    assert st.vars["phase"] == "pass" and st.vars["pass_dir"] == "left"
    prompts = G.prompts(st)
    assert {s: p["to"] for s, p in prompts.items()} == {0: 1, 1: 2, 2: 3, 3: 0}


def test_pass_moves_cards_and_keeps_them_known():
    st = G.new_state(4, seed=2)
    passed = {i: st.zone(f"hand:{i}").cards[:3] for i in range(4)}
    for i in range(4):
        G.act(st, i, {"type": "pass", "cards": passed[i]})
    for i in range(4):
        hand = st.zone(f"hand:{(i + 1) % 4}").cards
        assert all(c in hand for c in passed[i])
        # passer still sees the cards it gave away, nobody else does
        v = G.view(st, i)["zones"][f"hand:{(i + 1) % 4}"]["cards"]
        assert sorted(c for c in v if c is not None) == sorted(passed[i])
        v_other = G.view(st, (i + 2) % 4)["zones"][f"hand:{(i + 1) % 4}"]["cards"]
        assert all(c is None for c in v_other)
    assert st.vars["phase"] == "play"
    assert TWO_CLUBS in st.zone(f"hand:{st.vars['turn']}").cards


def test_bad_pass_rejected():
    st = G.new_state(4, seed=3)
    other = st.zone("hand:1").cards[0]
    with pytest.raises(IllegalAction):
        G.act(st, 0, {"type": "pass", "cards": st.zone("hand:0").cards[:2] + [other]})
    with pytest.raises(IllegalAction):
        G.act(st, 0, {"type": "pass", "cards": [st.zone("hand:0").cards[0]] * 3})
    with pytest.raises(IllegalAction):
        G.act(st, 0, {"type": "play", "card": st.zone("hand:0").cards[0]})


def test_legal_first_trick():
    hand = [TWO_CLUBS, C("C", 9), C("H", 5)]
    assert legal_plays(hand, [], 0, False) == [TWO_CLUBS]
    # void in clubs on first trick: no hearts, no Q♠
    hand = [C("H", 3), QUEEN_SPADES, C("D", 4)]
    assert legal_plays(hand, [TWO_CLUBS], 0, False) == [C("D", 4)]
    # only points: hearts allowed but not Q♠
    hand = [C("H", 3), QUEEN_SPADES]
    assert legal_plays(hand, [TWO_CLUBS], 0, False) == [C("H", 3)]
    hand = [C("H", 3), C("H", 9)]
    assert legal_plays(hand, [TWO_CLUBS], 0, False) == hand
    # Q♠ is fine after the first trick
    hand = [QUEEN_SPADES, C("D", 4)]
    assert legal_plays(hand, [C("C", 5)], 1, False) == hand


def test_legal_leads_and_follow():
    hand = [C("H", 3), C("S", 4), QUEEN_SPADES]
    assert legal_plays(hand, [], 3, False) == [C("S", 4), QUEEN_SPADES]
    assert legal_plays(hand, [], 3, True) == hand
    assert legal_plays([C("H", 3), C("H", 8)], [], 3, False) == [C("H", 3), C("H", 8)]
    assert legal_plays(hand, [C("S", 9)], 3, False) == [C("S", 4), QUEEN_SPADES]
    assert legal_plays(hand, [C("D", 9)], 3, False) == hand


def test_trick_winner():
    trick = [C("D", 5), C("D", 13), C("S", 14), C("D", 2)]
    assert trick_winner(trick, [2, 3, 0, 1]) == 3


def arrange(hands, trick_no=1, turn=0):
    """A play-phase state where seat i holds ``hands[i]`` (padded with minor-suit cards)."""
    st = G.new_state(4, seed=0)
    for i in range(4):
        st.move_all(f"hand:{i}", "deck")
    for i, cards in hands.items():
        for c in cards:
            st.move(c, f"hand:{i}")
    for i in range(4):
        while len(st.zone(f"hand:{i}").cards) < 4:
            spare = next(c for c in st.zone("deck").cards if suit_of(c) in "CD")
            st.move(spare, f"hand:{i}")
    st.vars.update(phase="play", trick_no=trick_no, turn=turn, leader=turn)
    return st


def test_queen_does_not_break_hearts():
    st = arrange({0: [QUEEN_SPADES], 1: [C("S", 3)], 2: [C("S", 4)], 3: [C("H", 5), C("D", 2)]})
    G.act(st, 0, {"type": "play", "card": QUEEN_SPADES})
    assert st.vars["hearts_broken"] is False
    G.act(st, 1, {"type": "play", "card": C("S", 3)})
    G.act(st, 2, {"type": "play", "card": C("S", 4)})
    G.act(st, 3, {"type": "play", "card": C("D", 2)})  # void in spades: diamond
    assert st.vars["hearts_broken"] is False
    assert st.vars["points_taken"] == [13, 0, 0, 0] and st.vars["turn"] == 0


def test_heart_discard_breaks_hearts():
    st = arrange({0: [C("S", 9)], 1: [C("H", 5)]})
    G.act(st, 0, {"type": "play", "card": C("S", 9)})
    G.act(st, 1, {"type": "play", "card": C("H", 5)})
    assert st.vars["hearts_broken"] is True


def test_scoring_and_moon():
    st = G.new_state(4, seed=6)
    st.vars["phase"] = "play"
    st.vars["points_taken"] = [26, 0, 0, 0]
    st.vars["scores"] = [10, 20, 30, 40]
    G._end_hand(st)
    assert st.vars["scores"] == [10, 46, 56, 66]
    assert st.vars["last_hand"]["moon"] == 0
    st.vars["points_taken"] = [13, 5, 8, 0]
    G._end_hand(st)
    assert st.vars["scores"] == [23, 51, 64, 66]
    assert st.vars["phase"] == "score"


def test_random_games_are_consistent():
    for seed in range(30):
        st = play_random(seed)
        v = st.vars
        assert G.is_over(st)
        assert max(v["scores"]) >= 100
        assert v["winners"] == [i for i in range(4) if v["scores"][i] == min(v["scores"])]
        for pts in v["score_history"]:
            assert sum(pts) in (26, 78)
        assert sum(map(sum, v["score_history"])) == sum(v["scores"])


def test_hand_cycle_pass_directions():
    seen = []
    st = G.new_state(4, seed=7)
    rng = random.Random(7)
    while len(seen) < 5 and not G.is_over(st):
        if not seen or seen[-1][0] != st.vars["hand_no"]:
            seen.append((st.vars["hand_no"], st.vars["pass_dir"], st.vars["phase"]))
        prompts = G.prompts(st)
        seat = min(prompts)
        G.act(st, seat, random_action(st, seat, prompts[seat], rng))
    assert [d for _, d, _ in seen] == ["left", "right", "across", "hold", "left"][: len(seen)]
    assert all(p == ("play" if d == "hold" else "pass") for _, d, p in seen)


def test_points_of():
    assert points_of(QUEEN_SPADES) == 13
    assert points_of(C("H", 2)) == 1
    assert points_of(C("S", 13)) == 0
    assert sum(points_of(c) for c in range(52)) == 26
    assert suit_of(QUEEN_SPADES) == "S" and rank_of(QUEEN_SPADES) == 12


def test_state_json_roundtrip_mid_game():
    st = play_random(8, until=lambda s: s.vars["trick_no"] == 5)
    d = json.loads(json.dumps(st.to_dict()))
    st2 = GameState.from_dict(d)
    rng1, rng2 = random.Random(1), random.Random(1)
    while not G.is_over(st):
        p1, p2 = G.prompts(st), G.prompts(st2)
        assert p1 == p2
        seat = min(p1)
        G.act(st, seat, random_action(st, seat, p1[seat], rng1))
        G.act(st2, seat, random_action(st2, seat, p2[seat], rng2))
    assert st.to_dict() == st2.to_dict()
