"""Cities and Patterns of 城市交易所 (rule book v5.5-beta, sections 1.3 and 2)."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

MUNICIPAL = "直辖市"

# province -> cities; the first city of a real province is its capital
PROVINCES: dict[str, list[str]] = {
    MUNICIPAL: ["北京", "上海", "重庆", "天津"],
    "江苏": ["南京", "常州", "无锡", "苏州", "徐州"],
    "湖北": ["武汉", "宜昌", "襄阳", "十堰", "荆州"],
    "四川": ["成都", "广元", "绵阳", "攀枝花", "宜宾"],
    "广东": ["广州", "深圳", "汕头", "中山", "河源"],
}
CITIES: list[str] = [c for cs in PROVINCES.values() for c in cs]
PROVINCE_OF: dict[str, str] = {c: p for p, cs in PROVINCES.items() for c in cs}
CAPITALS: list[str] = [cs[0] for p, cs in PROVINCES.items() if p != MUNICIPAL]
COPIES = 4


@dataclass(frozen=True)
class Pattern:
    id: str
    name: str
    value: int
    need: tuple[tuple[str, int], ...]   # (city, count) pairs

    @property
    def counter(self) -> Counter:
        return Counter(dict(self.need))

    @property
    def size(self) -> int:
        return sum(n for _, n in self.need)

    def cities(self) -> list[str]:
        return [c for c, _ in self.need]


def _p(pid: str, name: str, value: int, cities: list[str]) -> Pattern:
    return Pattern(pid, name, value, tuple(sorted(Counter(cities).items(), key=lambda kv: CITIES.index(kv[0]))))


def _build() -> list[Pattern]:
    ps: list[Pattern] = []
    # 2.1 standard
    for c in CITIES:
        ps.append(_p(f"four:{c}", f"四个{c}", 3 * 12, [c] * 4))
    ps.append(_p("municipal", "四个直辖市", 3 * 8, PROVINCES[MUNICIPAL]))
    ps.append(_p("capitals", "四个省会", 3 * 8, CAPITALS))
    for p, cs in PROVINCES.items():
        if p != MUNICIPAL:
            ps.append(_p(f"province:{p}", f"{p}全省", 3 * 10, cs))
    # 2.2 special
    special = [
        ("苏锡常", 5, ["苏州", "无锡", "常州"]),
        ("北上广深", 8, ["北京", "上海", "广州", "深圳"]),
        ("四大火炉", 8, ["重庆", "武汉", "南京", "广州"]),
        ("沿海港口", 8, ["上海", "天津", "深圳", "汕头"]),
        ("新城风采", 8, ["深圳", "攀枝花", "汕头", "绵阳"]),
        ("古来要塞", 8, ["徐州", "荆州", "襄阳", "广元"]),
        ("泉岭大球", 8, ["十堰", "襄阳", "中山", "广元"]),
        ("成襄铁路", 10, ["成都", "绵阳", "广元", "十堰", "襄阳"]),
        ("远离中心", 10, ["攀枝花", "重庆", "十堰", "汕头", "徐州"]),
        ("京沪高铁", 17, ["北京", "天津", "徐州", "南京", "常州", "无锡", "苏州", "上海"]),
        ("长江之歌", 22, ["攀枝花", "宜宾", "重庆", "宜昌", "荆州", "武汉", "南京", "常州", "上海"]),
    ]
    for name, v, cs in special:
        ps.append(_p(f"special:{name}", f"【{name}】", 3 * v, cs))
    # 2.3 city pairs
    for a, b in [("北京", "天津"), ("上海", "南京"), ("广州", "深圳"), ("成都", "重庆"), ("荆州", "襄阳")]:
        ps.append(_p(f"pair:{a}{b}", f"{a}{b}", 3 * 2, [a, b]))
    return ps


PATTERNS: list[Pattern] = _build()
PATTERN_BY_ID: dict[str, Pattern] = {p.id: p for p in PATTERNS}
