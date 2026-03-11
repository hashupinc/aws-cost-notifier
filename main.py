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
org_client = boto3.client("organizations")


def lambda_handler(event: Dict[str, Any], context: Any) -> None:
    """AWS Lambda関数のエントリポイントとして、請求情報を処理し、通知を送信する。

    この関数は、AWSの請求データを取得し、前日の請求データと比較した結果を評価します。
    請求情報に基づいて生成されたメッセージを、設定された宛先（メール、Slack、LINE）に送信します。
    宛先が設定されていない場合はエラーログを出力します。

    Args:
        event (Dict[str, Any]): Lambda関数に渡されるイベントオブジェクト。
        context (Any): ランタイム情報を提供するオブジェクト。

    Raises:
        Exception: メッセージ送信時または処理中にエラーが発生した場合に例外をスローします。
    """
    current_billing_data = get_billing_data()

    total_billing_info, service_billings, account_billings, tax_billing = (
        process_billing_data(current_billing_data)
    )

    # クレジット情報の取得
    credit_info = None
    if os.environ.get("SHOW_CREDIT_DETAILS") == "true":
        start_date, end_date = get_cost_date_range()
        gross_resp, credit_resp = get_credit_data(start_date, end_date)
        credit_info = process_credit_data(gross_resp, credit_resp)

    # 投稿用のメッセージを作成する
    title, detail = create_message(
        total_billing_info, service_billings, account_billings, tax_billing, credit_info
    )

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


def get_billing_data() -> dict:
    """AWSのCost Explorerから請求情報を取得する。

    この関数は、当月の請求データを日次で取得します。
    SHOW_CREDIT_DETAILS が有効な場合、Credit レコードを除外して実コストを返します。

    Returns:
        dict: 請求期間、グループ化されたサービス、およびリンクアカウントごとの
              請求情報を含む辞書。
    """
    start_date, end_date = get_cost_date_range()

    params = {
        "TimePeriod": {
            "Start": start_date,
            "End": end_date,
        },
        "Granularity": "DAILY",
        "Metrics": ["UnblendedCost"],
        "GroupBy": [
            {"Type": "DIMENSION", "Key": "SERVICE"},
            {"Type": "DIMENSION", "Key": "LINKED_ACCOUNT"},
        ],
    }

    # クレジット詳細表示が有効な場合、Credit レコードを除外して実コストを表示
    if os.environ.get("SHOW_CREDIT_DETAILS") == "true":
        params["Filter"] = {
            "Not": {"Dimensions": {"Key": "RECORD_TYPE", "Values": ["Credit"]}}
        }

    response = ce.get_cost_and_usage(**params)
    return response


def get_credit_data(start_date: str, end_date: str) -> Tuple[dict, dict]:
    """クレジット適用前のコスト（Gross cost）とクレジット額を取得する。

    Cost Explorer API を2回呼び出し、Credit レコードを除外した総コストと
    Credit レコードのみのコストを取得する。

    Args:
        start_date (str): ISO形式の開始日。
        end_date (str): ISO形式の終了日。

    Returns:
        Tuple[dict, dict]: Gross cost レスポンスと Credit レスポンスのタプル。
    """
    gross_resp = ce.get_cost_and_usage(
        TimePeriod={"Start": start_date, "End": end_date},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
        Filter={"Not": {"Dimensions": {"Key": "RECORD_TYPE", "Values": ["Credit"]}}},
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
    )

    credit_resp = ce.get_cost_and_usage(
        TimePeriod={"Start": start_date, "End": end_date},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
        Filter={"Dimensions": {"Key": "RECORD_TYPE", "Values": ["Credit"]}},
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
    )

    return gross_resp, credit_resp


def process_credit_data(gross_resp: dict, credit_resp: dict) -> Optional[dict]:
    """クレジットデータを処理し、クレジット情報を返す。

    Gross cost と Credit のレスポンスを受け取り、クレジットがある場合は
    サービス別の内訳を含むクレジット情報を返す。クレジットがない場合は None を返す。

    Args:
        gross_resp (dict): Gross cost の Cost Explorer レスポンス。
        credit_resp (dict): Credit の Cost Explorer レスポンス。

    Returns:
        Optional[dict]: クレジット情報。クレジットがない場合は None。
    """
    # Gross cost の合計を算出
    gross_cost = 0.0
    for time_period in gross_resp.get("ResultsByTime", []):
        for group in time_period.get("Groups", []):
            gross_cost += float(group["Metrics"]["UnblendedCost"]["Amount"])

    # Credit の合計とサービス別内訳を算出
    total_credits = 0.0
    credit_by_service = {}
    for time_period in credit_resp.get("ResultsByTime", []):
        for group in time_period.get("Groups", []):
            service_name = group["Keys"][0]
            amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
            total_credits += amount
            if service_name in credit_by_service:
                credit_by_service[service_name] += amount
            else:
                credit_by_service[service_name] = amount

    # クレジットがない場合は None を返す
    if total_credits == 0.0:
        return None

    # サービス別内訳を amount の絶対値の降順でソート
    sorted_services = sorted(
        [
            {"service_name": name, "amount": amount}
            for name, amount in credit_by_service.items()
        ],
        key=lambda x: abs(x["amount"]),
        reverse=True,
    )

    return {
        "gross_cost": gross_cost,
        "total_credits": total_credits,
        "credit_by_service": sorted_services,
    }


