from builtins import str
import json
import logging
import socket
from typing import Tuple

import requests
from django.template.loader import render_to_string
from datetime import timedelta
from babel.numbers import format_number
from babel.dates import format_date
from django.utils import timezone

from juloserver.julo.clients.infobip import JuloInfobipClient
from ..statuses import ApplicationStatusCodes
from ...julo.utils import display_rupiah
from ...julo.utils import format_e164_indo_phone_number
from ...julo.product_lines import ProductLineCodes
from juloserver.julo.exceptions import SmsNotSent
from ...julo.services2.reminders import Reminder
from . import get_julo_sentry_client
from django.conf import settings
from ...julo.services2 import encrypt
from juloserver.urlshortener.services import shorten_url
from juloserver.urlshortener.models import ShortenedUrl
from ..exceptions import JuloException
from juloserver.julo.models import (
    ExperimentSetting,
    FeatureSetting,
    SmsHistory,
    CommsProviderLookup,
)
from juloserver.julo.constants import (
    ExperimentConst,
    FeatureNameConst,
    VendorConst,
    ReminderTypeConst,
    URL_CARA_BAYAR,
)
from juloserver.julo.clients.constants import SMSPurpose
from juloserver.streamlined_communication.constant import (
    CommunicationPlatform,
    SmsTspVendorConstants,
    Product
)
from juloserver.streamlined_communication.services import process_streamlined_comm
from juloserver.promo_campaign.clients import PromoSmsClient
from juloserver.loan_refinancing.clients.sms import LoanRefinancingSmsClient
from juloserver.julo.services2.sms import create_sms_history

from juloserver.streamlined_communication.utils import (
    get_telco_code_and_tsp_name,
    get_tsp_config,
    get_comms_provider_name
)
from juloserver.streamlined_communication.models import (
    StreamlinedCommunication,
    StreamlinedMessage,
    SmsVendorRequest,
)
from juloserver.streamlined_communication.services import process_partner_sms_message
logger = logging.getLogger(__name__)
INFO_TITLE = "JULO Info"
REMINDER_TITLE = "JULO Reminder"
ALERT_TITLE = "JULO Alert"
MTL = (ProductLineCodes.MTL1, ProductLineCodes.MTL2)
STL = (ProductLineCodes.STL1, ProductLineCodes.STL2)
PEDEMTL = (ProductLineCodes.PEDEMTL1, ProductLineCodes.PEDEMTL2)
PEDESTL = (ProductLineCodes.PEDESTL1, ProductLineCodes.PEDESTL2)
LAKU6 = (ProductLineCodes.LAKU1, ProductLineCodes.LAKU2)
sentry_client = get_julo_sentry_client()
COMMUNICATION_PLATFORM = CommunicationPlatform.SMS


