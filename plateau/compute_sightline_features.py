"""カバレッジ完全なセル(covered_cells_23ku.txt)の車道サンプル点について、
PLATEAU LOD1建物データから視界特徴を計算し、セル単位に集計する。
"""
import csv
import os
import time

import numpy as np
from pyproj import Transformer

from plateau.parquet_index import build_index_from_parquet
from plateau.sightline import PlateauSightlineAnalyzer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARQUET_PATH = os.path.join(BASE_DIR, "plateau_data", "buildings_23ku.parquet")
ROAD_POINTS_PATH = os.path.join(BASE_DIR, "plateau_data", "road_sample_points_23ku.csv")
COVERED_CELLS_PATH = os.path.join(BASE_DIR, "plateau_data", "covered_cells_23ku.txt")
OUT_PATH = os.path.join(BASE_DIR, "plateau_data", "sightline_features_23ku.csv")


def main():
    with open(COVERED_CELLS_PATH) as f:
        covered_cells = set(line.strip() for line in f)
    print(f"対象セル(カバレッジ完全): {len(covered_cells)}")

    with open(ROAD_POINTS_PATH, encoding="utf-8") as f:
        road_points = [r for r in csv.DictReader(f) if r["cell_id"] in covered_cells]
    print(f"対象車道サンプル点: {len(road_points)}")

    print("\n建物インデックスを構築中(全671メッシュ、約177万棟、数分かかる見込み)...")
    t0 = time.time()
    index = build_index_from_parquet(PARQUET_PATH)
    print(f"インデックス構築完了: {len(index)}棟 ({time.time()-t0:.1f}秒)")

    analyzer = PlateauSightlineAnalyzer(index)
    transformer = Transformer.from_crs("EPSG:6668", "EPSG:6677", always_xy=True)

    print("\n視界特徴を計算中...")
    t0 = time.time()
    point_feats = []
    for i, r in enumerate(road_points):
        lat, lon = float(r["lat"]), float(r["lon"])
        x, y = transformer.transform(lon, lat)
        feats = analyzer.compute_features(x, y)
        point_feats.append({
            "cell_id": r["cell_id"],
            "mean_sightline_dist": feats["mean_sightline_dist"],
            "min_sightline_dist": feats["min_sightline_dist"],
            "std_sightline_dist": feats["std_sightline_dist"],
            "open_fraction": feats["open_fraction"],
        })
        if (i + 1) % 2000 == 0:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed
            remaining = (len(road_points) - i - 1) / rate
            print(f"  {i + 1}/{len(road_points)}点処理済み ({elapsed:.1f}秒経過, 残り約{remaining:.0f}秒)")

    print(f"\n点単位の計算完了: {time.time()-t0:.1f}秒")

    # セル単位に集計(点の平均・最小値の平均・開放方向割合の平均など)
    by_cell = {}
    for pf in point_feats:
        by_cell.setdefault(pf["cell_id"], []).append(pf)

    rows = []
    for cell_id, feats_list in by_cell.items():
        mean_dists = [f["mean_sightline_dist"] for f in feats_list]
        min_dists = [f["min_sightline_dist"] for f in feats_list]
        std_dists = [f["std_sightline_dist"] for f in feats_list]
        open_fracs = [f["open_fraction"] for f in feats_list]
        rows.append({
            "cell_id": cell_id,
            "n_points": len(feats_list),
            "sightline_mean_of_mean": np.mean(mean_dists),
            "sightline_mean_of_min": np.mean(min_dists),
            "sightline_worst_min": np.min(min_dists),
            "sightline_mean_of_std": np.mean(std_dists),
            "sightline_mean_open_fraction": np.mean(open_fracs),
        })

    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nセル単位の視界特徴を保存: {OUT_PATH} ({len(rows)}セル)")


if __name__ == "__main__":
    main()
