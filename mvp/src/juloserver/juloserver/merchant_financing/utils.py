import decimal
import io
import os
import re
import os
import string
import base64
import requests
from math import ceil

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from past.utils import old_div
from urllib.parse import urlparse

from juloserver.julocore.python2.utils import py2round
from juloserver.julo.formulas import round_rupiah_merchant_financing
from juloserver.julo.statuses import (
    PaymentStatusCodes,
    LoanStatusCodes,
    JuloOneCodes,
)
from juloserver.julo.exceptions import JuloException
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.models import (
    FeatureSetting,
    ProductLookup,
    ProductLine,
    Payment,
    StatusLookup,
    Loan,
    PaymentMethod,
)
from juloserver.julo.constants import FeatureNameConst
from juloserver.merchant_financing.constants import (
    MF_STANDARD_PRODUCT_UPLOAD_MAPPING_FIELDS,
    PARTNER_MF_DISBURSEMENT_UPLOAD_MAPPING_FIELDS,
    PARTNER_MF_ADJUST_LIMIT_UPLOAD_MAPPING_FIELDS,
    MFStandardProductUploadDetails,
    AXIATA_FEE_RATE,
    PARTNER_MF_REGISTER_UPLOAD_MAPPING_FIELDS,
)
from juloserver.merchant_financing.web_app.constants import WebAppErrorMessage
from juloserver.partnership.constants import (
    PartnershipTypeConstant,
    UPLOAD_DOCUMENT_MAX_SIZE,
    PartnershipFeatureNameConst,
)
from juloserver.partnership.models import (
    PartnershipConfig,
    PartnershipFeatureSetting,
)
from juloserver.loan.models import LoanAdjustedRate
from juloserver.loan.services.adjusted_loan_matrix import get_daily_max_fee

from juloserver.followthemoney.models import LenderCurrent
from juloserver.minisquad.services2.google_drive import (
    get_partnership_google_drive_api_client,
    get_google_drive_file_id,
)
from juloserver.employee_financing.utils import verify_phone_number


def get_partner_product_line(interest_rate, origination_fee, admin_fee, product_line_code=None):
    if not product_line_code:
        product_line_codes = ProductLineCodes.axiata()
        product_line = ProductLine.objects.filter(product_line_code__in=product_line_codes)
        product_line_list = product_line.first_time_lines()
    else:
        product_line = ProductLine.objects.filter(product_line_code=product_line_code)
        product_line_list = list(product_line)

    interest_rate = old_div(decimal.Decimal('%s' % interest_rate), decimal.Decimal('100'))
    origination_fee_pct = old_div(decimal.Decimal('%s' % origination_fee), decimal.Decimal('100'))

    axiata_product_lookup = ProductLookup.objects.filter(
        product_line__in=product_line_list,
        interest_rate=interest_rate,
        origination_fee_pct=origination_fee_pct,
        late_fee_pct=AXIATA_FEE_RATE,
        admin_fee=admin_fee).first()

    if axiata_product_lookup:
        product_line = product_line.filter(
            product_line_code=axiata_product_lookup.product_line_id).first()
        return product_line, axiata_product_lookup

    return None, None


def is_loan_duration_valid(loan_duration, partner):
    # loan_duration is in days
    partnership_config = PartnershipConfig.objects.only('id', 'loan_duration').filter(
        partner=partner,
        partnership_type__partner_type_name=PartnershipTypeConstant.MERCHANT_FINANCING
    ).last()
    if not partnership_config:
        raise JuloException('Durasi pinjaman tidak tersedia')

    # available_duration is in days but stored in array
    available_duration = partnership_config.loan_duration
    if not available_duration or (len(available_duration) == 1 and available_duration[0] == 0):
        raise JuloException('Durasi pinjaman tidak tersedia')

    if loan_duration not in available_duration:
        return False
    return True


