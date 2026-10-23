import random

from cardgame.games.hearts.ai import HeartsAI, choose_pass, moon_hand
from cardgame.games.hearts.rules import QUEEN_SPADES, Hearts, card_id

G = Hearts()
C = card_id


def arrange(hands, trick=(), trick_seats=(), trick_no=1, turn=0, broken=False):
    st = G.new_state(4, seed=0)
    for i in range(4):
        st.move_all(f"hand:{i}", "deck")
    for c in trick:
        st.move(c, "trick")
    for i, cards in hands.items():
        for c in cards:
            st.move(c, f"hand:{i}")
    st.vars.update(phase="play", trick_no=trick_no, turn=turn, leader=(trick_seats or [turn])[0],
                   trick_seats=list(trick_seats), tricks=[], hearts_broken=broken)
    return st


def ai_play(st, seat):
    prompt = G.prompts(st)[seat]
    return HeartsAI().choose(G.view(st, seat), prompt)["card"]


def test_pass_unprotected_queen_and_high_spades():
    hand = [QUEEN_SPADES, C("S", 14), C("S", 3), C("D", 4), C("D", 6), C("D", 9), C("C", 5),
            C("C", 7), C("C", 8), C("H", 2), C("H", 3), C("H", 4), C("C", 3)]
    passed = choose_pass(hand)
    assert QUEEN_SPADES in passed and C("S", 14) in passed


def test_pass_keeps_protected_queen():
    hand = [QUEEN_SPADES, C("S", 2), C("S", 3), C("S", 5), C("S", 7), C("D", 13), C("D", 14),
            C("H", 14), C("C", 5), C("C", 7), C("C", 8), C("H", 3), C("H", 4)]
    passed = choose_pass(hand)
    assert QUEEN_SPADES not in passed
    assert C("H", 14) in passed and C("D", 14) in passed


def test_dumps_queen_under_king():
    st = arrange({1: [QUEEN_SPADES, C("S", 2), C("D", 5)], 0: [C("D", 2)], 2: [C("D", 3)], 3: [C("D", 4)]},
                 trick=[C("S", 13)], trick_seats=[0], turn=1)
    assert ai_play(st, 1) == QUEEN_SPADES


def test_discards_queen_when_void():
    st = arrange({1: [QUEEN_SPADES, C("H", 13), C("D", 5)], 0: [C("C", 2)], 2: [C("C", 3)], 3: [C("C", 4)]},
                 trick=[C("C", 9)], trick_seats=[0], turn=1)
    assert ai_play(st, 1) == QUEEN_SPADES


def test_ducks_with_highest_lower_card():
    st = arrange({1: [C("D", 3), C("D", 8), C("D", 12)], 0: [C("C", 2)], 2: [C("C", 3)], 3: [C("C", 4)]},
                 trick=[C("D", 10)], trick_seats=[0], turn=1)
    assert ai_play(st, 1) == C("D", 8)


def test_leads_low_spade_to_smoke_out_queen():
    st = arrange({0: [C("S", 4), C("D", 14), C("C", 13)], 1: [QUEEN_SPADES], 2: [C("C", 3)], 3: [C("C", 4)]},
                 turn=0)
    assert ai_play(st, 0) == C("S", 4)


def test_moon_hand_detection():
    strong = [C("H", r) for r in (14, 13, 12, 11, 10, 9)] + [C("S", 14), C("S", 13), QUEEN_SPADES,
                                                               C("D", 14), C("C", 14), C("C", 13), C("D", 2)]
    assert moon_hand(strong)
    weak = [C("H", r) for r in (14, 13, 2)] + [C("C", r) for r in range(2, 12)]
    assert not moon_hand(weak)


def test_ai_games_always_legal():
    ai = HeartsAI()
    for seed in range(15):
        st = G.new_state(4, seed=seed)
        while not G.is_over(st):
            prompts = G.prompts(st)
            seat = min(prompts)
            G.act(st, seat, ai.choose(G.view(st, seat), prompts[seat]))  # raises on illegal moves


def test_ai_beats_random_players():
    rng = random.Random(1)
    ai = HeartsAI()
    total = [0] * 4
    for seed in range(20):
        st = G.new_state(4, seed=100 + seed)
        while not G.is_over(st):
            prompts = G.prompts(st)
            seat = min(prompts)
            p = prompts[seat]
            if seat == 0:
                action = ai.choose(G.view(st, seat), p)
            elif p["type"] == "pass":
                action = {"type": "pass", "cards": rng.sample(st.zone(f"hand:{seat}").cards, 3)}
            elif p["type"] == "play":
                action = {"type": "play", "card": rng.choice(p["legal"])}
            else:
                action = {"type": "continue"}
            G.act(st, seat, action)
        for i in range(4):
            total[i] += st.vars["scores"][i]
    assert total[0] * 2 < min(total[1:])
