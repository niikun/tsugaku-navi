# データ出典・ライセンス

## 都内15区教育機関一覧(CC BY 4.0)

- 出典: 各区(多くは自治体標準データセット形式)、東京都オープンデータカタログ
  サイト経由。千代田区・中央区・新宿区・台東区・墨田区・江東区・品川区・
  世田谷区・中野区・練馬区・板橋区・北区・荒川区・葛飾区・大田区
- ライセンス: 各区ともCC BY 4.0 (https://creativecommons.org/licenses/by/4.0/deed.ja)
- 区立小中学校773校を地図上に常時表示

## 使用したオープンデータ(公共データ利用規約 PDL1.0/CC BY 4.0相当)

- 警察庁 交通事故統計情報オープンデータ
  出典: 警察庁ウェブサイト(https://www.npa.go.jp/publications/statistics/koutsuu/opendata/index_opendata.html)
- 国土地理院 地理院タイル(std/pale)
  出典: 国土地理院ウェブサイト(https://maps.gsi.go.jp/development/ichiran.html)
- 国土数値情報(行政区域N03・鉄道駅N02、国土交通省)
  出典: 国土交通省国土数値情報ダウンロードサイト(https://nlftp.mlit.go.jp/ksj/)
- PLATEAU(3D都市モデル、国土交通省)
  出典: 国土交通省 PLATEAUウェブサイト(https://www.mlit.go.jp/plateau/)

上記4点はいずれも「公共データ利用規約(第1.0版)」に基づき提供されており、CC BY 4.0と互換性がある。
本サービスでは各データを集計・加工したうえでAIモデルの学習および説明生成に利用しており、
政府機関の作成物であるかのような表示は行っていない。

## OpenStreetMapデータ

- フロントエンド地図表示(Leaflet経由の標準タイル)に利用
- OSM集計データ(信号機・横断歩道までの距離、道路種別など)を地点ごとに集計し、
  Claudeの説明根拠として利用
- © OpenStreetMap contributors, Open Database License (ODbL)
  (https://www.openstreetmap.org/copyright)

## 使用ソフトウェア・インフラ

- Leaflet.js / leaflet.markercluster / leaflet-routing-machine / leaflet.heat(OSSライブラリ)
- MobileNetV2(torchvision、ImageNet事前学習重み)をベースに独自データで転移学習
- Claude API(Anthropic)を対話的な説明生成に利用
- Cloudflare Workers + Containers(本ハッカソンのCloudflare特典を活用)

## プライバシーへの配慮

- 自宅・学校の位置情報はその場で処理するのみでサーバーに保存しない設計
