"""学習済み危険度回帰CNN(Poisson)による推論と、説明生成用の事実情報取得。

- score_point: 1地点の予測事故件数(3run平均)を返す
- score_route: ルート(緯度経度の配列)沿いを一定間隔でサンプリングしてスコアリングする
- get_point_facts: その地点のOSM属性(信号・横断歩道・道路種別)と、23区内かつ
  PLATEAUカバレッジがある場合は視界特徴の実値を返す

設計方針(旧リポジトリで確定した「分離案」を踏襲): CNNのスコアはルーティング
(どこが危険かのランキング)にのみ使い、「なぜ危険か」の説明はモデルの内部を
可視化する(Grad-CAM等)のではなく、その地点の事実情報(OSM属性・視界特徴の
実値)を使って組み立てる。

CATEGORY_THRESHOLDSは、旧リポジトリの値をそのまま引き継がず、GSI版train全域
(3,803セル、非拡張)へのアンサンブル予測から改めてパーセンタイルを計算すること
(`recompute_category_thresholds()`参照)。学習データ年数範囲・タイル種別が
異なれば予測値の分布も変わるため、値の使い回しはしない。
"""
import math
import os

import torch
from torch import nn
from torchvision import transforms
from torchvision.models import mobilenet_v2

from tiles import DEFAULT_TILE_STYLE, cell_id_for, fetch_cell_image_for_point, grid_steps

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "models")
GRID_M = 500
SEEDS = ["42", "1", "2"]
TILE_STYLE = DEFAULT_TILE_STYLE
MODEL_SUFFIX = "_poisson"

IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]

_TRANSFORM = transforms.Compose([
    transforms.ToTensor(),
    transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
])

# 4段階カテゴリの境界値(3境界: p20/p50/p80)。GSI版(std)train全域(3,803セル、
# 非拡張)への3runアンサンブル予測から算出(2026-07-25、
# `python risk_model.py --recompute-thresholds`の実行結果)。再学習したら
# 必ず計算し直すこと(学習データ年数範囲・タイル種別が変われば分布も変わる)。
CATEGORY_THRESHOLDS = [0.1250891814629237, 2.567613442738851, 5.860166168212891]
CATEGORY_LABELS = ["安全", "やや注意", "要注意", "危険"]

_models = None
_osm_lookup = None
_sightline_lookup = None
_road_index = None


def _build_model():
    model = mobilenet_v2(weights=None)
    in_features = model.classifier[1].in_features
    model.classifier[1] = nn.Linear(in_features, 1)
    return model


def _load_models():
    """3run分のepoch15固定チェックポイントを読み込み、キャッシュする。

    旧リポジトリはtorch.jit.trace+freeze+optimize_for_inferenceで最適化して
    いたが、まずは動作の正しさを優先してeagerモードのまま移植する
    (最適化は推論速度が問題になった時点で追加すること)。
    """
    global _models
    if _models is not None:
        return _models

    _models = []
    for seed in SEEDS:
        path = os.path.join(
            MODELS_DIR, f"risk_model_{GRID_M}m_{TILE_STYLE}{MODEL_SUFFIX}_seed{seed}_epoch15.pt")
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"{path} が見つかりません。先に "
                f"`uv run python train.py --style {TILE_STYLE} --model-suffix {MODEL_SUFFIX}_seed{seed}` "
                f"を実行してください。"
            )
        model = _build_model()
        checkpoint = torch.load(path, map_location="cpu")
        model.load_state_dict(checkpoint["state_dict"])
        model.eval()
        _models.append(model)
    return _models


def _load_osm_lookup():
    global _osm_lookup
    if _osm_lookup is not None:
        return _osm_lookup
    from osm_feature_lookup import OSMFeatureLookup
    _osm_lookup = OSMFeatureLookup()
    return _osm_lookup


