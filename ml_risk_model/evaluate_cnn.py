"""凍結評価セットでCNN(Poissonヘッド)を評価する。

train.pyで学習した各seedのepoch15チェックポイント(機械的ルール、成績による
後出し選択はしない)をeval_frozen/{style}/500mに適用し、evaluate_floor_osm.pyと
同じ残差Spearman(フロア予測に対する残差の順位相関)で評価する。フロア予測は
trainで学習した既存モデルをそのまま使う(evalで再学習しない、リークになるため)。

TODO(2026-07-25、ユーザー提案): シフトに対する予測値の安定性を副指標として
追加する余地がある。評価点の近傍(数十m単位)でtiles.pyから複数枚の画像を
取得し、予測値のばらつき(変動係数等)を見る。CNN学習後、実データで
試してから実装すること(未学習の段階での実装は時期尚早と判断し保留)。
"""
import argparse
import csv
import glob
import json
import os

import numpy as np
import torch
from PIL import Image
from torch import nn
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms
from torchvision.models import mobilenet_v2
from sklearn.ensemble import HistGradientBoostingRegressor

from evaluate_floor_osm import POISSON_PARAMS, load_joined, log_vehicle, residual_spearman, to_matrix
from tiles import DEFAULT_TILE_STYLE
from train import IMAGENET_MEAN, IMAGENET_STD, load_vehicle_length

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

val_transform = transforms.Compose([
    transforms.ToTensor(),
    transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
])


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


def fit_floor_model(style):
    """train側で駅距離・エッジ密度・建造物率+log曝露量のPoisson GBDTを学習する
    (evaluate_floor_osm.pyと同じ設定)。"""
    train_rows = load_joined(style, is_eval=False)
    eval_rows = load_joined(style, is_eval=True)
    y_train = np.array([float(r["accident_count"]) for r in train_rows])

    X_floor_train = np.column_stack([
        to_matrix(train_rows, ["station_dist", "edge_density", "built_env_fraction"]), log_vehicle(train_rows),
    ])
    X_floor_eval = np.column_stack([
        to_matrix(eval_rows, ["station_dist", "edge_density", "built_env_fraction"]), log_vehicle(eval_rows),
    ])
    floor_model = HistGradientBoostingRegressor(**POISSON_PARAMS).fit(X_floor_train, y_train)
    floor_pred_eval = floor_model.predict(X_floor_eval)
    cell_ids_eval = [r["cell_id"] for r in eval_rows]
    return dict(zip(cell_ids_eval, floor_pred_eval))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--style", choices=["std", "pale"], default=DEFAULT_TILE_STYLE)
    parser.add_argument("--model-glob", required=True,
                         help="評価するモデルファイルのglobパターン(例: models/risk_model_500m_std_poisson_seed*_epoch15.pt)")
    args = parser.parse_args()
    style = args.style

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    eval_dir = os.path.join(BASE_DIR, "eval_frozen", style, "500m")
    with open(os.path.join(eval_dir, "eval_manifest.csv"), encoding="utf-8") as f:
        eval_manifest_rows = list(csv.DictReader(f))
    osm_eval_path = os.path.join(BASE_DIR, "osm_features", f"osm_features_eval_{style}.csv")
    vehicle_length_lookup = load_vehicle_length(osm_eval_path)

    print("フロアモデルをtrainで学習し、evalに適用中(残差化の基準)...")
    floor_pred_by_cell = fit_floor_model(style)

    cell_ids = [r["cell_id"] for r in eval_manifest_rows]
    y = np.array([float(r["accident_count"]) for r in eval_manifest_rows])
    floor_pred_eval = np.array([floor_pred_by_cell[cid] for cid in cell_ids])

    model_paths = sorted(glob.glob(args.model_glob))
    if not model_paths:
        raise SystemExit(f"モデルが見つかりません: {args.model_glob}")

    results = []
    for path in model_paths:
        model = load_model(path).to(device)
        pred_by_cell = predict_cnn(model, eval_manifest_rows, vehicle_length_lookup, device)
        cnn_pred_eval = np.array([pred_by_cell[cid] for cid in cell_ids])
        rho, _ = residual_spearman(cnn_pred_eval, floor_pred_eval, y)
        results.append(rho)
        print(f"{os.path.basename(path)}: 残差Spearman={rho:.3f}")

    results = np.array(results)
    print(f"\n=== 平均±std (n={len(results)}チェックポイント/seed) ===")
    print(f"残差Spearman: {results.mean():.3f} ± {results.std():.3f}")


if __name__ == "__main__":
    main()
