"""CNN(MobileNetV2)にPoisson回帰ヘッド(log-link)を載せて学習する(件数/率回帰、v3設計)。

- 出力は2クラスのロジットではなく1スカラー(log予測率)。
- 損失はnn.PoissonNLLLoss(log_input=True)。曝露量(OSM車道延長)をオフセットとして
  raw出力に加算してからロスに渡す(学習される特徴ではなく、GLMのoffsetと同じ役割)。
- train/valのグループ分割は同一source_cell_id単位のみ(ラベルで分けない。件数回帰に
  クラスの概念がないため)。

学習時のデータ拡張(RandomResizedCrop等)は、平行移動・スケールに対する頑健性を
一定程度カバーする。これとは別に、経路上の細粒度な地点ずれに対する予測値の
安定性は学習では保証されないため、評価側(evaluate_cnn_count_regression.py
移植時)で「シフトに対する予測値の安定性」を副指標として確認すること
(2026-07-25、ユーザー提案。HANDOFF.md参照)。

実行前提: `uv add torch torchvision`で依存を追加し、`build_train_set.py`/
`augment_dataset.py`/`osm_feature_lookup.py`を先に実行してデータセット・
OSM特徴量CSVを揃えておくこと。
"""
import argparse
import csv
import math
import os
import random

import torch
from PIL import Image
from torch import nn
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms
from torchvision.models import MobileNet_V2_Weights, mobilenet_v2

from tiles import DEFAULT_TILE_STYLE

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "models")

IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]


def load_vehicle_length(osm_path):
    with open(osm_path, encoding="utf-8") as f:
        return {r["cell_id"]: float(r["vehicle_length_m"]) for r in csv.DictReader(f)}


def load_manifest_rows(grid_m, manifest_path):
    rows = []
    with open(manifest_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if int(row["grid_m"]) == grid_m:
                rows.append(row)
    return rows


def split_train_val(rows, val_ratio, seed):
    """source_cell_id(拡張画像の元画像ID)単位でグループ化してtrain/valに分割する。
    件数回帰にはクラスの概念がないため、ラベル別グループ化はしない。
    """
    rng = random.Random(seed)
    groups = {}
    for row in rows:
        source_id = row.get("source_cell_id") or row["cell_id"]
        groups.setdefault(source_id, []).append(row)

    group_ids = list(groups.keys())
    rng.shuffle(group_ids)
    n_val_groups = max(1, int(len(group_ids) * val_ratio))
    val_rows, train_rows = [], []
    for source_id in group_ids[:n_val_groups]:
        val_rows += groups[source_id]
    for source_id in group_ids[n_val_groups:]:
        train_rows += groups[source_id]
    return train_rows, val_rows


class RiskCellCountDataset(Dataset):
    def __init__(self, rows, transform, vehicle_length_lookup):
        self.rows = rows
        self.transform = transform
        self.vehicle_length_lookup = vehicle_length_lookup

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, idx):
        row = self.rows[idx]
        img_path = os.path.join(BASE_DIR, row["image_path"])
        image = Image.open(img_path).convert("RGB")
        count = float(row["accident_count"])
        source_id = row.get("source_cell_id") or row["cell_id"]
        vehicle_len = self.vehicle_length_lookup.get(source_id, 0.0)
        log_exposure = torch.log(torch.tensor(vehicle_len + 1.0, dtype=torch.float32))
        return self.transform(image), torch.tensor(count, dtype=torch.float32), log_exposure


def build_model(unfreeze_last_n=0, bias_init_log_rate=0.0):
    """bias_init_log_rate: 最終層のbiasをlog(平均事故率)で初期化する。
    raw出力+log(曝露量)がPoissonのlog予測率になるため、bias=0のままだと初期予測が
    log(曝露量)そのもの(=曝露量メートル数と同程度の件数)になり大きく発散する。
    重みを0で初期化しbiasだけ平均率に合わせることで、初期予測を「平均的な率」に
    校正してから学習を始める(trainデータのみから計算、リークではない)。
    """
    model = mobilenet_v2(weights=MobileNet_V2_Weights.IMAGENET1K_V1)
    for param in model.features.parameters():
        param.requires_grad = False
    if unfreeze_last_n > 0:
        for block in model.features[-unfreeze_last_n:]:
            for param in block.parameters():
                param.requires_grad = True
    in_features = model.classifier[1].in_features
    head = nn.Linear(in_features, 1)
    nn.init.zeros_(head.weight)
    nn.init.constant_(head.bias, bias_init_log_rate)
    model.classifier[1] = head
    return model


