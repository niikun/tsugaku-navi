# tsugaku-navi-gsi

歩行者事故リスクを地図タイル画像+CNNで推定するモデルの、地理院タイル移行版
リポジトリ。地理院タイルを主な地図画像ソースとして構築した
データ利用ルールを踏まえ
OSM由来の
コード・データ・学習済みモデルを持ち込まず、利用規約に基づいた出典・帰属表示のもとでゼロから構築している。

背景・全体計画は開発機上の別ディレクトリのメモ
を参照(このリポジトリ単体には含まれない)。

## データ出典・利用規約

### 地理院タイル(地図画像)

- 出典: 国土地理院 地理院タイル(標準地図, std)
- 利用規約: https://www.gsi.go.jp/kikakuchousei/kikakuchousei40182.html
- 出典表示: 「国土地理院」または「地理院タイル」+
  https://maps.gsi.go.jp/development/ichiran.html へのリンクを、
  地図画像を表示・配布する箇所(フロントエンド地図表示部・モデルカード等)に
  必ず付す
- レート制限: 0.5秒/枚(地理院タイルに明示的なレート制限の記載はないが、
  常識的な利用として踏襲)
- User-Agent: `tsugaku-navi-gsi/1.0 (contact: niikun0209@gmail.com; ...)`
  ([ml_risk_model/tiles.py](ml_risk_model/tiles.py)参照)
- タイル画像は逐次取得のみ行い、事前バルクアーカイブ化は行わない
  (`tile_cache/`は再生成可能なキャッシュとして`.gitignore`対象)

### 警察庁交通事故統計情報オープンデータ

- 出典: 警察庁交通事故統計情報オープンデータ
  https://www.npa.go.jp/publications/statistics/koutsuu/opendata/index_opendata.html
- [accident_data/extract_tokyo_pedestrian.py](accident_data/extract_tokyo_pedestrian.py)で処理

### 国土数値情報(行政区域データ等)

- 出典: 国土数値情報(国土交通省)
  [ml_risk_model/tokyo_boundary.py](ml_risk_model/tokyo_boundary.py)が使う
  `N03-20240101_13.geojson`(行政区域)等

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

1. **条件1**: 個々のOSM要素を一切含まない、集計統計のみであること
   (例: 「このセル内の信号機の数」はOK。信号機ごとの座標列はNG)
2. **条件2**: 帰属表示があること(ファイル自体のヘッダーコメント、または
   READMEの該当箇所に「OpenStreetMapデータを集計。© OpenStreetMap
   contributors, Open Database License」等の一文を付す)

この二条件により、OSM特徴量抽出パイプラインは常に

- **集計専用の出力ファイル**(条件1・2を満たせばコミット可)
- **生ジオメトリの作業用キャッシュ**(常に`.gitignore`対象、
  ファイル名パターンではなくディレクトリ単位のdeny-by-defaultで除外)

の2種類を分けて生成する設計にする。1つのファイルに両方を混在させない
(旧リポジトリの`cell_features_500m.pkl`が「集計っぽい名前だが実は生
ジオメトリ混在」だった反省による)。

`.gitignore`の該当ルールは[.gitignore](.gitignore)の
「OSM(またはOverpass API等〜」セクション参照。新しいOSM由来データの
出力先ディレクトリ・キャッシュファイル名を追加する際は、必ずそちらにも
deny-by-defaultのパターンを追加すること。

## 開発時の注意

他プロジェクト(特に`../traffic_accident/`)からファイルをコピー・移植する
際は、必ず以下のキーワードでgrepしてOSM依存が紛れ込んでいないか確認してから
コピーすること(自動チェックではなく人力または別エージェントによる再確認を
推奨):

```
tile|fetch_tile|osmium|.pbf|overpass|stations_cache
```

過去に`tile|fetch_tile|osmium|.pbf`のみのチェックで見落とし、
`spatial_block_split.py`がOverpass API経由で駅の個別座標を生キャッシュ
していた事例がある(詳細は[HANDOFF.md](HANDOFF.md)参照)。
