"""Game-independent state: cards, zones, visibility, rng, log.

Everything in a GameState is JSON-serialisable through ``to_dict`` /
``from_dict``.  The server keeps the omniscient state; clients only ever see
the output of ``view(seat)``, where cards a seat cannot see are masked.
"""
from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field
from typing import Any, Iterable

# Zone visibility
PUBLIC = "public"   # everybody sees the cards
OWNER = "owner"     # only the owner sees the cards, others see the count
HIDDEN = "hidden"   # nobody sees the cards (e.g. the draw pile)
VISIBILITIES = (PUBLIC, OWNER, HIDDEN)

FORMAT_VERSION = 1


class IllegalAction(Exception):
    """Raised by a rules module when an action is not allowed."""


@dataclass
class Zone:
    name: str
    owner: int | None = None
    visibility: str = PUBLIC
    cards: list[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"owner": self.owner, "visibility": self.visibility, "cards": list(self.cards)}

    @classmethod
    def from_dict(cls, name: str, d: dict) -> "Zone":
        return cls(name, d.get("owner"), d.get("visibility", PUBLIC), list(d.get("cards", [])))


class GameState:
    """Container for a game's complete state.

    * ``cards``   – static attributes of every card, keyed by card id.
    * ``zones``   – ordered card lists with owner and visibility.
    * ``props``   – per-card dynamic properties (face down, used, ...),
                    shown together with the card when it is visible.
    * ``known``   – per-card extra knowledge: seats that have seen a card
                    even though its zone would hide it (e.g. passed cards).
    * ``vars``    – public game variables (phase, turn, scores, ...).
    * ``private`` – one dict per seat, only visible to that seat.
    * ``log``     – messages, optionally restricted to some seats.
    """

    def __init__(self, game: str, num_players: int, options: dict | None = None, seed: int | None = None):
        self.game = game
        self.num_players = num_players
        self.options: dict = dict(options or {})
        self.cards: dict[int, dict] = {}
        self.zones: dict[str, Zone] = {}
        self.props: dict[int, dict] = {}
        self.known: dict[int, set[int]] = {}
        self.vars: dict[str, Any] = {}
        self.private: list[dict] = [{} for _ in range(num_players)]
        self.log_entries: list[dict] = []
        self.seq = 0
        self.rng = random.Random(seed)
        self._loc: dict[int, str] = {}

    # ----------------------------------------------------------- cards/zones
    def add_card(self, attrs: dict, zone: str) -> int:
        cid = len(self.cards)
        self.cards[cid] = dict(attrs)
        self.zones[zone].cards.append(cid)
        self._loc[cid] = zone
        return cid

    def add_zone(self, name: str, owner: int | None = None, visibility: str = PUBLIC) -> Zone:
        if visibility not in VISIBILITIES:
            raise ValueError(f"bad visibility {visibility!r}")
        if name in self.zones:
            raise ValueError(f"zone {name!r} exists")
        z = self.zones[name] = Zone(name, owner, visibility)
        return z

    def zone(self, name: str) -> Zone:
        return self.zones[name]

    def where(self, card: int) -> str:
        return self._loc[card]

    def move(self, card: int, dst: str, index: int | None = None) -> None:
        src = self._loc[card]
        self.zones[src].cards.remove(card)
        cards = self.zones[dst].cards
        if index is None:
            cards.append(card)
        else:
            cards.insert(index, card)
        self._loc[card] = dst

    def move_all(self, src: str, dst: str) -> None:
        for c in list(self.zones[src].cards):
            self.move(c, dst)

    def draw(self, src: str, dst: str, n: int = 1) -> list[int]:
        """Move the top ``n`` cards (end of list) of ``src`` to ``dst``."""
        drawn = []
        for _ in range(min(n, len(self.zones[src].cards))):
            c = self.zones[src].cards[-1]
            self.move(c, dst)
            drawn.append(c)
        return drawn

    def shuffle(self, name: str) -> None:
        z = self.zones[name]
        self.rng.shuffle(z.cards)
        for c in z.cards:
            self.known.pop(c, None)

    def reveal(self, card: int, seats: Iterable[int]) -> None:
        self.known.setdefault(card, set()).update(seats)

    def forget(self, card: int) -> None:
        self.known.pop(card, None)

    def attr(self, card: int, key: str) -> Any:
        return self.cards[card][key]

    def set_prop(self, card: int, key: str, value: Any) -> None:
        if value is None:
            self.props.get(card, {}).pop(key, None)
            if not self.props.get(card):
                self.props.pop(card, None)
        else:
            self.props.setdefault(card, {})[key] = value

    def prop(self, card: int, key: str, default: Any = None) -> Any:
        return self.props.get(card, {}).get(key, default)

    # ------------------------------------------------------------- visibility
    def visible_to(self, card: int, seat: int | None) -> bool:
        z = self.zones[self._loc[card]]
        if z.visibility == PUBLIC:
            return True
        if seat is None:
            return False
        if z.visibility == OWNER and z.owner == seat:
            return True
        return seat in self.known.get(card, ())

    def log(self, msg: str, to: Iterable[int] | None = None, **data) -> None:
        entry = {"seq": self.seq, "msg": msg}
        if to is not None:
            entry["to"] = sorted(set(to))
        if data:
            entry["data"] = data
        self.log_entries.append(entry)

    def view(self, seat: int | None) -> dict:
        """The state as seen by ``seat`` (None = spectator)."""
        zones = {}
        visible: set[int] = set()
        for name, z in self.zones.items():
            ids = []
            for c in z.cards:
                if self.visible_to(c, seat):
                    ids.append(c)
                    visible.add(c)
                else:
                    ids.append(None)
            zones[name] = {"owner": z.owner, "visibility": z.visibility, "cards": ids}
        return {
            "game": self.game,
            "num_players": self.num_players,
            "seat": seat,
            "seq": self.seq,
            "options": copy.deepcopy(self.options),
            "cards": {c: {**self.cards[c], **self.props.get(c, {})} for c in sorted(visible)},
            "zones": zones,
            "vars": copy.deepcopy(self.vars),
            "private": copy.deepcopy(self.private[seat]) if seat is not None else {},
            "log": [e for e in self.log_entries[-200:] if "to" not in e or (seat is not None and seat in e["to"])],
        }

    # ---------------------------------------------------------- serialisation
    def to_dict(self) -> dict:
        version, internal, gauss = self.rng.getstate()
        return {
            "format": FORMAT_VERSION,
            "game": self.game,
            "num_players": self.num_players,
            "options": copy.deepcopy(self.options),
            "seq": self.seq,
            "cards": {str(c): dict(a) for c, a in self.cards.items()},
            "zones": {n: z.to_dict() for n, z in self.zones.items()},
            "props": {str(c): dict(p) for c, p in self.props.items() if p},
            "known": {str(c): sorted(s) for c, s in self.known.items() if s},
            "vars": copy.deepcopy(self.vars),
            "private": copy.deepcopy(self.private),
            "log": copy.deepcopy(self.log_entries),
            "rng": [version, list(internal), gauss],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "GameState":
        if d.get("format") != FORMAT_VERSION:
            raise ValueError(f"unsupported state format {d.get('format')!r}")
        st = cls(d["game"], d["num_players"], d.get("options"))
        st.seq = d.get("seq", 0)
        st.cards = {int(c): dict(a) for c, a in d["cards"].items()}
        st.zones = {n: Zone.from_dict(n, z) for n, z in d["zones"].items()}
        st.props = {int(c): dict(p) for c, p in d.get("props", {}).items()}
        st.known = {int(c): set(s) for c, s in d.get("known", {}).items()}
        st.vars = copy.deepcopy(d.get("vars", {}))
        st.private = copy.deepcopy(d.get("private")) or [{} for _ in range(st.num_players)]
        st.log_entries = copy.deepcopy(d.get("log", []))
        version, internal, gauss = d["rng"]
        st.rng.setstate((version, tuple(internal), gauss))
        st._loc = {}
        for n, z in st.zones.items():
            for c in z.cards:
                if c in st._loc:
                    raise ValueError(f"card {c} appears in two zones")
                st._loc[c] = n
        if set(st._loc) != set(st.cards):
            raise ValueError("every card must be in exactly one zone")
        if len(st.private) != st.num_players:
            raise ValueError("private must have one entry per seat")
        return st

    def copy(self) -> "GameState":
        return GameState.from_dict(self.to_dict())
