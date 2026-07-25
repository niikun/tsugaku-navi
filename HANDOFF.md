# 引き継ぎメモ

## 現在地: フェーズ0(準備)途中。地理院タイル移行の新規リポジトリ立ち上げ中

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

### 未着手(フェーズ0の残り)

- [ ] `2.3`の残り: 移植予定だった`build_dataset.py`(学習データ生成)・
      `road_index.py`相当・OSM特徴量抽出パイプラインは、**フェーズ0.4の
      設計(集計のみ出力+生ジオメトリは常にgitignore)を反映してから**
      新規に書き直すか移植するか判断すること。今のところ何も移植していない

## 現在のディレクトリ構成

```
tsugaku-navi-gsi/
├── .gitignore                          # deny-by-default設計(上記参照)
├── README.md                           # データ出典・帰属表示・OSMデータ公開ルール(2.4)
├── HANDOFF.md                          # このファイル
├── .git/                               # git init済み、コミットはまだ0件
├── .venv/                              # uv venv、pillow/pyproj/shapely導入済み
├── accident_data/
│   ├── extract_tokyo_pedestrian.py     # 警察庁オープンデータ処理、OSM非依存
│   └── convert_to_geojson.py
├── plateau/
│   ├── compute_sightline_features.py
│   └── plateau/                        # コア視界計算モジュール(6ファイル、OSM非依存)
│       ├── __init__.py, index.py, meshcode.py,
│       └── parquet_index.py, parser.py, sightline.py
└── ml_risk_model/
    ├── tiles.py                        # 新規実装、地理院タイル(GSI std)、動作確認済み
    ├── tokyo_boundary.py               # 国土数値情報N03による都境界判定、動作確認済み
    ├── boundary_data/
    │   └── N03-20240101_13.geojson     # 国土数値情報(政府オープンデータ、OSM非依存)
    └── cell_enumeration.py             # 未検証(監査ではOK判定、実行テストはまだ)
```

**初回コミット済み**(`ad9d846`)。フェーズ0は完了。

## 次にやること(優先順)

1. フェーズ1(`build_dataset.py`等の学習パイプライン本体の新規実装、
   全学習セル分の地理院タイル再取得)に着手。ここが一番時間のかかる工程
   (フェーズ0.4の設計 — 集計のみ出力+生ジオメトリは常にgitignore —
   を反映すること)
2. 何か新しいファイルを旧プロジェクトからコピーする際は、**必ず
   `tile|fetch_tile|osmium|.pbf|overpass|stations_cache`を含めて
   grepチェックしてから**にすること(今回の監査での見落としを繰り返さない)
