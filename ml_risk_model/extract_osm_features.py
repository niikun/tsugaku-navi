"""extract_osm_raw_cache.pyが作った生キャッシュ(osm_data/osm_raw_cache_500m.pkl、
常にgitignore対象)から、セル単位の集計統計のみを取り出し、コミット可能なファイルに書き出す。

**ライセンス安全性のルール**(README.md「OSMベクターデータ」節参照): 出力先の
`osm_features/`ディレクトリは(1)個々のOSM要素(way_id・座標列・生タグ)を一切
含まない集計統計のみ、かつ(2)帰属表示付き、の両条件を満たすためコミット可能。
信号機・横断歩道の個別座標(`signal_points`/`crossing_points`)や車道の座標列
(`vehicle_ways`)は、このスクリプトの出力に一切含めない
(旧リポジトリの`cell_features_500m.pkl`が集計と生ジオメトリを混在させていた
反省を踏まえた設計。HANDOFF.md参照)。

出典: OpenStreetMapデータを集計。© OpenStreetMap contributors, Open Database
License (ODbL)。https://www.openstreetmap.org/copyright

出力形式について: `.gitignore`は`.pkl`/`.parquet`を「OSM由来の中間生成物か
再生成可能なキャッシュ」とみなし一律除外する多層防御ルールを持つ(このリポジトリの
方針上、これらの拡張子をコミット対象にする正当な理由はないため)。本スクリプトの
出力は数少ない例外(コミット可能な集計)だが、同じ理由でpickleは避け、
人間がレビューできる(diffで中身を確認できる)JSON形式で書き出す。
"""
import json
import os
import pickle

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_CACHE_PATH = os.path.join(BASE_DIR, "osm_data", "osm_raw_cache_500m.pkl")
OUTPUT_DIR = os.path.join(BASE_DIR, "osm_features")
OUTPUT_PATH = os.path.join(OUTPUT_DIR, "cell_aggregates_500m.json")

ATTRIBUTION = (
    "OpenStreetMapデータを集計。個々のOSM要素(座標・way_id・生タグ)は含まない。"
    "© OpenStreetMap contributors, Open Database License (ODbL). "
    "https://www.openstreetmap.org/copyright"
)

def _cell_key(gx, gy):
    return f"{gx}_{gy}"


def build_aggregates(raw_data):
    """JSON化のため、セルキー(gx, gy)タプルを"gx_gy"文字列に変換する。"""
    aggregates = {}
    for key in ("vehicle_length", "footway_length", "signal_count",
                "crossing_count", "vehicle_intersection", "vehicle_footway_intersection"):
        aggregates[key] = {_cell_key(*cell): v for cell, v in raw_data[key].items()}
    aggregates["highway_type_length"] = {
        _cell_key(*cell): type_lengths
        for cell, type_lengths in raw_data["highway_type_length"].items()
    }
    aggregates["attribution"] = ATTRIBUTION
    return aggregates


def main():
    if not os.path.exists(RAW_CACHE_PATH):
        raise SystemExit(
            f"生キャッシュが見つかりません: {RAW_CACHE_PATH}\n"
            "先に extract_osm_raw_cache.py を実行してください。"
        )

    with open(RAW_CACHE_PATH, "rb") as f:
        raw_data = pickle.load(f)

    aggregates = build_aggregates(raw_data)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(aggregates, f, ensure_ascii=False)

    print(f"集計のみの特徴量を保存しました(コミット可能): {OUTPUT_PATH}")
    print(f"車道データのあるセル数: {len(aggregates['vehicle_length'])}")
    print(f"歩道データのあるセル数: {len(aggregates['footway_length'])}")
    print("含まれるキー:", sorted(aggregates.keys()))
    assert "signal_points" not in aggregates and "crossing_points" not in aggregates \
        and "vehicle_ways" not in aggregates, "生ジオメトリが混入しています"


if __name__ == "__main__":
    main()
