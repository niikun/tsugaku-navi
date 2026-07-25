"""23区サブセットの対象セル(train+eval)について、車道way上のサンプル点
(cell_id, lat, lon)を生成する。視界特徴は「セル中心1点」ではなく
「セル内の車道サンプル点5〜10点の集計」で計算する設計のため。

**ライセンス安全性の設計**: 出力(`road_sample_points_23ku.csv`)は個々の
OSM要素由来の座標点(車道way上のサンプル点)を含むため、常にgitignore対象
(`plateau_data/`ディレクトリごと)。集計結果である`sightline_features_23ku.csv`
(セル単位の視界特徴の平均・分散等)だけがコミット可能。

道路データは`../ml_risk_model/osm_data/osm_raw_cache_500m.pkl`
(`extract_osm_raw_cache.py`が作った生キャッシュ、常にgitignore対象)の
`vehicle_ways`を再利用する(PBFの再スキャンを避けるため)。
"""
import csv
import math
import os
import pickle
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ml_risk_model"))
from tiles import grid_steps  # noqa: E402

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ML_DIR = os.path.join(BASE_DIR, "..", "ml_risk_model")
RAW_CACHE_PATH = os.path.join(ML_DIR, "osm_data", "osm_raw_cache_500m.pkl")
OUT_PATH = os.path.join(BASE_DIR, "plateau_data", "road_sample_points_23ku.csv")

GRID_M = 500
MAX_POINTS_PER_CELL = 8
MIN_SEGMENT_GAP_M = 40  # サンプル点同士が近すぎないようにする最小間隔
KU23_LON_MIN = 139.56  # 旧リポジトリと同じ、23区の粗い近似(経度しきい値)


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def cell_of(lat, lon, lat_step, lon_step):
    return int(lon // lon_step), int(lat // lat_step)


def load_target_cells(style):
    """23区サブセット(経度139.56以上)のtrain+evalセルの(gx,gy)集合を返す。

    このリポジトリ本来の本番セル集合(spatial_block_split由来、
    train全セル+eval全セル)を対象にする。旧リポジトリのようなラベルでの
    選抜は行わない(v3以降、選抜サンプリングという概念自体を廃止した設計を
    踏襲)。
    """
    lat_step, lon_step = grid_steps(GRID_M)
    cells = set()

    train_path = os.path.join(ML_DIR, "dataset", f"manifest_train_counts_500m_{style}.csv")
    with open(train_path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("source_cell_id", r["cell_id"]) != r["cell_id"]:
                continue
            lat, lon = float(r["lat_center"]), float(r["lon_center"])
            if lon >= KU23_LON_MIN:
                cells.add(cell_of(lat, lon, lat_step, lon_step))

    eval_path = os.path.join(ML_DIR, "eval_frozen", style, "500m", "eval_manifest.csv")
    with open(eval_path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            lat, lon = float(r["lat"]), float(r["lon"])
            if lon >= KU23_LON_MIN:
                cells.add(cell_of(lat, lon, lat_step, lon_step))

    return cells, lat_step, lon_step


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--style", choices=["std", "pale"], default="pale",
                         help="対象セル集合を決めるtrain/eval manifestのタイル種別"
                              "(視界特徴自体はタイル画像に依存しないため、どちらでも同じ結果になる)")
    args = parser.parse_args()

    target_cells, lat_step, lon_step = load_target_cells(args.style)
    print(f"対象セル数(23区サブセット、style={args.style}): {len(target_cells)}")

    if not os.path.exists(RAW_CACHE_PATH):
        raise SystemExit(f"生キャッシュが見つかりません: {RAW_CACHE_PATH}\n"
                          "先に ml_risk_model/extract_osm_raw_cache.py を実行してください。")
    with open(RAW_CACHE_PATH, "rb") as f:
        raw = pickle.load(f)
    vehicle_ways = raw["vehicle_ways"]
    print(f"車道way総数(生キャッシュ由来): {len(vehicle_ways)}")

    cell_points = {c: [] for c in target_cells}
    for way in vehicle_ways:
        coords = way["coords"]  # [(lat, lon), ...]
        for i in range(len(coords) - 1):
            lat1, lon1 = coords[i]
            lat2, lon2 = coords[i + 1]
            mid_lat, mid_lon = (lat1 + lat2) / 2, (lon1 + lon2) / 2
            c = cell_of(mid_lat, mid_lon, lat_step, lon_step)
            if c in cell_points:
                cell_points[c].append((mid_lat, mid_lon))

    rng = random.Random(42)
    rows = []
    n_empty = 0
    for (gx, gy), pts in cell_points.items():
        cell_id = f"{GRID_M}m_{gx}_{gy}"
        if not pts:
            n_empty += 1
            continue

        rng.shuffle(pts)
        selected = []
        for lat, lon in pts:
            if len(selected) >= MAX_POINTS_PER_CELL:
                break
            if all(haversine_m(lat, lon, sl, so) >= MIN_SEGMENT_GAP_M for sl, so in selected):
                selected.append((lat, lon))
        if not selected and pts:
            selected = [pts[0]]

        for i, (lat, lon) in enumerate(selected):
            rows.append({"cell_id": cell_id, "point_idx": i, "lat": lat, "lon": lon})

    print(f"車道データが無いセル数: {n_empty} / {len(target_cells)}")
    print(f"サンプル点総数: {len(rows)}")

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["cell_id", "point_idx", "lat", "lon"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"保存(gitignore対象): {OUT_PATH}")


if __name__ == "__main__":
    main()
