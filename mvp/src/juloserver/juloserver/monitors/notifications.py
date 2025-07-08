import json
import logging

from django.conf import settings
from django.utils import timezone
from slackclient import SlackClient

from juloserver.dana.constants import DanaBucket
from juloserver.julo.constants import MAX_PAYMENT_OVER_PAID
from juloserver.julo.utils import display_rupiah
from juloserver.partnership.constants import SLACK_CHANNEL_LEADGEN_WEBVIEW_NOTIF
from juloserver.warning_letter.constants import SLACK_CHANNEL_WL_NOTIF

logger = logging.getLogger(__name__)


def get_slack_client():
    return SlackClient(settings.SLACK_WEB_API_TOKEN)


def get_slack_sdk_web_client():
    from slack_sdk import WebClient

    return WebClient(token=settings.SLACK_WEB_API_TOKEN)


def get_slack_bot_client():
    return SlackClient(settings.SLACK_WEB_API_BOT_TOKEN)


def send_slack_bot_message(channel, message):
    slack_bot_client = get_slack_bot_client()
    slack_bot_client.api_call("chat.postMessage", channel=channel, text=message)


def notify_failure(text_data, channel=settings.SLACK_MONITORING_CHANNEL, label_env=False):

    # Info environment when sending alert to channel
    if label_env:
        text_env = '[Production] '
        if settings.ENVIRONMENT != 'prod':
            text_env = '[Non-Prod] '

        # Concatenate existing text data
        text_data = text_env + text_data

    logger.info(text_data)
    slack_client = SlackClient(settings.SLACK_WEB_API_TOKEN)
    slack_client.api_call(
        "chat.postMessage", channel=channel, text="```%s```" % json.dumps(text_data, indent=2)
    )


def notify_data_integrity_checks_completed(check_functions):
    data = {
        'name': 'data_integrity_checks',
        'status': 'completed',
        'check_count': len(check_functions),
    }
    logger.info(data)
    slack_client = SlackClient(settings.SLACK_WEB_API_TOKEN)
    slack_client.api_call(
        "chat.postMessage",
        channel=settings.SLACK_MONITORING_CHANNEL,
        text="```%s```" % json.dumps(data, indent=2),
    )


def notify_sepulsa_balance_low(text_data, channel=settings.SLACK_SEPULSA_CHANNEL):
    logger.info(text_data)
    slack_client = SlackClient(settings.SLACK_WEB_API_TOKEN)
    slack_client.api_call(
        "chat.postMessage", channel=channel, text="```%s```" % json.dumps(text_data, indent=2)
    )


def notify_sepulsa_product_not_exist(operators, channel=settings.SLACK_SEPULSA_CHANNEL):
    products = []
    for operator in operators:
        products.append(
            {
                'code': operator['code'],
                'description': operator['description'],
            }
        )

    data = {
        'Error': 'sepulsa_product_not_exist',
        'Environment': settings.ENVIRONMENT,
        'Product': products,
    }
    logger.info(data)
    slack_client = SlackClient(settings.SLACK_WEB_API_TOKEN)
    slack_client.api_call(
        "chat.postMessage", channel=channel, text="```%s```" % json.dumps(data, indent=2)
    )


def notify_sepulsa_product_closed(sepulsa_transaction, channel=settings.SLACK_SEPULSA_CHANNEL):
    data = {
        'name': 'sepulsa_product_closed',
        'sepulsa_product_id': sepulsa_transaction.product_id,
        'sepulsa_product_name': sepulsa_transaction.product.product_name,
    }
    logger.info(data)
    slack_client = SlackClient(settings.SLACK_WEB_API_TOKEN)
    slack_client.api_call(
        "chat.postMessage", channel=channel, text="```%s```" % json.dumps(data, indent=2)
    )


