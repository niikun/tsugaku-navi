# tsugaku-navi

歩行者事故リスクを地図タイル画像+CNNで推定するモデルのリポジトリ。

## データ出典・利用規約

### 都内15区の教育機関一覧(東京都オープンデータカタログサイト)

- 出典: 各区(多くは「自治体標準データセット」形式)、東京都オープンデータ
  カタログサイト経由。対応区・出典URLは
  [opendata/prepare_tokyo_schools.py](opendata/prepare_tokyo_schools.py)の
  `WARDS`辞書を参照(千代田区・中央区・新宿区・台東区・墨田区・江東区・
  品川区・世田谷区・中野区・練馬区・板橋区・北区・荒川区・葛飾区・大田区)
- ライセンス: 各区ともCC BY 4.0 https://creativecommons.org/licenses/by/4.0/deed.ja
- 区立小中学校773校(名称・所在地・緯度経度)を
  [opendata/tokyo_schools.geojson](opendata/tokyo_schools.geojson)として整形。
  フロントエンド(`frontend/schools.geojson`は同一内容)が地図上に常時表示する
  (`frontend/app.js`の`loadSchoolsData`)。デモで使う「西新宿小学校」もこのデータに含まれる
- 区ごとに文字コード(utf-8-sig/cp932/utf-16-le)・列構成(品川区・中野区・北区・
  大田区は独自形式、大田区のみXLSX)が異なるため、
  `opendata/prepare_tokyo_schools.py`で吸収している。千代田区は原データの
  小中学校に緯度経度が欠落していたため、国土地理院ジオコーディングAPIで
  補完した座標を固定値として埋め込み。台東区は番地がExcelで日付表記に
  自動変換されたまま公開されていたため、元表記に戻す補正を行っている
- 杉並区はカタログ掲載のCSV URL・wagmap版とも404(区サイト側の構成変更)だった
  ため今回は未対応。文京区・渋谷区・豊島区・足立区は「学校」を含むデータセットが
  見つからず、江戸川区は緯度経度を持たない通学区域データのみだった。
  新しいURL・データセットが見つかれば追加できる(今後の展望)

### 地理院タイル(地図画像)

- 出典: 国土地理院 地理院タイル。std(標準地図)・pale(淡色地図)の2種別に
  対応し、フェーズ1で両方を学習データ化しCNN精度を比較する
  ([ml_risk_model/tiles.py](ml_risk_model/tiles.py)の`TILE_STYLES`参照)
- 利用規約: https://www.gsi.go.jp/kikakuchousei/kikakuchousei40182.html
- 出典表示: 「国土地理院」または「地理院タイル」+
  https://maps.gsi.go.jp/development/ichiran.html へのリンクを、
  地図画像を表示・配布する箇所(フロントエンド地図表示部・モデルカード等)に
  必ず付す
- レート制限: 0.5秒/枚(地理院タイルに明示的なレート制限の記載はないが、
  常識的な利用として踏襲)
- User-Agent: `tsugaku-navi/1.0 (contact: niikun0209@gmail.com; ...)`
  ([ml_risk_model/tiles.py](ml_risk_model/tiles.py)参照)
- タイル画像は逐次取得のみ行い、事前バルクアーカイブ化は行わない
  (`tile_cache/`・学習用データセット`dataset/`・凍結評価セット`eval_frozen/`は
  再生成可能な成果物として`.gitignore`対象)

### フロントエンド地図表示(OpenStreetMap標準タイル、`frontend/`)

- `frontend/app.js`は、ユーザーが自宅・学校を指定してルート検索する画面の
  地図表示にLeaflet経由でOSM標準タイルサーバー(`tile.openstreetmap.org`)を
  使っている。通常のブラウザ経由の逐次リクエスト・帰属表示ありという、
  OSM Tile Usage Policyが想定する一般的な利用形態にあたる。帰属表示
  (`© OpenStreetMap contributors`)は`app.js`のタイルレイヤー定義内に
  既に含まれている

### 警察庁交通事故統計情報オープンデータ

- 出典: 警察庁交通事故統計情報オープンデータ
  https://www.npa.go.jp/publications/statistics/koutsuu/opendata/index_opendata.html
- [accident_data/extract_tokyo_pedestrian.py](accident_data/extract_tokyo_pedestrian.py)で処理

### 国土数値情報(行政区域・鉄道データ等)

