from __future__ import division
from builtins import str
from builtins import range
from past.utils import old_div
import json
import logging
import requests
import datetime
import io

from babel.dates import format_date
from pyexcel_xls import get_data as get_data_xls
from pyexcel_io import get_data as get_data_csv
from django.db.utils import IntegrityError
from django.utils import timezone
from dateutil.relativedelta import relativedelta
from django.template.loader import render_to_string

from juloserver.apiv2.credit_matrix2 import credit_score_rules2, messages
from juloserver.apiv2.credit_matrix2 import messages as cm2_messages

from juloserver.julocore.python2.utils import py2round

from juloserver.julo.formulas import determine_first_due_dates_by_payday
from juloserver.julo.formulas import compute_laku6_adjusted_payment_installment
from juloserver.julo.formulas import compute_laku6_payment_installment
from juloserver.julo.formulas import compute_adjusted_payment_installment
from juloserver.julo.formulas import compute_payment_installment
from juloserver.julo.formulas.offers import get_offer_options

from juloserver.julo.models import Application
from juloserver.julo.models import CreditScore
from juloserver.apiv2.models import AutoDataCheck
from juloserver.apiv2.models import PdPartnerModelResult
from juloserver.julo.models import SphpTemplate
from juloserver.julo.models import Offer
from juloserver.julo.models import Loan
from juloserver.julo.models import ProductLine
from juloserver.julo.models import ProductLookup
from juloserver.julo.models import PartnerPurchaseItem
from juloserver.julo.models import Document
from juloserver.julo.models import Device
from juloserver.julo.exceptions import JuloException

from juloserver.sdk.serializers import CreditScoreSerializer
from juloserver.sdk.serializers import ProductLineSerializer

from juloserver.julo.services2 import get_appsflyer_service
from juloserver.julo.constants import ScoreTag
from juloserver.julo.product_lines import ProductLineCodes, ProductLineManager
from juloserver.julo.statuses import LoanStatusCodes, PaymentStatusCodes
from juloserver.julo.constants import SPHPConst
from juloserver.julo.constants import MAX_LATE_FEE_RATE
from juloserver.julo.constants import NotPremiumAreaConst
from juloserver.julo.constants import JuloSTLMicro
from juloserver.apiv2.constants import CreditMatrixV19
from juloserver.sdk.constants import (
    CreditMatrixPartner,
    ProductMatrixPartner,
    CALLBACK_LAKU6,
    CALLBACK_URL_PEDE,
    TOKEN_LAKU6,
    LIST_PARTNER,
    JuloPEDEMicro
)
from juloserver.julo.utils import display_rupiah
from juloserver.julo.formulas.experiment import calculation_affordability
from juloserver.julo.formulas import round_rupiah
from juloserver.julo.partners import PartnerConstant
from juloserver.julo.statuses import ApplicationStatusCodes
from django.template import Context, Template
from juloserver.sdk.constants import partner_messages
from django.conf import settings
from juloserver.julo.clients import get_julo_digisign_client
from juloserver.julo.clients.constants import DigisignResultCode
from juloserver.sdk.models import AxiataCustomerData
from math import ceil

logger = logging.getLogger(__name__)


def get_sphp_payment(offer):
    # generate data payments
    payments = list()
    for payment_number in range(offer.loan_duration_offer):
        if payment_number == 0:
            installment = offer.first_installment_amount
            due_date = offer.first_payment_date
        else:
            installment = offer.installment_amount_offer
            due_date = offer.first_payment_date + relativedelta(months=payment_number)

        payment = dict(
            payment_number=payment_number + 1,
            due_date=due_date,
            due_amount=display_rupiah(installment),
            )

        payment_text = ("<tr>"
                        "<td>"
                        "<div class='hideExtra'>{payment_number}</div>"
                        "</td>"
                        "<td>"
                        "<div class='hideExtra'>{due_amount}</div>"
                        "</td>"
                        "<td>"
                        "<div class='hideExtra'>{due_date}</div>"
                        "</td>"
                        "</tr>".format(**payment))
        payments.append(payment_text)

    return "\n".join(payments)


def get_sphp_payment_obj(offer):
    # generate data payments
    payments = list()
    for payment_number in range(offer.loan_duration_offer):
        if payment_number == 0:
            installment = offer.first_installment_amount
            due_date = offer.first_payment_date
        else:
            installment = offer.installment_amount_offer
            due_date = offer.first_payment_date + relativedelta(months=payment_number)

        payment = dict(
            payment_number=payment_number + 1,
            due_date=due_date,
            due_amount=display_rupiah(installment),
            )
        payments.append(payment)

    return payments


def clean_html_string(data):
    try:
        return data.replace("\n", "").replace('\"', "").replace('\r', "").replace('\t', "")
    except Exception as e:
        return data