def compute_payment_installment_merchant_financing(loan_amount, loan_duration_days, monthly_interest_rate):
    """
    Computes installment and interest for payments after first installment
    """
    days_in_month = 30.0
    daily_interest_rate = float(monthly_interest_rate) / days_in_month
    principal = round_rupiah_merchant_financing(py2round(float(loan_amount) / loan_duration_days))
    installment_amount = int(round_rupiah_merchant_financing(
        (float(loan_amount) / loan_duration_days)))
    if daily_interest_rate > 0:
        installment_amount = int(
            round_rupiah_merchant_financing(
                (float(loan_amount) / loan_duration_days) + (old_div(daily_interest_rate, 100) *
                                                             float(loan_amount)))
        )

    installment_interest_amount = installment_amount - principal

    return principal, installment_interest_amount, installment_amount


def validate_merchant_financing_max_interest_with_ojk_rule(
        loan_requested, additional_loan_data, daily_max_fee_from_ojk):

    # interest_rate_monthly value already on decimal from table product lookup
    interest_rate_per_day = loan_requested['interest_rate_monthly'] / 30
    interest_rate_in_decimal = interest_rate_per_day * loan_requested['loan_duration_in_days']

    # origination_fee value already on decimal from table product lookup
    origination_fee_in_decimal = loan_requested['provision_fee']

    # get max fee base on ojk rule from feature setting
    max_fee_ojk = daily_max_fee_from_ojk * loan_requested['loan_duration_in_days']

    # simple fee its mean total fee from julo
    simple_fee = py2round(origination_fee_in_decimal + interest_rate_in_decimal, 3)

    if simple_fee > max_fee_ojk:
        provision_fee_rate = origination_fee_in_decimal
        if origination_fee_in_decimal > max_fee_ojk:
            provision_fee_rate = max_fee_ojk

        new_interest_rate = max_fee_ojk - origination_fee_in_decimal
        if new_interest_rate <= 0:
            new_interest_rate = 0

        additional_loan_data.update(
            {
                'is_exceed': True,
                'max_fee_ojk': py2round(max_fee_ojk, 3),
                'simple_fee': simple_fee,
                'provision_fee_rate': py2round(provision_fee_rate, 3),
                'new_interest_rate': py2round(new_interest_rate, 3)
            }
        )
        return additional_loan_data

    return additional_loan_data


