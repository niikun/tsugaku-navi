"""駅からの距離を使う交絡チェック(spatial_block_split.py等)向けの駅位置データ読み込み。

データは`prepare_station_data.py`が国土数値情報(鉄道データN02)から事前生成した
`boundary_data/N02-2022_Station_tokyo.geojson`を使う。OSM/Overpass APIには依存しない
(経緯: HANDOFF.md「OSMライセンス問題」参照)。
"""
import json
import math
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GEOJSON_PATH = os.path.join(BASE_DIR, "boundary_data", "N02-2022_Station_tokyo.geojson")

_cache = None


def load_station_points():
    """[(lat, lon), ...]を返す(東京本土、駅コード単位で重複統合済み)。"""
    global _cache
    if _cache is None:
        with open(GEOJSON_PATH, encoding="utf-8") as f:
            data = json.load(f)
        _cache = [
            (feat["geometry"]["coordinates"][1], feat["geometry"]["coordinates"][0])
            for feat in data["features"]
        ]
    return _cache


def _haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearest_station_distance(lat, lon, station_points):
    return min(_haversine_m(lat, lon, slat, slon) for slat, slon in station_points)