def get_partner_product_sphp(application_id, customer):
    application = Application.objects.filter(pk=application_id, customer=customer).first()
    offer = Offer.objects.filter(application=application).last()
    text_sphp = ''

    context = {
        'date_today': '',
        'application': application,
        'dob': format_date(application.dob, 'dd-MM-yyyy', locale='id_ID'),
        'full_address': application.complete_addresses,
    }

    other_context = {
        'loan_amount': display_rupiah(offer.loan_amount_offer),
        'max_total_late_fee_amount': display_rupiah(offer.max_total_late_fee_amount),
        'late_fee_amount': '',
        'doku_flag': False,
        'doku_account': '',
        'julo_bank_name': "JULO Finance",
        'julo_bank_code': '',
        'julo_bank_account_number': "",
        'provision_fee_amount': display_rupiah(offer.provision_fee),
        'interest_rate': '{}%'.format(offer.interest_percent_monthly),
        'lender_agreement_number': SPHPConst.AGREEMENT_NUMBER,
    }

    # set date_today
    now = datetime.datetime.now()
    date_today = now.strftime("%Y-%m-%d")
    context['date_today'] = date_today

    context = dict(list(context.items()) + list(other_context.items()))
    sphp_name = application.product_line.product_line_type
    text = SphpTemplate.objects.get(product_name=sphp_name)

    # render template by product_line
    if application.product_line.product_line_code in ProductLineCodes.pedemtl():
        payments = get_sphp_payment_obj(offer)
        context['payments'] = payments
    elif application.product_line.product_line_code in ProductLineCodes.pedestl():
        context['installment_amount'] = display_rupiah(offer.installment_amount_offer)
        context['min_due_date'] = format_date(offer.first_payment_date, 'd MMMM yyyy', locale='id_ID')
        context['first_late_fee_amount'] = display_rupiah(50000)

    template = Template(text.sphp_template)
    res = template.render(Context(context))
    return clean_html_string(res)


def get_laku6_sphp(application_id, customer):
    application_object = Application.objects.filter(pk=application_id, customer=customer).first()
    offer = Offer.objects.filter(application=application_object).last()
    purchased = PartnerPurchaseItem.objects.filter(partner=application_object.partner,
                                                   application_xid=application_object.application_xid).first()
    text = SphpTemplate.objects.filter(product_name=application_object.partner.name).get()
    now = datetime.datetime.now()
    date_today = now.strftime("%Y-%m-%d")

    origination_fee = offer.loan_amount_offer * offer.product.origination_fee_pct

    late_fee_amount = offer.product.late_fee_pct * offer.installment_amount_offer
    late_fee_amount = py2round(late_fee_amount if late_fee_amount > 55000 else 55000, -2)

    payments = get_sphp_payment(offer)
    data = dict()

    data['date_today'] = date_today
    data['full_address'] = application_object.complete_addresses
    data['julo_bank_name'] = "JULO Finance"
    data['julo_bank_code'] = ""
    data['julo_bank_account_number'] = ""
    data['dob'] = application_object.dob
    data['ktp'] = application_object.ktp
    data['mobile_phone_1'] = application_object.mobile_phone_1
    data['fullname'] = application_object.fullname
    data['application_xid'] = application_object.application_xid

    data['loan_amount'] = display_rupiah(offer.loan_amount_offer)
    data['installment_amount'] = offer.installment_amount_offer
    data['lender_agreement_number'] = SPHPConst.AGREEMENT_NUMBER
    data['late_fee_amount'] = display_rupiah(late_fee_amount)
    data['max_total_late_fee_amount'] = display_rupiah(offer.loan_amount_offer * MAX_LATE_FEE_RATE)
    data['provision_fee_amount'] = display_rupiah(origination_fee)
    data['payment_13_due_date'] = offer.first_payment_date + relativedelta(months=offer.loan_duration_offer)
    data['interest_rate'] = '{}%'.format(float(offer.interest_rate_monthly * 100))
    data['last_installment_amount'] = display_rupiah(offer.last_installment_amount)
    data['payments'] = payments

    data['device_name'] = purchased.device_name
    data['device_price'] = display_rupiah(purchased.device_price if purchased.device_price else 0)
    data['package_price'] = display_rupiah(purchased.package_price if purchased.package_price else 0)
    data['insurance_price'] = display_rupiah(purchased.insurance_price if purchased.insurance_price else 0)
    data['admin_fee'] = display_rupiah(purchased.admin_fee if purchased.admin_fee else 0)
    data['down_payment_amount'] = display_rupiah(purchased.down_payment if purchased.down_payment else 0)
    data['imei_code_laku6'] = purchased.imei_number

    return clean_html_string(text.sphp_template.format(**data))


