"""OSM版CNN(0.376±0.033、4年フロア基準)とGSI版CNNを「タイルソースのみ変えた」
真に同一の物差しで比較するための、セル集合・正解ラベルを固定した再構築。

背景: 当初のGSI版評価(evaluate_cnn.py --style std、結果0.484±0.010)は、
このリポジトリの事故CSV(2018〜2024年、7年分)を使って独自にspatial_block_split
からやり直していたため、旧OSM版の評価(2021〜2024年ラベル固定、n=919)とは
セル集合もラベルも異なっていた(検証の結果、eval側の重複はわずか159/919件)。
これはユーザー指摘により発覚した(「複数の変更を同時にした後、物差しがずれて
いないか」の確認)。

このスクリプトは、旧リポジトリの凍結manifest(`../traffic_accident/ml_risk_model/
dataset/manifest_train_v3_counts_500m.csv`・`eval_frozen/500m_v3_counts/
eval_manifest.csv`)から**cell_id・accident_countのみ**(どちらもOSM非依存:
グリッド座標の数値計算と警察庁データ)を借用し、それ以外(画像・station_dist・
edge_density・built_env_fraction・OSM特徴量)はすべてこのリポジトリの
GSIタイル・自前パイプラインで新規に計算し直す。station_dist_m(旧: Overpass API
由来)・画像・OSM特徴量は一切コピーしない。

出力先はdataset_v4match/ / eval_frozen_v4match/ で、本番のdataset/std/
eval_frozen/stdとは分離する(この比較専用の実験であり、本番パイプラインの
出力を汚染しないため)。
"""
import csv
import os

from build_eval_set import built_env_fraction
from edge_density import edge_density
from station_points import load_station_points, nearest_station_distance
from tiles import DEFAULT_TILE_STYLE, GRID_CONFIGS, build_cell_image, cell_bbox, grid_steps

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OLD_REPO = os.path.join(BASE_DIR, "..", "..", "traffic_accident", "ml_risk_model")
OLD_EVAL_MANIFEST = os.path.join(OLD_REPO, "eval_frozen", "500m_v3_counts", "eval_manifest.csv")
OLD_TRAIN_MANIFEST = os.path.join(OLD_REPO, "dataset", "manifest_train_v3_counts_500m.csv")

OUT_DATASET_DIR = os.path.join(BASE_DIR, "dataset_v4match")
OUT_EVAL_DIR = os.path.join(BASE_DIR, "eval_frozen_v4match", "500m")

GRID_M = 500


def parse_cell_id(cell_id):
    _, gx, gy = cell_id.split("_")
    return int(gx), int(gy)


def load_old_cells(path, dedup_source=False):
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if dedup_source:
        rows = [r for r in rows if r.get("source_cell_id", r["cell_id"]) == r["cell_id"]]
    out = []
    for r in rows:
        gx, gy = parse_cell_id(r["cell_id"])
        out.append({"cell_id": r["cell_id"], "gx": gx, "gy": gy, "accident_count": int(r["accident_count"])})
    return out


def ensure_image_for_cell(gx, gy, lat_step, lon_step, zoom, label, out_dir, style):
    d = os.path.join(out_dir, str(label))
    os.makedirs(d, exist_ok=True)
    cell_id = f"{GRID_M}m_{gx}_{gy}"
    img_path = os.path.join(d, f"{cell_id}.png")
    if not os.path.exists(img_path):
        lat_min, lat_max, lon_min, lon_max = cell_bbox(gx, gy, lat_step, lon_step)
        img = build_cell_image(lat_min, lat_max, lon_min, lon_max, zoom, style=style)
        img.save(img_path)
    return cell_id, img_path


def build_manifest(cells, out_dir, station_points, lat_step, lon_step, zoom, style, progress_label):
    rows = []
    for i, c in enumerate(cells):
        label_dir = 1 if c["accident_count"] >= 1 else 0
        cell_id, img_path = ensure_image_for_cell(
            c["gx"], c["gy"], lat_step, lon_step, zoom, label_dir, out_dir, style)
        lat = (c["gy"] + 0.5) * lat_step
        lon = (c["gx"] + 0.5) * lon_step
        rows.append({
            "grid_m": GRID_M, "cell_id": cell_id, "accident_count": c["accident_count"],
            "lat_center": lat, "lon_center": lon,
            "station_dist": nearest_station_distance(lat, lon, station_points),
            "edge_density": edge_density(img_path),
            "built_env_fraction": built_env_fraction(img_path),
            "image_path": img_path, "source_cell_id": cell_id,
        })
        if (i + 1) % 200 == 0:
            print(f"  [{progress_label}] {i + 1}/{len(cells)}件処理済み")
    return rows


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--style", choices=["std", "pale"], default=DEFAULT_TILE_STYLE)
    args = parser.parse_args()
    style = args.style

    if not os.path.exists(OLD_EVAL_MANIFEST):
        raise SystemExit(f"旧リポジトリの凍結manifestが見つかりません: {OLD_EVAL_MANIFEST}")

    eval_cells = load_old_cells(OLD_EVAL_MANIFEST)
    train_cells = load_old_cells(OLD_TRAIN_MANIFEST, dedup_source=True)
    print(f"旧4年フロア基準の凍結セル集合を読み込み: train={len(train_cells)}件 eval={len(eval_cells)}件")

    station_points = load_station_points()
    lat_step, lon_step = grid_steps(GRID_M)
    zoom = GRID_CONFIGS[GRID_M]["zoom"]

    print(f"\ntrainセルの画像取得・特徴計算中(スタイル: {style})...")
    train_out_dir = os.path.join(OUT_DATASET_DIR, style, f"{GRID_M}m")
    train_rows = build_manifest(train_cells, train_out_dir, station_points, lat_step, lon_step, zoom, style, "train")
    os.makedirs(OUT_DATASET_DIR, exist_ok=True)
    train_manifest_path = os.path.join(OUT_DATASET_DIR, f"manifest_train_v4match_500m_{style}.csv")
    with open(train_manifest_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(train_rows[0].keys()))
        w.writeheader()
        w.writerows(train_rows)
    print(f"train manifest: {train_manifest_path} ({len(train_rows)}件)")

    print(f"\nevalセルの画像取得・特徴計算中(スタイル: {style})...")
    eval_out_dir = os.path.join(BASE_DIR, "eval_frozen_v4match", style, f"{GRID_M}m")
    eval_rows = build_manifest(eval_cells, eval_out_dir, station_points, lat_step, lon_step, zoom, style, "eval")
    for r in eval_rows:
        r["lat"] = r.pop("lat_center")
        r["lon"] = r.pop("lon_center")
        r["station_dist_m"] = r.pop("station_dist")
        del r["source_cell_id"]
    eval_manifest_path = os.path.join(eval_out_dir, "eval_manifest.csv")
    with open(eval_manifest_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(eval_rows[0].keys()))
        w.writeheader()
        w.writerows(eval_rows)
    print(f"eval manifest: {eval_manifest_path} ({len(eval_rows)}件)")


if __name__ == "__main__":
    main()
