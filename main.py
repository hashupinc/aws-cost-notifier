import json
import logging
import os
from datetime import date, datetime, timedelta
from typing import Any, Dict, MutableMapping, Optional, Tuple
from urllib import request

import boto3

logger = logging.getLogger()

ce = boto3.client("ce", region_name="us-east-1")

# AWS アカウント名を取得するためのクライアント
org_client = boto3.client('organizations')


def lambda_handler(event: Dict[str, Any], context: Any) -> None:
    """Lambdaハンドラ"""
    current_billing_data = get_billing_data()
    prev_billing_data = get_billing_data(single_date=True)

    total_billing_info, service_billings, account_billings = process_billing_data(current_billing_data, prev_billing_data)

    # 投稿用のメッセージを作成する
    (title, detail) = create_message(total_billing_info, service_billings, account_billings)

    try:
        email_topic_arn = os.environ.get("EMAIL_TOPIC_ARN")
        slack_secret_name = os.environ.get("SLACK_SECRET_NAME")
        line_secret_name = os.environ.get("LINE_SECRET_NAME")

        # メール用トピックが設定されている場合は、メール用トピックにメッセージを送信する
        if email_topic_arn:
            sns = boto3.client("sns")
            sns.publish(
                TopicArn=email_topic_arn,
                Subject=title,
                Message=detail,
            )

        # SlackのWebhook URLが設定されている場合は、Slackにメッセージを投稿する
        if slack_secret_name:
            webhook_url = get_secret(slack_secret_name, "info")
            payload = {
                "text": title,
                "blocks": [
                    {"type": "header", "text": {"type": "plain_text", "text": title}},
                    {"type": "section", "text": {"type": "plain_text", "text": detail}},
                ],
            }
            data = json.dumps(payload).encode()
            headers = {"Content-Type": "application/json"}

            send_request(webhook_url, data, headers)

        # LINEのアクセストークンが設定されている場合は、LINEにメッセージを投稿する
        if line_secret_name:
            channel_access_token = get_secret(line_secret_name, "info")
            webhook_url = "https://api.line.me/v2/bot/message/broadcast"
            payload = {"messages": [{"type": "text", "text": f"{title}\n\n{detail}"}]}
            data = json.dumps(payload).encode("utf-8")
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {channel_access_token}",
            }

            send_request(webhook_url, data, headers)

        # いずれの送信先も設定されていない場合はエラーを出力する
        if not email_topic_arn and not slack_secret_name and not line_secret_name:
            logger.error(
                "No destination to post message. Please set environment variables."
            )

    except Exception as e:
        logger.exception("Exception occurred: %s", e)
        raise e


def get_billing_data(single_date=False) -> dict:
    """請求情報を取得する"""
    if single_date:
        end_date = date.today().isoformat()
        start_date = (date.today() - timedelta(days=1)).isoformat()
    else:
        start_date, end_date = get_total_cost_date_range()

    response = ce.get_cost_and_usage(
        TimePeriod={"Start": start_date, "End": end_date, },
        Granularity="DAILY" if single_date else "MONTHLY",
        Metrics=["AmortizedCost"],
        GroupBy=[
            {"Type": "DIMENSION", "Key": "SERVICE"},
            {"Type": "DIMENSION", "Key": "LINKED_ACCOUNT"}
        ]
    )
    return response


