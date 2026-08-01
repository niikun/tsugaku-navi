#!/bin/bash

# あんしんつうがくナビ - S3デプロイスクリプト
# 使い方: ./deploy.sh bucket-name [prefix]
# 例: ./deploy.sh niikun.net traffic_accident

BUCKET_NAME=$1
PREFIX=$2

if [ -z "$BUCKET_NAME" ]; then
    echo "エラー: バケット名を指定してください"
    echo "使い方: ./deploy.sh bucket-name [prefix]"
    echo "例: ./deploy.sh niikun.net traffic_accident"
    exit 1
fi

# プレフィックスが指定されている場合
if [ -n "$PREFIX" ]; then
    DESTINATION="s3://$BUCKET_NAME/$PREFIX/"
    WEB_URL="http://$BUCKET_NAME.s3-website-ap-northeast-1.amazonaws.com/$PREFIX/"
else
    DESTINATION="s3://$BUCKET_NAME/"
    WEB_URL="http://$BUCKET_NAME.s3-website-ap-northeast-1.amazonaws.com"
fi

echo "📦 S3バケットにファイルをアップロードしています..."
echo "バケット名: $BUCKET_NAME"
if [ -n "$PREFIX" ]; then
    echo "プレフィックス: $PREFIX/"
fi
echo ""

# 必要なファイルのみをアップロード
aws s3 sync . $DESTINATION \
    --exclude "*" \
    --include "index.html" \
    --include "styles.css" \
    --include "app.js" \
    --include "accidents.geojson" \
    --delete

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ アップロード完了！"
    echo ""
    echo "アップロード先: $DESTINATION"
    echo ""
    if [ -z "$PREFIX" ]; then
        echo "次のステップ:"
        echo "1. S3バケットの静的ウェブサイトホスティングを有効化"
        echo "2. バケットポリシーで公開読み取りを許可"
        echo ""
        echo "ウェブサイトURL:"
        echo "$WEB_URL"
    else
        echo "ウェブサイトURL（プレフィックス付き）:"
        echo "$WEB_URL"
        echo ""
        echo "注意: プレフィックス付きの場合、静的ウェブサイトホスティングの"
        echo "インデックスドキュメントは $PREFIX/index.html になります"
    fi
else
    echo "❌ エラー: アップロードに失敗しました"
    exit 1
fi