def generate_loan_payment_merchant_financing(application, loan_requested, distributor):
    loan_purpose = "Modal usaha"
    with transaction.atomic():
        today_date = timezone.localtime(timezone.now()).date()
        due_date = today_date + relativedelta(days=loan_requested['loan_duration_in_days'])
        first_payment_date = due_date
        daily_max_fee_from_ojk = get_daily_max_fee()
        additional_loan_data = {
            'is_exceed': False,
            'max_fee_ojk': 0.0,
            'simple_fee': 0.0,
            'provision_fee_rate': 0.0,
            'new_interest_rate': 0.0
        }
        monthly_interest_rate = loan_requested['interest_rate_monthly']
        daily_interest_rate = loan_requested['product_lookup'].daily_interest_rate
        loan_amount = loan_requested['loan_amount']

        provision_fee = loan_requested['provision_fee']
        if daily_max_fee_from_ojk:
            additional_loan_data = validate_merchant_financing_max_interest_with_ojk_rule(
                loan_requested, additional_loan_data, daily_max_fee_from_ojk
            )
            if additional_loan_data['is_exceed']:
                from juloserver.loan.services.loan_related import \
                    get_loan_amount_by_transaction_type
                monthly_interest_rate = additional_loan_data['new_interest_rate']
                daily_interest_rate = py2round(monthly_interest_rate / 30, 3)
                adjusted_loan_amount = get_loan_amount_by_transaction_type(
                    loan_requested['original_loan_amount'],
                    additional_loan_data['provision_fee_rate'], False
                )
                provision_fee = additional_loan_data['provision_fee_rate']
                loan_amount = adjusted_loan_amount

        status_lookups = StatusLookup.objects.filter(
            status_code__in=[LoanStatusCodes.INACTIVE, PaymentStatusCodes.PAYMENT_NOT_DUE])\
            .order_by('status_code')
        loan_status = status_lookups[0]
        payment_status = status_lookups[1]
        name_bank_validation_id = distributor.name_bank_validation_id
        installment_interest = (daily_interest_rate * loan_requested['loan_duration_in_days'])\
            * loan_requested['original_loan_amount']

        """
            Adding since July 2022, maybe some total_loan_disbursement_amount
            Can deduction based merchant_discount_rate and ppn too
            eg: loan_amount - (loan_amount * (origination_fee + mdr + mdr_ppn))
        """
        total_loan_disbursement_amount = loan_amount - (loan_amount * provision_fee)

        loan = Loan.objects.create(
            customer=application.customer,
            loan_status=loan_status,
            product=loan_requested['product_lookup'],
            loan_amount=loan_amount,
            loan_duration=loan_requested['loan_duration_in_days'],
            first_installment_amount=loan_amount + installment_interest,
            installment_amount=loan_amount + installment_interest,
            bank_account_destination=None,
            name_bank_validation_id=name_bank_validation_id,
            account=application.account,
            loan_purpose=loan_purpose,
            credit_matrix=None,
            loan_disbursement_amount=py2round(total_loan_disbursement_amount)
        )
        loan.cycle_day = first_payment_date.day
        loan.set_sphp_expiration_date()
        loan.sphp_sent_ts = timezone.localtime(timezone.now())
        # set payment method for Loan
        customer_has_vas = PaymentMethod.objects.active_payment_method(application.customer)
        if customer_has_vas:
            primary_payment_method = customer_has_vas.filter(is_primary=True).last()
            if primary_payment_method:
                loan.julo_bank_name = primary_payment_method.payment_method_name
                loan.julo_bank_account_number = primary_payment_method.virtual_account
        loan.save()

        Payment.objects.create(
            loan=loan, payment_status=payment_status,
            payment_number=1, due_date=due_date,
            due_amount=loan_amount + installment_interest,
            installment_principal=loan_amount,
            installment_interest=installment_interest
        )

        if additional_loan_data['is_exceed']:
            LoanAdjustedRate.objects.create(
                loan=loan,
                adjusted_monthly_interest_rate=monthly_interest_rate,
                adjusted_provision_rate=additional_loan_data['provision_fee_rate'],
                max_fee=additional_loan_data['max_fee_ojk'],
                simple_fee=additional_loan_data['simple_fee']
            )

        return loan


def is_loan_more_than_one(account):
    loans = account.loan_set.exclude(loan_status__in=(
            LoanStatusCodes.CANCELLED_BY_CUSTOMER,
            LoanStatusCodes.SPHP_EXPIRED,
            LoanStatusCodes.FUND_DISBURSAL_FAILED,
            LoanStatusCodes.PAID_OFF,))
    loan = loans.last()
    if loan and loan.status == LoanStatusCodes.INACTIVE:
        return True

    return False


def is_account_forbidden_to_create_loan(account):

    if account.status_id in {
        JuloOneCodes.INACTIVE,
        JuloOneCodes.OVERLIMIT,
        JuloOneCodes.SUSPENDED,
        JuloOneCodes.DEACTIVATED,
        JuloOneCodes.TERMINATED,
        JuloOneCodes.FRAUD_REPORTED,
        JuloOneCodes.APPLICATION_OR_FRIENDLY_FRAUD,
        JuloOneCodes.SCAM_VICTIM,
    }:
        return True
    return False


def custom_error_messages_for_merchant_financing(field_name, data_type, is_raise_invalid=True):
    default_message = str(field_name + " harus diisi")
    messages = {
        "blank": default_message,
        "null": default_message,
        "required": default_message
    }
    if is_raise_invalid:
        default_message = str(field_name + " tidak valid")
        if data_type == int:
            default_message = str(field_name + " harus integer")
        elif data_type == float:
            default_message = str(field_name + " harus float/decimal")
        elif data_type == str:
            default_message = str(field_name + " harus string")
        messages['invalid'] = default_message

    return messages


