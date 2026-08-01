# 引き継ぎメモ

## 現在地(2026-07-26時点): フェーズ0〜3のコア部分完了。pale版CNN
## (本番用全量データ、3run)を採用しrisk_model.pyを差し替え済み。
## Cloudflare Containersへの本番デプロイも完了・稼働確認済み
## (`https://tsugaku-navi-backend.tokyo-odh-097.workers.dev`)。
## フロントエンド(`frontend/`)もこのリポジトリに統合済み。
## 残作業はS3への手動アップロード確認・GitHubバックアップ・企画書最終化のみ
## (詳細は本ファイル末尾「次にやること」参照)

**重要な訂正の記録(2026-07-25)**: 当初「GSI版std CNN(0.484)が旧OSM版
(0.376)を上回った」と報告したが、これは評価セットのセル集合・事故ラベルの
年数範囲がこのリポジトリ独自(7年)と旧OSM版(4年固定)で異なっていたため
無効な比較だった。ユーザー指摘により一致セットで再検証した結果、
GSI版stdは旧OSM版に統計的に確定的に劣ることが判明(bootstrap CI
[-0.156,-0.048])。その後std/pale比較(旧OSM版には触れない自己完結型の
判定基準に切り替え)を行い、pale版を採用した。

**さらなる訂正(同日)**: pale版本番採用後の「全域0.439」も、山間部・低
インフラセルによる水増しと判明。CNN+視界stackingの劣化(-0.079)はGBDT
量子化アーティファクトと判明(線形コンバイナでは-0.001)。条件付き分散
異常(1049.65)は既知の数学的アーティファクト(2セル限定、順位指標への
影響なし)と確定診断。**さらに`built_env_fraction`(フロアの入力特徴量)の
色ヒューリスティックにバグがあり(山間部の白背景を「建造物」に誤分類)、
修正して都市部限定のフロアを再計算したところ、CNN残差Spearmanは
0.344ではなく最終的に**0.28程度**が正しい値と判明(vehicle_length_mとの
相関0.198→0.842に改善したことで確認)。企画書・Q&Aで使う見出し数値は
**0.28程度**とすること(0.439や0.344ではない)。本番モデル(risk_model.py)
自体はbuilt_env_fractionを使わないため再学習は不要。4件とも「ユーザーが
見出し数値を鵜呑みにせず追加検証を要求した」ことで発覚・解決した。
詳細な経緯・全数値は`ml_risk_model/STUDY_LOG.md`を必読。

背景・全体計画は `../traffic_accident/PLAN_GSI_MIGRATION.md` を参照
(締切2026-08-23、残り約29日、バッファほぼゼロ)。発覚経緯の全記録は
`../traffic_accident/ml_risk_model/STUDY_LOG.md` の「OSMライセンス問題の
発覚と対応」節。

**このリポジトリの大前提**: OSM由来のコード・データ・学習済みモデルを
一切持ち込まずにゼロから構築する。理由は2つ:
1. OSM標準タイルサーバー(`tile.openstreetmap.org`)由来のタイル画像を
   CNN学習に使っていたのが、OpenStreetMap FoundationのTile Usage Policy
   (標準タイルサーバー由来タイルの大量ダウンロード・アーカイブ化を禁止)に
   抵触していた
2. `cell_features_500m.pkl`等、「集計特徴量ファイル」だと思われていたものが
   実際には個々のOSM要素(道路座標列424,415件・信号機個別座標27,896件・
   横断歩道個別座標96,496件)を生の形で保持しており、ODbLのDerivative
   Databaseに該当する可能性が高いと判明した

## 今やっていること: フェーズ0(準備)

### 完了

- [x] **2.1 タイル画像比較**: OSM標準・地理院タイルstd・pale を実地点(新宿・
      立川・世田谷住宅地)で比較。`std`を採用候補に決定(pale次点)。
      駅名等の巨大ラベルは駅近接セルのみの局所的な問題、住宅地では道路階層の
      視覚的区別も十分機能することを確認済み
- [x] **2.2 利用規約の反映方法**: 出典表示文言・レート制限(0.5秒/枚)・
      User-Agent(`tsugaku-navi/1.0 (contact: niikun0209@gmail.com; ...)`)
      を確定
- [x] **2.3 新リポジトリ雛形**: `.gitignore`作成、新規`ml_risk_model/tiles.py`
      (地理院タイルstd版)を実装・動作確認済み(実際にタイル取得→256x256の
      セル画像合成まで成功)
- [x] 独立監査エージェントによる第三者チェックを実施(詳細は下記「監査で
      見つかった問題」)。指摘事項はすべて対応済み

### 監査で見つかった問題と対応(重要、必読)

自分で「OSM非依存のはず」と簡易grep(`tile|fetch_tile|osmium|.pbf`)で
チェックしてから旧プロジェクトのファイルをコピーしたが、独立監査エージェントに
`spatial_block_split.py`が**Overpass API**(OSM本体のクエリAPI、タイル・PBFとは
別の仕組み)を叩いて駅の個別座標を`stations_cache.json`に生のままキャッシュ
していることを発見された。`signal_points`/`crossing_points`と同じ性質の
リスクを、対象を変えて見落としていた。

**教訓**: OSM関連キーワードのチェックは`tile|osmium|.pbf`だけでは不十分。
`overpass`のような関連APIのキーワードも必ず含めること。ファイルを機械的に
コピーする前に、他人の目(サブエージェントでも可)でもう一段チェックを
入れる価値がある。

