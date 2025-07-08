import logging
from typing import Dict, Tuple

from juloserver.julo.models import FeatureSetting
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.julo.statuses import LoanStatusCodes

from juloserver.ana_api.models import SdDevicePhoneDetail

from juloserver.loan.clients import get_julo_care_client
from juloserver.loan.constants import (
    CampaignConst,
    JuloCareStatusConst,
)
from juloserver.loan.models import (
    LoanJuloCare,
    Loan,
)

from juloserver.payment_point.constants import TransactionMethodCode

from juloserver.account.models import AccountLimit

from juloserver.moengage.services.use_cases import (
    send_user_attributes_to_moengage_for_activate_julo_care,
)

logger = logging.getLogger(__name__)


def get_eligibility_status(
    customer,
    list_loan_tenure=None,
    loan_amount=0,
    device_brand=None,
    device_model=None,
    os_version=None,
) -> Tuple[bool, Dict]:
    """
    Get julocare eligibility for a customer
    """

    if not customer.is_julocare_eligible:
        return False, {}

    if list_loan_tenure is None:
        list_loan_tenure = []

    is_eligible = False
    response_data = {}

    process_loan_exist = Loan.objects.filter(
        loan_status__in=LoanStatusCodes.julo_care_restricted_status(),
        customer=customer,
    ).exists()
    if process_loan_exist:
        return is_eligible, response_data

    customer_device = SdDevicePhoneDetail.objects.filter(customer_id=customer.id).last()
    ana_device_brand = None
    ana_device_model = None
    ana_os_version = None
    if customer_device:
        ana_device_brand = customer_device.brand
        ana_device_model = customer_device.model
        ana_os_version = int(customer_device.sdk)

    # old apps use v1/user-campaign-eligibility, need to get device info from SdDevicePhoneDetail
    if not all([device_brand, device_model, os_version]):
        if not customer_device:
            return is_eligible, response_data

        device_brand = ana_device_brand
        device_model = ana_device_model
        os_version = ana_os_version

    # new apps use v2/user-campaign-eligibility, FE send device info directly
    else:
        # write log if device info is different to easy fix data in the future
        if (
            device_brand != ana_device_brand
            or device_model != ana_device_model
            or os_version != ana_os_version
        ):
            logger.warning(
                {
                    'action': 'juloserver.loan.services.julo_care_related.get_eligibility_status',
                    'customer_id': customer.id,
                    'message': 'Device info is different between device and SdDevicePhoneDetail',
                    'device_brand': device_brand,
                    'ana_device_brand': ana_device_brand,
                    'device_model': device_model,
                    'ana_device_model': ana_device_model,
                    'os_version': os_version,
                    'ana_os_version': ana_os_version,
                }
            )

    if not customer.customer_xid:
        return is_eligible, response_data

    json_data = {
        "customer_xid": customer.customer_xid,
        "device_brand_name": device_brand,
        "device_model_name": device_model,
        "api_level": os_version,
        "list_loan_tenure": list_loan_tenure,
    }

    api_response = get_julo_care_client().send_request('/v1/eligibility', 'post', json=json_data)
    if not api_response.get('success', False):
        return is_eligible, response_data

    eligible_data = api_response.get('data', {})
    if loan_amount:
        minimun_loan_amount = eligible_data.get('minimum_eligible_loan_amount', 0)
        if loan_amount < minimun_loan_amount:
            return is_eligible, response_data

    is_eligible = eligible_data.get('eligible', False)
    if not is_eligible:
        return is_eligible, response_data

    insurance_info = eligible_data.get('insurance_info', {})
    insurance_premium = insurance_info.get('insurance_premium', {})
    for tenure in list_loan_tenure:
        str_tenure = str(tenure)
        if str_tenure in insurance_premium:
            response_data[str_tenure] = insurance_premium[str_tenure]

    return is_eligible, response_data


