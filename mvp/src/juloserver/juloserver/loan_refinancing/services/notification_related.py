from builtins import str
from builtins import object
from builtins import range
from datetime import datetime
from wand.image import Image
from wand.drawing import Drawing
from wand.color import Color
import io
import logging
from django.template.loader import render_to_string
from juloserver.julo.clients import (
    get_julo_email_client,
    get_julo_sms_client,
    get_julo_pn_client,
    get_voice_client_v2,
    get_julo_perdana_sms_client,
)
from juloserver.julo.services2 import encrypt
from ..utils import convert_date_to_word
from ..constants import (
    CovidRefinancingConst,
    B5_EMAIL_TEMPLATE_MAPPING,
    B5_SMS_TEMPLATE_MAPPING,
    B5_SPECIAL_EMAIL_TEMPLATES,
)
from django.utils import timezone
from datetime import timedelta
from babel.dates import format_date
from juloserver.julo.utils import display_rupiah

from juloserver.julo.models import (
    PaymentMethod,
    EmailHistory,
    VoiceCallRecord,
    FeatureSetting,
)
from juloserver.pn_delivery.models import PNDelivery
from juloserver.loan_refinancing.constants import (
    LoanRefinancingConst,
    Campaign,
    CohortCampaignEmail,
    CohortCampaignPN,
)
from juloserver.loan_refinancing.models import WaiverRequest
from juloserver.julo.exceptions import JuloException
from juloserver.julo.constants import (
    VoiceTypeStatus,
    BucketConst,
)
from juloserver.julo.statuses import LoanStatusCodes
from argparse import Namespace
from django.db.models import (
    Q,
    F,
    Func,
    Sum,
)
from juloserver.loan_refinancing.models import LoanRefinancingRequestCampaign
from ...julo.payment_methods import PaymentMethodCodes
from juloserver.pii_vault.constants import (
    PiiSource,
    PiiVaultDataType,
)
from juloserver.minisquad.utils import collection_detokenize_sync_object_model
from juloserver.minisquad.constants import FeatureNameConst

logger = logging.getLogger(__name__)


def check_loan_refinancing_request_is_r4_spcecial_campaign_by_id(loan_refinancing_request_id):
    is_loan_refinancing_request_campaign = LoanRefinancingRequestCampaign.objects.filter(
        loan_refinancing_request_id=loan_refinancing_request_id,
        campaign_name=Campaign.COHORT_CAMPAIGN_NAME,
        expired_at__gte=datetime.today().date(),
    ).exists()

    return is_loan_refinancing_request_campaign


def check_loan_refinancing_with_requested_status_cohort_campaign(loan_refinancing_request_id):
    is_loan_refinancing_request_campaign = LoanRefinancingRequestCampaign.objects.filter(
        loan_refinancing_request_id=loan_refinancing_request_id,
        campaign_name=Campaign.COHORT_CAMPAIGN_NAME,
        expired_at__gte=datetime.today().date(),
        loan_refinancing_request__status=CovidRefinancingConst.STATUSES.requested,
    ).exists()

    return is_loan_refinancing_request_campaign


def check_sos_loan_refinancing(loan_refinancing_request_id):
    return LoanRefinancingRequestCampaign.objects.filter(
        loan_refinancing_request_id=loan_refinancing_request_id,
        campaign_name=Campaign.R1_SOS_REFINANCING_23,
        loan_refinancing_request__status=CovidRefinancingConst.STATUSES.approved,
    ).exists()


def check_loan_refinancing_request_is_r4_dpd_181_plus(loan_refinancing_request_id):
    return LoanRefinancingRequestCampaign.objects.filter(
        loan_refinancing_request_id=loan_refinancing_request_id,
        campaign_name=Campaign.COHORT_CAMPAIGN_DPD_181_PLUS,
        expired_at__gte=datetime.today().date(),
    ).exists()


def check_loan_refinancing_request_is_r4_dpd_181_plus_blast(loan_refinancing_request_id):
    promo_blast_fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.WAIVER_R4_PROMO_BLAST, is_active=True
    ).last()

    if not promo_blast_fs:
        return False

    parameters = promo_blast_fs.parameters
    campaign_name = parameters.get('campaign_automation', {}).get('campaign_name_list', [])
    return LoanRefinancingRequestCampaign.objects.filter(
        loan_refinancing_request_id=loan_refinancing_request_id,
        campaign_name__in=campaign_name,
        expired_at__gte=datetime.today().date(),
    ).exists()


def check_template_bucket_5(payment, template_code, template_type, is_for_j1=False):
    if not payment:
        return False, template_code
    due_late_days = payment.due_late_days if not is_for_j1 else payment.dpd
    if due_late_days >= BucketConst.BUCKET_5_DPD:
        if template_type == 'email':
            b5_template = B5_EMAIL_TEMPLATE_MAPPING.get(template_code)
            if b5_template:
                return True, b5_template
        elif template_type == 'sms':
            b5_template = B5_SMS_TEMPLATE_MAPPING.get(template_code)
            if b5_template:
                return True, b5_template
        elif template_type == 'crm_sending':
            return True, template_code
    elif template_code in B5_SPECIAL_EMAIL_TEMPLATES:
        if is_for_j1:
            application = payment.account.application_set.last()
        else:
            application = payment.loan.application

        check_b5_email_history = EmailHistory.objects.filter(
            application=application, template_code__in=list(B5_EMAIL_TEMPLATE_MAPPING.values())
        ).exists()
        if check_b5_email_history:
            return True, B5_SPECIAL_EMAIL_TEMPLATES[template_code]

    return False, template_code


