"""build_train_set.pyで作った生画像をオフラインでデータ拡張し、manifestに追記する。

地図タイル画像は写真と違って上下左右の向きに意味的な制約が薄いため、
二面体群(90度刻みの回転 x 水平反転)の組み合わせ+軽い明るさ/コントラスト
ジッターで1枚の生画像から複数枚を複製する。

同一セル由来の拡張画像は必ずtrain_v3_poisson.py(移植予定)のtrain/val分割で
同じ側に入るよう、manifestにsource_cell_id(生画像のcell_id)を持たせて
グループ化できるようにする。生画像側のsource_cell_idは自分自身のcell_id。

再実行時は生画像のみを起点に再生成するため、拡張画像を消さずに再実行しても
manifestは一貫した内容に上書きされる(拡張ファイル自体は既存があれば再生成しない)。

注意: build_train_set.pyを再実行するとmanifestはこのスクリプトが追記した
拡張行を含まない状態に戻る(生画像のみで書き直されるため)。データセット生成が
完了してから最後にこのスクリプトを実行すること。
"""
import csv
import os
import random

from PIL import Image, ImageEnhance

from tiles import DEFAULT_TILE_STYLE

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_DIR = os.path.join(BASE_DIR, "dataset")

AUG_PER_IMAGE = 3  # 生画像1枚につき追加する拡張画像の枚数
RANDOM_SEED = 42

# 二面体群(回転0/90/180/270 x 水平反転有無)の8通り。0番目(無変換)は生画像そのものなので使わない。
_TRANSFORMS = [
    lambda img: img,
    lambda img: img.transpose(Image.ROTATE_90),
    lambda img: img.transpose(Image.ROTATE_180),
    lambda img: img.transpose(Image.ROTATE_270),
    lambda img: img.transpose(Image.FLIP_LEFT_RIGHT),
    lambda img: img.transpose(Image.FLIP_LEFT_RIGHT).transpose(Image.ROTATE_90),
    lambda img: img.transpose(Image.FLIP_LEFT_RIGHT).transpose(Image.ROTATE_180),
    lambda img: img.transpose(Image.FLIP_LEFT_RIGHT).transpose(Image.ROTATE_270),
]


def _jitter_color(img, rng):
    img = ImageEnhance.Brightness(img).enhance(rng.uniform(0.85, 1.15))
    img = ImageEnhance.Contrast(img).enhance(rng.uniform(0.85, 1.15))
    return img


def load_raw_rows(manifest_path):
    with open(manifest_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if r.get("source_cell_id", r["cell_id"]) == r["cell_id"]]


def augment_row(row, rng):
    src_path = os.path.join(BASE_DIR, row["image_path"])
    image = Image.open(src_path).convert("RGB")
    out_dir = os.path.dirname(src_path)

    variant_indices = rng.sample(range(1, len(_TRANSFORMS)), AUG_PER_IMAGE)

    new_rows = []
    for i, variant_idx in enumerate(variant_indices, start=1):
        transformed = _jitter_color(_TRANSFORMS[variant_idx](image), rng)
        aug_cell_id = f"{row['cell_id']}_aug{i}"
        out_path = os.path.join(out_dir, f"{aug_cell_id}.png")
        if not os.path.exists(out_path):
            transformed.save(out_path)

        new_row = dict(row)
        new_row["cell_id"] = aug_cell_id
        new_row["source_cell_id"] = row["cell_id"]
        new_row["image_path"] = os.path.relpath(out_path, BASE_DIR)
        new_rows.append(new_row)
    return new_rows


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--style", choices=["std", "pale"], default=DEFAULT_TILE_STYLE,
                         help="build_train_set.pyと同じスタイルを指定する")
    parser.add_argument("--manifest", default=None,
                         help="拡張対象のmanifestファイルパス(省略時はスタイルから自動決定)")
    args = parser.parse_args()
    manifest_path = args.manifest or os.path.join(
        DATASET_DIR, f"manifest_train_counts_500m_{args.style}.csv")

    raw_rows = load_raw_rows(manifest_path)
    if not raw_rows:
        raise SystemExit(f"{manifest_path} に生画像がありません。先に build_train_set.py を実行してください。")
    print(f"生画像: {len(raw_rows)}件 -> 各{AUG_PER_IMAGE}枚の拡張画像を追加")

    rng = random.Random(RANDOM_SEED)
    all_rows = []
    for row in raw_rows:
        row = dict(row)
        row["source_cell_id"] = row["cell_id"]
        all_rows.append(row)
        all_rows.extend(augment_row(row, rng))

    fieldnames = list(all_rows[0].keys())
    with open(manifest_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"manifest更新: {manifest_path} ({len(all_rows)}件, 生画像の{AUG_PER_IMAGE + 1}倍)")


if __name__ == "__main__":
    main()