def notify_max_cashback_earned(customer_id, application_id, loan_id, payment, email, amount):
    data = {
        'action': 'max_cashback_earned',
        'customer_id': customer_id,
        'application_id': application_id,
        'loan_id': loan_id,
        'payment_id': payment.id,
        'email': email,
        'cashback_earned_amount': display_rupiah(amount),
    }
    logger.info(data)
    slack_client = SlackClient(settings.SLACK_WEB_API_TOKEN)
    slack_client.api_call(
        "chat.postMessage",
        channel=settings.SLACK_CASHBACK,
        text="```%s```" % json.dumps(data, indent=2),
    )
    slack_client.api_call(
        "chat.postMessage",
        channel=settings.SLACK_BACKEND,
        text="```%s```" % json.dumps(data, indent=2),
    )


def notify_count_cashback_delayed(list):
    if settings.ENVIRONMENT != 'prod':
        return
    data = {
        'action': 'count_cashback_delayed',
        'count': len(list),
        'list_customer_wallet_history_id': list,
    }
    logger.info(data)
    slack_client = SlackClient(settings.SLACK_WEB_API_TOKEN)
    slack_client.api_call(
        "chat.postMessage",
        channel=settings.SLACK_BACKEND,
        text="```%s```" % json.dumps(data, indent=2),
    )


def notify_partner_account_attribution(application, partner_referral, description):
    if settings.ENVIRONMENT != 'prod':
        return
    if partner_referral:
        partner_referral_id = partner_referral.id
    else:
        partner_referral_id = None

    data = {
        'action': 'partner_account_attribution',
        'description': description,
        'application_id': application.id,
        'partner_referral_id': partner_referral_id,
        'partner_name': application.partner.name,
    }
    logger.info(data)
    slack_client = SlackClient(settings.SLACK_WEB_API_TOKEN)
    slack_client.api_call(
        "chat.postMessage",
        channel=settings.SLACK_PARTNER_ATTRIBUTION,
        text="```%s```" % json.dumps(data, indent=2),
    )


def notify_payment_over_paid(payment, amount):
    if settings.ENVIRONMENT != 'prod':
        return
    if MAX_PAYMENT_OVER_PAID > amount:
        return
    loan = payment.loan
    data = {
        'action': 'payment_over_paid',
        'amount': display_rupiah(amount),
        'customer_id': loan.customer_id,
        'application_id': loan.application_id,
        'loan_id': loan.id,
        'payment_id': payment.id,
    }
    logger.info(data)
    slack_client = get_slack_client()
    slack_client.api_call(
        "chat.postMessage",
        channel=settings.SLACK_DEV_FINANCE,
        text="```%s```" % json.dumps(data, indent=2),
    )


def notify_application_status_info(attachment, text):
    slack_channel = "#status_info"
    if settings.ENVIRONMENT != 'prod':
        text += " <--" + settings.ENVIRONMENT
        slack_channel = "#status_info_test"
    slack_client = get_slack_client()
    intro_msg = json.dumps([{"text": attachment, "color": "#36a64f"}])
    logger.info(attachment)
    slack_client.api_call(
        "chat.postMessage", channel=slack_channel, text=text, attachments=intro_msg
    )


def notify_application_status_info_to_reporter(reporter, attachment, text):
    if settings.ENVIRONMENT != 'prod':
        text += " <--" + settings.ENVIRONMENT
    slack_client = SlackClient(settings.SLACK_WEB_API_TOKEN)
    intro_msg = json.dumps([{"text": attachment, "color": "#36a64f"}])
    logger.info(attachment)
    slack_client.api_call("chat.postMessage", channel=reporter, text=text, attachments=intro_msg)


def notify_cashback_abnormal(list):
    if settings.ENVIRONMENT != 'prod':
        return
    data = {
        'action': 'cashback_abnormal',
        'count': len(list),
        'list_customer_wallet_history': list,
    }
    logger.info(data)
    slack_client = SlackClient(settings.SLACK_WEB_API_TOKEN)
    slack_client.api_call(
        "chat.postMessage",
        channel=settings.SLACK_DEV_FINANCE,
        text="```%s```" % json.dumps(data, indent=2),
    )


def notify_failed_post_anaserver(notify_data):
    if settings.ENVIRONMENT != 'prod':
        return
    slack_channel = "#info-ana-fails"
    slack_client = SlackClient(settings.SLACK_WEB_API_TOKEN)
    slack_client.api_call(
        "chat.postMessage",
        channel=slack_channel,
        text="```%s```" % json.dumps(notify_data, indent=2),
    )