def mf_disbursement_format_data(raw_data):
    formatted_data = {}
    for raw_field, formatted_field in PARTNER_MF_DISBURSEMENT_UPLOAD_MAPPING_FIELDS:
        formatted_data[formatted_field] = raw_data[raw_field.lower()]

    return formatted_data


def merchant_financing_register_format_data(raw_data):
    formated_data = {}

    for raw_field, formated_field in PARTNER_MF_REGISTER_UPLOAD_MAPPING_FIELDS:
        formated_data[formated_field] = raw_data.get(raw_field)

    return formated_data


def merchant_financing_adjust_limit_format_data(raw_data):
    formated_data = {}

    for raw_field, formated_field in PARTNER_MF_ADJUST_LIMIT_UPLOAD_MAPPING_FIELDS:
        formated_data[formated_field] = raw_data.get(raw_field)

    return formated_data


def validate_kin_name(kin_name: str) -> tuple:
    is_valid = True
    notes = ""

    value = kin_name.strip()

    if not value:
        is_valid = False
        notes = 'nama kontak darurat tidak boleh kosong'

    elif len(value) < 3:
        is_valid = False
        notes = 'nama kontak darurat minimal 3 karakter'

    # Validate contain numeric ex: 'Deni1' or 0eni
    elif any(char.isdigit() for char in value):
        is_valid = False
        notes = 'Mohon pastikan nama sesuai KTP (tanpa Bpk, Ibu, Sdr, dsb)'

    # Validate any special char !"#$%&'()*+,-./:;<=>?@[\]^_`{|}~.
    elif any(char in string.punctuation for char in value):
        is_valid = False
        notes = 'Mohon pastikan nama sesuai KTP (tanpa Bpk, Ibu, Sdr, dsb)'

    # Validate double space
    elif "  " in value:
        is_valid = False
        notes = 'Mohon pastikan nama sesuai KTP (tanpa Bpk, Ibu, Sdr, dsb)'

    return is_valid, notes


def validate_kin_mobile_phone(
    kin_mobile_phone: str, close_kin_mobile_phone: str, mobile_phone_1: str
) -> tuple:
    is_valid = True
    notes = ""

    if not kin_mobile_phone:
        is_valid = False
        notes = 'nomor kontak darurat tidak boleh kosong'

    elif len(kin_mobile_phone) < 10:
        is_valid = False
        notes = 'nomor kontak darurat minimal 10 digit'

    elif len(kin_mobile_phone) > 14:
        is_valid = False
        notes = 'nomor kontak darurat maksimal 14 digit'

    # Validate double space
    elif "  " in kin_mobile_phone:
        is_valid = False
        notes = 'nomor kontak darurat tidak boleh double spasi'

    elif not re.match(r'^08[0-9]{7,14}$', kin_mobile_phone):
        is_valid = False
        notes = 'nomor kontak darurat mohon diisi dengan format 08xxxxx'

    else:
        # Validate repeat number until 7 times. Ex: 081111111234
        repeated_number = filter(lambda x: kin_mobile_phone.count(x) >= 7, kin_mobile_phone)
        if len(set(repeated_number)) > 0:
            is_valid = False
            notes = 'Maaf, nomor kontak darurat yang kamu masukkan tidak valid. Mohon masukkan nomor lainnya.'

        # Validate kin_mobile_phone against mobile_phone_1 and close_kin_mobile_phone
        if kin_mobile_phone == mobile_phone_1:
            is_valid = False
            notes = 'nomor kontak darurat tidak boleh sama dengan pemilik akun'

        elif kin_mobile_phone == close_kin_mobile_phone:
            is_valid = False
            notes = 'nomor kontak darurat tidak boleh sama nomor hp pasangan/orang tua'

    return is_valid, notes


