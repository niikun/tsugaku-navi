#!/usr/bin/env python3
"""
警察庁オープンデータの本票CSV(全国・全事故種別、Shift_JIS)から
東京都の歩行者事故(事故類型=人対車両)を抽出し、緯度経度をDMSから10進に
変換して tokyo_pedestrian_accidents.csv に追記する。

データ出典: 警察庁交通事故統計情報オープンデータ
https://www.npa.go.jp/publications/statistics/koutsuu/opendata/index_opendata.html

列位置は年度によって変わる(2019〜2021年は58列、2022〜2024年は68列で、
サポカー・認知機能検査経過日数等の項目が後から追加された)ため、位置決め打ちでは
なく列名(DictReader)で参照する。列名自体は確認した全年度(2019〜2024)で安定している。
出力列は現行(2022〜2024年)の68列を正としてそろえ、旧フォーマットの年度には
存在しない列は空文字で埋める(捏造ではなく「その年度は記録されていない」ことの表現)。

使い方:
    python3 extract_tokyo_pedestrian.py honhyo_2024.csv
"""
import csv
import os
import sys

TOKYO_PREF_CODE = "30"
PEDESTRIAN_ACCIDENT_TYPE = 1  # 事故類型: 人対車両(先頭桁0x)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_PATH = os.path.join(BASE_DIR, "tokyo_pedestrian_accidents.csv")

LAT_COL = "地点　緯度（北緯）"
LON_COL = "地点　経度（東経）"
PREF_COL = "都道府県コード"
TYPE_COL = "事故類型"

# 出力csvの正規の列順(現行2022〜2024年フォーマット、lat/lonにリネーム済み)。
# 新規追加された年度限定の列は、旧年度データでは空文字で埋める。
CANONICAL_HEADER = None
if os.path.exists(OUTPUT_PATH):
    with open(OUTPUT_PATH, encoding="utf-8") as f:
        CANONICAL_HEADER = next(csv.reader(f))


def _dms_to_decimal_lat(raw):
    deg, minute, sec = int(raw[0:2]), int(raw[2:4]), int(raw[4:9]) / 1000
    return deg + minute / 60 + sec / 3600


def _dms_to_decimal_lon(raw):
    deg, minute, sec = int(raw[0:3]), int(raw[3:5]), int(raw[5:10]) / 1000
    return deg + minute / 60 + sec / 3600


def _normalize_field(value):
    """既存csvは数値項目の先頭ゼロを取り除いた形式(例: "09"ではなく"9")なので合わせる。"""
    if value.isdigit():
        return str(int(value))
    return value


def extract_rows(honhyo_path, output_header):
    """output_header(現行68列、lat/lon済み)の列順にそろえた行のリストを返す。
    honhyo_path側に無い列は空文字で埋める。
    """
    with open(honhyo_path, encoding="cp932") as f:
        reader = csv.DictReader(f)
        source_cols = reader.fieldnames
        rows = []
        for row in reader:
            if row[PREF_COL] != TOKYO_PREF_CODE:
                continue
            if int(row[TYPE_COL]) != PEDESTRIAN_ACCIDENT_TYPE:
                continue
            row = {k: _normalize_field(v) for k, v in row.items()}
            row["lat"] = str(_dms_to_decimal_lat(row[LAT_COL]))
            row["lon"] = str(_dms_to_decimal_lon(row[LON_COL]))
            rows.append(row)

    source_col_set = set(source_cols) | {"lat", "lon"}
    missing = [c for c in output_header if c not in source_col_set]
    if missing:
        print(f"  注記: {honhyo_path} に無い列(空文字で埋める): {missing}")

    out_rows = [[row.get(col, "") for col in output_header] for row in rows]
    return out_rows


def main():
    if len(sys.argv) != 2:
        raise SystemExit("使い方: python3 extract_tokyo_pedestrian.py <honhyo_YYYY.csv>")
    honhyo_path = sys.argv[1]

    file_exists = os.path.exists(OUTPUT_PATH)
    if CANONICAL_HEADER is not None:
        output_header = CANONICAL_HEADER
    else:
        # 出力先がまだ無い場合、この年度のヘッダーをlat/lonリネームして正とする。
        with open(honhyo_path, encoding="cp932") as f:
            output_header = next(csv.reader(f))
        output_header = [("lat" if c == LAT_COL else "lon" if c == LON_COL else c) for c in output_header]

    new_rows = extract_rows(honhyo_path, output_header)
    print(f"抽出: {len(new_rows)}件 (都道府県=東京, 事故類型=人対車両)")

    with open(OUTPUT_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(output_header)
        writer.writerows(new_rows)

    print(f"{OUTPUT_PATH} に追記しました(追加 {len(new_rows)}件)")


if __name__ == "__main__":
    main()
