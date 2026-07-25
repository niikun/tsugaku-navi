"""車道ジオメトリの空間インデックス(STRtreeベース)。

extract_osm_raw_cache.pyが保存したvehicle_roads_tokyo.parquet(車道wayの座標列+
種別、footway系は除外、常にgitignore対象の生キャッシュ)を読み込み、以下の2つに使う:

1. crossings_for_route: ルートが実際に車道を横切る地点の検出
   (「横断歩道あり+信号あり/なし」「横断歩道なし」の分類の元データ)
2. nearest_road_type: 経路上の各地点にいちばん近い車道の種別
   (セル単位のdominant_road_typeと違い、線単位で「今どの道にいるか」を反映する)

**ライセンス安全性の設計**: このファイル自体のソースコードは座標を一切含まない
(READMEの「条件1」に相当)。入力データ(vehicle_roads_tokyo.parquet)は個々の
OSM要素(way_id+座標列)を持つため`osm_data/`ディレクトリごと常にgitignore対象。
この関数群の戻り値(横断地点・最近傍道路種別)はクエリ1回ごとの計算結果であり、
永続化・コミットはしない(旧リポジトリでこのファイルが「良い設計の手本」として
監査で評価された点を踏襲。HANDOFF.md参照)。

shapelyの慣例に合わせ、内部の座標順はすべて(x=経度, y=緯度)。
predicateは対称な"intersects"を使うため、plateau/plateau/index.pyで見つかった
contains/within方向の罠(クエリ側が主語になる)は関係ない。
"""
import math
import os

import pandas as pd
from shapely import wkb as shapely_wkb
from shapely.geometry import LineString, Point
from shapely.ops import nearest_points
from shapely import STRtree

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VEHICLE_ROADS_PATH = os.path.join(BASE_DIR, "osm_data", "vehicle_roads_tokyo.parquet")

# 以下のしきい値は3テストルート(新宿・立川・境界またぎ)で目視検証して決めた値。
# 結果を見ながら調整したため事前登録ではないが、調整の理由はコード内コメントに残す。
TRANSVERSE_ANGLE_MIN_DEG = 45   # 車道との交差角度がこれ未満(≒平行)なら「道に沿って歩いている」とみなし除外
CROSSING_DEDUP_M = 25            # この距離以内の検出は同一の横断イベントとして統合
# (実測: 同一の車道が複数wayに分割されているケースで15.2m離れた2点に分裂検出
# された例があったため、15mから25mに拡大した)
MARKED_CROSSING_MAX_M = 40       # 横断歩道の実座標がこの距離以内にあれば「横断歩道あり」
# (実測: 3テストルートでルート×車道の幾何学的な交点から実際の横断歩道までの距離を
# 測ったところ、20〜40m圏内に本物の横断歩道があるケースが複数あった(例: 20.9m,
# 21.1m, 35.1m)。20mでは実在する横断歩道を「なし」と誤判定していたため35mまで
# 拡大したが、35.1mの実測ケースをぎりぎり含められない値だったため40mに再拡大した。
# 経路と道路の交点は、幅のある交差点内で実際の横断歩道の位置からある程度ズレるため。
# なお別途、複数way分割による重複検出時の代表点選択バグ(dedup_crossingsのkey)も
# 同時に修正済み。しきい値だけの問題ではなかった。)
SIGNAL_NEAR_CROSSING_MAX_M = 30  # 横断歩道からこの距離以内に信号があれば「信号あり」
NEAREST_ROAD_MAX_M = 60         # 経路区間から車道までがこの距離を超えたら「近くに車道なし」扱い

NARROW_HIGHWAY_TYPES = {"residential", "service", "unclassified", "living_street"}


def _haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _bearing_deg(lat1, lon1, lat2, lon2):
    dlon = math.radians(lon2 - lon1)
    lat1r, lat2r = math.radians(lat1), math.radians(lat2)
    x = math.sin(dlon) * math.cos(lat2r)
    y = math.cos(lat1r) * math.sin(lat2r) - math.sin(lat1r) * math.cos(lat2r) * math.cos(dlon)
    return math.degrees(math.atan2(x, y)) % 360


def _angle_diff(a, b):
    d = abs(a - b) % 360
    return min(d, 360 - d)


def load_roads(parquet_path=VEHICLE_ROADS_PATH):
    df = pd.read_parquet(parquet_path)
    roads = []
    for row in df.itertuples(index=False):
        line = shapely_wkb.loads(row.geometry_wkb)
        roads.append({"way_id": row.way_id, "highway": row.highway, "geometry": line})
    return roads


