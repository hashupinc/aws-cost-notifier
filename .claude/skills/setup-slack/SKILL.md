---
name: setup-slack
description: aws-cost-notifier の Slack 通知をウィザード形式でセットアップする
---

# Slack 通知セットアップ

aws-cost-notifier の Slack 通知をウィザード形式で対話的にセットアップします。

## 使用方法
```
/setup-slack
```

## 実行フロー

### Step 1: Webhook URL の確認
ユーザーに Slack Webhook URL を持っているか確認する。

**持っていない場合**、以下の手順を案内する:
1. https://api.slack.com/apps にアクセス
2. 「Create New App」→「From scratch」を選択
3. App 名（例: `AWS Cost Notifier`）とワークスペースを選択して作成
4. 左メニュー「Incoming Webhooks」→ トグルを ON
5. 「Add New Webhook to Workspace」→ 通知先チャンネルを選択して「Allow」
6. 生成された Webhook URL（`https://hooks.slack.com/services/...`）をコピー

案内後、ユーザーに Webhook URL の入力を求める。

### Step 2: Webhook URL の疎通確認
入力された URL にテストメッセージを送信して疎通を確認する:

```bash
curl -s -o /dev/null -w "%{http_code}" -X POST -H 'Content-Type: application/json' \
  -d '{"text":"[テスト] aws-cost-notifier Slack 通知セットアップ確認"}' \
  "${WEBHOOK_URL}"
```

- 200 が返れば成功。Slack チャンネルにメッセージが届いたか確認を促す
- 失敗した場合は URL の再入力を求める

### Step 3: デプロイ情報の確認
以下を確認する:
- **AWS プロファイル名**: `AWS_PROFILE` に使う値
- **スタック名**: 既存スタックがあるか `aws cloudformation describe-stacks` で確認
- **リージョン**: デフォルト `ap-northeast-1`

既存スタックがある場合は現在のパラメータを取得して引き継ぐ。

### Step 4: CloudFormation デプロイ
既存パラメータを維持しつつ `SlackWebhookUrl` を追加してデプロイ:

```bash
AWS_PROFILE=${PROFILE} aws cloudformation deploy \
  --template-file template.yaml \
  --stack-name ${STACK_NAME} \
  --region ${REGION} \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    SlackWebhookUrl=${WEBHOOK_URL} \
    ...既存パラメータ...
```

### Step 5: 実通知テスト
Lambda を手動実行して Slack にコスト通知が届くか確認:

```bash
AWS_PROFILE=${PROFILE} aws lambda invoke \
  --function-name ${STACK_NAME}-nab-function \
  --region ${REGION} \
  /dev/stdout
```

Slack チャンネルに通知が届いたか確認を促す。

### Step 6: 完了メッセージ
セットアップ完了を報告し、以下を伝える:
- 通知は EventBridge Scheduler により定期実行される
- Webhook URL は Secrets Manager に安全に保管されている
- 設定変更は CloudFormation パラメータの更新で可能

## 技術的な注意事項
- Webhook URL は CloudFormation パラメータ `SlackWebhookUrl` として渡す（NoEcho で保護）
- CFn 内部で Secrets Manager に保存され、Lambda は Extension 経由で取得する
- 既存スタックの更新時は、他のパラメータ（EmailAddress, ShowCreditDetails 等）を `--parameter-overrides` で明示的に引き継ぐか、`UsePreviousValue` を使う
