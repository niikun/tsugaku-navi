# Cloudflare Containersへのデプロイ手順

つうがくナビ バックエンドを、GSI版モデル(pale本番3run)込みでCloudflare
Containersにデプロイする手順。旧HuggingFace Spaces版
(`../../../traffic_accident/deploy/huggingface/`)からの移行で、目的は:

1. **本番モデルの差し替え**: 現行のHF Space(`tsugaku-navi-backend-space`)は
   実は旧OSM版モデルのままで、かつOSMライセンス対応のため生ジオメトリ
   キャッシュを同梱できず`get_point_facts`の一部・`route_crossings`・
   `narrow_road_segments`が動作していない。この構成ではGSI版pale本番モデル
   一式(生キャッシュ込み)を積むため、両方解消される。
2. **コスト削減**: HuggingFace SpacesのDocker SDKはPRO以上の有料プラン
   ($9/月〜)が必須。Cloudflare Workers Paid($5/月〜、ハッカソン特典で
   期間中は無償)の方が安い。

## 事前準備(あなたが行うこと)

### 1. ハッカソン特典の申請

`https://odh-tokyo2026.code4japan.org/2026-Cloudflare-Paid-...`に記載の
5ステップ(Cloudflareアカウント作成→Googleフォーム申請→事務局登録→
招待メール受信→チーム切り替え)を完了させる。**Cloudflareアカウント作成は
済んでいるとのことなのでStep 2から。**

特典は2026年9月末まで(ファイナリスト等は延長)。**期間終了後は権限停止で
デプロイ済みサービスが動かなくなるため、事前にこのディレクトリ一式を
GitHubにバックアップすること**(`.gitignore`は`ml_risk_model/osm_data/`を
除外済みなので、そのままgit initしてpushして問題ない)。

### 2. Docker

`wrangler deploy`はコンテナイメージをローカルでビルドするため、Dockerが
起動している環境で実行する必要がある(このセッションの開発機には未導入)。

### 3. ANTHROPIC_API_KEY

`/ask`エンドポイント(Claude APIで説明文生成)に必要。`/score`のみなら不要。

## 手順

```bash
# 1. デプロイバンドルを組み立てる(tsugaku-naviリポジトリ直下から実行)
cd ml_risk_model && \
  ls osm_data/osm_raw_cache_500m.pkl osm_data/vehicle_roads_tokyo.parquet && \
  cd .. # 無ければ先に extract_osm_raw_cache.py を実行
./deploy/cloudflare/prepare_container.sh

# 2. 組み立てたディレクトリに移動
cd ../tsugaku-navi-cloudflare

# 3. Node依存関係をインストール
npm install

# 4. Cloudflareにログイン(ブラウザでOAuth)
npx wrangler login

# 5. ハッカソン特典適用後のアカウント/チームを選択
#    (複数アカウントがある場合 `npx wrangler whoami` で確認、
#     wrangler.jsonc に "account_id" を追記して固定してもよい)

# 6. Secretsを設定
npx wrangler secret put ANTHROPIC_API_KEY

# 7. 型定義を生成(任意、エディタ補完用)
npm run types

# 8. デプロイ(Docker起動が必要、初回は数分かかる)
npx wrangler deploy
```

デプロイ後に表示されるURL(`https://tsugaku-navi-backend.<subdomain>.workers.dev`)
が新しいバックエンドのエンドポイント。フロントエンド側の呼び出し先URLを
これに更新すること(現行は`niikun.net/traffic_accident`のapp.jsがHF Spaceの
URLを指しているはず)。

## 動作確認

```bash
curl -X POST https://<デプロイ先URL>/score \
  -H "Content-Type: application/json" \
  -d '{"home": {"lat": 35.6938, "lon": 139.7034}, "school": {"lat": 35.6895, "lon": 139.6917}, "route": null}'
```

`risk_points`・`route_crossings`・`narrow_road_segments`が正しく返ることを
確認する(HF Spaces版ではosm_data不足のため一部が動作していなかった箇所)。

## 注意点

- **初回コンテナ起動は数分かかる**(`wrangler deploy`直後、READMEの
  「Cold Start & Scale Behavior」参照)。デモ直前に一度リクエストを
  送っておくと安心。
- **`sleepAfter`は10分**(`src/index.ts`)。無活動状態が続くとコンテナは
  止まり、次のリクエストで再起動(数秒〜数十秒のコールドスタート)する。
  ハッカソン審査のタイミングに合わせて事前ウォームアップすることを推奨。
- **`ml_risk_model/osm_data/`配下は絶対にGitHubにコミットしない**
  (このディレクトリの`.gitignore`で除外済み、`prepare_container.sh`を
  再実行しても上書きされない設定のはず。念のため`git status`で確認する
  こと)。
- 特典期間終了(2026-09-30予定)後はコンテナが動かなくなる。継続利用する
  場合は自費でのWorkers Paid契約($5/月〜)に切り替えるか、他のホスティング
  先を検討すること。
