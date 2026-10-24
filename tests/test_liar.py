import random

import pytest

from cardgame.engine import IllegalAction
from cardgame.games.liar import Liar
from cardgame.games.liar.ai import LiarAI

G = Liar()


def setup(n=3, hands=None, turn=0, options=None):
    """A state at the start of a round with chosen hands, e.g. {0: [7, 7, "joker"]};
    every other card goes to the discard pile."""
    st = G.new_state(n, options, seed=1)
    for i in range(n):
        st.move_all(f"hand:{i}", "deck")
    for i, ranks in (hands or {}).items():
        for r in ranks:
            c = next(c for c in st.zone("deck").cards
                     if (st.cards[c].get("joker") if r == "joker" else st.cards[c].get("rank") == r))
            st.move(c, f"hand:{i}")
    st.move_all("deck", "discard")
    st.vars.update(phase="lead", turn=turn, x=None, passed=[False] * n, claims=[], out=[])
    return st


def hand(st, seat):
    return list(st.zone(f"hand:{seat}").cards)


def ranks(st, seat):
    """Ranks in a hand, jokers as 99."""
    return sorted((99 if st.cards[c].get("joker") else st.cards[c]["rank"] for c in hand(st, seat)))


def test_deal_is_even_and_uses_every_card():
    st = G.new_state(5, {"decks": 2, "jokers": 1}, seed=3)
    sizes = [len(hand(st, i)) for i in range(5)]
    assert sum(sizes) == 2 * 53 and max(sizes) - min(sizes) <= 1
    assert sum(1 for a in st.cards.values() if a.get("joker")) == 2


def test_lead_must_play_and_others_only_see_the_count():
    st = setup(hands={0: [7, 7, 9], 1: [5], 2: [5]})
    assert G.prompts(st) == {0: {"type": "lead", "min": 1}}
    with pytest.raises(IllegalAction):
        G.act(st, 0, {"type": "pass"})
    played = [c for c in hand(st, 0) if st.cards[c]["rank"] == 7]
    G.act(st, 0, {"type": "lead", "x": 7, "cards": played})
    assert st.vars["x"] == 7 and st.vars["turn"] == 1
    assert sorted(G.view(st, 0)["zones"]["claim"]["cards"]) == sorted(played)
    assert G.view(st, 1)["zones"]["claim"]["cards"] == [None, None]
    p = G.prompts(st)[1]
    assert p["type"] == "play" and p["challenge"] == {"seat": 0, "count": 2, "reveal": 2}


def test_true_claim_challenged_challenger_takes_everything():
    st = setup(hands={0: [7, "joker", 9], 1: [5, 6], 2: [5]})
    G.act(st, 0, {"type": "lead", "x": 7, "cards": [c for c in hand(st, 0) if st.cards[c].get("rank") != 9]})
    G.act(st, 1, {"type": "challenge"})
    assert ranks(st, 1) == [5, 6, 7, 99]
    assert st.vars["last_result"]["truthful"] is True
    # the turned cards are known to all; the claimer won and leads again
    assert all(c in G.view(st, 2)["zones"]["hand:1"]["cards"] for c in st.vars["last_result"]["shown"])
    assert st.vars["phase"] == "lead" and st.vars["turn"] == 0 and st.vars["round_no"] == 2


def test_lie_challenged_claimer_takes_back_the_round():
    st = setup(hands={0: [7, 9], 1: [7, 6], 2: [5, 5]})
    G.act(st, 0, {"type": "lead", "x": 7, "cards": [c for c in hand(st, 0) if st.cards[c]["rank"] == 7]})
    G.act(st, 1, {"type": "play", "cards": [c for c in hand(st, 1) if st.cards[c]["rank"] == 6]})
    G.act(st, 2, {"type": "challenge"})
    # seat 1 takes back its card and seat 0's 7 as well
    assert ranks(st, 1) == [6, 7, 7] and st.vars["last_result"]["truthful"] is False
    assert st.vars["turn"] == 2 and st.vars["phase"] == "lead"


