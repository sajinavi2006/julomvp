from abc import ABC, abstractmethod
import math
from typing import Dict, List, Optional, Tuple
import logging
import base64

from kombu.exceptions import LimitExceeded
import requests

from juloserver.julo.constants import FeatureNameConst
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.julo.models import Customer, Partner, Image, Application, FeatureSetting
from juloserver.loan.exceptions import (
    AccountLimitExceededException,
    AccountUnavailable,
    LoggableException,
    TransactionAmountExceeded,
    TransactionAmountTooLow,
)
from juloserver.loan.services.loan_creation import get_loan_creation_cm_data, get_loan_matrices
from juloserver.payment_point.models import TransactionMethod
from juloserver.qris.constants import QrisLinkageStatus
from juloserver.qris.exceptions import (
    HasNotSignedWithLender,
    NoQrisLenderAvailable,
    QrisLinkageNotFound,
    QrisMerchantBlacklisted,
)
from juloserver.qris.services.core_services import (
    has_linkage_signed_with_current_lender,
    is_success_linkage_older_than,
)
from juloserver.qris.services.feature_settings import (
    QrisFAQSettingHandler,
    QrisLoanEligibilitySetting,
    QrisProgressBarSetting,
    QrisTenureFromLoanAmountHandler,
    QrisTenureFromLoanAmountSetting,
    QrisBlacklistMerchantSetting,
)
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.qris.services.linkage_related import get_linkage
from juloserver.qris.tasks import (
    process_callback_register_from_amar_task,
    process_callback_transaction_status_from_amar_task,
)
from juloserver.account.models import Account, AccountLimit
from juloserver.julo.statuses import JuloOneCodes
from juloserver.loan.constants import LoanErrorCodes
from juloserver.loan.services.credit_matrix_repeat import get_credit_matrix_repeat
from juloserver.loan.services.loan_formula import LoanAmountFormulaService
from juloserver.loan.services.loan_related import get_credit_matrix_and_credit_matrix_product_line
from juloserver.loan.services.loan_tax import get_tax_rate
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.qris.models import QrisPartnerLinkage
from juloserver.julo.clients import get_julo_sentry_client


logger = logging.getLogger(__name__)


class QrisUserStateService(ABC):
    """
    Abstract Base Service for QrisUserStateView
    """

    def __init__(self, customer_id: int, partner_name: str):
        self.customer = Customer.objects.get(pk=customer_id)
        self.partner_name = partner_name
        self.partner = Partner.objects.get(name=self.partner_name)

        self.linkage = get_linkage(
            customer_id=customer_id,
            partner_id=self.partner.id,
        )

    @abstractmethod
    def get_response(self) -> Tuple[Dict, str]:
        """
        please implement for each partner
        """
        pass