class JuloSmsClient(PromoSmsClient, LoanRefinancingSmsClient, object):

    def __init__(self, source='JULO'):
        self.source = source

    def send_sms_monty(self, phone_number, message, is_otp=False):
        """
        send message with monty
        """
        active_feature = FeatureSetting.objects.get_or_none(
            feature_name=FeatureNameConst.MONTY_SMS, is_active=True)
        if not active_feature:
            raise JuloException("Monty SMS Deactivated")

        uname = settings.MONTY_NON_OTP_API_USERNAME
        pwd = settings.MONTY_NON_OTP_API_PASSWORD
        url = settings.MONTY_API_URL

        if is_otp:
            uname = settings.MONTY_API_USERNAME
            pwd = settings.MONTY_API_PASSWORD

        if phone_number[:1] == '+':
            phone_number = phone_number[1:]
        params = {
            'username': uname,
            'password': pwd,
            'destination': phone_number,
            'source': self.source,
            'text': message
        }

        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/x-www-form-urlencoded'
        }

        safe_params = params.copy()
        safe_params['username'] = safe_params['username'][-2:]
        safe_params['password'] = safe_params['password'][-2:]
        logger.info({
            'action': 'sending_sms_via_monty',
            'url': url,
            'params': safe_params,
            'headers': headers
        })
        try:
            response = requests.get(url, headers=headers, params=params)
        except Exception as e:
            sentry_client.captureException()
            raise SmsNotSent('failed to send sms (via monty) to number ' + phone_number + ': ' + str(e))

        api_response = json.loads(response.content)
        SmsVendorRequest.objects.create(
            vendor_identifier=api_response['SMS'][0]['Id'],
            phone_number=api_response['SMS'][0]['DestinationAddress'],
            comms_provider_lookup_id=CommsProviderLookup.objects.get(
                provider_name=VendorConst.MONTY.capitalize()
            ).id,
            payload=api_response,
        )
        # We need to renamed monty response to be like nexmo,
        # This prevent us to changed our behaviour to call the sms client and saving sms history
        renamed_response = {'messages': [
            {
                'status': str(api_response['SMS'][0]['ErrorCode']),
                'to': api_response['SMS'][0]['DestinationAddress'],
                'message-id': api_response['SMS'][0]['Id']

            }
        ]}
        renamed_response['messages'][0]['julo_sms_vendor'] = VendorConst.MONTY
        renamed_response['messages'][0]['is_otp'] = is_otp
        logger.info({
            'status': "sms_sent (via monty)",
            'api_response': api_response
        })

        return message, renamed_response

    def send_sms_nexmo(self, phone_number, message, is_paylater=False, is_otp=False):
        """
        send message with nexmo
        """
        sms_key = settings.NEXMO_NON_OTP_API_KEY
        sms_secret = settings.NEXMO_NON_OTP_API_SECRET
        url = settings.NEXMO_SMS_URL
        callback_url = settings.NEXMO_CALLBACK
        if is_otp:
            sms_key = settings.NEXMO_API_KEY
            sms_secret = settings.NEXMO_API_SECRET
        if is_paylater:
            sms_key = settings.NEXMO_API_BL_KEY
            sms_secret = settings.NEXMO_API_BL_SECRET

        params = {
            'api_key': sms_key,
            'api_secret': sms_secret,
            'to': phone_number,
            'from': self.source,
            'text': message,
            'callback': callback_url,
        }

        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/x-www-form-urlencoded'
        }

        # This is so that our API credentials are not entirely logged,
        # only the last 2 chars for debugging
        safe_params = params.copy()
        safe_params['api_key'] = safe_params['api_key'][-2:]
        safe_params['api_secret'] = safe_params['api_secret'][-2:]
        logger.info({
            'action': 'sending_sms_via_nexmo',
            'url': url,
            'params': safe_params,
            'headers': headers
        })
        try:
            response = requests.post(url, headers=headers, params=params)
        except Exception as e:
            sentry_client.captureException()
            raise SmsNotSent('failed to send sms (via nexmo) to number ' + phone_number + ': ' + str(e))

        api_response = json.loads(response.content)
        SmsVendorRequest.objects.create(
            vendor_identifier=api_response['messages'][0]['message-id'],
            phone_number=api_response['messages'][0]['to'],
            comms_provider_lookup_id=CommsProviderLookup.objects.get(
                provider_name=VendorConst.NEXMO.capitalize()
            ).id,
            payload=api_response,
        )
        api_response['messages'][0]['julo_sms_vendor'] = VendorConst.NEXMO
        api_response['messages'][0]['is_otp'] = is_otp
        logger.info({
            'status': "sms_sent (via nexmo)",
            'api_response': api_response
        })

        return message, api_response

    def send_sms_infobip_primary(self, phone_number: str, message: str, is_otp: bool = False) -> Tuple[str, dict]:
        """
        Handle sending sms using Infobip as primary and Nexmo (Vonage) as backup.

        Args:
            phone_number (str): Phone number to send sms.
            message (str): Message to send.
            is_otp (bool): To differentiate the infobip account used.

        Returns:
            str: Message string.
            dict: Restructured response from Infobip / Nexmo (Vonage).
        """
        try:
            infobip_client = JuloInfobipClient(is_otp=is_otp)
            msg, response = infobip_client.send_sms(phone_number, message)

            response['messages'][0]['julo_sms_vendor'] = VendorConst.INFOBIP
        except Exception as e:
            logger.info({
                'status': 'Infobip fails: retrying send via Nexmo',
                'message': e
            })

            msg, response = self.send_sms_nexmo(phone_number, message)

        return msg, response

    def send_sms_alicloud_primary(self, phone_number: str, message: str, is_otp: bool = False) -> Tuple[str, dict]:
        """
        Handle sending sms using Alicloud as primary and Nexmo (Vonage) as backup.

        Args:
            phone_number (str): Phone number to send sms.
            message (str): Message to send.

        Returns:
            str: Message string.
            dict: Restructured response from Alicloud / Nexmo (Vonage).
        """
        # Import in function to avoid Alicloud SDK breaking unit tests.
        from juloserver.julo.clients.alicloud import JuloAlicloudClient
        try:
            alicloud_client = JuloAlicloudClient(is_otp=is_otp)
            msg, response = alicloud_client.send_sms(phone_number, message)

            response['messages'][0]['julo_sms_vendor'] = VendorConst.ALICLOUD
        except Exception as e:
            logger.info({
                'status': 'Alicloud fails: retrying send via Nexmo',
                'message': e
            })

            msg, response = self.send_sms_nexmo(phone_number, message)

        return msg, response

    def send_sms(self, phone_number, message, is_otp=False):
        """
        Handle sending sms based on is_otp which defines whether the message is considered OTP or not.

        Args:
            phone_number (str): Phone number to send sms.
            message (str): Message to send.
            is_otp (bool) : Define whether the message is considered OTP or not

        Returns:
            msg (str): Message string.
            response (dict): Restructured response from one of the vendors (Alicloud, Nexmo, Monty, Infobip).
        """
        msg, response = self.send_sms_dynamic(phone_number, message, is_otp)

        return msg, response

    def send_sms_otp(self, phone_number, message):
        """

        Handle sending OTP sms using Monty as primary and Nexmo (Vonage) as backup.

        Args:
            phone_number (str): Phone number to send sms.
            message (str): Message to send.

        Returns:
            str: Message string.
            dict: Restructured response from Alicloud / Nexmo (Vonage).

        TODO:
            Rename to send_sms_monty_primary.
        """
        try:
            msg, response = self.send_sms_monty(phone_number, message, is_otp=True)
            response['messages'][0]['julo_sms_vendor'] = VendorConst.MONTY
            response['messages'][0]['is_otp'] = True
            if response['messages'][0]['status'] != '0':
                raise JuloException('SMS send failed|response={}'.format(response))
            return msg, response

        except Exception as e:
            logger.info({
                'status': 'monty fails: retrying send via nexmo',
                'message': e
            })

            msg, response = self.send_sms_nexmo(phone_number, message, is_otp=True)
            return msg, response

    def send_sms_dynamic(self, phone_number, message, is_otp):
        """
        Handle sending SMS dynamically with primary and backup vendor based on
        telco service provider config from the table SmsTspVendorConfig.

        Args:
            phone_number (str): Phone number to send sms.
            message (str): Message to send.
            is_otp (bool): Boolean value indicating the type of sms OTP/non-OTP

        Returns:
            str: Message string.
            dict: Restructured response from  one of the vendors (Alicloud, Nexmo, Monty, Infobip).

        """
        primary_vendor = None
        backup_vendor = None
        julo_sms_vendor = None
        try:
            telco_code, tsp_provider_name = get_telco_code_and_tsp_name(phone_number)
            primary_vendor, backup_vendor = get_tsp_config(tsp_provider_name, is_otp)
            msg, response = self.trigger_sms_vendor_function(primary_vendor, phone_number, message, is_otp)
            julo_sms_vendor = SmsTspVendorConstants.VENDOR_NAME_MAP[primary_vendor]
            response['messages'][0]['julo_sms_vendor'] = julo_sms_vendor
            response['messages'][0]['is_otp'] = is_otp
            if julo_sms_vendor == VendorConst.MONTY and response['messages'][0]['status'] != '0':
                raise JuloException('SMS send failed|response={}'.format(response))
            return msg, response

        except Exception as e:
            sentry_client.captureException()
            logger.exception({
                'status': '{0} fails: retrying send via {1}'.format(
                    get_comms_provider_name(primary_vendor),
                    get_comms_provider_name(backup_vendor)),
                'message': e
            })

            msg, response = self.trigger_sms_vendor_function(backup_vendor, phone_number, message, is_otp)
            julo_sms_vendor = SmsTspVendorConstants.VENDOR_NAME_MAP[backup_vendor]
            response['messages'][0]['julo_sms_vendor'] = julo_sms_vendor
            response['messages'][0]['is_otp'] = is_otp
            if julo_sms_vendor == VendorConst.MONTY and response['messages'][0]['status'] != '0':
                raise JuloException('SMS send failed with backup vendor|response={}'.format(response))
            return msg, response

    def send_sms_infobip(self, phone_number: str, message: str, is_otp: bool = False) -> Tuple[str, dict]:
        """
        Handle sending sms using Infobip.

        Args:
            phone_number (str): Phone number to send sms.
            message (str): Message to send.
            is_otp (bool): To differentiate the infobip account used.

        Returns:
            str: Message string.
            dict: Restructured response from Infobip.
        """
        infobip_client = JuloInfobipClient(is_otp=is_otp)
        msg, response = infobip_client.send_sms(phone_number, message)

        response['messages'][0]['julo_sms_vendor'] = VendorConst.INFOBIP

        return msg, response

    def send_sms_alicloud(self, phone_number: str, message: str, is_otp: bool = False) -> Tuple[str, dict]:
        """
        Handle sending sms using Alicloud .

        Args:
.            phone_number (str): Phone number to send sms.
            message (str): Message to send.

        Returns:
            str: Message string.
            dict: Restructured response from Alicloud.
        """
        # Import in function to avoid Alicloud SDK breaking unit tests.
        from juloserver.julo.clients.alicloud import JuloAlicloudClient
        alicloud_client = JuloAlicloudClient(is_otp=is_otp)
        msg, response = alicloud_client.send_sms(phone_number, message)

        response['messages'][0]['julo_sms_vendor'] = VendorConst.ALICLOUD

        return msg, response

    def send_sms_experiment(
        self, phone_number: str, message: str, unique_id_last_digit: int, is_otp=False,
    ) -> Tuple[str, dict]:
        """
        Central point for handling sms vendor experiment.

        Args:
            phone_number (str): Phone number to send sms.
            message (str): Message to send.
            unique_id_last_digit (int): last digit of account_id for Non OTP and cutomer_id for OTP will be used
            is_otp (bool): To depict if the experiment is for otp/non-otp sms.

        Returns:
            str: Message string.
            dict: Restructured response from Alicloud / Nexmo (Vonage).

        TODO:
            To be primary function to replace send_sms after finalize vendor choice for SMS.
        """
        if is_otp:
            experiment_code = ExperimentConst.PRIMARY_OTP_SMS_VENDORS_EXPERIMENT
        else:
            experiment_code = ExperimentConst.PRIMARY_SMS_VENDORS_EXPERIMENT
        ab_experiment_setting = ExperimentSetting.objects.get(
            code=experiment_code)
        today = timezone.localtime(timezone.now())
        criteria = ab_experiment_setting.criteria
        if (ab_experiment_setting.is_active
             and ab_experiment_setting.start_date <= today <= ab_experiment_setting.end_date):
            if unique_id_last_digit in criteria['monty']:
                text_message, response = self.send_sms(
                    phone_number=format_e164_indo_phone_number(phone_number),
                    message=message, is_otp=is_otp
                )
            elif unique_id_last_digit in criteria['infobip']:
                text_message, response = self.send_sms_infobip_primary(
                    phone_number=format_e164_indo_phone_number(phone_number),
                    message=message,
                    is_otp=is_otp,
                )
            else:
                text_message, response = self.send_sms_alicloud_primary(
                    phone_number=format_e164_indo_phone_number(phone_number),
                    message=message,
                    is_otp=is_otp,
                )
        else:
            text_message, response = self.send_sms(
                phone_number=format_e164_indo_phone_number(phone_number),
                message=message, is_otp=is_otp
            )
        response['messages'][0]['is_otp'] = is_otp
        return text_message, response

#######################################################################
# APPLICATION
#######################################################################
    def sms_legal_document_resubmission(self, application, change_reason):
        """
        send sms notification for application status 162
        """
        template = 'sms_application_162'
        reasons = change_reason.split(",")
        reasons_list = []
        text_reason = ''
        for c_reason in reasons:
            if "-" in c_reason:
                reason = c_reason.split("-")
                reasons_list.append(reason[1])
        text_reason = (', ').join(reasons_list)

        context = {
            'fullname': application.fullname_with_title,
            'status_change_reason': text_reason
        }
        filter_ = dict(
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template,
            status_code=ApplicationStatusCodes.LEGAL_AGREEMENT_RESUBMISSION_REQUESTED
        )
        msg = process_streamlined_comm(filter_, replaced_data=context)
        logger.info({
            'action': 'sending_sms_legal_document_resubmission',
            'application_id': application.id,
            'message': msg,
            'template': template
        })

        text_message, response = self.send_sms(
            phone_number=format_e164_indo_phone_number(application.mobile_phone_1),
            message=msg,
        )

        return text_message, response['messages'][0], template