def send_message_normal_format(message, channel):
    slack_client = get_slack_client()
    slack_client.api_call("chat.postMessage", channel=channel, text=message)


def send_message_normal_format_to_users(message, users):
    slack_bot_client = get_slack_bot_client()
    for user in users:
        slack_bot_client.api_call("chat.postMessage", channel=user, text=message)


def notify_empty_bucket_sent_to_dialer_daily(attachment, improved=False):
    # parameter "improved" for flag this come from bucket used new function or not
    title = 'Empty buckets send to dialer'
    if improved:
        title = 'Unsent bucket to dialer'
    text = (
        "<@UKLTRUX1T> <@URLGD516U> <@UM3LBK3LY> <@U02DV0XPV5F> <@UUKCXG17S>\n"
        + "=== *%s* ===\n" % title
        + timezone.localtime(timezone.now()).strftime("*%A*, *%Y-%m-%d | %H:%M*")
    )
    slack_channel = "#intelix_notification"
    if settings.ENVIRONMENT != 'prod':
        text += " <--" + settings.ENVIRONMENT
        slack_channel = "#empty_bucket_sent_to_dialer_test"
        # todo : please comment again this line after testing done
        # return

    slack_client = get_slack_client()
    intro_msg = json.dumps([{"text": attachment, "color": "#36a64f"}])
    slack_client.api_call(
        "chat.postMessage", channel=slack_channel, text=text, attachments=intro_msg
    )


def notify_failed_manual_store_genesys_call_results(attachment):
    text = "=== *Failed manual upload genesys call results* ===\n" + timezone.localtime(
        timezone.now()
    ).strftime("*%A*, *%Y-%m-%d | %H:%M*")
    slack_channel = "#genesys_experiment"
    if settings.ENVIRONMENT != 'prod':
        text += " <--" + settings.ENVIRONMENT

    slack_client = get_slack_client()
    intro_msg = json.dumps([{"text": attachment, "color": "#36a64f"}])
    slack_client.api_call(
        "chat.postMessage", channel=slack_channel, text=text, attachments=intro_msg
    )


def notify_failed_hit_api_partner(
    partner_name='',
    url='',
    method='',
    headers='',
    body='',
    case='',
    response_status='',
    response_data='',
):
    message_to_slack = (
        "<!here> %s API Call Failed\n```URL: %s\nMETHOD: %s"
        "\nHEADERS: %s\nBODY: %s\nCASE: %s\nRESPONSE STATUS: %s\n"
        "RESPONSE DATA: %s```"
        % (partner_name, url, method, headers, body, case, response_status, response_data)
    )
    slack_bot_client = get_slack_bot_client()
    slack_bot_client.api_call(
        "chat.postMessage",
        channel=SLACK_CHANNEL_LEADGEN_WEBVIEW_NOTIF,
        text=message_to_slack,
    )


def notify_bulk_cancel_call_ai_rudder(message, title, attachment_message=None):
    # parameter "improved" for flag this come from bucket used new function or not
    if settings.ENVIRONMENT != 'prod':
        title = " <-- " + settings.ENVIRONMENT + " " + title

    text = (
        message
        + "\n=== *%s* ===\n" % title
        + timezone.localtime(timezone.now()).strftime("*%A*, *%Y-%m-%d | %H:%M*")
    )
    slack_channel = "#ai-rudder-cancel-call-bulk-results"
    slack_client = get_slack_client()
    if attachment_message:
        attachment_message = json.dumps([{"text": attachment_message, "color": "#36a64f"}])
    slack_client.api_call(
        "chat.postMessage", channel=slack_channel, text=text, attachments=attachment_message
    )


def slack_notify_and_send_csv_files(message, csv_path, channel, file_name):
    client = get_slack_bot_client()
    csv_file = open(csv_path, 'rb')
    client.api_call(
        'files.upload',
        channels=channel,
        filename=file_name,
        file=csv_file,
        initial_comment=message,
        headers="application/x-www-form-urlencoded",
    )
    csv_file.close()


