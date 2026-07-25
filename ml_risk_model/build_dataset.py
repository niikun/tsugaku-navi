"""事故データ(CSV)の読み込みとセル単位の事故件数集計。

`build_train_set.py`/`build_eval_set.py`/`spatial_block_split.py`から共通で使う。
事故データは警察庁交通事故統計情報オープンデータ由来で、OSMには依存しない
(README.md参照)。
"""
import csv
import os
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE_DIR, "..", "accident_data", "tokyo_pedestrian_accidents.csv")


def load_accidents():
    rows = []
    with open(CSV_PATH, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            lat = float(row["lat"])
            lon = float(row["lon"])
            if lat > 35.0:  # 離島(伊豆・小笠原)を除外し本土のみ
                rows.append((lat, lon))
    return rows


def build_cell_counts(accidents, lat_step, lon_step):
    counts = defaultdict(int)
    for lat, lon in accidents:
        gy = int(lat / lat_step)
        gx = int(lon / lon_step)
        counts[(gx, gy)] += 1
    return counts
