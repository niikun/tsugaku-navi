"""東京都行政界(国土数値情報N03)による、セルが「都内かつ境界から十分離れている」かの判定。

別リポジトリ(traffic_accident、開発機上では`../traffic_accident/`に配置)での
旧設計において、負例サンプリング(distant方式・stratified方式とも)が東京都の
行政境界を考慮しておらず、train負例の55.8%・eval負例の66.3%が実際には東京都外
(埼玉・千葉・神奈川)だったことが判明した経緯がある(詳細:
traffic_accidentリポジトリの`plateau/CONSULTATION_SIGHTLINE.md`追記4)。
この教訓を踏まえ、候補セルが都境界から一定距離(既定500m)以上内側にあるかを
判定するユーティリティとして、このリポジトリでも同じ設計を踏襲する。

境界バッファを設けるのは、都内でも境界近くは「事故の一部が隣県側で記録され欠落する」
端効果があり得るため。正例側の都外判定(約1.3%)もこれで同時に除外される。
"""
import os

from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import unary_union, transform as shapely_transform

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GEOJSON_PATH = os.path.join(BASE_DIR, "boundary_data", "N03-20240101_13.geojson")
BUFFER_M = 500

_eroded_polygon_6677 = None
_to_6677 = None


def _load():
    global _eroded_polygon_6677, _to_6677
    if _eroded_polygon_6677 is not None:
        return

    import json
    with open(GEOJSON_PATH, encoding="utf-8") as f:
        d = json.load(f)
    geoms = [shape(f["geometry"]) for f in d["features"] if f["geometry"] is not None]
    tokyo_poly_4326 = unary_union(geoms)

    to_6677 = Transformer.from_crs("EPSG:4326", "EPSG:6677", always_xy=True)
    tokyo_poly_6677 = shapely_transform(lambda x, y: to_6677.transform(x, y), tokyo_poly_4326)

    _eroded_polygon_6677 = tokyo_poly_6677.buffer(-BUFFER_M)
    _to_6677 = to_6677


def is_deep_inside_tokyo(lat, lon):
    """(lat, lon)が東京都行政界からBUFFER_M以上内側にあればTrue。"""
    _load()
    from shapely.geometry import Point
    x, y = _to_6677.transform(lon, lat)
    return _eroded_polygon_6677.contains(Point(x, y))


if __name__ == "__main__":
    # サンプル地点で動作確認(新宿駅付近=都内深く、境界付近の座標=False期待)
    print("新宿駅付近(35.6905, 139.7005):", is_deep_inside_tokyo(35.6905, 139.7005))
    print("埼玉側と疑われる地点(35.76, 139.556):", is_deep_inside_tokyo(35.76, 139.556))
    print("千葉側と疑われる地点(35.66, 139.89):", is_deep_inside_tokyo(35.66, 139.89))
