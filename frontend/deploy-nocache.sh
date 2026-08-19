#!/bin/bash

# あんしんつうがくナビ - S3デプロイスクリプト（キャッシュなし版）
# 使い方: ./deploy-nocache.sh bucket-name [prefix]
# 例: ./deploy-nocache.sh niikun.net traffic_accident

BUCKET_NAME=$1
PREFIX=$2

if [ -z "$BUCKET_NAME" ]; then
    echo "エラー: バケット名を指定してください"
    echo "使い方: ./deploy-nocache.sh bucket-name [prefix]"
    echo "例: ./deploy-nocache.sh niikun.net traffic_accident"
    exit 1
fi

# プレフィックスが指定されている場合
if [ -n "$PREFIX" ]; then
    DESTINATION="s3://$BUCKET_NAME/$PREFIX"
    WEB_URL="http://$BUCKET_NAME.s3-website-ap-northeast-1.amazonaws.com/$PREFIX/"
else
    DESTINATION="s3://$BUCKET_NAME"
    WEB_URL="http://$BUCKET_NAME.s3-website-ap-northeast-1.amazonaws.com"
fi

echo "📦 S3バケットにファイルをアップロードしています（キャッシュ無効化）..."
echo "バケット名: $BUCKET_NAME"
if [ -n "$PREFIX" ]; then
    echo "プレフィックス: $PREFIX/"
fi
echo ""

# HTMLファイル（キャッシュ完全無効）
echo "⬆️  index.html をアップロード中..."
aws s3 cp index.html $DESTINATION/index.html \
    --cache-control "no-cache, no-store, must-revalidate" \
    --metadata-directive REPLACE

# CSSファイル（短いキャッシュ: 1分）
echo "⬆️  styles.css をアップロード中..."
aws s3 cp styles.css $DESTINATION/styles.css \
    --cache-control "max-age=60, must-revalidate" \
    --metadata-directive REPLACE

# JavaScriptファイル（短いキャッシュ: 1分）
echo "⬆️  app.js をアップロード中..."
aws s3 cp app.js $DESTINATION/app.js \
    --cache-control "max-age=60, must-revalidate" \
    --metadata-directive REPLACE

# GeoJSONデータ（長めのキャッシュ: 1時間、データはあまり変わらないため）
echo "⬆️  accidents.geojson をアップロード中..."
aws s3 cp accidents.geojson $DESTINATION/accidents.geojson \
    --cache-control "max-age=3600, public" \
    --metadata-directive REPLACE

# GeoJSONデータ（学校位置、長めのキャッシュ: 1時間）
echo "⬆️  schools.geojson をアップロード中..."
aws s3 cp schools.geojson $DESTINATION/schools.geojson \
    --cache-control "max-age=3600, public" \
    --metadata-directive REPLACE

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ アップロード完了！"
    echo ""
    echo "アップロード先: $DESTINATION"
    echo ""
    echo "キャッシュ設定:"
    echo "  - index.html: キャッシュなし（常に最新）"
    echo "  - styles.css: 1分間キャッシュ"
    echo "  - app.js: 1分間キャッシュ"
    echo "  - accidents.geojson: 1時間キャッシュ"
    echo ""
    echo "ウェブサイトURL:"
    echo "$WEB_URL"
    echo ""
    echo "💡 ヒント: ブラウザで強制再読み込み（Ctrl+Shift+R / Cmd+Shift+R）すると"
    echo "   すぐに最新版が表示されます"
else
    echo "❌ エラー: アップロードに失敗しました"
    exit 1
fi
