# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AWS Lambda アプリケーション。AWS Cost Explorer から請求データを取得し、Email(SNS)・Slack・LINE に通知する。
Python 3.9+ / Poetry / CloudFormation (SAM-style) で構成。

## Commands

```bash
make install          # Poetry で依存関係インストール
make lint             # flake8 による静的解析
make format           # black によるコード整形
make run              # main.py をローカル実行（AWS認証が必要）
make update-template  # main.py の内容を template.yaml の ZipFile に同期
```

テストフレームワークは未導入。CI では `make lint` のみ実行。

## Architecture

### 実行フロー

1. `lambda_handler()` → EventBridge から定期実行
2. `get_cost_date_range()` → 請求期間を算出（当月1日〜2日前、1日実行時は前月）
3. `get_billing_data()` → Cost Explorer API で日次コストを取得（SERVICE, LINKED_ACCOUNT でグループ化）
4. `process_billing_data()` → サービス別・アカウント別に集計（Tax は別枠）
5. `create_message()` → 通知メッセージ生成（前日比デルタ付き）
6. `send_email()` / `send_slack()` / `send_line()` → 各チャネルに送信（環境変数で制御）

### コード構成

- **main.py** — 全ロジックが1ファイルに集約（Lambda ZipFile 制約のため）
- **template.yaml** — CloudFormation テンプレート。Lambda コードは ZipFile として埋め込み
- main.py を編集後、`make update-template` で template.yaml に反映する運用

### 通知チャネル（すべてオプション）

| チャネル | 環境変数 | 認証情報の取得先 |
|---------|---------|--------------|
| Email | `EMAIL_TOPIC_ARN` | SNS Topic ARN |
| Slack | `SLACK_SECRET_NAME` | Secrets Manager（Lambda Extension 経由） |
| LINE | `LINE_SECRET_NAME` | Secrets Manager（Lambda Extension 経由） |

### CloudFormation リソース命名

`NAB` プレフィックス（Notification AWS Billing）: `NABFunction`, `NABFunctionRole`, `NABTopicToEmail` 等。

## Code Style

- **flake8**: max-line-length = 150（`.flake8` で設定）
- **black**: デフォルト設定
- コメント・ドキュメントは日本語
- PR はセマンティックコミットメッセージ必須（`feat:`, `fix:`, `docs:` 等）
