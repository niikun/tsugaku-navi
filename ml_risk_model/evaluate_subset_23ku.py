"""23区×PLATEAUカバレッジ完全セルのサブセットで、フロア・OSM・CNNを再計算する。

視界特徴(plateau/)は23区カバレッジ完全セルにしか存在しないため、視界特徴との
比較はすべてこのサブセット上で行う必要がある(全域の数字と混ぜない)。
CNNは全域trainで学習済みの3runモデルを推論のみで使う。フロア・OSMは
このサブセットのtrain側で再学習する(視界モデルと同じデータ量で公平に
比較するため)。

**2026-07-25、GSI版パイプライン単体でやり直した版**: 旧OSM版の結論
(視界特徴に精度面の追加価値なし)を根拠に優先度を下げていたが、これは
「OSM版に触れない」方針と矛盾するため撤回した。std/pale比較で判明した
通り、CNNが画像から拾う情報の性質はタイルソースに対して敏感であり、
旧OSM版の結論をGSI版に流用できる保証はない。フロア・OSM・CNNの数値は
すべてこのリポジトリのGSI版(pale採用)パイプラインで再計算する。
"""
import csv
import glob
import json
import os

import numpy as np
import torch
from PIL import Image
from sklearn.ensemble import HistGradientBoostingRegressor
from torch import nn
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms
from torchvision.models import mobilenet_v2

from evaluate_floor_osm import OSM_FEATURE_COLS, POISSON_PARAMS, conditional_dispersion, load_joined, log_vehicle, residual_spearman, to_matrix
from train import IMAGENET_MEAN, IMAGENET_STD, load_vehicle_length

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PLATEAU_DIR = os.path.join(BASE_DIR, "..", "plateau")
COVERED_CELLS_PATH = os.path.join(PLATEAU_DIR, "plateau_data", "covered_cells_23ku.txt")
STYLE = "pale"  # std/pale比較の結果、採用したタイル種別(STUDY_LOG.md参照)

val_transform = transforms.Compose([
    transforms.ToTensor(),
    transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
])


def load_covered():
    with open(COVERED_CELLS_PATH, encoding="utf-8") as f:
        return set(l.strip() for l in f if l.strip())


def build_model():
    model = mobilenet_v2(weights=None)
    in_features = model.classifier[1].in_features
    model.classifier[1] = nn.Linear(in_features, 1)
    return model


def load_model(path):
    model = build_model()
    checkpoint = torch.load(path, map_location="cpu")
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()
    return model


class EvalCountDataset(Dataset):
    def __init__(self, rows, vehicle_length_lookup):
        self.rows = rows
        self.vehicle_length_lookup = vehicle_length_lookup

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, idx):
        row = self.rows[idx]
        img_path = os.path.join(BASE_DIR, row["image_path"])
        image = Image.open(img_path).convert("RGB")
        vehicle_len = self.vehicle_length_lookup.get(row["cell_id"], 0.0)
        log_exposure = torch.log(torch.tensor(vehicle_len + 1.0, dtype=torch.float32))
        return val_transform(image), log_exposure, row["cell_id"]


def predict_cnn(model, rows, vehicle_length_lookup, device):
    loader = DataLoader(EvalCountDataset(rows, vehicle_length_lookup), batch_size=8, shuffle=False)
    cell_ids, preds = [], []
    with torch.no_grad():
        for images, log_exposure, cids in loader:
            images, log_exposure = images.to(device), log_exposure.to(device)
            raw = model(images).squeeze(-1)
            log_pred = raw + log_exposure
            preds.extend(log_pred.exp().cpu().tolist())
            cell_ids.extend(cids)
    return dict(zip(cell_ids, preds))