- 出典: 国土数値情報(国土交通省)
  - [ml_risk_model/tokyo_boundary.py](ml_risk_model/tokyo_boundary.py)が使う
    `N03-20240101_13.geojson`(行政区域)
  - [ml_risk_model/station_points.py](ml_risk_model/station_points.py)が使う
    `N02-2022_Station_tokyo.geojson`(鉄道駅、駅からの距離の交絡チェック用)。
    [ml_risk_model/prepare_station_data.py](ml_risk_model/prepare_station_data.py)が
    N02(鉄道、2022年度)から生成する一回限りの準備データ。旧リポジトリの
    Overpass API(OSM本体)依存だった同種の処理を置き換えたもの
    (HANDOFF.md参照)

### PLATEAU(3D都市モデル)

- [plateau/](plateau/)モジュールが使用。OSM/ODbLとは別のライセンス体系
  (G空間情報センター利用規約)のため、本ドキュメントのOSM関連ルールの対象外

### OSMベクターデータ(道路・信号機・横断歩道等の位置情報)

タイル画像とは別に、OSM由来のベクターデータ(Overpass API等で取得した
道路・信号機・横断歩道の位置情報)を扱うファイルにも同じ規律を適用する。
判定基準は「OSMを経由したかどうか」ではなく「出力に個々のOSM要素
(way_id・node_id・座標列・生タグ)が個別アクセス可能な形で残っているか」。

**公開可否の二値ルール**: 以下の**条件1・条件2の両方**を満たさない
ファイルは`.gitignore`で除外する(コミットしない)。

1. **条件1**: 個々のOSM要素は集計統計のみであること
   (例: 「このセル内の信号機の数」はOK。信号機ごとの座標列はNG。
   「最寄りの信号機までの距離」も、多数地点分を面的に持つと三点測量で
   元の座標を再構成できてしまうためNG扱いとする
   ([ml_risk_model/osm_feature_lookup.py](ml_risk_model/osm_feature_lookup.py)の
   `NEAREST_POINT_COLS`参照。`osm_features/`にはこの列を含めず、
   `osm_data/`側にのみフル版を保持する)
2. **条件2**: 帰属表示があること(ファイル自体のヘッダーコメント、または
   READMEの該当箇所に「OpenStreetMapデータを集計。© OpenStreetMap
   contributors, Open Database License」等の一文を付す)

この二条件により、OSM特徴量抽出パイプラインは常に

- **集計専用の出力ファイル**(条件1・2を満たせばコミット可)
- **生ジオメトリの作業用キャッシュ**(常に`.gitignore`対象、
  ファイル名パターンではなくディレクトリ単位のdeny-by-defaultで除外)

の2種類を分けて生成する設計にする。1つのファイルに両方を混在させない。

`.gitignore`の該当ルールは[.gitignore](.gitignore)の
「OSM(またはOverpass API等〜」セクション参照。新しいOSM由来データの
出力先ディレクトリ・キャッシュファイル名を追加する際は、必ずそちらにも
deny-by-defaultのパターンを追加すること。

**実装(フェーズ1)**: 以下の2段階に分けている。

1. [ml_risk_model/extract_osm_raw_cache.py](ml_risk_model/extract_osm_raw_cache.py) —
   pyosmiumでOSM PBFを1回ストリーム処理し、信号機・横断歩道の個別座標や
   車道wayの座標列を含む生キャッシュを`ml_risk_model/osm_data/`(常に
   `.gitignore`対象)に書き出す
2. [ml_risk_model/extract_osm_features.py](ml_risk_model/extract_osm_features.py) —
   生キャッシュを読み、セル単位の集計統計のみを`ml_risk_model/osm_features/`
   (コミット可能、帰属表示付き)にJSON形式で書き出す。pickleではなくJSONに
   しているのは、`.gitignore`が`*.pkl`/`*.parquet`を「OSM由来の中間生成物」と
   みなして一律除外する多層防御ルールを持っており、コミット対象はdiffで
   中身をレビューできる形式にする方が筋が良いため

[ml_risk_model/osm_feature_lookup.py](ml_risk_model/osm_feature_lookup.py)の
`OSMFeatureLookup`は、セル単位の特徴(車道延長・歩道延長・信号機数等)は
committable な集計JSONから、信号機/横断歩道への最近傍距離だけは実行時に
生キャッシュを読んで計算する(結果のスカラー値はどこにもファイル書き戻し
しない)。[ml_risk_model/road_index.py](ml_risk_model/road_index.py)も同様に、
ソースコード自体は座標を持たず、生キャッシュ由来のparquetを実行時に読む
設計(旧リポジトリで「良い設計の手本」と評価された点を踏襲)。

