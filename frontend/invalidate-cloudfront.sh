#!/bin/bash

# CloudFront キャッシュ無効化スクリプト
# 使い方: ./invalidate-cloudfront.sh DISTRIBUTION_ID [path]
# 例: ./invalidate-cloudfront.sh E1234567890ABC /traffic_accident/*

DISTRIBUTION_ID=$1
PATH_PATTERN=${2:-"/*"}

if [ -z "$DISTRIBUTION_ID" ]; then
    echo "エラー: CloudFront Distribution IDを指定してください"
    echo "使い方: ./invalidate-cloudfront.sh DISTRIBUTION_ID [path]"
    echo "例: ./invalidate-cloudfront.sh E1234567890ABC /traffic_accident/*"
    echo ""
    echo "Distribution IDの確認方法:"
    echo "  aws cloudfront list-distributions --query 'DistributionList.Items[*].[Id,DomainName]' --output table"
    exit 1
fi

echo "🔄 CloudFrontキャッシュを無効化しています..."
echo "Distribution ID: $DISTRIBUTION_ID"
echo "パス: $PATH_PATTERN"
echo ""

aws cloudfront create-invalidation \
    --distribution-id $DISTRIBUTION_ID \
    --paths "$PATH_PATTERN"

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ キャッシュ無効化リクエストを送信しました"
    echo "💡 反映まで数分かかる場合があります"
else
    echo "❌ エラー: キャッシュ無効化に失敗しました"
    exit 1
fi