対応済み:
- `spatial_block_split.py`をリポジトリから削除(現状`build_dataset.py`未移植で
  どのみち実行不能だった。駅距離ベースの交絡確認が必要になったら、
  国土数値情報(鉄道)等のOSM以外の政府オープンデータで作り直すこと)
- `.gitignore`を、ファイル名パターンでの許可制(漏れるリスクあり)から、
  `ml_risk_model/osm_data/`ディレクトリ丸ごとのdeny-by-default方式に変更。
  `*_cache.json`(Overpass等の外部API個別要素キャッシュ全般)も追加
- `tiles.py`・`tokyo_boundary.py`のdocstring中、旧リポジトリへの相対パス
  参照(`../traffic_accident/...`)が「別リポジトリを指している」旨を
  明示するよう修正(このリポジトリ単体で読むと存在しないパスだったため)

- [x] **2.4 OSMベクターデータのファイル分類・帰属表示**: `README.md`を
      新規作成し、地理院タイル・警察庁オープンデータ・国土数値情報・
      PLATEAUの各出典表示と、OSMベクターデータの公開可否二値ルール
      (条件1: 個々のOSM要素を含まない集計統計のみ、条件2: 帰属表示あり、
      の両方を満たさないファイルは`.gitignore`対象)を明文化した

フェーズ0は完了(初回コミット`ad9d846`)。

## 今やっていること: フェーズ1(データ取得元の切り替え・パイプライン本体)

### 完了

- [x] **3.1 tiles.pyの書き換え**: 地理院タイル(GSI)に切り替え済み。さらに
      std/pale両対応にし(`TILE_STYLES`)、フェーズ1で両方学習しCNN精度を
      比較する設計にした(タイルキャッシュ・データセット出力先もstyleごとに
      分離)
- [x] **学習パイプライン本体を新規実装**(v1/v2の二値分類・層化負例サンプリング
      設計は使わず、v3=件数/率回帰設計を唯一のバージョンとして採用。旧
      traffic_accidentリポジトリのSTUDY_LOG.mdで「確定・完了」とされていた
      設計):
      - `spatial_block_split.py` — train/valの空間ブロック分割(純粋な空間計算、
        OSM非依存)
      - `station_points.py` + `prepare_station_data.py` — 駅距離の交絡チェック用
        駅データ。旧リポジトリのOverpass API依存を、国土数値情報N02(鉄道、
        2022年度)に置き換えた。東京本土の駅1,530件(概算・重複統合済み)
      - `build_dataset.py` — 事故CSV読み込み・セル別事故件数集計
      - `build_eval_set.py` — valブロック全セルを凍結評価セット化(選抜なし)。
        `ensure_image`/`built_env_fraction`はtrain側からも共用
      - `build_train_set.py` — trainブロック全セルのmanifest生成
      - `edge_density.py` — 画像ベースの建造物密度代理指標
      - `extract_osm_raw_cache.py` — pyosmiumでPBFを1パス処理し、信号機・
        横断歩道の個別座標や車道wayの座標列を含む生キャッシュを
        `osm_data/`(常にgitignore対象)に出力。旧リポジトリと同じ件数
        (車道way 424,415件・信号機27,896件・横断歩道96,496件)を実行確認済み
      - `extract_osm_features.py` — 生キャッシュから集計統計のみを取り出し、
        `osm_features/cell_aggregates_500m.json`(コミット可能、帰属表示付き)
        に書き出す。JSON形式にしたのは、`.gitignore`の`*.pkl`/`*.parquet`
        一律除外ルールと衝突せず、かつdiffでレビューできるようにするため
      - `osm_feature_lookup.py` — `OSMFeatureLookup`(集計JSONからセル特徴を
        引き、最近傍距離だけは実行時に生キャッシュを読んで計算。結果は
        ファイルに書き戻さない)
      - `road_index.py` — ほぼそのまま移植(元々ソースコードに座標を持たない
        設計で、監査で「良い設計の手本」と評価されていた)
      - 上記すべて、実データ(コピー済みの警察庁事故CSV・生成したN02駅
        データ・実際に抽出したOSM生キャッシュ)でスモークテスト済み
- [x] `.gitignore`のバグ発見・修正: `dataset/**/*.png`のようなmiddle-slash
      パターンは、gitignore仕様上「リポジトリルート直下」にのみ有効な
      anchoredパターンになり、実際のパス`ml_risk_model/dataset/`には
      効いていなかった。`ml_risk_model/dataset/`・`ml_risk_model/eval_frozen/`
      という実パスに修正した(教訓: サブディレクトリにあるパスをgitignore
      する際は、`**`を使う場合でも実際に`git check-ignore -v`で確認すること)

### 完了(続き、2026-07-25)

- [x] **eval分(valブロック896セル)をstd/pale両方で先行取得**: 破損・欠損なし
      896/896件、所要時間はどちらも約41.5分(実測。レート制限0.5秒/枚は
      守られている)
- [x] **std/pale目視比較→std採用を決定**: 渋谷駅(高密度商業地、事故66件)・
      本天沼(中密度住宅地、事故3件)の2セルで比較。stdは建物が塗りつぶし
      (オレンジ)表示で密度・形状が視覚的に強く際立ち、道路も種別ごとに
      色分けされ階層が判別しやすい。paleは建物が輪郭線のみでコントラストが
      大幅に低く、CNNが密度・形状パターンを学習する材料としては情報量が
      少ないと判断。フェーズ0.1のstd優先判断を裏付ける結果
      - **train全量(3,803セル)はstdのみ取得する**(1スタイル約2.9時間、
        両方だと約5.9時間のため、片方に絞って時間短縮)。pale版train全量は
        取得しない。paleはPLAN_GSI_MIGRATION §6.Aの事前登録済みフォールバック
        (std版CNNがOSM版v4の精度に届かない場合の一回限りの再試行選択肢)
        として温存する