def main():
    covered = load_covered()
    print(f"23区・PLATEAUカバレッジ完全セル: {len(covered)}件")

    train_rows = load_joined(STYLE, is_eval=False)
    eval_rows = load_joined(STYLE, is_eval=True)

    train_sub = [r for r in train_rows if r["cell_id"] in covered]
    eval_sub = [r for r in eval_rows if r["cell_id"] in covered]
    train_out = [r for r in train_rows if r["cell_id"] not in covered]
    eval_out = [r for r in eval_rows if r["cell_id"] not in covered]

    def stats(rows):
        counts = [float(r["accident_count"]) for r in rows]
        pos_rate = sum(1 for c in counts if c >= 1) / len(counts)
        return len(rows), np.mean(counts), pos_rate

    n_tr_in, mean_tr_in, pos_tr_in = stats(train_sub)
    n_tr_out, mean_tr_out, pos_tr_out = stats(train_out)
    n_ev_in, mean_ev_in, pos_ev_in = stats(eval_sub)
    n_ev_out, mean_ev_out, pos_ev_out = stats(eval_out)

    print(f"train: kept(23ku内)={n_tr_in}(mean_count={mean_tr_in:.3f}, pos_rate={pos_tr_in:.3f}) "
          f"dropped={n_tr_out}(mean_count={mean_tr_out:.3f}, pos_rate={pos_tr_out:.3f})")
    print(f"eval:  kept(23ku内)={n_ev_in}(mean_count={mean_ev_in:.3f}, pos_rate={pos_ev_in:.3f}) "
          f"dropped={n_ev_out}(mean_count={mean_ev_out:.3f}, pos_rate={pos_ev_out:.3f})")

    y_train = np.array([float(r["accident_count"]) for r in train_sub])
    y_eval = np.array([float(r["accident_count"]) for r in eval_sub])

    X_floor_train = np.column_stack([
        to_matrix(train_sub, ["station_dist", "edge_density", "built_env_fraction"]), log_vehicle(train_sub),
    ])
    X_floor_eval = np.column_stack([
        to_matrix(eval_sub, ["station_dist", "edge_density", "built_env_fraction"]), log_vehicle(eval_sub),
    ])
    X_osm_train = np.column_stack([to_matrix(train_sub, OSM_FEATURE_COLS), log_vehicle(train_sub)])
    X_osm_eval = np.column_stack([to_matrix(eval_sub, OSM_FEATURE_COLS), log_vehicle(eval_sub)])

    floor_model = HistGradientBoostingRegressor(**POISSON_PARAMS).fit(X_floor_train, y_train)
    osm_model = HistGradientBoostingRegressor(**POISSON_PARAMS).fit(X_osm_train, y_train)

    floor_pred_eval = floor_model.predict(X_floor_eval)
    osm_pred_eval = osm_model.predict(X_osm_eval)

    disp_floor_eval = conditional_dispersion(y_eval, floor_pred_eval)
    disp_osm_eval = conditional_dispersion(y_eval, osm_pred_eval)
    print(f"\n条件付き過分散(23区サブセット、eval): フロア={disp_floor_eval:.2f} OSM={disp_osm_eval:.2f}")

    rho_floor_self, _ = residual_spearman(floor_pred_eval, floor_pred_eval, y_eval)
    rho_osm, _ = residual_spearman(osm_pred_eval, floor_pred_eval, y_eval)
    print(f"\n=== 23区サブセット・残差Spearman ===")
    print(f"フロア自身: {rho_floor_self:.3f}(健全性チェック)")
    print(f"OSM: {rho_osm:.3f}")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    vehicle_length_lookup = load_vehicle_length(
        os.path.join(BASE_DIR, "osm_features", f"osm_features_eval_{STYLE}.csv"))
    with open(os.path.join(BASE_DIR, "eval_frozen", STYLE, "500m", "eval_manifest.csv"), encoding="utf-8") as f:
        image_path_by_id = {r["cell_id"]: r["image_path"] for r in csv.DictReader(f)}
    cell_ids_sub = [r["cell_id"] for r in eval_sub]
    cnn_rows = [{"cell_id": cid, "image_path": image_path_by_id[cid]} for cid in cell_ids_sub]

    model_paths = sorted(glob.glob(os.path.join(BASE_DIR, "models", f"risk_model_500m_{STYLE}_poisson_seed*_epoch15.pt")))
    cnn_rhos = []
    for path in model_paths:
        model = load_model(path).to(device)
        pred_by_cell = predict_cnn(model, cnn_rows, vehicle_length_lookup, device)
        cnn_pred_eval = np.array([pred_by_cell[cid] for cid in cell_ids_sub])
        rho, _ = residual_spearman(cnn_pred_eval, floor_pred_eval, y_eval)
        cnn_rhos.append(rho)
        print(f"{os.path.basename(path)}: 残差Spearman(23区サブセット)={rho:.3f}")

    cnn_rhos = np.array(cnn_rhos)
    cnn_mean, cnn_std = float(cnn_rhos.mean()), float(cnn_rhos.std())
    threshold = 2 * cnn_std
    print(f"\nCNN 3run平均(23区サブセット): {cnn_mean:.3f} ± {cnn_std:.3f}")
    print(f"事前登録する閾値(seed std×2): {threshold:.3f}")

    result = {
        "tile_style": STYLE,
        "n_covered_cells": len(covered),
        "train_kept": {"n": n_tr_in, "mean_count": mean_tr_in, "pos_rate": pos_tr_in},
        "train_dropped": {"n": n_tr_out, "mean_count": mean_tr_out, "pos_rate": pos_tr_out},
        "eval_kept": {"n": n_ev_in, "mean_count": mean_ev_in, "pos_rate": pos_ev_in},
        "eval_dropped": {"n": n_ev_out, "mean_count": mean_ev_out, "pos_rate": pos_ev_out},
        "conditional_dispersion_eval": {"floor": disp_floor_eval, "osm": disp_osm_eval},
        "residual_spearman_23ku_subset": {
            "floor_self": rho_floor_self, "osm": rho_osm,
            "cnn_per_seed": cnn_rhos.tolist(), "cnn_mean": cnn_mean, "cnn_std": cnn_std,
        },
        "preregistered_threshold_2x_cnn_seed_std": threshold,
    }
    out_dir = os.path.join(BASE_DIR, "eval_frozen", STYLE, "500m")
    out_path = os.path.join(out_dir, "subset_23ku_result.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n保存: {out_path}")


if __name__ == "__main__":
    main()