def process_billing_data(current_data):
    """請求データを処理し、集計結果を返す。

    現在の請求データと前日の請求データを受け取り、総請求額、
    サービスごとの請求額、アカウントごとの請求額を計算してまとめます。

    Args:
        current_data (dict): 現在の請求期間のデータを含む辞書。

    Returns:
        Tuple[dict, list, list]:
            - 総請求額の情報を含む辞書。開始日、終了日、請求額、前日の請求額を含む。
            - サービスごとの請求情報をまとめたリスト。
            - アカウントごとの請求情報をまとめたリスト。
    """
    daily_data = current_data["ResultsByTime"]

    # 各サービスとアカウントの総請求額を格納する辞書
    aggregated_service_billings = {}
    aggregated_account_billings = {}

    # 全体の請求額を計算
    total_billing = 0.0
    tax_billing = 0.0

    for day_index, day_data in enumerate(daily_data):
        for item in day_data["Groups"]:
            service_name = item["Keys"][0]

            # 「Tax」サービスは除外
            if service_name == "Tax":
                tax_billing += float(item["Metrics"]["UnblendedCost"]["Amount"])
                continue

            # 請求額を取得
            billing = float(item["Metrics"]["UnblendedCost"]["Amount"])
            total_billing += billing

            # サービスごとの請求額の集計
            if service_name not in aggregated_service_billings:
                aggregated_service_billings[service_name] = {
                    "billing": 0.0,
                    "prev_billing": 0.0,
                }

            aggregated_service_billings[service_name]["billing"] += billing
            if day_index == len(daily_data) - 1:  # 「前日」の合計
                aggregated_service_billings[service_name]["prev_billing"] += billing

            # アカウントごとの請求額の集計
            if len(item["Keys"]) > 1:
                account_id = item["Keys"][1]
                if account_id not in aggregated_account_billings:
                    aggregated_account_billings[account_id] = {
                        "billing": 0.0,
                        "prev_billing": 0.0,
                    }

                aggregated_account_billings[account_id]["billing"] += billing
                if day_index == len(daily_data) - 1:  # 「前日」の合計
                    aggregated_account_billings[account_id]["prev_billing"] += billing

    # 前日から当日への増加分を計算
    prev_day_total_billing = sum(
        float(item["Metrics"]["UnblendedCost"]["Amount"])
        for item in daily_data[-1]["Groups"]
    )

    # サービスおよびアカウントのリストを作成
    service_billings = [
        {
            "service_name": service_name,
            "billing": data["billing"],
            "prev_billing": data["prev_billing"],
        }
        for service_name, data in aggregated_service_billings.items()
    ]

    account_billings = [
        {
            "account_id": account_id,
            "billing": data["billing"],
            "prev_billing": data["prev_billing"],
        }
        for account_id, data in aggregated_account_billings.items()
    ]

    # 開始日と終了日を取得
    start_date = daily_data[0]["TimePeriod"]["Start"]
    end_date = daily_data[-1]["TimePeriod"]["End"]

    return (
        {
            "start": start_date,
            "end": end_date,
            "billing": total_billing,
            "prev_billing": prev_day_total_billing,
        },
        service_billings,
        account_billings,
        tax_billing,
    )


def main():
    """AWS請求情報を取得し、処理した結果を出力する。

    この関数はAWSの請求データを取得し、現在の請求期間と前日の請求期間のデータを処理します。
    複数のレベル（総額、サービス別、アカウント別）で請求情報を整理し、
    メッセージを作成してコンソールに表示します。
    """
    current_billing_data = get_billing_data()

    total_billing_info, service_billings, account_billings, tax_billing = (
        process_billing_data(current_billing_data)
    )

    # クレジット情報の取得
    credit_info = None
    if os.environ.get("SHOW_CREDIT_DETAILS") == "true":
        start_date, end_date = get_cost_date_range()
        gross_resp, credit_resp = get_credit_data(start_date, end_date)
        credit_info = process_credit_data(gross_resp, credit_resp)

    title, details = create_message(
        total_billing_info, service_billings, account_billings, tax_billing, credit_info
    )
    print(title)
    print(details)


