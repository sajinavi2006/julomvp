from __future__ import print_function
from builtins import str
from builtins import range
import logging

# Cannot delete this import due to many UT dependent
import requests

from babel.dates import format_date
from babel.numbers import format_currency
from django.db.models import Sum

from juloserver.julo.clients import (
    get_julo_nemesys_client,
    get_julo_sentry_client,
)
from juloserver.julo.services2.experiment import check_pn_script_experiment
from juloserver.julo.exceptions import AutomatedPnNotSent
from juloserver.julo.models import (
    ApplicationHistory,
    Application,
    AwsFaceRecogLog,
    PotentialCashbackHistory,
    Image,
    FeatureSetting,
)

from juloserver.apiv2.constants import JUNE22_PROMO_BANNER_DICT
from juloserver.account_payment.models import AccountPayment

from ...julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.constants import (
    FaceRecognition,
    PushNotificationLoanEvent,
    PNBalanceConsolidationVerificationEvent,
    FeatureNameConst,
    PushNotificationDowngradeAlert,
    PushNotificationPointChangeAlert,
)
from ...julo.utils import display_rupiah
from datetime import datetime
from django.utils import timezone

from juloserver.streamlined_communication.constant import (
    CommunicationPlatform,
    ImageType,
    PageType,
)
from juloserver.streamlined_communication.services import (
    process_streamlined_comm,
    process_streamlined_comm_without_filter,
)
from juloserver.promo_campaign.clients import PromoPnClient
from juloserver.loan_refinancing.clients.pn import LoanRefinancingPnClient
from juloserver.julo_starter.services.notification import get_data_notification_second_check
from juloserver.julo_starter.constants import NotificationSetJStarter
from juloserver.streamlined_communication.models import StreamlinedCommunication
from juloserver.autodebet.services.account_services import get_existing_autodebet_account
from juloserver.autodebet.constants import VendorConst

logger = logging.getLogger(__name__)
INFO_TITLE = "JULO Info"
REMINDER_TITLE = "JULO Reminder"
ALERT_TITLE = "JULO Alert"
folded_hands = u'\U0001F64F'
APOLOGY_TITLE = "Mohon Maaf " + folded_hands
COMMUNICATION_PLATFORM = CommunicationPlatform.PN
# Please centralized used emoticon on this variable
EMOTICON_LIST = {
    'money_mouth': u'\U0001F911',  # 🤑
    'grinning_face': u'\U0001F929',  # 🤩
    'face_sweat': u'\U0001F613',  # 😓
    'cross_mark': u'\u274C',  # ❌
    'receipt': u'\U0001F9FE',  # 🧾
    'thumbs_up': u'\U0001F44D',  # 👍🏻,
    'party_popper': u'\U0001F389',  # 🎉,
    'face_screaming_in_fear': u'\U0001F631',  # 😱
    'wink': u'\U0001F609',  # 😉
    'slightly_frowning_face': u'\U0001F641',  # 🙁
}


class MessagingService(LoanRefinancingPnClient, PromoPnClient, object):
    def send_downstream_message(self, registration_ids, data, template_code, notification=None):
        """
        Redirect PN traffic to messaging_service.

        For higher level function, use PushNotificationService in streamlined_communication
            ```
            from juloserver.streamlined_communication.services import get_push_notification_service

            pn_service = get_push_notification_service()
            pn_service.send_pn(streamlined_communication, customer_id)
            ```
        """
        nemesys_client = get_julo_nemesys_client()

        body_data = {}
        if notification:
            body_data.update(notification)
        body_data.update(data)
        if 'text' in list(body_data.keys()):
            body_data['body'] = body_data.pop('text')

        json = {
            "registration_id": registration_ids[0],
            "template_code": template_code,
            "application_id": body_data.pop("application_id", None),
            "payment_id": body_data.pop("payment_id", None),
            "data": body_data
        }

        return nemesys_client.push_notification_api(json)


class JuloPNClient(MessagingService):
    def inform_etl_finished(self, application, success, special_event_check=False):
        device_query = application.customer.device_set.all()
        gcm_reg_id = device_query.order_by('cdate').values_list('gcm_reg_id', flat=True).last()
        if success:
            text = ("Score Anda telah tersedia. Silahkan cek "
                    "sekarang dan ajukan pinjaman-nya.")
        else:
            text = ("Terjadi kendala pada proses registrasi. "
                    "Mohon verifikasi kembali data Anda.")
        notification = {
            "title": INFO_TITLE,
            "text": text,
            "click_action": "com.julofinance.juloapp_HOME"
        }
        data = {
            "destination_page": "product_selection",
            "application_id": application.id,
            "success": success
        }
        if special_event_check:
            text = ("Dalam situasi ini, JULO harus mengurangi jumlah pencairan pinjaman. "
                    "Coba ajukan kembali 3 bulan ke depan.")
            notification = {
                "title": APOLOGY_TITLE,
                "text": text,
                "click_action": "com.julofinance.juloapp_HOME"
            }

        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code="inform_etl_finished")
        logger.info(response)
        return response

    # 140
    def inform_offers_made(self, fullname, gcm_reg_id, application_id):

        # congrats = "Selamat!" if fullname == "" else "Selamat, %s!" % fullname
        is_have_fullname = len(fullname) > 0
        context = {
            'fullname': fullname.title()
        }
        template_code = "inform_offers_made"
        filter_ = dict(
            criteria__is_have_fullname=is_have_fullname,
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template_code,
            status_code=ApplicationStatusCodes.OFFER_MADE_TO_CUSTOMER
        )
        msg = process_streamlined_comm(filter_, context)
        notification = {
            "title": INFO_TITLE,
            "text": msg,
        }

        data = {
            "destination_page": "Offer",
            "application_id": application_id
        }

        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code)
        logger.info(response)
        return response

# i60
    def inform_legal_document(self, fullname, gcm_reg_id, application_id):
        is_have_fullname = len(fullname) > 0
        context = {
            'fullname': fullname.title()
        }
        template_code = "inform_legal_document"
        filter_ = dict(
            criteria__is_have_fullname=is_have_fullname,
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template_code,
            status_code=ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL
        )
        msg = process_streamlined_comm(filter_, context)
        notification = {
            "title": INFO_TITLE,
            "text": msg
        }

        data = {
            "destination_page": "Legal Agreement",
            "application_id": application_id
        }
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code)
        logger.info(response)
        return response

# 162
    def inform_legal_document_resubmission(self, fullname, gcm_reg_id, application_id):
        is_have_fullname = len(fullname) > 0
        context = {
            'fullname': fullname.title()
        }
        template_code = "inform_legal_document_resubmission"
        filter_ = dict(
            criteria__is_have_fullname=is_have_fullname,
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template_code,
            status_code=ApplicationStatusCodes.LEGAL_AGREEMENT_RESUBMISSION_REQUESTED
        )
        msg = process_streamlined_comm(filter_, context)
        notification = {
            "title": INFO_TITLE,
            "text": msg,
        }

        data = {
            "destination_page": "Legal Agreement",
            "application_id": application_id
        }
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code)
        logger.info(response)
        return response

# 163
    def inform_legal_document_resubmitted(self, gcm_reg_id, application_id):
        template_code = "inform_legal_document_resubmitted"
        filter_ = dict(
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template_code,
            status_code=ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED
        )
        message = process_streamlined_comm(filter_)
        notification = {
            "title": INFO_TITLE,
            "body": message,
        }

        data = {
            "destination_page": "Legal Agreement",
            "application_id": application_id
        }
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code)
        logger.info(response)
        return response

# 170
    def inform_legal_document_signed(self, gcm_reg_id, application_id):
        template_code = "inform_legal_document_signed"
        filter_ = dict(
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template_code,
            status_code=ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED
        )
        message = process_streamlined_comm(filter_)
        notification = {
            "title": INFO_TITLE,
            "body": message,
        }
        data = {
            "destination_page": "Legal Agreement",
            "application_id": application_id
        }
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code)
        logger.info(response)
        return response