class CovidLoanRefinancingEmail(object):
    def __init__(self, loan_refinancing_request):
        self._loan_refinancing_request = loan_refinancing_request
        self._account = self._loan_refinancing_request.account
        self._is_for_j1 = True if self._account else False
        self._email_client = get_julo_email_client()
        self._loan = loan_refinancing_request.loan
        if self._is_for_j1:
            self._application = self._account.application_set.last()
        else:
            self._application = self._loan.application
        self._customer = self._application.customer
        self._product_type = loan_refinancing_request.product_type
        self._status = loan_refinancing_request.status
        self._payment_method = self._get_customer_payment_method_for_refinancing()
        channel_list = self._loan_refinancing_request.comms_channel_list()
        self._validate_comms_channel = CovidRefinancingConst.COMMS_CHANNELS.email in channel_list
        self._channel = loan_refinancing_request.channel

    def send_approved_email(self):
        if not self._validate_comms_channel:
            return
        send_approved_email_method = self._get_loan_refinancing_product_method()
        send_approved_email_method['send_approved']()

    def send_activated_email(self):
        if not self._validate_comms_channel:
            return
        send_activated_email_method = self._get_loan_refinancing_product_method()
        send_activated_email_method['send_activated']()

    def send_offer_selected_email(self):
        if not self._validate_comms_channel:
            return

        send_refinancing_email_method = self._get_loan_refinancing_product_method()
        send_refinancing_email_method['send_offer_selected']()

    def send_opt_email(self):
        send_activated_email_method = self._get_loan_refinancing_product_method()
        send_activated_email_method['send_opt']()

    def send_pending_refinancing_email(self):
        send_activated_email_method = self._get_loan_refinancing_product_method()
        send_activated_email_method['send_pending_refinancing']()

    def send_offer_refinancing_email(self):
        if not self._validate_comms_channel:
            return
        send_offer_email_method = self._get_loan_refinancing_product_method()
        send_offer_email_method['send_offer']()

    def send_expiration_minus_2_email(self):
        from ..services.loan_related import get_unpaid_payments
        from juloserver.account_payment.services.account_payment_related import (
            get_unpaid_account_payment,
        )

        # block refinancing DPD 181+
        if check_loan_refinancing_request_is_r4_dpd_181_plus(self._loan_refinancing_request.id):
            return
        if check_loan_refinancing_request_is_r4_dpd_181_plus_blast(
            self._loan_refinancing_request.id
        ):
            return

        if not self._validate_comms_channel:
            return

        if self._is_for_j1:
            ordered_unpaid_payments = get_unpaid_account_payment(self._account.id)
        else:
            ordered_unpaid_payments = get_unpaid_payments(self._loan, order_by='payment_number')

        first_unpaid_payment = ordered_unpaid_payments[0]

        if check_loan_refinancing_request_is_r4_spcecial_campaign_by_id(
            self._loan_refinancing_request.id
        ):
            subject = CohortCampaignEmail.SUBJECT_R4_2
        else:
            subject = 'Satu langkah lagi menuju keringanan pinjaman, bayar sebelum {}'.format(
                format_date(
                    self._loan_refinancing_request.first_due_date, 'd MMMM yyyy', locale='id_ID'
                )
            )
        customer_info, _ = self._construct_email_params(None)
        template, template_code, calendar_link = self._get_reminder_template(2)

        # update template for bucket 5
        is_bucket_5, template_code = check_template_bucket_5(
            first_unpaid_payment, template_code, 'email'
        )

        parameters = self._email_client.email_base(
            self._loan_refinancing_request,
            subject,
            template,
            calendar_link=calendar_link,
            customer_info=customer_info,
            is_bucket_5=is_bucket_5,
            is_for_j1=self._is_for_j1,
        )
        parameters = parameters[:-1] + (template_code, first_unpaid_payment)
        self._create_email_history(*parameters)

    def send_expiration_minus_1_email(self):
        from ..services.loan_related import get_unpaid_payments
        from juloserver.account_payment.services.account_payment_related import (
            get_unpaid_account_payment,
        )

        # block refinancing DPD 181+
        if check_loan_refinancing_request_is_r4_dpd_181_plus(self._loan_refinancing_request.id):
            return
        if check_loan_refinancing_request_is_r4_dpd_181_plus_blast(
            self._loan_refinancing_request.id
        ):
            return

        if not self._validate_comms_channel:
            return

        if self._is_for_j1:
            ordered_unpaid_payments = get_unpaid_account_payment(self._account.id)
        else:
            ordered_unpaid_payments = get_unpaid_payments(self._loan, order_by='payment_number')

        first_unpaid_payment = ordered_unpaid_payments[0]

        if check_loan_refinancing_request_is_r4_spcecial_campaign_by_id(
            self._loan_refinancing_request.id
        ):
            subject = CohortCampaignEmail.SUBJECT_R4_3
        else:
            subject = '[TINGGAL SELANGKAH LAGI] Lakukan pembayaran sekarang untuk aktivasi program'

        customer_info, _ = self._construct_email_params(None)
        template, template_code, calendar_link = self._get_reminder_template(1)

        # update template for bucket 5
        is_bucket_5, template_code = check_template_bucket_5(
            first_unpaid_payment, template_code, 'email', is_for_j1=self._is_for_j1
        )

        parameters = self._email_client.email_base(
            self._loan_refinancing_request,
            subject,
            template,
            calendar_link=calendar_link,
            customer_info=customer_info,
            is_bucket_5=is_bucket_5,
            is_for_j1=self._is_for_j1,
        )
        parameters = parameters[:-1] + (template_code, first_unpaid_payment)
        self._create_email_history(*parameters)

    def send_reminder_email(self):
        if not self._validate_comms_channel:
            return
        send_reminder_email_method = self._get_loan_refinancing_product_method()
        send_reminder_email_method['send_reminder']()

    def send_proactive_email(self, status=None, day=None):
        from ..services.loan_related import get_unpaid_payments
        from juloserver.account_payment.services.account_payment_related import (
            get_unpaid_account_payment,
        )

        if self._loan_refinancing_request.channel != CovidRefinancingConst.CHANNELS.proactive:
            return

        if self._status == CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_email:
            template_code = "emailsent_offer_first_email"
            subject = "JULO memahami kondisi keuangan Anda. Ajukan restrukturisasi sekarang."
            if status == "email_open":
                template_code = "emailsent_open_offer_first_email"
                subject = "Anda berkesempatan mendapat keringanan pinjaman JULO!"
                if day == 4:
                    template_code = "emailsent_open_offer_second_email"
                    subject = "Jangan lewatkan kesempatan mendapatkan keringanan pinjaman JULO!"
        elif self._status == CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_submit:
            template_code = "formviewed_offer_first_email"
            subject = "Program keringanan pinjaman menanti! Lengkapi data Anda."
        elif self._status == CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_offer:
            template_code = "offergenerated_first_email"
            subject = "MAU CICILAN LEBIH RINGAN? Ajukan program keringanan sekarang! "

        if self._is_for_j1:
            payments = get_unpaid_account_payment(self._account.id)
        else:
            payments = get_unpaid_payments(self._loan, order_by='payment_number')

        first_unpaid_payment = payments[0]

        # update template for bucket 5
        is_bucket_5, template_code = check_template_bucket_5(
            first_unpaid_payment, template_code, 'email', is_for_j1=self._is_for_j1
        )

        parameters = self._email_client.email_proactive_refinancing_reminder(
            self._loan_refinancing_request, subject, template_code, is_bucket_5
        )
        self._create_email_history(*(parameters + (first_unpaid_payment,)))

    def send_offer_selected_minus_1_email_reminder(self):
        from ..services.loan_related import get_unpaid_payments
        from juloserver.account_payment.services.account_payment_related import (
            get_unpaid_account_payment,
        )

        if not self._validate_comms_channel:
            return
        if (
            self._product_type in CovidRefinancingConst.waiver_products()
            and self._channel == CovidRefinancingConst.CHANNELS.reactive
        ):
            return

        subject = (
            '[KESEMPATAN TERAKHIR] Tinggal Sedikit Lagi! Konfirmasi program '
            'keringanan Anda hari ini'
        )
        template_code = 'offerselected_third_email'

        if self._is_for_j1:
            ordered_unpaid_payments = get_unpaid_account_payment(self._account.id)
        else:
            ordered_unpaid_payments = get_unpaid_payments(self._loan, order_by='payment_number')

        first_unpaid_payment = ordered_unpaid_payments[0]

        # update template for bucket 5
        is_bucket_5, template_code = check_template_bucket_5(
            first_unpaid_payment, template_code, 'email', is_for_j1=self._is_for_j1
        )

        parameters = self._email_client.email_refinancing_offer_selected(
            self._loan_refinancing_request,
            subject,
            template_code,
            is_bucket_5,
            is_for_j1=self._is_for_j1,
        )
        self._create_email_history(*(parameters + (first_unpaid_payment,)))

    def send_offer_selected_minus_2_email_reminder(self):
        from ..services.loan_related import get_unpaid_payments
        from juloserver.account_payment.services.account_payment_related import (
            get_unpaid_account_payment,
        )

        if not self._validate_comms_channel:
            return
        if (
            self._product_type in CovidRefinancingConst.waiver_products()
            and self._channel == CovidRefinancingConst.CHANNELS.reactive
        ):
            return

        subject = '[TINGGAL SELANGKAH LAGI] Konfirmasi program keringanan sebelum {}'.format(
            format_date(
                self._loan_refinancing_request.first_due_date, 'd MMMM yyyy', locale='id_ID'
            )
        )
        template_code = 'offerselected_second_email'
        if self._is_for_j1:
            ordered_unpaid_payments = get_unpaid_account_payment(self._account.id)
        else:
            ordered_unpaid_payments = get_unpaid_payments(self._loan, order_by='payment_number')

        first_unpaid_payment = ordered_unpaid_payments[0]

        # update template for bucket 5
        is_bucket_5, template_code = check_template_bucket_5(
            first_unpaid_payment, template_code, 'email', is_for_j1=self._is_for_j1
        )

        parameters = self._email_client.email_refinancing_offer_selected(
            self._loan_refinancing_request,
            subject,
            template_code,
            is_bucket_5,
            is_for_j1=self._is_for_j1,
        )
        self._create_email_history(*(parameters + (first_unpaid_payment,)))

    def send_multiple_payment_ptp_email(self):
        if self._status != CovidRefinancingConst.STATUSES.approved:
            return

        if not self._loan_refinancing_request.is_multiple_ptp_payment:
            return

        subject = 'Kesepakatan dengan agen JULO tentang program keringanan pembayaran'
        template = 'waiver/immediate_multiple_ptp_payment.html'
        template_code = 'immediate_multiple_ptp_payment'

        customer_info, payment_info = self._construct_email_params(None)
        if self._is_for_j1:
            first_unpaid_payment = self._account.get_oldest_unpaid_account_payment()
        else:
            first_unpaid_payment = self._loan.get_oldest_unpaid_payment()
        payment_info['is_bucket_5'], template_code = check_template_bucket_5(
            first_unpaid_payment, template_code, 'email', is_for_j1=self._is_for_j1
        )
        payment_info[
            "multiple_payment_ptp"
        ] = self._loan_refinancing_request.waiverrequest_set.last().unpaid_multiple_payment_ptp()
        payment_info['total_remaining_amount'] = (
            payment_info["multiple_payment_ptp"].aggregate(total=Sum('remaining_amount'))["total"]
            or 0
        )

        parameters = self._email_client.email_multiple_payment_ptp(
            customer_info, payment_info, subject, template
        )
        self._create_email_history(*(parameters + (template_code, first_unpaid_payment)))

    def send_multiple_payment_minus_expiry_email(self):
        if self._status != CovidRefinancingConst.STATUSES.approved:
            return

        if not self._loan_refinancing_request.is_multiple_ptp_payment:
            return

        subject = 'Sehari sebelum masa berlaku program keringanan berakhir'
        template = 'waiver/multiple_ptp_expiry_date.html'
        template_code = 'multiple_ptp_1_day_expiry_date'

        customer_info, payment_info = self._construct_email_params(None)
        if self._is_for_j1:
            first_unpaid_payment = self._account.get_oldest_unpaid_account_payment()
        else:
            first_unpaid_payment = self._loan.get_oldest_unpaid_payment()

        payment_info['is_bucket_5'], template_code = check_template_bucket_5(
            first_unpaid_payment, template_code, 'email', is_for_j1=self._is_for_j1
        )
        multiple_payment_ptp = (
            self._loan_refinancing_request.waiverrequest_set.last().ordered_multiple_payment_ptp()
        )
        payment_info["multiple_payment_ptp"] = multiple_payment_ptp
        payment_info["total_remaining_amount"] = (
            multiple_payment_ptp.aggregate(total=Sum('remaining_amount'))["total"] or 0
        )
        payment_info['is_on_promised_date'] = False

        if not self._validate_email_send_for_multiple_payment_ptp(
            False, first_unpaid_payment, multiple_payment_ptp.last()
        ):
            return

        parameters = self._email_client.email_multiple_payment_ptp(
            customer_info, payment_info, subject, template
        )
        self._create_email_history(*(parameters + (template_code, first_unpaid_payment)))

    def send_multiple_payment_expiry_email(self):
        if self._status != CovidRefinancingConst.STATUSES.approved:
            return

        if not self._loan_refinancing_request.is_multiple_ptp_payment:
            return

        subject = 'Masa berlaku program keringanan berakhir hari ini'
        template = 'waiver/multiple_ptp_expiry_date.html'
        template_code = 'multiple_ptp_on_expiry_date'

        customer_info, payment_info = self._construct_email_params(None)
        if self._is_for_j1:
            first_unpaid_payment = self._account.get_oldest_unpaid_account_payment()
        else:
            first_unpaid_payment = self._loan.get_oldest_unpaid_payment()

        payment_info['is_bucket_5'], template_code = check_template_bucket_5(
            first_unpaid_payment, template_code, 'email', is_for_j1=self._is_for_j1
        )
        multiple_payment_ptp = (
            self._loan_refinancing_request.waiverrequest_set.last().ordered_multiple_payment_ptp()
        )
        payment_info["multiple_payment_ptp"] = multiple_payment_ptp
        payment_info["total_remaining_amount"] = (
            multiple_payment_ptp.aggregate(total=Sum('remaining_amount'))["total"] or 0
        )
        payment_info['is_on_promised_date'] = True

        if not self._validate_email_send_for_multiple_payment_ptp(
            True, first_unpaid_payment, multiple_payment_ptp.last()
        ):
            return

        parameters = self._email_client.email_multiple_payment_ptp(
            customer_info, payment_info, subject, template
        )
        self._create_email_history(*(parameters + (template_code, first_unpaid_payment)))

    def _get_reminder_template(self, due_to_expired):
        calendar_link = self._generate_google_calendar_link()
        if self._product_type in CovidRefinancingConst.reactive_products():
            if due_to_expired == 2:
                return (
                    'covid_refinancing/refinancing_product_approved_reminder_email_2.html',
                    'approved_second_email_R1R2R3',
                    calendar_link,
                )
            elif due_to_expired == 1:
                return (
                    'covid_refinancing/refinancing_product_approved_reminder_email_1.html',
                    'approved_third_email_R1R2R3',
                    calendar_link,
                )

        if self._product_type == CovidRefinancingConst.PRODUCTS.r4:
            is_loan_refinancing_request_campaign = (
                check_loan_refinancing_request_is_r4_spcecial_campaign_by_id(
                    self._loan_refinancing_request.id
                )
            )
            if due_to_expired == 2:
                if is_loan_refinancing_request_campaign:
                    return (
                        'covid_refinancing/covid_r4_special_cohort_minus2_email.html',
                        CohortCampaignEmail.TEMPLATE_CODE_R4_2,
                        calendar_link,
                    )
                else:
                    return (
                        'covid_refinancing/r4_approved_reminder_email_2.html',
                        'approved_second_email_R4',
                        calendar_link,
                    )
            elif due_to_expired == 1:
                if is_loan_refinancing_request_campaign:
                    return (
                        'covid_refinancing/covid_r4_special_cohort_minus1_email.html',
                        CohortCampaignEmail.TEMPLATE_CODE_R4_3,
                        calendar_link,
                    )
                else:
                    return (
                        'covid_refinancing/r4_approved_reminder_email_1.html',
                        'approved_third_email_R4',
                        calendar_link,
                    )

        if self._product_type in (
            CovidRefinancingConst.PRODUCTS.r5,
            CovidRefinancingConst.PRODUCTS.r6,
        ):
            if due_to_expired == 2:
                return (
                    'covid_refinancing/r5r6_approved_reminder_email_2.html',
                    'approved_second_email_R5R6',
                    calendar_link,
                )
            elif due_to_expired == 1:
                return (
                    'covid_refinancing/r5r6_approved_reminder_email_1.html',
                    'approved_third_email_R5R6',
                    calendar_link,
                )

        if self._status == CovidRefinancingConst.STATUSES.requested:
            if due_to_expired == 2:
                return (
                    'covid_refinancing/requested_status_special_cohort_minus_2_email.html',
                    CohortCampaignEmail.TEMPLATE_CODE_OTHER_REFINANCING_2,
                    calendar_link,
                )
            elif due_to_expired == 1:
                return (
                    'covid_refinancing/requested_status_special_cohort_minus_1_email.html',
                    CohortCampaignEmail.TEMPLATE_CODE_OTHER_REFINANCING_3,
                    calendar_link,
                )

        raise ValueError('template for product %s is not found' % self._product_type)

    def _get_loan_refinancing_product_method(self):
        if self._status == CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_email:
            return {
                'send_opt': self._send_opt_email_p1,
            }
        if self._product_type == CovidRefinancingConst.PRODUCTS.r1:
            return {
                'send_approved': self._send_approved_email_r1,
                'send_activated': self._send_activated_email_r1,
                'send_offer_selected': self._send_offer_selected_refinancing,
                'send_pending_refinancing': self._send_pending_loan_refinancing,
                'send_opt': self._send_confirmation_email,
                'send_reminder': self._send_reminder_email,
            }
        if self._product_type == CovidRefinancingConst.PRODUCTS.r2:
            return {
                'send_approved': self._send_approved_email_r2,
                'send_activated': self._send_activated_email_r2,
                'send_offer_selected': self._send_offer_selected_refinancing,
                'send_pending_refinancing': self._send_pending_loan_refinancing,
                'send_opt': self._send_confirmation_email,
                'send_reminder': self._send_reminder_email,
            }
        if self._product_type == CovidRefinancingConst.PRODUCTS.r3:
            return {
                'send_approved': self._send_approved_email_r3,
                'send_activated': self._send_activated_email_r3,
                'send_offer_selected': self._send_offer_selected_refinancing,
                'send_pending_refinancing': self._send_pending_loan_refinancing,
                'send_opt': self._send_confirmation_email,
                'send_reminder': self._send_reminder_email,
            }
        if self._product_type in CovidRefinancingConst.waiver_products():
            return {
                'send_approved': self._send_approved_email_waiver,
                'send_opt': self._send_confirmation_email,
                'send_activated': self._send_activated_email_waiver_products,
                'send_offer_selected': self._send_offer_selected_waiver,
                'send_pending_refinancing': self._send_pending_loan_refinancing,
                'send_reminder': self._send_reminder_email,
            }
        if self._status == CovidRefinancingConst.STATUSES.requested:
            return {'send_offer': self._send_requested_status_campaign_email}

        raise ValueError(
            "Product not found with id %s, status %s, product type %s"
            % (self._loan_refinancing_request.id, self._status, self._product_type)
        )

    def _send_activated_email_r1(self):
        from ..services.loan_related import (
            get_unpaid_payments_after_restructure,
            get_unpaid_account_payments_after_restructure,
        )
        from juloserver.julo.services import get_google_calendar_for_email_reminder

        subject = 'Selamat! Pembayaran Anda diterima dan program keringanan berhasil diproses'
        template = 'covid_refinancing/covid_reactive_product_activated_email.html'
        if self._is_for_j1:
            ordered_unpaid_payments = get_unpaid_account_payments_after_restructure(
                self._account, order_by='due_date'
            )
        else:
            ordered_unpaid_payments = get_unpaid_payments_after_restructure(
                self._loan, order_by='payment_number'
            )

        first_unpaid_payment = ordered_unpaid_payments[0]
        _, _, calendar_link = get_google_calendar_for_email_reminder(
            self._application, is_for_j1=self._is_for_j1
        )

        parameters = self._email_client.email_covid_refinancing_activated_for_all_product(
            self._customer,
            subject,
            template,
            ordered_unpaid_payments,
            calendar_link,
            is_for_j1=self._is_for_j1,
        )
        self._create_email_history(*(parameters + (first_unpaid_payment,)))

    def _send_activated_email_r2(self):
        from ..services.loan_related import (
            get_unpaid_payments_after_restructure,
            get_unpaid_account_payments_after_restructure,
        )
        from juloserver.julo.services import get_google_calendar_for_email_reminder

        subject = 'Selamat! Pembayaran Anda diterima dan program keringanan berhasil diproses'
        template = 'covid_refinancing/covid_reactive_product_activated_email.html'
        if self._is_for_j1:
            ordered_unpaid_payments = get_unpaid_account_payments_after_restructure(
                self._account, order_by='due_date'
            )
        else:
            ordered_unpaid_payments = get_unpaid_payments_after_restructure(
                self._loan, order_by='payment_number'
            )
        first_unpaid_payment = ordered_unpaid_payments[0]
        _, _, calendar_link = get_google_calendar_for_email_reminder(
            self._application, is_for_j1=self._is_for_j1
        )

        parameters = self._email_client.email_covid_refinancing_activated_for_all_product(
            self._customer,
            subject,
            template,
            ordered_unpaid_payments,
            calendar_link,
            is_for_j1=self._is_for_j1,
        )
        self._create_email_history(*(parameters + (first_unpaid_payment,)))

    def _send_activated_email_r3(self):
        from ..services.loan_related import (
            get_unpaid_payments_after_restructure,
            get_unpaid_account_payments_after_restructure,
        )
        from juloserver.julo.services import get_google_calendar_for_email_reminder

        subject = 'Selamat! Pembayaran Anda diterima dan program keringanan berhasil diproses'
        template = 'covid_refinancing/covid_reactive_product_activated_email.html'

        if self._is_for_j1:
            ordered_unpaid_payments = get_unpaid_account_payments_after_restructure(
                self._account, order_by='due_date'
            )
        else:
            ordered_unpaid_payments = get_unpaid_payments_after_restructure(
                self._loan, order_by='payment_number'
            )

        first_unpaid_payment = ordered_unpaid_payments[0]
        _, _, calendar_link = get_google_calendar_for_email_reminder(
            self._application, is_for_j1=self._is_for_j1
        )

        parameters = self._email_client.email_covid_refinancing_activated_for_all_product(
            self._customer,
            subject,
            template,
            ordered_unpaid_payments,
            calendar_link,
            is_for_j1=self._is_for_j1,
        )
        self._create_email_history(*(parameters + (first_unpaid_payment,)))

    def _send_offer_selected_refinancing(self):
        from ..services.loan_related import get_unpaid_payments
        from juloserver.account_payment.services.account_payment_related import (
            get_unpaid_account_payment,
        )

        subject = 'Program Restrukturasi Pinjaman Sedang Diproses'
        template_code = (
            'offerselected_first_email_R1'
            if self._product_type == CovidRefinancingConst.PRODUCTS.r1
            else "offerselected_first_email_R2R3"
        )
        if self._is_for_j1:
            ordered_unpaid_payment_or_account_payments = get_unpaid_account_payment(
                self._account.id
            )
        else:
            ordered_unpaid_payment_or_account_payments = get_unpaid_payments(
                self._loan, order_by='payment_number'
            )

        first_unpaid_payment_or_account_payment = ordered_unpaid_payment_or_account_payments[0]
        parameters = self._email_client.email_refinancing_offer_selected(
            self._loan_refinancing_request, subject, template_code, is_for_j1=self._is_for_j1
        )
        self._create_email_history(*(parameters + (first_unpaid_payment_or_account_payment,)))

    def _send_offer_selected_waiver(self):
        from ..services.loan_related import get_unpaid_payments
        from juloserver.account_payment.services.account_payment_related import (
            get_unpaid_account_payment,
        )

        subject = 'Program Restrukturasi Pinjaman Sedang Diproses'
        template_code = 'offerselected_first_email_R4'

        if self._is_for_j1:
            ordered_unpaid_payments = get_unpaid_account_payment(self._account.id)
        else:
            ordered_unpaid_payments = get_unpaid_payments(self._loan, order_by='payment_number')

        first_unpaid_payment = ordered_unpaid_payments[0]

        # update template for bucket 5
        is_bucket_5, template_code = check_template_bucket_5(
            first_unpaid_payment, template_code, 'email', is_for_j1=self._is_for_j1
        )

        parameters = self._email_client.email_refinancing_offer_selected(
            self._loan_refinancing_request,
            subject,
            template_code,
            is_bucket_5,
            is_for_j1=self._is_for_j1,
        )
        self._create_email_history(*(parameters + (first_unpaid_payment,)))

    def _send_approved_email_r1(self):
        from ..services.loan_related import (
            get_unpaid_payments,
            construct_tenure_probabilities,
        )
        from juloserver.account_payment.services.account_payment_related import (
            get_unpaid_account_payment,
        )
        from ..services.refinancing_product_related import get_max_tenure_extension_r1
        from juloserver.refinancing.services import generate_new_payment_structure

        max_tenure_extension = get_max_tenure_extension_r1(self._loan_refinancing_request)
        if self._is_for_j1:
            ordered_unpaid_payments = get_unpaid_account_payment(self._account.id)
            max_tenure_extension += self._account.sum_of_all_active_loan_duration()
        else:
            ordered_unpaid_payments = get_unpaid_payments(self._loan, order_by='payment_number')
            max_tenure_extension += self._loan.loan_duration

        if not max_tenure_extension:
            raise JuloException('Loan is not eligible since num of payments do not match')

        first_unpaid_payment = ordered_unpaid_payments[0]

        loan_duration = (
            ordered_unpaid_payments.count() + self._loan_refinancing_request.loan_duration
        )
        real_loan_duration = 0
        loan_duration_to_save = 0

        if loan_duration > max_tenure_extension:
            loan_duration_to_save = max_tenure_extension - self._loan.loan_duration
            real_loan_duration = max_tenure_extension
        else:
            loan_duration_to_save = self._loan_refinancing_request.loan_duration
            real_loan_duration = loan_duration

        first_installment = LoanRefinancingConst.FIRST_LOAN_REFINANCING_INSTALLMENT
        if self._is_for_j1 and self._loan_refinancing_request.product_type:
            _, new_payment_structures, late_fee_discount = generate_new_payment_structure(
                self._loan_refinancing_request.account,
                self._loan_refinancing_request,
                chosen_loan_duration=real_loan_duration,
                is_with_latefee_discount=True,
            )
            prerequisite_amount = new_payment_structures[first_installment]['due_amount']
        else:
            new_payment_structures = construct_tenure_probabilities(
                ordered_unpaid_payments, max_tenure_extension, self._loan_refinancing_request
            )
            late_fee_discount = new_payment_structures['late_fee_amount']
            prerequisite_amount = new_payment_structures[real_loan_duration][first_installment][
                'due_amount'
            ]
            new_payment_structures = new_payment_structures[real_loan_duration]

        self._loan_refinancing_request.update_safely(
            prerequisite_amount=prerequisite_amount,
            total_latefee_discount=late_fee_discount,
            status=CovidRefinancingConst.STATUSES.approved,
            loan_duration=loan_duration_to_save,
        )

        date_ref = self._loan_refinancing_request.request_date
        if self._loan_refinancing_request.form_submitted_ts:
            date_ref = timezone.localtime(self._loan_refinancing_request.form_submitted_ts).date()

        new_payment_structures[0]['due_date'] = date_ref + timedelta(
            days=self._loan_refinancing_request.expire_in_days
        )
        customer_info, payment_info = self._construct_email_params(new_payment_structures)
        subject = 'Menunggu Pembayaran untuk Aktivasi Program Keringanan '
        template = 'covid_refinancing/covid_refinancing_product_approved_email.html'
        parameters = self._email_client.email_covid_refinancing_approved_for_all_product(
            customer_info, payment_info, subject, template, self._generate_google_calendar_link()
        )
        self._create_email_history(*(parameters + (first_unpaid_payment,)))

    def _send_approved_email_r2(self):
        from ..services.refinancing_product_related import construct_new_payments_for_r2
        from ..services.loan_related import get_unpaid_payments
        from juloserver.account_payment.services.account_payment_related import (
            get_unpaid_account_payment,
        )
        from juloserver.refinancing.services import generate_new_payment_structure

        if self._is_for_j1:
            ordered_unpaid_payments = get_unpaid_account_payment(self._account.id)
        else:
            ordered_unpaid_payments = get_unpaid_payments(self._loan, order_by='payment_number')

        first_unpaid_payment = ordered_unpaid_payments[0]
        if self._is_for_j1 and self._loan_refinancing_request.product_type:
            _, new_payment_structures, total_latefee_discount = generate_new_payment_structure(
                self._loan_refinancing_request.account,
                self._loan_refinancing_request,
                count_unpaid_account_payments=len(ordered_unpaid_payments),
                is_with_latefee_discount=True,
            )
            self._loan_refinancing_request.update_safely(
                prerequisite_amount=new_payment_structures[0]['due_amount'],
                status=CovidRefinancingConst.STATUSES.approved,
                total_latefee_discount=total_latefee_discount,
            )
        else:
            new_payment_structures = construct_new_payments_for_r2(
                self._loan_refinancing_request, ordered_unpaid_payments, simulate=True
            )

        customer_info, payment_info = self._construct_email_params(new_payment_structures)
        subject = 'Menunggu Pembayaran untuk Aktivasi Program Keringanan '
        template = 'covid_refinancing/covid_refinancing_product_approved_email.html'
        parameters = self._email_client.email_covid_refinancing_approved_for_all_product(
            customer_info, payment_info, subject, template, self._generate_google_calendar_link()
        )
        self._create_email_history(*(parameters + (first_unpaid_payment,)))

    def _send_approved_email_r3(self):
        from ..services.refinancing_product_related import construct_new_payments_for_r3
        from ..services.loan_related import get_unpaid_payments
        from juloserver.account_payment.services.account_payment_related import (
            get_unpaid_account_payment,
        )
        from juloserver.refinancing.services import generate_new_payment_structure

        if self._is_for_j1:
            ordered_unpaid_payments = get_unpaid_account_payment(self._account.id)
        else:
            ordered_unpaid_payments = get_unpaid_payments(self._loan, order_by='payment_number')

        first_unpaid_payment = ordered_unpaid_payments[0]
        if self._is_for_j1 and self._loan_refinancing_request.product_type:
            _, new_payment_structures, total_latefee_discount = generate_new_payment_structure(
                self._loan_refinancing_request.account,
                self._loan_refinancing_request,
                count_unpaid_account_payments=len(ordered_unpaid_payments),
                is_with_latefee_discount=True,
            )
        else:
            new_payment_structures = construct_new_payments_for_r3(
                self._loan_refinancing_request, ordered_unpaid_payments
            )
            total_latefee_discount = new_payment_structures['total_latefee_amount']
            new_payment_structures = new_payment_structures['payments']
        first_installment = LoanRefinancingConst.FIRST_LOAN_REFINANCING_INSTALLMENT
        self._loan_refinancing_request.update_safely(
            prerequisite_amount=new_payment_structures[first_installment]['due_amount'],
            total_latefee_discount=total_latefee_discount,
            status=CovidRefinancingConst.STATUSES.approved,
        )

        customer_info, payment_info = self._construct_email_params(new_payment_structures)
        subject = 'Menunggu Pembayaran untuk Aktivasi Program Keringanan '
        template = 'covid_refinancing/covid_refinancing_product_approved_email.html'
        parameters = self._email_client.email_covid_refinancing_approved_for_all_product(
            customer_info, payment_info, subject, template, self._generate_google_calendar_link()
        )
        self._create_email_history(*(parameters + (first_unpaid_payment,)))

    def _send_approved_email_waiver(self):
        if self._is_for_j1:
            first_unpaid_payment = self._account.get_oldest_unpaid_account_payment()
        else:
            first_unpaid_payment = self._loan.get_oldest_unpaid_payment()

        total_payments = 0
        is_loan_refinancing_request_campaign = False
        subject = 'Menunggu Pembayaran untuk Aktivasi Program Keringanan '
        if self._loan_refinancing_request.product_type == CovidRefinancingConst.PRODUCTS.r4:
            is_loan_refinancing_request_campaign = (
                check_loan_refinancing_request_is_r4_spcecial_campaign_by_id(
                    self._loan_refinancing_request.id
                )
            )
            if is_loan_refinancing_request_campaign:
                template = 'covid_refinancing/covid_r4_special_cohort_approved_email.html'
                template_code = CohortCampaignEmail.TEMPLATE_CODE_R4_1
                subject = CohortCampaignEmail.SUBJECT_R4_1
            else:
                template = 'covid_refinancing/covid_r4_approved_email.html'
                template_code = 'approved_first_email_R4'

        else:
            template = 'covid_refinancing/covid_r5_r6_approved_email.html'
            template_code = 'approved_first_email_R5R6'

        waiver_request_filter = {}
        if self._is_for_j1:
            waiver_request_filter['account'] = self._account
        else:
            waiver_request_filter['loan_id'] = self._loan.id

        waiver_request = WaiverRequest.objects.filter(**waiver_request_filter).last()
        if waiver_request:
            total_payments = waiver_request.outstanding_amount

        self._loan_refinancing_request.update_safely(
            status=CovidRefinancingConst.STATUSES.approved
        )

        customer_info, payment_info = self._construct_email_params(
            self._loan_refinancing_request.last_prerequisite_amount
        )

        payment_info["total_payments"] = total_payments

        # update template for bucket 5
        is_bucket_5, template_code = check_template_bucket_5(
            first_unpaid_payment, template_code, 'email', is_for_j1=self._is_for_j1)

        parameters = self._email_client.email_covid_refinancing_approved_for_r4(
            customer_info, payment_info, subject,
            template, self._generate_google_calendar_link(),
            is_bucket_5)
        self._create_email_history(*(parameters + (template_code, first_unpaid_payment)))

    def _send_opt_email_p1(self):
        from ..services.loan_related import (
            get_unpaid_payments,
            construct_tenure_probabilities,
        )
        from ..services.refinancing_product_related import get_max_tenure_extension_r1
        from juloserver.account_payment.services.account_payment_related import \
            get_unpaid_account_payment
        max_tenure_extension = get_max_tenure_extension_r1(self._loan_refinancing_request)
        if self._is_for_j1:
            ordered_unpaid_payments = get_unpaid_account_payment(self._account.id)
            max_tenure_extension += self._account.sum_of_all_active_loan_duration()
        else:
            ordered_unpaid_payments = get_unpaid_payments(self._loan, order_by='payment_number')
            max_tenure_extension += self._loan.loan_duration

        first_unpaid_payment = ordered_unpaid_payments[0]
        if not max_tenure_extension:
            raise JuloException('Loan is not eligible since num of payments do not match')

        loan_duration = ordered_unpaid_payments.count() + \
                        self._loan_refinancing_request.loan_duration

        if loan_duration > max_tenure_extension:
            real_loan_duration = max_tenure_extension
        else:
            real_loan_duration = loan_duration

        new_payment_structures = construct_tenure_probabilities(
            ordered_unpaid_payments, max_tenure_extension, self._loan_refinancing_request)

        self._loan_refinancing_request.update_safely(
            status=CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_email
        )

        customer_info, payment_info = self._construct_email_params(
            new_payment_structures[real_loan_duration])
        subject = 'Hubungi JULO Segera: \
                  Kesempatan Emas Bagi Anda Untuk Lunasi Pinjaman Dengan Diskon.' \
                  ' Waktu & Slot Terbatas!'
        template = 'covid_refinancing/covid_p1_opt_email.html'
        template_code = 'email_notif_proactive_refinancing'
        parameters = self._email_client.email_covid_refinancing_opt(
            customer_info, subject, template, template_code)
        self._create_email_history(*(parameters + (first_unpaid_payment,)))

    def _send_confirmation_email(self):
        from ..services.loan_related import get_unpaid_payments
        from juloserver.account_payment.services.account_payment_related import \
            get_unpaid_account_payment
        if self._is_for_j1:
            ordered_unpaid_payments = get_unpaid_account_payment(self._account.id)
        else:
            ordered_unpaid_payments = get_unpaid_payments(
                self._loan, order_by='payment_number')
        first_unpaid_payment = ordered_unpaid_payments[0]

        customer_info, _ = self._construct_email_params(None, is_need_va=False)
        subject = 'Langkah berikutnya untuk proses pengajuan Program Keringanan'
        template = 'covid_refinancing/covid_confirmation_email.html'
        template_code = 'click_setujuwebpage_email'
        parameters = self._email_client.email_covid_refinancing_opt(
            customer_info, subject, template, template_code)
        self._create_email_history(*(parameters + (first_unpaid_payment,)))

    def _send_pending_loan_refinancing(self):
        from ..services.loan_related import (
            get_unpaid_payments,
            construct_tenure_probabilities,
        )
        from ..services.refinancing_product_related import get_max_tenure_extension_r1

        ordered_unpaid_payments = get_unpaid_payments(self._loan, order_by='payment_number')
        first_unpaid_payment = ordered_unpaid_payments[0]
        max_tenure_extension = get_max_tenure_extension_r1(self._loan_refinancing_request)
        max_tenure_extension += self._loan.loan_duration

        if not max_tenure_extension:
            raise JuloException('Loan is not eligible since num of payments do not match')

        loan_duration = ordered_unpaid_payments.count() + \
                        self._loan_refinancing_request.loan_duration
        real_loan_duration = 0
        loan_duration_to_save = 0

        if loan_duration > max_tenure_extension:
            loan_duration_to_save = max_tenure_extension - self._loan.loan_duration
            real_loan_duration = max_tenure_extension
        else:
            real_loan_duration = loan_duration

        new_payment_structures = construct_tenure_probabilities(
            ordered_unpaid_payments, max_tenure_extension)

        new_payment_structures[real_loan_duration][0]['due_date'] = \
            timezone.localtime(
                self._loan_refinancing_request.request_date or \
                self._loan_refinancing_request.cdate).date() + \
            timedelta(days=self._loan_refinancing_request.expire_in_days)
        customer_info, payment_info = self._construct_email_params(
            new_payment_structures[real_loan_duration])
        subject = 'Selamat, Permohonan Pengurangan Cicilan Anda Telah Disetujui!'
        template = 'covid_refinancing/covid_pending_refinancing_email.html'
        parameters = self._email_client.email_covid_pending_refinancing_approved_for_all_product(
            customer_info, payment_info, subject, template)
        self._create_email_history(*(parameters + (first_unpaid_payment,)))

    def _send_activated_email_waiver_products(self):
        from juloserver.julo.services import get_google_calendar_for_email_reminder
        from ..services.loan_related import get_unpaid_payments
        from juloserver.account_payment.services.account_payment_related import (
            get_unpaid_account_payment,
            is_account_loan_paid_off,
        )
        if not self._is_for_j1:
            self._loan.refresh_from_db()
            if self._loan.status == LoanStatusCodes.PAID_OFF:
                subject = 'Selamat! Program keringanan berhasil dan pinjaman Anda telah lunas'
                template = 'covid_refinancing/covid_waiver_product_activated_email.html'
                template_code = "activated_offer_waiver_paidoff_email"
            else:
                subject = "Selamat! Pembayaran Anda diterima dan program keringanan berhasil diproses"
                template = 'covid_refinancing/covid_waiver_product_activated_email_notpaid.html'
                template_code = "activated_offer_waiver_notpaidoff_email_non_J1"

            ordered_payments = get_unpaid_payments(self._loan, order_by='payment_number')
        else:
            if is_account_loan_paid_off(self._account):
                subject = 'Selamat! Program keringanan berhasil dan pinjaman Anda telah lunas'
                template = 'covid_refinancing/covid_waiver_product_activated_email.html'
                template_code = "activated_offer_waiver_paidoff_email"
            else:
                subject = "Selamat! Pembayaran Anda diterima dan program keringanan berhasil diproses"
                template = 'covid_refinancing/covid_waiver_product_activated_email_notpaid.html'
                template_code = "activated_offer_waiver_notpaidoff_email"

            ordered_payments = get_unpaid_account_payment(self._account.id)

        if ordered_payments:
            first_unpaid_payment = ordered_payments[0]
        else:
            if not self._is_for_j1:
                first_unpaid_payment = self._loan.payment_set.last()
            else:
                first_unpaid_payment = self._account.accountpayment_set.last()

        _, _, calendar_link = get_google_calendar_for_email_reminder(
            self._application, is_for_j1=self._is_for_j1)

        # update template for bucket 5
        is_bucket_5, template_code = check_template_bucket_5(
            first_unpaid_payment, template_code, 'email', is_for_j1=self._is_for_j1)

        parameters = self._email_client.email_base(
            self._loan_refinancing_request, subject,
            template, ordered_payments, calendar_link,
            is_bucket_5=is_bucket_5, is_for_j1=self._is_for_j1)
        self._create_email_history(*(parameters[:-1] + (template_code, first_unpaid_payment,)))

    def _send_reminder_email(self):
        from ..services.loan_related import get_unpaid_payments
        from ..services.refinancing_product_related import (
            get_due_date,
            get_first_payment_due_date,
        )
        subject = '(REMINDER) Langkah berikutnya untuk proses pengajuan Program Keringanan'
        template = 'covid_refinancing/covid_reminder_email.html'

        ordered_unpaid_payments = get_unpaid_payments(self._loan,
                                                      order_by='payment_number')
        first_unpaid_payment = ordered_unpaid_payments[0]

        product_type = self._loan_refinancing_request.product_type

        if product_type:
            if product_type in CovidRefinancingConst.reactive_products():

                parameters = self._email_client.email_reminder_refinancing(
                    self._loan_refinancing_request,
                    subject,
                    template,
                    get_due_date(self._loan_refinancing_request)
                )

            else:
                parameters = self._email_client.email_reminder_refinancing(
                    self._loan_refinancing_request,
                    subject,
                    template,
                    get_first_payment_due_date(self._loan_refinancing_request)
                )

            self._create_email_history(*(parameters + (first_unpaid_payment,)))

    # send first email for Requested status refinancing campaign
    def _send_requested_status_campaign_email(self):
        if not check_loan_refinancing_with_requested_status_cohort_campaign(
            self._loan_refinancing_request.id):
            return
        from juloserver.account_payment.services.account_payment_related import \
            get_unpaid_account_payment

        ordered_unpaid_payments = get_unpaid_account_payment(self._account.id)
        first_unpaid_payment = ordered_unpaid_payments[0]
        template = 'covid_refinancing/requested_status_special_cohort_email.html'
        template_code = CohortCampaignEmail.TEMPLATE_CODE_OTHER_REFINANCING_1
        subject = CohortCampaignEmail.SUBJECT_OTHER_REFINANCING_1
        calendar_link = self._generate_google_calendar_link()
        customer_info, _ = self._construct_email_params(None)

        # update template for bucket 5
        is_bucket_5, template_code = check_template_bucket_5(
            first_unpaid_payment, template_code, 'email')

        parameters = self._email_client.email_base(
            self._loan_refinancing_request, subject, template, calendar_link=calendar_link,
            customer_info=customer_info, is_bucket_5=is_bucket_5, is_for_j1=self._is_for_j1
        )
        parameters = parameters[:-1] + (template_code, first_unpaid_payment)
        self._create_email_history(*parameters)

    # send second email for Requested status refinancing campaign
    def _send_requested_status_campaign_expiration_minus_2_email(self):
        if not check_loan_refinancing_with_requested_status_cohort_campaign(
            self._loan_refinancing_request.id):
            return

        from juloserver.account_payment.services.account_payment_related import \
            get_unpaid_account_payment

        ordered_unpaid_payments = get_unpaid_account_payment(self._account.id)
        first_unpaid_payment = ordered_unpaid_payments[0]
        subject = CohortCampaignEmail.SUBJECT_OTHER_REFINANCING_2
        customer_info, _ = self._construct_email_params(None)
        template, template_code, calendar_link = self._get_reminder_template(2)

        # update template for bucket 5
        is_bucket_5, template_code = check_template_bucket_5(
            first_unpaid_payment, template_code, 'email')

        parameters = self._email_client.email_base(
            self._loan_refinancing_request, subject, template, calendar_link=calendar_link,
            customer_info=customer_info, is_bucket_5=is_bucket_5, is_for_j1=self._is_for_j1
        )
        parameters = parameters[:-1] + (template_code, first_unpaid_payment)
        self._create_email_history(*parameters)

    # send third email for Requested status refinancing campaign
    def _send_requested_status_campaign_expiration_minus_1_email(self):
        if not check_loan_refinancing_with_requested_status_cohort_campaign(
            self._loan_refinancing_request.id):
            return
            
        from juloserver.account_payment.services.account_payment_related import \
            get_unpaid_account_payment

        ordered_unpaid_payments = get_unpaid_account_payment(self._account.id)
        first_unpaid_payment = ordered_unpaid_payments[0]
        subject = CohortCampaignEmail.SUBJECT_OTHER_REFINANCING_3
        customer_info, _ = self._construct_email_params(None)
        template, template_code, calendar_link = self._get_reminder_template(1)

        # update template for bucket 5
        is_bucket_5, template_code = check_template_bucket_5(
            first_unpaid_payment, template_code, 'email', is_for_j1=self._is_for_j1)

        parameters = self._email_client.email_base(
            self._loan_refinancing_request, subject, template, calendar_link=calendar_link,
            customer_info=customer_info, is_bucket_5=is_bucket_5, is_for_j1=self._is_for_j1
        )
        parameters = parameters[:-1] + (template_code, first_unpaid_payment)
        self._create_email_history(*parameters)

    # this special case for sos refinancing
    def send_offer_sos_refinancing_email(self):
        if not check_sos_loan_refinancing(self._loan_refinancing_request.id):
            return

        from juloserver.account_payment.services.account_payment_related import \
            get_unpaid_account_payment

        ordered_unpaid_payments = get_unpaid_account_payment(self._account.id)
        first_unpaid_payment = ordered_unpaid_payments[0]
        template = 'covid_refinancing/sos_refinancing_email.html'
        template_code = 'sos_email_refinancing_r1_30/08/23'
        subject = 'Program Spesial untuk Pelanggan Spesial Seperti Kamu!'

        parameters = self._email_client.email_sos_refinancing(
            self._loan_refinancing_request, subject, template)
        parameters = parameters[:-1] + (template_code, first_unpaid_payment)
        self._create_email_history(*parameters)

    def send_r4_promo_for_b5_lender_jtf(self, api_key):
        from juloserver.account_payment.services.account_payment_related import (
            get_unpaid_account_payment,
        )

        ordered_unpaid_payments = get_unpaid_account_payment(self._account.id)
        first_unpaid_payment = ordered_unpaid_payments[0]
        template = 'covid_refinancing/manual_r4_promo_b5_dpd121_JTF.html'
        template_code = 'manual_r4_promo_b5_dpd121_JTF'
        subject = 'Penawaran Potongan Pembayaran Tagihan'
        parameters = self._email_client.email_promo_r4_b5(
            self._loan_refinancing_request, subject, template, api_key
        )
        parameters = parameters[:-1] + (template_code, first_unpaid_payment)

        self._create_email_history(*parameters)

    def send_r4_promo_blast(self, template, template_code, template_raw=None):
        from juloserver.account_payment.services.account_payment_related import (
            get_unpaid_account_payment,
        )

        ordered_unpaid_payments = get_unpaid_account_payment(self._account.id)
        first_unpaid_payment = ordered_unpaid_payments[0]

        subject = 'Penawaran Potongan Pembayaran Tagihan'
        parameters = self._email_client.email_promo_r4_blast(
            self._loan_refinancing_request, subject, template, template_raw
        )
        parameters = parameters[:-1] + (template_code, first_unpaid_payment)

        self._create_email_history(*parameters)

    # this special case for activated sos refinancing
    def send_email_sos_refinancing_activated(self):
        from ..services.loan_related import (
            get_unpaid_payments_after_restructure,
            get_unpaid_account_payments_after_restructure,
        )
        from juloserver.julo.services import get_google_calendar_for_email_reminder
        subject = 'Selamat! Program keringanan berhasil diproses'
        template = 'covid_refinancing/covid_sos_refinancing_activated_email .html'
        ordered_unpaid_payments = get_unpaid_account_payments_after_restructure(
            self._account, order_by='due_date')

        first_unpaid_payment = ordered_unpaid_payments[0]
        _, _, calendar_link = get_google_calendar_for_email_reminder(
            self._application, is_for_j1=self._is_for_j1)

        parameters = self._email_client.email_covid_refinancing_activated_for_all_product(
            self._customer, subject, template, ordered_unpaid_payments, calendar_link,
            is_for_j1=self._is_for_j1
        )
        self._create_email_history(*(parameters + (first_unpaid_payment,)))

    def _construct_email_params(self, new_payment_structures, is_need_va=True):
        encrypter = encrypt()
        encrypted_uuid = None
        if self._loan_refinancing_request.uuid:
            encrypted_uuid = encrypter.encode_string(str(self._loan_refinancing_request.uuid))

        due_date = self._loan_refinancing_request.first_due_date

        if self._product_type in CovidRefinancingConst.proactive_products():
            due_date = timezone.localtime(self._loan_refinancing_request.cdate).date() + timedelta(
                days=5)
        customer_info = {
            'customer': self._customer,
            'encrypted_uuid': encrypted_uuid
        }
        if is_need_va:
            payment_method_detokenized = collection_detokenize_sync_object_model(
                PiiSource.PAYMENT_METHOD,
                self._payment_method,
                None,
                ['virtual_account'],
                PiiVaultDataType.KEY_VALUE,
            )
            customer_info['va_number'] = payment_method_detokenized.virtual_account
            customer_info['bank_code'] = self._payment_method.bank_code
            customer_info['bank_name'] = self._payment_method.payment_method_name

        payment_info = {
            'new_payment_structures': new_payment_structures,
            'late_fee_discount': self._loan_refinancing_request.total_latefee_discount,
            'prerequisite_amount': self._loan_refinancing_request.last_prerequisite_amount,
            'due_date': due_date,
            'tenure_extension': self._loan_refinancing_request.loan_duration
        }

        return customer_info, payment_info

    def _create_email_history(self, status, headers, subject, msg, template, payment):
        if status == 202:
            customer_detokenized = collection_detokenize_sync_object_model(
                PiiSource.CUSTOMER,
                self._customer,
                self._customer.customer_xid,
                ['email'],
            )
            email_history_param = dict(
                customer=self._customer,
                sg_message_id=headers["X-Message-Id"],
                to_email=customer_detokenized.email,
                subject=subject,
                application=self._application,
                message_content=msg,
                template_code=template,
            )
            if self._is_for_j1:
                email_history_param['account_payment'] = payment
            else:
                email_history_param['payment'] = payment

            EmailHistory.objects.create(**email_history_param)

            logger.info({
                "action": "email_notify_loan_refinancing",
                "customer_id": self._customer.id,
                "template_code": template
            })
        else:
            logger.warn({
                'action': "email_notify_loan_refinancing",
                'status': status,
                'message_id': headers['X-Message-Id']
            })

    def _generate_google_calendar_link(self):
        text = "Batas Akhir Pembayaran u/ Program Keringanan JULO"
        date_formatted = str(self._loan_refinancing_request.first_due_date).replace("-", "")
        date = "{}T100000%2f{}T110000".format(date_formatted, date_formatted)
        payment_method_detokenized = collection_detokenize_sync_object_model(
            PiiSource.PAYMENT_METHOD,
            self._payment_method,
            None,
            ['virtual_account'],
            PiiVaultDataType.KEY_VALUE,
        )
        context_details = dict(
            fullname_with_title=self._application.fullname_with_title,
            prerequisite_amount=self._loan_refinancing_request.prerequisite_amount,
            virtual_account_number=payment_method_detokenized.virtual_account,
        )
        details = render_to_string("covid_refinancing/approved_calendar_template.html",
                                   context_details)

        return "http://www.google.com/calendar/event?action=TEMPLATE&" \
               "recur=RRULE:COUNT=1&dates={}&text={}&location=&details={}".format(date, text,
                                                                                  details)

    def _validate_email_send_for_multiple_payment_ptp(
            self, _is_on_promised_date, first_unpaid_payment, multiple_payment_ptp
    ):
        if multiple_payment_ptp.is_fully_paid:
            return False

        templates = ['immediate_multiple_ptp_payment', 'immediate_multiple_ptp_payment_b5']
        for i in range(multiple_payment_ptp.sequence):
            templates.append('payment_date_%s_multiple_ptp_1_day' % str(i + 1))
            templates.append('payment_date_%s_multiple_ptp_1_day_b5' % str(i + 1))
            templates.append('payment_date_%s_multiple_ptp_on_day' % str(i + 1))
            templates.append('payment_date_%s_multiple_ptp_on_day_b5' % str(i + 1))

        if _is_on_promised_date:
            templates.append('multiple_ptp_1_day_expiry_date')
            templates.append('multiple_ptp_1_day_expiry_date_b5')

        today = timezone.localtime(timezone.now())
        start_of_day = today.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)
        email_history_filter = dict(
            customer=self._customer,
            application=self._application,
            template_code__in=templates,
            cdate__gte=start_of_day,
            cdate__lt=end_of_day,
        )
        if self._is_for_j1:
            email_history_filter['account_payment'] = first_unpaid_payment
        else:
            email_history_filter['payment'] = first_unpaid_payment

        return not EmailHistory.objects.filter(**email_history_filter).exists()

    def _get_customer_payment_method_for_refinancing(self):
        primary_payment_method = (
            self._customer.paymentmethod_set.filter(
                is_latest_payment_method=True, bank_code__isnull=False
            )
            .exclude(payment_method_code__in=PaymentMethodCodes.NOT_SUPPORT_REFINANCING_OR_WAIVER)
            .exclude(payment_method_name__icontains='Autodebet')
            .last()
        )
        if not primary_payment_method:
            primary_payment_method = (
                self._customer.paymentmethod_set.filter(is_primary=True, bank_code__isnull=False)
                .exclude(
                    payment_method_code__in=PaymentMethodCodes.NOT_SUPPORT_REFINANCING_OR_WAIVER
                )
                .exclude(payment_method_name__icontains='Autodebet')
                .last()
            )

        if primary_payment_method:
            return primary_payment_method

        # since faspay cannot show prerequisite_amount on loan refinancing
        # for alfamart and indomaret so we change the primary payment method to
        # payment method that have same bank when the customer do disburse
        first_layer_safety_net_qs = self._customer.paymentmethod_set.filter(
            payment_method_code=PaymentMethodCodes.PERMATA)
        second_layer_safety_net_qs = self._customer.paymentmethod_set.filter(
            bank_code__isnull=False).exclude(
            payment_method_code__in=PaymentMethodCodes.NOT_SUPPORT_REFINANCING_OR_WAIVER
        ).exclude(payment_method_name__icontains='Autodebet').order_by('sequence')
        bank_account_destination = self._customer.bankaccountdestination_set.exclude(
            is_deleted=True).last()
        if not bank_account_destination:
            logger.error({
                'action': '_get_customer_payment_method_for_refinancing',
                'message': 'customer dont have any bank account destination data',
                'identifier': {
                    'loan_refinancing_request': self._loan_refinancing_request.id,
                    'customer': self._customer.id
                }
            })
            return first_layer_safety_net_qs.last() or second_layer_safety_net_qs.first()

        payment_method_base_on_bank_account_destination = self._customer.paymentmethod_set.filter(
            bank_code=bank_account_destination.bank.bank_code).last()
        if not payment_method_base_on_bank_account_destination:
            logger.error({
                'action': '_get_customer_payment_method_for_refinancing',
                'message': 'customer dont have any payment method same as bank account destination',
                'identifier': {
                    'loan_refinancing_request': self._loan_refinancing_request.id,
                    'customer': self._customer.id,
                    'bank_account_destination': bank_account_destination.id
                }
            })
            return first_layer_safety_net_qs.last() or second_layer_safety_net_qs.first()

        return payment_method_base_on_bank_account_destination


