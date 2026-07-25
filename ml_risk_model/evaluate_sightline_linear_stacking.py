"""CNN+視界の合成を、浅いGBDT(量子化アーティファクトの疑いあり、
evaluate_sightline_23ku.pyのCNN+視界stackingがCNN単体を-0.079下回った件)
ではなく線形Poissonコンバイナ(sklearn.linear_model.PoissonRegressor)で
行う。

コンバイナの正則化強度(alpha)は、視界を含まない「CNN単体を線形コンバイナに
通しただけ」の対照実験がCNN生予測にどれだけ近いかで選ぶ(視界を使う本番
仮説を見る前に、視界と無関係な基準でハイパーパラメータを決める)。

GSI版パイプライン単体(pale採用)でやり直した版。STUDY_LOG.md参照。
"""
import csv
import glob
import os

import numpy as np
import torch
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import PoissonRegressor

from evaluate_floor_osm import OSM_FEATURE_COLS, POISSON_PARAMS, load_joined, log_vehicle, residual_spearman, to_matrix
from evaluate_sightline_23ku import SIGHTLINE_COLS, load_model, load_sightline, predict_and_extract, to_sight_matrix
from evaluate_subset_23ku import STYLE, load_covered
from train import load_vehicle_length

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def main():
    covered = load_covered()
    sight_by_id = load_sightline()
    train_rows_all = load_joined(STYLE, is_eval=False)
    eval_rows_all = load_joined(STYLE, is_eval=True)
    train_sub = [r for r in train_rows_all if r["cell_id"] in covered]
    eval_sub = [r for r in eval_rows_all if r["cell_id"] in covered]
    print(f"train_sub={len(train_sub)}件  eval_sub={len(eval_sub)}件")

    y_train = np.array([float(r["accident_count"]) for r in train_sub])
    y_eval = np.array([float(r["accident_count"]) for r in eval_sub])
    log_veh_train = log_vehicle(train_sub)
    log_veh_eval = log_vehicle(eval_sub)

    X_floor_train = np.column_stack([to_matrix(train_sub, ["station_dist", "edge_density", "built_env_fraction"]), log_veh_train])
    X_floor_eval = np.column_stack([to_matrix(eval_sub, ["station_dist", "edge_density", "built_env_fraction"]), log_veh_eval])
    floor_model = HistGradientBoostingRegressor(**POISSON_PARAMS).fit(X_floor_train, y_train)
    floor_pred_eval = floor_model.predict(X_floor_eval)

    X_sight_train_5 = to_sight_matrix(train_sub, sight_by_id)
    X_sight_eval_5 = to_sight_matrix(eval_sub, sight_by_id)

    vlt = load_vehicle_length(os.path.join(BASE_DIR, "osm_features", f"osm_features_train_{STYLE}.csv"))
    vle = load_vehicle_length(os.path.join(BASE_DIR, "osm_features", f"osm_features_eval_{STYLE}.csv"))
    with open(os.path.join(BASE_DIR, "dataset", f"manifest_train_counts_500m_{STYLE}.csv"), encoding="utf-8") as f:
        tip = {
            r["cell_id"]: r["image_path"] for r in csv.DictReader(f)
            if r.get("source_cell_id", r["cell_id"]) == r["cell_id"]
        }
    with open(os.path.join(BASE_DIR, "eval_frozen", STYLE, "500m", "eval_manifest.csv"), encoding="utf-8") as f:
        eip = {r["cell_id"]: r["image_path"] for r in csv.DictReader(f)}
    train_img_rows = [{"cell_id": r["cell_id"], "image_path": tip[r["cell_id"]]} for r in train_sub]
    eval_img_rows = [{"cell_id": r["cell_id"], "image_path": eip[r["cell_id"]]} for r in eval_sub]

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model_paths = sorted(glob.glob(os.path.join(BASE_DIR, "models", f"risk_model_500m_{STYLE}_poisson_seed*_epoch15.pt")))
    cids_tr = [r["cell_id"] for r in train_sub]
    cids_ev = [r["cell_id"] for r in eval_sub]

    # --- alphaの選定: 視界なし(CNN単体を線形コンバイナに通すだけ)がCNN生予測に
    #     最も近くなるalphaを選ぶ(視界仮説を見る前の基準で決める) ---
    alphas = [1e-4, 1e-3, 1e-2, 1e-1, 1.0]
    print("=== alpha選定(CNN単体、視界なし、run1のみで予備確認) ===")
    path0 = model_paths[0]
    model0 = load_model(path0).to(device)
    pt0, _ = predict_and_extract(model0, train_img_rows, vlt, device)
    pe0, _ = predict_and_extract(model0, eval_img_rows, vle, device)
    cnn_pred_train0 = np.array([pt0[c] for c in cids_tr])
    cnn_pred_eval0 = np.array([pe0[c] for c in cids_ev])
    raw_cnn_train0 = np.log(cnn_pred_train0) - log_veh_train
    raw_cnn_eval0 = np.log(cnn_pred_eval0) - log_veh_eval
    rho_raw0, _ = residual_spearman(cnn_pred_eval0, floor_pred_eval, y_eval)
    print(f"CNN生予測(参考): {rho_raw0:.3f}")
    best_alpha, best_diff = None, None
    for alpha in alphas:
        Xtr = np.column_stack([raw_cnn_train0, log_veh_train])
        Xev = np.column_stack([raw_cnn_eval0, log_veh_eval])
        reg = PoissonRegressor(alpha=alpha, max_iter=2000).fit(Xtr, y_train)
        pred = reg.predict(Xev)
        rho, _ = residual_spearman(pred, floor_pred_eval, y_eval)
        diff = abs(rho - rho_raw0)
        print(f"alpha={alpha}: 線形再構成(視界なし)={rho:.3f}  |diff|={diff:.3f}")
        if best_diff is None or diff < best_diff:
            best_diff, best_alpha = diff, alpha
    print(f"選定alpha: {best_alpha}\n")

    # --- 本評価: 各run ---
    stacking_rhos = []
    cnn_alone_rhos = []
    for path in model_paths:
        model = load_model(path).to(device)
        pt, _ = predict_and_extract(model, train_img_rows, vlt, device)
        pe, _ = predict_and_extract(model, eval_img_rows, vle, device)
        cnn_pred_train = np.array([pt[c] for c in cids_tr])
        cnn_pred_eval = np.array([pe[c] for c in cids_ev])
        rho_alone, _ = residual_spearman(cnn_pred_eval, floor_pred_eval, y_eval)
        cnn_alone_rhos.append(rho_alone)

        raw_cnn_train = np.log(cnn_pred_train) - log_veh_train
        raw_cnn_eval = np.log(cnn_pred_eval) - log_veh_eval

        X_train = np.column_stack([raw_cnn_train, X_sight_train_5, log_veh_train])
        X_eval = np.column_stack([raw_cnn_eval, X_sight_eval_5, log_veh_eval])
        reg = PoissonRegressor(alpha=best_alpha, max_iter=2000).fit(X_train, y_train)
        pred_eval = reg.predict(X_eval)
        rho, _ = residual_spearman(pred_eval, floor_pred_eval, y_eval)
        stacking_rhos.append(rho)
        print(f"{os.path.basename(path)}: CNN単体={rho_alone:.3f}  CNN+視界(線形コンバイナ)={rho:.3f}")

    stacking_rhos = np.array(stacking_rhos)
    cnn_alone_rhos = np.array(cnn_alone_rhos)
    cnn_alone_mean, cnn_alone_std = float(cnn_alone_rhos.mean()), float(cnn_alone_rhos.std())
    threshold = 2 * cnn_alone_std

    print(f"\nCNN単体({len(model_paths)}run平均): {cnn_alone_mean:.3f} ± {cnn_alone_std:.3f}")
    print(f"CNN+視界(線形コンバイナ、{len(model_paths)}run平均): {stacking_rhos.mean():.3f} ± {stacking_rhos.std():.3f}")
    print(f"CNN単体からの上乗せ: {stacking_rhos.mean() - cnn_alone_mean:+.3f}")
    print(f"判定閾値(seed std×2): {threshold:.3f}")

    import json
    result = {
        "tile_style": STYLE,
        "selected_alpha": best_alpha,
        "cnn_alone": {"per_run": cnn_alone_rhos.tolist(), "mean": cnn_alone_mean, "std": cnn_alone_std},
        "cnn_plus_sightline_linear": {"per_run": stacking_rhos.tolist(), "mean": float(stacking_rhos.mean()), "std": float(stacking_rhos.std())},
        "uplift": float(stacking_rhos.mean() - cnn_alone_mean),
        "threshold_2x_cnn_seed_std": threshold,
    }
    out_path = os.path.join(BASE_DIR, "eval_frozen", STYLE, "500m", "sightline_linear_stacking_result.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n保存: {out_path}")


if __name__ == "__main__":
    main()
