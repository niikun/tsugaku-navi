"""地理院タイル取得・地図画像合成の共通ロジック。

build_dataset.py（学習データ生成）と risk_model.py（推論）の
両方から使われる。

本リポジトリでは取得元に国土地理院「地理院タイル」を使う。std(標準地図)・
pale(淡色地図)の2種別に対応し、フェーズ1では両方で学習データを作成して
CNN精度を比較する(`TILE_STYLES`参照。フェーズ0.1でstdを第一候補、pale次点と
決定したが、実際の比較検証はフェーズ1で行う)。
経緯: 別リポジトリ(traffic_accident)で、OSM標準タイルサーバー
(tile.openstreetmap.org)から取得した画像を学習データに使っていたところ、
OpenStreetMap Foundationの Tile Usage Policy
(https://operations.osmfoundation.org/policies/tiles/、標準タイルサーバー
由来のタイルの大量ダウンロード・アーカイブ化を禁止)に抵触することが判明した。
これを受けて、OSM由来のコード・データを一切持ち込まない前提でこのリポジトリを
新規に立ち上げた。旧リポジトリ側の発覚経緯の記録:
traffic_accidentリポジトリ(このリポジトリとは別のgitリポジトリ、開発機上では
`../traffic_accident/`に配置)の`ml_risk_model/STUDY_LOG.md`「OSMライセンス
問題の発覚と対応」を参照。

地理院タイルの座標系(z/x/y)は、Web Mercatorスリッピーマップ方式という
業界標準の座標変換方式(OSM・Google Maps・地理院タイル等、多くのタイル
配信サービスが共通して使う公開仕様)に基づく。`lonlat_to_pixel`等の座標変換
ロジックはこの標準仕様の実装であり、OSM固有のコードではない。
利用規約: https://www.gsi.go.jp/kikakuchousei/kikakuchousei40182.html
出典表示: 「国土地理院」または「地理院タイル」+
https://maps.gsi.go.jp/development/ichiran.html へのリンク。
"""
import math
import os
import time
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TILE_CACHE_DIR = os.path.join(BASE_DIR, "tile_cache")

# 学習データセットが対応済みの地理院タイル種別。フェーズ0.1でstdを第一候補、
# paleを次点として決定したが、実際の学習・評価では両方を取得しCNN精度を比較する
# (タイルソースをOSMから地理院タイルに変える、という今回の変更のスコープ内の
# 選定作業のため、両方試すこと自体は変更範囲外のブレではない)。
TILE_STYLES = ("std", "pale")
DEFAULT_TILE_STYLE = "std"

# 地理院タイルの利用規約に明示的なレート制限の記載はないが、OSM対応時と
# 同水準の保守的な間隔を踏襲する(常識的な利用を維持するため)。
USER_AGENT = "tsugaku-navi-gsi/1.0 (contact: niikun0209@gmail.com; educational hackathon project)"
TILE_MIN_INTERVAL_SEC = 0.5

TILE_URL_TEMPLATE = "https://cyberjapandata.gsi.go.jp/xyz/{style}/{z}/{x}/{y}.png"

# 地理院タイル(std/pale)の対応ズームレベルは5〜18。500mグリッド(zoom17)は
# 範囲内だが、将来的な100mグリッド(zoom19相当)は非対応のため、実装する場合は
# グリッドサイズをズーム対応範囲に合わせて調整すること(PLAN_GSI_MIGRATION.md 6.C参照)。
GRID_CONFIGS = {
    500: {"zoom": 17},
}

FINAL_IMG_SIZE = 256


def grid_steps(grid_m):
    deg_lat_km = 111.0
    deg_lon_km = 111.0 * math.cos(math.radians(35.7))
    grid_km = grid_m / 1000
    return grid_km / deg_lat_km, grid_km / deg_lon_km


def cell_id_for(lat, lon, grid_m):
    lat_step, lon_step = grid_steps(grid_m)
    gy = int(lat / lat_step)
    gx = int(lon / lon_step)
    return gx, gy


def cell_bbox(gx, gy, lat_step, lon_step):
    lat_min = gy * lat_step
    lat_max = (gy + 1) * lat_step
    lon_min = gx * lon_step
    lon_max = (gx + 1) * lon_step
    return lat_min, lat_max, lon_min, lon_max


def lonlat_to_pixel(lon, lat, zoom):
    n = 256 * (2 ** zoom)
    x = (lon + 180.0) / 360.0 * n
    lat_rad = math.radians(lat)
    y = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n
    return x, y


_last_download_time = [0.0]


def fetch_tile(z, x, y, style=DEFAULT_TILE_STYLE):
    from PIL import Image

    cache_path = os.path.join(TILE_CACHE_DIR, style, str(z), str(x), f"{y}.png")
    if os.path.exists(cache_path):
        return Image.open(cache_path).convert("RGB")

    os.makedirs(os.path.dirname(cache_path), exist_ok=True)

    elapsed = time.time() - _last_download_time[0]
    if elapsed < TILE_MIN_INTERVAL_SEC:
        time.sleep(TILE_MIN_INTERVAL_SEC - elapsed)

    url = TILE_URL_TEMPLATE.format(style=style, z=z, x=x, y=y)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = resp.read()
    _last_download_time[0] = time.time()

    with open(cache_path, "wb") as f:
        f.write(data)

    import io
    return Image.open(io.BytesIO(data)).convert("RGB")


def build_cell_image(lat_min, lat_max, lon_min, lon_max, zoom, style=DEFAULT_TILE_STYLE):
    from PIL import Image

    x0, y1 = lonlat_to_pixel(lon_min, lat_min, zoom)  # 左下
    x1, y0 = lonlat_to_pixel(lon_max, lat_max, zoom)  # 右上
    px_min, px_max = min(x0, x1), max(x0, x1)
    py_min, py_max = min(y0, y1), max(y0, y1)

    tx_min, tx_max = int(px_min // 256), int(px_max // 256)
    ty_min, ty_max = int(py_min // 256), int(py_max // 256)

    canvas_w = (tx_max - tx_min + 1) * 256
    canvas_h = (ty_max - ty_min + 1) * 256
    canvas = Image.new("RGB", (canvas_w, canvas_h))

    for tx in range(tx_min, tx_max + 1):
        for ty in range(ty_min, ty_max + 1):
            tile = fetch_tile(zoom, tx, ty, style=style)
            canvas.paste(tile, ((tx - tx_min) * 256, (ty - ty_min) * 256))

    crop_box = (
        int(px_min - tx_min * 256),
        int(py_min - ty_min * 256),
        int(px_max - tx_min * 256),
        int(py_max - ty_min * 256),
    )
    cropped = canvas.crop(crop_box)
    return cropped.resize((FINAL_IMG_SIZE, FINAL_IMG_SIZE))


def fetch_cell_image_for_point(lat, lon, grid_m, style=DEFAULT_TILE_STYLE):
    """指定した緯度経度が属するグリッドセルの地図画像を返す。"""
    zoom = GRID_CONFIGS[grid_m]["zoom"]
    lat_step, lon_step = grid_steps(grid_m)
    gx, gy = cell_id_for(lat, lon, grid_m)
    lat_min, lat_max, lon_min, lon_max = cell_bbox(gx, gy, lat_step, lon_step)
    return build_cell_image(lat_min, lat_max, lon_min, lon_max, zoom, style=style)