def process_billing_data(current_data, prev_data):
    current_total_billing = 0.0
    prev_total_billing = 0.0

    current_time_period = current_data["ResultsByTime"][0]["TimePeriod"]

    current_total_billing = sum(float(item["Metrics"]["AmortizedCost"]["Amount"]) for item in current_data["ResultsByTime"][0]["Groups"])
    prev_total_billing = sum(float(item["Metrics"]["AmortizedCost"]["Amount"]) for item in prev_data["ResultsByTime"][0]["Groups"])

    # サービスごとの請求額の集計
    aggregated_service_billings = {}

    for item in current_data["ResultsByTime"][0]["Groups"]:
        service_name = item["Keys"][0]
        billing = float(item["Metrics"]["AmortizedCost"]["Amount"])
        aggregated_service_billings.setdefault(service_name, {"billing": 0.0, "prev_billing": 0.0})
        aggregated_service_billings[service_name]["billing"] += billing

    for prev_item in prev_data["ResultsByTime"][0]["Groups"]:
        service_name = prev_item["Keys"][0]
        prev_billing = float(prev_item["Metrics"]["AmortizedCost"]["Amount"])
        if service_name in aggregated_service_billings:
            aggregated_service_billings[service_name]["prev_billing"] += prev_billing

    service_billings = [
        {
            "service_name": service_name,
            "billing": data["billing"],
            "prev_billing": data["prev_billing"],
        }
        for service_name, data in aggregated_service_billings.items()
    ]

    # アカウント毎の請求額の計算
    aggregated_account_billings = {}

    for item in current_data["ResultsByTime"][0]["Groups"]:
        if len(item["Keys"]) > 1:
            account_id = item["Keys"][1]
            billing = float(item["Metrics"]["AmortizedCost"]["Amount"])
            aggregated_account_billings.setdefault(account_id, {"billing": 0.0, "prev_billing": 0.0})
            aggregated_account_billings[account_id]["billing"] += billing

    for prev_item in prev_data["ResultsByTime"][0]["Groups"]:
        if len(prev_item["Keys"]) > 1:
            account_id = prev_item["Keys"][1]
            prev_billing = float(prev_item["Metrics"]["AmortizedCost"]["Amount"])
            if account_id in aggregated_account_billings:
                aggregated_account_billings[account_id]["prev_billing"] += prev_billing

    account_billings = [
        {
            "account_id": account_id,
            "billing": data["billing"],
            "prev_billing": data["prev_billing"],
        }
        for account_id, data in aggregated_account_billings.items()
    ]

    return {
        "start": current_time_period["Start"],
        "end": current_time_period["End"],
        "billing": current_total_billing,
        "prev_billing": prev_total_billing,
    }, service_billings, account_billings


def main():
    current_billing_data = get_billing_data()
    prev_billing_data = get_billing_data(single_date=True)

    total_billing_info, service_billings, account_billings = process_billing_data(current_billing_data, prev_billing_data)

    title, details = create_message(total_billing_info, service_billings, account_billings)
    print(title)
    print(details)


def create_message(
    total_billing: dict, service_billings: list, account_billings: list
) -> Tuple[str, str]:
    """メッセージを作成する"""
    start = datetime.strptime(total_billing["start"], "%Y-%m-%d").strftime("%m/%d")

    # Endの日付は結果に含まないため、表示上は前日にしておく
    end_today = datetime.strptime(total_billing["end"], "%Y-%m-%d")
    end_yesterday = (end_today - timedelta(days=1)).strftime("%m/%d")

    total = total_billing["billing"]
    prev_total = total_billing["prev_billing"]

    account_id = os.environ.get("ACCOUNT_ID")

    title = f"AWS Billing Notification ({start}～{end_yesterday}) : {total:.2f} USD ({prev_total:+.2f} USD)"

    details = []

    # サービス毎の請求額
    details.append("Service Billing Details:")
    for item in service_billings:
        service_name = item["service_name"]
        billing = round(item["billing"], 2)
        prev_billing = item["prev_billing"]

        if billing == 0.0:
            # 請求無し（0.0 USD）の場合は、内訳を表示しない
            continue
        details.append(f"・{service_name}: {billing:.2f} USD ({prev_billing:+.2f} USD)")

    # 全サービスの請求無し（0.0 USD）の場合は以下メッセージを追加
    if not details:
        details.append("No charge this period at present.")

    # アカウントIDと名前のマッピングを取得
    account_name_mapping = get_account_name_mapping()

    # アカウント毎の請求額
    details.append("\nAccount Billing Details:")
    aggregated_account_billings = create_aggregated_account_billings(account_billings)
    for item in aggregated_account_billings:
        account_id = item["account_id"]
        account_name = account_name_mapping.get(account_id, None)
        billing = round(item["billing"], 2)
        prev_billing = item["prev_billing"]

        if billing == 0.0:
            # 請求無し（0.0 USD）の場合は、内訳を表示しない
            continue
        if account_name is None:
            details.append(f"・{account_id}: {billing:.2f} USD ({prev_billing:+.2f} USD)")
        else:
            details.append(f"・{account_name} ({account_id}): {billing:.2f} USD ({prev_billing:+.2f} USD)")

    # 全アカウントの請求無し（0.0 USD）の場合は以下メッセージを追加
    if not any(item["billing"] != "0.0" for item in account_billings):
        details.append("No account charge this period at present.")

    return title, "\n".join(details)


