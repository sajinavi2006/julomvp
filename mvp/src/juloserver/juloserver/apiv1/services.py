import itertools
import logging
from builtins import str
from datetime import date, datetime, timedelta
import io

import semver

from cacheops import cached
from babel.dates import format_date
from dateutil.relativedelta import relativedelta
from django.db.models import Q
from django.template import TemplateDoesNotExist
from django.template.loader import render_to_string
from django.utils import timezone

from zipfile import ZIP_DEFLATED, ZipFile

from juloserver.application_flow.services import is_active_julo1
from juloserver.loan_selloff.models import LoanSelloff

from ..julo.models import (
    Application,
    ApplicationHistory,
    AwsFaceRecogLog,
    BankApplication,
    CreditScore,
    KycRequest,
    Loan,
    MobileFeatureSetting,
    Offer,
    PartnerLoan,
    Payment,
    ProductLine,
    StatusLookup,
    FeatureSetting,
)
from ..julo.partners import PartnerConstant
from ..julo.product_lines import (
    ProductLineCodes,
    ProductLineManager,
    ProductLineNotFound,
)
from ..julo.statuses import ApplicationStatusCodes, LoanStatusCodes, PaymentStatusCodes
from ..julo.utils import display_rupiah, get_expired_time
from ..streamlined_communication.constant import CommunicationPlatform
from ..streamlined_communication.services import process_streamlined_comm

from juloserver.apiv1.dropdown import write_dropdowns_to_buffer
from juloserver.apiv1.constants import ListImageTypes
from juloserver.julo.constants import FeatureNameConst

logger = logging.getLogger(__name__)


def get_voice_record_script(application):
    if application.product_line_code in ProductLineCodes.loc():
        return get_voice_record_script_loc(application)
    else:
        return get_voice_record_script_default(application)


def get_voice_record_script_default(application):
    script = (
        "Hari ini, tanggal %(TODAY_DATE)s, saya %(FULL_NAME)s lahir tanggal"
        " %(DOB)s mengajukan pinjaman melalui PT. JULO TEKNOLOGI FINANSIAL"
        " dan telah disetujui sebesar yang tertera pada Surat Perjanjian Hutang Piutang "
        "%(LOAN_DURATION)s. Saya berjanji untuk melunasi pinjaman sesuai dengan Surat"
        " Perjanjian Hutang Piutang yang telah saya tanda tangani."
    )
    if application.product_line_code in ProductLineCodes.julo_one():
        from juloserver.loan.services.views_related import (
            get_voice_record_script_loan_default,
        )

        loan = application.account.loan_set.last()
        return get_voice_record_script_loan_default(application, loan)
    if application.account:
        loan = application.account.loan_set.last()
    else:
        loan = application.loan
    if application.product_line_code in ProductLineCodes.mtl():
        loan_duration = "selama %s bulan" % loan.loan_duration
    elif application.product_line_code in ProductLineCodes.bri():
        loan_duration = "selama %s bulan" % loan.loan_duration
    elif application.product_line_code in ProductLineCodes.grab():
        script = (
            "Hari ini, tanggal %(TODAY_DATE)s, saya %(FULL_NAME)s lahir tanggal"
            " %(DOB)s mengajukan pinjaman melalui PT JULO TEKNOLOGI FINANSIAL."
            " Pinjaman sebesar %(LOAN_AMOUNT)s telah disetujui dan saya berjanji"
            " untuk melunasinya %(LOAN_DURATION)s sesuai dengan Perjanjian Hutang"
            " Piutang yang telah saya tanda tangani."
        )
        loan_duration = "dalam kurun waktu 5 minggu"
    elif application.product_line_code in ProductLineCodes.stl():
        formatted_due_date = format_date(
            application.loan.payment_set.first().due_date, 'd MMMM yyyy', locale='id_ID'
        )
        loan_duration = "yang jatuh tempo pada tanggal %s" % formatted_due_date
    elif application.product_line_code in ProductLineCodes.grabfood():
        loan_duration = "selama %s minggu" % loan.loan_duration
    else:
        raise ProductLineNotFound(application.product_line_code)
    template_data = {
        "TODAY_DATE": format_date(timezone.now().date(), 'd MMMM yyyy', locale='id_ID'),
        "FULL_NAME": application.fullname,
        "DOB": format_date(application.dob, 'd MMMM yyyy', locale='id_ID'),
        "LOAN_AMOUNT": display_rupiah(loan.loan_amount),
        "LOAN_DURATION": loan_duration,
    }
    log_dict = {'application_id': application.id}
    log_dict.update(template_data)
    logger.info(log_dict)
    return script % template_data


def get_voice_record_script_loc(application):
    script = (
        "Hari ini, tanggal %(TODAY_DATE)s, saya %(FULL_NAME)s lahir tanggal"
        " %(DOB)s mengaktifkan limit kredit JULO dan telah disetujui melalui"
        " PT. JULO TEKNOLOGI FINANSIAL sebesar %(CREDIT_LIMIT)s."
        " Saya berjanji untuk melunasi tagihan setiap bulan nya sesuai dengan Surat"
        " Perjanjian Hutang Piutang yang telah saya tanda tangani."
    )
    template_data = {
        "TODAY_DATE": format_date(timezone.now().date(), 'd MMMM yyyy', locale='id_ID'),
        "FULL_NAME": application.fullname,
        "DOB": format_date(application.dob, 'd MMMM yyyy', locale='id_ID'),
        "CREDIT_LIMIT": display_rupiah(application.line_of_credit.limit),
    }
    log_dict = {'application_id': application.id}
    log_dict.update(template_data)
    logger.info(log_dict)
    return script % template_data


def determine_product_line(customer, data):
    if 'product_line_code' in data:
        product_line_code = int(data['product_line_code'])
    else:
        product_line_code = None
    stl_max_duration = ProductLineManager.get_or_none(ProductLineCodes.STL1).max_duration
    any_paid_off_loan = customer.loan_set.filter(loan_status=LoanStatusCodes.PAID_OFF).first()
    if any_paid_off_loan is None:
        if product_line_code is not None and product_line_code in ProductLineCodes.ctl():
            product_line = ProductLine.objects.get(product_line_code=ProductLineCodes.CTL1)
        else:
            if int(data['loan_duration_request']) == stl_max_duration:
                product_line = ProductLine.objects.get(product_line_code=ProductLineCodes.STL1)
            else:
                product_line = ProductLine.objects.get(product_line_code=ProductLineCodes.MTL1)
    else:
        if product_line_code is not None and product_line_code in ProductLineCodes.ctl():
            product_line = ProductLine.objects.get(product_line_code=ProductLineCodes.CTL2)
        else:
            if int(data['loan_duration_request']) == stl_max_duration:
                product_line = ProductLine.objects.get(product_line_code=ProductLineCodes.STL2)
            else:
                product_line = ProductLine.objects.get(product_line_code=ProductLineCodes.MTL2)
    logger.info(
        {
            'any_paid_off_loan': any_paid_off_loan,
            'customer_id': customer.id,
            'loan_duration_request': data['loan_duration_request'],
            'product_line': product_line,
        }
    )
    return product_line