- [x] `osm_feature_lookup.py`のCSV出力名を`osm_features_{train,eval}_{style}.csv`
      とし、std/pale両対応にしてある(pale版は今回evalのみ生成、trainは
      当面生成しない)

- [x] **3.2 train全量(std)の地理院タイル取得完了**: 3,803セル全件取得、破損・
      欠損なし。所要時間約2h55m(実測、レート制限0.5秒/枚を遵守)。
      `augment_dataset.py --style std`実行(15,212件、生画像の4倍)、
      `osm_feature_lookup.py --style std`実行(train 3,803件・eval 896件の
      OSM特徴量CSVを`osm_features/`に生成・コミット可能)
      - **バグ修正**: `osm_feature_lookup.py`が当初、拡張画像行(`_aug1`等)も
        含めてOSM特徴量を紐付けており、train CSVが15,212行に膨張していた
        (旧リポジトリは`source_cell_id==cell_id`で元画像のみに絞る設計だった)。
        同じフィルタを追加し3,803行に修正
- [x] **3.3 回帰テスト**: `evaluate_floor_osm.py --style std`を実行し、
      フロア/OSM Poisson GBDT(画像を一切使わない、OSM特徴量のみのベースライン)
      の残差Spearmanが旧OSM版(タイル画像のみ変更前)の実測値と近いことを確認。
      **フロア自身=0.000(健全性チェック、定義通り)、OSM=0.201**
      (旧OSM版の実測値0.211と近い、差0.010は誤差範囲)。OSM特徴量抽出
      パイプライン(extract_osm_raw_cache.py→extract_osm_features.py→
      osm_feature_lookup.py)・空間ブロック分割・セル列挙が旧リポジトリと
      整合していることの強い傍証。周辺の分散/平均比は旧(train6.38/eval6.64)
      よりやや高い(train11.61/eval9.10、事故データの年数範囲の違い等が
      要因の可能性、CNN学習の障害にはならない)

### フェーズ2移植チェックリスト(2026-07-25、v4プロトコル一式の棚卸し)

`../traffic_accident/ml_risk_model/PREREGISTRATION_COUNT_REGRESSION.md`の
「進行順序」に基づく最小の実行系列: フロア/OSM Poisson(GBDT)→過分散・log1p
頑健性チェック→CNN Poissonヘッド3seed再学習→判定(残差Spearman比較)→
(任意)23区視界特徴サブセット評価。

**必須(v3判定プロトコルの中核)** — 2026-07-25、全てコード移植・構文チェック済み
(train全量データ待ちのため実行はまだ):
- [x] `augment_dataset.py` — オフラインデータ拡張(回転×反転+明暗ジッター)。
  `source_cell_id`で同一生画像由来の拡張画像をtrain/val同じ側に固定する設計は
  維持(でないとリークする)。styleごとのmanifestファイル名に対応
- [x] `train.py`(旧`train_v3_poisson.py`相当) — CNN Poissonヘッド学習
  (MobileNetV2、log曝露量=`log(vehicle_length_m+1)`をoffsetとして加算)。
  3seed(42, 1, 2)・epoch15固定チェックポイントの規律を維持。**未実行**
  (`uv add torch torchvision`が必要、train全量データ取得後に着手)
- [x] `evaluate_floor_osm.py`(旧`evaluate_count_regression_v2.py`相当) —
  フロア/OSM Poisson(GBDT、駅距離・エッジ密度・建造物率+log曝露量)の
  残差Spearman評価。**主指標**(旧v1の層内Spearmanは移植していない、
  改訂履歴参照)。scikit-learnをpyproject.tomlに追加済み
- [x] `evaluate_cnn.py`(旧`evaluate_cnn_count_regression.py`相当) — CNNの
  残差Spearman評価(フロアはtrain側で学習したものをevalに適用するのみ、
  eval再学習はリークになるため禁止)。シフト頑健性の副指標追加はCNN学習後に
  実データで検討する設計(未実装、train.py docstring参照)
- [x] `check_final_overdispersion.py` — 条件付き過分散・log1p頑健性の最終確認
  (NB/ZIP切り替えの要否判断)

**判断基準は事前登録済み(結果を見る前に固定、変更しない)**:
CNN/OSMがフロアを上回るか = 3seed平均残差Spearmanの差がseed間標準偏差の2倍を
超えること。閾値そのものの後出し変更はしない(v1/v2から一貫した規律)。

**検討要(過去の個別インシデント対応、GSI版で同種の疑問が再発したら参照)**:
- `check_ensemble_scale_sanity.py` — 特定の予測値が過大に見えた際の桁確認。
  GSI版でも同様の疑義が出たら流用
- `diagnose_stacking_artifact.py` — CNN+視界stackingの劣化原因切り分け。
  視界特徴を使う段階(23区サブセット)で同じ劣化が出たら参照
- `bootstrap_6yr_vs_4yr.py` / `evaluate_6yr_floor_osm.py` — 学習データ期間
  (4年 vs 6年)の選択は旧リポジトリで決着済みの過去の意思決定。GSI版で
  同じ論点を再検証する必要があるかは要判断(データ期間自体はGSI移行と無関係)