# 180
    def inform_loan_has_started(self, gcm_reg_id, application_id):
        template_code = "inform_loan_has_started"
        filter_ = dict(
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template_code,
            status_code=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
        )
        # message = "Dana pinjaman sedang di-transfer"
        message = process_streamlined_comm(filter_)
        notification = {
            "title": INFO_TITLE,
            "body": message
        }
        data = {
            "destination_page": PageType.LOAN,
            "application_id": application_id
        }
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code)
        logger.info(response)
        return response

# paid_payment
    def inform_payment_received(self, gcm_reg_id, payment_number, application_id, product_line_code,
                                payment_status_code):
        message = ""
        template_code = "inform_payment_received"
        filter_ = dict(
            criteria__product_line__contains=[product_line_code],
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template_code,
            status_code=payment_status_code
        )
        replaced_data = {
            'payment_number': payment_number
        }
        """
            ProductLineCodes.multiple_payment(): Pembayaran ke-{{payment_number}} telah diterima.
            ProductLineCodes.one_payment(): Pinjaman Anda telah lunas.
        """
        message = process_streamlined_comm(filter_, replaced_data)
        notification = {
            "title": INFO_TITLE,
            "body": message
        }
        data = {
            "destination_page": PageType.LOAN,
            "application_id": application_id
        }
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code)
        logger.info(response)
        return response

    ###########################################################################
    # Reminders
    ###########################################################################

    def inform_payment_due_soon(self, payment):
        gcm_reg_id = payment.loan.application.device.gcm_reg_id
        application_id = payment.loan.application.id
        product_line_code = payment.loan.application.product_line.product_line_code
        payment_number = payment.payment_number
        message = ""
        # template_code used for nemesys and streamlined
        template_code = "inform_payment_due_soon"
        # because ptp not already in streamlined then it just handle regular payment
        replaced_data = {
            'payment_number': payment_number
        }
        filter_ = dict(
            criteria__product_line__contains=[product_line_code],
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template_code,
        )
        """
            ProductLineCodes.multiple_payment(): Cicilan ke-{payment_number} akan jatuh tempo, harap transfer.
            ProductLineCodes.one_payment(): Pelunasan akan jatuh tempo, harap transfer.
        """
        if not payment.ptp_date:
            filter_['dpd'] = payment.due_late_days
        else:
            filter_['ptp'] = payment.ptp_late_days
        message = process_streamlined_comm(filter_, replaced_data)
        notification = {
            "title": REMINDER_TITLE,
            "body": message
        }
        data = {
            "destination_page": PageType.LOAN,
            "application_id": application_id
        }
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code)
        logger.info(response)
        return response

    def inform_payment_due_today(self, payment):
        gcm_reg_id = payment.loan.application.device.gcm_reg_id
        application_id = payment.loan.application.id
        product_line_code = payment.loan.application.product_line.product_line_code
        payment_number = payment.payment_number
        template_code = "inform_payment_due_today"
        message = ""
        # because ptp not already in streamlined than just handle regular payment
        replaced_data = {
            'payment_number': payment_number
        }
        filter_ = dict(
            criteria__product_line__contains=[product_line_code],
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template_code,
        )
        if not payment.ptp_date:
            filter_['dpd'] = payment.due_late_days
        else:
            filter_['ptp'] = payment.ptp_late_days
        message = process_streamlined_comm(filter_, replaced_data)
        """
            ProductLineCodes.multiple_payment(): Cicilan ke-{payment_number} jatuh tempo hari ini, harap transfer.
            ProductLineCodes.one_payment(): jatuh tempo hari ini, harap transfer.
        """
        notification = {
            "title": REMINDER_TITLE,
            "body": message
        }
        data = {
            "destination_page": PageType.LOAN,
            "application_id": application_id
        }
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code)
        logger.info(response)
        return response

    def inform_mtl_payment(self, payment, status=None, dpd=None):
        gcm_reg_id = payment.loan.application.device.gcm_reg_id
        application_id = payment.loan.application.id
        message = None
        # if status == 'T-5':
        #     message = ("90% pelanggan kami sudah berhasil mendapatkan Ekstra Cashback, ayo dapatkan juga.")
        # elif status == 'T-4>T-2':
        #     message = ("Anda masih punya kesempatan dapat Ekstra Cashback. Bayar angsuran ke-%s sekarang.") % (payment.payment_number)
        # elif status == 'T-1>T-0':
        #     message = ("95% pelanggan di area Anda sudah membayar. Ayo bayar, kesempatan terakhir mendapatkan Cashback.")
        # elif status == 'T+1>T+4':
        #     message = ("Masih ada kesempatan memperbaiki skor kredit. Ayo bayarkan tagihan Anda sekarang.")
        # elif status == 'T+5>T++':
        #     message = ("Jangan biarkan beban Anda bertambah, Kami carikan solusi kendala Anda. Hubungi Kami segera.")
        dpd_from_payment = payment.due_late_days
        template_code = 'MTL_T{}'.format(dpd_from_payment)
        replaced_data = {
            'payment_number': payment.payment_number
        }
        filter_ = dict(
            criteria__isnull=True,
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template_code,
            dpd=dpd_from_payment
        )
        message = process_streamlined_comm(filter_, replaced_data)

        if dpd_from_payment in range(-5, 1):
            message = check_pn_script_experiment(payment, dpd_from_payment, message)

        notification = {
            "title": REMINDER_TITLE,
            "body": message
        }
        data = {
            "destination_page": PageType.LOAN,
            "application_id": application_id,
            "payment_id": payment.id,
        }
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code)
        logger.info({
            "function": "inform_mtl_payment",
            "description": "for PN Experiment v2",
            "dpd": dpd,
            "template_code": template_code,
            "payment_id": payment.id,
            "due_date": payment.due_date,
            "send_date": timezone.localtime(timezone.now()).date(),
            "response": response
        })
        return response

    def inform_stl_payment(self, payment, status=None):
        gcm_reg_id = payment.loan.application.device.gcm_reg_id
        application_id = payment.loan.application.id
        template_code = 'STL_T{}'.format(payment.due_late_days)
        # if status == 'T-5>T-0':
        #     message = ("95% pelanggan di area Anda sudah membayar. Ayo ikut bayar Pinjaman Anda sekarang.")
        # elif status == 'T+1>T+4':
        #     message = ("Masih ada kesempatan memperbaiki skor kredit. Ayo bayarkan tagihan Anda sekarang.")
        # elif status == 'T+5>T++':
        #     message = ("Jangan biarkan beban Anda bertambah, Kami carikan solusi kendala Anda. Hubungi Kami segera.")
        filter_ = dict(
            criteria__isnull=True,
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template_code,
            dpd=payment.due_late_days
        )
        message = process_streamlined_comm(filter_)
        notification = {
            "title": REMINDER_TITLE,
            "body": message
        }
        data = {
            "destination_page": PageType.LOAN,
            "application_id": application_id,
            "payment_id": payment.id,
        }
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code)
        logger.info(response)
        return response

    # remind customer to upload document
    def reminder_upload_document(self, gcm_reg_id, application_id):

        message = "Unggah dokumen untuk persetujuan"
        notification = {
            "title": REMINDER_TITLE,
            "body": message,
        }

        data = {
            "destination_page": PageType.HOME,
            "application_id": application_id
        }

        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code="reminder_upload_document")
        logger.info(response)
        return response

    def reminder_docs_resubmission(self, gcm_reg_id, application_id):
        message = (
            "Kirimkan kekurangan Dokumen Anda."
        )
        notification = {
            "title": REMINDER_TITLE,
            "body": message
        }
        data = {
            "destination_page": PageType.HOME,
            "application_id": application_id
        }
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code="reminder_docs_resubmission")
        logger.info(response)
        return response

    def reminder_verification_call_ongoing(self, gcm_reg_id, application_id):
        message = (
            "Kabarkan referensi anda utk menjawab telpon JULO"
        )
        notification = {
            "title": REMINDER_TITLE,
            "body": message
        }
        data = {
            "destination_page": PageType.HOME,
            "application_id": application_id
        }
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code="reminder_verification_call_ongoing")
        logger.info(response)
        return response

    def reminder_app_status_105(self, gcm_reg_id, application_id, credit_score):
        message = (
            "SEDIKIT LAGI!! Cukup dengan pilih produk pinjaman dan unggah dokumen saja untuk mendapatkan pencairan."
        )
        if credit_score == 'A-':
            message = (
                "Skor Kredit Anda sangat bagus! Ayo, sedikit lagi untuk mendapatkan pinjaman hingga 8 juta rupiah!"
            )

        notification = {
            "title": REMINDER_TITLE,
            "body": message
        }
        data = {
            "destination_page": "product selection",
            "application_id": application_id
        }
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code="reminder_app_status_105")
        logger.info(response)
        return response

    def inform_submission_approved(self, fullname, gcm_reg_id, application_id):
        message = ("Selamat! Pengajuan anda telah berhasil disetujui, selangkah lagi menuju pencairan")
        notification = {
            "title": REMINDER_TITLE,
            "body": message,
            "click_action": "com.julofinance.juloapp_HOME"
        }
        data = {
            "destination_page": PageType.HOME,
            "application_id": application_id
        }

        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code="inform_submission_approved")

        logger.info(response)

        return response

    def send_pn_playstore_rating(self, fullname, gcm_reg_id, application_id, message, image_url, title):
        # PN for playstore rating from 180 - JIRA ON-1190

        notification = {
            "title": title,
            "body": message,
            "click_action": "com.julofinance.juloapp_HOME"
        }

        data = {
            "destination_page": "rating_playstore",
            "application_id": application_id,
            "image_url": image_url
        }

        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code="send_pn_playstore_rating")

        logger.info(response)

        return response

    def remainder_for_playstore_rating(self, fullname, gcm_reg_id, application_id):
        message = ("Berikan bintang 5 jika JULO sudah membantu kebutuhan Anda")
        notification = {
            "title": REMINDER_TITLE,
            "body": message,
            "click_action": "com.julofinance.juloapp_HOME"
        }
        data = {
            "destination_page": "rating_page",
            "application_id": application_id
        }

        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code="remainder_for_playstore_rating")

        logger.info(response)

        return response

    ###########################################################################
    # Alerts
    ###########################################################################

    def inform_payment_late(self, payment):
        if payment.loan.application.device is not None:
            gcm_reg_id = payment.loan.application.device.gcm_reg_id
            application_id = payment.loan.application.id
            product_line_code = payment.loan.application.product_line.product_line_code
            payment_number = payment.payment_number
            template_code = "inform_payment_late"
            message = ""
            # because ptp not already in streamlined than just handle regular payment
            if not payment.ptp_date:
                replaced_data = {
                    'payment_number': payment_number
                }
                filter_ = dict(
                    criteria__product_line__contains=[product_line_code],
                    communication_platform=COMMUNICATION_PLATFORM,
                    template_code=template_code,
                    dpd=payment.due_late_days
                )
                message = process_streamlined_comm(filter_, replaced_data)
            else:
                if product_line_code in ProductLineCodes.multiple_payment():
                    message = (
                                  "Cicilan ke-%s terlambat, harap transfer."
                              ) % payment_number
                elif product_line_code in ProductLineCodes.one_payment():
                    message = "Pelunasan terlambat, harap transfer."

            notification = {
                "title": ALERT_TITLE,
                "body": message
            }
            data = {
                "destination_page": PageType.LOAN,
                "application_id": application_id,
                "payment_id": payment.id,
            }
            response = self.send_downstream_message(
                registration_ids=[gcm_reg_id],
                notification=notification,
                data=data,
                template_code=template_code)
            logger.info(response)

            return response
        else:
            return None

    # Correction needed

    # email has been verified
    def inform_email_verified(self, gcm_reg_id):
        message = (
            "Email telah diverifikasi, ajukan pinjaman segera!"
        )
        notification = {
            "title": INFO_TITLE,
            "body": message
        }
        data = {
            "destination_page": "Application Form"
        }
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code="inform_email_verified")
        logger.info(response)
        return response

    # documents have been submitted
    def inform_docs_submitted(self, gcm_reg_id, application_id):
        message = (
            "Foto telah selesai diunggah."
        )
        notification = {
            "title": INFO_TITLE,
            "body": message
        }
        data = {
            "destination_page": PageType.HOME,
            "application_id": application_id
        }
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code="inform_docs_submitted")
        logger.info(response)
        return response

    # sphp has been signed
    def inform_sphp_signed(self, gcm_reg_id, application_id):
        message = (
            "Surat perjanjian telah ditandatangani."
        )
        notification = {
            "title": INFO_TITLE,
            "body": message
        }
        data = {
            "destination_page": "Legal Agreement",
            "application_id": application_id
        }
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code="inform_sphp_signed")
        logger.info(response)
        return response

        # document resubmission request

    def inform_docs_resubmission(self, gcm_reg_id, application_id):
        message = (
            "Dokumen kurang/ tidak jelas. Mohon cek email untuk ditindak-lanjuti."
        )
        application = Application.objects.get_or_none(pk=application_id)
        app_history = ApplicationHistory.objects.filter(
            application=application,
            status_new=ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED).last()
        failed_upload_image_reasons = [
            'failed upload selfie image',
            'Passed KTP check & failed upload selfie image'
        ]
        passed_face_recog = AwsFaceRecogLog.objects.filter(application=application).last()
        title_face_recog = None
        if passed_face_recog and not passed_face_recog.is_quality_check_passed or \
                (app_history and app_history.change_reason in failed_upload_image_reasons):
            title_face_recog = 'Upload Kembali Selfie Anda'
            if app_history and app_history.change_reason in failed_upload_image_reasons or \
                    not passed_face_recog.raw_response['FaceRecordsStatus'] and \
                    not passed_face_recog.raw_response['UnindexedFaces']:
                message = (
                    'Foto selfie Anda tidak terdeteksi. Klik di sini untuk mengunggahnya kembali!'
                )
            elif passed_face_recog.raw_response['UnindexedFaces']:
                message = (
                    'Foto selfie Anda kurang jelas dan tidak terdeteksi. Klik di sini untuk mengunggahnya kembali!'
                )
            elif not passed_face_recog.is_quality_check_passed:
                message = (
                    'Foto selfie Anda buram/tidak jelas. Klik di sini untuk mengunggahnya kembali!'
                )

        notification = {
            "title": ALERT_TITLE if not title_face_recog else title_face_recog,
            "body": message
        }
        data = {
            "destination_page": PageType.HOME,
            "application_id": application_id
        }
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code="inform_docs_resubmission")
        logger.info(response)
        return response

    def inform_docs_verified(self, gcm_reg_id, application_id):
        message = (
            "Verifikasi referensi sedang berlangsung."
        )
        notification = {
            "title": INFO_TITLE,
            "body": message
        }
        data = {
            "destination_page": PageType.HOME,
            "application_id": application_id
        }
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code="inform_docs_verified")
        logger.info(response)
        return response

    def trigger_location(self, gcm_reg_id, application_id):
        notification = {
            "title": "location trigger test",
            "text": "your location has been triggered"
        }

        data = {
            "action": "update_location",
            "application_id": application_id
        }

        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code="trigger_location")
        logger.info(response)

        return response

    def inform_verification_call_ongoing(self, gcm_reg_id, application_id):
        message = (
            "Kabarkan referensi anda utk menjawab telpon JULO"
        )
        notification = {
            "title": INFO_TITLE,
            "body": message
        }
        data = {
            "destination_page": PageType.HOME,
            "application_id": application_id
        }
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code="inform_verification_call_ongoing")
        logger.info(response)
        return response

    def kyc_in_progress(self, gcm_reg_id, application_id):
        message = (
            "Selamat! E-Form Voucher Anda sudah siap"
        )
        notification = {
            "title": INFO_TITLE,
            "body": message
        }
        data = {
            "destination_page": PageType.HOME,
            "application_id": application_id
        }
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code="kyc_in_progress")
        logger.info(response)
        return response

    def alert_rescrape(self, gcm_reg_id, application_id):
        message = (
            "Sambil menunggu perhitungan JULO poin, pelajari produk JULO sekarang!"
        )
        notification = {
            "title": ALERT_TITLE,
            "body": message
        }
        data = {
            "destination_page": PageType.HOME,
            "application_id": application_id
        }
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code="alert_rescrape")
        logger.info(response)
        return response

    def infrom_cashback_sepulsa_transaction(self, customer, transaction_status, is_cashback=True):
        device_query = customer.device_set.all()
        gcm_reg_id = device_query.order_by('cdate').values_list('gcm_reg_id', flat=True).last()
        word_cashback = 'cashback ' if is_cashback else ''
        click_action = "com.julofinance.juloapp_CASHBACK_RESULT"
        destination_page = "cashback_transaction"
        if transaction_status == 'success':
            message = (
                "Transaksi {}berhasil, silahkan cek aplikasi JULO".format(word_cashback)
            )
        elif transaction_status == 'failed':
            message = (
                "Transaksi {}gagal, silahkan coba kembali melalui aplikasi JULO".format(
                    word_cashback
                )
            )
        else:
            return
        if not is_cashback:
            click_action = "com.julofinance.juloapp_HOME"
            destination_page = PageType.HOME
        notification = {
            "title": INFO_TITLE,
            "body": message,
            "click_action": click_action
        }
        data = {
            "destination_page": destination_page,
        }
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code="infrom_cashback_sepulsa_transaction")
        logger.info(response)
        return response

    def notify_lebaran_promo(self, application):
        device = application.customer.device_set.last()
        gcm_reg_id = device.gcm_reg_id

        message = (
            "PROMO Diskon Lebaran! Buka aplikasi JULO sekarang!"
        )

        notification = {
            "title": INFO_TITLE,
            "body": message,
        }

        data = {
            "destination_page": PageType.HOME,
            "application_id": application.id
        }

        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code="notify_lebaran_promo")
        logger.info(response)
        return response

    def infrom_loc_sepulsa_transaction(self, sepulsa_transaction):
        device_query = sepulsa_transaction.customer.device_set.all()
        gcm_reg_id = device_query.order_by('cdate').values_list('gcm_reg_id', flat=True).last()
        if gcm_reg_id:
            if sepulsa_transaction.transaction_status == 'success':
                message = (
                        "Transaksi %s berhasil, silahkan cek aplikasi JULO" % (
                    sepulsa_transaction.product.title_product())
                )
            elif sepulsa_transaction.transaction_status == 'failed':
                message = (
                        "Transaksi %s gagal, silahkan coba kembali melalui aplikasi JULO" % (
                    sepulsa_transaction.product.title_product())
                )
            else:
                return
            notification = {
                "title": INFO_TITLE,
                "body": message,
                "click_action": "com.julofinance.juloapp_HOME"
            }
            data = {
                "destination_page": "loc_installment",
            }

            response = self.send_downstream_message(
                registration_ids=[gcm_reg_id],
                notification=notification,
                data=data,
                template_code="infrom_loc_sepulsa_transaction")
            logger.info(response)
            return response

    def inform_loc_notification(self, gcm_reg_id, message):
        notification = {
            "title": REMINDER_TITLE,
            "body": message,
            "click_action": "com.julofinance.juloapp_HOME"
        }
        data = {
            "destination_page": "loc_installment",
        }

        response = self.send_downstream_message(registration_ids=[gcm_reg_id],
                                                notification=notification,
                                                data=data,
                                                template_code="inform_loc_notification")
        logger.info(response)
        return response

    def alert_retrofix_credit_score(self, gcm_reg_id, application_id):
        message = (
            "Selamat! Skor Anda terupdate, ajukan Pinjaman Tanpa Jaminan sekarang juga!"
        )
        notification = {
            "title": ALERT_TITLE,
            "body": message
        }
        data = {
            "destination_page": PageType.HOME,
            "application_id": application_id
        }
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code="alert_retrofix_credit_score")
        logger.info(response)
        return response

    def inform_transfer_cashback_finish(self, cashback, success):
        device_query = cashback.application.customer.device_set.all()
        gcm_reg_id = device_query.order_by('cdate').values_list('gcm_reg_id', flat=True).last()
        transfer_amount = display_rupiah(cashback.transfer_amount)

        if success:
            text = ("Cashback sebesar {} telah dikirimkan ke rekening {} {}".format(
                transfer_amount, cashback.bank_name, cashback.bank_number))
        else:
            text = ("Cashback sebesar {} gagal ditransfer ke rekening anda, segera hub cs@julo.co.id.".format(
                transfer_amount))
        notification = {
            "title": INFO_TITLE,
            "text": text,
            "click_action": "com.julofinance.juloapp_CASHBACK_RESULT"
        }
        data = {
            "destination_page": "cashback_transaction",
        }
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code="inform_transfer_cashback_finish")
        logger.info(response)
        return response

    def inform_loc_reset_pin_finish(self, gcm_reg_id, message):
        notification = {
            "title": INFO_TITLE,
            "body": message,
            "click_action": "com.julofinance.juloapp_HOME"
        }
        data = {
            "type": "loc_reset_pin_success",
            "destination_page": "loc_installment",
        }

        response = self.send_downstream_message(registration_ids=[gcm_reg_id],
                                                notification=notification,
                                                data=data,
                                                template_code="inform_loc_reset_pin_finish")
        logger.info(response)
        return response

    def inform_get_cashback_promo_asian_games(self, customer):
        device_query = customer.device_set.all()
        gcm_reg_id = device_query.order_by('cdate').values_list('gcm_reg_id', flat=True).last()
        text = ("Selamat! payment Anda dapat cashback Rp20.000,- dari Promo Asian Games.")
        notification = {
            "title": INFO_TITLE,
            "text": text,
            "click_action": "com.julofinance.juloapp_CASHBACK_RESULT"
        }
        data = {
            "destination_page": "cashback_disbursement",
        }
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code="inform_get_cashback_promo_asian_games")
        logger.info(response)
        return response

    def inform_asian_games_campaign(self, customer):
        device_query = customer.device_set.all()
        gcm_reg_id = device_query.order_by('cdate').values_list('gcm_reg_id', flat=True).last()
        if gcm_reg_id:
            text = ("Meriahkan Asian Games 2018! Buka website JULO sekarang!")
            notification = {
                "title": INFO_TITLE,
                "text": text,
                "click_action": "com.julofinance.juloapp_HOME"
            }
            data = {
                "destination_page": PageType.HOME,
            }
            response = self.send_downstream_message(
                registration_ids=[gcm_reg_id],
                notification=notification,
                data=data,
                template_code="inform_asian_games_campaign")
            logger.info(response)
            return response
        else:
            return False

    def inform_va_notification(self, customer):
        device_query = customer.device_set.all()
        gcm_reg_id = device_query.order_by('cdate').values_list('gcm_reg_id', flat=True).last()
        text = ("Perubahan nomor Virtual Account BCA")
        notification = {
            "title": INFO_TITLE,
            "text": text,
            "click_action": "com.julofinance.juloapp_PAYMENT_METHOD"
        }
        data = {
            "destination_page": "payment_method",
        }
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code="inform_va_notification")
        logger.info(response)
        return response

    def early_payment_promo(self, gcm_reg_id, notif_text):
        text = (notif_text)
        notification = {
            "title": INFO_TITLE,
            "text": text,
            "click_action": "com.julofinance.juloapp_HOME"
        }
        data = {
            "destination_page": PageType.HOME,
        }
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code="early_payment_promo")
        logger.info(response)
        return response

    def inform_robocall_notification(self, customer, application_id, payment_id, dpd=None, type=None):
        device_query = customer.device_set.all()
        gcm_reg_id = device_query.order_by('cdate').values_list('gcm_reg_id', flat=True).last()
        notification = {
            "title": REMINDER_TITLE,
            "text": "Lakukan pembayaran tagihan JULO hari ini dan dapatkan cashback nya!",
            "click_action": "com.julofinance.juloapp_HOME"
        }
        data = {
            "destination_page": PageType.LOAN,
            "application_id": application_id,
            "payment_id": payment_id
        }
        template_code = '{}_T{}'.format(type, dpd)
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code)
        logger.info(response)
        return response

    def loan_paid_off_rating(self, customer):
        device_query = customer.device_set.all()
        gcm_reg_id = device_query.order_by('cdate').values_list('gcm_reg_id', flat=True).last()
        text = ("Terima Kasih telah Menggunakan JULO! Mohon Bantuannya untuk Memberikan Rating "
                "kepada JULO sesuai dengan Pengalaman Anda Menggunakan JULO!")
        notification = {
            "title": INFO_TITLE,
            "text": text,
            "click_action": "com.julofinance.juloapp_HOME"
        }
        data = {
            "destination_page": "rating_page",
        }
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code="loan_paid_off_rating")
        logger.info(response)
        return response

    def complete_form_notification(self, customer):
        device_query = customer.device_set.all()
        gcm_reg_id = device_query.order_by('cdate').values_list('gcm_reg_id', flat=True).last()
        notification = {
            "title": REMINDER_TITLE,
            "body": ("Yuk Selesaikan Formulir Pengajuanmu untuk Mendapatkan "
                     "Pinjaman Hingga 8 Juta Rupiah!"),
            "click_action": "com.julofinance.juloapp_REGISTER_V3"
        }
        data = {
            "destination_page": "register_v3",
        }
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code="complete_form_notification")
        logger.info(response)
        return response

    def notifications_enhancements_v1(self, customer, notification_template):
        device_query = customer.device_set.all()
        gcm_reg_id = device_query.order_by('cdate').values_list('gcm_reg_id', flat=True).last()
        data = {
            "title": notification_template['title'],
            "body": notification_template['body'],
            "click_action": notification_template['click_action'],
            "destination_page": notification_template['destination_page'],
            "image_url": notification_template['image_url']
        }
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            data=data,
            template_code="notifications_enhancements_v1")
        logger.info(response)
        return response

    def pn_backup_va(self, gcm_reg_id, first_name, va_method, va_number):
        message = 'INFO:\
            Hi {}! Perubahan Nomor Virtual Account.\
            Silahkan lakukan pembayaran angsuran JULO Anda dengan nomor \
            {}: {}. Hubungi cs@julo.co.id u/ info lebih lanjut.' \
            .format(first_name, va_method, va_number)

        notification = {
            "title": REMINDER_TITLE,
            "body": message
        }

        data = {
            "destination_page": PageType.HOME
        }

        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code="pn_activate_backup_va")

        logger.info(response)

        return response

    def pn_face_recognition(self, gcm_reg_id, message):
        notification = {
            "title": 'face_recognition',
            "body": message
        }

        data = {
            "destination_page": PageType.HOME
        }

        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code='pn_face_recognition'
        )

        logger.info(response)
        return response

    # 110
    def inform_old_version_reinstall(self, gcm_reg_id, application_id):
        template_code = "inform_old_version_reinstall"
        filter_ = dict(
            communication_platform=COMMUNICATION_PLATFORM,
            template_code=template_code,
            status_code=ApplicationStatusCodes.FORM_SUBMITTED
        )
        message = process_streamlined_comm(filter_)
        notification = {
            "title": INFO_TITLE,
            "body": message,
            "click_action": "com.julofinance.juloapp_HOME"
        }

        data = {
            "destination_page": PageType.HOME,
            "application_id": application_id
        }
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code
        )
        logger.info(response)
        return response

    def cashback_transfer_complete_osp_recovery_apr2020(self, application_id, gcm_reg_id, cashback_amt):
        notification = {
            "title": "Cashback telah ditransfer ke akun JULO Anda",
            "body": "Cashback Anda sebesar Rp. %s sudah kami transfer. Silakan cek aplikasi JULO Anda." % cashback_amt
        }

        data = {
            "application_id": application_id,
            "destination_page": PageType.HOME
        }

        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code="pn_mar2020_hi_season")
        return response

    def notify_lebaran_campaign_2020_mtl(self, application, date):
        moneywing_emoji = u'\U0001F4B8'
        coveredmouthsmile_emoji = u'\U0001F92D'
        giftunicode_emoji = u'\U0001F381'
        device = application.customer.device_set.last()
        gcm_reg_id = device.gcm_reg_id
        # Set appropriate message for Respective Date
        if date.day == 27 and date.month == 4:
            title = "Hi, Ada Kejutan Spesial dari JULO" + giftunicode_emoji
            message = "Yuk, bayar cicilan JULO Anda dan menangkan total hadiah 10jt rupiah!" + \
                      moneywing_emoji
        elif date.day == 29 and date.month == 4:
            title = "Kesempatan Baik Buat Anda!" + moneywing_emoji
            message = "Psst.. cek email dari Kami tentang kejutan spesial untuk Anda!"
        elif date.day == 1 and date.month == 5:
            title = "Hadiah Total 10jt Menunggu Anda!" + moneywing_emoji
            message = "Bayar cicilan Anda dan raih peluang jadi pemenang undian!" + \
                      moneywing_emoji + " Tunggu apalagi?"
        elif date.day == 3 and date.month == 5:
            title = "Kejutan Spesial dari JULO untuk Anda!" + giftunicode_emoji
            message = "Segera bayar cicilan JULO Anda & menangkan total hadiah 10jt rupiah!"
        elif date.day == 7 and date.month == 5:
            title = "KESEMPATAN TERAKHIR Jadi Pemenang" + moneywing_emoji
            message = "THR sudah di tangan?" + coveredmouthsmile_emoji + \
                      " Segera bayar cicilan Anda dan jadilah salah satu pemenang beruntung! " + \
                      moneywing_emoji
        else:
            return
        notification = {
            "title": title,
            "body": message,
        }

        data = {
            "destination_page": PageType.HOME,
            "application_id": application.id
        }

        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code="notify_lebaran_campaign_2020_mtl")
        logger.info(response)
        return response

    def automated_payment_reminder(
        self, payment, message, heading_title, template_code, buttons):
        gcm_reg_id = payment.loan.application.device.gcm_reg_id
        application_id = payment.loan.application.id
        notification = {
            "title": heading_title,
            "body": message
        }
        data = {
            "destination_page": "Loan Activities",
            "application_id": application_id,
            "payment_id": payment.id,
        }
        data["buttons"] = buttons
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code)

        logger.info(response)
        return response

    def automated_payment_reminder(
        self, payment, message, heading_title, template_code, buttons, image=None):
        gcm_reg_id = payment.loan.application.device.gcm_reg_id
        application_id = payment.loan.application.id
        notification = {
            "title": heading_title,
            "body": message
        }
        if image:
            notification.update({
                "image_url": image.public_image_url
            })
        data = {
            "destination_page": PageType.LOAN,
            "application_id": application_id,
            "payment_id": payment.id,
        }
        data["buttons"] = buttons
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code)
        logger.info({
            "function": "automated PN",
            "template_code": template_code,
            "payment_id": payment.id,
            "due_date": payment.due_date,
            "send_date": timezone.localtime(timezone.now()).date(),
            "response": response
        })
        return response


    def send_pn_depracated_app(self, application_id):
        application = Application.objects.get(id=application_id)
        gcm_reg_id = application.device.gcm_reg_id
        template_code = 'send_pn_depracated_app'
        notification = {
            "title": "Update Aplikasi JULO kamu",
            "body": "Ayo Update Aplikasi JULO kamu, untuk kelancaran pengajuan"
        }
        data = {
            "destination_page": PageType.HOME,
            "application_id": application_id,
        }
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code)

        logger.info({
            "function": "send_pn_depracated_app",
            "template_code": template_code,
            "send_date": timezone.localtime(timezone.now()).date(),
            "response": response
        })
        return response

    def send_reminder_sign_sphp(self, application_id):
        application = Application.objects.get(id=application_id)
        gcm_reg_id = application.device.gcm_reg_id
        template_code = 'sphp_sign_ready_reminder'
        notification = {
            "title": "Yuk buka aplikasi JULOmu",
            "body": " Lakukan OTP sekarang untuk tanda tangan SPHP mu.",
            "click_action": "com.julofinance.juloapp_HOME"
        }
        data = {
            "destination_page": "sphp_page",
            "application_id": application_id,
        }
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code)

        logger.info({
            "function": "sphp_sign_ready_reminder",
            "template_code": template_code,
            "send_date": timezone.localtime(timezone.now()).date(),
            "response": response
        })

        return response

    def manual_blast_pn(self, account_payment: AccountPayment, gcm_reg_id: str,
                        streamlined_pn: StreamlinedCommunication, context_data: dict
                        ):
        """
        Process to provide customer data for NemeSys, our internal PN/messaging service.

        Args:
            account_payment (AccountPayment): AccountPayment object expected to have account and
                application.
            gcm_reg_id (str): Device's gcm registration ID as sending target.
            streamlined_pn (StreamlinedCommunication): StreamlinedCOmmunication object ID.
            context_data (dict): A dictionary of data to be used as context to render PN content.
        """
        if not streamlined_pn:
            return

        sentry_client = get_julo_sentry_client()
        logger.info({
            'action': 'manual_blast_pn',
            'streamlined_communication': streamlined_pn,
            'account_payment_id': account_payment.id,
            'message': "triggered manual_blast_pn",
        })

        application = account_payment.account.application_set.last()
        application_id = application.id if application else None
        customer_id = application.customer_id if application else None

        try:
            message_content = process_streamlined_comm_without_filter(streamlined_pn, context_data)
            image = Image.objects.get_or_none(
                image_source=streamlined_pn.id, image_type=ImageType.STREAMLINED_PN,
                image_status=Image.CURRENT
            )

            notification = {
                "title": streamlined_pn.subject,
                "body": message_content
            }
            if image:
                notification.update({
                    "image_url": image.public_image_url
                })
            data = {
                "destination_page": PageType.LOAN,
                "account_payment_id": account_payment.id,
                "customer_id": customer_id,
                "application_id": application_id
            }

            response = self.send_downstream_message(
                registration_ids=[gcm_reg_id],
                notification=notification,
                data=data,
                template_code=streamlined_pn.template_code)

            logger.info({
                'message': 'Finish send_downstream_message',
                'module': 'juloserver.julo.clients.pn',
                'action': 'JuloPNClient@manual_blast_pn',
                'response_status_code': response.status_code,
                'template_code': streamlined_pn.template_code,
                'moengage_template_code': streamlined_pn.moengage_template_code,
                'response': response,
                'data': data,
            })
            return response
        except Exception as e:
            sentry_client.capture_exceptions()
            raise AutomatedPnNotSent(str(e))


    def automated_payment_reminder_j1(
            self, account_payment, message, heading_title, template_code, buttons, image=None):
        application = account_payment.account.application_set.last()
        gcm_reg_id = application.device.gcm_reg_id
        application_id = application.id
        notification = {
            "title": heading_title,
            "body": message
        }
        if image:
            notification.update({
                "image_url": image.public_image_url
            })

        data = {
            "destination_page": PageType.LOAN,
            "application_id": application_id,
            "payment_id": account_payment.id,
        }
        data["buttons"] = buttons
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code)
        logger.info({
            "function": "automated PN J1",
            "template_code": template_code,
            "payment_id": account_payment.id,
            "due_date": account_payment.due_date,
            "send_date": timezone.localtime(timezone.now()).date(),
            "response": response
        })
        return response

    def cashback_expire_reminder(self, customer, message, template_code):
        device_query = customer.device_set.all()
        gcm_reg_id = device_query.order_by('cdate').values_list('gcm_reg_id', flat=True).last()
        notification = {
            "title": REMINDER_TITLE,
            "body": message
        }

        data = {
            "destination_page": "cashback_transaction",
            "customer_id": customer.id,
        }
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code)
        logger.info({
            "action": "cashback_expire_pn",
            "template_code": template_code,
            "customer_id": customer.id,
            "send_date": timezone.localtime(timezone.now()).date(),
            "response": response
        })
        return response

    def in_app_callback_reminder(self, title, message, gcm_reg_id):
        notification = {
            "title": title,
            "body": message
        }
        data = {
            "destination_page": PageType.HOME,
        }
        template_code = 'in_app_callback_reminder'
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code)

        logger.info({
            "function": "send_notification_in_app_callback_promise",
            "template_code": template_code,
            "send_date": timezone.localtime(timezone.now()).date(),
            "response": response
        })
        return response

    def in_app_ptp_broken(self, title, message, gcm_reg_id):
        notification = {
            "title": title,
            "body": message
        }
        data = {
            "destination_page": PageType.HOME,
        }
        template_code = 'in_app_ptp_broken'
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code)
        logger.info({
            "function": "send_notification_in_app_ptp_broken",
            "template_code": template_code,
            "send_date": timezone.localtime(timezone.now()).date(),
            "response": response
        })
        return response

    def alert_claim_cfs_action_assignment(self, customer, cashback_amount):
        device_query = customer.device_set.all()
        gcm_reg_id = device_query.order_by('cdate').values_list('gcm_reg_id', flat=True).last()
        cashback_earned = format_currency(cashback_amount, 'Rp')
        message = ("Selamat! Kamu mendapatkan cashback sebesar {} dari hadiah misi yang belum "
                   "kamu ambil bulan ini".format(cashback_earned))
        notification = {
            "title": ALERT_TITLE,
            "body": message
        }
        data = {
            "destination_page": "cfs"
        }
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code="alert_cfs_action_assignment_cashback_earned")

        logger.info(response)

        return response

    def pn_june2022_hi_season(self, gcm_reg_id, pn_type, due_date):
        due_date_normal = due_date
        due_date = datetime.strptime(str(due_date), '%Y-%m-%d').strftime('%d-%m-%Y')
        moneywing = '\U0001F4B8'
        if pn_type == 'pn1_8h':
            template_code = 'pn1_juni2022_hi_season'
            title = 'Kilau Juni Melesat'
            message = ('Bayar Lebih awal, Bawa Pulang Hadiah Emas dan Sepeda Listrik!' +
                       moneywing + moneywing)

        else:
            template_code = 'pn2_juni2022_hi_season'
            title = 'Sepeda Listrik dan Emas 1 Gr Siap Kamu Bawa Pulang!' + moneywing
            message = ('Bayar sebelum %s, '
                       'klik banner promo di app & jadi pemenangnya!') % due_date

        notification = {
            "title": title,
            "body": message
        }

        data = {
            "destination_page": PageType.HOME,
            "image_url": JUNE22_PROMO_BANNER_DICT['email'][str(due_date_normal)]
        }

        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code)

        logger.info(response)
        return response

    def pn_tailor_backup(self, gcm_reg_id, account_payment, template_code, dpd):
        wink = u'\U0001F609'
        moneybag = u'\U0001F4B0'
        money_wing = u'\U0001F4B8'

        due_amount = display_rupiah(account_payment.due_amount)
        month_due_date = format_date(account_payment.due_date, 'MMMM', locale='id_ID')
        if dpd == -4:
            title = 'Bayar Lebih Awal, Untung Lebih Besar! ' + moneybag
            message = ("Yuk, bayar tagihan {} "
                       "bulan {} sekarang juga!".format(due_amount, month_due_date))
        elif dpd == -2:
            title = 'Ekstra Cashback menunggu Kamu! ' + wink
            message = ('Bayar tagihan {} bulan {} sekarang!'.format(due_amount, month_due_date))
        elif dpd == -1:
            title = 'Kesempatan Untuk Dapat Cashback Masih Ada Nih, Yuk Gercep! ' + moneybag
            message = ('Bayar angsuran bulan {} sekarang juga'.format(month_due_date))
        elif dpd == 0:
            title = 'Kesempatan Terakhir Untuk Dapat Cashback ' + money_wing
            message = ('Tagihan Anda telah jatuh tempo, lakukan pembayaran '
                       'hari ini & dapatkan cashbacknya!')
        else:
            return

        notification = {
            "title": title,
            "body": message
        }
        application = account_payment.account.application_set.last()
        customer = account_payment.account.customer
        data = {
            "destination_page": PageType.LOAN,
            "account_payment_id": account_payment.id,
            "customer_id": customer.id,
            "application_id": application.id
        }

        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code)

        logger.info(response)
        return response

    def credit_card_notification(self, customer, title, body, template_code,
                                 destination=PageType.HOME):
        device_query = customer.device_set.all()
        gcm_reg_id = device_query.order_by('cdate').values_list('gcm_reg_id', flat=True).last()
        notification = {
            "title": title,
            "body": body
        }
        data = {
            "destination_page": destination
        }
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code)

        logger.info(response)
        return response

    def checkout_notification(
            self, gcm_reg_id, template_code, destination=PageType.LOAN, commitment_amount=0):
        title = ''
        body = ''
        if template_code == 'pn_checkout_expired':
            title = 'Yah, Batas Waktu Pembayaran Sudah Habis ' + EMOTICON_LIST['face_sweat']
            body = 'Coba ulangi kembali proses pembayarannya, ya.'
        elif template_code == 'pn_checkout_cancelled':
            title = 'Pembayaranmu Dibatalkan ' + EMOTICON_LIST['cross_mark']
            body = 'Silakan lakukan checkout untuk melanjutkan ke proses pembayaran, ya.'
        elif template_code == 'pn_checkout_payfull':
            title = 'Asik, Pembayaran Berhasil! ' + EMOTICON_LIST['money_mouth'] + EMOTICON_LIST[
                'grinning_face']
            body = 'Hore! Tagihan sebesar {} sudah terbayar. Terima kasih, ya!'.format(
                display_rupiah(commitment_amount))
        elif template_code == 'pn_checkout_paylessfull':
            title = 'Asik, Bayar Tagihan Sebagian Berhasil! ' + EMOTICON_LIST['grinning_face']
            body = 'Jangan lupa untuk lunasi sebagiannya lagi, ya'
        elif template_code == 'pn_checkout_paymorefull':
            title = 'Ada Kelebihan dari Pembayaranmu, Lho! ' + EMOTICON_LIST['receipt']
            body = 'Tenang, kelebihannya kami alokasikan ke ' \
                   'tagihan lain atau masuk cashback kamu, kok!'
        if not title or not body:
            return

        notification = {
            "title": title,
            "body": body
        }
        data = {
            "destination_page": destination
        }
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code)

        logger.info(response)
        return response

    def pn_cashback_for_early_repayment(
            self, gcm_reg_id, template_code, customer_id, loan_ids=None, account_payment_ids=None):
        cashback = 0

        if template_code == 'pn_cashback_potential':
            potential_cashback_histories = PotentialCashbackHistory.objects.filter(
                account_payment_id__in=account_payment_ids,
                account_payment__due_amount__lte=0,
                is_pn_sent=False
            ).only('id', 'amount', 'is_pn_sent')

            if not potential_cashback_histories:
                return

            for item in potential_cashback_histories:
                cashback += item.amount

            if not cashback:
                return

            cashback = display_rupiah(cashback)

            title = 'Asik, Kamu Berpotensi Dapat Cashback!'
            body = 'Potensi cashback sebesar {} bisa kamu dapatkan karena kamu '\
                'bayar tagihan pada {} sebelum jatuh tempo'.format(
                    cashback, format_date(potential_cashback_histories.last().
                                          account_payment.paid_date, 'd MMMM yyyy', locale='id_ID'))
            destination = 'Loan'
            potential_cashback_histories.update(is_pn_sent=True)
        elif template_code == 'pn_cashback_claim':
            potential_cashback_histories = PotentialCashbackHistory.objects.filter(
                loan_id__in=loan_ids
            ).only('id', 'amount', 'is_pn_sent')

            if not potential_cashback_histories:
                return

            for item in potential_cashback_histories:
                cashback += item.amount

            if not cashback:
                return

            cashback = display_rupiah(cashback)
            title = 'Yeay, Cashback Kamu Sudah Masuk dan Siap Digunakan!'
            body = 'Kamu mendapatkan total cashback {}. ' \
                   'Manfaatkan cashback-nya, ya!'.format(cashback)
            destination = 'cashback_transaction'
        else:
            return

        notification = {
            "title": title,
            "body": body
        }
        data = {
            "destination_page": destination,
            "customer_id": customer_id
        }
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code)

        logger.info(response)
        return response

    def pn_julo_starter_master_agreement(self, gcm_reg_id):
        template_code = 'pn_julo_starter_master_agreement'
        title = 'Tandatangani ini, Dapatkan Limitmu!'
        body = 'Yuk, segera selesaikan prosesnya'

        notification = {
            "title": title,
            "body": body
        }

        data = {
            "destination_page": 'julo_starter_master_agreement'
        }

        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code)

        logger.info(response)
        return response

    def pn_julo_starter_eligibility(self, gcm_reg_id, template_code):
        if template_code == 'pn_eligibility_ok':
            title = 'Form-nya Udah Siap Diisi, Lho!'
            body = ('Yuk, isi segera agar proses pengajuannya cepat selesai dan '
                    'kamu langsung dapat limit JULO Turbo!')
            destination = 'julo_starter_eligbility_ok'
        elif template_code == 'pn_eligibility_j1_offer':
            title = 'Yah, Form JULO Turbo Tak Tersedia'
            body = ('Eits, kamu bisa ajukan pembuatan akun JULO Kredit Digital dengan '
                    'limit yang lebih besar, kok!')
            destination = 'julo_starter_eligbility_j1_offer'
        elif template_code == 'pn_eligbility_rejected':
            title = 'Yah, Form JULO Turbo Tak Tersedia'
            body = 'Siap-siap untuk coba ajukan lagi 31 hari ke depan, ya!'
            destination = 'julo_starter_eligbility_rejected'
        else:
            return

        notification = {
            "title": title,
            "body": body
        }

        data = {
            "destination_page": destination
        }

        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code)

        logger.info(response)
        return response

    def checks_and_scoring_notification_jstarter(self, gcm_reg_id, template_code, customer_id):

        template_data = get_data_notification_second_check(template_code)
        title = template_data[NotificationSetJStarter.KEY_TITLE]
        body = template_data[NotificationSetJStarter.KEY_BODY]
        destination = template_data[NotificationSetJStarter.KEY_DESTINATION]

        notification = {
            "title": title,
            "body": body
        }

        data = {
            "destination_page": destination,
            "customer_id": customer_id
        }

        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code)

        logger.info({
            "message": "Forward notification to third party",
            "template_code": template_code,
            "gcm_reg_id": gcm_reg_id,
            "process": "checks_and_scoring_notification_jstarter",
            "response": response
        })
        return response

    def pn_julo_starter_emulator_detection(self, gcm_reg_id, customer_id):
        template_code = 'pn_julo_starter_emulator_detection'
        title = 'non-popup'
        body = 'Application is ready to check emulator'

        notification = {
            "title": title,
            "body": body
        }

        data = {
            "destination_page": 'julo_starter_sphinx_passed',
            "customer_id": customer_id,
        }

        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code)

        logger.info({
            "template_code": template_code,
            "gcm_reg_id": gcm_reg_id,
            "process": "pn_julo_starter_emulator_detection",
            "response": response
        })
        return response

    def pn_non_popup(self, gcm_reg_id, data, template_code, **kwargs):
        process_name = kwargs.get('process', '')
        notification = {
            "title": "non-popup"
        }

        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code,
        )

        logger.info({
            "template_code": template_code,
            "gcm_reg_id": gcm_reg_id,
            "process": process_name,
            "response": response
        })
        return response

    def pn_loan_success_x220(self, gcm_reg_id, loan_xid, loan_amount):
        data = {
            'event': PushNotificationLoanEvent.LOAN_SUCCESS_X220,
            'loan_xid': loan_xid,
            'loan_amount': loan_amount,
            'body': 'Inform loan success 220',
        }
        return self.pn_non_popup(
            gcm_reg_id=gcm_reg_id,
            data=data,
            template_code='inform_loan_success_220',
            process_name='pn_loan_success_x220'
        )

    def pn_recall_repayment_success(self, gcm_reg_id, amount):
        template_code = 'pn_recall_repayment_success'
        title = 'Asik, Pembayaranmu Berhasil!{}'.format(EMOTICON_LIST['thumbs_up'])
        body = 'Makasih, ya. Tagihanmu Rp{} berhasil dibayar! '\
               'Cek pembayaran ini di Riwayat Pembayaran, oke?'.format(amount)

        notification = {
            "title": title,
            "body": body
        }

        data = {
            "destination_page": 'loan_activity'
        }

        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code)

        logger.info(response)
        return response

    def pn_downgrade_alert(self, gcm_reg_id, customer_id):
        data = {
            'event': PushNotificationDowngradeAlert.DOWNGRADE_INFO_ALERT,
            'customer_id': customer_id,
            'body': 'Invalidate downgrade alert',
        }
        return self.pn_non_popup(
            gcm_reg_id=gcm_reg_id,
            data=data,
            template_code='pn_downgrade_alert',
            process_name='pn_downgrade_alert'
        )

    def pn_autodebet_activated(self, account, gcm_reg_id):
        now = timezone.localtime(timezone.now())
        account_payments = account.accountpayment_set.not_paid_active().order_by('due_date')

        if not account_payments:
            return 'No payment due today'

        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.AUTODEBET_ACTIVATION_PN_CONFIG,
            is_active=True
        ).last()

        if not feature_setting or not feature_setting.parameters:
            return 'pn config feature not found'

        autodebet_account = get_existing_autodebet_account(account)
        due_amount = 0
        due_date = ''
        title = feature_setting.parameters.get('title').format(EMOTICON_LIST["party_popper"])
        next_unpaid_payment = account_payments.filter(due_date__gt=now.date()).first()

        if next_unpaid_payment:
            due_date = next_unpaid_payment.due_date
            due_amount = next_unpaid_payment.due_amount

            for account_payment in account_payments:
                if not account_payment.due_date <= now.date():
                    break
                due_amount += account_payment.due_amount
        elif account_payments.last().dpd <= 0:
            last_account_payment = account_payments.last()
            due_date = last_account_payment.due_date
            due_amount = last_account_payment.due_amount

        if autodebet_account.vendor in [VendorConst.BCA, VendorConst.BRI]:
            application = account.last_application
            body = feature_setting.parameters.get('pn_body').format(
                application.payday, display_rupiah(due_amount)
            )
        else:
            body = feature_setting.parameters.get('pn_body').format(
                due_date, display_rupiah(due_amount)
            )

        if not next_unpaid_payment or account_payments.last().dpd > 0:
            body = feature_setting.parameters.get('pn_late_account_payment_body')

        template_code = "pn_autodebet_activated"

        notification = {
            "title": title,
            "body": body
        }

        data = {
            'destination_page': PageType.LOAN
        }

        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code)

        logger.info({
            "template_code": template_code,
            "gcm_reg_id": gcm_reg_id,
            "process": "pn_autodebet_activated",
            "response": response
        })

        return response


    def pn_balance_consolidation_verification_approve(self, gcm_reg_id):
        data = {
            'event': PNBalanceConsolidationVerificationEvent.APPROVED_STATUS_EVENT,
            'body': 'The balance consolidation verification is approved',
        }
        return self.pn_non_popup(
            gcm_reg_id=gcm_reg_id,
            data=data,
            template_code='balance_consolidation_verification_status_update',
            process_name='pn_balance_consolidation_verification_approve'
        )

    def pn_gopay_autodebet_partial_repayment(self, customer, paid_amount):
        gcm_reg_id = customer.device_set.last().gcm_reg_id
        template_code = 'pn_gopay_autodebet_partial_repayment'
        title = 'Tagihan Rp{} Dibayar Pakai GoPay'.format(paid_amount)
        body = 'Yuk, top up saldo GoPay kamu lagi untuk membayar sisa tagihanmu bulan ini, ya!'

        notification = {
            "title": title,
            "body": body
        }

        data = {
            "destination_page": PageType.TAGIHAN,
            "customer_id": customer.id,
        }

        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code
        )

        logger.info({
            "template_code": template_code,
            "gcm_reg_id": gcm_reg_id,
            "process": "pn_gopay_autodebet_partial_repayment",
            "response": response
        })
        return response

    def pn_autodebet_insufficient_balance_turn_off(self, customer, vendor):
        device_query = customer.device_set.all()
        gcm_reg_id = device_query.order_by('cdate').values_list('gcm_reg_id', flat=True).last()
        template_code = 'ad{}_insufficient_balance_turn_off'.format(vendor.lower())
        if vendor == VendorConst.GOPAY:
            vendor = "GoPay"
        title = 'Autodebit {} Nonaktif Sementara!{}'.format(
            vendor, EMOTICON_LIST['face_screaming_in_fear']
        )
        body = (
            'Soalnya saldo rekeningmu kurang dari total tagihan yang harus dibayar. '
            'Yuk, aktifkan lagi sekarang!'
        )

        notification = {
            "title": title,
            "body": body
        }

        data = {
            "destination_page": 'autodebet_reactivate',
            "customer_id": customer.id,
        }

        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code)

        logger.info({
            "template_code": template_code,
            "gcm_reg_id": gcm_reg_id,
            "process": "ad{}_insufficient_balance_turn_off".format(vendor.lower()),
            "response": response
        })
        return response

    def unable_reactivate_autodebet(self, gcm_reg_id=None):
        template_code = 'unable_reactivate_autodebet'
        notification = {
            "title": "Update App untuk Reaktivasi Autodebet",
            "body": "Biar reaktivasi autodebet kamu lancar, update app JULO kamu dulu, yuk! {}" \
                .format(EMOTICON_LIST['wink'])
        }
        data = {
            "destination_page": PageType.HOME,
        }
        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code)

        logger.info({
            "template_code": template_code,
            "gcm_reg_id": gcm_reg_id,
            "process": "unable_reactivate_autodebet",
            "response": response
        })
        return response

    def pn_idfy_unfinished_autodebet_activation(self, customer, vendor):
        device_query = customer.device_set.all()
        gcm_reg_id = device_query.order_by('cdate').values_list('gcm_reg_id', flat=True).last()
        template_code = "ad{}_unfinished_activation".format(vendor.lower())
        title = 'Aktivasi Autodebit {} Jadi Lebih Mudah!{}'.format(
            vendor, EMOTICON_LIST['party_popper']
        )
        body = 'Sekarang aktivasi Autodebit {} bisa lewat video call, gak perlu ribet lagi! Klik di sini, ya.'.format(
            vendor
        )

        notification = {"title": title, "body": body}

        data = {
            "destination_page": PageType.AUTODEBET_IDFY,
        }

        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code,
        )

        logger.info(
            {
                "template_code": template_code,
                "gcm_reg_id": gcm_reg_id,
                "process": "pn_idfy_unfinished_autodebet_activation",
                "response": response,
            }
        )
        return response

    def pn_reactivation_success(self, gcm_reg_id):
        template_code = 'pn_notify_back_to_420'
        title = 'Asik, Kamu Bisa Transaksi Lagi!'
        body = 'Yuk, mulai transaksi barumu! Siapa tau ada promo yang bisa kamu gunakan juga!'

        notification = {"title": title, "body": body}

        data = {"destination_page": PageType.HOME}

        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code,
        )

        logger.info(
            {
                "template_code": template_code,
                "gcm_reg_id": gcm_reg_id,
                "process": "pn_reactivation_success",
                "response": response,
            }
        )
        return response

    def pn_point_change(self, gcm_reg_id, customer_id):
        data = {
            'event': PushNotificationPointChangeAlert.POINT_CHANGE_ALERT,
            'customer_id': customer_id,
            'body': 'Invalidate point change alert',
        }
        return self.pn_non_popup(
            gcm_reg_id=gcm_reg_id,
            data=data,
            template_code='pn_point_change_alert',
            process_name='pn_point_change_alert'
        )

    def pn_bri_bad_status_before_deduction(self, gcm_reg_id):
        template_code = 'pn_bri_bad_status_before_deduction'
        title = 'Yah, penarikan Autodebit BRI kamu gagal ' + EMOTICON_LIST['slightly_frowning_face']
        body = 'Bayar tagihanmu sekarang secara manual agar terhindar biaya keterlambatan. Setelah itu, periksa autodebit BRI kamu, oke?'

        notification = {"title": title, "body": body}

        data = {"destination_page": PageType.HOME}

        response = self.send_downstream_message(
            registration_ids=[gcm_reg_id],
            notification=notification,
            data=data,
            template_code=template_code,
        )

        logger.info(
            {
                "template_code": template_code,
                "gcm_reg_id": gcm_reg_id,
                "process": "pn_reactivation_success",
                "response": response,
            }
        )
        return response