def _load_sightline_lookup():
    """23区・PLATEAUカバレッジ完全セルの視界特徴。データファイルが無い場合は
    空辞書を返し、呼び出し側はhas_sightline=Falseにフォールバックする
    (PLATEAU視界特徴の23区評価は現状「後回し」項目、HANDOFF.md参照。
    データは`../traffic_accident/plateau/plateau_data/sightline_features_23ku.csv`
    をこのリポジトリの`plateau/plateau_data/`にコピーするか、
    `plateau/compute_sightline_features.py`で作り直すこと)。
    """
    global _sightline_lookup
    if _sightline_lookup is not None:
        return _sightline_lookup
    import csv
    path = os.path.join(BASE_DIR, "..", "plateau", "plateau_data", "sightline_features_23ku.csv")
    if not os.path.exists(path):
        _sightline_lookup = {}
        return _sightline_lookup
    with open(path, encoding="utf-8") as f:
        _sightline_lookup = {r["cell_id"]: r for r in csv.DictReader(f)}
    return _sightline_lookup


def _load_road_index():
    global _road_index
    if _road_index is not None:
        return _road_index
    from road_index import RoadIndex, load_roads
    _road_index = RoadIndex(load_roads())
    return _road_index


def categorize(predicted_count):
    if CATEGORY_THRESHOLDS is None:
        raise RuntimeError(
            "CATEGORY_THRESHOLDSが未設定です。recompute_category_thresholds()を"
            "先に実行するか、risk_model.CATEGORY_THRESHOLDSに値を設定してください。"
        )
    for threshold, label in zip(CATEGORY_THRESHOLDS, CATEGORY_LABELS):
        if predicted_count < threshold:
            return label
    return CATEGORY_LABELS[-1]


def recompute_category_thresholds(percentiles=(20, 50, 80)):
    """train全域(非拡張)へのアンサンブル予測から4段階カテゴリの境界値を計算する。"""
    import csv
    import numpy as np
    from evaluate_cnn import EvalCountDataset, predict_cnn
    from train import load_vehicle_length

    global CATEGORY_THRESHOLDS
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    models = [m.to(device) for m in _load_models()]

    manifest_path = os.path.join(BASE_DIR, "dataset", f"manifest_train_counts_500m_{TILE_STYLE}.csv")
    with open(manifest_path, encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r.get("source_cell_id", r["cell_id"]) == r["cell_id"]]
    vehicle_length_lookup = load_vehicle_length(
        os.path.join(BASE_DIR, "osm_features", f"osm_features_train_{TILE_STYLE}.csv"))

    all_preds = []
    for model in models:
        pred_by_cell = predict_cnn(model, rows, vehicle_length_lookup, device)
        all_preds.append([pred_by_cell[r["cell_id"]] for r in rows])
    ensemble = np.mean(np.array(all_preds), axis=0)

    CATEGORY_THRESHOLDS = [float(np.percentile(ensemble, p)) for p in percentiles]
    return CATEGORY_THRESHOLDS


def score_point(lat, lon, grid_m=GRID_M):
    """指定地点の予測事故件数(3runアンサンブル平均)を返す。

    画像は指定座標が属するグリッドセルに丸め込んで取得する
    (fetch_cell_image_for_point)。任意中心での切り出し(経路細粒度化)は、
    旧リポジトリでCNNが訓練分布外になり50mシフトで予測値が20〜35%変動する
    ことが確認され断念された経緯がある(STUDY_LOG.md参照)。このリポジトリでも
    同じ制約を引き継ぐ。
    """
    models = _load_models()
    image = fetch_cell_image_for_point(lat, lon, grid_m, style=TILE_STYLE)
    tensor = _TRANSFORM(image).unsqueeze(0)

    lookup = _load_osm_lookup()
    feats = lookup.features_for(lat, lon)
    log_exposure = math.log(feats["vehicle_length_m"] + 1.0)

    preds = []
    with torch.no_grad():
        for model in models:
            raw = model(tensor)[0, 0].item()
            preds.append(math.exp(raw + log_exposure))
    return sum(preds) / len(preds)