class AmarUserStateService(QrisUserStateService):
    @property
    def email(self) -> str:
        return self.customer.email

    @property
    def nik(self) -> str:
        return self.customer.nik

    @property
    def phone(self) -> str:
        return self.customer.phone

    @property
    def is_linkage_active(self) -> bool:
        """
        For AMAR, linkage is set active after callback success
        """
        is_linkage_success = self.linkage.status == QrisLinkageStatus.SUCCESS
        return is_linkage_success

    @property
    def signature_id(self) -> str:
        """
        Signature for master agreement
        """
        signature_image = self.linkage.qris_user_state.signature_image

        if signature_image:
            return str(signature_image.id)

    @property
    def to_partner_xid(self) -> str:
        return self.linkage.to_partner_user_xid.hex

    @property
    def user_state(self) -> str:
        return self.linkage.qris_user_state

    @property
    def available_limit(self) -> int:
        account_id = self.customer.account.id
        account_limit = AccountLimit.objects.filter(account_id=account_id).last()

        return account_limit.available_limit

    @property
    def to_sign_lender(self) -> str:
        """
        Return name of lender that user needs to sign agreement with
        """
        is_already_signed, current_lender = has_linkage_signed_with_current_lender(
            linkage=self.linkage,
        )

        if not is_already_signed:
            return current_lender.lender_name

        return ""

    def _get_active_progress_bar_data(self, setting: QrisProgressBarSetting, status: str) -> Dict:
        response = {
            "is_active": True,
            "percentage": setting.get_percentage(status),
            "messages": {
                "title": setting.get_title(status),
                "body": setting.get_body(status),
                "footer": setting.get_footer(status),
            },
        }

        return response

    def get_progress_bar(self) -> Dict:
        """
        Get progress bar info for user
        """

        qris_progress_bar = QrisProgressBarSetting()
        empty_response = {
            "is_active": False,
            "percentage": "",
            "messages": {
                "title": "",
                "body": "",
                "footer": "",
            },
        }
        # not active
        if not qris_progress_bar.is_active:
            return empty_response

        # first time, no linkage, show intitial/default progress state
        if not self.linkage:
            return self._get_active_progress_bar_data(
                setting=qris_progress_bar,
                status=QrisProgressBarSetting.STATUS_DEFAULT,
            )

        # expired after success for some time
        if qris_progress_bar.is_disappear_active and is_success_linkage_older_than(
            seconds_since_success=qris_progress_bar.active_seconds_after_success,
            linkage_id=self.linkage.id,
        ):
            return empty_response

        # show progress bar based on other statuses
        linkage_status = self.linkage.status

        return self._get_active_progress_bar_data(
            setting=qris_progress_bar,
            status=linkage_status,
        )

    def get_response(self) -> Dict:
        """
        Response for AMAR Linkage User State
        """
        qris_faq_handler = QrisFAQSettingHandler()
        response_data = {
            "email": "",
            "phone": "",
            "nik": "",
            "is_linkage_active": False,
            "signature_id": "",
            "to_partner_xid": "",
            "faq_link": qris_faq_handler.get_amar_faq_link(),
            "to_sign_lender": self.to_sign_lender,
        }

        if self.linkage and self.user_state and self.signature_id:
            response_data['email'] = self.email
            response_data['phone'] = self.phone
            response_data['signature_id'] = self.signature_id
            response_data['is_linkage_active'] = self.is_linkage_active
            response_data['nik'] = self.nik
            response_data['to_partner_xid'] = self.to_partner_xid
            response_data['available_limit'] = self.available_limit

        # add progress bar
        response_data['registration_progress_bar'] = self.get_progress_bar()

        return response_data


def get_qris_user_state_service(customer_id: int, partner_name: str) -> QrisUserStateService:
    """
    Get correct service logic for view
    based on partner name
    """
    map = {PartnerNameConstant.AMAR: AmarUserStateService}

    # init service
    service = map[partner_name](
        customer_id=customer_id,
        partner_name=partner_name,
    )

    return service


def check_qris_loan_eligibility(input_amount: int) -> None:
    """
    Check specific qris settings
    Params:
        input_amount: amount that user inputs
    """
    fs = QrisLoanEligibilitySetting()
    if not fs.is_active:
        return

    if input_amount > fs.max_requested_amount:
        raise TransactionAmountExceeded

    if input_amount < fs.min_requested_amount:
        raise TransactionAmountTooLow


class AmarRegisterLoginCallbackService:
    def __init__(self, data: Dict):
        self.payload = data
        self.to_partner_user_xid = data['partnerCustomerId']
        self.status = data['status']
        self.type = data['type']
        self.account_number = data['accountNumber']

    def process_callback(self) -> None:
        """
        Process callback from amar registration/login
        """
        process_callback_register_from_amar_task.delay(
            to_partner_user_xid=self.to_partner_user_xid,
            amar_status=self.status,
            payload=self.payload,
        )


# List of income_ranges (lower_bound, upper_bound, label)
INCOME_RANGES = [
    (float('-inf'), 3_000_000, "Dibawah 3 juta"),
    (3_000_000, 5_000_000, "3 - 5 juta"),
    (5_000_000, 10_000_000, "5 - 10 juta"),
    (10_000_000, 20_000_000, "10 - 20 juta"),
    (20_000_000, 30_000_000, "20 - 30 juta"),
    (30_000_000, 50_000_000, "30 - 50 juta"),
    (50_000_000, 100_000_000, "50 - 100 juta"),
    (100_000_000, float('inf'), "Diatas 100 juta")
]

GENDER_MAP = {
    "Pria": "Laki-Laki",
    "Wanita": "Perempuan"
}

