"""trainブロック内の全セル(都境界フィルタ済み、選抜なし)を事故件数(0を含む)付きで
列挙し、train.pyが使えるmanifestを作る(件数/率回帰設計)。

正例/負例への分類・層化サンプリング・負例マッチングは一切行わない。選抜がない分、
Cohen's dのような交絡確認は不要になる(全数を使うため)。
"""
import csv
import os

from build_dataset import build_cell_counts, load_accidents
from build_eval_set import built_env_fraction, ensure_image
from cell_enumeration import enumerate_all_cells
from edge_density import edge_density
from spatial_block_split import BLOCK_SIZE_M, BUFFER_M, GRID_M, assign_blocks, block_grid_steps
from station_points import load_station_points, nearest_station_distance
from tiles import DEFAULT_TILE_STYLE, GRID_CONFIGS, grid_steps

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SPLIT_SEED = 10  # spatial_block_split.py / build_eval_set.pyと同じシード(同一分割を再現する)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--style", choices=["std", "pale"], default=DEFAULT_TILE_STYLE,
                         help="地理院タイルの種別(std=標準地図, pale=淡色地図)")
    args = parser.parse_args()
    style = args.style

    station_points = load_station_points()

    accidents = load_accidents()
    lat_step, lon_step = grid_steps(GRID_M)
    zoom = GRID_CONFIGS[GRID_M]["zoom"]
    counts = build_cell_counts(accidents, lat_step, lon_step)
    positive_cells_all = list(counts.keys())

    block_lat_step, block_lon_step = block_grid_steps(BLOCK_SIZE_M)
    block_of_cell, val_blocks, train_blocks = assign_blocks(
        positive_cells_all, lat_step, lon_step, block_lat_step, block_lon_step, SPLIT_SEED,
    )
    print(f"trainブロック: {len(train_blocks)}件  valブロック: {len(val_blocks)}件(除外対象)")

    print("trainブロック内の全セルを列挙中(都境界フィルタ・valバッファ除外込み、選抜なし)...")
    train_cells = enumerate_all_cells(
        train_blocks, lat_step, lon_step, block_lat_step, block_lon_step,
        val_blocks=val_blocks, buffer_m=BUFFER_M,
    )
    n_pos = sum(1 for c in train_cells if counts.get(c, 0) >= 1)
    print(f"train全セル: {len(train_cells)}件(うち事故あり{n_pos}件、事故なし{len(train_cells) - n_pos}件)")

    def cell_latlon(gx, gy):
        return (gy + 0.5) * lat_step, (gx + 0.5) * lon_step

    print(f"セル画像を確認/取得中(スタイル: {style})...")
    manifest_rows = []
    for i, (gx, gy) in enumerate(train_cells):
        accident_count = counts.get((gx, gy), 0)
        label_dir = 1 if accident_count >= 1 else 0  # 画像保存先ディレクトリの都合のみ。ターゲットはaccident_count
        cell_id, img_path = ensure_image(gx, gy, lat_step, lon_step, zoom, label_dir, style=style)
        lat, lon = cell_latlon(gx, gy)
        manifest_rows.append({
            "grid_m": GRID_M, "cell_id": cell_id, "accident_count": accident_count,
            "lat_center": lat, "lon_center": lon,
            "station_dist": nearest_station_distance(lat, lon, station_points),
            "edge_density": edge_density(img_path),
            "built_env_fraction": built_env_fraction(img_path),
            "image_path": img_path, "source_cell_id": cell_id,
        })
        if (i + 1) % 200 == 0:
            print(f"  {i + 1}/{len(train_cells)}件処理済み")

    manifest_path = os.path.join(BASE_DIR, "dataset", f"manifest_train_counts_500m_{style}.csv")
    with open(manifest_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(manifest_rows[0].keys()))
        writer.writeheader()
        writer.writerows(manifest_rows)

    print(f"\nmanifest: {manifest_path} ({len(manifest_rows)}件)")


if __name__ == "__main__":
    main()