- `cross_evaluate.py` — v1/v2(二値分類・負例サンプリング方式)固有の交差評価。
  v3は選抜サンプリングを行わないため、この診断はそのままでは不要
- `extract_cnn_features.py` / `gradcam.py` — CNN特徴のconcat実験・Grad-CAM
  可視化。判定プロトコルの主要経路ではないが、視界+OSM+CNN concat条件を
  試す場合や可視化が要る場面で使う

**23区×PLATEAUサブセット、視界特徴比較 — GSI版パイプライン単体で再検証が必須
(2026-07-25、方針転換。「後回し」ではなく「やり直す」に変更)**:

当初は旧OSM版での結論(視界特徴に精度面の追加価値なし、閾値0.086未達)を
根拠に優先度を下げていたが、これは誤りだった。理由: (1) 提出物では旧OSM版に
一切触れない方針のため、旧OSM版の結論を根拠にすることはその方針と矛盾する
(触れないはずのものを暗黙の前提として使うことになる)。(2) std/pale比較で
判明した通り、タイルソースが変わるとCNNの拾う画像情報の性質(条件付き分散
4.13→2.31、seed安定性0.022→0.005)は無視できないほど変わる。「CNNの性質は
タイルソースに対して不変」という前提自体がこのセッションの実測で崩れている
ため、視界特徴の価値判定も旧OSM版の結論を流用できない。GSI版(pale採用)
パイプライン単体で、フロア・視界単独・視界+OSM・CNN+視界stackingの
4構成を再計算し、事前登録(閾値をGSI版CNNのseed stdから算出し直す)・
bootstrap確認まで、自己完結した形でやり直す必要がある。

再検証の枠組み自体(23区×PLATEAUカバレッジ完全セルのサブセット、
CNN+視界のstacking設計、事前登録・bootstrap確認という手続き)は旧repoの
設計をそのまま踏襲してよい(手法・コードは非OSM・非OSM版依存)。数値だけを
GSI版で置き換える。

- `evaluate_subset_23ku.py` — 23区サブセットでフロア/OSM/CNNを再計算
- `evaluate_sightline_23ku.py` — 視界単独・視界+OSM・CNN+視界stacking・concatの4構成評価
- `evaluate_sightline_linear_stacking.py` — stackingを線形Poissonコンバイナで再検証
  (GBDTの量子化アーティファクト対策、diagnose_stacking_artifact.pyの結論を踏まえた版)
- CNN非依存の部分(23区×PLATEAUカバレッジ完全セルの抽出、視界特徴の実値計算)は
  pale版CNN学習の完了を待たずに並行着手できる

**モデル重みの扱い**: 旧`.pt`チェックポイントは一切引き継がない
(README.md/.gitignore既定方針)。GSI版は必ずゼロから再学習する。

## 現在のディレクトリ構成

```
tsugaku-navi/
├── .gitignore                          # deny-by-default設計(dataset/eval_frozenバグ修正済み)
├── README.md                           # データ出典・帰属表示・OSMデータ公開ルール(2.4)
├── HANDOFF.md                          # このファイル
├── pyproject.toml / uv.lock            # 依存: osmium, pandas, pyarrow, scipy, shapely等
├── accident_data/
│   ├── extract_tokyo_pedestrian.py     # 警察庁オープンデータ処理、OSM非依存
│   ├── convert_to_geojson.py
│   └── tokyo_pedestrian_accidents.csv  # 旧リポジトリから複製(OSM非依存データ)
├── plateau/                             # コア視界計算モジュール(OSM非依存)
└── ml_risk_model/
    ├── tiles.py                        # 地理院タイル(GSI std/pale両対応)
    ├── tokyo_boundary.py               # 国土数値情報N03による都境界判定
    ├── station_points.py / prepare_station_data.py  # 国土数値情報N02由来の駅データ
    ├── spatial_block_split.py          # train/val空間ブロック分割
    ├── build_dataset.py / build_train_set.py / build_eval_set.py  # データセット生成
    ├── augment_dataset.py              # オフラインデータ拡張(フェーズ2、移植済み未実行)
    ├── train.py                        # CNN Poissonヘッド学習(フェーズ2、移植済み未実行、torch未導入)
    ├── evaluate_floor_osm.py / evaluate_cnn.py / check_final_overdispersion.py
    │                                    # v3判定プロトコルの評価スクリプト(フェーズ2、移植済み未実行)
    ├── edge_density.py
    ├── cell_enumeration.py
    ├── extract_osm_raw_cache.py        # OSM生キャッシュ抽出(常にgitignore対象の出力)
    ├── extract_osm_features.py         # OSM集計特徴量抽出(コミット可能な出力)
    ├── osm_feature_lookup.py           # OSMFeatureLookup(集計+実行時生キャッシュ参照)
    ├── road_index.py                   # 車道空間インデックス(ソースは座標非依存)
    ├── boundary_data/                  # N03(行政界)・N02(駅、生成済み)、コミット対象
    ├── osm_features/                   # OSM集計JSON、コミット対象
    ├── osm_data/                       # OSM生データ・生キャッシュ、常にgitignore対象
    ├── dataset/ / eval_frozen/         # 学習・評価用タイル画像、常にgitignore対象
    └── tile_cache/                     # タイル生キャッシュ、常にgitignore対象
```

## フェーズ2(CNN学習・判定)結果(2026-07-25)

