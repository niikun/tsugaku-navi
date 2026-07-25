"""pyosmiumでPBFを1回ストリーム処理し、セル単位(500m)のOSM属性を集計する。

**重要(ライセンス安全性の設計)**: このスクリプトの出力(`osm_data/osm_raw_cache_500m.pkl`
と`osm_data/vehicle_roads_tokyo.parquet`)は、個々のOSM要素(信号機・横断歩道の
個別座標、車道wayのway_id+座標列)を生のまま含む「作業用の生キャッシュ」であり、
**絶対にコミットしない**(`osm_data/`ディレクトリごと`.gitignore`のdeny-by-default
対象)。集計のみのコミット可能な特徴量は、このキャッシュを読んだ
`extract_osm_features.py`が別途`osm_features/`ディレクトリに書き出す
(README.md「OSMベクターデータ」節、HANDOFF.md参照)。

設計(旧リポジトリでのFable5との相談内容を踏襲、詳細は別リポジトリ
traffic_accidentのSTUDY_LOG.md参照):
- sidewalk/maxspeed/lanesはタグ保持率が5%未満のため使わない。
- 信号機・横断歩道はノードベースの情報で保持率が高いためセルごとのカウントを使う。
- footway延長は車道延長と別集計し、「footway延長÷車道延長」を歩行者空間の分離度の
  代理指標として使う。
- 交差点密度は車道wayのみのノード次数(参照way数)で計算し、footwayとの交点は
  別特徴(車道×footway交差点数、非公式な横断地点の代理)として分離する。
- 集計は「延長(m)」ベース(wayの本数は編集粒度のノイズを拾うため使わない)。

出典: OpenStreetMapデータ。© OpenStreetMap contributors, Open Database License
(ODbL)。https://www.openstreetmap.org/copyright
"""
import math
import os
import pickle
from collections import defaultdict

import osmium

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PBF_PATH = os.path.join(BASE_DIR, "osm_data", "kanto-latest.osm.pbf")
RAW_CACHE_PATH = os.path.join(BASE_DIR, "osm_data", "osm_raw_cache_500m.pkl")
VEHICLE_ROADS_PATH = os.path.join(BASE_DIR, "osm_data", "vehicle_roads_tokyo.parquet")

# train+valブロックの実際のbbox(west, south, east, north)
BBOX = (138.98, 35.49, 139.96, 35.82)

VEHICLE_HIGHWAY = {
    "motorway", "trunk", "primary", "secondary", "tertiary", "unclassified",
    "residential", "service", "living_street",
    "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link",
}
FOOTWAY_HIGHWAY = {"footway", "path", "pedestrian", "steps", "cycleway", "track", "corridor"}

GRID_M = 500


