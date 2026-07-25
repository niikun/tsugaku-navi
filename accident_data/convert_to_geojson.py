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
            feature = {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [lon, lat]  # GeoJSONは [経度, 緯度] の順
                },
                "properties": {
                    "year": row.get('発生日時　　年', ''),
                    "month": row.get('発生日時　　月', ''),
                    "day": row.get('発生日時　　日', ''),
                    "hour": row.get('発生日時　　時', ''),
                    "minute": row.get('発生日時　　分', ''),
                    "day_night": row.get('昼夜', ''),
                    "weather": row.get('天候', ''),
                    "road_shape": row.get('道路形状', ''),
                    "accident_type": row.get('事故類型', ''),
                    "injury_level_a": row.get('人身損傷程度（当事者A）', ''),
                    "injury_level_b": row.get('人身損傷程度（当事者B）', ''),
                    "age_a": row.get('年齢（当事者A）', ''),
                    "age_b": row.get('年齢（当事者B）', ''),
                    "signal": row.get('信号機', ''),
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
