"""過分散の最終確認: フロア・OSM・CNNそれぞれのPoisson予測に対する条件付き
Pearson残差の分散(全域eval)。

周辺の分散/平均比は共変量で説明される分の分散も含むため、各モデルの予測値muで
条件付けたPearson残差の分散を見る必要がある。あわせて、Poissonの分布仮定を
外した単純Spearman(mu, y)でも同じ順位(CNN>OSM>フロアが期待値)が保たれるかを
確認し、NB/ZIPへの切り替えが必要かどうかを最終判断する。

CNN学習後(train.py実行後)に使うこと。それまでは実行できない。
"""
import argparse
import csv
import glob
import json
import os

import numpy as np
import torch
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor

from evaluate_cnn import load_model, predict_cnn
from evaluate_floor_osm import OSM_FEATURE_COLS, POISSON_PARAMS, load_joined, log_vehicle, to_matrix
from tiles import DEFAULT_TILE_STYLE
from train import load_vehicle_length

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def pearson_dispersion(y, mu_hat):
    pearson_resid = (y - mu_hat) / np.sqrt(np.clip(mu_hat, 1e-6, None))
    dispersion = np.sum(pearson_resid ** 2) / (len(y) - 1)
    return dispersion


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--style", choices=["std", "pale"], default=DEFAULT_TILE_STYLE)
    parser.add_argument("--cnn-model", required=True,
                         help="代表として使う1本のCNNチェックポイント(例: models/risk_model_500m_std_poisson_seed42_epoch15.pt)")
    args = parser.parse_args()
    style = args.style

    train_rows = load_joined(style, is_eval=False)
    eval_rows = load_joined(style, is_eval=True)
    y_train = np.array([float(r["accident_count"]) for r in train_rows])
    y_eval = np.array([float(r["accident_count"]) for r in eval_rows])
    cell_ids_eval = [r["cell_id"] for r in eval_rows]

    X_floor_train = np.column_stack([
        to_matrix(train_rows, ["station_dist", "edge_density", "built_env_fraction"]), log_vehicle(train_rows),
    ])
    X_floor_eval = np.column_stack([
        to_matrix(eval_rows, ["station_dist", "edge_density", "built_env_fraction"]), log_vehicle(eval_rows),
    ])
    X_osm_train = np.column_stack([to_matrix(train_rows, OSM_FEATURE_COLS), log_vehicle(train_rows)])
    X_osm_eval = np.column_stack([to_matrix(eval_rows, OSM_FEATURE_COLS), log_vehicle(eval_rows)])

    floor_model = HistGradientBoostingRegressor(**POISSON_PARAMS).fit(X_floor_train, y_train)
    osm_model = HistGradientBoostingRegressor(**POISSON_PARAMS).fit(X_osm_train, y_train)
    mu_floor = floor_model.predict(X_floor_eval)
    mu_osm = osm_model.predict(X_osm_eval)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    eval_dir = os.path.join(BASE_DIR, "eval_frozen", style, "500m")
    with open(os.path.join(eval_dir, "eval_manifest.csv"), encoding="utf-8") as f:
        eval_manifest_rows = list(csv.DictReader(f))
    osm_eval_path = os.path.join(BASE_DIR, "osm_features", f"osm_features_eval_{style}.csv")
    vehicle_length_lookup = load_vehicle_length(osm_eval_path)
    model = load_model(args.cnn_model).to(device)
    pred_by_cell = predict_cnn(model, eval_manifest_rows, vehicle_length_lookup, device)
    mu_cnn = np.array([pred_by_cell[cid] for cid in cell_ids_eval])

    print(f"=== 条件付きPearson分散(全域eval, n={len(y_eval)}) ===")
    results = {"tile_style": style}
    for name, mu in [("floor", mu_floor), ("osm", mu_osm), ("cnn", mu_cnn)]:
        disp = pearson_dispersion(y_eval, mu)
        rho, _ = spearmanr(mu, y_eval)
        results[name] = {"dispersion": float(disp), "simple_spearman": float(rho)}
        print(f"{name}: 条件付き分散/平均比={disp:.2f}  単純Spearman(mu, y)={rho:.3f}")

    out_path = os.path.join(eval_dir, "final_overdispersion_check.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n保存: {out_path}")


if __name__ == "__main__":
    main()
