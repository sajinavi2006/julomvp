import logging

from juloserver.julocore.python2.utils import py2round
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting
from juloserver.loan.models import (
    LoanAdditionalFee,
    LoanAdditionalFeeType,
)
from juloserver.loan.constants import LoanTaxConst, LoanDigisignFeeConst
from juloserver.julo.exceptions import JuloException

logger = logging.getLogger(__name__)


def get_loan_tax_setting(application_id=None):
    tax_fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.LOAN_TAX_CONFIG,
        is_active=True,
    ).last()
    if not tax_fs:
        return None

    parameters = tax_fs.parameters
    whitelist = parameters.get("whitelist", {})
    is_whitelisted = whitelist.get('is_active', False)
    whitelisted_application_ids = whitelist.get('list_application_ids', [])
    if is_whitelisted and application_id not in whitelisted_application_ids:
        # Whitelist on but app_id is not whitelisted, same with inactive
        return None

    return parameters


def calculate_tax_amount(provision_amount, product_line_id, application_id=None):
    """
    Calculate tax amount based on provision.
    Tax percentage will be taken from FS.
    if FS is disabled, no tax will be taken
    """
    tax_fs = get_loan_tax_setting(application_id)

    logger.info(
        {
            "action": "juloserver.loan.services.loan_tax.calculate_tax_amount",
            "provision_amount": provision_amount,
            "product_line_id": product_line_id,
            "tax_fs": tax_fs,
            "application_id": application_id,
        }
    )

    if not tax_fs or (
        tax_fs.get('product_line_codes') and product_line_id not in tax_fs.get('product_line_codes')
    ):
        """
        return 0 if no FS,
        also return 0 if product_line_code not registered
        but bypass this check if product_line_codes empty
        (empty means apply for all product_line_code)
        """
        return 0

    return int(py2round(tax_fs.get('tax_percentage', 0) * provision_amount))


def get_tax_rate(product_line_id: int, app_id: int = None) -> float:
    tax_fs = get_loan_tax_setting(app_id)

    logger.info(
        {
            "action": "juloserver.loan.services.loan_tax.get_tax_rate",
            "product_line_id": product_line_id,
            "tax_fs": tax_fs,
            "application_id": app_id,
        }
    )

    if not tax_fs or (
        tax_fs.get('product_line_codes') and product_line_id not in tax_fs.get('product_line_codes')
    ):
        return 0

    return tax_fs.get('tax_percentage', 0)


def insert_loan_tax(loan, tax_amount):
    """
    Insert loan_tax amount to LoanAdditionalFee Table
    if data already exist, will update
    """
    if not loan:
        raise JuloException("Loan not found")

    logger.info(
        {
            "action": "juloserver.loan.services.loan_tax.insert_loan_tax",
            "loan_id": loan.id,
            "tax_amount": tax_amount,
        }
    )
    loan_additional_fee_type = LoanAdditionalFeeType.objects.get_or_none(
        name=LoanTaxConst.ADDITIONAL_FEE_TYPE
    )
    if not loan_additional_fee_type:
        # raise error
        logger.error(
            {
                "action": "juloserver.loan.services.loan_tax.insert_loan_tax",
                "fee_type": "fee_type loan_tax Not found",
                "loan_id": loan.id,
                "tax_amount": tax_amount,
            }
        )
        return None

    defaults = {'fee_amount': tax_amount}
    # Tax only 1, if tax already exist update.
    loan_tax, created = LoanAdditionalFee.objects.update_or_create(
        loan=loan,
        fee_type=loan_additional_fee_type,
        defaults=defaults,
    )
    if not created:
        logger.info(
            {
                "action": "juloserver.loan.services.loan_tax.insert_loan_tax",
                "fee_type": "LoanAdditionalFee already exist, updated",
                "loan_id": loan.id,
                "tax_amount": tax_amount,
            }
        )
    return loan_tax


def insert_loan_digisign_fee(loan, digisign_fee):
    if not loan:
        raise JuloException("Loan not found")

    loan_digisign_fee_type = LoanAdditionalFeeType.objects.get_or_none(
        name=LoanDigisignFeeConst.DIGISIGN_FEE_TYPE
    )
    if not loan_digisign_fee_type:
        # raise error
        logger.error(
            {
                "action": "juloserver.loan.services.loan_tax.insert_loan_digisign_fee",
                "fee_type": "fee_type loan_digisign_fee Not found",
                "loan_id": loan.id,
                "digisign_fee": digisign_fee,
            }
        )
        return None

    defaults = {'fee_amount': digisign_fee}
    loan_digisign_fee, created = LoanAdditionalFee.objects.update_or_create(
        loan=loan,
        fee_type=loan_digisign_fee_type,
        defaults=defaults,
    )
    if not created:
        logger.info(
            {
                "action": "juloserver.loan.services.loan_tax.insert_loan_digisign_fee",
                "fee_type": "LoanAdditionalFee already exist, updated",
                "loan_id": loan.id,
                "digisign_fee": digisign_fee,
            }
        )
    return loan_digisign_fee


def insert_loan_registration_fees(loan, registration_fees_dict):
    for fee_type, fee_amount in registration_fees_dict.items():
        loan_registraton_fee_type = LoanAdditionalFeeType.objects.get_or_none(
            name=fee_type
        )
        if not loan_registraton_fee_type:
            logger.error(
                {
                    "action": "juloserver.loan.services.loan_tax.insert_loan_registration_fees",
                    "fee_type": fee_type,
                    "loan_id": loan.id,
                    "amount": fee_amount,
                    "error": "LoanAdditionalFeeType not found",
                }
            )
            continue

        defaults = {'fee_amount': fee_amount}
        loan_registration_fee, created = LoanAdditionalFee.objects.update_or_create(
            loan=loan,
            fee_type=loan_registraton_fee_type,
            defaults=defaults,
        )
        if not created:
            logger.info(
                {
                    "action": "juloserver.loan.services.loan_tax.insert_loan_registration_fees",
                    "fee_type": fee_type,
                    "loan_id": loan.id,
                    "amount": fee_amount,
                    "error": "LoanAdditionalFee already exist, updated",
                }
            )