def generate_skrtp_link(loan, timestamp) -> str:
    loan_xid_str = str(loan.loan_xid)
    now = timestamp

    now_str = now.strftime("%Y%m%d%H%M%S")
    token_str = '{}_{}'.format(loan_xid_str, now_str)

    token_bytes = token_str.encode("ascii")
    base64_bytes = base64.b64encode(token_bytes)
    base64_string = base64_bytes.decode("ascii")

    skrtp_link = settings.JULO_WEB_URL + '/skrtp/{}'.format(base64_string)

    return skrtp_link


def compute_mf_amount(interest_rate, financing_tenure, installment_number, financing_amount):
    interest_amount = (interest_rate / 12 / 30) * financing_amount * financing_tenure
    total_due_amount = interest_amount + financing_amount

    principal_each_payment = ceil(financing_amount / installment_number)
    interest_each_payment = ceil(interest_amount / installment_number)

    installment_each_payment = principal_each_payment + interest_each_payment

    deviation = 0
    total_due_amount_payment = installment_each_payment * installment_number
    if total_due_amount_payment != total_due_amount:
        deviation = abs(total_due_amount - total_due_amount_payment)

    first_installment_amount = installment_each_payment + deviation
    return (
        first_installment_amount,
        installment_each_payment,
        deviation,
        interest_each_payment,
        principal_each_payment,
    )


def get_rounded_monthly_interest_rate(interest_rate):
    return round(interest_rate / 12 * 100, 4)


def validate_max_file_size(file, file_size):
    max_file_size = file_size * 1024 * 1024  # calculate to MB
    if file.size > max_file_size:
        return "file size is too big"


def mf_standard_loan_submission_format_data(raw_data):
    formatted_data = {}
    mapping_fileds = MF_STANDARD_PRODUCT_UPLOAD_MAPPING_FIELDS
    if raw_data.get(MFStandardProductUploadDetails.INVOICE_LINK):
        mapping_fileds.append(("invoice_link", MFStandardProductUploadDetails.INVOICE_LINK))
    if raw_data.get(MFStandardProductUploadDetails.GIRO_LINK):
        mapping_fileds.append(("giro_link", MFStandardProductUploadDetails.GIRO_LINK))
    if raw_data.get(MFStandardProductUploadDetails.SKRTP_LINK):
        mapping_fileds.append(("skrtp_link", MFStandardProductUploadDetails.SKRTP_LINK))
    if raw_data.get(MFStandardProductUploadDetails.MERCHANT_PHOTO_LINK):
        mapping_fileds.append(
            ("merchant_photo_link", MFStandardProductUploadDetails.MERCHANT_PHOTO_LINK)
        )

    for raw_field, formatted_field in mapping_fileds:
        formatted_data[formatted_field] = raw_data[raw_field.lower()]

    return formatted_data


def compute_loan_calculation_mf_standard(loan_requested):
    provision_amount = (
        loan_requested['provision_fee'] * loan_requested['original_loan_amount_requested']
    )

    return provision_amount


def compute_mf_standard_amount(
    loan_requested, loan_amount, monthly_interest_rate, is_provision_fee_not_included=False
):
    installment_number = loan_requested['installment_number']
    provision_fee = loan_requested['provision_fee']
    financing_tenure = loan_requested['financing_tenure']

    interest_amount = (monthly_interest_rate / 30) * loan_amount * financing_tenure

    principal_each_payment = round(loan_amount / installment_number)
    provision_each_payment = round((provision_fee * loan_amount) / installment_number)

    if is_provision_fee_not_included:
        interest_each_payment = round(interest_amount / installment_number)
    else:
        interest_each_payment = round(
            (interest_amount / installment_number) + provision_each_payment
        )

    installment_each_payment = principal_each_payment + interest_each_payment

    first_installment_amount = installment_each_payment
    return (
        first_installment_amount,
        installment_each_payment,
        interest_each_payment,
        principal_each_payment,
    )