# NOTE: This function is use by Dana Collection also
def notify_empty_bucket_daily_ai_rudder(
    attachment, improved=False, bucket_name=None, custom_title=None
):
    # parameter "improved" for flag this come from bucket used new function or not
    title = 'Empty buckets send to dialer'
    if improved:
        title = 'Unsent bucket to dialer'
    if custom_title:
        title = custom_title

    if bucket_name == DanaBucket.DANA_BUCKET_AIRUDDER:
        text = (
            # These are the personal slack Member ID
            "<!channel>\n"
            + "=== *%s* ===\n" % title
            + timezone.localtime(timezone.now()).strftime("*%A*, *%Y-%m-%d | %H:%M*")
        )
        slack_channel = "#dana_ai_rudder_notification"
        if settings.ENVIRONMENT != 'prod':
            text += " <--" + settings.ENVIRONMENT
            slack_channel = "#dana_ai_rudder_notification_sandbox"
    else:
        text = (
            "<@UKLTRUX1T> <@URLGD516U> <@UM3LBK3LY> <@UUKCXG17S> <@U02LJHC8EBW> <@U04DS20LFHA> <@U03TSPL42BZ>\n"
            + "=== *%s* ===\n" % title
            + timezone.localtime(timezone.now()).strftime("*%A*, *%Y-%m-%d | %H:%M*")
        )
        slack_channel = "#ai_rudder_notification"
        if settings.ENVIRONMENT != 'prod':
            text += " <--" + settings.ENVIRONMENT
            slack_channel = "#ai_rudder_notification_sandbox"

    slack_client = get_slack_client()
    intro_msg = json.dumps([{"text": attachment, "color": "#36a64f"}])
    slack_client.api_call(
        "chat.postMessage", channel=slack_channel, text=text, attachments=intro_msg
    )


def notify_dana_loan_stuck_211_payment_consult(total_dana_loan_stuck_211):
    title = "Dana Loan Stuck 211 Payment Consult"
    text = "=== *%s* ===\n" % title + timezone.localtime(timezone.now()).strftime(
        "*%A*, *%Y-%m-%d | %H:%M*"
    )
    attachment = "Please check, there is loan stuck on 211. \n Total Data = {}".format(
        total_dana_loan_stuck_211
    )
    slack_channel = "#dana_loan_stuck_211_payment_consult"
    if settings.ENVIRONMENT != 'prod':
        text += " <--" + settings.ENVIRONMENT
        slack_channel = "#dana_loan_stuck_211_payment_consult_sandbox"

    slack_client = get_slack_client()
    intro_msg = json.dumps([{
        "text": attachment,
        "color": "#36a64f"
    }])
    slack_client.api_call(
        "chat.postMessage",
        channel=slack_channel,
        text=text,
        attachments=intro_msg)


def notify_call_result_hourly_ai_rudder(attachment):
    title = "Call Result Fail to Conduct"
    text = (
        "<@UKLTRUX1T> <@U030G4EJGET> <@U80695ELX> <@UUKCXG17S> <@U03DZV3FQ8K> <@U02LJHC8EBW> \n"
        + "=== *%s* ===\n" % title
        + timezone.localtime(timezone.now()).strftime("*%A*, *%Y-%m-%d | %H:%M*")
    )
    slack_channel = "#ai_rudder_notification"
    if settings.ENVIRONMENT != 'prod':
        text += " <--" + settings.ENVIRONMENT
        slack_channel = "#ai_rudder_notification_sandbox"

    slack_client = get_slack_client()
    intro_msg = json.dumps([{"text": attachment, "color": "#36a64f"}])
    slack_client.api_call(
        "chat.postMessage", channel=slack_channel, text=text, attachments=intro_msg
    )


def notify_payment_failure_with_severity_alert(text_data, color, channel):
    logger.info(text_data)
    data = {
        "channel": channel,
        "attachments": [
            {
                "color": color,
                "text": text_data,
            }
        ]
    }
    logger.info(data)
    slack_client = SlackClient(settings.SLACK_WEB_API_TOKEN)
    slack_client.api_call(
        "chat.postMessage", **data
    )