#######################################################################
# PAYMENT REMINDES
#######################################################################
    def sms_payment_due_today(self, payment):
        """
        send sms reminder for payment with due date today
        """
        template = self.get_sms_templates(payment.loan.application.product_line.product_line_code,
                                          payment.ptp_date, 0, None)

        if not template:
            logger.info({
                'action': 'sending_sms_payment_due_today_template_not_found',
                'payment_id': payment.id,
                'loan_id': payment.loan.id
            })
            return

        payment_number = payment.payment_number
        due_amount = payment.due_amount
        bank_name = payment.loan.julo_bank_name
        account_number = payment.loan.julo_bank_account_number
        sms_name = payment.loan.application.first_name_with_title_short
        payment_cashback_amount = (0.01 / payment.loan.loan_duration) * payment.loan.loan_amount
        due_date = format_date(payment.notification_due_date, 'dd-MMM', locale='id_ID')
        context = {
            'payment_number': payment_number,
            'due_amount': display_rupiah(due_amount),
            'due_date': due_date,
            'bank_name': bank_name,
            'account_number': account_number,
            'first_name_with_title_sms': sms_name,
            'payment_cashback_amount': display_rupiah(int(payment_cashback_amount)),
            'how_pay_url': URL_CARA_BAYAR,
            }
        filter_ = dict(
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template
        )
        msg = process_streamlined_comm(filter_, replaced_data=context)
        # msg = render_to_string(template + '.txt', context=context)
        logger.info({
            'action': 'sending_sms_payment_due_today',
            'payment_id': payment.id,
            'loan_id': payment.loan.id,
            'template': template
        })

        text_message, response = self.send_sms(
            phone_number=format_e164_indo_phone_number(payment.loan.application.mobile_phone_1),
            message=msg,
        )

        reminder = Reminder()
        reminder.create_reminder_history(payment, None, template, response['messages'][0]['julo_sms_vendor'],
                                         ReminderTypeConst.SMS_TYPE_REMINDER)

        return text_message, response['messages'][0], template

    def sms_payment_due_in2(self, payment):
        """
        send sms reminder for payment with due date in 2 days
        """
        template = self.get_sms_templates(payment.loan.application.product_line.product_line_code,
                                          payment.ptp_date, -2, None)

        if not template:
            logger.info({
                'action': 'sending_sms_payment_due_in2_template_not_found',
                'payment_id': payment.id,
                'loan_id': payment.loan.id
            })
            return

        payment_number = payment.payment_number
        due_amount = payment.due_amount
        due_date = str(payment.notification_due_date.day) + '/' + str(payment.notification_due_date.month)
        due_date_minus_2 = payment.notification_due_date - timedelta(days=2)
        bank_name = payment.loan.julo_bank_name
        account_number = payment.loan.julo_bank_account_number
        sms_name = payment.loan.application.first_name_with_title_short
        payment_cashback_amount = (0.02 / payment.loan.loan_duration) * payment.loan.loan_amount
        encrypttext = encrypt()
        encoded_payment_id = encrypttext.encode_string(str(payment.id))
        url = settings.PAYMENT_DETAILS + str(encoded_payment_id)
        shortened_url = shorten_url(url)
        due_date = format_date(payment.notification_due_date, 'dd-MMM', locale='id_ID')
        context = {
            'payment_number': payment_number,
            'due_amount': display_rupiah(due_amount),
            'due_date': due_date,
            'bank_name': bank_name,
            'account_number': account_number,
            'first_name_with_title_sms': sms_name,
            'due_date_minus_2': str(due_date_minus_2.day) + '/' + str(due_date_minus_2.month),
            'cashback_multiplier': payment.cashback_multiplier,
            'payment_cashback_amount': display_rupiah(int(payment_cashback_amount)),
            'payment_details_url': shortened_url,
        }
        filter_ = dict(
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template
        )
        msg = process_streamlined_comm(filter_, replaced_data=context)
        # msg = render_to_string(template + '.txt', context)
        logger.info({
            'action': 'sending_sms_payment_due_in_2_days',
            'payment_id': payment.id,
            'loan_id': payment.loan.id,
            'template': template
        })

        text_message, response = self.send_sms(
            phone_number=format_e164_indo_phone_number(payment.loan.application.mobile_phone_1),
            message=msg,
        )

        reminder = Reminder()
        reminder.create_reminder_history(payment, None, template, response['messages'][0]['julo_sms_vendor'],
                                         ReminderTypeConst.SMS_TYPE_REMINDER)

        return text_message, response['messages'][0], template

    def sms_payment_due_in7(self, payment):
        """
        This method is to send SMS to all customers that payment is due to 7 days to remind
        them of the cashback for payment that is paid minimum 4 days from due date.

        """
        due_date_in_4_days =  payment.due_date - timedelta(days=4)
        template = self.get_sms_templates(payment.loan.application.product_line.product_line_code,
                                          payment.ptp_date, -7, None)

        if not template:
            logger.info({
                'action': 'sending_sms_payment_due_in7_template_not_found',
                'payment_id': payment.id,
                'loan_id': payment.loan.id
            })
            return

        sms_name = payment.loan.application.first_name_with_title_short
        payment_cashback_amount = (0.03 / payment.loan.loan_duration) * payment.loan.loan_amount
        encrypttext = encrypt()
        encoded_payment_id = encrypttext.encode_string(str(payment.id))
        url = settings.PAYMENT_DETAILS + str(encoded_payment_id)
        shortened_url = shorten_url(url)
        due_date_in_4_days = format_date(due_date_in_4_days, 'dd-MMM', locale='id_ID')
        context = {
            'first_name_with_title_sms': sms_name,
            'due_date_minus_4': str(due_date_in_4_days),
            'payment_cashback_amount': display_rupiah(int(payment_cashback_amount)),
            'payment_details_url': shortened_url
        }
        filter_ = dict(
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template
        )
        msg = process_streamlined_comm(filter_, replaced_data=context)
        logger.info({
            'action': 'sending_sms_payment_due_in_7_days',
            'payment_id': payment.id,
            'loan_id': payment.loan.id,
            'template': template
        })
        text_message, response = self.send_sms(
            phone_number=format_e164_indo_phone_number(payment.loan.application.mobile_phone_1),
            message=msg,
        )

        reminder = Reminder()
        reminder.create_reminder_history(payment, None, template, response['messages'][0]['julo_sms_vendor'],
                                         ReminderTypeConst.SMS_TYPE_REMINDER)

        return text_message, response['messages'][0], template


    def sms_payment_due_in4(self, payment):
        """
        send sms reminder for payment with due date in 4 days
        """
        if payment.ptp_date:
            template = 'sms_ptp_-2_4'
        else:
            if payment.loan.application.product_line.product_line_code in MTL:
                template = 'sms_dpd_-4'
            elif payment.loan.application.product_line.product_line_code in STL:
                template = 'stl_sms_dpd_-4'

        payment_number = payment.payment_number
        due_amount = payment.due_amount
        due_date = str(payment.notification_due_date.day) + '/' + str(payment.notification_due_date.month)
        due_date_minus_4 = payment.notification_due_date - timedelta(days=4)
        bank_name = payment.loan.julo_bank_name
        account_number = payment.loan.julo_bank_account_number
        sms_name = payment.loan.application.first_name_with_title
        payment_cashback_amount = (0.03 / payment.loan.loan_duration) * payment.loan.loan_amount
        encrypttext = encrypt()
        encoded_payment_id = encrypttext.encode_string(str(payment.id))
        url = settings.PAYMENT_DETAILS + str(encoded_payment_id)
        shortened_url = shorten_url(url)

        context = {
            'payment_number': payment_number,
            'due_amount': display_rupiah(due_amount),
            'due_date': due_date,
            'bank_name': bank_name,
            'account_number': account_number,
            'name': sms_name,
            'due_date_minus_4': str(due_date_minus_4.day) + '/' + str(due_date_minus_4.month),
            'cashback_multiplier': payment.cashback_multiplier,
            'payment_cashback_amount': display_rupiah(int(payment_cashback_amount)),

            'url':shortened_url,
        }
        msg = render_to_string(template + '.txt', context)

        logger.info({
            'action': 'sending_sms_payment_due_in_4_days',
            'payment_id': payment.id,
            'loan_id': payment.loan.id,
            'template': template
        })

        text_message, response = self.send_sms(
            phone_number=format_e164_indo_phone_number(payment.loan.application.mobile_phone_1),
            message=msg,
        )
        return text_message, response['messages'][0], template

    def sms_payment_dpd_1(self, payment):
        """
        send sms reminder for payment with due date late 1 day
        """
        template = self.get_sms_templates(payment.loan.application.product_line.product_line_code,
                                          payment.ptp_date, 1, None)
        payment_number = payment.payment_number
        due_amount = payment.due_amount
        due_date = str(payment.notification_due_date.day) + '/' + str(payment.notification_due_date.month)
        bank_name = payment.loan.julo_bank_name
        account_number = payment.loan.julo_bank_account_number
        sms_name = payment.loan.application.first_name_with_title_short
        due_date = format_date(payment.notification_due_date, 'dd-MMM', locale='id_ID')

        context = {
            'payment_number': payment_number,
            'due_amount': display_rupiah(due_amount),
            'due_date': due_date,
            'bank_name': bank_name,
            'account_number': account_number,
            'first_name_with_title_sms': sms_name
        }
        filter_ = dict(
            dpd=1,
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template
        )
        msg = process_streamlined_comm(filter_, replaced_data=context)
        # msg = render_to_string(template + '.txt', context)
        logger.info({
            'action': 'sending_sms_payment_dpd_1',
            'payment_id': payment.id,
            'loan_id': payment.loan.id,
            'template': template
        })

        text_message, response = self.send_sms(
            phone_number=format_e164_indo_phone_number(payment.loan.application.mobile_phone_1),
            message=msg,
        )

        reminder = Reminder()
        reminder.create_reminder_history(payment, None, template, response['messages'][0]['julo_sms_vendor'],
                                         ReminderTypeConst.SMS_TYPE_REMINDER)

        return text_message, response['messages'][0], template

    def sms_payment_dpd_3(self, payment):
        """
        send sms reminder for payment with due date late 3 day
        """
        template = self.get_sms_templates(payment.loan.application.product_line.product_line_code,
                                          payment.ptp_date, 3, None)
        payment_number = payment.payment_number
        due_amount = payment.due_amount
        due_date = str(payment.notification_due_date.day) + '/' + str(payment.notification_due_date.month)
        bank_name = payment.loan.julo_bank_name
        account_number = payment.loan.julo_bank_account_number
        sms_name = payment.loan.application.first_name_with_title_short
        due_date = format_date(payment.notification_due_date, 'dd-MMM', locale='id_ID')

        context = {
            'payment_number': payment_number,
            'due_amount': display_rupiah(due_amount),
            'due_date': due_date,
            'bank_name': bank_name,
            'account_number': account_number,
            'first_name_with_title_sms': sms_name
        }
        # msg = render_to_string(template + '.txt', context)
        filter_ = dict(
            dpd=3,
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template
        )
        msg = process_streamlined_comm(filter_, replaced_data=context)
        logger.info({
            'action': 'sending_sms_payment_dpd_1',
            'payment_id': payment.id,
            'loan_id': payment.loan.id,
            'template': template
        })
        text_message, response = self.send_sms(
            phone_number=format_e164_indo_phone_number(payment.loan.application.mobile_phone_1),
            message=msg,
        )

        reminder = Reminder()
        reminder.create_reminder_history(payment, None, template, response['messages'][0]['julo_sms_vendor'],
                                         ReminderTypeConst.SMS_TYPE_REMINDER)

        return text_message, response['messages'][0], template

    def sms_payment_dpd_5(self, payment):
        """
        send sms reminder for payment with due date late 5 day
        """
        template = self.get_sms_templates(payment.loan.application.product_line.product_line_code,
                                          payment.ptp_date, 5, None)
        payment_number = payment.payment_number
        due_amount = payment.due_amount
        due_date = str(payment.notification_due_date.day) + '/' + str(payment.notification_due_date.month)
        bank_name = payment.loan.julo_bank_name
        account_number = payment.loan.julo_bank_account_number
        sms_name = payment.loan.application.first_name_with_title_short
        due_date = format_date(payment.notification_due_date, 'dd-MMM', locale='id_ID')
        context = {
            'payment_number': payment_number,
            'due_amount': display_rupiah(due_amount),
            'due_date': due_date,
            'bank_name': bank_name,
            'account_number': account_number,
            'first_name_with_title_sms': sms_name
        }
        # msg = render_to_string(template + '.txt', context)
        filter_ = dict(
            dpd=5,
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template
        )
        msg = process_streamlined_comm(filter_, replaced_data=context)
        logger.info({
            'action': 'sending_sms_payment_dpd_5',
            'payment_id': payment.id,
            'loan_id': payment.loan.id,
            'template': template
        })

        text_message, response = self.send_sms(
            phone_number=format_e164_indo_phone_number(payment.loan.application.mobile_phone_1),
            message=msg,
        )

        reminder = Reminder()
        reminder.create_reminder_history(payment, None, template, response['messages'][0]['julo_sms_vendor'],
                                         ReminderTypeConst.SMS_TYPE_REMINDER)

        return text_message, response['messages'][0], template

    def sms_payment_dpd_7(self, payment):
        """
        send sms reminder for payment with due date late 7 day
        """
        template = self.get_sms_templates(payment.loan.application.product_line.product_line_code,
                                          payment.ptp_date, 7, None)
        payment_number = payment.payment_number
        due_amount = payment.due_amount
        due_date = str(payment.notification_due_date.day) + '/' + str(payment.notification_due_date.month)
        bank_name = payment.loan.julo_bank_name
        account_number = payment.loan.julo_bank_account_number
        sms_name = payment.loan.application.first_name_with_title_short
        due_date = format_date(payment.notification_due_date, 'dd-MMM', locale='id_ID')
        context = {
            'payment_number': payment_number,
            'due_amount': display_rupiah(due_amount),
            'due_date': due_date,
            'bank_name': bank_name,
            'account_number': account_number,
            'first_name_with_title_sms': sms_name
        }
        # msg = render_to_string(template + '.txt', context)
        filter_ = dict(
            dpd=7,
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template
        )
        msg = process_streamlined_comm(filter_, replaced_data=context)
        logger.info({
            'action': 'sending_sms_payment_dpd_7',
            'payment_id': payment.id,
            'loan_id': payment.loan.id,
            'template': template
        })

        text_message, response = self.send_sms(
            phone_number=format_e164_indo_phone_number(payment.loan.application.mobile_phone_1),
            message=msg,
        )

        reminder = Reminder()
        reminder.create_reminder_history(payment, None, template, response['messages'][0]['julo_sms_vendor'],
                                         ReminderTypeConst.SMS_TYPE_REMINDER)

        return text_message, response['messages'][0], template

    def sms_payment_dpd_10(self, payment):
        """
        send sms reminder for payment with due date late 10 day
        """
        product_line_code = payment.loan.application.product_line.product_line_code
        if product_line_code in STL or product_line_code in PEDESTL:
            if payment.ptp_date:
                return None
            template = self.get_sms_templates(payment.loan.application.product_line.product_line_code,
                                              payment.ptp_date, 10, None)
            payment_number = payment.payment_number
            due_amount = payment.due_amount
            due_date = str(payment.notification_due_date.day) + '/' + str(payment.notification_due_date.month)
            bank_name = payment.loan.julo_bank_name
            account_number = payment.loan.julo_bank_account_number
            sms_name = payment.loan.application.first_name_with_title_short
            due_date = format_date(payment.notification_due_date, 'dd-MMM', locale='id_ID')

            context = {
                'payment_number': payment_number,
                'due_amount': display_rupiah(due_amount),
                'due_date': due_date,
                'bank_name': bank_name,
                'account_number': account_number,
                'first_name_with_title_sms': sms_name
            }
            # msg = render_to_string(template + '.txt', context)
            filter_ = dict(
                dpd=10,
                communication_platform=COMMUNICATION_PLATFORM,
                template_code=template
            )
            msg = process_streamlined_comm(filter_, replaced_data=context)
            logger.info({
                'action': 'sending_sms_payment_dpd_10',
                'payment_id': payment.id,
                'loan_id': payment.loan.id,
                'template': template
            })

            text_message, response = self.send_sms(
                phone_number=format_e164_indo_phone_number(payment.loan.application.mobile_phone_1),
                message=msg,
            )

            reminder = Reminder()
            reminder.create_reminder_history(payment, None, template, response['messages'][0]['julo_sms_vendor'],
                                             ReminderTypeConst.SMS_TYPE_REMINDER)

            return text_message, response['messages'][0], template

    def sms_payment_dpd_21(self, payment):
        """
        send sms reminder for payment with due date late 21 day
        """
        product_line_code = payment.loan.application.product_line.product_line_code
        if product_line_code in MTL or product_line_code in PEDEMTL or product_line_code in LAKU6:
            template = self.get_sms_templates(payment.loan.application.product_line.product_line_code,
                                              payment.ptp_date, 21, None)
            payment_number = payment.payment_number
            due_amount = payment.due_amount
            due_date = str(payment.notification_due_date.day) + '/' + str(payment.notification_due_date.month)
            bank_name = payment.loan.julo_bank_name
            account_number = payment.loan.julo_bank_account_number
            sms_name = payment.loan.application.first_name_with_title_short
            due_date = format_date(payment.notification_due_date, 'dd-MMM', locale='id_ID')
            context = {
                'payment_number': payment_number,
                'due_amount': display_rupiah(due_amount),
                'due_date': due_date,
                'bank_name': bank_name,
                'account_number': account_number,
                'first_name_with_title_sms': sms_name
            }
            # msg = render_to_string(template + '.txt', context)
            filter_ = dict(
                dpd=21,
                communication_platform=COMMUNICATION_PLATFORM,
                template_code=template
            )
            msg = process_streamlined_comm(filter_, replaced_data=context)
            logger.info({
                'action': 'sending_sms_payment_dpd_21',
                'payment_id': payment.id,
                'loan_id': payment.loan.id,
                'template': template
            })
            text_message, response = self.send_sms(
                phone_number=format_e164_indo_phone_number(payment.loan.application.mobile_phone_1),
                message=msg,
            )

            reminder = Reminder()
            reminder.create_reminder_history(payment, None, template, response['messages'][0]['julo_sms_vendor'],
                                             ReminderTypeConst.SMS_TYPE_REMINDER)

            return text_message, response['messages'][0], template

    def sms_custom_payment_reminder(self, mobile_number, text):
        """
        send individual customize sms payment reminder
        """
        phone_number = format_e164_indo_phone_number(mobile_number)
        logger.info({
            'action': 'sending_custom_sms',
            'to_phone_number': phone_number,
            'text': text
        })

        message, response = self.send_sms(phone_number, text)

        return message, response['messages'][0]

    def sms_payment_ptp_update(self, payment):
        """
        send sms digital handshake for PTP
        """
        template = 'sms_update_ptp'

        context = {
            'due_amount': display_rupiah(payment.due_amount),
            'ptp_date': str(payment.ptp_date.day) + '/' + str(payment.ptp_date.month),
            'bank_name': payment.loan.julo_bank_name,
            'account_number': payment.loan.julo_bank_account_number,
            'fullname': payment.loan.application.fullname_with_title,
        }
        msg = render_to_string(template + '.txt', context)

        logger.info({
            'action': 'sending_sms_ptp_update',
            'payment_id': payment.id,
            'loan_id': payment.loan.id,
            'template': template
        })

        text_message, response = self.send_sms(
            phone_number=format_e164_indo_phone_number(payment.loan.application.mobile_phone_1),
            message=msg,
        )
        return text_message, response['messages'][0], template

    def sms_kyc_in_progress(self, mobile_number, eform_voucher):
        """
        send sms individual kyc in progress
        """
        template = 'sms_kyc_in_progress'
        context = {
            'eform_voucher': eform_voucher
        }
        msg = render_to_string(template + '.txt', context)
        phone_number = format_e164_indo_phone_number(mobile_number)
        logger.info({
            'action': 'sms_kyc_in_progress',
            'to_phone_number': phone_number,
            'msg': msg
        })
        message, response = self.send_sms(phone_number, msg)
        return message, response['messages'][0]

    def sms_resubmission_request_reminder(self, application, expired_day):
        """
        send sms reminder for application resubmission
        """
        template = 'sms_reminder_131'
        context = {
            'fullname': application.fullname_with_title,
            'applink': 'https://goo.gl/YvXsB5',
            'day': expired_day,
            'time': '22:00'
        }
        filter_ = dict(
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template,
            status_code=ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED
        )
        msg = process_streamlined_comm(filter_, replaced_data=context)
        logger.info({
            'action': 'sending_sms_reminder_131',
            'application_id': application.id,
            'template': template
        })

        text_message, response = self.send_sms(
            phone_number=format_e164_indo_phone_number(application.mobile_phone_1),
            message=msg,
        )
        return text_message, response['messages'][0], template

    def sms_event_end_year(self, mobile_number):
        """
        send sms event end year promosi pulsa
        """
        msg = "Terimakasih telah berpartisipasi dalam Kejutan Akhir Tahun JULO. Pulsa Rp 25000 akan terisi ke HP yg terdaftar dalam 48 jam!"
        phone_number = format_e164_indo_phone_number(mobile_number)
        logger.info({
            'action': 'sms_event_end_year',
            'to_phone_number': phone_number,
            'msg': msg
        })
        message, response = self.send_sms(phone_number, msg)
        return message, response['messages'][0]

    def sms_reminder_138(self, mobile_phone):
        """
        send sms reminder for completing verification 138
        """
        template_code = 'sms_reminder_138'
        filter_ = dict(
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template_code,
            status_code=ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING
        )
        msg = process_streamlined_comm(filter_)
        phone_number = format_e164_indo_phone_number(mobile_phone)
        logger.info({
            'action': 'sms_reminder_138',
            'to_phone_number': phone_number,
            'msg': msg
        })
        message, response = self.send_sms(phone_number, msg)
        return message, response['messages'][0], template_code

    def send_sms_streamline(self, template_code, context, application):
        filter_ = dict(
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template_code
        )
        mobile_phone = application.mobile_phone_1
        msg = process_streamlined_comm(filter_, context)
        if not msg:
            logger.error({
                'action': 'send_sms_streamline_template_not_found',
                'to_phone_number': mobile_phone,
                'template_code': template_code
            })
            return
        phone_number = format_e164_indo_phone_number(mobile_phone)
        logger.info({
            'action': 'send_sms_streamline',
            'to_phone_number': phone_number,
            'msg': msg
        })
        message, response = self.send_sms(phone_number, msg)
        response_message = response['messages'][0]
        create_sms_history(response=response_message,
                           template_code=template_code,
                           message_content=message,
                           to_mobile_phone=format_e164_indo_phone_number(response_message["to"]),
                           phone_number_type="mobile_phone_1",
                           customer=application.customer,
                           application=application)
        return message, response_message, template_code

    def sms_reminder_175(self, mobile_phone):
        """
        send sms reminder for remind people to submit their correct bank number to get disbursed
        """
        template_code = 'sms_reminder_175'
        filter_ = dict(
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template_code,
            status_code=ApplicationStatusCodes.NAME_VALIDATE_FAILED
        )
        msg = process_streamlined_comm(filter_)
        phone_number = format_e164_indo_phone_number(mobile_phone)
        logger.info({
            'action': 'sms_reminder_175',
            'to_phone_number': phone_number,
            'msg': msg
        })
        message, response = self.send_sms(phone_number, msg)
        return message, response['messages'][0], template_code

    def sms_reminder_135_21year(self, application):
        """
        send sms reminder when applican age has 21 year for 135 'age not met' application
        """
        context = {
            'firstname': application.first_name_with_title,
            'applink': 'https://goo.gl/VeRC4O',
        }

        msg = render_to_string('sms_135_21year.txt', context)
        phone_number = format_e164_indo_phone_number(application.mobile_phone_1)
        logger.info({
            'action': 'sms_reminder_135_21year',
            'to_phone_number': phone_number,
            'msg': msg
        })
        message, response = self.send_sms(phone_number, msg)
        return message, response['messages'][0]

    def sms_grab_notification(self, mobile_phone, reminder=False):
        """
        send sms notification for signing SPHP
        """
        if reminder:
            template = 'sms_notif_grab_2.txt'
        else:
            template = 'sms_notif_grab_1.txt'
        msg = render_to_string(template)
        phone_number = format_e164_indo_phone_number(mobile_phone)
        logger.info({
            'action': 'sms_grab_notification',
            'to_phone_number': phone_number,
            'msg': msg
        })
        message, response = self.send_sms(phone_number, msg)
        return message, response['messages'][0]

    def sms_lebaran_promo(self, application, payment_event):
        """
        send sms for lebaran even
        """
        context = {
            'firstname': application.fullname.split()[0],
            'applink': 'bit.ly/diskonlebaran2018',
            'discount': payment_event.event_payment,
            'payment_number': payment_event.payment.payment_number
        }

        msg = render_to_string('sms_lebaran_promo.txt', context)
        phone_number = format_e164_indo_phone_number(application.mobile_phone_1)
        logger.info({
            'action': 'sms_lebaran_promo',
            'to_phone_number': phone_number,
            'msg': msg
        })
        message, response = self.send_sms(phone_number, msg)
        return message, response['messages'][0]

    def sms_loc_notification(self, phone_number, message):
        phone_number = format_e164_indo_phone_number(phone_number)
        logger.info({
            'action': 'sms_loc_notification',
            'to_phone_number': phone_number,
            'msg': message
        })
        message, response = self.send_sms(
            phone_number=phone_number,
            message=message,
        )
        return message, response['messages'][0]

    def sms_va_notification(self, application):
        """
        send sms notification change VA
        """
        msg = render_to_string('sms_va_notification.txt')
        phone_number = format_e164_indo_phone_number(application.mobile_phone_1)
        logger.info({
            'action': 'sms_va_notification',
            'to_phone_number': phone_number,
            'msg': msg
        })
        message, response = self.send_sms(phone_number, msg)
        return message, response['messages'][0]

    def sms_experiment(self, payment, method_name):
        """
        send sms reminder for payment, with experiment use old template
        """
        product_str = ''
        loan = payment.loan
        application = loan.application
        if application.product_line.product_line_code in MTL:
            product_str = 'mtl'
        else:
            product_str = 'stl'
        template = ''
        if 'due_in' in method_name:
            template = 'exp_sms_%s_minusdpd' % (product_str)
        elif 'due_today' in method_name:
            template = 'exp_sms_%s_today' % (product_str)
        elif 'dpd_10' in method_name:
            template = 'exp_sms_%s_dpd_10' % (product_str)
        elif 'dpd_1' in method_name:
            template = 'exp_sms_%s_dpd_1' % (product_str)
        elif 'dpd_3' in method_name:
            template = 'exp_sms_%s_dpd_3' % (product_str)
        elif 'dpd_5' in method_name:
            template = 'exp_sms_%s_dpd_5' % (product_str)
        elif 'dpd_7' in method_name:
            template = 'exp_sms_%s_dpd_7' % (product_str)
        elif 'dpd_21' in method_name:
            template = 'exp_sms_%s_dpd_21' % (product_str)

        payment_number = payment.payment_number
        due_amount = payment.due_amount
        due_date = str(payment.notification_due_date.day) + '/' + str(payment.notification_due_date.month)
        bank_name = loan.julo_bank_name
        account_number = loan.julo_bank_account_number

        context = {
            'payment_number': payment_number,
            'due_amount': display_rupiah(due_amount),
            'due_date': due_date,
            'bank_name': bank_name,
            'account_number': account_number
        }
        msg = render_to_string(template + '.txt', context)

        logger.info({
            'action': 'sending_sms_experiment',
            'method_name': method_name,
            'template':template,
            'context': context,
            'payment_id': payment.id,
            'loan_id': loan.id
        })

        text_message, response = self.send_sms(
            phone_number=format_e164_indo_phone_number(application.mobile_phone_1),
            message=msg,
        )

        reminder = Reminder()
        reminder.create_reminder_history(payment, None, template, response['messages'][0]['julo_sms_vendor'],
                                         ReminderTypeConst.SMS_TYPE_REMINDER)

        return text_message, response['messages'][0], template

    def sms_agreement(self, phone, text_message):
        """
        send sms notification of agreement
        """

        message, response = self.send_sms(format_e164_indo_phone_number(phone), text_message)
        logger.info({
            'action': 'sms_agreement_notification',
            'to_phone_number': phone,
            'msg': text_message
        })

        return message, response['messages'][0]

    def prefix_change_notification(self, phone, text_message):
        """
        send sms notification of agreement
        """

        message, response = self.send_sms(format_e164_indo_phone_number(phone), text_message)
        logger.info({
            'action': 'prefix_change_notification',
            'to_phone_number': phone,
            'msg': text_message
        })

        return message, response['messages'][0]

    def blast_custom(self, phone, template, context=None):
        """
        send sms notification of agreement
        """
        text_message = render_to_string(template + '.txt', context)
        message, response = self.send_sms(format_e164_indo_phone_number(phone), text_message)
        logger.info({
            'action': 'blast_custom',
            'to_phone_number': phone,
            'msg': text_message
        })

        return message, response['messages'][0]

    def sms_custom_paylater_reminder(self, mobile_number, text):
        """
        send individual customize sms payment reminder
        """
        phone_number = format_e164_indo_phone_number(mobile_number)
        logger.info({
            'action': 'sending_custom_sms',
            'to_phone_number': phone_number,
            'text': text
        })
        message, response = self.send_sms_nexmo(phone_number, text, is_paylater=True)
        return message, response['messages'][0]

    def premium_otp(self, mobile_number, text, change_sms_provide=False):
        """
        send OTP SMS using premium SMS credential
        always use is_otp=True to use premium OTP sms credential
        """
        phone_number = format_e164_indo_phone_number(mobile_number)
        logger.info({
            'action': 'sending_otp_sms',
            'to_phone_number': phone_number,
            'text': text
        })
        message, response = self.send_sms(phone_number, text, is_otp=True)

        return message, response['messages'][0]

    def sms_reminder_172(self, mobile_phone):
        """
        send sms reminder for remind people to submit their correct bank number to get disbursed
        """
        template = 'sms_reminder_172'
        filter_ = dict(
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template,
            status_code=ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED_AND_DP_PENDING
        )
        msg = process_streamlined_comm(filter_)
        phone_number = format_e164_indo_phone_number(mobile_phone)
        logger.info({
            'action': 'sms_reminder_172',
            'to_phone_number': phone_number,
            'msg': msg
        })
        message, response = self.send_sms(phone_number, msg)
        return message, response['messages'][0], template

    def sms_loan_approved(self, application):
        """
        send sms of loan approved by the ac bypass experiment
        """
        short_url = ''
        shortened_url = ShortenedUrl.objects.get_or_none(full_url=settings.LOAN_APPROVAL_SMS_URL)
        if shortened_url:
            short_url = shortened_url.short_url
        template = 'sms_loan_approved_160'
        context = {
            'loan_amount': application.loan.loan_amount,
            'loan_duration': application.loan.loan_duration,
            'shortened_url': settings.URL_SHORTENER_BASE + short_url
        }
        filter_ = dict(
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template,
            status_code=ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL
        )
        text_message = process_streamlined_comm(filter_, context)
        message, response = self.send_sms(format_e164_indo_phone_number(application.mobile_phone_1), text_message)
        logger.info({
            'action': 'sms_loan_approved_160',
            'to_phone_number': application.mobile_phone_1,
            'msg': text_message
        })
        return message, response['messages'][0], template

    def sms_payment_reminder_replaced_wa(self, payment):
        """
        send sms reminder for payment with due date -5,-3
        for replacing Whatsapp
        """
        payment_number = payment.payment_number
        due_amount = payment.due_amount
        due_date = payment.notification_due_date.strftime("%d/%m")
        bank_name = payment.loan.julo_bank_name
        account_number = payment.loan.julo_bank_account_number
        first_name = payment.loan.application.first_name_with_title_short
        product_line_code = payment.loan.application.product_line.product_line_code
        if payment.ptp_date:
            return None
        template_name = self.get_sms_templates(payment.loan.application.product_line.product_line_code,
                                          payment.ptp_date, payment.due_late_days, None)
        encrypttext = encrypt()
        encoded_payment_id = encrypttext.encode_string(str(payment.id))
        url = settings.PAYMENT_DETAILS + str(encoded_payment_id)
        shortened_url = shorten_url(url)
        due_date = format_date(payment.notification_due_date, 'dd-MMM', locale='id_ID')
        context = {
            'payment_number': payment_number,
            'due_amount': display_rupiah(due_amount),
            'due_date': due_date,
            'first_name': first_name,
            'bank_name': bank_name,
            'account_number': account_number,
            'url': shortened_url
            }
        filter_ = dict(
            dpd=payment.due_late_days,
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template_name,
            criteria__product_line__contains=[product_line_code],
        )
        msg = process_streamlined_comm(filter_, replaced_data=context)
        logger.info({
            'action': 'sending_sms_payment_reminder_replaced_wa',
            'payment_id': payment.id,
            'loan_id': payment.loan.id,
            'template': template_name
        })

        text_message, response = self.send_sms(
            phone_number=format_e164_indo_phone_number(payment.loan.application.mobile_phone_1),
            message=msg,
        )

        reminder = Reminder()
        reminder.create_reminder_history(payment, None, template_name, response['messages'][0]['julo_sms_vendor'],
                                         ReminderTypeConst.SMS_TYPE_REMINDER)

        return text_message, response['messages'][0], template_name

    def sms_payment_reminder_replaced_wa_for_bukalapak(self, statement,
                                                       template_code,
                                                       customer):
        context = {
            'firstname': customer.fullname.split()[0].title(),
            'due_amount': format_number(statement.statement_due_amount, locale='id_ID'),
            'due_date': format_date(statement.statement_due_date, 'dd-MMM', locale='id_ID')
        }
        filter_ = dict(
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template_code,
            status_code=statement.statement_status_id
        )
        msg = process_streamlined_comm(filter_, replaced_data=context)
        phone_number = format_e164_indo_phone_number(customer.phone)
        logger.info({
            'action': 'sending_sms_for_replace_WA',
            'to_phone_number': phone_number,
            'template_code': template_code,
            'text': msg
        })
        message, response = self.send_sms_nexmo(phone_number, msg, is_paylater=True)
        return message, response['messages'][0]

    def get_sms_templates(self, product_line_code, ptp_date, due_days, gender=None):

        if due_days > 0:
            due_days = '+' + str(due_days)
        else:
            due_days = str(due_days)

        persona = ''
        if (gender == 'Pria'):
            persona = 'friska_'

        if (gender == 'Wanita'):
            persona = 'rudolf_'

        if product_line_code in MTL:
            if ptp_date:
                template = 'sms_ptp_mtl_' + due_days
            else:
                template = persona + 'mtl_sms_dpd_' + due_days
        elif product_line_code in STL:
            if ptp_date:
                template = 'sms_ptp_stl_' + due_days
            else:
                template = persona + 'stl_sms_dpd_' + due_days
        elif product_line_code in PEDEMTL:
            if ptp_date:
                template = 'sms_ptp_pedemtl_' + due_days
            else:
                template = 'pedemtl_sms_dpd_' + due_days
        elif product_line_code in PEDESTL:
            if ptp_date:
                template = 'sms_ptp_pedestl_' + due_days
            else:
                template = 'pedestl_sms_dpd_' + due_days
        elif product_line_code in LAKU6:
            if ptp_date:
                template = 'sms_ptp_laku6_' + due_days
            else:
                template = 'laku6mtl_sms_dpd_' + due_days
        else:
            return None

        return template

    def sms_notify_bukalapak_customer_va_generated(self, template_code, customer, va_number, dpd, due_amount):
        context = {
            'first_name': customer.fullname.split()[0].title(),
            'virtual_account': va_number,
            'dpd': dpd,
            'due_amount': 'Rp {:,}'.format(due_amount)
        }

        filter_ = dict(
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template_code
        )

        msg = process_streamlined_comm(filter_, replaced_data=context)
        phone_number = format_e164_indo_phone_number(customer.phone)
        logger.info({
            'action': 'sending_sms_for_replace_WA',
            'to_phone_number': phone_number,
            'template_code': template_code,
            'text': msg
        })
        message, response = self.send_sms_nexmo(phone_number, msg, is_paylater=True)
        return message, response['messages'][0]

    def sms_automated_comm(self, payment, message, template_code):
        """
        send sms reminder for payment with due date late
        """
        logger.info({
            'action': 'sms_automated_comm',
            'payment_id': payment.id,
            'loan_id': payment.loan.id,
            'template': template_code
        })

        text_message, response = self.send_sms(
            phone_number=format_e164_indo_phone_number(payment.loan.application.mobile_phone_1),
            message=message,
        )

        reminder = Reminder()
        reminder.create_reminder_history(payment, None, template_code, response['messages'][0]['julo_sms_vendor'],
                                         ReminderTypeConst.SMS_TYPE_REMINDER)

        return text_message, response['messages'][0], template_code

    def sms_automated_comm_j1(
            self, application_or_account_payment, message, template_code,
            sms_type=None, is_application=False
    ):
        """
        send sms for j1 automated SMS
        """
        logger.info({
            'action': 'sms_automated_comm_j1',
            'template': template_code
        })
        account = application_or_account_payment.account
        account_payment = None
        if not is_application:
            application = account.application_set.filter(
                workflow_id=account.account_lookup.workflow_id,
            ).last()
            account_payment = application_or_account_payment
        else:
            application = application_or_account_payment

        if not application:
            logger.info({
                'action': 'sms_automated_comm_j1',
                'template': template_code,
                'error': "dont have any active application"
            })

        phone_number = application.mobile_phone_1
        text_message, response = self.send_sms_experiment(
                                                phone_number, message, int(str(account.id)[-1]))

        reminder = Reminder()
        if not sms_type:
            sms_type = ReminderTypeConst.SMS_TYPE_REMINDER

        vendor = response['messages'][0]['julo_sms_vendor']
        reminder.create_j1_reminder_history(
            account_payment, None, template_code, vendor,
            sms_type
        )
        return text_message, response['messages'][0], template_code

    def sms_osp_recovery_promo(self, mobile_phone, is_change_template=False):
        # not declare on streamlined comm because just promo
        msg = 'Promo refund biaya bunga JULO hingga 40% utk Anda! Hingga 15 April. Cek email utk info lebih lanjut.'
        if is_change_template:
            msg = '#LebihHemat dengan promo cashback biaya bunga JULO. Hanya berlaku sampai 15 April! Cek email utk info lebih lanjut.'
        phone_number = format_e164_indo_phone_number(mobile_phone)
        logger.info({
            'action': 'sms_reminder_138',
            'to_phone_number': phone_number,
            'msg': msg
        })
        message, response = self.send_sms(phone_number, msg)
        return message, response['messages'][0]

    def sms_lebaran_campaign_2020(self, application, date, payment_url, is_partner=False):
        """
        send sms for lebaran event
        """
        context = {
            'first_name': application.first_name_only,
            'payment_url': payment_url
        }
        if is_partner:
            if date.day == 26 and date.month == 4:
                template_code = 'lebaran20_sms_reminder_1_laku6_pede_icare.txt'
            elif date.day == 6 and date.month == 5:
                template_code = 'lebaran20_sms_reminder_2_laku6_pede_icare.txt'
        else:
            if date.day == 26 and date.month == 4:
                template_code = 'lebaran20_sms_reminder_1_mtl.txt'
            elif date.day == 6 and date.month == 5:
                template_code = 'lebaran20_sms_reminder_2_mtl.txt'
        msg = render_to_string(template_code, context)
        phone_number = format_e164_indo_phone_number(application.mobile_phone_1)
        logger.info({
            'action': 'sms_lebaran_campaign_2020',
            'to_phone_number': phone_number,
            'msg': msg
        })
        message, response = self.send_sms(phone_number, msg)
        return message, response['messages'][0], template_code, msg

    def sms_repayment_awareness_campaign(self, firstname_with_short_title, day, mobile_phone):
        # not declare on streamlined comm because just promo
        msg = ''
        if day == 17:
            msg = 'Hi {}, Sudah tahu bahwa Anda dpt ' \
                  'membayar cicilan JULO via Indomaret/Alfamart? Temukan cara pembayaran mudah lainnya \njulo.co.id/r/cbr'
        elif day == 24:
            msg = 'Hi {}, Mudah banget lho untuk ' \
                  'bayar cicilan JULO! Ada banyak pilihan cara bayar, yuk pilih yang paling mudah ' \
                  'untuk Anda! julo.co.id/r/cbr'
        elif day == 1:
            msg = 'Hi {}, Sudah tahu bahwa Anda dapat ' \
                  'membayar cicilan JULO via ATM? Temukan cara pembayaran mudah lainnya di sini. julo.co.id/r/cbr'
        elif day == 8:
            msg = 'Hi {}, Anda bisa melunasi tagihan JULO ' \
                  'dengan mudah walaupun sedang #DiRumahAja! Temukan cara pembayaran mudahnya di sini. julo.co.id/r/cbr'
        msg = msg.format(firstname_with_short_title)
        phone_number = format_e164_indo_phone_number(mobile_phone)
        logger.info({
            'action': 'sms_repayment_awareness_campaign',
            'day':day,
            'to_phone_number': phone_number,
            'msg': msg
        })
        message, response = self.send_sms(phone_number, msg)
        return message, response['messages'][0]


    def sms_campaign_for_noncontacted_customer(self, mobile_phone, customer_name, sms_template_code):
        if sms_template_code == 1:
            msg = ("Dear {name}, punya pertanyaan ttg pinjaman JULO? Anda dpt hub. "
                    "kami di 02150718800 atau 02150718822 tiap Senin-Jumat, pk 9.00-18.00")
        elif sms_template_code == 2:
            msg = ("Dear {name}, ada pertanyaan ttg pembayaran / keringanan bayar JULO? "
                    "Kontak kami di 02150718800 / 02150718822 tiap Senin-Jumat, pk 9.00-18.00 ")
        elif sms_template_code == 3:
            msg = ("Dear {name}, JULO hadir lebih dekat dg Anda! Hub. 02150718800 / 02150718822 "
                    "tiap Senin-Jumat, pk 9.00-18.00 utk bantuan ttg pinjaman JULO Anda")
        else:
            raise JuloException('sms template not found')

        msg = msg.format(name=customer_name)

        phone_number = format_e164_indo_phone_number(mobile_phone)
        logger.info({
            'action': 'sms_campaign_for_noncontacted_customer',
            'to_phone_number': phone_number,
            'msg': msg
        })
        message, response = self.send_sms(phone_number, msg)
        return message, response['messages'][0], phone_number

    def sms_automated_comm_unsent_moengage(self, account_payment, message, template_code):
        """
        send sms reminder for account payment that not sent through moengage
        """
        logger.info({
            'action': 'sms_automated_comm_unsent_moengage',
            'account_payment_id': account_payment.id,
            'account_id': account_payment.account.id,
            'template': template_code
        })

        application = account_payment.account.application_set.last()

        if not application:
            logger.warning({
                'action': 'sms_automated_comm_unsent_moengage',
                'message': 'application not found',
                'account_payment_id': account_payment.id
            })

        text_message, response = self.send_sms(
            phone_number=format_e164_indo_phone_number(application.mobile_phone_1),
            message=message,
        )

        reminder = Reminder()
        reminder.create_j1_reminder_history(
            account_payment,
            None,
            template_code,
            response['messages'][0]['julo_sms_vendor'],
            ReminderTypeConst.SMS_TYPE_REMINDER)

        return text_message, response['messages'][0], template_code


    def sms_magic_link(self, mobile_number, generated_magic_link, template_code):
        template = 'fraud/' + template_code + ".txt"
        context = {
            'generated_magic_link': generated_magic_link
        }
        msg = render_to_string(template, context)
        logger.info({
            'action': 'sms_magic_link',
            'to_phone_number': mobile_number,
            'msg': msg
        })
        message, response = self.send_sms(mobile_number, msg)
        return message, response['messages'][0]

    def sms_webapp_customers_dropoff(self, application, template_code):
        sent_count = SmsHistory.objects.filter(
            application_id = application.id,
            template_code=template_code).count()
        if sent_count >= 2:
            logger.warning({
                'action': 'sms_webapp_customers_dropoff',
                'application_id': str(application.id),
                'reason': 'Reached maximum number of alerts for the application'})
            return
        mobile_phone = application.mobile_phone_1
        if not mobile_phone and application.customer.phone:
            mobile_phone = application.customer.phone
        if not mobile_phone:
            prev_otp = application.otprequest_set.last()
            if prev_otp:
                mobile_phone = prev_otp.phone_number
        if not mobile_phone:
            logger.warning({
                'action': 'sms_webapp_customers_dropoff',
                'application_id': str(application.id),
                'reason': 'SMS not sent due to unavailablitiy of phone number'})
            return
        filter_ = dict(
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template_code)
        msg = process_streamlined_comm(filter_)
        if not msg:
            logger.error({
                'action': 'sms_webapp_customers_dropoff',
                'to_phone_number': mobile_phone,
                'template_code': template_code})
            return
        phone_number = format_e164_indo_phone_number(mobile_phone)
        logger.info({
            'action': 'sms_webapp_customers_dropoff',
            'to_phone_number': phone_number,
            'msg': msg})
        message, response = self.send_sms(phone_number, msg)
        response_message = response['messages'][0]
        create_sms_history(response=response_message,
                           template_code=template_code,
                           message_content=message,
                           to_mobile_phone=format_e164_indo_phone_number(response_message["to"]),
                           phone_number_type="mobile_phone_1",
                           customer=application.customer,
                           application=application)
        return message, response_message, template_code

    def trigger_sms_vendor_function(self, comms_provider_id, phone_number, message, is_otp):
        function_name = SmsTspVendorConstants.VENDOR_MAP[comms_provider_id]
        if hasattr(self, function_name) and callable(getattr(self, function_name)):
            msg, response = getattr(self, function_name)(phone_number, message, is_otp=is_otp)
            return msg, response
        raise Exception("Sms Vendor Function {} doesn't exist".format(function_name))

    def send_grab_sms_based_on_template_code(self, template_code, application):
        if application.first_name_only:
            first_name_only = application.first_name_only
        else:
            first_name_only = application.customer.first_name_only
        if first_name_only is None:
            first_name_only = ''

        context = {
            'sms_firstname': first_name_only
        }

        filter_ = dict(
            communication_platform=CommunicationPlatform.SMS,
            extra_conditions__isnull=True,
            template_code=template_code,
            product=Product.SMS.GRAB,
            dpd__isnull=True,
            ptp__isnull=True,
            status_code_id=application.application_status_id,
            is_active=True
        )
        processed_message = process_streamlined_comm(filter_, replaced_data=context)
        if not processed_message:
            return

        phone_number = format_e164_indo_phone_number(application.mobile_phone_1)
        message, response = self.send_sms(phone_number, processed_message)
        response = response['messages'][0]
        if response['status'] == '0':
            create_sms_history(response=response,
                               customer=application.customer,
                               application=application,
                               template_code=template_code,
                               message_content=processed_message,
                               to_mobile_phone=phone_number,
                               phone_number_type='phone'
                               )
            logger.info({
                'action': 'send_grab_sms_based_on_template_code',
                'status': 'SMS sent',
                'template_code': template_code,
                'to_phone_number': phone_number,
                'msg': processed_message

            })
        else:
            logger.info({
                'action': 'send_grab_sms_based_on_template_code',
                'status': 'SMS not sent',
                'application': application,
                'template_code': template_code,
                'response': response
            })

        return


