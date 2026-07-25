"""正例セルの空間クラスタリングによる近傍記憶リークを防ぐため、
東京をブロック単位(3〜5km四方)でtrain/valに分割する(buffered spatial split)。

セル単位でtrain/valを分けても、valの正例セルのすぐ隣にtrain正例セルが
存在しうるため、「この街区の見た目=危険」というローカルな記憶でval精度が
水増しされる恐れがある。ブロック単位で分割し、さらにvalブロック境界から
一定距離(buffer)以内のtrainセルを除外することで、この経路を構造的に塞ぐ。

分割の妥当性チェックとして、train/val間で正例数・駅からの距離分布に
偏りがないかも確認する(駅位置データはstation_points.py、国土数値情報N02由来。
別リポジトリ(traffic_accident)のOverpass API依存版とは異なる設計)。
"""
import math
import os
import random

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy import stats

from build_dataset import build_cell_counts, load_accidents
from station_points import load_station_points, nearest_station_distance
from tiles import grid_steps

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

GRID_M = 500
BLOCK_SIZE_M = 4000
BUFFER_M = 500
VAL_RATIO = 0.2
RANDOM_SEED = 42


def block_grid_steps(block_m):
    deg_lat_km = 111.0
    deg_lon_km = 111.0 * math.cos(math.radians(35.7))
    block_km = block_m / 1000
    return block_km / deg_lat_km, block_km / deg_lon_km