def notify_dialer_discrepancies(attachment):
    title = "Dialer Data Discrepancies"
    text = (
        "<@U030G4EJGET> <@U02LJHC8EBW> <@UKLTRUX1T> <@U80695ELX> \n"
        + "=== *%s* ===\n" % title
        + timezone.localtime(timezone.now()).strftime("*%A*, *%Y-%m-%d | %H:%M*")
    )
    slack_channel = "#ai_rudder_notification"
    if settings.ENVIRONMENT != 'prod':
        text += " <--" + settings.ENVIRONMENT
        slack_channel = "#ai_rudder_notification_sandbox"

    slack_client = get_slack_client()
    intro_msg = json.dumps([{"text": attachment, "color": "#36a64f"}])
    slack_client.api_call(
        "chat.postMessage", channel=slack_channel, text=text, attachments=intro_msg
    )


def notify_cron_job_has_been_hit_more_than_once(task_name):
    title = 'Cron Job Hit More Than Once'

    text = (
        # These are the personal slack Member ID
        "<!channel>\n"
        + "=== *%s* ===\n" % title
        + timezone.localtime(timezone.now()).strftime("*%A*, *%Y-%m-%d | %H:%M*")
    )
    attachment = "This `{}` has been executed more than once".format(task_name)
    slack_channel = "#alerts_julopartnership"
    if settings.ENVIRONMENT != 'prod':
        text += " <--" + settings.ENVIRONMENT
        slack_channel = "#alerts_julopartnership_sandbox"

    slack_client = get_slack_client()
    intro_msg = json.dumps([{"text": attachment, "color": "#039BE5"}])
    slack_client.api_call(
        "chat.postMessage", channel=slack_channel, text=text, attachments=intro_msg
    )


def notify_max_3_platform_check_axiata_mtl(attachment, fullname=None, application_id=None):
    if attachment:
        title = 'Max 3 Platform Check'
        color = "#cc0000"
        text = (
            "<!subteam^S04KD0ZPQUF|ops-partnership-team>\n"
            + "=== *%s* ===\n" % title
            + timezone.localtime(timezone.now()).strftime("*%A*, *%Y-%m-%d | %H:%M*")
        )

    else:
        title = 'Application Creation'
        color = "#36a64f"
        text = "=== *%s* ===\n" % title + timezone.localtime(timezone.now()).strftime(
            "*%A*, *%Y-%m-%d | %H:%M*"
        )
        attachment = "SUCCESS loan creation for {}, application_id: {}".format(
            fullname, application_id
        )


def notify_max_3_platform_check_axiata(
    attachment, fullname=None, application_id=None, loan_id=None, is_axiata_bau=False
):
    text = ""
    color = ""

    if is_axiata_bau:
        if attachment:
            title = 'Max 3 Platform Check AXIATA BAU'
            color = "#cc0000"
            text = (
                "<!subteam^S04KD0ZPQUF|ops-partnership-team>\n"
                + "=== *%s* ===\n" % title
                + timezone.localtime(timezone.now()).strftime("*%A*, *%Y-%m-%d | %H:%M*")
            )
        elif loan_id:
            title = 'Loan Creation AXIATA BAU'
            color = "#2986cc"
            text = "=== *%s* ===\n" % title + timezone.localtime(timezone.now()).strftime(
                "*%A*, *%Y-%m-%d | %H:%M*"
            )
            attachment = "SUCCESS loan creation for {}, loan_id: {}".format(fullname, loan_id)

    else:
        if attachment:
            title = 'Max 3 Platform Check'
            color = "#cc0000"
            text = (
                "<!subteam^S04KD0ZPQUF|ops-partnership-team>\n"
                + "=== *%s* ===\n" % title
                + timezone.localtime(timezone.now()).strftime("*%A*, *%Y-%m-%d | %H:%M*")
            )
        else:
            title = 'Application Creation'
            color = "#36a64f"
            text = "=== *%s* ===\n" % title + timezone.localtime(timezone.now()).strftime(
                "*%A*, *%Y-%m-%d | %H:%M*"
            )
            attachment = "SUCCESS loan creation for {}, application_id: {}".format(
                fullname, application_id
            )

    slack_channel = "#axiata_max_3_check"
    if settings.ENVIRONMENT != 'prod':
        text += " <--" + settings.ENVIRONMENT
        slack_channel = "#axiata_max_3_check_sandbox"
    slack_client = get_slack_client()
    intro_msg = json.dumps([{"text": attachment, "color": color}])
    slack_client.api_call(
        "chat.postMessage", channel=slack_channel, text=text, attachments=intro_msg
    )