def render_account_summary_cards(customer, application=None):

    account_summary_cards = []

    if application is None or not isinstance(application, Application):
        app_qs = Application.objects.regular_not_deletes().filter(customer=customer).order_by('-id')
        application = app_qs.first()  # get first for now

    # User has not submitted any application. show default message
    if application is None:
        account_summary_cards.append(render_default_card())
        return account_summary_cards

    # User already submitted short form and get score C
    today_date = timezone.localtime(timezone.now()).date()
    start_date = date(2018, 11, 1)
    end_date = date(2018, 11, 30)
    if (
        application.application_status_id < ApplicationStatusCodes.FORM_SUBMITTED
        and start_date <= today_date <= end_date
    ):
        credit_score = CreditScore.objects.get_or_none(application=application)
        if credit_score and credit_score.score == 'C':
            account_summary_cards.append(render_bfi_oct_promo_card())

    # User has completed application and waiting for partner approval
    if application.application_status_id == ApplicationStatusCodes.PENDING_PARTNER_APPROVAL:
        card = render_application_status_card(application, None)
        if card is not None:
            account_summary_cards.append(card)
        return account_summary_cards

    # User has approved partner loan
    if application.application_status_id == ApplicationStatusCodes.PARTNER_APPROVED:
        partner_loan = PartnerLoan.objects.get_or_none(application=application)
        card = render_application_status_card(application, partner_loan)
        if card is not None:
            account_summary_cards.append(card)
        return account_summary_cards

    loan = Loan.objects.get_or_none(customer=customer, application=application)

    # User has submitted application but still waiting for offers
    if loan is None:
        card = render_application_status_card(application, None)
        if card is not None:
            account_summary_cards.append(card)
        return account_summary_cards

    # User has accepted an offer but still going through loan approval
    if loan.loan_status_id == LoanStatusCodes.INACTIVE:
        card = render_application_status_card(application, None)
        if card is not None:
            account_summary_cards.append(card)
        return account_summary_cards

    if loan.loan_status_id == LoanStatusCodes.PAID_OFF:
        card = render_loan_status_card(loan)
        if card is not None:
            account_summary_cards.append(card)
        return account_summary_cards
    # User already has started the loan and has payments
    if loan.loan_status_id not in LoanStatusCodes.inactive_status():
        payments = Payment.objects.by_loan(loan).order_by('due_date')
        # TODO: remove this block as we'll never reach this situation
        # since when the loan is current, payment entries already created
        # if len(payments) <= 0:
        #     # this is probably status 160/161
        #     card = self.render_application_status_card(application, loan)
        #     if card is not None:
        #         account_summary_cards.append(card)
        #     return account_summary_cards

        # The loan is active and has payments
        payment_cards = render_payment_status_cards(loan, payments)
        for payment_card in payment_cards:
            account_summary_cards.append(payment_card)

        # TODO: depracated card for now
        # account_summary_cards.append(self.render_bonus_card(customer))
        return account_summary_cards

    return account_summary_cards


def construct_card(
    msg,
    header,
    bottomimage,
    buttonurl,
    topimage,
    buttontext,
    buttonstyle=None,
    expired_time=None,
    data=None,
):
    card = {
        'body': msg,
        'header': header,
        'bottomimage': bottomimage,
        'buttonurl': buttonurl,
        'topimage': topimage,
        'buttontext': buttontext,
        'buttonstyle': buttonstyle,
        'expired_time': expired_time,
        'data': data,
    }
    logger.info(card)
    return card


def render_loan_status_card(loan):

    total_cb_amt = loan.cashback_earned_total
    if loan.customer.can_reapply:
        url_canreapply = 'http://www.julofinance.com/android/goto/reapply'
        can_reapply_desc = (
            'Untuk mengajukan kembali pinjaman yang baru, silahkan klik tombol Ajukan Pinjaman.'
        )
        btn_text = 'Ajukan Pinjaman Baru'
    else:
        url_canreapply = None
        can_reapply_desc = 'Untuk mengajukan pinjaman baru, silahkan hubungi CS@julofinance.com.'
        btn_text = None

    # set default ctx (stl, bri)
    ctx = {'can_reapply_desc': can_reapply_desc}
    msg = None

    application = loan.application
    if application.product_line_id in ProductLineCodes.mtl():
        ctx = {'total_cb_amt': display_rupiah(total_cb_amt), 'can_reapply_desc': can_reapply_desc}
        msg = render_to_string('MTL_' + str(LoanStatusCodes.PAID_OFF) + '.txt', ctx)
    elif application.product_line_id in ProductLineCodes.stl():
        msg = render_to_string('STL_' + str(LoanStatusCodes.PAID_OFF) + '.txt', ctx)
    elif application.product_line_id in ProductLineCodes.bri():
        msg = render_to_string('STL_' + str(LoanStatusCodes.PAID_OFF) + '.txt', ctx)
    elif application.product_line_id in ProductLineCodes.grab():
        msg = render_to_string('GRAB_' + str(LoanStatusCodes.PAID_OFF) + '.txt')
    elif application.product_line_id in ProductLineCodes.grabfood():
        msg = render_to_string('GRAB_' + str(LoanStatusCodes.PAID_OFF) + '.txt')

    header = 'INFORMASI PINJAMAN'

    if is_active_julo1():
        if loan.customer.can_reapply:
            url_canreapply = 'https://play.google.com/store/apps/details?id=com.julofinance.juloapp'
            btn_text = 'Update'
            msg = (
                'Update aplikasi Anda sekarang dan nikmati '
                'pinjaman lebih mudah dengan limit kredit JULO.'
            )
            header = 'BARU! Limit Kredit JULO'
        else:
            url_canreapply = None
            btn_text = None
            msg = (
                'Mohon maaf, Anda tidak dapat mengajukan pinjaman saat ini. '
                '%s' % loan.customer.reapply_msg
            )

    if not msg:
        return None
    card = construct_card(msg, header, None, url_canreapply, None, btn_text)

    return card


