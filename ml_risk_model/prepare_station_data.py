"""国土数値情報 鉄道データ(N02)から、東京本土の駅位置(概算)を抽出する一回限りの準備スクリプト。

旧リポジトリでは駅からの距離の交絡チェック(spatial_block_split.py)にOverpass API
(OSM本体のクエリAPI)を使っていたが、これはOSMライセンス問題の一部として指摘された
(HANDOFF.md参照)。本スクリプトはOverpassを使わず、国土数値情報(政府オープンデータ、
OSM/ODbLとは無関係)の鉄道データ(N02)から同等の駅位置データを作る。

N02のStationレイヤは「駅」を表すが、ジオメトリはPoint(点)ではなくCurve(隣接駅間の
線区間)として提供されている(KsjAppSchema-N02-v3_1.xsdのStationType定義を参照)。
本スクリプトでは、同一駅コード(N02_005c)に属する区間の中点を平均し、駅の代表点とする
近似を行う。交絡チェック用の粗い距離指標としては十分な精度。

出典: 国土数値情報(国土交通省)鉄道データ(N02、2022年度)
https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N02-v3_1.html

使い方:
    python3 prepare_station_data.py
出力:
    boundary_data/N02-2022_Station_tokyo.geojson (Point、駅名・駅コード付き)
"""
import io
import json
import os
import urllib.request
import zipfile
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_PATH = os.path.join(BASE_DIR, "boundary_data", "N02-2022_Station_tokyo.geojson")

SOURCE_URL = "https://nlftp.mlit.go.jp/ksj/gml/data/N02/N02-22/N02-22_GML.zip"
ZIP_MEMBER = "UTF-8/N02-22_Station.geojson"
USER_AGENT = "tsugaku-navi/1.0 (contact: niikun0209@gmail.com; educational hackathon project)"

# 東京本土のバウンディングボックス(南,西,北,東)。旧spatial_block_split.pyのTOKYO_BBOXと同じ。
TOKYO_BBOX = (35.0, 138.9, 35.9, 140.0)


def _download_zip_bytes():
    req = urllib.request.Request(SOURCE_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def build_station_points(zip_bytes):
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        with z.open(ZIP_MEMBER) as f:
            data = json.load(f)

    south, west, north, east = TOKYO_BBOX
    by_code = defaultdict(list)
    for feat in data["features"]:
        coords = feat["geometry"]["coordinates"]
        mid_lat = sum(c[1] for c in coords) / len(coords)
        mid_lon = sum(c[0] for c in coords) / len(coords)
        if not (south <= mid_lat <= north and west <= mid_lon <= east):
            continue
        code = feat["properties"]["N02_005c"]
        by_code[code].append((mid_lat, mid_lon, feat["properties"]["N02_005"]))

    features = []
    for code, entries in by_code.items():
        lat = sum(e[0] for e in entries) / len(entries)
        lon = sum(e[1] for e in entries) / len(entries)
        name = entries[0][2]
        features.append({
            "type": "Feature",
            "properties": {"station_name": name, "station_code": code},
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
        })
    return {"type": "FeatureCollection", "features": features}


def main():
    print(f"国土数値情報N02(鉄道)を取得中: {SOURCE_URL}")
    zip_bytes = _download_zip_bytes()
    geojson = build_station_points(zip_bytes)
    print(f"東京本土の駅(概算・重複統合後): {len(geojson['features'])}件")

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False)
    print(f"保存しました: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