def get_laku6_sphp_temp(application_id, customer):
    application_object = Application.objects.filter(pk=application_id, customer=customer).first()
    offer = Offer.objects.filter(application=application_object).last()
    purchased = PartnerPurchaseItem.objects.filter(partner=application_object.partner,
                                                   application_xid=application_object.application_xid).first()
    text = SphpTemplate.objects.filter(product_name=application_object.partner.name).get()
    now = datetime.datetime.now()
    date_today = now.strftime("%Y-%m-%d")

    origination_fee = offer.loan_amount_offer * offer.product.origination_fee_pct

    late_fee_amount = offer.product.late_fee_pct * offer.installment_amount_offer
    late_fee_amount = py2round(late_fee_amount if late_fee_amount > 55000 else 55000, -2)

    payments = list()
    for payment_number in range(offer.loan_duration_offer):
        if payment_number == 0:
            installment = offer.first_installment_amount
            due_date = offer.first_payment_date
        else:
            installment = offer.installment_amount_offer
            due_date = offer.first_payment_date + relativedelta(months=payment_number)

        payment = dict(
            payment_number=payment_number + 1,
            due_date=due_date,
            due_amount=display_rupiah(installment),
        )

        payment_text = ("<tr>"
                        "<td>"
                        "<div class='hideExtra'>{payment_number}</div>"
                        "</td>"
                        "<td>"
                        "<div class='hideExtra'>{due_amount}</div>"
                        "</td>"
                        "<td>"
                        "<div class='hideExtra'>{due_date}</div>"
                        "</td>"
                        "</tr>".format(**payment))
        payments.append(payment_text)

    payments_text = "\n".join(payments)
    data = dict()

    data['date_today'] = date_today
    data['full_address'] = application_object.complete_addresses
    data['julo_bank_name'] = "JULO Finance"
    data['julo_bank_code'] = ""
    data['julo_bank_account_number'] = ""
    data['dob'] = application_object.dob
    data['ktp'] = application_object.ktp
    data['mobile_phone_1'] = application_object.mobile_phone_1
    data['fullname'] = application_object.fullname
    data['application_xid'] = application_object.application_xid

    data['loan_amount'] = display_rupiah(offer.loan_amount_offer)
    data['installment_amount'] = offer.installment_amount_offer
    data['lender_agreement_number'] = SPHPConst.AGREEMENT_NUMBER
    data['late_fee_amount'] = display_rupiah(late_fee_amount)
    data['max_total_late_fee_amount'] = display_rupiah(offer.loan_amount_offer * MAX_LATE_FEE_RATE)
    data['provision_fee_amount'] = display_rupiah(origination_fee)
    data['payment_13_due_date'] = offer.first_payment_date + relativedelta(months=offer.loan_duration_offer)
    data['interest_rate'] = '{}%'.format(float(offer.interest_rate_monthly * 100))
    data['last_installment_amount'] = display_rupiah(offer.last_installment_amount)
    data['payments'] = payments

    data['device_name'] = purchased.device_name
    data['device_price'] = display_rupiah(purchased.device_price if purchased.device_price else 0)
    data['package_price'] = display_rupiah(purchased.package_price if purchased.package_price else 0)
    data['insurance_price'] = display_rupiah(purchased.insurance_price if purchased.insurance_price else 0)
    data['admin_fee'] = display_rupiah(purchased.admin_fee if purchased.admin_fee else 0)
    data['down_payment_amount'] = display_rupiah(purchased.down_payment if purchased.down_payment else 0)
    data['imei_code_laku6'] = purchased.imei_number

    return text.sphp_template.format(**data)

def get_credit_score_partner(application_id):
    credit_score = CreditScore.objects.get_or_none(application_id=application_id)
    if credit_score:
        # try to generate credit_limit when its get 0
        if credit_score.credit_limit == 0:
            application = Application.objects.get_or_none(pk=application_id)
            credit_limit = get_partner_credit_limit(application, credit_score.score)
            credit_score.credit_limit = credit_limit
            credit_score.save()

        return credit_score

    credit_model_result = PdPartnerModelResult.objects.filter(application_id=application_id).last()
    if not credit_model_result:
        return None

    application = Application.objects.get(id=application_id)
    partner_name = str(application.partner_name)
    rules = credit_score_rules2[partner_name]
    bypass_checks = rules['bypass_checks']
    if is_customer_has_good_payment_histories(application.customer):
        bypass_check_for_good_customer = ['fraud_form_partial_device', 'fraud_device']
        bypass_checks = set(bypass_checks + bypass_check_for_good_customer)
    failed_checks = AutoDataCheck.objects.filter(application_id=application_id, is_okay=False)
    failed_checks = failed_checks.exclude(data_to_check__in=bypass_checks)
    failed_checks = failed_checks.values_list('data_to_check', flat=True)

    check_order = CreditMatrixPartner.BINARY_CHECK_SHORT + CreditMatrixPartner.BINARY_CHECK_LONG

    first_failed_check = None
    score_tag = None
    for check in check_order:
        if check in failed_checks:
            if not first_failed_check:
                first_failed_check = check
                break

    if first_failed_check:
        message = first_failed_check
        product_list = []
        score = 'C'
        score_tag = ScoreTag.C_FAILED_BINARY
    else:
        score, product_list, message = get_partner_score(credit_model_result.pgood,
                                                         application.partner)
        if score == 'C':
            score_tag = ScoreTag.C_LOW_CREDIT_SCORE
            product_list = []

    if score in ['A-', 'B+'] and 2000000 <= application.monthly_income < 3000000:
        score = 'B-'
        message = cm2_messages['B_minus_score']

    # get inside premium area
    inside_premium_area = AutoDataCheck.objects.filter(application_id=application_id,
                                                       data_to_check='inside_premium_area').last()
    if inside_premium_area is None:
        inside_premium_area = True
    else:
        inside_premium_area = inside_premium_area.is_okay

    credit_limit = get_partner_credit_limit(application, score)
    if not credit_limit and PartnerConstant.LAKU6_PARTNER:
        score = 'C'
        score_tag = ScoreTag.C_LOW_CREDIT_SCORE
        product_list = []

    try:
        # appsflyer_service = get_appsflyer_service()
        # appsflyer_service.info_eligible_product(application, product_list)
        return CreditScore.objects.create(application_id=application_id,
                                          score=score,
                                          products_str=json.dumps(product_list),
                                          message=message,
                                          inside_premium_area=inside_premium_area,
                                          score_tag=score_tag,
                                          credit_limit=credit_limit,
                                          failed_checks=list(failed_checks))
    except IntegrityError:
        return CreditScore.objects.get(application_id=application_id)