class JuloSmsAfterRobocall(object):

    def __init__(self, api_key, api_secret, base_url):
        self.api_secret = api_secret
        self.api_key = api_key
        self.base_url = base_url
    
    def send_sms(self, phone_number, message, template_code, purpose=SMSPurpose.MARKETING):
        url = str(self.base_url) + '/v1/send'
        phone_number = format_e164_indo_phone_number(phone_number)
        params = {
            "phone_number": phone_number,
            "sms_content": message,
            "purpose": purpose,
            "hostname": socket.gethostname()
        }

        headers = {
            "JULO-SMS-API-KEY": self.api_key,
            "JULO-SMS-API-SECRET": self.api_secret,
            'Content-Type': 'application/json'
        }
        # Use try except
        status = "success"
        try:
            # Send request
            api_response = requests.post(url, headers=headers, json=params, timeout=30)
            response = api_response.json()
            xid = response["data"]["xid"]
        except Exception as e:
            status = "error"
            sentry_client.captureException()
            logger.error({
                'action': "JuloSmsAfterRobocall.send_sms_error",
                'error': str(e)
            })

        logger.info({
            'action': "JuloSmsAfterRobocall.send_sms",
            'api_response': response
        })

        # Record SMS performance at ops.sms_history
        message_id = xid if status == "success" else None
        SmsHistory.objects.create(
            message_id=message_id,
            message_content=message,
            to_mobile_phone=phone_number,
            template_code=template_code,
            status=status
        )

        return xid
    
    def check_status(self, xid):
        url_check_status = str(self.base_url) + '/v1/check-status'

        status_params = {
            "xid": [xid]
        }
        headers = {
            "JULO-SMS-API-KEY": self.api_key,
            "JULO-SMS-API-SECRET": self.api_secret,
            'Content-Type': 'application/json'
        }
        status = None
        try:
            status_response = requests.post(url_check_status, headers=headers, json=status_params, timeout=30)
            response = status_response.json()
            status = response["data"][0]["status"]
        except Exception as e:
            sentry_client.captureException()
            logger.error({
                'action': "JuloSmsAfterRobocall.check_status_error",
                'error': str(e)
            })

        logger.info({
            'action': "JuloSmsAfterRobocall.check_status",
            'api_response': response,
            'xid': xid
        })
        return status