def get_julo_care_configuration(
    customer, transaction_method_code, device_brand=None, device_model=None, os_version=None
):
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.JULO_CARE_CONFIGURATION,
        is_active=True,
    ).last()

    configuration = {
        'campaign_name': '',
        'alert_image': '',
        'alert_description': '',
        'max_default_amount': 0,
        'show_alert': False,
        'show_pop_up': False,
        'toggle_title': '',
        'toggle_description': '',
        'toggle_link_text': '',
        'toggle_click_link': '',
    }
    if feature_setting and transaction_method_code == TransactionMethodCode.SELF.code:
        account_limit = AccountLimit.objects.filter(account=customer.account).last()
        if account_limit:
            is_eligible, _ = get_eligibility_status(
                customer=customer,
                list_loan_tenure=[],
                loan_amount=account_limit.available_limit,
                device_brand=device_brand,
                device_model=device_model,
                os_version=os_version,
            )

            if is_eligible:
                configuration.update(feature_setting.parameters)
                configuration['campaign_name'] = CampaignConst.JULO_CARE

    return configuration


def julo_care_create_policy(loan, loan_julo_care):
    customer = loan.customer

    device_brand = loan_julo_care.device_brand
    device_model = loan_julo_care.device_model
    os_version = loan_julo_care.os_version

    # old apps do not submit device info when create a loan, get data from SdDevicePhoneDetail
    if not all([device_brand, device_model, os_version]):
        customer_device = SdDevicePhoneDetail.objects.filter(customer_id=customer.id).last()
        if not customer_device:
            return False

        device_brand = customer_device.brand
        device_model = customer_device.model
        os_version = int(customer_device.sdk)

    json_data = {
        "customer_xid": customer.customer_xid,
        "device_brand": device_brand,
        "device_model_name": device_model,
        "api_level": os_version,
        "email": customer.email,
        "fullname": customer.fullname,
        "insurance_premium": loan_julo_care.insurance_premium,
        "loan_tenure": loan.loan_duration,
        "phone_number": customer.phone,
        "product_identifier_number": "",
        "product_identifier_type": "IMEI",
        "transaction_id": loan.loan_xid,
    }

    api_response = get_julo_care_client().send_request('/v1/policy', 'post', json=json_data)
    return api_response.get('success', False)


def update_loan_julo_care(serializer_class, data):
    serializer = serializer_class(data=data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    loan = Loan.objects.get_or_none(loan_xid=data['transaction_id'])
    if not loan:
        return False

    loan_julo_care = LoanJuloCare.objects.get_or_none(loan=loan, status=JuloCareStatusConst.PENDING)
    if not loan_julo_care:
        return False

    documents = data['documents'][0]
    loan_julo_care.update_safely(
        policy_id=data['policy_id'],
        policy_number=data['policy_number'],
        policy_product_code=data['product_code'],
        quotation_number=data['quotation_number'],
        status=data['status'],
        document_url=documents['url'],
        document_filename=documents['filename'],
        document_type=documents['type'],
        document_alias=documents['alias'],
    )

    execute_after_transaction_safely(
        lambda: send_user_attributes_to_moengage_for_activate_julo_care.delay(loan_id=loan.id)
    )

    return True


def reconstruct_loan_duration_response(customer, data, transaction_method_id):
    if int(transaction_method_id) != TransactionMethodCode.SELF.code:
        return data

    loan_choices = [loan_choice['duration'] for loan_choice in data['loan_choice']]
    if not loan_choices:
        return data

    is_eligible, all_insurance_premium = get_eligibility_status(
        customer, loan_choices, data['loan_choice'][0]['loan_amount']
    )
    data['is_device_eligible'] = is_eligible
    if is_eligible:
        for ix, loan_choice in enumerate(data['loan_choice']):
            insurance_premium = all_insurance_premium.get(str(loan_choice['duration']))
            if insurance_premium:
                new_provision_amount = loan_choice['provision_amount'] + insurance_premium
                tax = loan_choice.get('tax', 0)
                data['loan_choice'][ix].update(
                    {
                        'disbursement_amount': (
                            loan_choice['loan_amount'] - new_provision_amount - tax
                        ),
                        'provision_amount': new_provision_amount,
                        'insurance_premium': insurance_premium,
                        'disbursement_fee': 0,
                        'loan_campaign': "",
                        'is_show_toggle': False,
                    }
                )

    return data