def mapping_lender_for_loan_mf_standard(application):
    lender = partner = None
    bypass_by_product_line = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.BYPASS_LENDER_MATCHMAKING_PROCESS_BY_PRODUCT_LINE,
        category="followthemoney",
        is_active=True,
    ).first()
    if bypass_by_product_line:
        lender_mapping = bypass_by_product_line.parameters
        lender_id = lender_mapping.get(str(application.product_line_id))
        if lender_id:
            lender = LenderCurrent.objects.get_or_none(id=lender_id)
        else:
            lender = LenderCurrent.objects.get(lender_name='jtp')

    if lender:
        partner = lender.user.partner

    return partner, lender


def get_lender_by_partner(application):
    lender = LenderCurrent.objects.get(lender_name='jtp')
    loan_partner = lender.user.partner
    feature_setting = PartnershipFeatureSetting.objects.filter(
        feature_name=PartnershipFeatureNameConst.LENDER_MATCHMAKING_BY_PARTNER,
        is_active=True,
    ).first()
    if feature_setting:
        app_partner_name = application.partner.name_detokenized
        fs_param = feature_setting.parameters
        lender_name = fs_param.get(app_partner_name)
        if lender_name:
            lender_by_partner = LenderCurrent.objects.get_or_none(lender_name=lender_name)
            if lender_by_partner:
                lender = lender_by_partner
                loan_partner = lender.user.partner
            return loan_partner, lender

    return loan_partner, lender


def validate_file_from_url(url: str) -> str:
    err_invalid_link = "Files link is not valid, please reupload with the right link"

    try:
        result = urlparse(url)
        if all([result.scheme, result.netloc]):
            try:
                resp_head = requests.head(url)
                if resp_head and resp_head.status_code >= 300:
                    return err_invalid_link
            except Exception:
                return err_invalid_link
        else:
            return err_invalid_link

        if "drive.google" in url:
            regex = "https://drive.google.com/file/d/(.*?)/(.*?)"
            file_id = re.search(regex, url)
            if not file_id:
                return err_invalid_link + " - invalid Google Drive URL"
            file_id = file_id[1]
            google_base_url = "https://docs.google.com/uc?export=download"
            session = requests.Session()
            response = session.get(google_base_url, params={"id": file_id}, stream=True)
            content_length = response.headers.get("Content-Length")
            max_file_size = 2 * 1024 * 1024
            if int(content_length) > max_file_size:
                return err_invalid_link + " - File size too big"
            content_disposition = response.headers.get("Content-Disposition")
            if not content_disposition:
                return err_invalid_link + " - invalid Google Drive URL"
            match = re.search(r'filename="(.+?)"', content_disposition)
            if not match:
                return err_invalid_link + " - Invalid Google Drive URL"
            filename = match.group(1)
            _, file_ext = os.path.splitext(filename)
        else:
            path = urlparse(url).path
            file_ext = os.path.splitext(path)[1]

        allowed_file_ext = {
            '.pdf',
            '.png',
            '.jpg',
            '.jpeg',
            '.webp',
        }
        if file_ext not in allowed_file_ext:
            return err_invalid_link + ' - invalid file type'

    except Exception:
        return err_invalid_link + " - invalid url"


def validate_file_from_url_including_restricted_file(url):
    err_invalid_link = "Files link is not valid, please reupload with the right link"
    downloaded_file_path = ""
    try:
        if "drive.google" in url:
            file_id = get_google_drive_file_id(url)
            gdrive_client = get_partnership_google_drive_api_client()
            file_name, file_type, file_size = gdrive_client.get_file_metadata(file_id)
            downloaded_file_path = os.path.join('/media', file_name)
            gdrive_client.download_restricted_google_drive_file(file_id, downloaded_file_path)

            max_file_size = UPLOAD_DOCUMENT_MAX_SIZE
            if int(file_size) > max_file_size:
                return err_invalid_link + " - File size too big", ""

            _, file_ext = os.path.splitext(file_name)
        else:
            path = urlparse(url).path
            file_ext = os.path.splitext(path)[1]

        allowed_file_ext = {
            '.pdf',
            '.png',
            '.jpg',
            '.jpeg',
            '.webp',
        }
        if file_ext not in allowed_file_ext:
            return err_invalid_link + ' - invalid file type', ""

        return "", downloaded_file_path

    except Exception:
        return err_invalid_link + " - invalid url", ""