def render_payment_status_cards(loan, payments):
    """
    get the template and the required parameters then combine them together and put them in to
    the cards.
    """
    payment_status_cards = []
    application = loan.application
    for payment in payments:
        now = datetime.now().date()

        # there are existing user that apply partner non app (laku6, pede) open our app and
        # got break on home screen
        # cause condition did'nt match
        if application.product_line_id not in ProductLineCodes.with_payment_homescreen():
            continue

        # Payment MTL t-5, t-4, t-3, t-2,
        if (
            application.product_line_id in ProductLineCodes.mtl()
            and payment.due_date - relativedelta(days=2) >= now
            and payment.paid_amount != payment.due_amount
            and payment.status not in PaymentStatusCodes.paid_status_codes()
        ):
            if payment.due_date - relativedelta(days=4) >= now:
                deadline_date = payment.due_date - relativedelta(days=4)
            else:
                deadline_date = payment.due_date - relativedelta(days=2)

            ctx = {
                'cashback_multiplier': payment.cashback_multiplier,
                'deadline_date': deadline_date.strftime("%d %B %Y"),
            }
            msg = render_to_string('MTL_Tminus5_Tminus2.txt', ctx)
            card = construct_card(
                msg,
                'INFORMASI PINJAMAN',
                None,
                'http://www.julofinance.com/android/goto/loan_activity',
                None,
                'AKTIVITAS PINJAMAN',
            )
            payment_status_cards.append(card)

        # 'Payment not due' status is only shown for the next upcoming payment 310.
        if payment.payment_status_id == PaymentStatusCodes.PAYMENT_NOT_DUE:
            payment_seq = payment.payment_number
            due_amount = payment.due_amount
            due_date = payment.due_date.strftime("%d %B %Y")

            # parameters
            ctx = {
                'payment_seq': payment_seq,
                'due_amount': display_rupiah(due_amount),
                'due_date': due_date,
            }

            if application.product_line_id in itertools.chain(
                ProductLineCodes.mtl(), ProductLineCodes.bri(), ProductLineCodes.grabfood()
            ):
                # replace placeholders in template with the parameters
                msg = render_to_string(
                    'MTL_' + str(PaymentStatusCodes.PAYMENT_NOT_DUE) + '.txt', ctx
                )
            elif application.product_line_id in ProductLineCodes.stl():
                msg = render_to_string(
                    'STL_' + str(PaymentStatusCodes.PAYMENT_NOT_DUE) + '.txt', ctx
                )
            elif application.product_line_id in ProductLineCodes.grab():
                msg = render_to_string(
                    'GRAB_' + str(PaymentStatusCodes.PAYMENT_NOT_DUE) + '.txt', ctx
                )

            card = construct_card(
                msg,
                'INFORMASI PINJAMAN',
                None,
                'http://www.julofinance.com/android/goto/loan_activity',
                None,
                'Aktivitas Pinjaman',
            )
            payment_status_cards.append(card)
            break  # we stop here if next payment is due

        card = None

        # All payments with status codes 311-327 will be shown on homepage at all times,
        # until they're paid.
        # Payment due in 3 days 311
        if (
            payment.payment_status_id == PaymentStatusCodes.PAYMENT_DUE_IN_3_DAYS
            and payment.paid_amount != payment.due_amount
        ):  #
            # status
            # 311 and has not paid
            ctx = {
                'due_amount': display_rupiah(payment.due_amount),
                'due_date': payment.due_date.strftime("%d %B %Y"),
                'julo_bank_name': loan.julo_bank_name,
                'julo_bank_account_number': loan.julo_bank_account_number,
                'late_fee': display_rupiah(payment.calculate_late_fee()),
            }

            if application.product_line_id in itertools.chain(
                ProductLineCodes.mtl(), ProductLineCodes.bri(), ProductLineCodes.grabfood()
            ):
                ctx['payment_seq'] = payment.payment_number
                msg = render_to_string(
                    'MTL_' + str(PaymentStatusCodes.PAYMENT_DUE_IN_3_DAYS) + '.txt', ctx
                )
            elif application.product_line_id in ProductLineCodes.stl():
                ctx['late_fee'] = display_rupiah(50000)
                msg = render_to_string(
                    'STL_' + str(PaymentStatusCodes.PAYMENT_DUE_IN_3_DAYS) + '.txt', ctx
                )
            elif application.product_line_id in ProductLineCodes.grab():
                ctx['payment_seq'] = payment.payment_number
                msg = render_to_string(
                    'GRAB_' + str(PaymentStatusCodes.PAYMENT_DUE_IN_3_DAYS) + '.txt', ctx
                )

            card = construct_card(
                msg,
                'INFORMASI PINJAMAN',
                None,
                'http://www.julofinance.com/android/goto/loan_activity',
                None,
                'Aktivitas Pinjaman',
            )

        # Payment due today 312
        elif (
            payment.payment_status_id == PaymentStatusCodes.PAYMENT_DUE_TODAY
            and payment.paid_amount != payment.due_amount
        ):
            # 312 and has not paid
            ctx = {
                'due_amount': display_rupiah(payment.due_amount),
                'due_date': payment.due_date.strftime("%d %B %Y"),
                'julo_bank_name': loan.julo_bank_name,
                'julo_bank_account_number': loan.julo_bank_account_number,
                'late_fee': display_rupiah(payment.calculate_late_fee()),
            }

            if application.product_line_id in itertools.chain(
                ProductLineCodes.mtl(), ProductLineCodes.bri(), ProductLineCodes.grabfood()
            ):
                ctx['payment_seq'] = payment.payment_number
                # replace placeholders in template with the parameters
                msg = render_to_string(
                    'MTL_' + str(PaymentStatusCodes.PAYMENT_DUE_TODAY) + '.txt', ctx
                )
            elif application.product_line_id in ProductLineCodes.stl():
                ctx['late_fee'] = display_rupiah(50000)
                msg = render_to_string(
                    'STL_' + str(PaymentStatusCodes.PAYMENT_DUE_TODAY) + '.txt', ctx
                )
            elif application.product_line_id in ProductLineCodes.grab():
                ctx['payment_seq'] = payment.payment_number
                msg = render_to_string(
                    'GRAB_' + str(PaymentStatusCodes.PAYMENT_DUE_TODAY) + '.txt', ctx
                )

            card = construct_card(
                msg,
                'INFORMASI PINJAMAN',
                None,
                'http://www.julofinance.com/android/goto/loan_activity',
                None,
                'Aktivitas Pinjaman',
            )

        # 1dpd
        elif (
            payment.payment_status.status_code == PaymentStatusCodes.PAYMENT_1DPD
            and payment.paid_amount != payment.due_amount
        ):
            #
            # status 320 and has not paid
            ctx = {
                'late_fee': display_rupiah(payment.calculate_late_fee()),
                'due_amount': display_rupiah(payment.due_amount),
                'due_date': payment.due_date.strftime("%d %B %Y"),
                'grace_date': payment.grace_date.strftime("%d %B %Y"),
                'julo_bank_name': loan.julo_bank_name,
                'julo_bank_account_number': loan.julo_bank_account_number,
                'late_days': (datetime.now().date() - payment.due_date).days,
            }

            if application.product_line_id in ProductLineCodes.mtl():
                ctx['payment_seq'] = payment.payment_number
                # replace placeholders in template with the parameters
                msg = render_to_string('MTL_' + str(PaymentStatusCodes.PAYMENT_1DPD) + '.txt', ctx)
            elif application.product_line_id in ProductLineCodes.stl():
                ctx['late_fee'] = display_rupiah(50000)
                msg = render_to_string('STL_' + str(PaymentStatusCodes.PAYMENT_1DPD) + '.txt', ctx)
            elif application.product_line_id in itertools.chain(
                ProductLineCodes.bri(), ProductLineCodes.grabfood()
            ):
                ctx['payment_seq'] = payment.payment_number
                msg = render_to_string(
                    'MTL_' + str(PaymentStatusCodes.PAYMENT_NOT_DUE) + '.txt', ctx
                )
            elif application.product_line_id in ProductLineCodes.grab():
                ctx['payment_seq'] = payment.payment_number
                msg = render_to_string(
                    'GRAB_' + str(PaymentStatusCodes.PAYMENT_NOT_DUE) + '.txt', ctx
                )

            card = construct_card(
                msg,
                'INFORMASI PINJAMAN',
                None,
                'http://www.julofinance.com/android/goto/loan_activity',
                None,
                'Aktivitas Pinjaman',
            )

        elif (
            payment.payment_status.status_code == PaymentStatusCodes.PAYMENT_5DPD
            or payment.payment_status.status_code == StatusLookup.PAYMENT_30DPD_CODE
            or payment.payment_status.status_code == PaymentStatusCodes.PAYMENT_60DPD
            or payment.payment_status.status_code == PaymentStatusCodes.PAYMENT_90DPD
            or payment.payment_status.status_code == PaymentStatusCodes.PAYMENT_120DPD
            or payment.payment_status.status_code == PaymentStatusCodes.PAYMENT_150DPD
            or payment.payment_status.status_code == PaymentStatusCodes.PAYMENT_180DPD
        ) and payment.paid_amount != payment.due_amount:
            ctx = {
                'payment_seq': payment.payment_number,
                'late_fee': display_rupiah(payment.late_fee_amount),
                'due_amount': display_rupiah(payment.due_amount),
                'due_date': payment.due_date,
                'julo_bank_name': loan.julo_bank_name,
                'julo_bank_account_number': loan.julo_bank_account_number,
                'late_days': (datetime.now().date() - payment.due_date).days,
            }

            if application.product_line_id in itertools.chain(
                ProductLineCodes.mtl(), ProductLineCodes.bri()
            ):
                msg = render_to_string('MTL_' + str(PaymentStatusCodes.PAYMENT_5DPD) + '.txt', ctx)
            elif application.product_line_id in ProductLineCodes.stl():
                if (
                    payment.due_date + relativedelta(days=10) <= date.today()
                    and payment.due_date + relativedelta(days=29) >= date.today()
                ):
                    msg = render_to_string('STL_10_dpd.txt', ctx)
                else:
                    msg = render_to_string(
                        'STL_' + str(payment.payment_status.status_code) + '.txt', ctx
                    )
            elif application.product_line_id in ProductLineCodes.grab():
                if payment.due_date + timedelta(days=14) < datetime.now().date():
                    msg = render_to_string(
                        'GRAB_' + str(PaymentStatusCodes.PAYMENT_5DPD) + '.txt', ctx
                    )
                else:
                    msg = render_to_string(
                        'GRAB_' + str(PaymentStatusCodes.PAYMENT_NOT_DUE) + '.txt', ctx
                    )
            elif application.product_line_id in ProductLineCodes.grabfood():
                ctx['payment_seq'] = payment.payment_number
                msg = render_to_string(
                    'MTL_' + str(PaymentStatusCodes.PAYMENT_NOT_DUE) + '.txt', ctx
                )

            card = construct_card(
                msg,
                'INFORMASI PINJAMAN',
                None,
                'http://www.julofinance.com/android/goto/loan_activity',
                None,
                'Aktivitas Pinjaman',
            )

        # 'Paid on time/ within grace period / late' will be shown only for 7 days
        # since the payment is made.
        # Paid on time
        elif payment.payment_status_id == PaymentStatusCodes.PAID_ON_TIME:
            payment_seq = payment.payment_number
            cb_amt = payment.cashback_earned
            total_cb_amt = loan.cashback_earned_total
            if application.product_line_id in itertools.chain(
                ProductLineCodes.grab(), ProductLineCodes.grabfood()
            ):
                if payment.paid_date == datetime.now().date():
                    ctx = {'payment_seq': payment_seq}
                    msg = render_to_string(
                        'GRAB_' + str(PaymentStatusCodes.PAID_ON_TIME) + '.txt', ctx
                    )
                    card = construct_card(
                        msg,
                        'INFORMASI PINJAMAN',
                        None,
                        'http://www.julofinance.com/android/goto/loan_activity',
                        None,
                        'Aktivitas Pinjaman',
                    )
            elif payment.paid_date + timedelta(days=7) >= datetime.now().date():
                if application.product_line_id in ProductLineCodes.mtl():
                    ctx = {
                        'payment_seq': payment_seq,
                        'cb_amt': display_rupiah(cb_amt),
                        'total_cb_amt': display_rupiah(total_cb_amt),
                    }
                    msg = render_to_string(
                        'MTL_' + str(PaymentStatusCodes.PAID_ON_TIME) + '.txt', ctx
                    )
                elif application.product_line_id in ProductLineCodes.stl():
                    msg = render_to_string('STL_' + str(PaymentStatusCodes.PAID_ON_TIME) + '.txt')
                elif application.product_line_id in ProductLineCodes.bri():
                    ctx = {'payment_seq': payment_seq}
                    msg = render_to_string(
                        'BRI_' + str(PaymentStatusCodes.PAID_ON_TIME) + '.txt', ctx
                    )

                if application.product_line_id not in ProductLineCodes.grab():
                    card = construct_card(
                        msg,
                        'INFORMASI PINJAMAN',
                        None,
                        'http://www.julofinance.com/android/goto/loan_activity',
                        None,
                        'Aktivitas Pinjaman',
                    )

        elif (
            payment.payment_status_id == PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD
            or payment.payment_status.status_code == PaymentStatusCodes.PAID_LATE
        ):
            payment_seq = payment.payment_number
            if application.product_line_id in itertools.chain(
                ProductLineCodes.grab(), ProductLineCodes.grabfood()
            ):
                if payment.paid_date == datetime.now().date():
                    ctx = {'payment_seq': payment_seq}
                    msg = render_to_string(
                        'MTL_' + str(PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD) + '.txt', ctx
                    )
                    card = construct_card(
                        msg,
                        'INFORMASI PINJAMAN',
                        None,
                        'http://www.julofinance.com/android/goto/loan_activity',
                        None,
                        'Aktivitas Pinjaman',
                    )
            elif payment.paid_date + timedelta(days=7) >= datetime.now().date():
                if application.product_line_id in ProductLineCodes.mtl():
                    ctx = {'payment_seq': payment_seq}
                    msg = render_to_string(
                        'MTL_' + str(PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD) + '.txt', ctx
                    )
                elif application.product_line_id in ProductLineCodes.stl():
                    msg = render_to_string(
                        'STL_' + str(PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD) + '.txt'
                    )
                elif application.product_line_id in ProductLineCodes.bri():
                    ctx = {'payment_seq': payment_seq}
                    msg = render_to_string(
                        'BRI_' + str(PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD) + '.txt', ctx
                    )

                if application.product_line_id not in ProductLineCodes.grab():
                    card = construct_card(
                        msg,
                        'INFORMASI PINJAMAN',
                        None,
                        'http://www.julofinance.com/android/goto/loan_activity',
                        None,
                        'Aktivitas Pinjaman',
                    )

        if card is not None:
            payment_status_cards.append(card)

    return payment_status_cards