class RoadIndex:
    def __init__(self, roads):
        self.roads = roads
        self.geoms = [r["geometry"] for r in roads]
        self.tree = STRtree(self.geoms)

    def _local_bearing(self, line, lon, lat):
        """線上でクエリ点にいちばん近い頂点区間の方位角(度)を返す(交差角度の判定用)。"""
        coords = list(line.coords)
        p = Point(lon, lat)
        best_i, best_d = 0, None
        for i in range(len(coords) - 1):
            seg = LineString([coords[i], coords[i + 1]])
            d = seg.distance(p)
            if best_d is None or d < best_d:
                best_d, best_i = d, i
        (lon1, lat1), (lon2, lat2) = coords[best_i], coords[best_i + 1]
        return _bearing_deg(lat1, lon1, lat2, lon2)

    def nearest_road_type(self, lat, lon, max_dist_m=NEAREST_ROAD_MAX_M):
        """指定地点にいちばん近い車道の種別(highway=タグ)。近くに車道が無ければNone。"""
        pt = Point(lon, lat)
        buffer_deg = max_dist_m / 111000.0 * 1.5
        idx = self.tree.query(pt.buffer(buffer_deg), predicate="intersects")
        if len(idx) == 0:
            return None
        best_i, best_dist = None, None
        for i in idx:
            nearest_on_line = nearest_points(pt, self.geoms[i])[1]
            d = _haversine_m(lat, lon, nearest_on_line.y, nearest_on_line.x)
            if best_dist is None or d < best_dist:
                best_dist, best_i = d, i
        if best_dist is None or best_dist > max_dist_m:
            return None
        return self.roads[best_i]["highway"]

    def crossings_for_route(self, route_coords):
        """ルート([(lat, lon), ...])が実際に車道を横切る地点を検出する。

        route_segmentと車道の交差角度が浅い(≒平行、歩いている道に沿っている)
        場合は横断とみなさず除外する。近接する検出は1件の横断イベントに統合する。
        """
        raw_crossings = []
        for i in range(len(route_coords) - 1):
            lat1, lon1 = route_coords[i]
            lat2, lon2 = route_coords[i + 1]
            if lat1 == lat2 and lon1 == lon2:
                continue
            route_seg = LineString([(lon1, lat1), (lon2, lat2)])
            idx = self.tree.query(route_seg, predicate="intersects")
            route_bearing = _bearing_deg(lat1, lon1, lat2, lon2)
            for j in idx:
                road_geom = self.geoms[j]
                inter = route_seg.intersection(road_geom)
                if inter.is_empty:
                    continue
                for pt in self._extract_points(inter):
                    plon, plat = pt.x, pt.y
                    road_bearing = self._local_bearing(road_geom, plon, plat)
                    diff = _angle_diff(route_bearing, road_bearing)
                    if diff < TRANSVERSE_ANGLE_MIN_DEG or diff > (180 - TRANSVERSE_ANGLE_MIN_DEG):
                        continue  # 平行=道に沿って歩いている。横断ではない
                    raw_crossings.append({"lat": plat, "lon": plon, "highway": self.roads[j]["highway"]})
        return raw_crossings

    @staticmethod
    def _extract_points(geom):
        if geom.geom_type == "Point":
            return [geom]
        if geom.geom_type == "MultiPoint":
            return list(geom.geoms)
        return []  # LineString/MultiLineString(車道と重なって伸びている)は横断地点として扱わない

    @staticmethod
    def dedup_crossings(raw_crossings, key=None):
        """近接する検出(同じ物理的な交差点が複数の車道wayに分割されて重複検出
        されたもの)を1つに統合する。

        重要: keyを渡さない場合は幾何検出順で先着優先になるが、それだと
        「横断歩道タグに近い側の点(=正しく『横断歩道あり』と分類されるはずの点)」
        が、たまたま検出順で後になっただけで握りつぶされ、代わりに残った遠い側の
        点が『横断歩道なし』と誤分類される、という実際に起きたバグがあった。
        risk_model.get_route_crossingsは分類(has_marked_crossing等)を計算した
        後でこの関数を呼び、keyに「横断歩道ありを優先」を渡すことでこれを防ぐ。
        """
        if key is None:
            key = lambda c: 0
        clusters = []  # [{"anchor": (lat, lon), "members": [...]}, ...]
        for c in raw_crossings:
            target = None
            for cluster in clusters:
                if _haversine_m(c["lat"], c["lon"], cluster["anchor"][0], cluster["anchor"][1]) < CROSSING_DEDUP_M:
                    target = cluster
                    break
            if target is None:
                clusters.append({"anchor": (c["lat"], c["lon"]), "members": [c]})
            else:
                target["members"].append(c)
        return [max(cluster["members"], key=key) for cluster in clusters]
