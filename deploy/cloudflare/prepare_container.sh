#!/bin/bash
# つうがくナビ バックエンドをCloudflare Containersにデプロイするための
# 最小構成ディレクトリを組み立てるスクリプト。
# (旧HuggingFace Spaces版: ../traffic_accident/deploy/huggingface/prepare_space.sh
#  と同じ考え方だが、以下の点が異なる)
#
# - 推論コード・モデル・OSM集計特徴量・視界特徴量は、本リポジトリ
#   (tsugaku-navi、地理院タイル版・GSI版パイプライン)から取る。
#   旧OSM版(traffic_accidentリポジトリ)のものは一切使わない。
# - backend/(lambda_handler.py・accident_data.py・pyproject.toml等、
#   Claude API呼び出しと事故データ集計のロジック)はタイル取得元と無関係
#   なので、tsugaku-navi-backend-space(現行本番、HuggingFace Spaces用に
#   組み立て済みのコピー)からそのまま持ってくる。変更なし。
# - `wrangler deploy`はDockerイメージをローカルビルド・プッシュするだけで
#   git commitを経由しないため、HF Spaces版では除外していた
#   ml_risk_model/osm_data/(生ジオメトリキャッシュ、常にgitignore対象)も
#   Dockerイメージには含める。GitHubには絶対にコミットしないこと
#   (container.gitignore参照、出力先に.gitignoreとしてコピーする)。
#
# 使い方:
#   ./prepare_container.sh [出力先ディレクトリ]
#   (省略時は ../../../tsugaku-navi-cloudflare、このプロジェクトの
#    一つ上の階層に作る。プロジェクト本体のgitリポジトリの外に出す)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GSI_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BACKEND_SRC="$(cd "$GSI_ROOT/../tsugaku-navi-backend-space" && pwd)"
OUT_DIR="${1:-$GSI_ROOT/../tsugaku-navi-cloudflare}"

TILE_STYLE="pale"
MODEL_SEEDS=(42 1 2)

echo "=== GSIリポジトリ: $GSI_ROOT ==="
echo "=== backend/コード取得元: $BACKEND_SRC ==="
echo "=== 出力先: $OUT_DIR ==="

if [ -d "$OUT_DIR/.git" ]; then
    echo "警告: $OUT_DIR には既にgitリポジトリがあります。中身は上書きしますが.gitは残します。" >&2
fi
mkdir -p "$OUT_DIR"
# .git以外を削除してクリーンな状態から組み立てる(誤って古いosm_data等を残さないため)
find "$OUT_DIR" -mindepth 1 -maxdepth 1 -not -name ".git" -exec rm -rf {} +

echo "--- Cloudflare Workers設定 (Dockerfile / wrangler.jsonc / package.json / src/) ---"
cp "$SCRIPT_DIR/Dockerfile" "$OUT_DIR/"
cp "$SCRIPT_DIR/wrangler.jsonc" "$OUT_DIR/"
cp "$SCRIPT_DIR/package.json" "$OUT_DIR/"
cp "$SCRIPT_DIR/tsconfig.json" "$OUT_DIR/"
cp "$SCRIPT_DIR/.dockerignore" "$OUT_DIR/"
cp "$SCRIPT_DIR/container.gitignore" "$OUT_DIR/.gitignore"
mkdir -p "$OUT_DIR/src"
cp "$SCRIPT_DIR/src/index.ts" "$SCRIPT_DIR/src/env.d.ts" "$OUT_DIR/src/"

echo "--- 事故データ (police open data、タイル取得元と無関係、backend-spaceの現行版をそのまま使用) ---"
cp "$BACKEND_SRC/accidents.geojson" "$OUT_DIR/"

echo "--- backend/ (Pythonコード。lambda_handler.py/accident_data.pyはOSM/GSIどちらのタイル源とも無関係) ---"
mkdir -p "$OUT_DIR/backend"
cp "$BACKEND_SRC/backend/accident_data.py" \
   "$BACKEND_SRC/backend/lambda_handler.py" \
   "$BACKEND_SRC/backend/pyproject.toml" \
   "$BACKEND_SRC/backend/uv.lock" \
   "$OUT_DIR/backend/"
cp "$SCRIPT_DIR/server.py" "$OUT_DIR/backend/"

echo "--- ml_risk_model/ (GSI版推論コード + pale本番3runモデル + OSM集計/生キャッシュ) ---"
mkdir -p "$OUT_DIR/ml_risk_model/models" "$OUT_DIR/ml_risk_model/osm_features" "$OUT_DIR/ml_risk_model/osm_data"
cp "$GSI_ROOT/ml_risk_model/risk_model.py" \
   "$GSI_ROOT/ml_risk_model/road_index.py" \
   "$GSI_ROOT/ml_risk_model/tiles.py" \
   "$GSI_ROOT/ml_risk_model/osm_feature_lookup.py" \
   "$OUT_DIR/ml_risk_model/"

for seed in "${MODEL_SEEDS[@]}"; do
    src="$GSI_ROOT/ml_risk_model/models/risk_model_500m_${TILE_STYLE}_poisson_seed${seed}_epoch15.pt"
    if [ ! -f "$src" ]; then
        echo "エラー: $src が見つかりません。risk_model.pyのTILE_STYLE/MODEL_SUFFIX/SEEDSと合っているか確認してください。" >&2
        exit 1
    fi
    cp "$src" "$OUT_DIR/ml_risk_model/models/"
done

cp "$GSI_ROOT/ml_risk_model/osm_features/cell_aggregates_500m.json" "$OUT_DIR/ml_risk_model/osm_features/"

# 【重要】以下2ファイルは個々のOSM要素(信号機・横断歩道の座標、車道wayの座標列)を
# 生の形で保持しており、README.mdの公開可否二値ルール(条件1不成立)によりGitには
# 絶対にコミットしない。ただしDockerイメージには含める(wrangler deployはgit経由の
# デプロイではないため矛盾しない。Dockerfile冒頭のコメント参照)。
if [ ! -f "$GSI_ROOT/ml_risk_model/osm_data/osm_raw_cache_500m.pkl" ] || \
   [ ! -f "$GSI_ROOT/ml_risk_model/osm_data/vehicle_roads_tokyo.parquet" ]; then
    echo "エラー: osm_data/osm_raw_cache_500m.pkl または vehicle_roads_tokyo.parquet が見つかりません。" >&2
    echo "先に extract_osm_raw_cache.py を実行してください。" >&2
    exit 1
fi
cp "$GSI_ROOT/ml_risk_model/osm_data/osm_raw_cache_500m.pkl" \
   "$GSI_ROOT/ml_risk_model/osm_data/vehicle_roads_tokyo.parquet" \
   "$OUT_DIR/ml_risk_model/osm_data/"

echo "--- plateau/ (視界特徴の集計済みCSVのみ) ---"
mkdir -p "$OUT_DIR/plateau/plateau_features"
cp "$GSI_ROOT/plateau/plateau_features/sightline_features_23ku.csv" \
   "$OUT_DIR/plateau/plateau_features/"

echo ""
echo "=== 完了 ==="
du -sh "$OUT_DIR"
echo ""
echo "次の手順:"
echo "  cd $OUT_DIR"
echo "  npm install"
echo "  npx wrangler login"
echo "  npx wrangler secret put ANTHROPIC_API_KEY"
echo "  npx wrangler deploy   # Dockerが起動している必要あり"
echo ""
echo "詳細は deploy/cloudflare/README_DEPLOY.md を参照。"