def render_application_status_card(application, loan):
    from juloserver.apiv2.services import get_credit_score3, is_c_score_in_delay_period

    """
    get the template and the required parameters then combine them together.
    this is more generic than render_by_payment method since the templates 99%
    don't need any parameters.
    """
    app_status = application.application_status_id
    filter_ = dict(communication_platform=CommunicationPlatform.IAN, status_code=app_status)
    if app_status == ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED:
        app_history = ApplicationHistory.objects.filter(application=application).last()
        expired_time = get_expired_time(app_history)
        passed_face_recog = AwsFaceRecogLog.objects.filter(application=application).last()
        failed_upload_image_reasons = [
            'failed upload selfie image',
            'Passed KTP check & failed upload selfie image',
        ]
        if application.app_version and semver.match(application.app_version, ">=1.1.1"):
            template = str(app_status) + '.txt'
            button_text = (
                "Unggah Dokumen"
                if passed_face_recog and passed_face_recog.is_quality_check_passed
                else "Unggah Foto"
            )
            if (
                passed_face_recog
                and not passed_face_recog.is_quality_check_passed
                or (app_history and app_history.change_reason in failed_upload_image_reasons)
            ):
                if (
                    app_history
                    and app_history.change_reason in failed_upload_image_reasons
                    or not passed_face_recog.raw_response['FaceRecordsStatus']
                    and not passed_face_recog.raw_response['UnindexedFaces']
                ):
                    template = str(app_status) + '_no_face_found' + '.txt'
                elif passed_face_recog.raw_response['UnindexedFaces']:
                    template = str(app_status) + '_no_face_and_bad_image_quality' + '.txt'
                elif not passed_face_recog.is_quality_check_passed:
                    template = str(app_status) + '_bad_image_quality' + '.txt'
            filter_['template_code'] = 'ian_' + template.split('.')[0]
            msg = process_streamlined_comm(filter_)
            if not msg:
                msg = render_to_string(template, None)
            card = construct_card(
                msg,
                "INFORMASI PENGAJUAN",
                None,
                'http://www.julofinance.com/android/goto/appl_docs',
                None,
                button_text,
                None,
                expired_time,
            )
        else:
            ctx = {'email': application.email}
            template = str(app_status) + '_old.txt'
            if passed_face_recog and not passed_face_recog.is_quality_check_passed:
                if (
                    not passed_face_recog.raw_response['FaceRecordsStatus']
                    and not passed_face_recog.raw_response['UnindexedFaces']
                ):
                    template = str(app_status) + '_no_face_found' + '.txt'
                elif passed_face_recog.raw_response['UnindexedFaces']:
                    template = str(app_status) + '_no_face_and_bad_image_quality' + '.txt'
                elif not passed_face_recog.is_quality_check_passed:
                    template = str(app_status) + '_bad_image_quality' + '.txt'
            filter_['template_code'] = 'ian_' + template.split('.')[0]
            msg = process_streamlined_comm(filter_, ctx)
            if not msg:
                msg = render_to_string(template, ctx)
            card = construct_card(
                msg, "INFORMASI PENGAJUAN", None, None, None, None, None, expired_time
            )
        return card

    credit_score = get_credit_score3(application)
    if app_status == ApplicationStatusCodes.FORM_PARTIAL and not credit_score:
        msg = render_to_string(str(app_status) + '_no_score.txt', None)
        card = construct_card(msg, "INFORMASI PENGAJUAN", None, None, None, None, None, None)
        return card

    mocked_rating_score_tags_list = ['c_failed_binary']
    mocked_rating_score_feature_setting = MobileFeatureSetting.objects.filter(
        feature_name='mock_rating_page', is_active=True
    ).last()

    if mocked_rating_score_feature_setting:
        mocked_rating_score_tags_list = mocked_rating_score_feature_setting.parameters['score_tags']

    c_mocked_customer = CreditScore.objects.filter(application=application, score='C')

    if None in mocked_rating_score_tags_list:
        c_mocked_customer = c_mocked_customer.filter(
            Q(score_tag__isnull=True) | Q(score_tag__in=mocked_rating_score_tags_list)
        ).exists()
    else:
        c_mocked_customer = c_mocked_customer.filter(
            score_tag__in=mocked_rating_score_tags_list
        ).exists()

    if c_mocked_customer and is_c_score_in_delay_period(application):
        c_mocked_customer = False

    if app_status == ApplicationStatusCodes.FORM_PARTIAL and c_mocked_customer:
        if application.customer.is_review_submitted:
            return
        if application.app_version and semver.match(application.app_version, ">=3.17.0"):
            msg = render_to_string(str(app_status) + '_c_binary_failed.txt', None)
            card = construct_card(
                msg,
                "KRITIK DAN SARAN",
                None,
                'http://www.julofinance.com/android/goto/rating_in_apps',
                None,
                "Kritik dan Saran",
                None,
                None,
            )
            return card

    # Header
    header = None
    if app_status in (
        ApplicationStatusCodes.FORM_PARTIAL,
        ApplicationStatusCodes.FORM_SUBMITTED,
        ApplicationStatusCodes.FORM_SUBMISSION_ABANDONED,
        ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
        ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
        ApplicationStatusCodes.PRE_REJECTION,
        ApplicationStatusCodes.PENDING_PARTNER_APPROVAL,
        ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
        ApplicationStatusCodes.DOCUMENTS_VERIFIED,
        ApplicationStatusCodes.CALL_ASSESSMENT,
        ApplicationStatusCodes.APPLICATION_RESUBMITTED,
        ApplicationStatusCodes.APPLICATION_DENIED,
        ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED,
        ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
        ApplicationStatusCodes.OFFER_MADE_TO_CUSTOMER,
        ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
        ApplicationStatusCodes.OFFER_DECLINED_BY_CUSTOMER,
        ApplicationStatusCodes.OFFER_EXPIRED,
        ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
        ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL,
        ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING,
        ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
        ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
        ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING,
        ApplicationStatusCodes.ACTIVATION_CALL_FAILED,
        ApplicationStatusCodes.LEGAL_AGREEMENT_RESUBMISSION_REQUESTED,
        ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED,
        ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED,
        ApplicationStatusCodes.LEGAL_AGREEMENT_EXPIRED,
        ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED_AND_DP_PENDING,
        ApplicationStatusCodes.DOWN_PAYMENT_PAID,
        ApplicationStatusCodes.DOWN_PAYMENT_EXPIRED,
        ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
        ApplicationStatusCodes.FUND_DISBURSAL_FAILED,
        ApplicationStatusCodes.PARTNER_APPROVED,
        ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
        ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
        ApplicationStatusCodes.KYC_IN_PROGRESS,
        ApplicationStatusCodes.DIGISIGN_FAILED,
        ApplicationStatusCodes.LENDER_APPROVAL,
    ):
        header = 'INFORMASI PENGAJUAN'
    elif app_status == ApplicationStatusCodes.FORM_CREATED:
        header = 'WELCOME'
    # button text

    button_text = None
    if app_status in (
        ApplicationStatusCodes.FORM_SUBMITTED,
        ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
    ):
        button_text = 'Unggah Dokumen'
    elif app_status == ApplicationStatusCodes.OFFER_MADE_TO_CUSTOMER:
        button_text = 'Penawaran Pinjaman'
    elif app_status in (
        ApplicationStatusCodes.FORM_SUBMISSION_ABANDONED,
        ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
        ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED,
        ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
        ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
        ApplicationStatusCodes.OFFER_DECLINED_BY_CUSTOMER,
        ApplicationStatusCodes.OFFER_EXPIRED,
        ApplicationStatusCodes.LEGAL_AGREEMENT_EXPIRED,
        ApplicationStatusCodes.LOC_APPROVED,
        ApplicationStatusCodes.DOWN_PAYMENT_EXPIRED,
    ):
        button_text = 'Ajukan Pinjaman Baru'
    elif app_status == ApplicationStatusCodes.FORM_PARTIAL:
        button_text = 'Pilih Pinjaman'
    elif app_status in (
        ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
        ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
    ):
        button_text = 'Mohon tunggu telepon dari JULO'
    elif app_status in (
        ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
        ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
        ApplicationStatusCodes.DOCUMENTS_VERIFIED,
        ApplicationStatusCodes.CALL_ASSESSMENT,
        ApplicationStatusCodes.PRE_REJECTION,
        ApplicationStatusCodes.APPLICATION_RESUBMITTED,
        ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
        ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING,
    ):
        button_text = 'Mohon tunggu dan kembali dalam 1 hari kerja'
    elif app_status == ApplicationStatusCodes.KYC_IN_PROGRESS:
        kyc = KycRequest.objects.filter(application=application, is_processed=False).last()
        if kyc:
            if kyc.is_expired:
                button_text = 'Dapatkan Voucher Baru'
            else:
                button_text = 'Aktifkan Rekening'
    elif app_status == ApplicationStatusCodes.FUND_DISBURSAL_FAILED:
        button_text = 'Mohon hubungi JULO'
    elif app_status in (
        ApplicationStatusCodes.LEGAL_AGREEMENT_RESUBMISSION_REQUESTED,
        ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
    ):
        button_text = 'Surat Perjanjian'
    elif app_status in (
        ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED,
        ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED,
    ):
        button_text = 'Silahkan cek jadwal pembayaran cicilan di halaman Aktivitas Pinjaman'
    elif app_status == ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED_AND_DP_PENDING:
        button_text = 'Lakukan pembayaran DP Anda'
    elif app_status == ApplicationStatusCodes.DOWN_PAYMENT_PAID:
        button_text = 'Silakan unggah kwitansi/bukti transfer di halaman Aktivitas Pinjaman'
    elif app_status == ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL:
        button_text = 'Aktivitas Pinjaman'
    elif app_status == ApplicationStatusCodes.DIGISIGN_FACE_FAILED:
        button_text = 'Unggah Selfie'

    # button url
    button_url = None
    if app_status in (
        ApplicationStatusCodes.FORM_SUBMITTED,
        ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
        ApplicationStatusCodes.DIGISIGN_FACE_FAILED,
    ):
        button_url = 'http://www.julofinance.com/android/goto/appl_docs'
    elif app_status == ApplicationStatusCodes.OFFER_MADE_TO_CUSTOMER:
        button_url = 'http://www.julofinance.com/android/goto/got_offers'
    elif app_status == ApplicationStatusCodes.FORM_PARTIAL:
        button_url = 'http://www.julofinance.com/android/goto/product'
    elif app_status == ApplicationStatusCodes.KYC_IN_PROGRESS:
        kyc = KycRequest.objects.filter(application=application, is_processed=False).last()
        if kyc:
            if kyc.is_expired:
                button_url = 'http://www.julofinance.com/android/goto/regen_evoucher'
            else:
                button_url = 'http://www.julofinance.com/android/goto/activate_evoucher'
    elif app_status == ApplicationStatusCodes.FUND_DISBURSAL_FAILED:
        button_url = 'http://www.julofinance.com/android/goto/contactus'
    elif app_status in (
        ApplicationStatusCodes.LEGAL_AGREEMENT_RESUBMISSION_REQUESTED,
        ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
    ):
        button_url = 'http://www.julofinance.com/android/goto/agreement'
    elif app_status == ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL:
        button_url = 'http://www.julofinance.com/android/goto/loan_activity'
    elif app_status in (
        ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
        ApplicationStatusCodes.FORM_SUBMISSION_ABANDONED,
        ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED,
        ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
        ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
        ApplicationStatusCodes.OFFER_DECLINED_BY_CUSTOMER,
        ApplicationStatusCodes.LEGAL_AGREEMENT_EXPIRED,
        ApplicationStatusCodes.OFFER_EXPIRED,
        ApplicationStatusCodes.DOWN_PAYMENT_EXPIRED,
        ApplicationStatusCodes.LOC_APPROVED,
        ApplicationStatusCodes.APPLICATION_DENIED,
    ):
        button_url = 'http://www.julofinance.com/android/goto/reapply'

    template_name = 'ian_' + str(app_status)
    ctx = None
    if (
        app_status == ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
    ):  # template 160.txt needs some paramters from database.
        if loan is not None:
            loan_amount = loan.loan_amount
            loan_active_date = loan.fund_transfer_ts
            loan_amount_text = (
                'telah diproses dan akan masuk ke rekening Bank Anda dalam 1 hari kerja.'
            )
            if application.partner_name == PartnerConstant.DOKU_PARTNER:
                loan_amount_text = 'telah diproses dan akan masuk ke rekening Doku Anda sekarang.'
            ctx = {
                'loan_amount': display_rupiah(loan_amount),
                'loan_amount_text': loan_amount_text,
                'loan_active_date': loan_active_date.strftime("%d %B %Y"),
            }
    elif app_status == StatusLookup.OFFER_MADE_TO_CUSTOMER_CODE:
        offers = Offer.objects.shown_for_application(application=application)
        if offers is not None and offers:
            offer = offers.order_by("-cdate").first()  # maximum cdate
            expiry_date = offer.offer_exp_date
            ctx = {'expiry_date': expiry_date.strftime("%d %B %Y")}
    elif app_status == ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL:
        sphp_expiry_date = application.sphp_exp_date
        ctx = {'expiry_date': sphp_expiry_date.strftime("%d %B %Y")}
    elif app_status in (
        ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED,
        ApplicationStatusCodes.DOWN_PAYMENT_PAID,
    ):
        if application.product_line_code in ProductLineCodes.mtl():
            template_name = 'MTL_' + str(app_status)
        elif application.product_line_code in ProductLineCodes.stl():
            template_name = 'STL_' + str(app_status)
        elif application.product_line_code in ProductLineCodes.bri():
            template_name = 'MTL_' + str(app_status)
        elif application.product_line_code in ProductLineCodes.grab():
            if app_status == ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED:
                template_name = 'MTL_' + str(app_status)
            else:
                template_name = 'MTL_' + str(app_status)
    # TODO : Turn on again after experiment ITI done
    # elif app_status == ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED_AND_DP_PENDING:
    #     payment = loan.payment_set.get(payment_number=1)
    #     ctx = {
    #         'paid_amount': payment.paid_amount,
    #         'due_dates': payment.due_dates,
    #         'bank_name': loan.julo_bank_name
    #     }
    #     if application.product_line_code in ProductLineCodes.mtl():
    #         template_name = 'MTL_' + str(app_status) + '.txt'
    #     elif application.product_line_code in ProductLineCodes.stl():
    #         template_name = 'STL_' + str(app_status) + '.txt'
    #     elif application.product_line_code in ProductLineCodes.bri():
    #         template_name = 'MTL_' + str(app_status) + '.txt'
    #     elif application.product_line_code in ProductLineCodes.grab():
    #         template_name = 'MTL_' + str(app_status) + '.txt'
    elif app_status == ApplicationStatusCodes.PARTNER_APPROVED:
        if loan is not None:
            loan_amount = loan.loan_amount
            contract_number = loan.agreement_number
            ctx = {
                'loan_amount': display_rupiah(loan_amount),
                'contract_number': str(contract_number),
            }
    elif app_status == ApplicationStatusCodes.KYC_IN_PROGRESS:
        kyc = KycRequest.objects.filter(application=application, is_processed=False).last()
        bank_application = BankApplication.objects.filter(application=application).last()
        uker_name = bank_application.uker_name.split(';')[1]
        if kyc:
            if kyc.is_expired:
                ctx = {
                    'color': '#DB4D3D',
                    'eform_voucher': kyc.eform_voucher,
                    'status': 'Kadaluarsa',
                    'uker_name': uker_name,
                }
            else:
                ctx = {
                    'color': '#00ACF0',
                    'eform_voucher': kyc.eform_voucher,
                    'status': 'Aktif',
                    'uker_name': uker_name,
                }

    elif app_status == ApplicationStatusCodes.LOC_APPROVED:
        template_name = 'LOC_' + str(app_status)

    if application.product_line_id in ProductLineCodes.loc():
        button_text, button_url = render_application_status_card_loc(app_status)

    msg = None
    if is_active_julo1():
        if application.customer.can_reapply:
            button_url = 'https://play.google.com/store/apps/details?id=com.julofinance.juloapp'
            button_text = 'Update'
            msg = (
                'Update aplikasi Anda sekarang dan nikmati '
                'pinjaman lebih mudah dengan limit kredit JULO.'
            )
            header = 'BARU! Limit Kredit JULO'
        elif button_url == 'http://www.julofinance.com/android/goto/reapply':
            button_url = None
            button_text = None
            msg = (
                'Mohon maaf, Anda tidak dapat mengajukan pinjaman saat ini. '
                '%s' % application.customer.reapply_msg
            )
            header = 'INFORMASI PENGAJUAN'

    try:
        if not msg:
            filter_['template_code'] = template_name
            msg = process_streamlined_comm(filter_, ctx)
            if not msg:
                # remove ian_ prefix
                template_name = template_name.replace('ian_', '')
                msg = render_to_string(template_name + '.txt', ctx)
    except TemplateDoesNotExist as e:
        logger.error(e)
        return None

    card = construct_card(msg, header, None, button_url, None, button_text)
    return card


