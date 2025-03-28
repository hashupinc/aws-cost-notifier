# aws-cost-notifier

## 概要
AWSのコストを取得し、メッセージを送信します。

### 集計期間
- 実行月の1日から現在までのコストを取得します。
  - 例(実行日... 2025/03/20): 2025/03/01 ~ 2025/03/20
- 実行日が1日の場合は、前月の1日から現在までのコストを取得します。
  - 例(実行日... 2025/04/01): 2025/03/01 ~ 2025/04/01

### メッセージ内容
- 合計コスト
- サービスごとのコスト
- アカウントごとのコスト
- 上記項目の前日比

### 出力メッセージ例
```
AWS Billing Notification (03/01～03/27) : 4.42 USD (+0.40 USD)
Service Billing Details:
・AWS Cost Explorer: 0.37 USD (+0.37 USD)
・AWS Secrets Manager: 1.03 USD (+0.02 USD)
・Amazon EC2 Container Registry (ECR): 0.38 USD (+0.01 USD)
・Amazon Relational Database Service: 1.24 USD (+0.00 USD)
・Amazon Route 53: 1.00 USD (+0.00 USD)
・Amazon Simple Storage Service: 0.01 USD (+0.00 USD)
・Tax: 0.40 USD (+0.00 USD)

Account Billing Details:
・${Account ID}: 4.42 USD (+0.40 USD)
```

## Python 環境での確認実行方法
### 前提条件
- aws-cliがインストールされていること
- aws profileが設定されていること
- sso-loginが完了していること

### 実行手順
1. インストールコマンドを実行
    ```
    make install
    ```
2. コスト取得コマンドを実行
    ```
    make get-aws-cost
    ```
3. ターミナルにコストが表示されることを確認