class CovidLoanRefinancingSMS(object):
    def __init__(self, loan_refinancing_request):
        self.loan_refinancing_request = loan_refinancing_request
        self.sms_client = get_julo_sms_client()
        self.perdana_sms_client = get_julo_perdana_sms_client()
        self.loan = loan_refinancing_request.loan
        self.account = loan_refinancing_request.account
        self.is_for_j1 = True if loan_refinancing_request.account else False
        if self.is_for_j1:
            self.application = self.account.application_set.last()
        else:
            self.application = self.loan.application
        self.customer = self.application.customer
        self.product_type = loan_refinancing_request.product_type
        self.status = loan_refinancing_request.status
        if self.is_for_j1:
            self.payment = self.account.accountpayment_set.not_paid_active().first()
        else:
            self.payment = self.loan.payment_set.not_paid_active().first()
        self.payment_method = PaymentMethod.objects.filter(
            customer=self.customer, is_latest_payment_method=True
        ).last()
        if not self.payment_method:
            self.payment_method = PaymentMethod.objects.filter(
                customer=self.customer, is_primary=True
            ).last()
        channel_list = self.loan_refinancing_request.comms_channel_list()
        self._validate_comms_channel = CovidRefinancingConst.COMMS_CHANNELS.sms in channel_list
        self._channel = loan_refinancing_request.channel

    def send_approved_sms(self):
        if not self._validate_comms_channel:
            return
        send_approved_sms_method = self._get_loan_refinancing_product_method()
        send_approved_sms_method.send_approved()

    def send_activated_sms(self):
        if not self._validate_comms_channel:
            return
        send_activated_sms_method = self._get_loan_refinancing_product_method()
        send_activated_sms_method.send_activated()

    def send_reminder_offer_selected_1_sms(self):
        if self.product_type in CovidRefinancingConst.waiver_products() and \
           self._channel == CovidRefinancingConst.CHANNELS.reactive:
            return

        method = self._get_loan_refinancing_product_method()
        method.send_reminder_offer_selected_1()

    def send_reminder_offer_selected_2_sms(self):
        if self.product_type in CovidRefinancingConst.waiver_products() and \
           self._channel == CovidRefinancingConst.CHANNELS.reactive:
            return

        method = self._get_loan_refinancing_product_method()
        method.send_reminder_offer_selected_2()

    def send_reminder_offer_selected_sms(self):
        if not self._validate_comms_channel:
            return
        if self.product_type in CovidRefinancingConst.waiver_products() and \
           self._channel == CovidRefinancingConst.CHANNELS.reactive:
            return

        method = self._get_loan_refinancing_product_method()
        method.send_reminder_offer_selected()

    def send_expiration_minus_2_sms(self):
        method = self._get_loan_refinancing_product_method()
        method.send_reminder_minus_2()

    def send_expiration_minus_1_sms(self):
        method = self._get_loan_refinancing_product_method()
        method.send_reminder_minus_1()

    def send_proactive_sms(self, status=None):
        if self.loan_refinancing_request.channel != CovidRefinancingConst.CHANNELS.proactive:
            return

        if not self.payment:
            return
        all_template_codes = dict(
            robocall=None,
            pn=None,
            email=None
        )

        if self.status == CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_email:
            if status == "email_open":
                template_code = "emailsent_open_offer_first_sms"
                message = "{}, klik {} utk segera isi & lengkapi data terkait pengajuan " \
                          "program keringanan JULO".format(self.application.first_name_only,
                                                           self.loan_refinancing_request.url)
                all_template_codes['pn'] = ("emailsent_open_offer_first_pn",
                                            "emailsent_open_offer_second_pn",)
                all_template_codes["email"] = ("emailsent_open_offer_first_email",
                                               "emailsent_open_offer_second_email",
                                               "emailsent_open_offer_first_email_b5",
                                               "emailsent_open_offer_second_email_b5")
            else:
                template_code = "emailsent_offer_first_sms"
                message = (
                    "{}, Anda terpilih utk dapat restrukturisasi pinjaman JULO. "
                    "Klik skrg untuk meringankan cicilan Anda. {}".format(
                        self.application.first_name_only, self.loan_refinancing_request.url
                    )
                )
                all_template_codes["robocall"] = ("emailsent_offer_first_robocall",)
        elif self.status == CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_submit:
            template_code = "formviewed_offer_first_sms"
            message = (
                "{}, jangan lewatkan program keringanan pinjaman JULO. Lengkapi data "
                "dan selesaikan pengajuanmu. klik {}".format(
                    self.application.first_name_only, self.loan_refinancing_request.url
                )
            )
            all_template_codes["pn"] = (
                "formviewed_offer_first_pn",
                "formviewed_offer_second_pn",
            )
            all_template_codes["email"] = (
                "formviewed_offer_first_email",
                "formviewed_offer_first_email_b5",
            )
        elif self.status == CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_offer:
            template_code = "offergenerated_first_sms"
            message = (
                "{}, pilih Pelunasan Dengan Diskon atau Restrukturisasi utk melanjutkan "
                "pengajuan program keringanan. Klik disini {}".format(
                    self.application.first_name_only, self.loan_refinancing_request.url
                )
            )
            all_template_codes["robocall"] = ("offergenerated_first_robocall",)

        self._send_sms_with_validation(all_template_codes, template_code, message)

    def _get_loan_refinancing_product_method(self):
        if self.product_type in CovidRefinancingConst.reactive_products():
            return Namespace(
                **{
                    'send_approved': self._send_approved_all_product,
                    'send_activated': self._send_activated_refinancing_product,
                    'send_reminder_minus_2': self._reminder_minus_2_all_product,
                    'send_reminder_minus_1': self._reminder_minus_1_all_product,
                    'send_reminder_offer_selected_1': self._send_reminder_offer_selected_minus_1,
                    'send_reminder_offer_selected_2': self._send_reminder_offer_selected_minus_2,
                    "send_reminder_offer_selected": self._send_reminder_offer_selected,
                }
            )
        if self.product_type in CovidRefinancingConst.waiver_products():
            return Namespace(
                **{
                    'send_approved': self._send_approved_all_product,
                    'send_activated': self._send_activated_waiver_product,
                    'send_reminder_offer_selected_1': self._send_reminder_offer_selected_minus_1,
                    'send_reminder_offer_selected_2': self._send_reminder_offer_selected_minus_2,
                    'send_reminder_minus_2': self._reminder_minus_2_all_product,
                    'send_reminder_minus_1': self._reminder_minus_1_all_product,
                    "send_reminder_offer_selected": self._send_reminder_offer_selected,
                }
            )

        raise ValueError(
            "Product not found with id %s, status %s, product type %s"
            % (
                self.loan_refinancing_request.id,
                self.loan_refinancing_request.status,
                self.loan_refinancing_request.product_type,
            )
        )

    def _send_approved_all_product(self):
        is_loan_refinancing_request_campaign = (
            check_loan_refinancing_request_is_r4_spcecial_campaign_by_id(
                self.loan_refinancing_request.id
            )
        )
        is_loan_refinancing_request_campaign_r123 = (
            check_loan_refinancing_with_requested_status_cohort_campaign(
                self.loan_refinancing_request.id
            )
        )
        if is_loan_refinancing_request_campaign or is_loan_refinancing_request_campaign_r123:
            """
            code on below got comment beacuse for avoid sms sending to customer
            when exists loan_refinancing_request_campaign
            """
            # message = "{}, Ingin merdeka dr pinjaman JULO? Bayar " \
            #           "{} sebelum tgl {}, " \
            #           "hutang 100% LUNAS!" \
            #     .format(self.application.first_name_only,
            #             display_rupiah(self.loan_refinancing_request.last_prerequisite_amount),
            #             format_date(self.loan_refinancing_request.first_due_date,
            #                         'd MMMM yyyy', locale='id_ID')
            #             )
            return
        else:
            message = (
                "{}, terima kasih utk pengajuan program keringanan JULO. "
                "Bayar {} sebelum tgl {} utk aktivasi".format(
                    self.application.first_name_only,
                    display_rupiah(self.loan_refinancing_request.last_prerequisite_amount),
                    format_date(
                        self.loan_refinancing_request.first_due_date, 'd MMMM yyyy', locale='id_ID'
                    ),
                )
            )

        template_code = "approved_offer_first_sms"

        # update template for bucket 5
        is_bucket_5, template_code = check_template_bucket_5(
            self.payment, template_code, 'sms', is_for_j1=self.is_for_j1
        )
        if is_bucket_5:
            new_sms_client = self.perdana_sms_client
        else:
            new_sms_client = self.sms_client

        new_sms_client.loan_refinancing_sms(self.loan_refinancing_request, message, template_code)

    def _send_activated_refinancing_product(self):
        # check loan_refinancing_request_campaign for avoid sms sending to customer
        is_loan_refinancing_request_campaign = (
            check_loan_refinancing_request_is_r4_spcecial_campaign_by_id(
                self.loan_refinancing_request.id
            )
        )
        is_loan_refinancing_request_campaign_r123 = (
            check_loan_refinancing_with_requested_status_cohort_campaign(
                self.loan_refinancing_request.id
            )
        )
        if is_loan_refinancing_request_campaign or is_loan_refinancing_request_campaign_r123:
            return
        template_code = CovidRefinancingConst.TEMPLATE_CODE_ACTIVATION.sms
        message = (
            "{}, tks telah membayar. Program keringanan Anda telah aktif."
            " Lihat aplikasi utk jadwal bayar selanjutnya. collections@julo.co.id"
        ).format(self.application.first_name_with_title)
        self.sms_client.loan_refinancing_sms(self.loan_refinancing_request, message, template_code)

    def _send_activated_waiver_product(self):
        # check loan_refinancing_request_campaign for avoid sms sending to customer
        is_loan_refinancing_request_campaign = (
            check_loan_refinancing_request_is_r4_spcecial_campaign_by_id(
                self.loan_refinancing_request.id
            )
        )
        is_loan_refinancing_request_campaign_r123 = (
            check_loan_refinancing_with_requested_status_cohort_campaign(
                self.loan_refinancing_request.id
            )
        )
        if is_loan_refinancing_request_campaign or is_loan_refinancing_request_campaign_r123:
            return
        template_code = CovidRefinancingConst.TEMPLATE_CODE_ACTIVATION.sms
        message = (
            "{}, tks telah melakukan pembayaran. Program keringanan Anda telah diproses dan aktif."
            "collections@julo.co.id utk info lbh lanjut. Tks."
        ).format(self.application.first_name_with_title)
        self.sms_client.loan_refinancing_sms(self.loan_refinancing_request, message, template_code)

    def _reminder_minus_2_all_product(self):
        is_loan_refinancing_request_campaign = (
            check_loan_refinancing_request_is_r4_spcecial_campaign_by_id(
                self.loan_refinancing_request.id
            )
        )
        is_loan_refinancing_request_campaign_r123 = (
            check_loan_refinancing_with_requested_status_cohort_campaign(
                self.loan_refinancing_request.id
            )
        )
        if is_loan_refinancing_request_campaign or is_loan_refinancing_request_campaign_r123:
            """
            code on below got comment beacuse for avoid sms sending to customer
            when exists loan_refinancing_request_campaign
            """
            # message = "{first_name}, Selangkah lagi utk merdeka dr hutang! Bayar " \
            #           "{prerequisite_amount} sebelum tgl {offer_expiry_date}, " \
            #           "hutang 100% LUNAS!" \
            #     .format(first_name=self.application.first_name_only,
            #             prerequisite_amount=display_rupiah(
            #                 self.loan_refinancing_request.last_prerequisite_amount),
            #             offer_expiry_date=format_date(
            #                 self.loan_refinancing_request.first_due_date, 'd MMMM yyyy',
            #                 locale='id_ID')
            #             )
            return
        all_template_codes = dict(
            robocall=("approved_first_robocall_alloffers",), pn=("approved_offer_first_pn",)
        )
        template_code = "approved_offer_second_sms"
        message = (
            "{}, penawaran program keringanan JULO Anda berakhir dlm 2 hari. "
            "Bayar {} sebelum {}".format(
                self.application.first_name_with_title,
                display_rupiah(self.loan_refinancing_request.last_prerequisite_amount),
                format_date(
                    self.loan_refinancing_request.first_due_date, 'd MMMM yyyy', locale='id_ID'
                ),
            )
        )

        if self.product_type in CovidRefinancingConst.reactive_products():
            all_template_codes["email"] = ("approved_first_email_R1R2R3",)
        elif self.product_type == CovidRefinancingConst.PRODUCTS.r4:
            all_template_codes["email"] = ("approved_first_email_R4", "approved_first_email_R4_b5")
        else:
            all_template_codes["email"] = (
                "approved_first_email_R5R6",
                "approved_first_email_R5R6_b5",
            )

        self._send_sms_with_validation(all_template_codes, template_code, message)

    def _reminder_minus_1_all_product(self):
        is_loan_refinancing_request_campaign = (
            check_loan_refinancing_request_is_r4_spcecial_campaign_by_id(
                self.loan_refinancing_request.id
            )
        )
        is_loan_refinancing_request_campaign_r123 = (
            check_loan_refinancing_with_requested_status_cohort_campaign(
                self.loan_refinancing_request.id
            )
        )
        if is_loan_refinancing_request_campaign or is_loan_refinancing_request_campaign_r123:
            """
            code on below got comment beacuse for avoid sms sending to customer
            when exists loan_refinancing_request_campaign
            """
            # message = "{first_name}, KESEMPATAN TERAKHIR! Segera bayar " \
            #           "{prerequisite_amount} sebelum {offer_expiry_date} " \
            #           "& siap u/ merdeka dr hutang!" \
            #     .format(first_name=self.application.first_name_only,
            #             prerequisite_amount=display_rupiah(
            #                 self.loan_refinancing_request.last_prerequisite_amount),
            #             offer_expiry_date=format_date(
            #                 self.loan_refinancing_request.first_due_date,
            #                 'd MMMM yyyy', locale='id_ID')
            #             )
            return
        all_template_codes = dict(
            robocall=("approved_first_robocall_alloffers",),
            pn=("offerselected_second_PN_R1R2R3R4",),
        )
        template_code = "approved_offer_third_sms"
        message = (
            "{}, penawaran program keringanan JULO Anda berakhir BESOK. "
            "Bayar {} sebelum {}".format(
                self.application.first_name_with_title,
                display_rupiah(self.loan_refinancing_request.last_prerequisite_amount),
                format_date(
                    self.loan_refinancing_request.first_due_date, 'd MMMM yyyy', locale='id_ID'
                ),
            )
        )

        if self.product_type in CovidRefinancingConst.reactive_products():
            all_template_codes["email"] = ("approved_second_email_R1R2R3",)
        elif self.product_type == CovidRefinancingConst.PRODUCTS.r4:
            all_template_codes["email"] = (
                "approved_second_email_R4",
                "approved_second_email_R4_b5",
            )
        else:
            all_template_codes["email"] = (
                "approved_second_email_R5R6",
                "approved_second_email_R5R6_b5",
            )

        self._send_sms_with_validation(all_template_codes, template_code, message)

    def _send_reminder_offer_selected_minus_1(self):
        # check loan_refinancing_request_campaign for avoid sms sending to customer
        is_loan_refinancing_request_campaign = (
            check_loan_refinancing_request_is_r4_spcecial_campaign_by_id(
                self.loan_refinancing_request.id
            )
        )
        is_loan_refinancing_request_campaign_r123 = (
            check_loan_refinancing_with_requested_status_cohort_campaign(
                self.loan_refinancing_request.id
            )
        )
        if is_loan_refinancing_request_campaign or is_loan_refinancing_request_campaign_r123:
            return
        all_template_codes = dict(
            robocall=("offerselected_first_robocall_R1R2R3R4",),
            pn=("offerselected_second_PN_R1R2R3R4",),
            email=("offerselected_second_email", "offerselected_second_email_b5"),
        )

        template_code = "offerselected_third_sms_R1R2R3R4"
        message = (
            "[KESEMPATAN TERAKHIR] Klik {} utk menyelesaikan pengajuan "
            "program keringanan JULO. Masa berlaku program berakhir BESOK.".format(
                self.loan_refinancing_request.url
            )
        )

        self._send_sms_with_validation(all_template_codes, template_code, message)

    def _send_reminder_offer_selected_minus_2(self):
        # check loan_refinancing_request_campaign for avoid sms sending to customer
        is_loan_refinancing_request_campaign = (
            check_loan_refinancing_request_is_r4_spcecial_campaign_by_id(
                self.loan_refinancing_request.id
            )
        )
        is_loan_refinancing_request_campaign_r123 = (
            check_loan_refinancing_with_requested_status_cohort_campaign(
                self.loan_refinancing_request.id
            )
        )
        if is_loan_refinancing_request_campaign or is_loan_refinancing_request_campaign_r123:
            return
        all_template_codes = dict(
            robocall=("offerselected_first_robocall_R1R2R3R4",),
            pn=("offerselected_first_PN_R1R2R3R4",),
        )
        if self.product_type in CovidRefinancingConst.reactive_products():
            all_template_codes["email"] = (
                ("offerselected_first_email_R1",)
                if self.product_type == CovidRefinancingConst.PRODUCTS.r1
                else ("offerselected_first_email_R2R3",)
            )
        else:
            all_template_codes["email"] = (
                "offerselected_first_email_R4",
                "offerselected_first_email_R4_b5",
            )

        template_code = "offerselected_second_sms_R1R2R3R4"
        message = (
            "{}, selesaikan pengajuan PROGRAM KERINGANAN JULO disini {}. "
            "Tinggal 2 hari lagi.".format(
                self.application.first_name_with_title, self.loan_refinancing_request.url
            )
        )

        self._send_sms_with_validation(all_template_codes, template_code, message)

    def _send_reminder_offer_selected(self):
        # check loan_refinancing_request_campaign for avoid sms sending to customer
        is_loan_refinancing_request_campaign = (
            check_loan_refinancing_request_is_r4_spcecial_campaign_by_id(
                self.loan_refinancing_request.id
            )
        )
        is_loan_refinancing_request_campaign_r123 = (
            check_loan_refinancing_with_requested_status_cohort_campaign(
                self.loan_refinancing_request.id
            )
        )
        if is_loan_refinancing_request_campaign or is_loan_refinancing_request_campaign_r123:
            return
        template_code = "offerselected_first_sms_R1R2R3R4"
        message = (
            "Selangkah lagi! Klik {} utk melanjutkan pengajuan keringanan JULO. "
            "collections@julo.co.id utk info lbh lanjut".format(self.loan_refinancing_request.url)
        )

        # update template for bucket 5
        is_bucket_5, template_code = check_template_bucket_5(
            self.payment, template_code, 'sms', is_for_j1=self.is_for_j1
        )
        if is_bucket_5:
            new_sms_client = self.perdana_sms_client
        else:
            new_sms_client = self.sms_client

        new_sms_client.loan_refinancing_sms(self.loan_refinancing_request, message, template_code)

    def _send_sms_with_validation(self, all_template_codes, template_code, message):
        communication_list = self.loan_refinancing_request.comms_channel_list()

        # update template for bucket 5
        is_bucket_5, template_code = check_template_bucket_5(
            self.payment, template_code, 'sms', is_for_j1=self.is_for_j1
        )
        if is_bucket_5:
            new_sms_client = self.perdana_sms_client
        else:
            new_sms_client = self.sms_client

        if self.loan_refinancing_request.channel == CovidRefinancingConst.CHANNELS.reactive:
            if CovidRefinancingConst.COMMS_CHANNELS.sms in communication_list:
                new_sms_client.loan_refinancing_sms(
                    self.loan_refinancing_request, message, template_code
                )
        else:
            if (
                self._valid_voice_call_history(all_template_codes["robocall"])
                and self._valid_pn_history(all_template_codes["pn"])
                and self._valid_email_history(all_template_codes["email"])
            ):
                new_sms_client.loan_refinancing_sms(
                    self.loan_refinancing_request, message, template_code
                )

    def _valid_voice_call_history(self, robocall_template_codes):
        if not robocall_template_codes:
            return True

        voice_call_records = (
            VoiceCallRecord.objects.annotate(
                call_price_int=Func(
                    F('call_price'),
                    template='%(function)s(%(expressions)s AS %(type)s)',
                    function='Cast',
                    type='float',
                ),
                duration_int=Func(
                    F('duration'),
                    template='%(function)s(%(expressions)s AS %(type)s)',
                    function='Cast',
                    type='int',
                ),
            )
            .filter(
                template_code__in=robocall_template_codes,
                event_type=VoiceTypeStatus.REFINANCING_REMINDER,
                voice_identifier=self.payment.id,
                cdate__hour__in=[8, 10, 12],
            )
            .filter(Q(call_price__isnull=True) | Q(call_price_int=0) | Q(duration_int__lt=15))
        )

        if voice_call_records.count() != 3:
            return False

        return True

    def _valid_pn_history(self, template_codes):
        if not template_codes:
            return True

        pn_deliveries = PNDelivery.objects.filter(
            fcm_id=self.customer.last_gcm_id, pn_blast__name__in=template_codes
        ).exclude(
            status__in=(
                "open",
                "click",
            )
        )

        return pn_deliveries.count() >= 1

    def _valid_email_history(self, template_codes):
        if not template_codes:
            return True

        email_histories = EmailHistory.objects.filter(
            template_code__in=template_codes, payment_id=self.payment.id
        ).exclude(status__in=("open", "click"))

        return email_histories.count() >= 1