def render_application_status_card_loc(app_status):
    button_text = None
    button_url = None

    # button text
    if app_status == ApplicationStatusCodes.FORM_PARTIAL:
        button_text = 'Pilih Pinjaman'
    elif app_status in (
        ApplicationStatusCodes.FORM_SUBMITTED,
        ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
    ):
        button_text = 'Unggah Dokumen'
    elif app_status in (
        ApplicationStatusCodes.FORM_SUBMISSION_ABANDONED,
        ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED,
        ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
        ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
        ApplicationStatusCodes.OFFER_DECLINED_BY_CUSTOMER,
        ApplicationStatusCodes.LEGAL_AGREEMENT_EXPIRED,
        ApplicationStatusCodes.DOWN_PAYMENT_EXPIRED,
    ):
        button_text = 'Ajukan Pengaktifan Baru'
    elif app_status in (
        ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
        ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
        ApplicationStatusCodes.DOCUMENTS_VERIFIED,
        ApplicationStatusCodes.PRE_REJECTION,
        ApplicationStatusCodes.APPLICATION_RESUBMITTED,
        ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
        ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING,
    ):
        button_text = 'Mohon tunggu dan kembali dalam 1 hari kerja'
    elif app_status in (
        ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
        ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
    ):
        button_text = 'Mohon tunggu telepon dari JULO'
    elif app_status == ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL:
        button_text = 'Surat Perjanjian'
    elif app_status in (
        ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED,
        ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED,
    ):
        button_text = 'Silahkan pelajari penggunaan produk di aktivitas pinjaman non-tunai'
    elif app_status == ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED_AND_DP_PENDING:
        button_text = 'Lakukan pembayaran DP Anda'
    elif app_status == ApplicationStatusCodes.DOWN_PAYMENT_PAID:
        button_text = 'Silakan unggah kwitansi/bukti transfer di halaman Aktivitas Pinjaman'
    elif app_status == ApplicationStatusCodes.LOC_APPROVED:
        button_text = 'Ajukan Pinjaman Baru'

    # button url
    if app_status == ApplicationStatusCodes.FORM_PARTIAL:
        button_url = 'http://www.julofinance.com/android/goto/product'
    elif app_status in (
        ApplicationStatusCodes.FORM_SUBMITTED,
        ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
    ):
        button_url = 'http://www.julofinance.com/android/goto/appl_docs'
    elif app_status in (
        ApplicationStatusCodes.FORM_SUBMISSION_ABANDONED,
        ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED,
        ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
        ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
        ApplicationStatusCodes.OFFER_DECLINED_BY_CUSTOMER,
        ApplicationStatusCodes.LEGAL_AGREEMENT_EXPIRED,
        ApplicationStatusCodes.DOWN_PAYMENT_EXPIRED,
    ):
        button_url = 'http://www.julofinance.com/android/goto/reapply'
    elif app_status == ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL:
        button_url = 'http://www.julofinance.com/android/goto/agreement'
    elif app_status == ApplicationStatusCodes.LOC_APPROVED:
        button_url = 'http://www.julofinance.com/android/goto/reapply'

    return button_text, button_url