MARITAL_STATUS_MAP = {
    "Lajang": "BELUM KAWIN",
    "Menikah": "KAWIN",
    "Cerai": "CERAI HIDUP",
    "Janda / duda": "CERAI MATI"
}

EDUCATION_LEVEL_MAP = {
    "SD": "SD",
    "SLTP": "SMP",
    "SLTA": "SMA",
    "Diploma": "Diploma",
    "S1": "S1 (Sarjana)",
    "S2": "S2 (Magister)",
    "S3": "S3 (Doktoral)"
}


def get_education_level_label(value):
    # Return the mapped value or an empty string for None or unrecognized values
    return EDUCATION_LEVEL_MAP.get(value, "")


def get_marital_status_label(status):
    # Return the mapped value, or an empty string for None or unrecognized values
    return MARITAL_STATUS_MAP.get(status, "")


def get_gender_label(value):
    # Return the mapped value, or an empty string for None or unrecognized values
    return GENDER_MAP.get(value, "")


def get_monthly_income_range(income) -> str:
    """
    Find the appropriate income range label for the given income.
    """
    if not income:
        income = 1
    for lower_bound, upper_bound, label in INCOME_RANGES:
        if lower_bound <= income < upper_bound:
            return label


def get_qris_partner_linkage(partner_xid, to_partner_user_xid) -> QrisPartnerLinkage:
    partner = Partner.objects.get(partner_xid=partner_xid)
    partner_id = partner.id
    qris_partner_linkage = QrisPartnerLinkage.objects.filter(
        to_partner_user_xid=to_partner_user_xid,
        partner_id=partner_id
    ).last()
    return qris_partner_linkage


def convert_image_to_base64(image: Image) -> Optional[str]:
    try:
        # Fetch the image from the URL
        response = requests.get(image.image_url)
        response.raise_for_status()

        # Encode the content to base64
        image_base64 = base64.b64encode(response.content).decode('utf-8')

        extension = image.url.split(".")[-1]
        encoded_image = f"data:image/jpeg;base64,{image_base64}"
        if extension == 'png':
            encoded_image = f"data:image/png;base64,{image_base64}"
        elif extension == 'jpg' or extension == 'jpeg':
            encoded_image = f"data:image/jpeg;base64,{image_base64}"
        return encoded_image
    except requests.RequestException as e:
        sentry_client = get_julo_sentry_client()
        sentry_client.captureException()
        return None


def validate_image(image: Image, application: Application) -> bool:
    """
    There are two cases for image to be valid:
    1. image_status = 0, meaning the image uploaded by the customer is acceptable.
    2. image_status = 1, meaning resubmission required, in this case we check for application
       status, if x190 or x191, image is valid.
    """
    is_current_image = image.image_status == Image.CURRENT
    is_resubmission_image = image.image_status == Image.RESUBMISSION_REQ
    is_application_approved = application.status in {
        ApplicationStatusCodes.LOC_APPROVED, ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE
    }

    is_valid_image = is_current_image or (is_resubmission_image and is_application_approved)
    return is_valid_image