class CovidLoanRefinancingPN(object):
    def __init__(self, loan_refinancing_request):
        self.loan_refinancing_request = loan_refinancing_request
        self.pn_client = get_julo_pn_client()
        self.loan = loan_refinancing_request.loan
        self.account = loan_refinancing_request.account
        self.is_for_j1 = True if loan_refinancing_request.account else False
        if self.is_for_j1:
            self.application = self.account.application_set.last()
        else:
            self.application = self.loan.application
        self.customer = self.application.customer
        self.product_type = loan_refinancing_request.product_type
        self.status = loan_refinancing_request.status
        self.payment_method = PaymentMethod.objects.filter(
            customer=self.customer, is_latest_payment_method=True
        ).last()
        if not self.payment_method:
            self.payment_method = PaymentMethod.objects.filter(
                customer=self.customer, is_primary=True
            ).last()
        self.base_image_url = (
            "https://julocampaign.julo.co.id/" "refinancing_integration/"
        )
        self.base_image_url_campaign = CohortCampaignPN.BASE_IMAGE_URL
        channel_list = self.loan_refinancing_request.comms_channel_list()
        self._validate_comms_channel = CovidRefinancingConst.COMMS_CHANNELS.pn in channel_list
        self._channel = loan_refinancing_request.channel

    def send_approved_pn(self):
        if not self._validate_comms_channel:
            return
        send_approved_pn_method = self._get_loan_refinancing_product_method()
        send_approved_pn_method.send_approved()

    def send_activated_pn(self):
        if not self._validate_comms_channel:
            return
        send_activated_pn_method = self._get_loan_refinancing_product_method()
        send_activated_pn_method.send_activated()

    def send_reminder_offer_selected_minus_1_pn(self):
        if not self._validate_comms_channel:
            return
        if (
            self.product_type in CovidRefinancingConst.waiver_products()
            and self._channel == CovidRefinancingConst.CHANNELS.reactive
        ):
            return

        method = self._get_loan_refinancing_product_method()
        method.send_reminder_offer_selected_minus_1()

    def send_reminder_offer_selected_minus_2_pn(self):
        if not self._validate_comms_channel:
            return
        if (
            self.product_type in CovidRefinancingConst.waiver_products()
            and self._channel == CovidRefinancingConst.CHANNELS.reactive
        ):
            return

        method = self._get_loan_refinancing_product_method()
        method.send_reminder_offer_selected_minus_2()

    def send_reminder_offer_pn(self):
        if not self._validate_comms_channel:
            return
        if (
            self.product_type in CovidRefinancingConst.waiver_products()
            and self._channel == CovidRefinancingConst.CHANNELS.reactive
        ):
            return

        method = self._get_loan_refinancing_product_method()
        method.send_reminder_offer_selected()

    def send_expiration_minus_2_pn(self):
        if not self._validate_comms_channel:
            return
        method = self._get_loan_refinancing_product_method()
        method.send_reminder_minus_2()

    def send_expiration_minus_1_pn(self):
        if not self._validate_comms_channel:
            return
        method = self._get_loan_refinancing_product_method()
        method.send_reminder_minus_1()

    def send_offer_refinancing_pn(self):
        if not self._validate_comms_channel:
            return
        send_approved_pn_method = self._get_loan_refinancing_product_method()
        send_approved_pn_method.send_offer()

    def send_requested_status_campaign_minus_2_pn(self):
        if not self._validate_comms_channel:
            return
        method = self._get_loan_refinancing_product_method()
        method.send_reminder_minus_2()

    def send_requested_status_campaign_minus_1_pn(self):
        if not self._validate_comms_channel:
            return
        method = self._get_loan_refinancing_product_method()
        method.send_reminder_minus_1()

    def send_proactive_pn(self, status=None, day=None):
        if self.loan_refinancing_request.channel != CovidRefinancingConst.CHANNELS.proactive:
            return

        tadaicon = u'\U0001f389'

        if self.status == CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_email:
            template_code = "emailsent_offer_first_pn"
            title = "Keringanan pinjaman JULO hanya untuk Anda"
            message = "Bayar cicilan lebih ringan. Ajukan di sini."
            filename = "cicilan-lebih-ringan.png"
            if day == 3:
                template_code = "emailsent_offer_second_pn"
                title = "Keringanan pinjaman untukmu!"
                message = "JULO bantu kesulitan Anda. Ajukan sekarang."
                filename = "male-version.png"
            if status == "email_open":
                template_code = "emailsent_open_offer_first_pn"
                title = "%s, kesempatan restrukturisasi pinjaman %s" % (
                    self.application.first_name_only,
                    tadaicon,
                )
                message = "Isi dan lengkapi data di sini utk menikmati keringanan pinjaman JULO"
                filename = "female-version.png"
                if day == 3:
                    template_code = "emailsent_open_offer_second_pn"
                    title = "Restrukturisasi pinjaman buat Anda"
                    message = "{}, segera ajukan keringanan pinjaman di sini".format(
                        self.application.first_name_only
                    )
                    filename = "mau-cicilan-lebih-ringan-new.png"
        elif self.status == CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_submit:
            template_code = "formviewed_offer_first_pn"
            title = "Lengkapi data & ajukan keringanan %s" % tadaicon
            message = "{}, hanya 10 menit untuk mengajukan keringanan pinjaman".format(
                self.application.first_name_only
            )
            filename = "hanya-10-menit.png"
            if day == 4:
                template_code = "formviewed_offer_second_pn"
                title = "Program Keringanan cm datang sekali"
                message = "{}, segera lengkapi data & ajukan keringanan pinjaman".format(
                    self.application.first_name_only
                )
                filename = "hanya-10-menit.png"
        elif self.status == CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_offer:
            template_code = "offergenerated_first_pn"
            title = "Pilih program keringanan Anda"
            message = "Selesaikan pengajuan disini, penawaran terbatas."
            filename = "male-version-2-new.png"
            if day == 4:
                template_code = "offergenerated_second_pn"
                title = "Selesaikan pengajuan keringanan pinjaman"
                message = "Pilih antara Pelunasan Dengan Diskon atau Restrukturisasi."
                filename = "male-version-2-new.png"

        data = {
            "title": title,
            "image_url": self.base_image_url + filename,
            "body": message,
            "redirect_url": (
                "{}?utm_source=pn&utm_medium=pn&utm_campaign=restrukturisasiform"
                "&utm_content=reminderform"
            ).format(self.loan_refinancing_request.url),
        }

        self.pn_client.loan_refinancing_notification(
            self.loan_refinancing_request, data, template_code
        )

    def _get_loan_refinancing_product_method(self):
        if self.product_type in CovidRefinancingConst.reactive_products():
            return Namespace(
                **{
                    'send_approved': self._send_approved_all_product,
                    'send_activated': self._send_activated_refinancing_product,
                    'send_reminder_offer_selected_minus_1': self._send_reminder_offer_selected_minus_1,
                    'send_reminder_offer_selected_minus_2': self._send_reminder_offer_selected_minus_2,
                    'send_reminder_minus_2': self._reminder_minus_2_all_product,
                    'send_reminder_minus_1': self._reminder_minus_1_all_product,
                    'send_reminder_offer_selected': self._send_reminder_offer_selected,
                }
            )
        if self.product_type in CovidRefinancingConst.waiver_products():
            return Namespace(
                **{
                    'send_approved': self._send_approved_all_product,
                    'send_activated': self._send_activated_waiver_product,
                    'send_reminder_offer_selected_minus_1': self._send_reminder_offer_selected_minus_1,
                    'send_reminder_offer_selected_minus_2': self._send_reminder_offer_selected_minus_2,
                    'send_reminder_minus_2': self._reminder_minus_2_all_product,
                    'send_reminder_minus_1': self._reminder_minus_1_all_product,
                    'send_reminder_offer_selected': self._send_reminder_offer_selected,
                }
            )
        if self.status == CovidRefinancingConst.STATUSES.requested:
            return Namespace(
                **{
                    'send_offer': self._send_requested_status_campaign_pn,
                    'send_reminder_minus_2': self._send_requested_status_campaign_reminder_minus_2,
                    'send_reminder_minus_1': self._send_requested_status_campaign_reminder_minus_1,
                }
            )

        raise ValueError(
            "Product not found with id %s, status %s, product type %s"
            % (
                self.loan_refinancing_request.id,
                self.loan_refinancing_request.status,
                self.loan_refinancing_request.product_type,
            )
        )

    def _send_approved_all_product(self):
        template_code = "approved_offer_first_pn"
        is_loan_refinancing_request_campaign = (
            check_loan_refinancing_request_is_r4_spcecial_campaign_by_id(
                self.loan_refinancing_request.id
            )
        )
        if is_loan_refinancing_request_campaign:
            title = CohortCampaignPN.SUBJECT_R4_1
            message = CohortCampaignPN.MESSAGE_R4_1
            image_url = "{}{}".format(self.base_image_url_campaign, CohortCampaignPN.IMAGE_URL_R4_1)
            template_code = CohortCampaignPN.TEMPLATE_CODE_R4_1
        else:
            message = "%s, bayar sejumlah %s sebelum tgl %s utk aktivasi program keringanan" % (
                self.application.first_name_with_title,
                display_rupiah(self.loan_refinancing_request.last_prerequisite_amount),
                format_date(
                    self.loan_refinancing_request.first_due_date, 'd MMMM yyyy', locale='id_ID'
                ),
            )
            title = "Pembayaran untuk Aktivasi Program"
            image_url = "%spn-banner-as-soon-approved.png" % self.base_image_url

        data = {
            "title": title,
            "image_url": image_url,
            "body": message,
        }
        self.pn_client.loan_refinancing_notification(
            self.loan_refinancing_request, data, template_code
        )

    def _send_activated_refinancing_product(self):
        template_code = "activated_offer_refinancing_pn"
        message = (
            "{}, trm kasih telah membayar. Program keringanan Anda telah aktif. "
            "Lihat email/aplikasi utk jadwal bayar selanjutnya "
        ).format(self.application.first_name_with_title)
        data = {
            "title": "Program keringanan telah aktif",
            "image_url": "%sselamat.png" % self.base_image_url,
            "body": message,
        }
        self.pn_client.loan_refinancing_notification(
            self.loan_refinancing_request, data, template_code
        )

    def _send_activated_waiver_product(self):
        from juloserver.account_payment.services.account_payment_related import (
            is_account_loan_paid_off,
        )

        if self.is_for_j1:
            criteria = is_account_loan_paid_off(self.account)
        else:
            criteria = self.loan.status == LoanStatusCodes.PAID_OFF
            self.loan.refresh_from_db()

        if criteria:
            template_code = "activated_offer_waiver_notpaidoff_pn"
            message = "{}, program keringanan Anda berhasil & tagihan Anda telah lunas.".format(
                self.application.first_name_with_title
            )
        else:
            template_code = "activated_offer_waiver_paidoff_pn"
            message = (
                "{}, program keringanan Anda berhasil diproses. Lihat email/aplikasi "
                "utk jadwal bayar selanjutnya.".format(self.application.first_name_with_title)
            )

        data = {
            "title": "Selamat! Program keringanan berhasil diproses",
            "image_url": "%sselamat.png" % self.base_image_url,
            "body": message,
        }
        self.pn_client.loan_refinancing_notification(
            self.loan_refinancing_request, data, template_code
        )

    def _reminder_minus_2_all_product(self):
        # block refinancing DPD 181+
        if check_loan_refinancing_request_is_r4_dpd_181_plus(self.loan_refinancing_request.id):
            return
        if check_loan_refinancing_request_is_r4_dpd_181_plus_blast(
            self.loan_refinancing_request.id
        ):
            return

        template_code = "approved_offer_second_pn"
        is_loan_refinancing_request_campaign = (
            check_loan_refinancing_request_is_r4_spcecial_campaign_by_id(
                self.loan_refinancing_request.id
            )
        )

        if is_loan_refinancing_request_campaign:
            title = CohortCampaignPN.SUBJECT_R4_2
            message = CohortCampaignPN.MESSAGE_R4_2
            image_url = "{}{}".format(self.base_image_url_campaign, CohortCampaignPN.IMAGE_URL_R4_2)
            template_code = CohortCampaignPN.TEMPLATE_CODE_R4_2
        else:
            message = "Tinggal 2 hari lagi. Bayar sejumlah %s sebelum %s" % (
                display_rupiah(self.loan_refinancing_request.last_prerequisite_amount),
                format_date(
                    self.loan_refinancing_request.first_due_date, 'd MMMM yyyy', locale='id_ID'
                ),
            )
            title = "Yuk, Bayar untuk Aktivasi Keringanan"
            image_url = "%spn-banner-2-days-before-expired-approved.png" % self.base_image_url
        data = {
            "title": title,
            "image_url": image_url,
            "body": message,
        }
        self.pn_client.loan_refinancing_notification(
            self.loan_refinancing_request, data, template_code
        )

    def _reminder_minus_1_all_product(self):
        # block refinancing DPD 181+
        if check_loan_refinancing_request_is_r4_dpd_181_plus(self.loan_refinancing_request.id):
            return
        if check_loan_refinancing_request_is_r4_dpd_181_plus_blast(
            self.loan_refinancing_request.id
        ):
            return

        template_code = "approved_offer_third_pn"
        is_loan_refinancing_request_campaign = (
            check_loan_refinancing_request_is_r4_spcecial_campaign_by_id(
                self.loan_refinancing_request.id
            )
        )

        if is_loan_refinancing_request_campaign:
            title = CohortCampaignPN.SUBJECT_R4_3
            message = CohortCampaignPN.MESSAGE_R4_3
            image_url = "{}{}".format(self.base_image_url_campaign, CohortCampaignPN.IMAGE_URL_R4_3)
            template_code = CohortCampaignPN.TEMPLATE_CODE_R4_3
        else:
            message = "Bayar sejumlah %s paling lambat %s" % (
                display_rupiah(self.loan_refinancing_request.last_prerequisite_amount),
                format_date(
                    self.loan_refinancing_request.first_due_date, 'd MMMM yyyy', locale='id_ID'
                ),
            )
            title = "[BERAKHIR BESOK] Bayar sekarang utk aktivasi program"
            image_url = "%spn-banner-1-day-before-expired-approved.png" % self.base_image_url
        data = {
            "title": title,
            "image_url": image_url,
            "body": message,
        }
        self.pn_client.loan_refinancing_notification(
            self.loan_refinancing_request, data, template_code
        )

    def _send_reminder_offer_selected_minus_1(self):
        template_code = 'offerselected_third_PN_R1R2R3R4'
        message = (
            "Lakukan konfirmasi pilihan program HARI INI. "
            "Klik utk melanjutkan pengajuan keringanan."
        )

        data = {
            "title": "[KESEMPATAN TERAKHIR] %s" % u'\u231B',
            "image_url": ("{}pn-banner-1-day-before-expired-offer-selected.jpg").format(
                self.base_image_url
            ),
            "body": message,
            "redirect_url": (
                "{}?utm_source=pn&utm_medium=pn&utm_campaign=restrukturisasiform"
                "&utm_content=reminderform"
            ).format(self.loan_refinancing_request.url),
        }
        self.pn_client.loan_refinancing_notification(
            self.loan_refinancing_request, data, template_code
        )

    def _send_reminder_offer_selected_minus_2(self):
        template_code = 'offerselected_second_PN_R1R2R3R4'
        message = (
            "{}, segera selesaikan pengajuan keringanan Anda di sini. Tinggal 2 hari lagi.".format(
                self.application.first_name_with_title
            )
        )

        data = {
            "title": "Konfirmasi pilihan program keringanan Anda",
            "image_url": "{}pn-banner-2-day-before-expired-offer-selected.jpg".format(
                self.base_image_url
            ),
            "body": message,
            "redirect_url": (
                "{}?utm_source=pn&utm_medium=pn&utm_campaign=restrukturisasiform"
                "&utm_content=reminderform"
            ).format(self.loan_refinancing_request.url),
        }
        self.pn_client.loan_refinancing_notification(
            self.loan_refinancing_request, data, template_code
        )

    def _send_reminder_offer_selected(self):
        template_code = 'offerselected_first_PN_R1R2R3R4'
        message = (
            "{}, Anda telah memilih program keringanan. Klik pesan ini utk melanjutkan "
            "proses pengajuan.".format(self.application.first_name_only)
        )

        data = {
            "title": "Konfirmasi pilihan program Anda",
            "image_url": "%spn-banner-as-soon-offer-selected.png" % self.base_image_url,
            "body": message,
            "redirect_url": (
                "{}?utm_source=pn&utm_medium=pn&utm_campaign=restrukturisasiform"
                "&utm_content=reminderform"
            ).format(self.loan_refinancing_request.url),
        }
        self.pn_client.loan_refinancing_notification(
            self.loan_refinancing_request, data, template_code
        )

    # send first PN for Requested status campaign
    def _send_requested_status_campaign_pn(self):
        if not check_loan_refinancing_with_requested_status_cohort_campaign(
            self.loan_refinancing_request.id
        ):
            return
        template_code = CohortCampaignPN.TEMPLATE_CODE_OTHER_REFINANCING_1
        data = {
            "title": CohortCampaignPN.SUBJECT_OTHER_REFINANCING_1,
            "body": CohortCampaignPN.MESSAGE_OTHER_REFINANCING_1,
            "image_url": "{}pn_program_berkah_r6_1.png".format(self.base_image_url_campaign),
        }
        self.pn_client.loan_refinancing_notification(
            self.loan_refinancing_request, data, template_code
        )

    # send second PN for Requested status campaign
    def _send_requested_status_campaign_reminder_minus_2(self):
        if not check_loan_refinancing_with_requested_status_cohort_campaign(
            self.loan_refinancing_request.id
        ):
            return
        template_code = CohortCampaignPN.TEMPLATE_CODE_OTHER_REFINANCING_2
        data = {
            "title": CohortCampaignPN.SUBJECT_OTHER_REFINANCING_2,
            "body": CohortCampaignPN.MESSAGE_OTHER_REFINANCING_2,
            "image_url": "{}pn_program_berkah_r6_2.png".format(self.base_image_url_campaign),
        }
        self.pn_client.loan_refinancing_notification(
            self.loan_refinancing_request, data, template_code
        )

    # send third PN for Requested status campaign
    def _send_requested_status_campaign_reminder_minus_1(self):
        if not check_loan_refinancing_with_requested_status_cohort_campaign(
            self.loan_refinancing_request.id
        ):
            return
        template_code = CohortCampaignPN.TEMPLATE_CODE_OTHER_REFINANCING_3
        data = {
            "title": CohortCampaignPN.SUBJECT_OTHER_REFINANCING_3,
            "body": CohortCampaignPN.MESSAGE_OTHER_REFINANCING_3,
            "image_url": "{}pn_program_berkah_r6_3.png".format(self.base_image_url_campaign),
        }
        self.pn_client.loan_refinancing_notification(
            self.loan_refinancing_request, data, template_code
        )


