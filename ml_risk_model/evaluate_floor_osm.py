"""フロア/OSM Poisson回帰(GBDT)の評価(件数/率回帰、v3設計の主指標)。

主指標: 残差Spearman(フロア予測に対する残差の順位相関)。フロアモデル
(駅距離・エッジ密度・建造物率+log曝露量)をtrainで学習し、evalに適用した
予測値を基準に、実測値・評価対象モデル予測値をそれぞれ
log(1+x) - log(1+floor_pred) で残差化してから順位相関を取る。フロア自身の
残差は定義上0になるため、健全性チェックが指標に組み込まれる
(旧リポジトリでの指標改訂の経緯: 初版の「5分位層内Spearman」はフロア自身が
0から乖離する残差交絡があったため、この残差Spearman方式に置き換えられた。
詳細は`../traffic_accident/ml_risk_model/PREREGISTRATION_COUNT_REGRESSION.md`
「改訂履歴」参照)。

あわせて、条件付き過分散(Pearson残差の分散)と、log(1+y)二乗誤差回帰による
頑健性チェック(分布仮定に対する順位の安定性確認)も行う。
"""
import csv
import json
import os

import numpy as np
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor

from tiles import DEFAULT_TILE_STYLE

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
POISSON_PARAMS = dict(loss="poisson", max_depth=2, max_iter=30, learning_rate=0.05, random_state=10)
SQUARED_PARAMS = dict(loss="squared_error", max_depth=2, max_iter=30, learning_rate=0.05, random_state=10)

OSM_FEATURE_COLS = [
    "vehicle_length_m", "footway_length_m", "footway_ratio", "signal_count", "crossing_count",
    "vehicle_intersection_count", "vehicle_footway_intersection_count", "signal_nearest_m",
    "crossing_nearest_m", "primary_ratio", "secondary_ratio", "tertiary_ratio",
    "residential_ratio", "service_ratio", "unclassified_ratio", "trunk_ratio",
]


def load_joined(style, is_eval):
    """train/evalのmanifestとosm_features_*.csvをcell_id単位で結合する。

    accident_countは常にmanifest側の値を正とする(osm_features_*.csv自身の
    同名列は生成時点のコピーに過ぎず、別のmanifestを渡すと古いまま残る
    バグを旧リポジトリで一度出したため)。
    """
    if is_eval:
        manifest_path = os.path.join(BASE_DIR, "eval_frozen", style, "500m", "eval_manifest.csv")
        osm_name = f"osm_features_eval_{style}.csv"
    else:
        manifest_path = os.path.join(BASE_DIR, "dataset", f"manifest_train_counts_500m_{style}.csv")
        osm_name = f"osm_features_train_{style}.csv"

    with open(manifest_path, encoding="utf-8") as f:
        manifest_rows = {r["cell_id"]: r for r in csv.DictReader(f)}

    osm_path = os.path.join(BASE_DIR, "osm_features", osm_name)
    with open(osm_path, encoding="utf-8") as f:
        osm_rows = list(csv.DictReader(f))

    joined = []
    for r in osm_rows:
        m = manifest_rows.get(r["cell_id"])
        if m is None:
            continue
        row = dict(r)
        row["accident_count"] = m["accident_count"]
        row["station_dist"] = m["station_dist_m"] if is_eval else m["station_dist"]
        row["edge_density"] = m["edge_density"]
        row["built_env_fraction"] = m["built_env_fraction"]
        joined.append(row)
    return joined


def to_matrix(rows, cols):
    return np.array([[float(r[c]) for c in cols] for r in rows])


def log_vehicle(rows):
    return np.log(np.array([float(r["vehicle_length_m"]) for r in rows]) + 1.0)


def residual_spearman(model_pred_eval, floor_pred_eval, y_eval, log_space_model_pred=False, log_space_floor_pred=False):
    """log(1+pred) - log(1+floor_pred) の順位相関(残差Spearman)。
    log_space_*=Trueの場合、そのpredは既にlog1p空間の値として渡されている(そのまま使う)。
    """
    floor_log = floor_pred_eval if log_space_floor_pred else np.log1p(np.clip(floor_pred_eval, 0, None))
    model_log = model_pred_eval if log_space_model_pred else np.log1p(np.clip(model_pred_eval, 0, None))
    y_log = np.log1p(y_eval)

    r_y = y_log - floor_log
    r_model = model_log - floor_log

    if np.allclose(r_model.std(), 0):
        return 0.0, "自己比較(定義上ゼロ、分散なしのため相関は未定義→0として扱う)"
    rho, _ = spearmanr(r_model, r_y)
    return float(rho), None


