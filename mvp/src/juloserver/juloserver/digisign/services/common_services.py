import logging
from typing import Dict

from django.db import transaction

from juloserver.julo.models import FeatureSetting, Application
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.digisign.constants import RegistrationStatus, DigisignFeeTypeConst
from juloserver.digisign.models import DigisignRegistration, DigisignRegistrationFee
from juloserver.digisign.services.digisign_register_services import get_registration_status


logger = logging.getLogger(__name__)


def is_eligible_for_digisign(application: Application) -> bool:
    fs = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.DIGISIGN,
        is_active=True
    )
    product_line_code = application.product_line.product_line_code
    is_valid_product_line = fs and product_line_code in ProductLineCodes.digisign_products()
    is_valid_whitelist = check_digisign_whitelist(application.customer_id)
    return is_valid_product_line and is_valid_whitelist


def check_digisign_whitelist(customer_id):
    whitelist_fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.WHITELIST_DIGISIGN, is_active=True
    ).last()
    if whitelist_fs:
        whitelist_customer_ids = whitelist_fs.parameters.get('customer_ids', [])
        return customer_id in whitelist_customer_ids
    return True


def can_charge_digisign_fee(application: Application) -> bool:
    status = None
    if is_eligible_for_digisign(application):
        status = get_registration_status(application)

    return status in RegistrationStatus.DONE_STATUS


def calc_digisign_fee(loan_amount: int, transaction_method_code: int) -> int:
    fs = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.DIGISIGN,
        is_active=True
    )
    params = fs.parameters if fs and fs.parameters else {}
    params = params.get('digisign_fee', {})
    params = params.get('signature_fee')
    if not params:
        return 0

    trans_method_settings = params.get('transaction_method_settings', [])
    trans_method_actives = {}
    for setting in trans_method_settings:
        trans_method = setting.get('transaction_method')
        is_active = setting.get('is_active', False)
        if trans_method:
            trans_method_actives[trans_method] = is_active

    if not trans_method_actives.get(transaction_method_code, False):
        return 0

    if loan_amount < params.get('minimum_loan_amount', 0):
        return 0

    total_fee = params.get('borrower_fee', 0) + params.get('lender_fee', 0)
    return total_fee


def calc_registration_fee(application: Application) -> Dict:
    fs = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.DIGISIGN,
        is_active=True
    )
    params = fs.parameters if fs and fs.parameters else {}
    params = params.get('digisign_fee', {})
    registration_fee_settings = params.get('registration_fee')
    if not registration_fee_settings:
        return {}

    registration = DigisignRegistration.objects.filter(
        customer_id=application.customer_id
    ).last()
    registration_fees = DigisignRegistrationFee.objects.filter(
        customer_id=application.customer_id,
        status__in=[
            DigisignFeeTypeConst.REGISTRATION_FEE_CHARGED_STATUS,
            DigisignFeeTypeConst.REGISTRATION_FEE_CREATED_STATUS,
        ]
    )

    uncharge_fee_types = set()
    if isinstance(registration.verification_results, dict):
        for fee_name, result in registration.verification_results.items():
            if result:
                uncharge_fee_types.add(
                    DigisignFeeTypeConst.REGISTRATION_STATUS_MAPPING_FEES[fee_name]
                )

    for fee_obj in registration_fees:
        if fee_obj.fee_type in DigisignFeeTypeConst.REGISTRATION_FEES:
            uncharge_fee_types.remove(fee_obj.fee_type)

    registration_fees = {}
    for fee_type in uncharge_fee_types:
        fee = 0
        if fee_type == DigisignFeeTypeConst.REGISTRATION_DUKCAPIL_FEE_TYPE:
            fee = registration_fee_settings.get('dukcapil_check_fee', 0)
        elif fee_type == DigisignFeeTypeConst.REGISTRATION_FR_FEE_TYPE:
            fee = registration_fee_settings.get('fr_check_fee', 0)
        elif fee_type == DigisignFeeTypeConst.REGISTRATION_LIVENESS_FEE_TYPE:
            fee = registration_fee_settings.get('liveness_check_fee', 0)

        if fee:
            registration_fees[fee_type] = fee

    return registration_fees


def insert_registration_fees(customer_id: int, registration_fees: dict, extra_data: dict={}):
    if not registration_fees:
        return

    for fee_type, fee_amount in registration_fees.items():
        registration_fee = DigisignRegistrationFee.objects.filter(
            customer_id=customer_id,
            fee_type=fee_type,
            status=DigisignFeeTypeConst.REGISTRATION_FEE_CHARGED_STATUS
        ).last()

        if registration_fee:
            logger.info(
                {
                    "action": "juloserver.digisign.services.insert_registration_fees",
                    "data": {
                        "fee_type": fee_type,
                        "customer_id": customer_id,
                        "status": DigisignFeeTypeConst.REGISTRATION_FEE_CHARGED_STATUS
                    },
                    "error": "DigisignRegistrationFee already charged",
                }
            )
        else:
            DigisignRegistrationFee.objects.create(
                customer_id=customer_id,
                fee_type=fee_type,
                status=DigisignFeeTypeConst.REGISTRATION_FEE_CREATED_STATUS,
                fee_amount=fee_amount,
                extra_data=extra_data
            )


def update_registration_fees_status(customer_id: int, loan_id: int, disbursed: bool):
    logger.info(
        {
            "action": "juloserver.digisign.services.update_registration_fees_status",
            "data": {
                "loan_id": loan_id,
                "customer_id": customer_id,
                "disbursed": disbursed,
            },
        }
    )

    with transaction.atomic():
        registration_fees = DigisignRegistrationFee.objects.select_for_update().filter(
            customer_id=customer_id,
            extra_data__loan_id=loan_id,
        )

        if disbursed:
            registration_fees.update(status=DigisignFeeTypeConst.REGISTRATION_FEE_CHARGED_STATUS)
        else:
            registration_fees.update(status=DigisignFeeTypeConst.REGISTRATION_FEE_CANCELLED_STATUS)


def get_total_digisign_fee(
    app: Application, requested_loan_amount: int, transaction_code: int
) -> int:
    """
    Get all the digisign fee for calculation
    """

    digisign_fee = total_register_fee = 0
    registration_fees_dict = {}

    if can_charge_digisign_fee(app):
        digisign_fee = calc_digisign_fee(
            loan_amount=requested_loan_amount,
            transaction_method_code=transaction_code,
        )
        registration_fees_dict = calc_registration_fee(app)
        total_register_fee = sum(registration_fees_dict.values())

    total_fee = digisign_fee + total_register_fee

    logger.info(
        {
            "action": "julosever.digisign.services.common_services.get_total_digisign_fee",
            "message": "get total digisign fee",
            "total_fee": total_fee,
            "customer_id": app.customer_id,
            "application_id": app.id,
            "digisign_fee": digisign_fee,
            "total_register_fee": total_register_fee,
            "registration_fees_dict": registration_fees_dict,
        }
    )

    return total_fee