def is_customer_has_good_payment_histories(customer, is_for_julo_one=False):
    apps = customer.application_set.filter(loan__loan_status=LoanStatusCodes.PAID_OFF)
    if is_for_julo_one and not apps:
        return True

    result = False
    for app in apps:
        payments = app.loan.payment_set.all()
        all_statuses = list([x.payment_status.status_code for x in payments])
        result = not any(status == PaymentStatusCodes.PAID_LATE for status in all_statuses)
    return result


def get_partner_score(probability, partner):
    partner_name = str(partner.name)
    if partner_name in [PartnerConstant.LAKU6_PARTNER]:
        product_line = ProductLineCodes.laku6()
    elif partner_name in [PartnerConstant.PEDE_PARTNER]:
        product_line = ProductLineCodes.pede()
    else:
        product_line = []

    if probability >= CreditMatrixPartner.A_MINUS_THRESHOLD:
        return 'A-', product_line, messages['A_minus_score']
    if probability >= CreditMatrixPartner.B_PLUS_THRESHOLD:
        return 'B+', product_line, messages['B_plus_score']
    if probability >= CreditMatrixPartner.B_MINUS_THRESHOLD:
        return 'B-', product_line, messages['B_minus_score']

    return 'C', [], messages['not_meet_criteria']


def get_partner_productline(application, partner, product_code=None):
    product_line = ProductLine.objects.all()
    loan = Loan.objects.filter(customer=application.customer).paid_off().first()

    if partner:
        partner_name = str(partner.name)
        if partner_name == PartnerConstant.PEDE_PARTNER:
            product_line_codes = ProductLineCodes.pede()
        if partner_name == PartnerConstant.LAKU6_PARTNER:
            product_line_codes = ProductLineCodes.laku6()
        if partner_name == 'icare':
            product_line_codes = ProductLineCodes.icare()
        if partner_name == 'axiata':
            product_line_codes = ProductLineCodes.axiata()

        product_line = ProductLine.objects.filter(product_line_code__in=product_line_codes)

    product_line_list = product_line.repeat_lines() if loan else product_line.first_time_lines()
    if product_code:
        product_line_list = product_line_list.filter(product_line_code=product_code)
    return product_line_list


def get_partner_credit_limit(application, score):
    input_params = {
        'application_id': application.id,
        'monthly_income': application.monthly_income,
        'monthly_housing_cost': application.monthly_housing_cost,
        'monthly_expenses': application.monthly_expenses,
        'total_current_debt': application.total_current_debt
    }

    affordability, income_modified = calculation_affordability(**input_params)

    packages = ['SILVER', 'GOLD', 'PLATINUM', 'DIAMOND']
    new_affordability = affordability * 0.5
    interest = 0.08 + CreditMatrixPartner.INTEREST_BY_SCORE[score]
    residual = 0.45 / 12
    denominator = interest - residual
    limit_list = []

    for package in packages:
        post_paid = (ProductMatrixPartner.ERAFONE_FEE + ProductMatrixPartner.POST_PAID[package] - ProductMatrixPartner.DOWNPAYMENT[package])
        nominator = new_affordability - (post_paid * interest)

        device_price = round_rupiah(old_div(nominator, denominator))
        limit_list.append(device_price)

    credit_limit = min(limit_list)

    if score == 'A-' and credit_limit > 10000000:
        credit_limit = 10000000

    if score == 'B+' and credit_limit > 9000000:
        credit_limit = 9000000

    if score == 'B-' and credit_limit > 8000000:
        credit_limit = 8000000

    if score == 'C':
        credit_limit = 0

    return credit_limit if credit_limit > 0 else 0


def get_partner_offer(application, package=None):
    input_params = {
        'application_id': application.id,
        'monthly_income': application.monthly_income,
        'monthly_housing_cost': application.monthly_housing_cost,
        'monthly_expenses': application.monthly_expenses,
        'total_current_debt': application.total_current_debt
    }
    recomendation_offers = None

    affordability, income_modified = calculation_affordability(**input_params)

    if str(application.partner.name) == PartnerConstant.PEDE_PARTNER:
        # proper loan principal need to be provided
        recomendation_offers = get_pede_offer_recommendations(
            application.product_line.product_line_code,
            application.loan_amount_request,
            application.loan_duration_request,
            affordability,
            application.payday,
            application.id)
    else:
        loan_principal = ProductMatrixPartner.loan_principal(
            application.loan_amount_request, package)
        recomendation_offers = get_laku6_offer_recommendations(
            application.product_line.product_line_code,
            application.loan_amount_request,
            loan_principal,
            application.loan_duration_request,
            affordability * 0.5,
            application.payday,
            application.id)

    offer_data = None
    if recomendation_offers:
        if recomendation_offers['requested_offer'] and recomendation_offers['requested_offer']['can_afford'] is True:
            offer_data = recomendation_offers['requested_offer']
            offer_data.pop('can_afford')
        elif len(recomendation_offers['offers']) > 0:
            offer_data = recomendation_offers['offers'][0]

        if offer_data is not None:
            product = ProductLookup.objects.get(pk=offer_data['product'])
            offer_data['application'] = application
            offer_data['offer_number'] = 1
            offer_data['is_approved'] = True
            offer_data['is_accepted'] = False
            offer_data['product'] = product

    return offer_data


