"""セル/地点ごとのOSM特徴量を引く。

**ライセンス安全性の設計**(README.md「OSMベクターデータ」節参照): このクラスが
使う2つのデータソースは性質が全く異なる:
- `osm_features/cell_aggregates_500m.json`(extract_osm_features.py出力): 集計
  のみ・帰属表示付きでコミット可能
- `osm_data/osm_raw_cache_500m.pkl`(extract_osm_raw_cache.py出力): 信号機・
  横断歩道の個別座標を含む生キャッシュ、常にgitignore対象

`features_for`が返すsignal_nearest_m/crossing_nearest_mは、その場で個別座標を
参照して計算するスカラー値で、この関数自体は結果をどこにも書き戻さない
(risk_model.pyのライブ推論はこの値をレスポンスとして返すだけで永続化しない)。

ただし、この最近傍距離を500mメッシュで面的に(多数の地点について)ファイルへ
書き出すと、複数地点からの距離を組み合わせた三点測量で個々の信号機・横断歩道の
座標を実質的に再構成できてしまう。単純な「件数」集計とは性質が異なり
コミット対象にはできないため、`main()`が生成する学習・評価用CSVでは
nearest_m系の列を`osm_features/`(コミット対象)には含めず、`osm_data/`
(常にgitignore対象)にフル版を書き出す。evaluate_floor_osm.py等、
nearest_m系特徴が必要な評価専用スクリプトはそちらを参照する。
"""
import csv
import json
import math
import os
import pickle

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AGGREGATES_PATH = os.path.join(BASE_DIR, "osm_features", "cell_aggregates_500m.json")
RAW_CACHE_PATH = os.path.join(BASE_DIR, "osm_data", "osm_raw_cache_500m.pkl")
GRID_M = 500

MAIN_HIGHWAY_TYPES = ["primary", "secondary", "tertiary", "residential", "service", "unclassified", "trunk"]

# 個々のOSM要素(信号機・横断歩道)の座標に由来し、面的に持つと元座標を
# 再構成できてしまう列。コミット対象のosm_features/には含めない。
NEAREST_POINT_COLS = ("signal_nearest_m", "crossing_nearest_m")


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def cell_key(lat, lon, lat_step, lon_step):
    return f"{int(lon // lon_step)}_{int(lat // lat_step)}"


def nearest_point_distance(lat, lon, points):
    if not points:
        return None
    return min(haversine_m(lat, lon, plat, plon) for plat, plon in points)


class OSMFeatureLookup:
    def __init__(self):
        from tiles import grid_steps

        with open(AGGREGATES_PATH, encoding="utf-8") as f:
            self.aggregates = json.load(f)

        with open(RAW_CACHE_PATH, "rb") as f:
            raw = pickle.load(f)
        self.lat_step, self.lon_step = grid_steps(GRID_M)
        # 信号機・横断歩道は最近傍探索を高速化するため粗いグリッド(2km)でバケット化する
        self.bucket_deg = 0.02
        self.signal_buckets = self._bucketize(raw["signal_points"])
        self.crossing_buckets = self._bucketize(raw["crossing_points"])
        del raw  # 生ジオメトリの生リストはバケット化後は不要(メモリ上でも保持を最小化)

    def _bucketize(self, points):
        buckets = {}
        for lat, lon in points:
            key = (int(lon / self.bucket_deg), int(lat / self.bucket_deg))
            buckets.setdefault(key, []).append((lat, lon))
        return buckets

    def _nearest_via_bucket(self, lat, lon, buckets, max_ring=3):
        bx, by = int(lon / self.bucket_deg), int(lat / self.bucket_deg)
        for ring in range(max_ring + 1):
            candidates = []
            for dx in range(-ring, ring + 1):
                for dy in range(-ring, ring + 1):
                    if max(abs(dx), abs(dy)) != ring:
                        continue
                    candidates.extend(buckets.get((bx + dx, by + dy), []))
            if candidates:
                return nearest_point_distance(lat, lon, candidates)
        return None

    def features_for(self, lat, lon):
        c = cell_key(lat, lon, self.lat_step, self.lon_step)
        vehicle_len = self.aggregates["vehicle_length"].get(c, 0.0)
        footway_len = self.aggregates["footway_length"].get(c, 0.0)
        type_len = self.aggregates["highway_type_length"].get(c, {})

        feats = {
            "vehicle_length_m": vehicle_len,
            "footway_length_m": footway_len,
            "footway_ratio": footway_len / (vehicle_len + 1.0),
            "signal_count": self.aggregates["signal_count"].get(c, 0),
            "crossing_count": self.aggregates["crossing_count"].get(c, 0),
            "vehicle_intersection_count": self.aggregates["vehicle_intersection"].get(c, 0),
            "vehicle_footway_intersection_count": self.aggregates["vehicle_footway_intersection"].get(c, 0),
        }
        sd = self._nearest_via_bucket(lat, lon, self.signal_buckets)
        cd = self._nearest_via_bucket(lat, lon, self.crossing_buckets)
        feats["signal_nearest_m"] = sd if sd is not None else 5000.0
        feats["crossing_nearest_m"] = cd if cd is not None else 5000.0

        for hw in MAIN_HIGHWAY_TYPES:
            feats[f"{hw}_ratio"] = type_len.get(hw, 0.0) / (vehicle_len + 1.0)
        return feats