class PartnershipSMSClient(JuloSmsAfterRobocall):
    def __init__(self, api_key, api_secret, base_url):
        self.api_secret = api_secret
        self.api_key = api_key
        self.base_url = base_url

    def send_sms(self, phone_number, message, template_code, purpose=SMSPurpose.MARKETING):
        url = str(self.base_url) + '/v1/send'
        phone_number = format_e164_indo_phone_number(phone_number)
        params = {
            "phone_number": phone_number,
            "sms_content": message,
            "purpose": purpose,
            "hostname": socket.gethostname(),
        }

        headers = {
            "JULO-SMS-API-KEY": self.api_key,
            "JULO-SMS-API-SECRET": self.api_secret,
            'Content-Type': 'application/json',
        }
        status = "success"
        try:
            # Send request
            api_response = requests.post(url, headers=headers, json=params, timeout=30)
            response = api_response.json()
            xid = response["data"]["xid"]
        except Exception as e:
            status = "error"
            sentry_client.captureException()
            logger.error({'action': "PartnershipSMSClient.send_sms_error", 'error': str(e)})
            raise e

        logger.info({'action': "PartnershipSMSClient.send_sms", 'api_response': response})

        # Record SMS performance at ops.sms_history
        message_id = xid if status == "success" else None
        SmsHistory.objects.create(
            message_id=message_id,
            message_content=message,
            to_mobile_phone=phone_number,
            template_code=template_code,
            status=status,
        )

        return xid

    def check_status(self, xid):
        url_check_status = str(self.base_url) + '/v1/check-status'

        status_params = {"xid": [xid]}
        headers = {
            "JULO-SMS-API-KEY": self.api_key,
            "JULO-SMS-API-SECRET": self.api_secret,
            'Content-Type': 'application/json',
        }
        status = None
        try:
            status_response = requests.post(
                url_check_status, headers=headers, json=status_params, timeout=30
            )
            response = status_response.json()
            status = response["data"][0]["status"]
        except Exception as e:
            sentry_client.captureException()
            logger.error({'action': "PartnershipSMSClient.check_status_error", 'error': str(e)})

        logger.info(
            {'action': "PartnershipSMSClient.check_status", 'api_response': response, 'xid': xid}
        )
        return status