def post_partner(url, partner_token, partner_name, data=None):
    if partner_name == PartnerConstant.PEDE_PARTNER:
        headers = {'Content-Type': 'application/json'}
    else:
        headers = {'x-api-key': '%s' % partner_token, 'Content-Type': 'application/json'}

    url = url
    logger.info({
        'action': "post call to %s" % (partner_name,),
        'url': url,
        'data': data})
    response = requests.post(url, data=data, headers=headers)
    if response.status_code not in [200, 201]:
        err_msg = "POST to {} url {} fails: {}, {}".format(
            partner_name, url, response.status_code, response.text)

        logger.error(err_msg)


def send_partner_notify(application, credit_score):
    response = dict()
    if credit_score:
        response['application_xid'] = application.application_xid
        response['score'] = CreditScoreSerializer(credit_score).data
        partner_name = str(application.partner_name)
        if partner_name == PartnerConstant.LAKU6_PARTNER:
            TOKEN = TOKEN_LAKU6
            URL = CALLBACK_LAKU6
            post_partner(
                url=URL,
                data=json.dumps(response),
                partner_token=TOKEN,
                partner_name=partner_name)
        elif partner_name == PartnerConstant.PEDE_PARTNER:
            device_id = application.device.id
            gcm_reg_id = Device.objects.filter(id=device_id).values('gcm_reg_id')
            url_callback = CALLBACK_URL_PEDE
            response['body_message'] = ("Selamat pinjaman yang kamu ajukan disetujui, "
                                        "konfirmasi sekarang untuk cairkan pinjaman Anda.")

            if application.status == ApplicationStatusCodes.APPLICATION_DENIED:
                response['body_message'] = ("Anda belum dapat mengajukan pinjaman, "
                                            "karena belum memenuhi kriteria pinjaman yang ada.")

            if application.status == ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL:
                response['body_message'] = "Selamat dana pinjaman kamu sedang dalam proses pencairan ke rekening kamu."

            response['score'].pop('credit_limit')
            data = {
                "type": "Notification",
                "to": gcm_reg_id[0]['gcm_reg_id'],
                "priority": "high",
                "content_available": True,
                "data": {
                    "status": "success",
                    "code": 200,
                    "messageType": "julo_notification",
                    "body_message": response['body_message'],
                },
            }
            post_partner(
                url=url_callback,
                data=json.dumps(data),
                partner_token=None,
                partner_name=partner_name)


def make_json_from_data(column_names, row_data):
    """
    take column names and row info and merge into a single json object.
    :param column_names:
    :param row_data:
    :return:
    """
    row_list = []
    for item in row_data:
        json_obj = {}
        for i in range(0, column_names.__len__()):
            column_names[i] = column_names[i].lower()
            try:
                if column_names[i] != '':
                    word = str(item[i])
                    if word[:1] == "'":
                        word = word.replace("'", "")
                    if word != '':
                        json_obj[column_names[i]] = word
            except:
                pass
        row_list.append(json_obj)
    return row_list


def xls_to_dict(file_excel, delimiter=","):
    """
    Convert the read xls file into JSON.
    :param file_excel: Fully Qualified URL of the xls file to be read.
    :param delimiter: what separator that csv file used.
    :return: json representation of the workbook.
    """
    workbook_dict = {}
    try:
        sheets = get_data_xls(file_excel)
    except:
        file_excel.seek(0)
        file_io = io.StringIO(file_excel.read().decode())
        sheets = get_data_csv(file_io, delimiter=delimiter)

    for sheet in sheets:
        datas = sheets.get(sheet, None)
        if datas:
            columns = datas[0]
            nrows = len(datas)
            rows = []
            for row_index in range(1, nrows):
                row = datas[row_index]
                rows.append(row)
            sheet_data = make_json_from_data(columns, rows)
            workbook_dict[sheet] = sheet_data

    return workbook_dict