def get_prefilled_data(qris_partner_linkage: QrisPartnerLinkage) -> Dict:
    customer_id = qris_partner_linkage.customer_id
    customer = Customer.objects.get(id=customer_id)
    image = Image.objects.filter(
        image_source=customer.current_application_id,
        image_type='ktp_self',
        image_status__in=[Image.CURRENT, Image.RESUBMISSION_REQ]
    ).last()
    monthly_income_range = get_monthly_income_range(customer.monthly_income)
    detail_user_data = {
        "companyField": "",
        "companyName": customer.company_name,
        "education": get_education_level_label(customer.last_education),
        "monthlyIncome": monthly_income_range,
        "motherName": customer.mother_maiden_name,
        "taxNumber": "",
        "phoneNumber": customer.phone,
        "position": customer.job_type,
        "purpose": "Rekening Tabungan",
        "relatives": customer.kin_name,
        "sourceOfIncome": "Gaji Bulanan",
        "occupation": "",
    }

    domicile_address_data = {
        "address": customer.address_street_num,
        "city": customer.address_kabupaten,
        "district": customer.address_kecamatan,
        "homeType": "",
        "postalCode": customer.address_kodepos,
        "province": customer.address_provinsi,
        "rt": "0",
        "rw": "0",
        "village": customer.address_kelurahan
    }

    id_card_data = {
        "address": customer.address_street_num,
        "birthDate": customer.dob,
        "birthPlace": customer.birth_place,
        "city": customer.address_kabupaten,
        "district": customer.address_kecamatan,
        "fullName": customer.fullname,
        "gender": get_gender_label(customer.gender),
        "idCardNumber": customer.nik,
        "maritalStatus": get_marital_status_label(customer.marital_status),
        "postalCode": customer.address_kodepos,
        "province": customer.address_provinsi,
        "religion": "",
        "rt": "0",
        "rw": "0",
        "village": customer.address_kelurahan
    }

    result = {
        "detailUserData": detail_user_data,
        "domicileAddressData": domicile_address_data,
        "idCardData": id_card_data,
    }
    application = Application.objects.filter(id=customer.current_application_id).last()
    if image:
        # check for x190 if image_status = 1.
        is_valid_image = validate_image(image, application)
        if is_valid_image:
            image_base_64 = convert_image_to_base64(image)
            if image_base_64:
                id_card_file_data = {
                    "imageBase64": image_base_64
                }

                result['idCardFileData'] = id_card_file_data
    else:
        logger.info({
            'message': 'Image object not found',
            'image_source': customer.current_application_id
        })
    return result


def check_qris_blacklist_merchant(merchant_id, merchant_name) -> bool:
    """
    check merchant if blacklisted against feature setting
    """
    fs = QrisBlacklistMerchantSetting()
    if not fs.is_active:
        return False

    if merchant_id:
        if merchant_id.lower() in [mid.lower() for mid in fs.merchant_ids]:
            return True
    if merchant_name.lower() in [name.lower() for name in fs.merchant_names]:
        return True
    return False


class QrisLimitEligibilityService:
    def __init__(self, partner: Partner, data: Dict):
        self.data = data
        self.partner = partner

        # convert float amount from amar
        self.data['totalAmount'] = math.ceil(self.data['totalAmount'])

    def _get_final_loan_amount(self, requested_amount: int) -> int:

        # credit matrix
        app = self.account.get_active_application()
        (
            credit_matrix,
            credit_matrix_product_line,
        ) = get_credit_matrix_and_credit_matrix_product_line(
            application=app,
            is_self_bank_account=False,
            transaction_type=TransactionMethodCode.QRIS_1.name,
        )

        credit_matrix_repeat = get_credit_matrix_repeat(
            customer_id=self.linkage.customer_id,
            product_line_id=credit_matrix_product_line.product.product_line_code,
            transaction_method_id=TransactionMethodCode.QRIS_1.code,
        )

        credit_matrix_product = credit_matrix.product
        provision_rate = credit_matrix_product.origination_fee_pct

        if credit_matrix_repeat:
            provision_rate = credit_matrix_repeat.provision

        # tax rate
        tax_rate = get_tax_rate(
            product_line_id=app.product_line_code,
            app_id=app.id,
        )

        # finally, use service
        loan_amount_service = LoanAmountFormulaService(
            method_code=TransactionMethodCode.QRIS_1.code,
            requested_amount=requested_amount,
            tax_rate=tax_rate,
            provision_rate=provision_rate,
        )

        return loan_amount_service.final_amount

    def perform_check(self) -> Optional[LoggableException]:
        """
        Check eligibility for QRIS service
            - linkage
            - qris loan fs settings (input amount)
            - account suspension
            - available limit
            - has signed argeement with current lender?
        """

        # must check linkage before other checks
        self.linkage = QrisPartnerLinkage.objects.filter(
            to_partner_user_xid=self.data['partnerUserId'],
            partner_id=self.partner.id,
        ).last()
        if not self.linkage or self.linkage.status != QrisLinkageStatus.SUCCESS:
            raise QrisLinkageNotFound

        # input amount
        check_qris_loan_eligibility(
            input_amount=self.data['totalAmount'],
        )

        # merchant check
        transaction_detail = self.data.get("transactionDetail", {})
        merchant_id = transaction_detail.get("merchantId", "").strip()
        merchant_name = transaction_detail.get("merchantName", "").strip()

        if check_qris_blacklist_merchant(merchant_id, merchant_name):
            raise QrisMerchantBlacklisted

        # account
        self.account = Account.objects.filter(
            customer_id=self.linkage.customer_id,
            status_id=JuloOneCodes.ACTIVE,
        ).last()

        if not self.account:
            raise AccountUnavailable

        # account limit
        account_limit = self.account.accountlimit_set.last()

        if not account_limit:
            raise AccountUnavailable

        # available limit
        final_loan_amount = self._get_final_loan_amount(requested_amount=self.data['totalAmount'])

        if account_limit.available_limit < final_loan_amount:
            logger.info(
                {
                    "action": "QrisLimitEligibilityService.perform_check",
                    "customer_id": self.linkage.customer_id,
                    "message": "qris limit check limit exceeded",
                    "final_loan_amount": final_loan_amount,
                    "available_limit": account_limit.available_limit,
                    "requested_amount": self.data['totalAmount'],
                }
            )
            raise AccountLimitExceededException

        # check lender
        is_signed, lender = has_linkage_signed_with_current_lender(linkage=self.linkage)
        if not is_signed:
            logger.info(
                {
                    "action": "QrisLimitEligibilityService.perform_check",
                    "message": f"Customer has Not Signed With Lender {lender.lender_name}.",
                    "customer_id": self.linkage.customer_id,
                }
            )
            raise HasNotSignedWithLender