def render_deals_card():
    msg = render_to_string('deals.txt', None)
    card = construct_card(
        msg,
        'PROMO',
        None,
        None,
        'https://www.julofinance.com/images/newsfeed/banner_deal.jpg',
        None,
    )
    return card


def render_bonus_card(customer):
    data = {'referral_code': customer.self_referral_code}
    msg = render_to_string('bonus.txt', data)
    card = construct_card(
        msg,
        'REFERRAL BONUS',
        None,
        None,
        'https://www.julofinance.com/images/newsfeed/banner_referral_bonus.jpg',
        None,
    )
    return card


def render_default_card():
    msg = render_to_string('default.txt', None)
    card = construct_card(
        msg,
        'WELCOME',
        None,
        'http://www.julofinance.com/android/goto/appl_forms',
        None,
        'Formulir Pengajuan',
    )
    return card


def render_bfi_oct_promo_card():
    msg = render_to_string('promo_bfi_oct_2018.txt')
    card = construct_card(
        msg,
        'Promo BFI',
        None,
        None,
        'https://www.julo.co.id/apps_banner/banner_promo_bfi_oct_2018.jpg',
        None,
    )
    return card


# hide Julo Mini to remove STL product from APP for google rules
# def render_julomini_card():
#     msg = render_to_string('julomini.txt')
#     card = construct_card(
#         msg, 'JULO MINI | Rp 1.000.000 - 1 bulan', None, None, None, None,
#         None) # 2 is new button style, left and appear as link.
#     return card


