# つうがくナビ バックエンド - Cloudflare Containers 用
#
# ビルドコンテキストはこのファイルと同じディレクトリ(= prepare_container.shが
# 組み立てた、推論に必要な最小構成のディレクトリ)。backend/ml_risk_model/plateauは
# tsugaku-navi-gsiリポジトリ本体と同じ相対パス構造を保っている
# (risk_model.py・accident_data.pyのハードコードされた相対パス参照をそのまま
# 使えるようにするため)。
#
# 旧HuggingFace Spaces版(deploy/huggingface/、traffic_accidentリポジトリ)との
# 違い: `wrangler deploy`はDockerイメージをローカルでビルド・プッシュするだけで
# git commitを経由しない。そのためHF Spaces(gitリポジトリへのpushが必須で、
# ライセンス上コミットできないOSM生ジオメトリキャッシュを同梱できなかった)とは
# 異なり、ml_risk_model/osm_data/(常にgitignore対象、README.md参照)の内容も
# このDockerfileでCOPYして構わない。git管理下に置かない、という制約と、
# Dockerイメージに含める、という制約は別物であることに注意。
#
# データ(モデル・OSM集計/生キャッシュ・事故データ・PLATEAU視界特徴量)は
# 合計約150MB。tile_cache.tar(地図タイル画像のアーカイブ)は含めない・作らない。
# OpenStreetMap Foundationのタイル利用ポリシーとは無関係(地理院タイルを使って
# いるため)だが、地理院タイルについても同じ規律(バルクアーカイブ化はしない、
# 推論時に都度ライブ取得のみ)を踏襲する。

FROM python:3.11-slim

RUN useradd -m -u 1000 appuser
WORKDIR /app

# uv(このプロジェクトのパッケージマネージャ)をインストール
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# 依存関係だけ先にコピーしてsyncすることで、コード変更時にpip/uvの
# 再インストールが走らないようにする(Dockerレイヤーキャッシュ)
COPY backend/pyproject.toml backend/uv.lock /app/backend/
WORKDIR /app/backend
RUN uv sync --frozen --no-dev

WORKDIR /app
COPY accidents.geojson /app/accidents.geojson
COPY backend/ /app/backend/
COPY ml_risk_model/ /app/ml_risk_model/
COPY plateau/ /app/plateau/

RUN chown -R appuser:appuser /app
USER appuser

ENV PORT=8080
EXPOSE 8080

WORKDIR /app/backend
CMD ["uv", "run", "python", "server.py"]