`uv add torch torchvision`でtorch 2.13.0+cu130を導入(GPU: Quadro T1000、
CUDA 13.0)。1epoch smoke testで動作確認後、`train.py --style std`を
`--model-suffix`を変えて3回実行(セル42/1/2ラベル、各15epoch、GPU使用、
1回あたり実測約17分)。

**注意点(既知の制約、今回新たに直していない)**: `--seed`引数はtrain/val
分割にのみ使われ、モデル重み初期化はtorch未シード(旧リポジトリの
train_v3_poisson.pyも同じ設計)。「3seed(42,1,2)」は3回の独立した学習run
というラベルであり、モデル初期化の再現可能な乱数シードではない。

### 判定結果

`evaluate_cnn.py --style std --model-glob "models/risk_model_500m_std_poisson_seed*_epoch15.pt"`:

| モデル | 残差Spearman(全域) |
|---|---|
| フロア自身 | 0.000(健全性チェック) |
| OSM | 0.201 |
| CNN(GSI std、3run平均±std) | **0.484 ± 0.010** |
| (参考)旧OSM版CNN(3seed平均±std) | 0.376 ± 0.033 |

**判定基準(事前登録済み)に照らすと**: CNN-OSM差(0.283)はCNN seed間標準偏差
(0.010)の2倍(0.020)を大きく超えており、「CNNがフロア・OSMを明確に上回る」
と判定できる。さらに、地理院タイル(std)版CNNは旧OSM版CNNの実測値(0.376)を
**上回り**、seed間のばらつきも小さい(0.010 vs 0.033、より安定)。フェーズ0.1の
目視評価(std採用の判断根拠: 建物密度・道路階層の視覚的情報量)と整合する結果。

`check_final_overdispersion.py --style std --cnn-model models/risk_model_500m_std_poisson_seed42_epoch15.pt`:
単純Spearman(mu, y)はフロア0.709 < OSM0.736 < CNN0.748で、残差Spearmanと
同じ序列。**ただしCNNの条件付きPearson分散が異常に大きい(310.61、フロア/OSMは
約4.0)** — 一部セルで予測値muが極端に小さくなっている可能性がある(muが0に
近いとPearson残差(y-mu)/√muが発散する)。順位ベースの主指標(残差Spearman)は
この種のスケール較正の歪みに頑健なため判定は覆らないが、**推論時の実際の
予測件数の較正(offsetの扱い、極端な低予測セルの有無)は今後要確認**。
risk_model.py相当の推論コード移植時に必ず点検すること。

- [x] **CNN予測値の較正異常(条件付き分散310.61)の原因調査、完了**: eval 896セル
      中2セルだけで異常寄与の98.4%を占めていた(`500m_25096_7955`が84.7%、
      `500m_25111_7953`が13.7%)。両方とも`vehicle_length_m=0.0`(OSM上で車道が
      検出されないセル、曝露量オフセット=log(1)=0)で予測がほぼ0
      (4e-6・1e-4)になる一方、実測は1件・2件と稀な事故があった。Pearson残差
      `(y-mu)/√mu`はmu→0でy>0だと発散する数学的な性質のための現象であり、
      パイプラインのバグではない(y=0のセルでmu→0なら残差自体も0に収束し発散
      しない。発散するのはmuがほぼ0なのにyが非ゼロという稀な組み合わせのみ)。
      順位ベースの主指標(残差Spearman)はこの種のスケール歪みに頑健なため
      判定への影響はない。参考情報として記録: 車道長ゼロのセルに事故が
      記録されるのは、事故地点がセル境界付近で隣接セルの道路に近い、または
      OSM上「車道」に分類されないごく細い道路上の事故、等が考えられる
      (要因の確定はしていない、優先度は低い)

- [x] **risk_model.py相当の推論エントリポイント移植、完了**: `score_point`・
      `score_route`・`get_point_facts`・`get_route_crossings`・
      `get_narrow_road_segments`を移植。渋谷駅付近で実地スモークテスト済み
      (`score_point`予測61.07件、`categorize`結果「危険」。同セルの実測事故数
      66件[複数年累計]と近い妥当な水準。`route_crossings`5件検出、
      marked_crossing/signal判定・narrow_road_segments検出も正常動作)。
      `CATEGORY_THRESHOLDS`は旧リポジトリの値を使い回さず、
      `risk_model.py --recompute-thresholds`でGSI版(std)train全域への
      3runアンサンブル予測から実際に算出し直した(p20/p50/p80 =
      0.125/2.568/5.860、旧v3版0.28/2.04/4.19・v4版0.44/3.78/7.57とは異なる)。
      推論最適化(torch.jit.trace等)は旧リポジトリで行っていたが、まずは
      正しさ優先でeagerモードのまま。速度が問題になったら追加すること。
      **注意**: モデル読み込み時のパス(`_load_models`)はGRID_M/TILE_STYLE/
      MODEL_SUFFIX/SEEDSの組み合わせから機械的に組み立てているので、
      再学習して別名で保存した場合はこれらの定数を合わせて更新すること
- [x] 事故CSVの実際の年数範囲を確認: 2018〜2024年(7年分)。旧リポジトリの
      「4年(2021-2024)」「6年(2019-2024)」いずれとも異なる、より広い範囲
      (旧リポジトリのtokyo_pedestrian_accidents.csvをそのまま複製したため)。
      評価は全てこの同一データで一貫しているため比較上の問題はないが、
      正確な年数範囲としてこの事実を記録しておく
      - **訂正(2026-08-01)**: 「7年分」は不正確だった。年別件数を確認したところ
        2018年は123件のみ(うち76件が12月、残りも数件ずつ点在する紛れ込みに
        近い状態)で、2019〜2024年の各年は4,300〜5,200件台。実質的な収録期間は
        **2019年1月〜2024年12月の6年分**とするのが正確(件数29,284件自体は
        正しい)。学習・評価は全期間を同一に使っているためモデルの精度検証
        結果に影響はないが、企画書等で「7年分」と表記しないよう注意
        (`HACKATHON_PROPOSAL.md`は修正済み)