def render_season_card():
    now = date.today()
    if date(2017, 5, 26) <= now <= date(2017, 6, 18):
        msg = render_to_string('ramadhan.txt')
        card = construct_card(
            msg,
            'Ramadhan',
            None,
            None,
            'https://www.julofinance.com/images/newsfeed/ramadan.jpg',
            None,
        )
        return card
    elif date(2017, 6, 19) <= now <= date(2017, 7, 3):
        msg = render_to_string('eid.txt')
        card = construct_card(
            msg,
            'Eid Mubarak',
            None,
            None,
            'https://www.julofinance.com/images/newsfeed/eid.jpg',
            None,
        )
        return card
    return None


def render_sphp_card(customer, application=None):
    if application is None or not isinstance(application, Application):
        return None

    if application.application_status_id != ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL:
        return None
    if application.loan.status == LoanStatusCodes.PAID_OFF:
        return None
    msg = render_to_string('sphp.txt')
    card = construct_card(
        msg,
        'Surat Perjanjian Hutang Piutang (SPHP)',
        None,
        'http://www.julofinance.com/android/goto/agreement',
        None,
        'Lihat Surat Perjanjian',
    )
    return card


def render_campaign_card(customer, application_id):
    now = date.today()
    application = Application.objects.get_or_none(customer=customer, id=application_id)
    if (
        application is not None
        and application.partner is None
        and date(2018, 5, 15) <= now <= date(2018, 6, 8)
    ):
        if application is None:
            return None
        if (
            application.application_status.status_code
            != ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
        ):
            return None
        if application.loan.status == LoanStatusCodes.PAID_OFF:
            return None
        loan = Loan.objects.get_or_none(application_id=application_id)
        payment = loan.payment_set.filter(paymentevent__event_type='lebaran_promo').first()
        if payment and payment.payment_status_id < PaymentStatusCodes.PAID_ON_TIME:
            msg = render_to_string('promo_lebaran_2018.txt')
            card = construct_card(
                msg,
                'Ramadhan Penuh Berkah!',
                None,
                None,
                'https://www.julofinance.com/images/lebaran.jpg',
                None,
                None,
            )  # 2 is new button style, left and appear as link.
            return card
        return None
    elif date(2018, 5, 7) <= now <= date(2018, 6, 30):
        tokopedia_campaign_status_code = [
            ApplicationStatusCodes.FORM_PARTIAL,
            ApplicationStatusCodes.FORM_SUBMITTED,
            ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
            ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
            ApplicationStatusCodes.DOCUMENTS_VERIFIED,
            ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL,
            ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
            ApplicationStatusCodes.APPLICATION_RESUBMITTED,
            ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
            ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING,
            ApplicationStatusCodes.OFFER_MADE_TO_CUSTOMER,
            ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
            ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
            ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED,
            ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
        ]
        if application is None:
            return None
        if application.partner is None:
            return None
        if (
            application.partner.name == 'tokopedia'
            and application.application_status_id in tokopedia_campaign_status_code
        ):
            msg = render_to_string('tokopedia.txt')
            card = construct_card(
                msg,
                'KEJUTAN BUNGA 0%*',
                None,
                None,
                'https://www.julofinance.com/images/tokopedia.jpeg',
                None,
            )
            return card
        return None
    return None