def create_message(
    total_billing: dict,
    service_billings: list,
    account_billings: list,
    tax_billing: float,
    credit_info: Optional[dict] = None,
) -> Tuple[str, str]:
    """請求情報に基づいてメッセージのタイトルと詳細を作成する。

    与えられた請求情報から、全体の請求額、サービスごとの請求額、および
    アカウントごとの請求額に基づいて、人間が読みやすい形式のメッセージを作成します。
    メッセージは、通知に使用できるタイトルと詳細の2つの文字列を返します。

    Args:
        total_billing (dict): 全体の請求情報を含む辞書。'start', 'end', 'billing', 'prev_billing' キーを含む。
        service_billings (list): 各サービスごとの請求情報を含むリスト。各項目は'dict'であり、'service_name', 'billing', 'prev_billing'を含む。
        account_billings (list): 各アカウントごとの請求情報を含むリスト。各項目は'dict'であり、'account_id', 'billing', 'prev_billing'を含む。

    Returns:
        Tuple[str, str]: メッセージのタイトルと詳細を表す2つの文字列。
    """
    start = datetime.strptime(total_billing["start"], "%Y-%m-%d").strftime("%m/%d")

    # Endの日付は結果に含まないため、表示上は前日にしておく
    end_today = datetime.strptime(total_billing["end"], "%Y-%m-%d")
    end_yesterday = (end_today - timedelta(days=1)).strftime("%m/%d")

    total = total_billing["billing"]
    prev_total = total_billing["prev_billing"]

    title = f"AWS Billing Notification ({start}～{end_yesterday}) : {total:.02f} USD ({prev_total:+.02f} USD)"

    details = []

    # クレジット情報
    if credit_info is not None:
        details.append("Credit Usage:")
        details.append(
            f"- Gross Cost (before credits): {credit_info['gross_cost']:.02f} USD"
        )
        details.append(f"- Credits Applied: {credit_info['total_credits']:.02f} USD")
        for item in credit_info["credit_by_service"]:
            # クレジット額は負数なので絶対値で表示
            details.append(
                f"  - {item['service_name']}: {abs(item['amount']):.02f} USD"
            )
        details.append("")

    # サービス毎の請求額
    details.append("Service Billing Details:")
    has_service_billing = False
    for item in service_billings:
        service_name = item["service_name"]
        billing = item["billing"]
        prev_billing = item["prev_billing"]

        if billing == 0.0:
            # 請求無し（0.0 USD）の場合は、内訳を表示しない
            continue
        details.append(
            f"- {service_name}: {billing:.02f} USD ({prev_billing:+.02f} USD)"
        )
        has_service_billing = True

    # サービスの請求が1件もない場合はメッセージを追加
    if not has_service_billing:
        details.append("No charge this period at present.")

    # アカウントIDと名前のマッピングを取得
    account_name_mapping = get_account_name_mapping()

    # アカウント毎の請求額
    details.append("\nAccount Billing Details:")
    aggregated_account_billings = create_aggregated_account_billings(account_billings)
    for item in aggregated_account_billings:
        account_id = item["account_id"]
        account_name = account_name_mapping.get(account_id, None)
        billing = item["billing"]
        prev_billing = item["prev_billing"]

        if billing == 0.0:
            # 請求無し（0.0 USD）の場合は、内訳を表示しない
            continue
        if account_name is None:
            details.append(
                f"- {account_id}: {billing:.02f} USD ({prev_billing:+.02f} USD)"
            )
        else:
            details.append(
                f"- {account_name} ({account_id}): {billing:.02f} USD ({prev_billing:+.02f} USD)"
            )

    # 全アカウントの請求無し（0.0 USD）の場合は以下メッセージを追加
    if not any(item["billing"] != 0.0 for item in account_billings):
        details.append("No account charge this period at present.")

    # Taxの請求額
    if tax_billing > 0.0:
        details.append(f"\nTax Billing: {tax_billing:.02f} USD")
    else:
        details.append("No tax charge this period at present.")

    return title, "\n".join(details)


def get_account_name_mapping() -> Dict[str, str]:
    """AWS OrganizationsからアカウントIDと名前のマッピングを取得する。

    AWS Organizations APIを使用して、AWSアカウントIDとその対応するアカウント名の
    マッピングを取得します。この関数は呼び出し元の権限によっては
    アクセスが拒否される可能性があります。その場合は、アカウントIDのみを使用した
    代替案をログに警告として記録します。

    Returns:
        Dict[str, str]: アカウントIDをキー、アカウント名を値とする辞書。

    Raises:
        Boto3が特定の例外を投げた場合はその例外が伝播します。ただし、アクセス権がない場合は
        警告を出力して処理を続行します。
    """
    account_mapping = {}
    try:
        paginator = org_client.get_paginator("list_accounts")

        for page in paginator.paginate():
            logger.debug(f"Page: {page}")
            for account in page["Accounts"]:
                account_id = account["Id"]
                account_name = account["Name"]
                account_mapping[account_id] = account_name
    except org_client.exceptions.AccessDeniedException:
        logger.warning(
            "Access denied to list accounts. Falling back to using account IDs."
        )

    return account_mapping