def build_table(rows, lookup):
    """rows: [{'lat':.., 'lon':.., 'accident_count':.., 'cell_id':..}, ...]"""
    out = []
    for r in rows:
        feats = lookup.features_for(float(r["lat"]), float(r["lon"]))
        feats["cell_id"] = r["cell_id"]
        feats["accident_count"] = int(r["accident_count"])
        out.append(feats)
    return out


def main():
    import argparse
    from tiles import DEFAULT_TILE_STYLE

    parser = argparse.ArgumentParser()
    parser.add_argument("--style", choices=["std", "pale"], default=DEFAULT_TILE_STYLE,
                         help="build_train_set.py/build_eval_set.pyと同じスタイルを指定する")
    args = parser.parse_args()
    style = args.style

    lookup = OSMFeatureLookup()

    print("train側セルにOSM特徴を紐付け中...")
    train_manifest = os.path.join(BASE_DIR, "dataset", f"manifest_train_counts_500m_{style}.csv")
    with open(train_manifest, encoding="utf-8") as f:
        train_rows_raw = list(csv.DictReader(f))
    # 拡張画像(_aug1等)は元画像と同一セル・同一OSM特徴のため除外する
    # (augment_dataset.pyがsource_cell_id==cell_idで元画像を判別できるようにしている)。
    train_rows = [
        {"lat": r["lat_center"], "lon": r["lon_center"], "accident_count": r["accident_count"], "cell_id": r["cell_id"]}
        for r in train_rows_raw
        if r.get("source_cell_id", r["cell_id"]) == r["cell_id"]
    ]
    train_table = build_table(train_rows, lookup)

    print("凍結評価セットにOSM特徴を紐付け中...")
    eval_manifest = os.path.join(BASE_DIR, "eval_frozen", style, "500m", "eval_manifest.csv")
    with open(eval_manifest, encoding="utf-8") as f:
        eval_rows_raw = list(csv.DictReader(f))
    eval_rows = [
        {"lat": r["lat"], "lon": r["lon"], "accident_count": r["accident_count"], "cell_id": r["cell_id"]}
        for r in eval_rows_raw
    ]
    eval_table = build_table(eval_rows, lookup)

    safe_dir = os.path.join(BASE_DIR, "osm_features")
    full_dir = os.path.join(BASE_DIR, "osm_data")
    os.makedirs(safe_dir, exist_ok=True)
    os.makedirs(full_dir, exist_ok=True)
    for name, table in [("train", train_table), ("eval", eval_table)]:
        all_cols = list(table[0].keys())

        # フル版(nearest_m含む): 常にgitignore対象のosm_data/へ。
        # evaluate_floor_osm.py等、nearest_m系特徴が必要な評価専用スクリプト用。
        full_path = os.path.join(full_dir, f"osm_features_full_{name}_{style}.csv")
        with open(full_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=all_cols)
            writer.writeheader()
            writer.writerows(table)

        # 安全版(nearest_m除外): コミット対象のosm_features/へ。
        safe_cols = [c for c in all_cols if c not in NEAREST_POINT_COLS]
        safe_path = os.path.join(safe_dir, f"osm_features_{name}_{style}.csv")
        with open(safe_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=safe_cols)
            writer.writeheader()
            for row in table:
                writer.writerow({k: row[k] for k in safe_cols})

        print(f"{name}: {len(table)}件 -> full={full_path}, safe(commit可)={safe_path}")


if __name__ == "__main__":
    main()
