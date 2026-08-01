# AWS S3 デプロイガイド

このドキュメントでは、あんしんつうがくナビをAWS S3にデプロイする手順を説明します。

## 📋 目次

1. [前提条件](#前提条件)
2. [方法1: AWS CLIを使う方法](#方法1-aws-cliを使う方法)
3. [方法2: AWS Management Consoleを使う方法](#方法2-aws-management-consoleを使う方法)
4. [静的ウェブサイトホスティングの設定](#静的ウェブサイトホスティングの設定)
5. [バケットポリシーの設定](#バケットポリシーの設定)
6. [CloudFrontの設定（オプション）](#cloudfrontの設定オプション)

## 前提条件

### AWS CLIを使う場合

```bash
# AWS CLIのインストール（まだの場合）
# macOS
brew install awscli

# Linux
sudo apt-get install awscli

# Windows
# https://aws.amazon.com/cli/ からインストーラーをダウンロード

# AWS CLIの設定
aws configure
# AWS Access Key ID: [あなたのアクセスキー]
# AWS Secret Access Key: [あなたのシークレットキー]
# Default region name: ap-northeast-1
# Default output format: json
```

## 方法1: AWS CLIを使う方法

### ステップ1: S3バケットを作成

```bash
# バケット名を決める（世界中で一意である必要があります）
BUCKET_NAME="niikun.net"

# バケットを作成
aws s3 mb s3://$BUCKET_NAME --region ap-northeast-1
```

### ステップ2: ファイルをアップロード

デプロイスクリプトを使用：

```bash
# スクリプトに実行権限を付与
chmod +x deploy.sh

# デプロイを実行
./deploy.sh your-bucket-name
```

または手動でアップロード：

```bash
# 必要なファイルをアップロード
aws s3 cp index.html s3://$BUCKET_NAME/
aws s3 cp styles.css s3://$BUCKET_NAME/
aws s3 cp app.js s3://$BUCKET_NAME/
aws s3 cp accidents.geojson s3://$BUCKET_NAME/

# または一括アップロード
aws s3 sync . s3://$BUCKET_NAME \
    --exclude "*" \
    --include "index.html" \
    --include "styles.css" \
    --include "app.js" \
    --include "accidents.geojson"
```

### ステップ3: 静的ウェブサイトホスティングを有効化

```bash
aws s3 website s3://$BUCKET_NAME \
    --index-document index.html \
    --error-document index.html
```

### ステップ4: バケットポリシーを設定

バケットポリシーファイルを作成：

```bash
cat > bucket-policy.json << 'EOF'
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "PublicReadGetObject",
            "Effect": "Allow",
            "Principal": "*",
            "Action": "s3:GetObject",
            "Resource": "arn:aws:s3:::YOUR_BUCKET_NAME/*"
        }
    ]
}
EOF

# YOUR_BUCKET_NAMEを実際のバケット名に置換
sed -i "s/YOUR_BUCKET_NAME/$BUCKET_NAME/g" bucket-policy.json

# ポリシーを適用
aws s3api put-bucket-policy --bucket $BUCKET_NAME --policy file://bucket-policy.json
```

### ステップ5: パブリックアクセスブロックを無効化

```bash
aws s3api put-public-access-block \
    --bucket $BUCKET_NAME \
    --public-access-block-configuration \
    "BlockPublicAcls=false,IgnorePublicAcls=false,BlockPublicPolicy=false,RestrictPublicBuckets=false"
```

### ステップ6: アクセス確認

```bash
# ウェブサイトURLを表示
echo "ウェブサイトURL: http://$BUCKET_NAME.s3-website-ap-northeast-1.amazonaws.com"
```

## 方法2: AWS Management Consoleを使う方法

### ステップ1: S3バケットを作成

1. [AWS Management Console](https://console.aws.amazon.com/s3/)にログイン
2. 「バケットを作成」をクリック
3. バケット名を入力（例: `anshin-tsugaku-navi-your-name`）
4. リージョンを選択（例: アジアパシフィック（東京）`ap-northeast-1`）
5. 「このバケットのパブリックアクセスをすべてブロック」のチェックを**外す**
6. 「バケットを作成」をクリック

### ステップ2: ファイルをアップロード

1. 作成したバケットをクリック
2. 「アップロード」をクリック
3. 以下のファイルを選択：
   - `index.html`
   - `styles.css`
   - `app.js`
   - `accidents.geojson`
4. 「アップロード」をクリック

### ステップ3: 静的ウェブサイトホスティングを有効化

1. バケットの「プロパティ」タブをクリック
2. 一番下の「静的ウェブサイトホスティング」セクションまでスクロール
3. 「編集」をクリック
4. 「有効にする」を選択
5. インデックスドキュメント: `index.html`
6. エラードキュメント: `index.html`
7. 「変更を保存」をクリック

### ステップ4: バケットポリシーを設定

1. バケットの「アクセス許可」タブをクリック
2. 「バケットポリシー」セクションで「編集」をクリック
3. 以下のJSONを貼り付け（`YOUR_BUCKET_NAME`を実際のバケット名に変更）：

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "PublicReadGetObject",
            "Effect": "Allow",
            "Principal": "*",
            "Action": "s3:GetObject",
            "Resource": "arn:aws:s3:::YOUR_BUCKET_NAME/*"
        }
    ]
}
```

4. 「変更を保存」をクリック

### ステップ5: ウェブサイトにアクセス

1. 「プロパティ」タブに戻る
2. 「静的ウェブサイトホスティング」セクションのURLをクリック
3. アプリが表示されることを確認

ウェブサイトURL形式：
```
http://バケット名.s3-website-ap-northeast-1.amazonaws.com
```

## 更新方法

### ファイルを更新した場合

```bash
# 単一ファイルを更新
aws s3 cp index.html s3://$BUCKET_NAME/ --cache-control max-age=0
aws s3 cp styles.css s3://$BUCKET_NAME/ --cache-control max-age=0
aws s3 cp app.js s3://$BUCKET_NAME/ --cache-control max-age=0

# または一括更新
./deploy.sh your-bucket-name
```

### キャッシュのクリア

ブラウザのキャッシュをクリアするか、Ctrl+Shift+R（強制再読み込み）を実行してください。

## CloudFrontの設定（オプション）

HTTPSやカスタムドメインを使用したい場合は、CloudFrontを使用します。

### ステップ1: CloudFrontディストリビューションを作成

```bash
aws cloudfront create-distribution \
    --origin-domain-name $BUCKET_NAME.s3-website-ap-northeast-1.amazonaws.com \
    --default-root-object index.html
```

### ステップ2: カスタムドメインの設定（オプション）

1. Route 53でドメインを管理
2. ACM（AWS Certificate Manager）でSSL証明書を取得
3. CloudFrontディストリビューションにカスタムドメインと証明書を設定

## コスト見積もり

### S3のみ（月額）

- ストレージ: 約5.2MB → 約0.01円
- リクエスト: 1,000アクセス/月 → 約0.4円
- データ転送: 500MB/月 → 約60円

**合計: 約60円/月**

### CloudFront追加時（月額）

- データ転送: 500MB/月 → 約10円
- リクエスト: 1,000アクセス/月 → 約1円

**合計: 約71円/月**

## トラブルシューティング

### 403 Forbiddenエラー

- バケットポリシーが正しく設定されているか確認
- パブリックアクセスブロックが無効化されているか確認

### ファイルが見つからない

- ファイル名が正しいか確認（大文字小文字も区別されます）
- S3バケット内にファイルが存在するか確認

### CSSやJSが読み込まれない

- Content-Typeが正しく設定されているか確認
- ブラウザの開発者ツールでエラーを確認

## 参考リンク

- [Amazon S3 静的ウェブサイトホスティング](https://docs.aws.amazon.com/ja_jp/AmazonS3/latest/userguide/WebsiteHosting.html)
- [AWS CLI S3コマンドリファレンス](https://docs.aws.amazon.com/cli/latest/reference/s3/)
- [CloudFront ドキュメント](https://docs.aws.amazon.com/ja_jp/cloudfront/)
