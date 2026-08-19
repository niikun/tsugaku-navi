#!/usr/bin/env python3
"""
CSVデータをGeoJSON形式に変換するスクリプト
Tokyo pedestrian accidents CSV -> GeoJSON

データ出典: 警察庁交通事故統計情報オープンデータ（2019年1月～2024年12月）
https://www.npa.go.jp/publications/statistics/koutsuu/opendata/index_opendata.html
"""
import csv
import json

def convert_csv_to_geojson(csv_file, output_file):
    """CSVをGeoJSON形式に変換"""
    features = []

    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)

        for row in reader:
            # 座標の取得
            try:
                lat = float(row['lat'])
                lon = float(row['lon'])
            except (ValueError, KeyError):
                continue  # 座標が不正な場合はスキップ

            # GeoJSONのFeatureを作成
            # properties: frontend/app.jsのポップアップ表示で実際に使う項目のみに
            # 絞る(道路形状・事故類型・当事者の年齢/損傷程度・信号機は未使用)。
            # 座標も小数点以下6桁(約11cm精度、この用途には十分)に丸める。
            # フル項目・フル精度が必要な場合はこの絞り込みを外せば復元できる
            # (元のtokyo_pedestrian_accidents.csvは全項目を保持している)。
            feature = {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [round(lon, 6), round(lat, 6)]  # GeoJSONは [経度, 緯度] の順
                },
                "properties": {
                    "year": row.get('発生日時　　年', ''),
                    "month": row.get('発生日時　　月', ''),
                    "day": row.get('発生日時　　日', ''),
                    "hour": row.get('発生日時　　時', ''),
                    "minute": row.get('発生日時　　分', ''),
                    "day_night": row.get('昼夜', ''),
                    "weather": row.get('天候', ''),
                    "deaths": row.get('死者数', ''),
                    "injuries": row.get('負傷者数', '')
                }
            }

            features.append(feature)

    # GeoJSONのFeatureCollectionを作成
    geojson = {
        "type": "FeatureCollection",
        "features": features
    }

    # ファイルに書き出し
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(geojson, f, ensure_ascii=False, separators=(',', ':'))

    print(f"変換完了: {len(features)} 件の事故データを {output_file} に出力しました")

if __name__ == "__main__":
    convert_csv_to_geojson('tokyo_pedestrian_accidents.csv', 'accidents.geojson')
