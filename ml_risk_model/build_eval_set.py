"""valブロック内の全セル(都境界フィルタ済み、選抜なし)を事故件数(0を含む)付きで凍結する。

セル単位の正例/負例への分類・層化サンプリング・負例マッチングは行わない
(選抜がないため交絡確認そのものが不要になる、全数を評価対象にするため)。
このモジュールは`build_train_set.py`から`ensure_image`/`built_env_fraction`としても
再利用される。
"""
import csv
import hashlib
import json
import os

import numpy as np
from PIL import Image

from build_dataset import build_cell_counts, load_accidents
from cell_enumeration import enumerate_all_cells
from edge_density import edge_density
from spatial_block_split import BLOCK_SIZE_M, BUFFER_M, GRID_M, assign_blocks, block_grid_steps
from station_points import load_station_points, nearest_station_distance
from tiles import DEFAULT_TILE_STYLE, GRID_CONFIGS, build_cell_image, cell_bbox, grid_steps

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SPLIT_SEED = 10  # spatial_block_split.pyで確認済みの偏りのないシードを使うこと


def eval_dir(style):
    return os.path.join(BASE_DIR, "eval_frozen", style, f"{GRID_M}m")


def built_env_fraction(image_path):
    """緑・水色以外のピクセル比率(建造物率の簡易代理指標、エッジ密度とは独立)。
    地理院タイル(std)は水域=薄い青、緑地=薄緑が典型的なので、
    それ以外の色(建物・道路のグレー/白/ベージュ)の比率を建造物率とみなす。
    """
    img = Image.open(os.path.join(BASE_DIR, image_path)).convert("RGB")
    arr = np.asarray(img, dtype=np.int16)
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    is_green = (g > r + 10) & (g > b + 10)
    is_blue = (b > r + 10) & (b > g + 5)
    is_natural = is_green | is_blue
    return float((~is_natural).mean())


def enumerate_block_cells(block_ids, lat_step, lon_step, block_lat_step, block_lon_step, counts):
    """指定ブロック群に含まれる全500mセルを列挙し、正例/負例候補に分類する。"""
    from tokyo_boundary import is_deep_inside_tokyo

    positives, negatives = [], []
    for bgx, bgy in block_ids:
        lat_min, lat_max = bgy * block_lat_step, (bgy + 1) * block_lat_step
        lon_min, lon_max = bgx * block_lon_step, (bgx + 1) * block_lon_step
        gy_min, gy_max = int(lat_min // lat_step), int(lat_max // lat_step)
        gx_min, gx_max = int(lon_min // lon_step), int(lon_max // lon_step)
        for gy in range(gy_min, gy_max + 1):
            for gx in range(gx_min, gx_max + 1):
                lat_center = (gy + 0.5) * lat_step
                lon_center = (gx + 0.5) * lon_step
                cell_bgy = int(lat_center // block_lat_step)
                cell_bgx = int(lon_center // block_lon_step)
                if (cell_bgx, cell_bgy) != (bgx, bgy):
                    continue
                if not is_deep_inside_tokyo(lat_center, lon_center):
                    continue
                if counts.get((gx, gy), 0) >= 1:
                    positives.append((gx, gy))
                else:
                    negatives.append((gx, gy))
    return sorted(set(positives)), sorted(set(negatives))


def ensure_image(gx, gy, lat_step, lon_step, zoom, label, style=DEFAULT_TILE_STYLE):
    out_dir = os.path.join(BASE_DIR, "dataset", style, f"{GRID_M}m", str(label))
    os.makedirs(out_dir, exist_ok=True)
    cell_id = f"{GRID_M}m_{gx}_{gy}"
    img_path = os.path.join(out_dir, f"{cell_id}.png")
    if not os.path.exists(img_path):
        lat_min, lat_max, lon_min, lon_max = cell_bbox(gx, gy, lat_step, lon_step)
        img = build_cell_image(lat_min, lat_max, lon_min, lon_max, zoom, style=style)
        img.save(img_path)
    return cell_id, os.path.relpath(img_path, BASE_DIR)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--style", choices=["std", "pale"], default=DEFAULT_TILE_STYLE,
                         help="地理院タイルの種別(std=標準地図, pale=淡色地図)")
    args = parser.parse_args()
    style = args.style
    EVAL_DIR = eval_dir(style)

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
    print(f"valブロック: {len(val_blocks)}件")

    print("valブロック内の全セルを列挙中(都境界フィルタ込み、選抜なし)...")
    val_cells = enumerate_all_cells(
        val_blocks, lat_step, lon_step, block_lat_step, block_lon_step,
    )
    n_pos = sum(1 for c in val_cells if counts.get(c, 0) >= 1)
    print(f"val全セル: {len(val_cells)}件(うち事故あり{n_pos}件、事故なし{len(val_cells) - n_pos}件)")

    def cell_latlon(gx, gy):
        return (gy + 0.5) * lat_step, (gx + 0.5) * lon_step

    print("セル画像を確認/取得中...")
    rows = []
    os.makedirs(EVAL_DIR, exist_ok=True)
    for i, (gx, gy) in enumerate(val_cells):
        accident_count = counts.get((gx, gy), 0)
        label_dir = 1 if accident_count >= 1 else 0
        cell_id, img_path = ensure_image(gx, gy, lat_step, lon_step, zoom, label_dir, style=style)
        lat, lon = cell_latlon(gx, gy)

        src = os.path.join(BASE_DIR, img_path)
        with open(src, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        frozen_path = os.path.join(EVAL_DIR, os.path.basename(img_path))
        if not os.path.exists(frozen_path):
            with open(src, "rb") as fsrc, open(frozen_path, "wb") as fdst:
                fdst.write(fsrc.read())

        rows.append({
            "grid_m": GRID_M, "cell_id": cell_id, "accident_count": accident_count,
            "lat": lat, "lon": lon,
            "station_dist_m": round(nearest_station_distance(lat, lon, station_points), 1),
            "edge_density": round(edge_density(img_path), 4),
            "built_env_fraction": round(built_env_fraction(img_path), 4),
            "image_path": os.path.relpath(frozen_path, BASE_DIR),
            "sha256": digest,
        })
        if (i + 1) % 200 == 0:
            print(f"  {i + 1}/{len(val_cells)}件処理済み")

    manifest_path = os.path.join(EVAL_DIR, "eval_manifest.csv")
    with open(manifest_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    readme = {
        "tile_style": style,
        "grid_m": GRID_M,
        "block_size_m": BLOCK_SIZE_M,
        "buffer_m": BUFFER_M,
        "split_seed": SPLIT_SEED,
        "n_val_blocks": len(val_blocks),
        "n_cells_total": len(rows),
        "n_cells_with_accidents": n_pos,
        "n_cells_zero": len(rows) - n_pos,
        "design_note": (
            "都境界から500m以上内側にある全valブロックセルをそのまま評価対象とする"
            "(選抜・マッチングなし、件数/率回帰設計)。タイルは地理院タイル(GSI)由来。"
        ),
    }
    with open(os.path.join(EVAL_DIR, "README.json"), "w", encoding="utf-8") as f:
        json.dump(readme, f, ensure_ascii=False, indent=2)

    print(f"\n凍結完了: {manifest_path}")
    print(f"README: {os.path.join(EVAL_DIR, 'README.json')}")


if __name__ == "__main__":
    main()