def get_laku6_offer_recommendations(
        product_line_code, loan_amount_requested, loan_principal, loan_duration_requested, affordable_payment,
        payday, application_id):
    output = dict()
    today = timezone.localtime(timezone.now()).date()
    application = Application.objects.get_or_none(pk=application_id)

    # Calculate requested option, using highest interest rate product lookup

    product_line = ProductLineManager.get_or_none(product_line_code)
    rate = product_line.max_interest_rate

    if product_line.product_line_code in ProductLineCodes.laku6():
        credit_score = get_credit_score_partner(application.id)
        if credit_score:
            rate = CreditMatrixPartner.INTEREST_BY_SCORE[credit_score.score]

    interest_rate = py2round(rate * 12, 2)
    product_lookup = ProductLookup.objects.filter(
        interest_rate=interest_rate, product_line__product_line_code=product_line.product_line_code).first()

    first_payment_date_requested = determine_first_due_dates_by_payday(
        payday, today, product_line_code, loan_duration_requested)

    _, _, first_installment_requested = compute_laku6_adjusted_payment_installment(
        loan_amount_requested, loan_principal, loan_duration_requested, product_lookup.monthly_interest_rate, today,
        first_payment_date_requested)

    _, _, installment_requested = compute_laku6_payment_installment(
        loan_amount_requested, loan_principal, loan_duration_requested, product_lookup.monthly_interest_rate)

    can_afford = installment_requested <= affordable_payment
    output['requested_offer'] = {
        'product': product_lookup.product_code,
        'loan_amount_offer': loan_principal,
        'loan_duration_offer': loan_duration_requested,
        'installment_amount_offer': installment_requested,
        'first_installment_amount': first_installment_requested,
        'last_installment_amount': float(loan_amount_requested) * 0.45,
        'first_payment_date': first_payment_date_requested,
        'can_afford': can_afford
    }

    # Return also product rate

    output['product_rate'] = {
        'annual_interest_rate': product_lookup.interest_rate,
        'late_fee_rate': product_lookup.late_fee_pct,
        'origination_fee_rate': product_lookup.origination_fee_pct,
        'cashback_initial_rate': product_lookup.cashback_initial_pct,
        'cashback_payment_rate': product_lookup.cashback_payment_pct,
        'monthly_interest_rate': product_lookup.monthly_interest_rate,
    }

    output['offers'] = []

    logger.info({
        'product_line_code': product_line_code,
        'loan_amount_requested': loan_amount_requested,
        'loan_duration_requested': loan_duration_requested,
        'affordable_payment': affordable_payment,
        'payday': payday,
        'can_afford': can_afford
    })

    return output


def get_bestfit_from_min_max(target_val, min_val, max_val):
    if target_val > max_val:
        target_val = max_val
    if target_val < min_val:
        target_val = min_val
    return target_val


def get_pede_offer_recommendations(
        product_line_code, loan_amount_requested, loan_duration_requested, affordable_payment,
        payday, application_id, partner=None):
    # this functionality is based on MTL and STL
    output = dict()
    today = timezone.localtime(timezone.now()).date()
    application = Application.objects.get_or_none(pk=application_id)
    credit_score = get_credit_score_partner(application.id)
    if not credit_score:
        return None
    # Calculate requested option, using highest interest rate product lookup

    product_line = ProductLineManager.get_or_none(product_line_code)
    rate = product_line.max_interest_rate

    if product_line.product_line_code in ProductLineCodes.pedemtl():
        rate = CreditMatrixPartner.PEDE_INTEREST_BY_SCORE[credit_score.score]
        max_loan_score = CreditMatrixPartner.MAX_LOAN_AMOUNT_BY_SCORE[credit_score.score]

        if loan_amount_requested > max_loan_score:
            loan_amount_requested = max_loan_score

        inside_premium_area = credit_score.inside_premium_area
        if not inside_premium_area:
            max_amount = NotPremiumAreaConst.MTL_MAX_AMOUNT

            if loan_amount_requested > max_amount:
                loan_amount_requested = max_amount

    elif product_line.product_line_code in ProductLineCodes.pedestl():
        if credit_score.score == 'B-':
            loan_amount_requested = JuloSTLMicro.MIN_AMOUNT
            # credit score v 22.3
            if credit_score.score_tag == CreditMatrixV19.B_MINUS_HIGH_TAG:
                loan_amount_requested = JuloSTLMicro.MAX_AMOUNT

    interest_rate = py2round(rate * 12, 2)
    product_lookup = ProductLookup.objects.filter(
        interest_rate=interest_rate,
        product_line__product_line_code=product_line.product_line_code).first()

    first_payment_date_requested = determine_first_due_dates_by_payday(
        payday, today, product_line_code, loan_duration_requested)

    _, _, first_installment_requested = compute_adjusted_payment_installment(
        loan_amount_requested, loan_duration_requested, product_lookup.monthly_interest_rate,
        today, first_payment_date_requested)

    if product_line_code in ProductLineCodes.pedestl(): # similar to stl product
        installment_requested = first_installment_requested
    else:
        _, _, installment_requested = compute_payment_installment(
            loan_amount_requested, loan_duration_requested, product_lookup.monthly_interest_rate)

    can_afford = installment_requested <= affordable_payment
    output['requested_offer'] = {
        'product': product_lookup.product_code,
        'loan_amount_offer': loan_amount_requested,
        'loan_duration_offer': loan_duration_requested,
        'installment_amount_offer': installment_requested,
        'first_installment_amount': first_installment_requested,
        'first_payment_date': first_payment_date_requested,
        'can_afford': can_afford
    }
    # Return also product rate

    output['product_rate'] = {
        'annual_interest_rate': product_lookup.interest_rate,
        'late_fee_rate': product_lookup.late_fee_pct,
        'origination_fee_rate': product_lookup.origination_fee_pct,
        'cashback_initial_rate': product_lookup.cashback_initial_pct,
        'cashback_payment_rate': product_lookup.cashback_payment_pct,
        'monthly_interest_rate': product_lookup.monthly_interest_rate,
    }
    # Give offer recommendations

    output['offers'] = []

    logger.info({
        'product_line_code': product_line_code,
        'loan_amount_requested': loan_amount_requested,
        'loan_duration_requested': loan_duration_requested,
        'affordable_payment': affordable_payment,
        'payday': payday,
        'can_afford': can_afford
    })
    loan_amount_requested = float(loan_amount_requested)
    loan_duration_requested = int(loan_duration_requested)
    max_loan_amount = float(product_line.max_amount)
    max_loan_duration = int(product_line.max_duration)
    min_loan_amount = float(product_line.min_amount)
    min_loan_duration = int(product_line.min_duration)

    if product_line.product_line_code in ProductLineCodes.pedestl():

        loan_amount_requested = get_bestfit_from_min_max(
            loan_amount_requested, min_loan_amount, max_loan_amount)
        loan_duration_requested = get_bestfit_from_min_max(
            loan_duration_requested, min_loan_duration, max_loan_duration)

        first_payment_date = determine_first_due_dates_by_payday(
                payday, today, product_line_code)
        _, _, first_installment = compute_adjusted_payment_installment(
            loan_amount_requested, loan_duration_requested,
            product_lookup.monthly_interest_rate,
            today, first_payment_date)
        output['offers'].append(
            {
                'product': product_lookup.product_code,
                'offer_number': 1,
                'loan_amount_offer': loan_amount_requested,
                'loan_duration_offer': loan_duration_requested,
                'installment_amount_offer': first_installment,
                'first_installment_amount': first_installment,
                'first_payment_date': first_payment_date,
                'is_accepted': False
            }
        )
        return output

    if product_line.product_line_code in ProductLineCodes.pedemtl():
        max_loan_amount = CreditMatrixPartner.CREDIT_LIMIT_BY_SCORE[credit_score.score]
        max_loan_duration = CreditMatrixPartner.MAX_LOAN_DURATION_BY_SCORE[credit_score.score]

        loan_amount_requested = get_bestfit_from_min_max(
            loan_amount_requested, min_loan_amount, max_loan_amount)
        loan_duration_requested = get_bestfit_from_min_max(
            loan_duration_requested, min_loan_duration, max_loan_duration)

        first_payment_date = determine_first_due_dates_by_payday(
                payday, today, product_line_code)
        _, _, first_installment = compute_adjusted_payment_installment(
            loan_amount_requested, loan_duration_requested,
            product_lookup.monthly_interest_rate,
            today, first_payment_date)
        _, _, installment = compute_payment_installment(
                loan_amount_requested,
                loan_duration_requested,
                product_lookup.monthly_interest_rate)

        output['offers'].append(
            {
                'product': product_lookup.product_code,
                'loan_amount_offer': loan_amount_requested,
                'loan_duration_offer': loan_duration_requested,
                'installment_amount_offer': installment,
                'first_installment_amount': first_installment,
                'first_payment_date': first_payment_date,
                'is_accepted': False
            }
        )
        return output