def run_epoch(model, loader, device, criterion, optimizer=None):
    is_train = optimizer is not None
    model.train(is_train)

    total_loss, total_n = 0.0, 0
    with torch.set_grad_enabled(is_train):
        for images, counts, log_exposure in loader:
            images, counts, log_exposure = images.to(device), counts.to(device), log_exposure.to(device)
            raw = model(images).squeeze(-1)
            log_pred = raw + log_exposure
            loss = criterion(log_pred, counts)

            if is_train:
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

            total_loss += loss.item() * images.size(0)
            total_n += images.size(0)

    return total_loss / total_n


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--style", choices=["std", "pale"], default=DEFAULT_TILE_STYLE,
                         help="build_train_set.pyと同じタイル種別を指定する")
    parser.add_argument("--grid", type=int, default=500, choices=[500])
    parser.add_argument("--epochs", type=int, default=15)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--val-ratio", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--unfreeze-last-n", type=int, default=3)
    parser.add_argument("--manifest", default=None)
    parser.add_argument("--model-suffix", default="_poisson")
    parser.add_argument("--save-last-n-epochs", type=int, default=5)
    args = parser.parse_args()

    manifest_path = args.manifest or os.path.join(
        BASE_DIR, "dataset", f"manifest_train_counts_{args.grid}m_{args.style}.csv")
    osm_train_path = os.path.join(BASE_DIR, "osm_features", f"osm_features_train_{args.style}.csv")

    vehicle_length_lookup = load_vehicle_length(osm_train_path)

    rows = load_manifest_rows(args.grid, manifest_path)
    if not rows:
        raise SystemExit(f"grid={args.grid}m のデータが {manifest_path} にありません")
    train_rows, val_rows = split_train_val(rows, args.val_ratio, args.seed)
    print(f"grid={args.grid}m style={args.style}: train={len(train_rows)}件 val={len(val_rows)}件")

    total_count = sum(float(r["accident_count"]) for r in train_rows)
    total_exposure = sum(
        vehicle_length_lookup.get(r.get("source_cell_id") or r["cell_id"], 0.0) + 1.0 for r in train_rows
    )
    bias_init_log_rate = math.log(total_count / total_exposure)
    print(f"初期化用の平均事故率(train側): {total_count / total_exposure:.6f}/m  log={bias_init_log_rate:.3f}")

    train_transform = transforms.Compose([
        transforms.RandomResizedCrop(256, scale=(0.75, 1.0)),
        transforms.RandomHorizontalFlip(),
        transforms.RandomVerticalFlip(),
        transforms.RandomRotation(180),
        transforms.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.1),
        transforms.ToTensor(),
        transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
    ])
    val_transform = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
    ])

    train_loader = DataLoader(
        RiskCellCountDataset(train_rows, train_transform, vehicle_length_lookup),
        batch_size=args.batch_size, shuffle=True,
        num_workers=4, persistent_workers=True,
    )
    val_loader = DataLoader(
        RiskCellCountDataset(val_rows, val_transform, vehicle_length_lookup),
        batch_size=args.batch_size, shuffle=False,
        num_workers=4, persistent_workers=True,
    )

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = build_model(unfreeze_last_n=args.unfreeze_last_n, bias_init_log_rate=bias_init_log_rate).to(device)
    criterion = nn.PoissonNLLLoss(log_input=True, full=False)

    if args.unfreeze_last_n > 0:
        backbone_params = [p for p in model.features.parameters() if p.requires_grad]
        optimizer = torch.optim.Adam([
            {"params": model.classifier.parameters(), "lr": args.lr},
            {"params": backbone_params, "lr": args.lr * 0.1},
        ])
    else:
        optimizer = torch.optim.Adam(model.classifier.parameters(), lr=args.lr)

    os.makedirs(MODELS_DIR, exist_ok=True)
    model_path = os.path.join(MODELS_DIR, f"risk_model_{args.grid}m_{args.style}{args.model_suffix}.pt")

    for epoch in range(1, args.epochs + 1):
        train_loss = run_epoch(model, train_loader, device, criterion, optimizer)
        val_loss = run_epoch(model, val_loader, device, criterion)
        print(f"epoch {epoch:2d}/{args.epochs}  train_poisson_nll={train_loss:.4f}  val_poisson_nll={val_loss:.4f}")
        torch.save({"grid_m": args.grid, "style": args.style, "state_dict": model.state_dict()}, model_path)
        if epoch > args.epochs - args.save_last_n_epochs:
            epoch_path = os.path.join(
                MODELS_DIR, f"risk_model_{args.grid}m_{args.style}{args.model_suffix}_epoch{epoch}.pt")
            torch.save({"grid_m": args.grid, "style": args.style, "val_loss": val_loss,
                        "state_dict": model.state_dict()}, epoch_path)

    print(f"\n最終epochのモデルを {model_path} に保存しました(チェックポイント選択はepoch15固定で行う)")


if __name__ == "__main__":
    main()
