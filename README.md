# aws-cost-notifier

AWS のコストを定期的に取得し、Email・Slack・LINE に通知する Lambda アプリケーションです。

## 機能

- AWS Cost Explorer API から日次の請求データを取得
- サービス別・アカウント別のコスト内訳と前日比を通知
- クレジット適用中のアカウントでも実コスト・クレジット消費額を表示可能（`ShowCreditDetails` パラメータ）
- CFn (`template.yaml`) をアップロードすることで AWS 環境にデプロイ可能

## 集計期間

- 実行月の1日から2日前までのコストを取得します。
  - 例（実行日: 2025/03/20）: 2025/03/01 〜 2025/03/18
- 実行日が2日の場合は、前月の1日から前月末日までのコストを取得します。
  - 例（実行日: 2025/04/02）: 2025/03/01 〜 2025/03/31

## 出力メッセージ例

```
AWS Billing Notification (03/01～03/27) : 4.42 USD (+0.40 USD)
Service Billing Details:
- AWS Cost Explorer: 0.37 USD (+0.37 USD)
- AWS Secrets Manager: 1.03 USD (+0.02 USD)
- Amazon EC2 Container Registry (ECR): 0.38 USD (+0.01 USD)
- Amazon Relational Database Service: 1.24 USD (+0.00 USD)
- Amazon Route 53: 1.00 USD (+0.00 USD)
- Amazon Simple Storage Service: 0.01 USD (+0.00 USD)

Account Billing Details:
- my-account (123456789012): 4.42 USD (+0.40 USD)

Tax Billing: 0.40 USD
```

ShowCreditDetails 有効時は以下のセクションが先頭に追加されます:

```
Credit Usage:
- Gross Cost (before credits): 10.37 USD
- Credits Applied: -10.37 USD
  - Amazon SageMaker: 3.72 USD
  - Amazon QuickSight: 6.65 USD
```

## ローカル実行

### 前提条件

- Python 3.9+
- [uv](https://docs.astral.sh/uv/) がインストールされていること
- AWS プロファイルが設定されていること

### 実行手順

1. 依存関係をインストール
    ```
    make install
    ```
2. AWS プロファイルを設定
    ```
    export AWS_PROFILE=${PROFILE_NAME}
    ```
3. コスト取得を実行
    ```
    make run
    ```

## template.yaml の更新

`main.py` の内容を変更した場合、以下のコマンドで `template.yaml` に反映してください。

```
make update-template
```

## デプロイ

1. AWS コンソールから CloudFormation で `template.yaml` をアップロードしてスタックを作成
2. Lambda に `organizations:ListAccounts` ポリシーを追加でアタッチ（アカウント名の取得に必要）