def get_application_status(app):
    status = 'application_process'
    if app.application_status.status_code >= ApplicationStatusCodes.DOCUMENTS_SUBMITTED:
        status = 'verification_process'
    if app.application_status.status_code >= ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER:
        status = 'offer_made'
    if app.application_status.status_code == ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL:
        status = 'agreement_sign_request'
    if app.application_status.status_code == ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED:
        status = 'agreement_signed'
    if app.application_status.status_code >= ApplicationStatusCodes.NAME_VALIDATE_ONGOING:
        status = 'disbursement_process'
    if app.application_status.status_code == ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL:
        status = 'disbursement_success'
    if app.application_status.status_code == ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED_AND_DP_PENDING:
        status = 'verification_process'

    if app.application_status.status_code in (ApplicationStatusCodes.FORM_SUBMISSION_ABANDONED,
                                                ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
                                                ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED,
                                                ApplicationStatusCodes.LEGAL_AGREEMENT_EXPIRED):
        status = 'application_expired'
    if app.application_status.status_code == ApplicationStatusCodes.APPLICATION_DENIED:
        status = 'application_rejected'
    if app.application_status.status_code == ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER:
        status = 'application_canceled'
    if app.application_status.status_code == ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED:
        status = 'application_expired'
    if app.application_status.status_code == ApplicationStatusCodes.OFFER_EXPIRED:
        status = 'offer_expired'

    if app.application_status.status_code in (
            ApplicationStatusCodes.NAME_VALIDATE_FAILED,
            ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING):
        status = 'verification_process'

    return status


def get_score_tag(score):
    try:
        scores_dict = {
            'A-': 'A_minus_score',
            'B-': 'B_minus_score',
            'B+': 'B_plus_score'
        }
        return scores_dict[score]
    except Exception:
        return None


def get_application_rejection_message(score, app):
    try:
        score_tag = get_score_tag(score)
        if score_tag:
            message = partner_messages[score_tag]
        else:
            rules = credit_score_rules2[app.partner_name]
            bypass_checks = rules['bypass_checks']
            if is_customer_has_good_payment_histories(app.customer):
                bypass_check_for_good_customer = ['fraud_form_partial_device', 'fraud_device']
                bypass_checks = set(bypass_checks + bypass_check_for_good_customer)
            failed_checks = AutoDataCheck.objects.filter(
                application_id=app.id, is_okay=False)
            failed_checks = failed_checks.exclude(data_to_check__in=bypass_checks)
            failed_checks = failed_checks.values_list('data_to_check', flat=True)
            check_order = CreditMatrixV19.BINARY_CHECK_SHORT + CreditMatrixV19.BINARY_CHECK_LONG
            first_failed_check = None
            for check in check_order:
                if check in failed_checks:
                    first_failed_check = check
                    break
            message = partner_messages[first_failed_check]
    except Exception as e:
        message =  None
    return message