### 完了(続き、2026-07-25・訂正〜pale採用〜フェーズ3反映)

このセクションの上に記載した「GSI版std CNN 0.484が旧OSM版0.376を上回る」は
物差しのズレによる誤りだった訂正の全経緯・以下の作業は`STUDY_LOG.md`に
時系列で記録されている(このHANDOFFでは要点のみ):

- [x] 一致セット(旧OSM版の凍結manifestからcell_id・accident_countのみ借用、
      画像・OSM特徴量は全て自前パイプラインで再計算)でGSI版stdを再評価 →
      旧OSM版に統計的に確定的に劣ると判明(bootstrap CI [-0.156,-0.048])
- [x] 判定基準を「OSM版と同等以上」から「std/pale直接比較+単体実用適格性」
      の自己完結型に切り替え(`PLAN_GSI_MIGRATION.md`も同日付で書き直し、
      旧repo側、未コミット)
- [x] std/pale一致セット比較 → bootstrap境界線上(CI [-0.025,0.062])だが
      副次指標(seed安定性0.022→0.005、条件付き分散4.13→2.31)で一貫して
      pale優位 → **pale版を採用**
- [x] 目視評価(std優先)と実際の学習結果(pale優位)が逆だった教訓を記録
      (「目視評価が無意味」ではなく「人間に見やすい画像=CNNが学習しやすい
      画像とは限らない」という一般的洞察として)
- [x] pale版**本番用データセット**(このリポジトリ本来のspatial_block_split、
      train 3,803セル・eval 896セル。一致セットの3,569+919セルは検証専用
      として使い分け、本番には転用しない)を取得・3run学習
      (`risk_model_500m_pale_poisson_seed{42,1,2}_epoch15.pt`)
- [x] 全域評価: フロア0.000・OSM0.211・**CNN 0.439±0.003**(一致セット検証時
      の0.360±0.005よりさらに安定、全量データの効果)
- [x] 23区視界特徴評価をGSI版パイプライン単体でやり直し(旧OSM版の結論を
      前提にしないため): 視界単独-0.040、視界+OSM 0.264、CNN+視界stacking
      0.269±0.031(**CNN単体0.348±0.030から-0.079、事前登録閾値0.061を
      超えて確定的に劣化**)、concat 0.319±0.020(閾値内、区別できず)。
      **結論: 視界特徴に精度面の追加価値なし**(GSI版単体で独立に再確認)。
      視界特徴はrisk_model.pyの説明生成用データとしてのみ活用する方針を維持
- [x] カテゴリ境界(20/50/80パーセンタイル)をpale本番モデルの予測分布で
      再計算: `[0.177, 3.484, 7.355]`(std版の値`[0.125, 2.568, 5.860]`は
      流用していない)
- [x] `risk_model.py`をpale本番3runに差し替え(`TILE_STYLE = "pale"`を
      明示指定、`tiles.DEFAULT_TILE_STYLE`とは意図的に異なる値)
- [x] 動作確認3ケース(23区内=渋谷駅付近・多摩=立川駅付近・境界またぎ=
      東京湾岸)合格。23区内セルは`has_sightline=True`で視界実値も正しく
      取得、`score_route`のroute_crossings/narrow_road_segmentsも動作確認済み
      - **修正したバグ**: `risk_model.py`の`_load_sightline_lookup`が
        `compute_sightline_features.py`の出力先変更(`plateau_data/`→
        `plateau_features/`)に追従しておらず、23区内セルでも
        `has_sightline=False`になっていた。パスを修正

### 完了(続き、技術検証の総仕上げ、2026-07-25)

- [x] **全域0.439は山間部・低インフラセルで水増しされていたと訂正**:
      vehicle_length_m(車道延長)で段階的にフィルタすると0.439→0.344まで
      単調に低下し、独立な方法(23区×PLATEAUカバレッジ)の0.348±0.030と
      ほぼ収束(交差検証的な確認)。std/pale選定判断・本番モデルの学習自体
      には影響なし。**この0.344自体もさらに下方修正される(後述)**
- [x] **CNN+視界stackingの劣化(-0.079)はGBDT量子化アーティファクトと確定**:
      線形Poissonコンバイナで再検証したところ-0.001(ほぼゼロ)に消えた。
      「視界特徴に追加価値なし」の結論自体は変わらないが、「劣化もしない」
      が正確な言い方
- [x] **CNN予測値の条件付き分散異常(1049.65)を確定診断**: std版と完全に
      同じ2セル(`500m_25096_7955`・`500m_25111_7953`、いずれも
      `vehicle_length_m=0.0`)が寄与率99.7%を占める既知の数学的アーティファクト
      (Pearson残差`(y-mu)/√mu`がmu→0で発散)と確定。異常セルを除外しても
      残差Spearmanはほぼ不変(+0.003)、順位ベース主指標への影響なしを数値で
      確認
