"""A tiny two-player game used to exercise the engine and server.

Each player gets 3 cards from a hidden 6-card deck.  Every round both players
secretly choose a card at the same time; when both have chosen, the cards are
revealed and the higher one scores.  Three rounds.
"""
from cardgame.engine import AI, HIDDEN, OWNER, PUBLIC, Game, IllegalAction


class DuelAI(AI):
    def choose(self, view, prompt):
        return {"type": "choose", "card": min(prompt["legal"])}


class Duel(Game):
    id = "duel"
    name = "对决"
    min_players = max_players = 2
    ai_names = ("Alice", "Bob")

    def setup(self, st):
        st.add_zone("deck", visibility=HIDDEN)
        for i in range(2):
            st.add_zone(f"hand:{i}", owner=i, visibility=OWNER)
            st.add_zone(f"chosen:{i}", owner=i, visibility=OWNER)
            st.add_zone(f"won:{i}", owner=i, visibility=PUBLIC)
        for v in range(1, 7):
            st.add_card({"value": v}, "deck")
        st.shuffle("deck")
        for i in range(2):
            st.draw("deck", f"hand:{i}", 3)
        st.vars.update(round=0, scores=[0, 0])

    def prompts(self, st):
        if self.is_over(st):
            return {}
        return {i: {"type": "choose", "legal": list(st.zone(f"hand:{i}").cards)}
                for i in range(2) if not st.zone(f"chosen:{i}").cards}

    def apply(self, st, seat, action):
        card = action.get("card")
        if action["type"] != "choose" or card not in st.zone(f"hand:{seat}").cards:
            raise IllegalAction("不能出这张牌")
        st.move(card, f"chosen:{seat}")
        if all(st.zone(f"chosen:{i}").cards for i in range(2)):
            a, b = (st.zone(f"chosen:{i}").cards[0] for i in range(2))
            winner = 0 if st.attr(a, "value") > st.attr(b, "value") else 1
            st.vars["scores"][winner] += 1
            st.vars["round"] += 1
            for i in range(2):
                st.move_all(f"chosen:{i}", f"won:{winner}")
            st.log(f"第 {st.vars['round']} 轮：座位 {winner} 胜")

    def is_over(self, st):
        return st.vars["round"] >= 3

    def make_ai(self):
        return DuelAI()

    def ai_delay(self, st, prompt):
        return 0.0