def assign_blocks(cells, lat_step, lon_step, block_lat_step, block_lon_step, seed):
    """cellsの(gx,gy)ごとにブロックIDを求め、ブロック単位で80/20にtrain/val割当する。"""
    block_of_cell = {}
    blocks = set()
    for gx, gy in cells:
        lat_center = (gy + 0.5) * lat_step
        lon_center = (gx + 0.5) * lon_step
        bgy = int(lat_center // block_lat_step)
        bgx = int(lon_center // block_lon_step)
        block_of_cell[(gx, gy)] = (bgx, bgy)
        blocks.add((bgx, bgy))

    blocks = sorted(blocks)
    rng = random.Random(seed)
    rng.shuffle(blocks)
    n_val = max(1, int(len(blocks) * VAL_RATIO))
    val_blocks = set(blocks[:n_val])
    train_blocks = set(blocks[n_val:])
    return block_of_cell, val_blocks, train_blocks


def find_buffer_excluded(cells, block_of_cell, val_blocks, lat_step, lon_step,
                          block_lat_step, block_lon_step, buffer_m):
    """valブロックの境界からbuffer_m以内のtrainセルを除外対象として返す。"""
    buffer_lat_deg = buffer_m / 111000.0
    buffer_lon_deg = buffer_m / (111000.0 * math.cos(math.radians(35.7)))

    excluded = set()
    for gx, gy in cells:
        bgx, bgy = block_of_cell[(gx, gy)]
        if (bgx, bgy) in val_blocks:
            continue  # valセル自体はそのまま残す
        lat_center = (gy + 0.5) * lat_step
        lon_center = (gx + 0.5) * lon_step

        for dbgx, dbgy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            neighbor = (bgx + dbgx, bgy + dbgy)
            if neighbor not in val_blocks:
                continue
            if dbgy == 1:
                boundary_lat = (bgy + 1) * block_lat_step
                if boundary_lat - lat_center < buffer_lat_deg:
                    excluded.add((gx, gy))
            elif dbgy == -1:
                boundary_lat = bgy * block_lat_step
                if lat_center - boundary_lat < buffer_lat_deg:
                    excluded.add((gx, gy))
            elif dbgx == 1:
                boundary_lon = (bgx + 1) * block_lon_step
                if boundary_lon - lon_center < buffer_lon_deg:
                    excluded.add((gx, gy))
            elif dbgx == -1:
                boundary_lon = bgx * block_lon_step
                if lon_center - boundary_lon < buffer_lon_deg:
                    excluded.add((gx, gy))
    return excluded


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=RANDOM_SEED,
                         help="ブロック分割の乱数シード(駅距離分布が偏った場合に変えて再試行する用)")
    args = parser.parse_args()

    print("国土数値情報N02(鉄道)由来の駅座標を読み込み中...")
    station_points = load_station_points()
    print(f"駅座標: {len(station_points)}件")

    accidents = load_accidents()
    lat_step, lon_step = grid_steps(GRID_M)
    counts = build_cell_counts(accidents, lat_step, lon_step)
    positive_cells = list(counts.keys())
    print(f"正例セル(grid={GRID_M}m): {len(positive_cells)}件")

    block_lat_step, block_lon_step = block_grid_steps(BLOCK_SIZE_M)
    block_of_cell, val_blocks, train_blocks = assign_blocks(
        positive_cells, lat_step, lon_step, block_lat_step, block_lon_step, args.seed,
    )
    print(f"シード: {args.seed}")
    print(f"ブロック数: train={len(train_blocks)} val={len(val_blocks)} (block={BLOCK_SIZE_M}m四方)")

    excluded = find_buffer_excluded(
        positive_cells, block_of_cell, val_blocks,
        lat_step, lon_step, block_lat_step, block_lon_step, BUFFER_M,
    )
    print(f"バッファ({BUFFER_M}m)で除外されたtrain正例セル: {len(excluded)}件")

    train_pos, val_pos = [], []
    for gx, gy in positive_cells:
        bgx, bgy = block_of_cell[(gx, gy)]
        if (bgx, bgy) in val_blocks:
            val_pos.append((gx, gy))
        elif (gx, gy) not in excluded:
            train_pos.append((gx, gy))

    print(f"\n正例セル件数: train={len(train_pos)}  val={len(val_pos)}")

    def cell_latlon(gx, gy):
        return (gy + 0.5) * lat_step, (gx + 0.5) * lon_step

    train_dist = [nearest_station_distance(*cell_latlon(gx, gy), station_points) for gx, gy in train_pos]
    val_dist = [nearest_station_distance(*cell_latlon(gx, gy), station_points) for gx, gy in val_pos]

    u_stat, p_value = stats.mannwhitneyu(train_dist, val_dist, alternative="two-sided")
    n1, n2 = len(train_dist), len(val_dist)
    rank_biserial = 1 - (2 * u_stat) / (n1 * n2)

    print("\n--- 駅からの距離(m): train正例 vs val正例 ---")
    print(f"train: n={n1} mean={np.mean(train_dist):.1f} median={np.median(train_dist):.1f}")
    print(f"val:   n={n2} mean={np.mean(val_dist):.1f} median={np.median(val_dist):.1f}")
    print(f"Mann-Whitney U検定 p値={p_value:.4g}  rank-biserial効果量={rank_biserial:.3f}")
    if p_value < 0.05:
        print("=> train/valで駅距離分布に偏りあり。ブロック分割の乱数シードを変えて再試行を推奨。")
    else:
        print("=> train/valで駅距離分布に有意差なし。妥当な分割。")

    # 可視化: 正例セルをtrain/val/除外で色分けしたプロット
    fig, ax = plt.subplots(figsize=(8, 8))
    for cells, color, label in [
        (train_pos, "tab:blue", f"train positive (n={len(train_pos)})"),
        (val_pos, "tab:red", f"val positive (n={len(val_pos)})"),
        (excluded, "lightgray", f"excluded by buffer (n={len(excluded)})"),
    ]:
        if not cells:
            continue
        lats = [cell_latlon(gx, gy)[0] for gx, gy in cells]
        lons = [cell_latlon(gx, gy)[1] for gx, gy in cells]
        ax.scatter(lons, lats, s=4, c=color, label=label, alpha=0.7)

    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    ax.set_title(f"Block split (block={BLOCK_SIZE_M}m, buffer={BUFFER_M}m) positive cell assignment")
    ax.legend(markerscale=3)
    ax.set_aspect("equal")

    out_path = os.path.join(BASE_DIR, "spatial_block_split.png")
    fig.savefig(out_path, dpi=120, bbox_inches="tight")
    print(f"\n可視化を保存しました: {out_path}")


if __name__ == "__main__":
    main()