- [x] **`built_env_fraction`(フロアの入力特徴量)のバグを発見・修正**:
      山間部の白背景を「建造物」に誤分類しており、都市部と山間部を
      ほぼ区別できていなかった(vehicle_length_mとのSpearman相関0.198)。
      白背景を「自然」に含めるよう修正し相関0.842に改善。**修正版フロアで
      再計算した都市部限定のCNN残差Spearmanは0.344→0.28に低下**
      (noise幅±0.017を超える実質的な変化)。「GBDTは符号を気にしないので
      実害は限定的」という予測を検証せず記録だけで済ませなかった結果、
      実際に見出し数値を訂正する必要があると判明した。**企画書・Q&Aで
      使う最終的な見出し数値は0.28程度**(0.439でも0.344でもない)。
      CNNがフロア・OSMを上回るという定性的結論は維持(0.28 vs OSM0.172、
      差+0.109は閾値0.034を大きく超える)。本番モデル(risk_model.py)は
      built_env_fractionを使わないため再学習は不要。
      **未検証で残る点**: std/pale比較のbootstrap(CI [-0.025,0.062])は
      修正前のbuilt_env_fractionで行っており、修正後フロアでの再確認は
      していない(std/pale間のbuilt_env_fraction相関が0.9999だったため
      対称的な影響と推測されるが、実証はしていない)
- [x] **PLATEAU視界特徴の計算自体を検証**: vehicle_length_m(相関-0.526)・
      交差点密度(相関-0.554)と理にかなった相関を示しており、
      built_env_fractionのような計算バグは無いと確認。23区評価
      (視界単独・視界+OSM・stacking)は全てv2フロアで再計算し直し、
      CNN単体0.313±0.034・CNN+視界(線形)0.311±0.028(上乗せ-0.002)を
      確定。「視界特徴に追加価値なし」の結論はv2フロアでも完全に維持
- [ ] 技術検証を打ち止めとするかはユーザー確認待ち(2026-07-26時点)。
      詳細な検証過程・数値は全て`STUDY_LOG.md`に記録済み

### デプロイ移行(2026-07-26、着手)

**背景・重要な発見**: 現行本番バックエンド(`../tsugaku-navi-backend-space`、
HuggingFace Spaces)は実は**旧OSM版モデルのまま**で、かつOSMライセンス対応の
ため生ジオメトリキャッシュ(`osm_data/osm_raw_cache_500m.pkl`・
`vehicle_roads_tokyo.parquet`)を同梱できず、`get_point_facts`の一部・
`route_crossings`・`route_narrow_road_segments`が**動作していなかった**
(`prepare_space.sh`のコメントに明記)。デプロイ移行の目的は単なるホスティング
先変更ではなく、GSI版pale本番モデルへの差し替えとこの機能欠落の解消を兼ねる。

移行先はCloudflare Containers(Code for Japan「オープンデータハッカソン2026」の
Cloudflare特典、Workers Paid相当を2026年9月末まで無償提供、要事前申請)。
HuggingFace SpacesのDocker SDKはPRO以上の有料プラン($9/月〜)必須なのに対し、
Workers Paidは$5/月〜(特典適用中は無償)でコスト削減にもなる。

**発見した設計上のポイント**: `wrangler deploy`はDockerイメージをローカルで
ビルド・プッシュするだけでgit commitを経由しない。そのためHF Spaces(gitpush
必須、ライセンス上コミットできない生OSMキャッシュを同梱できなかった)とは異なり、
`ml_risk_model/osm_data/`(常にgitignore対象)の内容もDockerfileでCOPYして
構わない。「git管理下に置かない」と「Dockerイメージに含める」は別の制約。

**完了(コード・設定一式、`deploy/cloudflare/`)**:
- [x] `prepare_container.sh` — GSI版pale本番3run・OSM集計/生キャッシュ・
      視界特徴CSV・backend/(lambda_handler.py等、tsugaku-navi-backend-spaceの
      現行版を流用、タイル取得元と無関係なため変更なし)を組み立て、
      `../tsugaku-navi-cloudflare`に出力する。実行・動作確認済み(143MB)
- [x] `Dockerfile` — 旧HF Spaces版から流用、`ml_risk_model/osm_data/`のCOPYを
      追加。ポートは8080(Cloudflare Containersの慣例に合わせた、旧版は7860)
- [x] `server.py`(旧`hf_server.py`をリネーム、ロジック不変)
- [x] `wrangler.jsonc`・`src/index.ts`(Durable Object経由でコンテナに
      ルーティングするWorker、シングルトンパターン`getContainer(env.BACKEND)`)・
      `package.json`・`tsconfig.json`・`src/env.d.ts`(Secretsの型宣言)
- [x] `container.gitignore`(出力先の`.gitignore`になる。`osm_data/`除外を
      継承。ハッカソン特典終了後の必須GitHubバックアップ時にも安全)
- [x] 型チェック(`tsc --noEmit`)・`wrangler deploy --dry-run`(Workerの
      バンドルは成功、Docker CLI不在のためコンテナビルドのみ未検証)で
      設定の妥当性を確認済み
- [x] `risk_model.py`・`accident_data.py`・`lambda_handler.py`の実際の
      importが組み立て後のディレクトリで通ることを確認(パス解決含む)

**ユーザーの残作業(このセッションの開発機にはDocker・ブラウザが無く実行不可)**:
- [ ] ハッカソン特典の申請(Googleフォーム→事務局登録→招待メール→
      チーム切り替え、Cloudflareアカウント作成は済み)
- [ ] Dockerが使える環境で: `cd ../tsugaku-navi-cloudflare && npm install &&
      npx wrangler login && npx wrangler secret put ANTHROPIC_API_KEY &&
      npx wrangler deploy`(詳細は`deploy/cloudflare/README_DEPLOY.md`)