class CovidLoanRefinancingRobocall(object):
    def __init__(self, loan_refinancing_request):
        self.loan_refinancing_request = loan_refinancing_request
        self.robocall = get_voice_client_v2()
        self.loan = loan_refinancing_request.loan
        self.account = loan_refinancing_request.account
        self.is_for_j1 = True if loan_refinancing_request.account else False
        if self.is_for_j1:
            self.application = self.account.application_set.last()
        else:
            self.application = self.loan.application
        self.customer = self.application.customer
        self.product_type = loan_refinancing_request.product_type
        self.status = loan_refinancing_request.status
        if self.is_for_j1:
            self.payment = self.account.accountpayment_set.not_paid_active().first()
        else:
            self.payment = self.loan.payment_set.not_paid_active().first()

    def send_proactive_robocall(self, filter_data, limit):
        all_template_codes = None
        if self.status == CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_email:
            all_template_codes = dict(
                robocall="emailsent_offer_first_robocall",
                pn=("emailsent_offer_second_pn",),
                email=("emailsent_offer_first_email", "emailsent_offer_first_email_b5"),
            )
        elif self.status == CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_offer:
            all_template_codes = dict(
                robocall="offergenerated_first_robocall",
                pn=("offergenerated_second_pn",),
                email=("offergenerated_first_email", "offergenerated_first_email_b5"),
            )

        if all_template_codes and self._send_robocall_validation(
            all_template_codes, filter_data, limit
        ):
            if self.status == CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_email:
                if limit >= 2:
                    text = (
                        "Selamat siang {}, Anda adalah salah satu nasabah terpilih yang "
                        "mendapatkan program keringanan angsuran dari JULO. Segera cek email"
                        " Anda untuk info lebih lanjut karena kesempatan terbatas. "
                        "Terima kasih.".format(self.application.fullname_with_title)
                    )
                else:
                    text = (
                        "Selamat pagi {}, Anda adalah salah satu nasabah terpilih yang "
                        "mendapatkan program keringanan angsuran dari JULO. Segera cek"
                        " email Anda untuk info lebih lanjut karena kesempatan terbatas."
                        " Terima kasih.".format(self.application.fullname_with_title)
                    )
            elif self.status == CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_offer:
                expire_date_word = convert_date_to_word(self.loan_refinancing_request.expire_date)
                if limit >= 2:
                    text = (
                        "Selamat siang {}, Untuk melanjutkan pengajuan keringanan JULO, pilih "
                        "antara Pelunasan Dengan Diskon atau restrukturisasi pinjaman paling "
                        "lambat {}. Jika butuh bantuan, tekan 1. Agen JULO akan menghubungi "
                        "Anda. Terima kasih".format(
                            self.application.fullname_with_title, expire_date_word
                        )
                    )
                else:
                    text = (
                        "Selamat pagi {}, Untuk melanjutkan pengajuan keringanan JULO, pilih "
                        "antara Pelunasan Dengan Diskon atau restrukturisasi pinjaman paling "
                        "lambat {}. Jika Anda butuh bantuan, tekan 1. Agen JULO akan "
                        "menghubungi Anda. Terima kasih".format(
                            self.application.fullname_with_title, expire_date_word
                        )
                    )

            phone_number = self.application.mobile_phone_1
            self.robocall.refinancing_reminder(
                phone_number,
                self.payment.id,
                all_template_codes["robocall"],
                text,
                is_for_j1=self.is_for_j1,
            )

    def send_reminder_refinancing_minus_3_robocall(self, filter_data, limit):
        all_template_codes = None
        if self.status == CovidRefinancingConst.STATUSES.offer_selected:
            all_template_codes = dict(
                robocall="offerselected_first_robocall_R1R2R3R4",
                pn=("offerselected_first_PN_R1R2R3R4",),
                email=(
                    "offerselected_first_email_R4",
                    "offerselected_first_email_R1",
                    "offerselected_first_email_R2R3",
                    "offerselected_first_email_R4_b5",
                ),
            )
        elif self.status == CovidRefinancingConst.STATUSES.approved:
            all_template_codes = dict(
                robocall="approved_first_robocall_alloffers",
                pn=("approved_offer_first_pn",),
                email=(
                    "approved_first_email_R1R2R3",
                    "approved_first_email_R4",
                    "approved_first_email_R5R6",
                    "approved_first_email_R5R6_b5",
                    "approved_first_email_R4_b5",
                ),
            )

        if all_template_codes and self._send_robocall_validation(
            all_template_codes, filter_data, limit
        ):
            expire_date_word = convert_date_to_word(self.loan_refinancing_request.first_due_date)
            if self.status == CovidRefinancingConst.STATUSES.offer_selected:
                if limit >= 2:
                    text = (
                        "Selamat siang {}, Anda telah memilih program keringanan pinjaman "
                        "JULO. Silakan konfirmasi dengan klik tautan pada email Anda"
                        " sebelum tanggal {}. Tekan 1 jika Anda ingin dihubungi kembali oleh "
                        "agen kami. Terima kasih".format(
                            self.application.first_name_with_title, expire_date_word
                        )
                    )
                else:
                    text = (
                        "Selamat pagi {}, Anda telah memilih program keringanan pinjaman "
                        "JULO. Silakan konfirmasi dengan klik tautan pada email Anda"
                        " sebelum {}. Tekan 1 jika Anda ingin dihubungi kembali oleh agen"
                        " kami. Terima kasih".format(
                            self.application.first_name_with_title, expire_date_word
                        )
                    )
            elif self.status == CovidRefinancingConst.STATUSES.approved:
                if limit >= 2:
                    text = (
                        "Selamat siang {}, Anda telah konfirmasi program keringanan pinjaman "
                        "JULO. Bayar sebesar {} sebelum {} untuk mengaktifkan program. Jika "
                        "butuh bantuan, tekan 1 untuk dihubungi oleh agen kami. "
                        "Terima kasih".format(
                            self.application.fullname_with_title,
                            self.loan_refinancing_request.prerequisite_amount,
                            expire_date_word,
                        )
                    )
                else:
                    text = (
                        "Selamat pagi {}, Anda telah konfirmasi program keringanan pinjaman "
                        "JULO. Bayar sebesar {} sebelum {} untuk mengaktifkan program. Jika "
                        "butuh bantuan, tekan 1 untuk dihubungi oleh agen kami. "
                        "Terima kasih".format(
                            self.application.first_name_with_title,
                            self.loan_refinancing_request.prerequisite_amount,
                            expire_date_word,
                        )
                    )

            phone_number = self.application.mobile_phone_1
            self.robocall.refinancing_reminder(
                phone_number,
                self.payment.id,
                all_template_codes["robocall"],
                text,
                is_for_j1=self.is_for_j1,
            )

    def _valid_voice_call_history(self, template_code, filter_data, limit):
        if not template_code:
            return True

        if not self.payment:
            return False

        voice_call_records = (
            VoiceCallRecord.objects.annotate(
                call_price_int=Func(
                    F('call_price'),
                    template='%(function)s(%(expressions)s AS %(type)s)',
                    function='Cast',
                    type='float',
                ),
                duration_int=Func(
                    F('duration'),
                    template='%(function)s(%(expressions)s AS %(type)s)',
                    function='Cast',
                    type='int',
                ),
            )
            .filter(
                template_code=template_code,
                event_type=VoiceTypeStatus.REFINANCING_REMINDER,
                voice_identifier=self.payment.id,
            )
            .filter(Q(call_price__isnull=True) | Q(call_price_int=0) | Q(duration_int__lt=15))
        )

        if filter_data:
            voice_call_records = voice_call_records.filter(**filter_data)

        return voice_call_records.count() == limit

    def _valid_pn_history(self, template_codes):
        if not template_codes:
            return True

        pn_deliveries = PNDelivery.objects.filter(
            fcm_id=self.customer.last_gcm_id, pn_blast__name__in=template_codes
        ).exclude(
            status__in=(
                "open",
                "click",
            )
        )

        return pn_deliveries.count() >= 1

    def _valid_email_history(self, template_codes):
        if not template_codes:
            return True

        if not self.payment:
            return False
        email_history_filter = dict(
            template_code__in=template_codes,
        )
        if self.is_for_j1:
            email_history_filter['account_payment_id'] = self.payment.id
        else:
            email_history_filter['payment_id'] = self.payment.id

        email_histories = EmailHistory.objects.filter(**email_history_filter).exclude(
            status__in=("open", "click")
        )

        return email_histories.count() >= 1

    def _send_robocall_validation(self, all_template_codes, filter_data, limit):
        return (
            self._valid_voice_call_history(all_template_codes["robocall"], filter_data, limit)
            and self._valid_pn_history(all_template_codes["pn"])
            and self._valid_email_history(all_template_codes["email"])
        )