class AmarTransactionStatusCallbackService:
    def __init__(self, validated_data: Dict):
        self.data = validated_data

    def process_callback(self):
        """
        Process callback from amar transaction status
        """
        process_callback_transaction_status_from_amar_task.delay(
            payload=self.data,
        )


class QrisTenureRangeService:
    """
    Service class for QrisTenureRangeView
    """

    def __init__(self, customer: Customer):
        self.customer = customer
        self.fs_setting = QrisTenureFromLoanAmountSetting()
        self.qris_1_method = TransactionMethod.objects.get(pk=TransactionMethodCode.QRIS_1.code)

    def get_customer_qris_tenure_range(self, application) -> List[Dict]:
        """
        Get qris tenure range for a customer
        """
        # get max/min tenure from the correct Credit Matrix
        loan_matrices = get_loan_matrices(
            application=application,
            transaction_method=self.qris_1_method,
        )
        credit_matrix_data = get_loan_creation_cm_data(matrices=loan_matrices)
        max_tenure, min_tenure = credit_matrix_data.max_tenure, credit_matrix_data.min_tenure
        monthly_interest_rate = credit_matrix_data.monthly_interest_rate
        provision_fee_rate = credit_matrix_data.provision_fee_rate

        result = []
        for from_amount, to_amount, config_tenure in self.fs_setting.loan_amount_tenure_map:

            # set default tenure amount (1) if setting is not active
            if not self.fs_setting.is_active:
                config_tenure = self.fs_setting.DEFAULT_TENURE

            # get final tenure within range
            final_tenure = QrisTenureFromLoanAmountHandler.get_tenure_in_cm_range(
                loan_duration=config_tenure,
                max_tenure=max_tenure,
                min_tenure=min_tenure,
            )

            # display to FE, add 1 to from amount
            # 'cause in FS, if set: 19,999-30,000 it's actually 20,000-30,000
            displayed_from_amount = from_amount + 1

            tenure_obj = {
                "from_amount": displayed_from_amount,
                "to_amount": to_amount,
                "duration": final_tenure,
                "monthly_interest_rate": monthly_interest_rate,
                "provision_fee_rate": provision_fee_rate,
            }
            result.append(tenure_obj)

        # sort result by duration, from_amount ascending
        sorted_result = sorted(result, key=lambda x: (x["duration"], x["from_amount"]))

        return sorted_result

    def get_response(self) -> List[Dict]:
        application = self.customer.account.get_active_application()
        tenure_range = self.get_customer_qris_tenure_range(application)

        return {
            "tenure_range": tenure_range,
        }


def get_qris_landing_page_config_feature_setting():
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.QRIS_LANDING_PAGE_CONFIG,
    ).last()
    return feature_setting.parameters
