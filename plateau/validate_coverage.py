"""視界特徴の計算前に、データのカバレッジを検証する。

確認項目:
(a) 対象セルの必要メッシュが全てparquetに存在するか(参考情報、判定には使わない)
(b) 各セルの車道サンプル点付近に建物データがあるか
    (メッシュ内に建物が1棟でもあれば、そのセルはカバレッジ完全とみなす)
(c) height_sourceの内訳がメッシュによって極端に偏っていないか

出力(`plateau_data/covered_cells_23ku.txt`)はセルID(グリッド座標)のみで、
個々のOSM要素・PLATEAU建物データそのものは含まないため、コミット可能
(ただし置き場所は`plateau_data/`のまま、`.gitignore`のディレクトリ単位除外に
巻き込まれる。必要ならこのファイルだけ個別に例外を追加すること)。
"""
import os

import pandas as pd

from plateau.meshcode import latlon_to_mesh3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARQUET_PATH = os.path.join(BASE_DIR, "plateau_data", "buildings_23ku.parquet")
ROAD_POINTS_PATH = os.path.join(BASE_DIR, "plateau_data", "road_sample_points_23ku.csv")
REQUIRED_MESHES_PATH = os.path.join(BASE_DIR, "required_meshes_23ku.txt")
COVERED_CELLS_PATH = os.path.join(BASE_DIR, "plateau_data", "covered_cells_23ku.txt")


def main():
    import csv

    with open(REQUIRED_MESHES_PATH) as f:
        required_meshes = set(line.strip() for line in f)

    df = pd.read_parquet(PARQUET_PATH)
    available_meshes = set(df["mesh_code"].astype(str).unique())

    print(f"必要メッシュ数: {len(required_meshes)}")
    print(f"parquet内のメッシュ数: {len(available_meshes)}")
    missing = required_meshes - available_meshes
    print(f"(a) 欠落メッシュ数: {len(missing)} ({len(missing)/len(required_meshes):.1%})")

    with open(ROAD_POINTS_PATH, encoding="utf-8") as f:
        road_points = list(csv.DictReader(f))
    print(f"\n車道サンプル点総数: {len(road_points)}  対象セル数: {len(set(r['cell_id'] for r in road_points))}")

    df["mesh_code"] = df["mesh_code"].astype(str)
    mesh_groups = {code: g for code, g in df.groupby("mesh_code")}

    n_no_building = 0
    n_checked = 0
    empty_cells = set()
    for r in road_points:
        lat, lon = float(r["lat"]), float(r["lon"])
        mesh = latlon_to_mesh3(lat, lon)
        candidates = mesh_groups.get(mesh)
        found = candidates is not None and len(candidates) > 0
        n_checked += 1
        if not found:
            n_no_building += 1
            empty_cells.add(r["cell_id"])

    print(f"\n(b) 建物データが見つからない車道サンプル点: {n_no_building}/{n_checked} ({n_no_building/n_checked:.1%})")
    print(f"    該当セル数: {len(empty_cells)}")

    all_cells = set(r["cell_id"] for r in road_points)
    covered_cells = all_cells - empty_cells
    print(f"\nカバレッジ完全なセル(全サンプル点でメッシュデータあり): {len(covered_cells)}/{len(all_cells)}")
    with open(COVERED_CELLS_PATH, "w") as f:
        for c in sorted(covered_cells):
            f.write(c + "\n")
    print(f"保存: {COVERED_CELLS_PATH}")

    print("\n(c) メッシュ単位のheight_source内訳(measured率が低い外れ値メッシュ)")
    mesh_stats = df.groupby("mesh_code")["height_source"].apply(lambda s: (s == "measured").mean())
    print(f"    全体measured率: {(df['height_source']=='measured').mean():.4f}")
    print(f"    メッシュ別measured率の分布: min={mesh_stats.min():.3f} p10={mesh_stats.quantile(0.1):.3f} median={mesh_stats.median():.3f}")
    low_outliers = mesh_stats[mesh_stats < 0.8]
    print(f"    measured率80%未満のメッシュ数: {len(low_outliers)}")


if __name__ == "__main__":
    main()