def convert_second_to_indonesian_format(time):
    if time < 60:
        return "0 Hari 0 Jam 0 Menit"

    day = time // (24 * 3600)
    time = time % (24 * 3600)
    hour = time // 3600
    time %= 3600
    minutes = time // 60
    return f"{int(day)} Hari {int(hour)} Jam {int(minutes)} Menit"


def generate_image_for_refinancing_countdown(loan_refinancing_request):
    from wand.api import library

    current_timestamp = timezone.localtime(timezone.now())
    expired_timestamp = loan_refinancing_request.cdate + timedelta(
        days=loan_refinancing_request.expire_in_days
    )
    total_second = (expired_timestamp - current_timestamp).total_seconds()
    with Image() as gif:
        # 45 means minutes because we dont generate all the frame
        # just generate 45 frame per hit
        for minute in list(range(0, 45)):
            with Drawing() as draw:
                draw.fill_color = Color('#E2574C')
                draw.font = "Montserrat.otf"
                draw.font_size = 12
                draw.text_alignment = "center"
                draw.text_antialias = True
                label = convert_second_to_indonesian_format(total_second)
                with Image(width=130, height=15, background=Color("#FDEFEE")) as img:
                    x = int(img.width / 2)
                    y = int(10)
                    draw.text(x, y, label)
                    draw.draw(img)
                    gif.sequence.append(img)
            if total_second < 60:
                break

            total_second -= 60

        for frame in gif.sequence:
            with frame:
                library.MagickSetImageIterations(gif.wand, 1)
                frame.delay = 6000  # Centiseconds

        gif_image = io.BytesIO()
        gif.format = 'GIF'
        gif.type = 'optimize'
        gif.save(file=gif_image)
        gif_image.seek(0)

        return gif_image
