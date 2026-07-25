# 引き継ぎメモ

## 現在地: フェーズ0完了。フェーズ1(データパイプライン本体)実装完了、
## 全学習セル分の地理院タイル一括取得はこれから

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
      User-Agent(`tsugaku-navi-gsi/1.0 (contact: niikun0209@gmail.com; ...)`)
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

### 未着手(フェーズ1の残り)

- [ ] **3.2 全学習セル分の地理院タイル取得**: 今はまだ1ブロック分(数セル)の
      スモークテストのみ。`build_train_set.py --style std`と`--style pale`を
      実際に全trainブロック(train全セル約3,000件超)・`build_eval_set.py`を
      valブロック分に対して実行する必要がある。レート制限0.5秒/枚のため、
      長時間(数時間規模)かかる見込み。std/pale両方を取得する
      (フェーズ0.1で決定済みのstd優先は維持しつつ、実際の比較検証は
      このフェーズで行う方針、2026-07-25追加)
      - 実行後、`osm_feature_lookup.py --style {std,pale}`で
        `osm_features/osm_features_{train,eval}_{style}.csv`を生成すること
- [ ] **3.3 回帰テスト**: 画像サイズ・チャンネル数・前処理I/Oが旧パイプラインと
      一致するか確認(train.py/train_v3_poisson.py相当をまだ移植していないため
      未着手)
- [ ] train.py/train_v3_poisson.py相当の学習スクリプト移植は未着手(フェーズ2)。
      移植時に検討すべき軽量な改善案(2026-07-25、ユーザーからの提案):
      シフト頑健性のためのデータ拡張(学習時に画像を数十m単位でランダムに
      平行移動)を追加し、「シフトに対する予測値の安定性」を評価指標に
      軽く加える。前回断念した経路の細粒度化の根本原因(グリッド整列した
      構図への過学習)への対策として、低コストで試せる

## 現在のディレクトリ構成

```
tsugaku-navi-gsi/
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

## 次にやること(優先順)

1. `build_train_set.py`/`build_eval_set.py`をstd/pale両styleで全セル分実行し、
   `osm_feature_lookup.py`で特徴量CSVを生成する(3.2、いちばん時間のかかる工程)
2. train.py/train_v3_poisson.py相当の学習スクリプトを移植・新規実装する
   (フェーズ2、シフト頑健性データ拡張の検討を含む)
3. 何か新しいファイルを旧プロジェクトからコピーする際は、**必ず
   `tile|fetch_tile|osmium|.pbf|overpass|stations_cache`を含めて
   grepチェックしてから**にすること(今回の監査での見落としを繰り返さない)
4. サブディレクトリを`.gitignore`する際は、パターン追加後に必ず
   `git check-ignore -v <実際のファイルパス>`で効いているか確認すること
   (今回`dataset/**/*.png`が実際には無効だった教訓)