def get_account_name_mapping() -> Dict[str, str]:
    """AWS OrganizationsからアカウントIDと名前のマッピングを取得する"""
    account_mapping = {}
    try:
        paginator = org_client.get_paginator('list_accounts')

        for page in paginator.paginate():
            logger.debug(f"Page: {page}")
            for account in page['Accounts']:
                account_id = account['Id']
                account_name = account['Name']
                account_mapping[account_id] = account_name
    except org_client.exceptions.AccessDeniedException:
        logger.warning("Access denied to list accounts. Falling back to using account IDs.")

    return account_mapping


def create_aggregated_account_billings(account_billings: list) -> list:
    """アカウントIDごとに請求額を集計する"""
    aggregated_billings = {}

    for item in account_billings:
        account_id = item["account_id"]
        billing = item["billing"]
        prev_billing = item["prev_billing"]

        if account_id not in aggregated_billings:
            aggregated_billings[account_id] = {"billing": 0.0, "prev_billing": 0.0}

        # 現在と前回の両方の請求額を集計
        aggregated_billings[account_id]["billing"] += billing
        aggregated_billings[account_id]["prev_billing"] += prev_billing

    # 辞書をリストに変換
    return [
        {
            "account_id": account_id,
            "billing": data["billing"],
            "prev_billing": data["prev_billing"],
        }
        for account_id, data in aggregated_billings.items()
    ]


def get_total_cost_date_range() -> Tuple[str, str]:
    """請求期間を取得する """
    start_date = date.today().replace(day=1).isoformat()
    end_date = date.today().isoformat()

    # get_cost_and_usage()のstartとendに同じ日付は指定不可のため、
    # 「今日が1日」なら、「先月1日から今月1日（今日）」までの範囲にする
    if start_date == end_date:
        end_of_month = datetime.strptime(start_date, "%Y-%m-%d") + timedelta(days=-1)
        begin_of_month = end_of_month.replace(day=1)
        return begin_of_month.date().isoformat(), end_date

    # デバッグ用に先月1日から先月末日までの範囲にする
    # end_of_month = datetime.strptime(start_date, "%Y-%m-%d") + timedelta(days=-1)
    # begin_of_month = end_of_month.replace(day=1)
    # start_date = begin_of_month.date().isoformat()
    # end_date = end_of_month.date().isoformat()

    return start_date, end_date


def get_prev_cost_date_range() -> Tuple[str, str]:
    """前日の請求期間を取得する """
    end_date = date.today().isoformat()
    start_date = (date.today() - timedelta(days=1)).isoformat()
    return start_date, end_date


def get_secret(secret_name: Optional[str], secret_key: str) -> Any:
    """シークレットマネージャからシークレットを取得する"""
    # シークレット名を取得
    if secret_name is None:
        raise ValueError("Secret name must not be None")
    secrets_extension_endpoint = (
        "http://localhost:2773/secretsmanager/get?secretId=" + secret_name
    )

    # ヘッダーにAWSセッショントークンを設定
    aws_session_token = os.environ.get("AWS_SESSION_TOKEN")
    if aws_session_token is None:
        raise ValueError("aws sessuib token must not be None")
    headers = {"X-Aws-Parameters-Secrets-Token": aws_session_token}

    # シークレットマネージャからシークレットを取得
    secrets_extension_req = request.Request(secrets_extension_endpoint, headers=headers)
    with request.urlopen(secrets_extension_req) as response:
        secret_config = response.read()
    secret_json = json.loads(secret_config)["SecretString"]
    secret_value = json.loads(secret_json)[secret_key]
    return secret_value


def send_request(url: str, data: bytes, headers: MutableMapping[str, str]) -> None:
    """リクエストを送信する"""
    req = request.Request(url, data=data, headers=headers, method="POST")
    with request.urlopen(req) as response:
        print(response.status)


if __name__ == "__main__":
    main()