def render_loan_sell_off_card(loan):
    card = None
    loan_selloff = LoanSelloff.objects.get(loan=loan)
    if loan_selloff:
        sell_off_batch = loan_selloff.loan_selloff_batch
        if sell_off_batch:
            ctx = {'vendor': sell_off_batch.vendor}
            msg = render_to_string('loan_selloff.txt', ctx)
            card = construct_card(msg, 'INFORMASI PINJAMAN', None, None, None, None)
    return card


def generate_dropdown_zip(request, product_line_code):
    """
    Generate file dropdown in memory
    And sent file to response, and set invalidate per-day.
    """

    @cached(timeout=60 * 60 * 24, extra=request.GET)
    def _generate_dropdown_zip():
        in_memory = io.BytesIO()
        zip_file = ZipFile(in_memory, "a", ZIP_DEFLATED)
        write_dropdowns_to_buffer(zip_file, request.GET, int(product_line_code))

        # close the file
        zip_file.close()
        file_size = in_memory.tell()
        return in_memory, file_size

    def _generate_dropdown_for_jobs():
        in_memory = io.BytesIO()
        zip_file = ZipFile(in_memory, "a", ZIP_DEFLATED)
        write_dropdowns_to_buffer(zip_file, request.GET, int(product_line_code))

        # close the file
        zip_file.close()
        file_size = in_memory.tell()
        return in_memory, file_size

    in_memory, file_size = _generate_dropdown_zip()

    # check if not empty
    if file_size > 22:
        return in_memory, file_size

    # get for dropdown jobs only
    return _generate_dropdown_for_jobs()


def is_allowed_to_upload_photo(data):
    """
    This function only check based on Application ID
    To restrict user when upload files in certain status:
    - selfie
    - KTP
    """

    image_source = data.get('image_source', None)
    image_type = data.get('image_type', None)

    setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.VALIDATION_IMAGE_UPLOAD_STATUS,
    ).last()

    if not setting or not setting.is_active:
        return True

    if not image_source or not image_type:
        return True

    allow_app_status = setting.parameters.get(ListImageTypes.KEY_PARAMETER_CONFIG)
    application_id = int(image_source)
    application = Application.objects.filter(pk=application_id).last()
    if not application:
        return True

    if (
        not application.is_julo_one()
        and not application.is_julo_one_ios()
        and not application.is_julo_starter()
    ):
        return True

    # skip if application have partner
    if application.partner_id:
        return True

    application_status_code = application.application_status_id

    if application_status_code in allow_app_status:
        return True

    if (
        application_status_code >= ApplicationStatusCodes.FORM_PARTIAL
        and image_type.lower() in ListImageTypes.IMAGE_TYPES
    ):
        logger.warning(
            {
                'message': '[not_allowed] upload with image_type: {}'.format(image_type),
                'application_id': application.id,
                'application_status_code': application_status_code,
                'allow_app_status': allow_app_status,
            }
        )
        return False

    return True