def test_partial_check_flips_the_picked_cards():
    st = setup(hands={0: [7, 7, 9, 9, 9], 1: [5], 2: [5]}, options={"reveal": "third"})
    G.act(st, 0, {"type": "lead", "x": 7, "cards": hand(st, 0)[:4]})
    assert G.prompts(st)[1]["challenge"]["reveal"] == 2
    for bad in (None, [0], [0, 0], [0, 4], [True, 1]):
        with pytest.raises(IllegalAction):
            G.act(st, 1, {"type": "challenge", "picks": bad})
    claim = list(st.zone("claim").cards)
    G.act(st, 1, {"type": "challenge", "picks": [3, 1]})
    assert st.vars["last_result"]["shown"] == [claim[1], claim[3]]
    truthful = all(st.cards[c]["rank"] == 7 for c in (claim[1], claim[3]))
    assert st.vars["last_result"]["truthful"] is truthful


def test_all_pass_discards_the_table_and_the_last_player_wins():
    st = setup(hands={0: [7, 7, 8], 1: [5], 2: [5]})
    G.act(st, 0, {"type": "lead", "x": 7, "cards": hand(st, 0)[:2]})
    G.act(st, 1, {"type": "pass"})
    assert G.prompts(st)[2]["type"] == "play"
    G.act(st, 2, {"type": "pass"})
    assert ranks(st, 0) == [8] and not st.zone("claim").cards and not st.zone("table").cards
    assert st.vars["phase"] == "lead" and st.vars["turn"] == 0


def test_passed_players_are_skipped_and_cannot_challenge():
    st = setup(hands={0: [7, 8], 1: [5, 5], 2: [5, 6]})
    G.act(st, 0, {"type": "lead", "x": 7, "cards": hand(st, 0)[:1]})
    G.act(st, 1, {"type": "pass"})
    G.act(st, 2, {"type": "play", "cards": hand(st, 2)[:1]})
    assert G.prompts(st) == {0: G.prompts(st)[0]}      # seat 1 is skipped
    with pytest.raises(IllegalAction):
        G.act(st, 1, {"type": "challenge"})


def test_going_out_waits_until_the_claim_cannot_be_challenged():
    st = setup(hands={0: [7], 1: [5, 5], 2: [5, 6]})
    G.act(st, 0, {"type": "lead", "x": 7, "cards": hand(st, 0)})
    assert st.vars["out"] == []                         # can still be challenged
    G.act(st, 1, {"type": "play", "cards": hand(st, 1)[:1]})
    assert st.vars["out"] == [0]                        # a newer claim: out, first place
    # a caught lie on the last cards brings the player back
    st = setup(hands={0: [9], 1: [5, 5], 2: [5, 6]})
    G.act(st, 0, {"type": "lead", "x": 7, "cards": hand(st, 0)})
    G.act(st, 1, {"type": "challenge"})
    assert st.vars["out"] == [] and ranks(st, 0) == [9]


def test_round_ends_when_a_play_leaves_nobody_to_answer():
    # B empties their hand, A answers with their last card: B is out and A is
    # alone in the round, so it ends at once instead of waiting for A
    st = setup(n=2, hands={0: [5], 1: [7]}, turn=1)
    G.act(st, 1, {"type": "lead", "x": 7, "cards": hand(st, 1)})
    G.act(st, 0, {"type": "play", "cards": hand(st, 0)})
    assert st.vars["phase"] == "over" and st.vars["out"] == [1, 0] and st.vars["winners"] == [1]


def test_min_play_option():
    st = setup(hands={0: [7, 7, 9], 1: [5], 2: [5, 6]}, options={"min_play": 2})
    with pytest.raises(IllegalAction):
        G.act(st, 0, {"type": "lead", "x": 7, "cards": hand(st, 0)[:1]})
    G.act(st, 0, {"type": "lead", "x": 7, "cards": hand(st, 0)[:2]})
    assert G.prompts(st)[1]["can_play"] is False        # one card: pass or challenge only


@pytest.mark.parametrize("seed", range(30))
def test_ai_games_finish(seed):
    n = 2 + seed % 7
    opts = {"reveal": "third" if seed % 2 else "all", "decks": 1 + seed % 2,
            "min_play": 1 + (seed % 5 == 0), "jokers": seed % 3}
    st = G.new_state(n, opts, seed=seed)
    ais = [LiarAI(random.Random(seed * 10 + i)) for i in range(n)]
    for _ in range(3000):
        if G.is_over(st):
            break
        (seat, prompt), = G.prompts(st).items()
        G.act(st, seat, ais[seat].choose(G.view(st, seat), prompt))
    assert G.is_over(st) and sorted(st.vars["out"]) == list(range(n))
    assert sum(len(z.cards) for z in st.zones.values()) == len(st.cards)