- [x] 本番デプロイ実行(2026-07-26)。Dockerグループ権限・buildxプラグイン
      未導入・`instance_type`未指定(既定`lite`=256MiBがtorch推論に対して
      メモリ不足でクラッシュ)の3点を解決し、
      `https://tsugaku-navi-backend.tokyo-odh-097.workers.dev`で稼働確認。
      `/score`・`/ask`(MODELをclaude-opus-4-8→claude-sonnet-5に変更、
      コスト削減目的)とも動作確認済み。`route_crossings`・
      `narrow_road_segments`・`sightline`(23区)も正しく返っており、
      旧HF Spaces版で欠けていた機能が復旧したことを確認
- [x] フロントエンド(`app.js`)の呼び出し先URLを新エンドポイントに更新。
      S3へのアップロードはAWS CLI認証情報がこの開発機に無いため、
      4ファイル(index.html/styles.css/app.js/accidents.geojson)を
      まとめてConsoleから手動アップロードする方式で対応
- [x] **フロントエンド一式(`frontend/`)をこのリポジトリに統合(2026-07-26)**:
      `traffic_accident`から`index.html`・`styles.css`・`app.js`・
      `accidents.geojson`・`deploy.sh`・`deploy-nocache.sh`・
      `invalidate-cloudfront.sh`・`DEPLOYMENT.md`を移設。移設前にOSM関連
      キーワード監査(`tile|fetch_tile|osmium|.pbf|overpass|stations_cache`)を
      実施し、`app.js`がヒットしたが中身はLeaflet地図表示用のOSM標準タイル
      (`tile.openstreetmap.org`)への通常のブラウザ経由リクエストであり、
      CNN学習パイプラインが問題視していた「タイルの大量ダウンロード・
      アーカイブ化」とは別物(帰属表示も既にコード内にあり)と確認した上で
      移設。詳細はREADME.md「フロントエンド地図表示」節に記録
- [x] `frontend/`のUI微修正(2026-07-26): 事故マーカーが「じこがおきたばしょ」
      (赤、全域常時表示レイヤー)と「じっさいの事故」(青、AI検索結果レイヤー)の
      2色に分かれていたが、同じ「事故があった場所」を指すだけで色を分ける
      意味が無かった(ユーザー指摘)。`app.js`のAI結果側マーカーを赤に統一し
      ラベルも「じこがおきたばしょ」に統一(`index.html`の凡例・`styles.css`の
      凡例ドット色も合わせて修正)。あわせて実態と合わなくなっていた古い
      コメント(「AI側は個別マーカー描画をやめた」)も削除
- [ ] 特典期間終了(2026-09-30予定)前に`tsugaku-navi-cloudflare`(デプロイ
      バンドル)をGitHubへバックアップ(`.gitignore`で`osm_data/`除外済み、
      要`git status`確認)。あわせてこのリポジトリ自体(`frontend/`統合後)の
      コミットも検討する
- [ ] 動作確認3ケースをデプロイ後のエンドポイントに対して再実施

### 未着手(フェーズ3の残り)

- [ ] 企画書・ピッチ資料の最終化(旧OSM版への言及がないことを確認)
- [ ] PLAN_GSI_MIGRATION.md(旧repo)の編集をコミットするか判断
      (現状このリポジトリの操作からは未コミットのまま)
- [ ] 何か新しいファイルを旧プロジェクトからコピーする際は、**必ず
      `tile|fetch_tile|osmium|.pbf|overpass|stations_cache`を含めて
      grepチェックしてから**にすること(今回の監査での見落としを繰り返さない)
- [ ] サブディレクトリを`.gitignore`する際は、パターン追加後に必ず
      `git check-ignore -v <実際のファイルパス>`で効いているか確認すること
      (今回`dataset/**/*.png`が実際には無効だった教訓)

## 次にやること(2026-07-26時点、優先順)

1. **S3への手動アップロード完了確認**: `frontend/`の4ファイル
   (`index.html`・`styles.css`・`app.js`・`accidents.geojson`、事故マーカー
   色統一の修正済み)をAWS S3コンソールから`niikun.net`バケットの
   `traffic_accident/`に手動アップロード(この開発機にはAWS CLI認証情報が
   無いため)。CloudFrontを使っている場合はキャッシュ無効化(`/traffic_accident/*`)
   も忘れずに。アップロード後、実際に`niikun.net/traffic_accident`を開いて
   ルート検索→Cloudflareバックエンドが呼ばれる・事故マーカーが赤で統一
   されていることを確認する
2. **Cloudflareハッカソン特典の申請継続**: Googleフォーム申請→事務局登録→
   招待メール受信→チーム切り替え(Cloudflareアカウント作成・実際のデプロイは
   完了済みだが、特典適用前の通常課金で動いている可能性があるため、正式適用の
   確認を)
3. **GitHubバックアップ**(特典終了2026-09-30予定より十分前に):
   - `tsugaku-navi-cloudflare`(デプロイバンドル、`.gitignore`で`osm_data/`
     除外済み)
   - `tsugaku-navi`本体(`frontend/`統合後の状態。まだ一度もコミットして
     いない新規ファイルが大量にある想定、`git status`で確認してから)
4. 動作確認3ケース(23区内・多摩・境界またぎ)をデプロイ後の新エンドポイントに
   対して再実施
5. 企画書・ピッチ資料の最終化(旧OSM版・旧HuggingFace版への言及がないことを
   確認)