def register_digisign_pede(application):

    from juloserver.julo.services import process_application_status_change

    try:
        url, status, reason, registration = None, None, None, False
        digisign_client = get_julo_digisign_client()
        user_status_response = digisign_client.user_status(application.email)
        user_status_response_json = user_status_response['JSONFile']

        if user_status_response_json['result'] == DigisignResultCode.DATA_NOT_FOUND:
            register_response = digisign_client.register(application.id)
            register_response_json = register_response['JSONFile']
            if register_response_json['result'] == DigisignResultCode.SUCCESS:
                registration = True

        elif user_status_response_json['result'] == DigisignResultCode.SUCCESS and \
                user_status_response_json['info'] in ['aktif', 'belum aktif']:
            registration = True

        if registration:
            reason = 'success'
            status = 'registration_success'
            url = "{}/api/sdk/v1/digisign_pede_webview/{}/".format(
                settings.BASE_URL, application.application_xid
            )
        else:
            status = 'registration_failed'
            reason = register_response_json['notif']
            process_application_status_change(
                application.id, ApplicationStatusCodes.APPLICATION_DENIED,
                "partner_digital_signature_failed", "digisign"
            )

    except Exception as e:
        logger.error({
            'action': 'digisign pede registration ',
            'application_id': application.id,
            'message': str(e)
        })

    return url, status, reason


def get_pede_product_lines(customer, application_id, line_ids=None):
    if line_ids is not None:
        queryset = ProductLine.objects.filter(product_line_code__in=line_ids)
    else:
        queryset = ProductLine.objects.filter(product_line_code__in=ProductLineCodes.pede())
    loan = Loan.objects.filter(customer=customer).paid_off().first()

    product_line_list = queryset.repeat_lines() if loan else queryset.first_time_lines()

    credit_score = get_credit_score_partner(application_id)
    application = Application.objects.get_or_none(pk=application_id)
    application.product_line = product_line_list.first()
    application.save()

    application.refresh_from_db()
    inside_premium_area = True
    if credit_score:
        inside_premium_area = credit_score.inside_premium_area

    offer_data = Offer.objects.filter(application=application).first().__dict__

    for product_line in product_line_list:
        product_line_manager_data = ProductLineManager.get_or_none(product_line.product_line_code)
        rate = product_line_manager_data.max_interest_rate

        product_line.min_amount = offer_data['loan_amount_offer']
        product_line.max_amount = offer_data['loan_amount_offer']
        product_line.min_duration = offer_data['loan_duration_offer']
        product_line.max_duration = offer_data['loan_duration_offer']

        if product_line.product_line_code in ProductLineCodes.pedemtl():
            max_loan_score = CreditMatrixPartner.MAX_LOAN_AMOUNT_BY_SCORE[credit_score.score]
            product_line.min_interest_rate = CreditMatrixPartner.PEDE_INTEREST_BY_SCORE[credit_score.score]
            product_line.max_interest_rate = CreditMatrixPartner.PEDE_INTEREST_BY_SCORE[credit_score.score]

            if product_line.max_duration > max_loan_score:
                product_line.max_amount = max_loan_score

            if not inside_premium_area:
                product_line.min_amount = NotPremiumAreaConst.MTL_MIN_AMOUNT
                if product_line.max_duration > NotPremiumAreaConst.MTL_MAX_AMOUNT:
                    product_line.max_amount = NotPremiumAreaConst.MTL_MAX_AMOUNT

        elif product_line.product_line_code in ProductLineCodes.pedestl():
            if credit_score.score == 'B-':
                product_line.min_amount = JuloSTLMicro.MIN_AMOUNT
                product_line.max_amount = JuloSTLMicro.MIN_AMOUNT
                # credit score v 22.3
                if credit_score.score_tag == CreditMatrixV19.B_MINUS_HIGH_TAG:
                    product_line.min_amount = JuloSTLMicro.MIN_AMOUNT
                    product_line.max_amount = JuloSTLMicro.MAX_AMOUNT

            product_line.min_interest_rate = rate
            product_line.max_interest_rate = rate

    return product_line_list


def update_axiata_offer(offer):
    application = offer.application
    axiata_customer_data = AxiataCustomerData.objects.filter(application=application).last()
    if not axiata_customer_data:
        logger.info({
            'action': 'update_axiata_offer',
            'error': 'axiata_customer_data not found'
        })
        raise JuloException('axiata_customer_data not found')
    installment_amount = axiata_customer_data.loan_amount + ceil(
        axiata_customer_data.loan_amount * axiata_customer_data.interest_rate / 100.0
    )
    first_installment_amount = installment_amount
    installment_amount_offer = installment_amount
    offer.update_safely(
        installment_amount_offer=int(installment_amount_offer),
        first_installment_amount=int(first_installment_amount)
    )