def create_aggregated_account_billings(account_billings: list) -> list:
    """
    アカウントIDごとの請求額を集計する。

    各アカウントIDに対して現在および前回の請求額を合計します。
    結果は、アカウントID、合計請求額、前回の請求額を含む辞書のリストとして返されます。

    Args:
        account_billings (list): 'account_id', 'billing', 'prev_billing'を含む各アカウントの請求データのリスト。

    Returns:
        list: 'account_id'、'billing'、'prev_billing'を含む集計された請求データのリスト。
    """
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


def get_cost_date_range() -> Tuple[str, str]:
    """請求期間を取得する

    この関数は、当月の開始日から前日までの請求期間を計算します。
    ただし、今日が2日の場合（start_date と end_date が同一になる場合）は、
    前月の1日から前月末日までの期間を取得します。
    これは、Cost Explorer APIの制約により、開始日と終了日に同じ日付を指定できないためです。

    Returns:
        Tuple[str, str]: ISO形式の開始日と終了日を含むタプル。
    """
    start_date = date.today().replace(day=1).isoformat()
    end_date = (date.today() - timedelta(days=1)).isoformat()

    # get_cost_and_usage()のstartとendに同じ日付は指定不可のため、
    # 「今日が1日」なら、「先月1日から今月1日（今日）」までの範囲にする
    if start_date == end_date:
        end_of_month = datetime.strptime(start_date, "%Y-%m-%d") + timedelta(days=-1)
        begin_of_month = end_of_month.replace(day=1)
        start_date = begin_of_month.isoformat()

    return start_date, end_date


def get_secret(secret_name: Optional[str], secret_key: str) -> Any:
    """シークレットマネージャからシークレットを取得する

    AWSのParameters and Secrets Lambda Extensionを使用して、Secrets Managerから
    効率的にシークレットを取得します。この関数はローカルのエンドポイントを
    使用してシークレットにアクセスします。

    Args:
        secret_name (Optional[str]): 取得したいシークレットの名前。
        secret_key (str): シークレットデータの中で取得したい特定のキー。

    Returns:
        Any: 指定したシークレットキーに対応する値。

    Raises:
        ValueError: シークレット名またはAWSセッショントークンが設定されていない場合に発生します。

    Note:
        詳細については、AWSの公式ドキュメントを参照してください:
        https://docs.aws.amazon.com/ja_jp/secretsmanager/latest/userguide/retrieving-secrets_lambda.html
    """

    # シークレット名を取得
    if secret_name is None:
        raise ValueError("Secret name must not be None")

    # Lambda ローカル環境で動作する AWS Secrets Manager のエンドポイントへのリクエストを準備
    # AWS Parameters and Secrets Lambda Extension により、http://localhost:2773 で提供されるローカルエンドポイントを使用
    secrets_extension_endpoint = (
        "http://localhost:2773/secretsmanager/get?secretId=" + secret_name
    )

    # ヘッダーにAWSセッショントークンを設定
    aws_session_token = os.environ.get("AWS_SESSION_TOKEN")
    if aws_session_token is None:
        raise ValueError("AWS session token must not be None")
    headers = {"X-Aws-Parameters-Secrets-Token": aws_session_token}

    # Secrets Manager へのアクセスを高速化するために拡張機能が提供するキャッシュを活用
    # シークレットマネージャからシークレットを取得
    secrets_extension_req = request.Request(secrets_extension_endpoint, headers=headers)
    with request.urlopen(secrets_extension_req) as response:
        secret_config = response.read()
    secret_json = json.loads(secret_config)["SecretString"]
    secret_value = json.loads(secret_json)[secret_key]
    return secret_value


def send_request(url: str, data: bytes, headers: MutableMapping[str, str]) -> None:
    """指定されたURLにHTTP POSTリクエストを送信する。

    提供されたデータとヘッダーを使用して指定されたURLに対してHTTP POSTリクエストを実行します。
    レスポンスが正常に返ってくるかを確認するために、ステータスコードを出力します。

    Args:
        url (str): リクエストを送信する先のURL。
        data (bytes): POSTリクエストの本文として送信されるデータ。
        headers (MutableMapping[str, str]): リクエストに含めるヘッダー情報を表す辞書。

    Returns:
        None

    Raises:
        urllib.error.URLError: リクエストの送信中にURLにアクセスできない場合に発生します。
        urllib.error.HTTPError: リクエストがHTTPエラーのステータスコードを返した場合に発生します。
    """
    req = request.Request(url, data=data, headers=headers, method="POST")
    with request.urlopen(req) as response:
        print(response.status)


if __name__ == "__main__":
    main()