def conditional_dispersion(y, pred):
    """Pearson残差(y-pred)/sqrt(pred)の分散。1に近ければPoisson仮定は妥当、
    大きく上回れば条件付き過分散が残っている。"""
    pred_safe = np.clip(pred, 1e-6, None)
    pearson_resid = (y - pred_safe) / np.sqrt(pred_safe)
    return float(np.var(pearson_resid))


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--style", choices=["std", "pale"], default=DEFAULT_TILE_STYLE)
    args = parser.parse_args()
    style = args.style

    train_rows = load_joined(style, is_eval=False)
    eval_rows = load_joined(style, is_eval=True)
    print(f"train: {len(train_rows)}件  eval: {len(eval_rows)}件")

    y_train = np.array([float(r["accident_count"]) for r in train_rows])
    y_eval = np.array([float(r["accident_count"]) for r in eval_rows])

    X_floor_train = np.column_stack([
        to_matrix(train_rows, ["station_dist", "edge_density", "built_env_fraction"]), log_vehicle(train_rows),
    ])
    X_floor_eval = np.column_stack([
        to_matrix(eval_rows, ["station_dist", "edge_density", "built_env_fraction"]), log_vehicle(eval_rows),
    ])
    X_osm_train = np.column_stack([to_matrix(train_rows, OSM_FEATURE_COLS), log_vehicle(train_rows)])
    X_osm_eval = np.column_stack([to_matrix(eval_rows, OSM_FEATURE_COLS), log_vehicle(eval_rows)])

    # === Poissonパイプライン(主指標) ===
    floor_poisson = HistGradientBoostingRegressor(**POISSON_PARAMS).fit(X_floor_train, y_train)
    osm_poisson = HistGradientBoostingRegressor(**POISSON_PARAMS).fit(X_osm_train, y_train)

    floor_pred_train = floor_poisson.predict(X_floor_train)
    floor_pred_eval = floor_poisson.predict(X_floor_eval)
    osm_pred_train = osm_poisson.predict(X_osm_train)
    osm_pred_eval = osm_poisson.predict(X_osm_eval)

    disp_floor_train = conditional_dispersion(y_train, floor_pred_train)
    disp_osm_train = conditional_dispersion(y_train, osm_pred_train)
    disp_floor_eval = conditional_dispersion(y_eval, floor_pred_eval)
    disp_osm_eval = conditional_dispersion(y_eval, osm_pred_eval)

    print("=== 条件付き過分散(Pearson残差の分散、1に近いほどPoisson仮定が妥当) ===")
    print(f"フロア: train={disp_floor_train:.2f}  eval={disp_floor_eval:.2f}")
    print(f"OSM:   train={disp_osm_train:.2f}  eval={disp_osm_eval:.2f}")
    marginal_train = float(y_train.var() / y_train.mean())
    marginal_eval = float(y_eval.var() / y_eval.mean())
    print(f"(参考: 周辺の分散/平均比は train={marginal_train:.2f} eval={marginal_eval:.2f})")

    rho_floor_self, note_floor = residual_spearman(floor_pred_eval, floor_pred_eval, y_eval)
    rho_osm, _ = residual_spearman(osm_pred_eval, floor_pred_eval, y_eval)

    print("\n=== 主指標: 残差Spearman(フロア予測に対する残差の順位相関) ===")
    print(f"フロア自身: {rho_floor_self:.3f} ({note_floor})")
    print(f"OSM:       {rho_osm:.3f}")

    # === 頑健性チェック: log(1+y)二乗誤差回帰 ===
    y_train_log = np.log1p(y_train)
    floor_sq = HistGradientBoostingRegressor(**SQUARED_PARAMS).fit(X_floor_train, y_train_log)
    osm_sq = HistGradientBoostingRegressor(**SQUARED_PARAMS).fit(X_osm_train, y_train_log)
    floor_log_pred_eval = floor_sq.predict(X_floor_eval)
    osm_log_pred_eval = osm_sq.predict(X_osm_eval)

    rho_floor_self_sq, _ = residual_spearman(
        floor_log_pred_eval, floor_log_pred_eval, y_eval,
        log_space_model_pred=True, log_space_floor_pred=True,
    )
    rho_osm_sq, _ = residual_spearman(
        osm_log_pred_eval, floor_log_pred_eval, y_eval,
        log_space_model_pred=True, log_space_floor_pred=True,
    )

    print("\n=== 頑健性チェック: log(1+y)二乗誤差回帰での残差Spearman ===")
    print(f"フロア自身: {rho_floor_self_sq:.3f}")
    print(f"OSM:       {rho_osm_sq:.3f}")
    print(f"(Poissonベースと比較: フロア {rho_floor_self:.3f} vs {rho_floor_self_sq:.3f}、"
          f"OSM {rho_osm:.3f} vs {rho_osm_sq:.3f})")

    result = {
        "tile_style": style,
        "n_train": len(train_rows), "n_eval": len(eval_rows),
        "marginal_overdispersion": {"train": marginal_train, "eval": marginal_eval},
        "conditional_dispersion_pearson_resid_var": {
            "floor": {"train": disp_floor_train, "eval": disp_floor_eval},
            "osm": {"train": disp_osm_train, "eval": disp_osm_eval},
        },
        "residual_spearman_poisson": {"floor_self": rho_floor_self, "osm": rho_osm},
        "residual_spearman_log1p_squared_robustness_check": {"floor_self": rho_floor_self_sq, "osm": rho_osm_sq},
    }
    out_dir = os.path.join(BASE_DIR, "eval_frozen", style, "500m")
    out_path = os.path.join(out_dir, "floor_osm_result.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n保存: {out_path}")


if __name__ == "__main__":
    main()
