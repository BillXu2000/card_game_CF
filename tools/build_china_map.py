"""Build cardgame/static/data/china_map.json for the 城市交易所 map panel.

Sources (download into one directory, pass it as the first argument):
  china_full.json   https://geo.datav.aliyun.com/areas_v3/bound/100000_full.json
                    (provinces + 九段线, consistent with the Chinese standard map)
  ne_50m_admin_0_countries.geojson, ne_10m_rivers_lake_centerlines.geojson
                    https://github.com/nvkelso/natural-earth-vector (public domain)

Run:  .venv/bin/pip install shapely
      .venv/bin/python tools/build_china_map.py <dir>

Everything is projected with an Albers equal-area conic projection
(standard parallels 25°N / 47°N, central meridian 105°E, as used by
Chinese national maps); coordinates in the output are kilometres with y
pointing down, ready for an SVG viewBox.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from shapely.geometry import LineString, MultiLineString, MultiPolygon, Polygon, box, shape
from shapely.ops import unary_union

OUT = Path(__file__).resolve().parent.parent / "cardgame" / "static" / "data" / "china_map.json"

# ---------------------------------------------------------------- projection
R = 6371.0
LAT1, LAT2, LON0, LAT0 = math.radians(25), math.radians(47), math.radians(105), 0.0
N = (math.sin(LAT1) + math.sin(LAT2)) / 2
C = math.cos(LAT1) ** 2 + 2 * N * math.sin(LAT1)
RHO0 = R * math.sqrt(C - 2 * N * math.sin(LAT0)) / N


def project(lon: float, lat: float) -> tuple[float, float]:
    rho = R * math.sqrt(C - 2 * N * math.sin(math.radians(lat))) / N
    theta = N * (math.radians(lon) - LON0)
    return rho * math.sin(theta), -(RHO0 - rho * math.cos(theta))


def project_geom(g):
    from shapely.ops import transform
    return transform(lambda x, y, z=None: tuple(zip(*[project(a, b) for a, b in zip(x, y)])), g)


def bbox_of(lon0, lat0, lon1, lat1) -> list[float]:
    pts = [project(lon0 + (lon1 - lon0) * i / 20, lat0 + (lat1 - lat0) * j / 20) for i in range(21) for j in range(21)]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return [round(min(xs), 1), round(min(ys), 1), round(max(xs) - min(xs), 1), round(max(ys) - min(ys), 1)]


# ------------------------------------------------------------------ game data
# city: (lon, lat) of the city centre
CITIES = {
    "北京": (116.40, 39.90), "上海": (121.47, 31.23), "重庆": (106.55, 29.56), "天津": (117.20, 39.13),
    "南京": (118.80, 32.06), "常州": (119.97, 31.81), "无锡": (120.30, 31.57), "苏州": (120.58, 31.30),
    "徐州": (117.28, 34.20), "武汉": (114.31, 30.59), "宜昌": (111.29, 30.69), "襄阳": (112.14, 32.04),
    "十堰": (110.80, 32.63), "荆州": (112.24, 30.33), "成都": (104.07, 30.67), "广元": (105.84, 32.44),
    "绵阳": (104.68, 31.47), "攀枝花": (101.72, 26.58), "宜宾": (104.64, 28.75), "广州": (113.26, 23.13),
    "深圳": (114.06, 22.54), "汕头": (116.68, 23.35), "中山": (113.39, 22.52), "河源": (114.70, 23.74),
}
GAME_PROVINCES = {"北京市": "直辖市", "上海市": "直辖市", "重庆市": "直辖市", "天津市": "直辖市",
                  "江苏省": "江苏", "湖北省": "湖北", "四川省": "四川", "广东省": "广东"}

# railways through real stations (lon, lat); 成襄铁路 is the rule book's line, drawn
# along existing lines 宝成/西成 (成都-广元), 阳安 (广元-安康), 襄渝 (安康-襄阳)
RAILWAYS = {
    "jinghu": {"name": "京沪高铁", "kind": "hsr", "via": [
        ("北京", 116.38, 39.87), ("天津", 117.20, 39.13), ("沧州", 116.84, 38.30), ("德州", 116.36, 37.43),
        ("济南", 117.00, 36.65), ("泰安", 117.09, 36.20), ("曲阜", 116.99, 35.58), ("滕州", 117.17, 35.08),
        ("枣庄", 117.32, 34.81), ("徐州", 117.28, 34.20), ("宿州", 116.98, 33.64), ("蚌埠", 117.39, 32.92),
        ("滁州", 118.32, 32.30), ("南京", 118.80, 32.06), ("镇江", 119.45, 32.20), ("丹阳", 119.61, 32.00),
        ("常州", 119.97, 31.81), ("无锡", 120.30, 31.57), ("苏州", 120.58, 31.30), ("昆山", 120.98, 31.39),
        ("上海", 121.32, 31.19)]},
    "chengxiang": {"name": "成襄铁路", "kind": "rail", "via": [
        ("成都", 104.07, 30.67), ("德阳", 104.40, 31.13), ("绵阳", 104.68, 31.47), ("江油", 104.75, 31.78),
        ("广元", 105.84, 32.44), ("宁强", 106.26, 32.83), ("汉中", 107.03, 33.07), ("西乡", 107.77, 32.98),
        ("安康", 109.03, 32.68), ("白河", 110.11, 32.81), ("十堰", 110.80, 32.63), ("丹江口", 111.51, 32.54),
        ("襄阳", 112.14, 32.04)]},
}
# Natural Earth's Yangtze stops at 镇江; continue along the real course to the sea
YANGTZE_ESTUARY = [(119.61, 32.20), (119.80, 32.24), (120.05, 32.02), (120.27, 31.95), (120.55, 31.98),
                   (120.85, 31.93), (121.00, 31.78), (121.30, 31.55), (121.60, 31.42), (121.90, 31.33)]
# province name positions (lon, lat) where the centroid would sit on a city label
PROVINCE_LABEL = {"江苏省": (119.6, 33.6), "湖北省": (113.4, 31.55), "四川省": (102.3, 31.6), "广东省": (115.6, 24.5),
                  "北京市": (115.75, 40.8), "天津市": (118.45, 39.3), "上海市": (122.55, 30.95), "重庆市": (108.5, 30.75)}

VIEWS = {
    "main": (99.3, 20.6, 123.4, 41.3),
    "yrd": (118.35, 30.85, 122.05, 32.45),   # 长江三角洲
    "prd": (112.85, 22.15, 115.05, 24.0),    # 珠江三角洲
    "locator": (73.0, 3.0, 136.0, 54.0),
}
# detail regions get less simplification
DETAIL = [box(*project(118.0, 30.5), *project(122.3, 32.8)), box(*project(112.5, 21.9), *project(115.3, 24.3))]


def bounds_box(lon0, lat0, lon1, lat1):
    x, y, w, h = bbox_of(lon0, lat0, lon1, lat1)
    return box(x, y, x + w, y + h)


MAIN = bounds_box(*VIEWS["main"])


def simplify(g, tol_far=14.0, tol_main=2.5, tol_detail=0.7):
    def one(part):
        b = part.envelope
        if any(b.intersects(d) for d in DETAIL):
            return part.simplify(tol_detail, preserve_topology=True)
        if b.intersects(MAIN):
            return part.simplify(tol_main, preserve_topology=True)
        return part.simplify(tol_far, preserve_topology=True)

    if isinstance(g, (MultiPolygon, MultiLineString)):
        return type(g)([one(p) for p in g.geoms if not p.is_empty])
    return one(g)


def path(g) -> str:
    """SVG path data (km, 1 decimal)."""
    out = []

    def ring(coords, close):
        pts = [(round(x, 1), round(y, 1)) for x, y in coords]
        dedup = [pts[0]] + [p for a, p in zip(pts, pts[1:]) if p != a]
        if len(dedup) < 2:
            return
        out.append("M" + " ".join(f"{x:g},{y:g}" for x, y in dedup) + ("Z" if close else ""))

    def walk(geom):
        if geom.is_empty:
            return
        if isinstance(geom, Polygon):
            ring(geom.exterior.coords, True)
            for i in geom.interiors:
                ring(i.coords, True)
        elif isinstance(geom, LineString):
            ring(geom.coords, False)
        elif hasattr(geom, "geoms"):
            for p in geom.geoms:
                walk(p)

    walk(g)
    return "".join(out)


def main(src: Path) -> None:
    china = json.load(open(src / "china_full.json", encoding="utf-8"))
    provinces, dashes = [], None
    for f in china["features"]:
        props = f["properties"]
        g = shape(f["geometry"]).buffer(0) if f["geometry"]["type"] != "MultiPolygon" else shape(f["geometry"])
        if str(props.get("adcode")).endswith("_JD"):
            dashes = project_geom(g)
            continue
        pg = project_geom(g)
        provinces.append({"name": props["name"], "geom": pg, "centroid": props.get("centroid") or props.get("center")})
    land = unary_union([p["geom"].buffer(0) for p in provinces])

    countries = json.load(open(src / "ne_50m_admin_0_countries.geojson", encoding="utf-8"))
    skip = {"China", "Taiwan", "Hong Kong S.A.R.", "Macao S.A.R"}
    neighbours = [project_geom(shape(f["geometry"]).buffer(0)) for f in countries["features"]
                  if f["properties"].get("ADMIN") not in skip and f["properties"].get("NAME") not in {"China", "Taiwan"}]
    world_extent = bounds_box(*VIEWS["locator"]).buffer(500)
    neighbours = [n.intersection(world_extent) for n in neighbours if n.intersects(world_extent)]
    neighbour_land = unary_union(neighbours)
    near = neighbour_land.buffer(25)
    outline = land.boundary
    land_border = outline.intersection(near)
    coast = outline.difference(near)

    rivers = json.load(open(src / "ne_10m_rivers_lake_centerlines.geojson", encoding="utf-8"))
    yangtze = [project_geom(shape(f["geometry"])) for f in rivers["features"]
               if f["properties"].get("name") in ("Jinsha", "Chang Jiang", "Yangtze")]
    yangtze.append(LineString([project(*p) for p in YANGTZE_ESTUARY]))
    yellow = [project_geom(shape(f["geometry"])) for f in rivers["features"] if f["properties"].get("name") == "Huang"]

    out = {
        "source": "国界、省界：阿里云 DataV（与国家标准地图一致）；河流、邻国：Natural Earth",
        "projection": "Albers 等积圆锥投影，标准纬线 25°N/47°N，中央经线 105°E；单位 km",
        "views": {k: bbox_of(*v) for k, v in VIEWS.items()},
        "neighbours": path(simplify(neighbour_land, tol_main=4)),
        "provinces": [
            {"name": p["name"], "short": short_name(p["name"]), "game": GAME_PROVINCES.get(p["name"]),
             "d": path(simplify(p["geom"])),
             "label": [round(v, 1) for v in project(*PROVINCE_LABEL.get(p["name"], p["centroid"]))]
             if p["centroid"] else None}
            for p in provinces
        ],
        "coast": path(simplify(coast)),
        "border": path(simplify(land_border)),
        "dashes": path(dashes) if dashes is not None else "",  # thin polygons: never simplify
        "yangtze": path(simplify(unary_union(yangtze), tol_main=1.5)),
        "yellow_river": path(simplify(unary_union(yellow), tol_main=1.5)),
        "railways": {k: {"name": r["name"], "kind": r["kind"],
                         "d": path(LineString([project(lon, lat) for _, lon, lat in r["via"]]))}
                     for k, r in RAILWAYS.items()},
        "cities": {c: [round(v, 1) for v in project(*ll)] for c, ll in CITIES.items()},
        # where to write feature names: (lon, lat) next to the line
        "feature_labels": {name: [round(v, 1) for v in project(*ll)] for name, ll in {
            "长江": (116.6, 29.55), "京沪高铁": (117.25, 36.7), "成襄铁路": (107.4, 33.3),
        }.items()},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")


def short_name(name: str) -> str:
    for suffix in ("维吾尔自治区", "壮族自治区", "回族自治区", "自治区", "特别行政区", "省", "市"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


if __name__ == "__main__":
    main(Path(sys.argv[1]))
