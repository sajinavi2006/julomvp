from django.conf import settings
from django.utils import timezone
from django.db import connection

from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting
from juloserver.monitors.notifications import send_slack_bot_message


def count_number_of_loans_by_status(list_loan_status, product_line_applied):
    if not list_loan_status or not product_line_applied:
        return dict()

    sql_query = """
        SELECT loan_status_code as loan_status, COUNT(loan_status_code) as count_status
        FROM ops.loan l
        JOIN ops.application a ON l.application_id2 = a.application_id
            AND product_line_code in %s
        WHERE loan_status_code IN %s and a.partner_id is null
        GROUP BY loan_status_code
    """
    rows = list()
    with connection.cursor() as cursor:
        cursor.execute(sql_query, [tuple(product_line_applied), tuple(list_loan_status)])
        rows = cursor.fetchall()

    return dict(rows)


def construct_slack_message_alert_for_stuck_loan(
    count_loan_status, threshold_to_tag_member, list_user_id_to_tag_when_exceed_threshold,
):
    message_parts = [
        "*Report on _env:{}_ at _{}_:*\n".format(
            settings.ENVIRONMENT.upper(),
            timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M:%S")
        )
    ]
    list_loan_status_exceed_threshold = []
    for loan_status, count in count_loan_status.items():
        if count > threshold_to_tag_member:
            list_loan_status_exceed_threshold.append(str(loan_status))  # join expected str instance

        message_parts.append(
            "- Status `{}` has `{}` loans\n".format(loan_status, count)
        )

    if not count_loan_status:
        message_parts.append("- No loan stuck\n")

    if list_loan_status_exceed_threshold:
        mentions = [
            "<@{}>".format(user_id) for user_id in list_user_id_to_tag_when_exceed_threshold
        ]

        message_parts.append(
            "\n:warning: These loan statuses {} exceeded the threshold. "
            "Please help to check {}".format(
                ', '.join(list_loan_status_exceed_threshold), ' '.join(mentions)
            )
        )

    return ''.join(message_parts)


def send_alert_for_stuck_loan_through_slack():
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.ALERT_FOR_STUCK_LOAN,
        is_active=True,
    ).last()

    if not feature_setting:
        return None

    parameters = feature_setting.parameters

    send_slack_bot_message(
        channel=parameters['slack_channel_name'],
        message=construct_slack_message_alert_for_stuck_loan(
            count_loan_status=count_number_of_loans_by_status(
                parameters['list_stuck_loan_status'], parameters['product_line_applied']
            ),
            threshold_to_tag_member=parameters['threshold_to_tag_member'],
            list_user_id_to_tag_when_exceed_threshold=parameters[
                'list_user_id_to_tag_when_exceed_threshold'
            ],
        )
    )