def download_image_from_restricted_url(image_url):
    """
    download image for restricted URL
    the first part is for handling google drive url
    the second part is for handling any public url usually aws
    """
    if "drive.google" in image_url:
        file_id = get_google_drive_file_id(image_url)
        gdrive_client = get_partnership_google_drive_api_client()
        # to get file metadata to just check file type = image
        file_name, file_type, _ = gdrive_client.get_file_metadata(file_id)
        if "image" not in file_type:
            raise Exception("File is not an image: {}".format(image_url))

        downloaded_file_path = os.path.join('/media', file_name)
        gdrive_client.download_restricted_google_drive_file(file_id, downloaded_file_path)
        file_size = os.path.getsize(downloaded_file_path)
        if file_size > UPLOAD_DOCUMENT_MAX_SIZE:
            raise Exception(WebAppErrorMessage.NOT_ALLOWED_IMAGE_SIZE)
    else:
        downloaded_file_path = download_file_with_fileio(image_url, 'application/octet-stream')

    return downloaded_file_path


def download_pdf_from_restricted_url(pdf_url):
    """
    download pdf for restricted URL
    the first part is for handling google drive url
    the second part is for handling any public url usually aws
    """
    # TO DO implement security to check the file contains malware or else
    if "drive.google" in pdf_url:
        file_id = get_google_drive_file_id(pdf_url)
        gdrive_client = get_partnership_google_drive_api_client()
        # to get file metadata to just check file type = pdf
        file_name, file_type, _ = gdrive_client.get_file_metadata(file_id)
        if file_type != 'application/pdf':
            raise Exception("File is not an pdf: {}".format(pdf_url))

        downloaded_file_path = os.path.join('/media', file_name)
        gdrive_client.download_restricted_google_drive_file(file_id, downloaded_file_path)
        file_size = os.path.getsize(downloaded_file_path)
        if file_size > UPLOAD_DOCUMENT_MAX_SIZE:
            raise Exception(WebAppErrorMessage.NOT_ALLOWED_IMAGE_SIZE)
    else:
        downloaded_file_path = download_file_with_fileio(pdf_url, 'application/pdf')

    return downloaded_file_path


def download_file_with_fileio(url, file_type):
    file_name = os.path.basename(url)
    file_path = os.path.join('/media', file_name)
    response = requests.get(url, stream=True)
    if response.status_code == 200:
        content_type = response.headers.get("Content-Type")
        if content_type != file_type:
            content = "correct"
            if file_type == "application/pdf":
                content += " pdf"
            if file_type == "application/octet-stream":
                content += " image"
            raise Exception("File is not {}: {}".format(content, url))
        with io.FileIO(file_path, 'wb') as file:
            for chunk in response.iter_content(1024):  # Download in chunks
                file.write(chunk)
    else:
        raise Exception('Failed to fetch the url')

    return file_path


def get_fs_send_skrtp_option_by_partner(partner_name: str):
    email = None
    phone_number = None
    feature_setting = PartnershipFeatureSetting.objects.filter(
        feature_name=PartnershipFeatureNameConst.SEND_SKRTP_OPTION_BY_PARTNER,
        is_active=True,
    ).first()
    if feature_setting:
        fs_param = feature_setting.parameters
        fs_val = fs_param.get(partner_name)
        if fs_val and fs_val.get("is_active"):
            email = fs_val.get("email")
            phone_number = fs_val.get("phone_number")
            if not email or not re.match(r"[^@]+@[^@]+\.[^@]+", email):
                return "Invalid partner's email on feature setting", None, None
            if not phone_number or not verify_phone_number(phone_number):
                return "Invalid partner's phone_number on feature setting", email, None

    return None, email, phone_number