def in_bbox(lon, lat):
    return BBOX[0] <= lon <= BBOX[2] and BBOX[1] <= lat <= BBOX[3]


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def cell_of(lat, lon, lat_step, lon_step):
    return int(lon // lon_step), int(lat // lat_step)


def extract_all(lat_step, lon_step):
    vehicle_length = defaultdict(float)
    footway_length = defaultdict(float)
    highway_type_length = defaultdict(lambda: defaultdict(float))
    signal_count = defaultdict(int)
    crossing_count = defaultdict(int)
    signal_points = []
    crossing_points = []
    vehicle_ways = []  # 車道wayの座標列(road_index.pyの交差判定・線単位の種別判定用)

    node_touch = {}
    node_location = {}

    fp = osmium.FileProcessor(PBF_PATH).with_locations()
    n_ways = 0
    for obj in fp:
        if obj.is_node():
            tags = obj.tags
            lon, lat = obj.location.lon, obj.location.lat
            if not in_bbox(lon, lat):
                continue
            hw = tags.get("highway")
            if hw == "traffic_signals":
                c = cell_of(lat, lon, lat_step, lon_step)
                signal_count[c] += 1
                signal_points.append((lat, lon))
            elif hw == "crossing":
                c = cell_of(lat, lon, lat_step, lon_step)
                crossing_count[c] += 1
                crossing_points.append((lat, lon))
            continue

        if not obj.is_way():
            continue
        tags = obj.tags
        hw = tags.get("highway")
        is_vehicle = hw in VEHICLE_HIGHWAY
        is_footway = hw in FOOTWAY_HIGHWAY
        if not is_vehicle and not is_footway:
            continue

        nodes = obj.nodes
        if len(nodes) < 2:
            continue
        try:
            if not in_bbox(nodes[0].location.lon, nodes[0].location.lat):
                continue
        except Exception:
            continue

        n_ways += 1
        locs = []
        for n in nodes:
            try:
                locs.append((n.ref, n.location.lat, n.location.lon))
            except Exception:
                locs.append(None)

        if is_vehicle:
            coords = [(item[1], item[2]) for item in locs if item is not None]
            if len(coords) >= 2:
                vehicle_ways.append({"way_id": obj.id, "highway": hw, "coords": coords})

        for i in range(len(locs) - 1):
            a, b = locs[i], locs[i + 1]
            if a is None or b is None:
                continue
            _, lat1, lon1 = a
            _, lat2, lon2 = b
            seg_len = haversine_m(lat1, lon1, lat2, lon2)
            mid_lat, mid_lon = (lat1 + lat2) / 2, (lon1 + lon2) / 2
            c = cell_of(mid_lat, mid_lon, lat_step, lon_step)
            if is_vehicle:
                vehicle_length[c] += seg_len
            else:
                footway_length[c] += seg_len
            highway_type_length[c][hw] += seg_len

        for item in locs:
            if item is None:
                continue
            nid, lat, lon = item
            if nid not in node_touch:
                node_touch[nid] = [0, 0]
                if in_bbox(lon, lat):
                    node_location[nid] = (lat, lon)
            if is_vehicle:
                node_touch[nid][0] += 1
            else:
                node_touch[nid][1] += 1

        if n_ways % 100000 == 0:
            print(f"  {n_ways} way処理済み")

    print(f"合計way数: {n_ways}")

    vehicle_intersection = defaultdict(int)
    vehicle_footway_intersection = defaultdict(int)
    for nid, (v_cnt, f_cnt) in node_touch.items():
        if nid not in node_location:
            continue
        lat, lon = node_location[nid]
        c = cell_of(lat, lon, lat_step, lon_step)
        if v_cnt >= 2:
            vehicle_intersection[c] += 1
        if v_cnt >= 1 and f_cnt >= 1:
            vehicle_footway_intersection[c] += 1

    return {
        "vehicle_length": dict(vehicle_length),
        "footway_length": dict(footway_length),
        "highway_type_length": {k: dict(v) for k, v in highway_type_length.items()},
        "signal_count": dict(signal_count),
        "crossing_count": dict(crossing_count),
        "signal_points": signal_points,
        "crossing_points": crossing_points,
        "vehicle_intersection": dict(vehicle_intersection),
        "vehicle_footway_intersection": dict(vehicle_footway_intersection),
        "vehicle_ways": vehicle_ways,
    }


def _save_vehicle_roads_parquet(vehicle_ways, path):
    """車道wayの座標列をLineStringのWKBにしてparquetへ保存する
    (plateau/plateau/parquet_index.pyと同じ、footprint WKB方式の流用)。
    """
    import pandas as pd
    from shapely.geometry import LineString
    from shapely import wkb as shapely_wkb

    rows = []
    for w in vehicle_ways:
        line = LineString([(lon, lat) for lat, lon in w["coords"]])
        rows.append({
            "way_id": w["way_id"],
            "highway": w["highway"],
            "geometry_wkb": shapely_wkb.dumps(line),
        })
    df = pd.DataFrame(rows)
    df.to_parquet(path, index=False)
    return len(df)


def main():
    from tiles import grid_steps
    lat_step, lon_step = grid_steps(GRID_M)

    if not os.path.exists(PBF_PATH):
        raise SystemExit(
            f"PBFファイルが見つかりません: {PBF_PATH}\n"
            "Geofabrik等からKanto地方のOSM抽出データ(.osm.pbf)を取得し配置してください"
            "(このファイル自体は生のOSMデータであり、常にgitignore対象)。"
        )

    print("PBFをストリーム処理中(1パス、車道/歩道の延長・交差点・信号機・横断歩道を集計)...")
    result = extract_all(lat_step, lon_step)

    os.makedirs(os.path.dirname(RAW_CACHE_PATH), exist_ok=True)
    with open(RAW_CACHE_PATH, "wb") as f:
        pickle.dump(result, f)
    print(f"\n生キャッシュを保存しました(gitignore対象): {RAW_CACHE_PATH}")
    print(f"車道データのあるセル数: {len(result['vehicle_length'])}")
    print(f"歩道データのあるセル数: {len(result['footway_length'])}")
    print(f"信号機ノード総数: {len(result['signal_points'])}")
    print(f"横断歩道ノード総数: {len(result['crossing_points'])}")

    n_roads = _save_vehicle_roads_parquet(result["vehicle_ways"], VEHICLE_ROADS_PATH)
    print(f"車道way数: {n_roads} -> {VEHICLE_ROADS_PATH}(gitignore対象)")


if __name__ == "__main__":
    main()
