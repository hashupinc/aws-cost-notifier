import logging
import os
from datetime import date, datetime, timedelta
from typing import Tuple

import boto3

logger = logging.getLogger()

ce = boto3.client("ce", region_name="us-east-1")


def main():
    total_billing = get_total_billing()
    service_billings = get_service_billings()
    account_billings = get_account_billings()

    title, details = create_message(total_billing, service_billings, account_billings)
    print(title)
    print(details)


# 合計の請求額を取得する関数
def get_total_billing() -> dict:
    (start_date, end_date) = get_total_cost_date_range()

    response = ce.get_cost_and_usage(
        TimePeriod={"Start": start_date, "End": end_date},
        Granularity="MONTHLY",
        Metrics=["AmortizedCost"],
    )
    return {
        "start": response["ResultsByTime"][0]["TimePeriod"]["Start"],
        "end": response["ResultsByTime"][0]["TimePeriod"]["End"],
        "billing": response["ResultsByTime"][0]["Total"]["AmortizedCost"]["Amount"],
    }


# サービス毎の請求額を取得する関数
def get_service_billings() -> list:
    (start_date, end_date) = get_total_cost_date_range()

    response = ce.get_cost_and_usage(
        TimePeriod={"Start": start_date, "End": end_date},
        Granularity="MONTHLY",
        Metrics=["AmortizedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
    )

    billings = []

    for item in response["ResultsByTime"][0]["Groups"]:
        billings.append(
            {
                "service_name": item["Keys"][0],
                "billing": item["Metrics"]["AmortizedCost"]["Amount"],
            }
        )
    return billings


# アカウント毎の請求額を取得する関数
def get_account_billings() -> list:
    (start_date, end_date) = get_total_cost_date_range()

    response = ce.get_cost_and_usage(
        TimePeriod={"Start": start_date, "End": end_date},
        Granularity="MONTHLY",
        Metrics=["AmortizedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": "LINKED_ACCOUNT"}],
    )

    billings = []

    for item in response["ResultsByTime"][0]["Groups"]:
        account_id = item["Keys"][0]
        billing = item["Metrics"]["AmortizedCost"]["Amount"]
        billings.append(
            {
                "account_id": account_id,
                "billing": billing,
            }
        )
    return billings


# メッセージを作成する関数
def create_message(
    total_billing: dict, service_billings: list, account_billings: list
) -> Tuple[str, str]:
    start = datetime.strptime(total_billing["start"], "%Y-%m-%d").strftime("%m/%d")

    # Endの日付は結果に含まないため、表示上は前日にしておく
    end_today = datetime.strptime(total_billing["end"], "%Y-%m-%d")
    end_yesterday = (end_today - timedelta(days=1)).strftime("%m/%d")

    total = round(float(total_billing["billing"]), 2)

    account_id = os.environ.get("ACCOUNT_ID")

    raw_title = f"AWS Billing Notification ({start}～{end_yesterday}) : {total:.2f} USD"

    if account_id:
        title = f"{account_id} - {raw_title}"
    else:
        title = raw_title

    details = []

    # サービス毎の請求額
    details.append("Service Billing Details:")
    for item in service_billings:
        service_name = item["service_name"]
        billing = round(float(item["billing"]), 2)

        if billing == 0.0:
            # 請求無し（0.0 USD）の場合は、内訳を表示しない
            continue
        details.append(f"・{service_name}: {billing:.2f} USD")

    # 全サービスの請求無し（0.0 USD）の場合は以下メッセージを追加
    if not details:
        details.append("No charge this period at present.")

    # アカウント毎の請求額
    details.append("\nAccount Billing Details:")
    for item in account_billings:
        account_id = item["account_id"]
        billing = round(float(item["billing"]), 2)

        if billing == 0.0:
            # 請求無し（0.0 USD）の場合は、内訳を表示しない
            continue
        details.append(f"・{account_id}: {billing:.2f} USD")

    # 全アカウントの請求無し（0.0 USD）の場合は以下メッセージを追加
    if not any(item["billing"] != "0.0" for item in account_billings):
        details.append("No account charge this period at present.")

    return title, "\n".join(details)


# 請求額の期間を取得する関数
def get_total_cost_date_range() -> Tuple[str, str]:
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


if __name__ == "__main__":
    main()