def get_point_facts(lat, lon, grid_m=GRID_M):
    """説明生成用の事実情報。OSM属性は常に返す。視界特徴は23区・カバレッジが
    ある場合のみ返し、無ければhas_sightline=Falseにする(多摩地域・データ未整備
    のフォールバック)。
    """
    lookup = _load_osm_lookup()
    osm = lookup.features_for(lat, lon)

    gx, gy = cell_id_for(lat, lon, grid_m)
    cell_id = f"{grid_m}m_{gx}_{gy}"
    sightline_lookup = _load_sightline_lookup()
    sight = sightline_lookup.get(cell_id)

    facts = {
        "cell_id": cell_id,
        "osm": {
            "signal_count": osm["signal_count"],
            "signal_nearest_m": round(osm["signal_nearest_m"], 1),
            "crossing_count": osm["crossing_count"],
            "crossing_nearest_m": round(osm["crossing_nearest_m"], 1),
            "footway_ratio": round(osm["footway_ratio"], 3),
            "vehicle_intersection_count": osm["vehicle_intersection_count"],
            "dominant_road_type": max(
                ["primary", "secondary", "tertiary", "residential", "service", "unclassified", "trunk"],
                key=lambda hw: osm[f"{hw}_ratio"],
            ),
        },
        "has_sightline": sight is not None,
    }
    if sight is not None:
        facts["sightline"] = {
            "mean_sightline_m": round(float(sight["sightline_mean_of_mean"]), 1),
            "worst_direction_sightline_m": round(float(sight["sightline_worst_min"]), 1),
            "open_direction_fraction": round(float(sight["sightline_mean_open_fraction"]), 3),
        }
    return facts


def get_route_crossings(route_coords):
    """ルート([(lat, lon), ...])が実際に車道を横切る地点を検出し、横断歩道・信号の
    有無で分類する。road_index.RoadIndexが車道の線形状から「歩いている道に沿って
    いるだけ」と「実際に横切っている」を区別し(交差角度が浅い=平行なら除外)、
    横断歩道の実座標(OSMFeatureLookup)が近くにあるかどうかで
    has_marked_crossing/has_signalを判定する。
    """
    from road_index import MARKED_CROSSING_MAX_M, SIGNAL_NEAR_CROSSING_MAX_M, RoadIndex

    road_index = _load_road_index()
    osm_lookup = _load_osm_lookup()
    raw = road_index.crossings_for_route(route_coords)

    classified = []
    for c in raw:
        cd = osm_lookup._nearest_via_bucket(c["lat"], c["lon"], osm_lookup.crossing_buckets)
        has_marked_crossing = cd is not None and cd <= MARKED_CROSSING_MAX_M
        has_signal = False
        if has_marked_crossing:
            sd = osm_lookup._nearest_via_bucket(c["lat"], c["lon"], osm_lookup.signal_buckets)
            has_signal = sd is not None and sd <= SIGNAL_NEAR_CROSSING_MAX_M
        classified.append({
            "lat": c["lat"], "lon": c["lon"], "highway": c["highway"],
            "has_marked_crossing": has_marked_crossing, "has_signal": has_signal,
            "_cd": cd if cd is not None else float("inf"),
        })

    deduped = RoadIndex.dedup_crossings(
        classified,
        key=lambda c: (c["has_marked_crossing"], c["has_signal"], -c["_cd"])
    )

    return [{
        "lat": round(c["lat"], 6), "lon": round(c["lon"], 6),
        "highway": c["highway"],
        "has_marked_crossing": c["has_marked_crossing"],
        "has_signal": c["has_signal"],
    } for c in deduped]


def get_narrow_road_segments(route_coords, sample_every_m=30):
    """ルートのうち、実際に細い道路種別(住宅街の道・私道等)に沿っている区間を
    検出する。線単位の判定(road_index.nearest_road_type)を使うため、
    セル単位のdominant_road_typeのようなズレが起きない。CNN推論を伴わない
    純粋な幾何演算のため、細かいサンプリングでも訓練分布外の問題は関係ない。
    """
    from road_index import NARROW_HIGHWAY_TYPES

    road_index = _load_road_index()
    sampled = _sample_route([tuple(p) for p in route_coords], sample_every_m, max_points=200)

    labeled = []
    for lat, lon in sampled:
        hw = road_index.nearest_road_type(lat, lon)
        labeled.append({"lat": lat, "lon": lon, "is_narrow": hw in NARROW_HIGHWAY_TYPES})

    segments = []
    current = None
    for point in labeled:
        if point["is_narrow"]:
            if current is None:
                current = {"start": (point["lat"], point["lon"]), "end": (point["lat"], point["lon"])}
            else:
                current["end"] = (point["lat"], point["lon"])
        else:
            if current is not None:
                segments.append(current)
                current = None
    if current is not None:
        segments.append(current)

    return [
        {
            "start_lat": round(s["start"][0], 6), "start_lon": round(s["start"][1], 6),
            "end_lat": round(s["end"][0], 6), "end_lon": round(s["end"][1], 6),
        }
        for s in segments if s["start"] != s["end"]
    ]


