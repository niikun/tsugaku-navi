"""23区×PLATEAUカバレッジ完全セルのサブセットで、視界特徴を含む4構成を評価する。

- 視界単独(5特徴+log曝露量、Poisson GBDT)
- 視界+OSM(5+16特徴+log曝露量、Poisson GBDT)
- CNN+視界スタッキング(CNN予測[各run]+視界5特徴、Poisson GBDT。
  train側もCNN推論が必要なため、epoch15固定モデルでtrain_subに対しても推論する)
- concat(CNNペナルティメイト特徴1280次元+OSM16+視界5、Poisson GBDT、runごと)

フロア予測はサブセットtrain側で学習したモデルをevalに適用する
(evaluate_subset_23ku.pyと同一設定で再学習)。判定閾値は
evaluate_subset_23ku.pyが出力するCNN単体seed std×2を使う(実行後、
このスクリプト内のTHRESHOLD/CNN_ALONE_MEANを更新すること)。

GSI版パイプライン単体でやり直した経緯はevaluate_subset_23ku.py・
STUDY_LOG.md参照。
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

from evaluate_floor_osm import OSM_FEATURE_COLS, POISSON_PARAMS, load_joined, log_vehicle, residual_spearman, to_matrix
from evaluate_subset_23ku import STYLE, load_covered
from train import IMAGENET_MEAN, IMAGENET_STD, load_vehicle_length

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PLATEAU_DIR = os.path.join(BASE_DIR, "..", "plateau")
SIGHTLINE_PATH = os.path.join(PLATEAU_DIR, "plateau_features", "sightline_features_23ku.csv")

SIGHTLINE_COLS = [
    "sightline_mean_of_mean", "sightline_mean_of_min", "sightline_worst_min",
    "sightline_mean_of_std", "sightline_mean_open_fraction",
]

val_transform = transforms.Compose([
    transforms.ToTensor(),
    transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
])


def load_sightline():
    with open(SIGHTLINE_PATH, encoding="utf-8") as f:
        return {r["cell_id"]: r for r in csv.DictReader(f)}


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


class ImageDataset(Dataset):
    def __init__(self, rows, vehicle_length_lookup):
        self.rows = rows
        self.vehicle_length_lookup = vehicle_length_lookup

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, idx):
        row = self.rows[idx]
        image = Image.open(os.path.join(BASE_DIR, row["image_path"])).convert("RGB")
        vehicle_len = self.vehicle_length_lookup.get(row["cell_id"], 0.0)
        log_exposure = torch.log(torch.tensor(vehicle_len + 1.0, dtype=torch.float32))
        return val_transform(image), log_exposure, row["cell_id"]


def predict_and_extract(model, rows, vehicle_length_lookup, device):
    """各セルについて、Poisson予測件数と1280次元ペナルティメイト特徴の両方を返す。"""
    loader = DataLoader(ImageDataset(rows, vehicle_length_lookup), batch_size=8, shuffle=False)
    cell_ids, preds, feats = [], [], []
    with torch.no_grad():
        for images, log_exposure, cids in loader:
            images, log_exposure = images.to(device), log_exposure.to(device)
            x = model.features(images)
            x = nn.functional.adaptive_avg_pool2d(x, (1, 1))
            x = torch.flatten(x, 1)  # 1280次元
            raw = model.classifier(x).squeeze(-1)
            log_pred = raw + log_exposure
            preds.extend(log_pred.exp().cpu().tolist())
            feats.extend(x.cpu().numpy().tolist())
            cell_ids.extend(cids)
    pred_by_cell = dict(zip(cell_ids, preds))
    feat_by_cell = dict(zip(cell_ids, feats))
    return pred_by_cell, feat_by_cell


def to_sight_matrix(rows, sight_by_id):
    return np.array([[float(sight_by_id[r["cell_id"]][c]) for c in SIGHTLINE_COLS] for r in rows])


def main():
    covered = load_covered()
    sight_by_id = load_sightline()

    train_rows_all = load_joined(STYLE, is_eval=False)
    eval_rows_all = load_joined(STYLE, is_eval=True)
    train_sub = [r for r in train_rows_all if r["cell_id"] in covered]
    eval_sub = [r for r in eval_rows_all if r["cell_id"] in covered]
    assert all(r["cell_id"] in sight_by_id for r in train_sub + eval_sub)
    print(f"train_sub={len(train_sub)}件  eval_sub={len(eval_sub)}件")

    y_train = np.array([float(r["accident_count"]) for r in train_sub])
    y_eval = np.array([float(r["accident_count"]) for r in eval_sub])

    X_floor_train = np.column_stack([
        to_matrix(train_sub, ["station_dist", "edge_density", "built_env_fraction"]), log_vehicle(train_sub),
    ])
    X_floor_eval = np.column_stack([
        to_matrix(eval_sub, ["station_dist", "edge_density", "built_env_fraction"]), log_vehicle(eval_sub),
    ])
    floor_model = HistGradientBoostingRegressor(**POISSON_PARAMS).fit(X_floor_train, y_train)
    floor_pred_eval = floor_model.predict(X_floor_eval)

    X_sight_train = np.column_stack([to_sight_matrix(train_sub, sight_by_id), log_vehicle(train_sub)])
    X_sight_eval = np.column_stack([to_sight_matrix(eval_sub, sight_by_id), log_vehicle(eval_sub)])
    sight_model = HistGradientBoostingRegressor(**POISSON_PARAMS).fit(X_sight_train, y_train)
    sight_pred_eval = sight_model.predict(X_sight_eval)
    rho_sight, _ = residual_spearman(sight_pred_eval, floor_pred_eval, y_eval)

    X_sight_osm_train = np.column_stack([
        to_matrix(train_sub, OSM_FEATURE_COLS), to_sight_matrix(train_sub, sight_by_id), log_vehicle(train_sub),
    ])
    X_sight_osm_eval = np.column_stack([
        to_matrix(eval_sub, OSM_FEATURE_COLS), to_sight_matrix(eval_sub, sight_by_id), log_vehicle(eval_sub),
    ])
    sight_osm_model = HistGradientBoostingRegressor(**POISSON_PARAMS).fit(X_sight_osm_train, y_train)
    sight_osm_pred_eval = sight_osm_model.predict(X_sight_osm_eval)
    rho_sight_osm, _ = residual_spearman(sight_osm_pred_eval, floor_pred_eval, y_eval)

    print(f"\n視界単独: {rho_sight:.3f}")
    print(f"視界+OSM: {rho_sight_osm:.3f}")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    vehicle_length_lookup_eval = load_vehicle_length(
        os.path.join(BASE_DIR, "osm_features", f"osm_features_eval_{STYLE}.csv"))
    vehicle_length_lookup_train = load_vehicle_length(
        os.path.join(BASE_DIR, "osm_features", f"osm_features_train_{STYLE}.csv"))

    with open(os.path.join(BASE_DIR, "dataset", f"manifest_train_counts_500m_{STYLE}.csv"), encoding="utf-8") as f:
        train_image_path_by_id = {
            r["cell_id"]: r["image_path"] for r in csv.DictReader(f)
            if r.get("source_cell_id", r["cell_id"]) == r["cell_id"]
        }
    with open(os.path.join(BASE_DIR, "eval_frozen", STYLE, "500m", "eval_manifest.csv"), encoding="utf-8") as f:
        eval_image_path_by_id = {r["cell_id"]: r["image_path"] for r in csv.DictReader(f)}

    train_img_rows = [{"cell_id": r["cell_id"], "image_path": train_image_path_by_id[r["cell_id"]]} for r in train_sub]
    eval_img_rows = [{"cell_id": r["cell_id"], "image_path": eval_image_path_by_id[r["cell_id"]]} for r in eval_sub]

    model_paths = sorted(glob.glob(os.path.join(BASE_DIR, "models", f"risk_model_500m_{STYLE}_poisson_seed*_epoch15.pt")))

    X_sight_train_5 = to_sight_matrix(train_sub, sight_by_id)
    X_sight_eval_5 = to_sight_matrix(eval_sub, sight_by_id)
    X_osm_train_16 = to_matrix(train_sub, OSM_FEATURE_COLS)
    X_osm_eval_16 = to_matrix(eval_sub, OSM_FEATURE_COLS)
    log_veh_train = log_vehicle(train_sub)
    log_veh_eval = log_vehicle(eval_sub)

    stacking_rhos, concat_rhos, cnn_alone_rhos = [], [], []
    cell_ids_train = [r["cell_id"] for r in train_sub]
    cell_ids_eval = [r["cell_id"] for r in eval_sub]

    for path in model_paths:
        print(f"\n=== {os.path.basename(path)} ===")
        model = load_model(path).to(device)
        pred_train, feat_train = predict_and_extract(model, train_img_rows, vehicle_length_lookup_train, device)
        pred_eval, feat_eval = predict_and_extract(model, eval_img_rows, vehicle_length_lookup_eval, device)

        cnn_pred_train = np.array([pred_train[c] for c in cell_ids_train])
        cnn_pred_eval = np.array([pred_eval[c] for c in cell_ids_eval])
        rho_cnn_alone, _ = residual_spearman(cnn_pred_eval, floor_pred_eval, y_eval)
        cnn_alone_rhos.append(rho_cnn_alone)

        X_stack_train = np.column_stack([cnn_pred_train, X_sight_train_5, log_veh_train])
        X_stack_eval = np.column_stack([cnn_pred_eval, X_sight_eval_5, log_veh_eval])
        stack_model = HistGradientBoostingRegressor(**POISSON_PARAMS).fit(X_stack_train, y_train)
        stack_pred_eval = stack_model.predict(X_stack_eval)
        rho_stack, _ = residual_spearman(stack_pred_eval, floor_pred_eval, y_eval)
        stacking_rhos.append(rho_stack)
        print(f"CNN単体: {rho_cnn_alone:.3f}  CNN+視界(stacking): {rho_stack:.3f}")

        cnn_feat_train = np.array([feat_train[c] for c in cell_ids_train])
        cnn_feat_eval = np.array([feat_eval[c] for c in cell_ids_eval])
        X_concat_train = np.column_stack([cnn_feat_train, X_osm_train_16, X_sight_train_5, log_veh_train])
        X_concat_eval = np.column_stack([cnn_feat_eval, X_osm_eval_16, X_sight_eval_5, log_veh_eval])
        concat_model = HistGradientBoostingRegressor(**POISSON_PARAMS).fit(X_concat_train, y_train)
        concat_pred_eval = concat_model.predict(X_concat_eval)
        rho_concat, _ = residual_spearman(concat_pred_eval, floor_pred_eval, y_eval)
        concat_rhos.append(rho_concat)
        print(f"concat(CNN特徴+OSM+視界): {rho_concat:.3f}")

    stacking_rhos = np.array(stacking_rhos)
    concat_rhos = np.array(concat_rhos)
    cnn_alone_rhos = np.array(cnn_alone_rhos)
    cnn_alone_mean, cnn_alone_std = float(cnn_alone_rhos.mean()), float(cnn_alone_rhos.std())
    threshold = 2 * cnn_alone_std

    print("\n=== まとめ(23区サブセット、残差Spearman) ===")
    print(f"フロア自身: 0.000")
    print(f"OSM: (evaluate_subset_23ku.pyの出力参照)")
    print(f"CNN単体({len(model_paths)}run平均): {cnn_alone_mean:.3f} ± {cnn_alone_std:.3f}")
    print(f"視界単独: {rho_sight:.3f}")
    print(f"視界+OSM: {rho_sight_osm:.3f}")
    print(f"CNN+視界(stacking): {stacking_rhos.mean():.3f} ± {stacking_rhos.std():.3f}  (各run: {[round(r,3) for r in stacking_rhos]})")
    print(f"concat: {concat_rhos.mean():.3f} ± {concat_rhos.std():.3f}  (各run: {[round(r,3) for r in concat_rhos]})")
    print(f"\n判定閾値(事前登録、CNN単体seed std×2): {threshold:.3f}")
    print(f"CNN+視界 stacking の CNN単体からの上乗せ: {stacking_rhos.mean() - cnn_alone_mean:+.3f}")
    print(f"視界+OSM と CNN単体の差: {rho_sight_osm - cnn_alone_mean:+.3f}")

    result = {
        "tile_style": STYLE,
        "sightline_alone": rho_sight,
        "sightline_plus_osm": rho_sight_osm,
        "cnn_plus_sightline_stacking": {"per_run": stacking_rhos.tolist(), "mean": float(stacking_rhos.mean()), "std": float(stacking_rhos.std())},
        "concat_cnn_osm_sightline": {"per_run": concat_rhos.tolist(), "mean": float(concat_rhos.mean()), "std": float(concat_rhos.std())},
        "reference": {"floor_self": 0.0, "cnn_alone": {"per_run": cnn_alone_rhos.tolist(), "mean": cnn_alone_mean, "std": cnn_alone_std}},
        "preregistered_threshold_2x_cnn_seed_std": threshold,
    }
    out_path = os.path.join(BASE_DIR, "eval_frozen", STYLE, "500m", "sightline_result_23ku.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n保存: {out_path}")


if __name__ == "__main__":
    main()