def notify_dana_collection_each_process(task_name, total_data=None):
    title = 'Dana Collection Process Tracking'

    text = "=== *%s* ===\n" % title + timezone.localtime(timezone.now()).strftime(
        "*%A*, *%Y-%m-%d | %H:%M*"
    )
    attachment = ("This `{}` has been FINISHED " "with total data = {} :rocket:").format(
        task_name, total_data
    )
    slack_channel = "#process-tracking-dana-collection"
    if settings.ENVIRONMENT != 'prod':
        text += " <--" + settings.ENVIRONMENT
        slack_channel = "#process-tracking-dana-collection-sandbox"

    slack_client = get_slack_client()
    intro_msg = json.dumps([{"text": attachment, "color": "#69e503"}])
    slack_client.api_call(
        "chat.postMessage", channel=slack_channel, text=text, attachments=intro_msg
    )


def notify_fail_exclude_account_ids_collection_field_ai_rudder(attachment):
    title = "We Got Possibility Double Handle Due"
    text = (
        "<@U06PFJ1P1H9> <@U03TSPL42BZ> <@U05PWH9NZ8V> <@UKLTRUX1T> <@U06QW6Y6ZC4> <@U01VD8H96HW> <@U087BM75J6T> \n"
        + "=== *%s* ===\n" % title
        + timezone.localtime(timezone.now()).strftime("*%A*, *%Y-%m-%d | %H:%M*")
    )
    slack_channel = "#ai_rudder_notification"
    if settings.ENVIRONMENT != 'prod':
        text += " <--" + settings.ENVIRONMENT
        slack_channel = "#ai_rudder_notification_sandbox"

    slack_client = get_slack_client()
    intro_msg = json.dumps([{"text": attachment, "color": "#ff0000"}])
    slack_client.api_call(
        "chat.postMessage", channel=slack_channel, text=text, attachments=intro_msg
    )


def notify_status_pwl_delivery_data_upload(flag, error_msg=None):
    if flag == True:
        if error_msg:
            error_msg = "\nbut some rows not uploaded due to below errors\n{}".format(error_msg)
        message_to_slack = (
            "<!here>"
            "\nHEADERS: PWL DELIVERY DETAILS"
            "\nBODY: PWL delivery details added "
            "successfully in {} env {}".format(settings.ENVIRONMENT, error_msg)
        )
    else:
        message_to_slack = (
            "<!here>"
            "\nHEADERS: PWL DELIVERY DETAILS"
            "\nBODY: PWL delivery details upload failed in "
            "{} env\nreason:-\n{}".format(settings.ENVIRONMENT, error_msg)
        )
    slack_bot_client = get_slack_bot_client()
    slack_bot_client.api_call(
        "chat.postMessage",
        channel=SLACK_CHANNEL_WL_NOTIF,
        text=message_to_slack,
    )


def notify_partnership_insufficient_lender_balance(loan_id, lender_id):
    title = 'Partnership Insufficient Lender Balance'

    text = (
        "<!channel>\n"
        + "=== *%s* ===\n" % title
        + timezone.localtime(timezone.now()).strftime("*%A*, *%Y-%m-%d | %H:%M*")
    )
    attachment = "Lender Balance for lender_id `{}` is not sufficient for loan_id `{}`".format(
        lender_id, loan_id
    )
    slack_channel = "#alerts_partnership_insufficient_lender_balance"
    if settings.ENVIRONMENT != 'prod':
        text += " <--" + settings.ENVIRONMENT
        slack_channel = "#alerts_partnership_insufficient_lender_balance_sandbox"

    slack_client = get_slack_client()
    intro_msg = json.dumps([{"text": attachment, "color": "#039BE5"}])
    slack_client.api_call(
        "chat.postMessage", channel=slack_channel, text=text, attachments=intro_msg
    )