def _haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _sample_route(points, sample_every_m, max_points):
    """ルートを一定間隔でサンプリングし、[(lat, lon), ...] を返す(始点・終点は必ず含む)。"""
    if len(points) == 1:
        return [tuple(points[0])]

    samples = [tuple(points[0])]
    dist_since_last_sample = 0.0
    for (lat1, lon1), (lat2, lon2) in zip(points[:-1], points[1:]):
        seg_len = _haversine_m(lat1, lon1, lat2, lon2)
        if seg_len == 0:
            continue
        dist_since_last_sample += seg_len
        while dist_since_last_sample >= sample_every_m and len(samples) < max_points - 1:
            overshoot = dist_since_last_sample - sample_every_m
            frac = 1 - (overshoot / seg_len)
            samples.append((lat1 + (lat2 - lat1) * frac, lon1 + (lon2 - lon1) * frac))
            dist_since_last_sample -= sample_every_m

    samples.append(tuple(points[-1]))
    if len(samples) > max_points:
        step = (len(samples) - 1) / (max_points - 1)
        samples = [samples[round(i * step)] for i in range(max_points)]
    return samples


def _hazard_tiebreak_score(facts):
    """同じ500mセル内(=同じ予測値・同じセル集計属性)の候補地点が複数あるときに、
    どれを代表点として選ぶかのタイブレーク基準。crossing_nearest_m/signal_nearest_mは
    地点ごとの正確な最近傍距離(セルへの丸め込みなし)なので、これを使うと
    「実際に横断歩道や信号に近い地点」を代表点に選べる。
    """
    osm = facts["osm"]
    return -min(osm["crossing_nearest_m"], osm["signal_nearest_m"])


def score_route(points, grid_m=GRID_M, sample_every_m=150, max_points=12, max_risky_segments=3):
    """ルート沿いを一定間隔でサンプリングし、各点の予測事故件数・カテゴリと集計値を返す。"""
    sampled = _sample_route([tuple(p) for p in points], sample_every_m, max_points)
    scored = []
    for lat, lon in sampled:
        predicted_count = score_point(lat, lon, grid_m)
        gx, gy = cell_id_for(lat, lon, grid_m)
        scored.append({
            "lat": round(lat, 6), "lon": round(lon, 6),
            "predicted_count": round(predicted_count, 4),
            "category": categorize(predicted_count),
            "cell": (gx, gy),
        })
    counts = [p["predicted_count"] for p in scored]
    max_category = max(scored, key=lambda p: p["predicted_count"])["category"]

    cells = {}
    for p in scored:
        cells.setdefault(p["cell"], []).append(p)
    ranked_cells = sorted(cells.items(), key=lambda kv: -kv[1][0]["predicted_count"])[:max_risky_segments]

    risky_points_facts = []
    for cell, candidates in ranked_cells:
        facts_by_id = {id(p): get_point_facts(p["lat"], p["lon"], grid_m) for p in candidates}
        best = max(candidates, key=lambda p: _hazard_tiebreak_score(facts_by_id[id(p)]))
        risky_points_facts.append({
            "lat": best["lat"], "lon": best["lon"],
            "predicted_count": best["predicted_count"], "category": best["category"],
            "facts": facts_by_id[id(best)],
        })

    for p in scored:
        del p["cell"]

    route_crossings = get_route_crossings(points)
    narrow_road_segments = get_narrow_road_segments(points)

    return {
        "grid_m": grid_m,
        "max_predicted_count": round(max(counts), 4),
        "mean_predicted_count": round(sum(counts) / len(counts), 4),
        "max_category": max_category,
        "points": scored,
        "risky_points_facts": risky_points_facts,
        "route_crossings": route_crossings,
        "narrow_road_segments": narrow_road_segments,
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--recompute-thresholds", action="store_true")
    args = parser.parse_args()
    if args.recompute_thresholds:
        thresholds = recompute_category_thresholds()
        print(f"CATEGORY_THRESHOLDS = {thresholds}")
