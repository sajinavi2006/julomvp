from typing import List
import logging
from typing import Union

from juloserver.julo.services2.feature_setting import FeatureSettingHelper
from juloserver.payment_point.constants import (
    FeatureNameConst as PaymentPointFeatureConst,
    SepulsaProductType,
    TransactionMethodCode,
    SepulsaProductCategory,
    XfersEWalletConst,
)
from juloserver.payment_point.models import (
    AYCProduct,
    AYCEWalletTransaction,
    XfersProduct,
    XfersEWalletTransaction,
)
from juloserver.customer_module.models import BankAccountDestination, BankAccountCategory
from juloserver.customer_module.constants import BankAccountCategoryConst
from juloserver.disbursement.constants import NameBankValidationVendors, NameBankValidationStatus
from juloserver.disbursement.models import NameBankValidation
from juloserver.payment_point.exceptions import ProductNotFound
from juloserver.julo.models import Bank, Loan, SepulsaProduct, Application
from juloserver.disbursement.services import trigger_name_in_bank_validation
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.loan.services.loan_related import update_loan_status_and_loan_history
from juloserver.disbursement.exceptions import XfersApiError
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.payment_point.utils import get_ewallet_logo
from juloserver.loan.constants import LoanStatusChangeReason

logger = logging.getLogger(__name__)


def get_ayc_sepulsa_switching_feature_setting():
    return FeatureSettingHelper(PaymentPointFeatureConst.SEPULSA_AYOCONNECT_EWALLET_SWITCH)


def get_xfers_sepulsa_switching_feature_setting():
    return FeatureSettingHelper(PaymentPointFeatureConst.SEPULSA_XFERS_EWALLET_SWITCH)


def is_applied_ayc_switching_flow(customer_id: int, transaction_method: int) -> bool:
    """
    Determine whether to apply ayc ewallet flow
    """
    if transaction_method != TransactionMethodCode.DOMPET_DIGITAL.code:
        return False

    # get fs
    fs = get_ayc_sepulsa_switching_feature_setting()

    # case active
    if fs.is_active and fs.params:
        is_prod_testing = fs.params['is_active_prod_testing']
        test_customer_ids = fs.params['prod_testing_customer_ids']

        # testing on prod or not
        if is_prod_testing:
            if customer_id and customer_id in [int(x) for x in test_customer_ids]:
                return True
        else:
            return True

    return False


def is_applied_xfers_switching_flow(customer_id: int, transaction_method: int) -> bool:
    """
    Determine whether to apply xfers ewallet flow
    """
    if transaction_method != TransactionMethodCode.DOMPET_DIGITAL.code:
        return False

    # get fs
    fs = get_xfers_sepulsa_switching_feature_setting()

    # case active
    if fs.is_active and fs.params:
        is_prod_testing = fs.params['is_whitelist_active']
        test_customer_ids = fs.params['whitelist_customer_ids']

        # testing on prod or not
        if is_prod_testing:
            if customer_id and customer_id in [int(x) for x in test_customer_ids]:
                return True
        else:
            return True

    return False


def get_ayc_ewallet_categories() -> List[str]:
    """
    get ayc product with categories fields
    """
    categories = (
        AYCProduct.objects.filter(type=SepulsaProductType.EWALLET, is_active=True)
        .distinct('category')
        .values_list('category', flat=True)
    )
    return list(categories)


def get_xfers_ewallet_categories() -> List[str]:
    """
    get xfers e-wallet product with categories fields
    """
    categories = (
        XfersProduct.objects.filter(type=SepulsaProductType.EWALLET, is_active=True)
        .distinct('category')
        .values_list('category', flat=True)
    )
    return list(categories)


def get_sepulsa_ewallet_categories() -> List[str]:
    """
    get xfers e-wallet product with categories fields
    """
    ewallet_categories = (
        SepulsaProduct.objects.filter(
            type=SepulsaProductType.EWALLET, is_active=True, is_not_blocked=True
        )
        .distinct('category')
        .values_list('category', flat=True)
    )

    return list(ewallet_categories)


def create_ayc_ewallet_transaction_and_bank_info(
    loan: Loan, ayc_product: AYCProduct, phone_number: str
) -> int:
    AYCEWalletTransaction.objects.create(
        loan_id=loan.pk,
        customer_id=loan.customer_id,
        ayc_product_id=ayc_product.pk,
        phone_number=phone_number,
        partner_price=ayc_product.partner_price,
        customer_price=ayc_product.customer_price,
        customer_price_regular=ayc_product.customer_price_regular,
    )
    bank_account_destination = get_or_create_bank_info_for_ayc_ewallet_transaction(
        loan, ayc_product, phone_number
    )
    return bank_account_destination.pk


def get_or_create_bank_info_for_ayc_ewallet_transaction(
    loan: Loan, ayc_product: AYCProduct, phone_number: str
) -> BankAccountDestination:
    """
    AYC needs name_bank_validation to create beneficiary_id.
    We need to fake NameBankValidation to run AYC flow.
    """
    bank_category = BankAccountCategory.objects.get(category=BankAccountCategoryConst.EWALLET)
    bank = Bank.objects.filter(bank_name=ayc_product.category).first()
    bank_account_destination = BankAccountDestination.objects.filter(
        account_number=phone_number,
        customer_id=loan.customer_id,
        bank_account_category_id=bank_category.pk,
        bank_id=bank.pk,
    ).last()
    if bank_account_destination:
        return bank_account_destination

    # create if not exist
    name_bank_validation = NameBankValidation.objects.create(
        bank_code=bank.bank_code,
        account_number=phone_number,
        name_in_bank=loan.customer.fullname,
        mobile_phone=loan.customer.phone,
        method=NameBankValidationVendors.XFERS,
        validation_status=NameBankValidationStatus.SUCCESS,
        reason="AYC E-wallet transaction",
    )
    return BankAccountDestination.objects.create(
        bank_account_category_id=bank_category.pk,
        customer_id=loan.customer_id,
        bank_id=bank.pk,
        account_number=name_bank_validation.account_number,
        name_bank_validation_id=name_bank_validation.pk,
    )


def get_payment_point_product(
    customer_id: int, transaction_method_id: int, loan_amount: int, payment_point_product_id: int
) -> tuple:
    """
    Fetches the appropriate e-wallet product for a transaction, supporting AYC, Xfers, and Sepulsa.
    Raises ProductNotFound if the product is not found or valid.
    """
    product = SepulsaProduct.objects.filter(pk=payment_point_product_id).last()
    if not product:
        raise ProductNotFound

    product = get_ayc_or_sepulsa_ewallet_product(product, customer_id, transaction_method_id)
    product = get_xfers_or_sepulsa_ewallet_product(product, customer_id, transaction_method_id)

    # for postpaid product we need amount from inquiry
    if product.category not in SepulsaProductCategory.POSTPAID:
        loan_amount = product.customer_price_regular

    return product, loan_amount


def get_ayc_or_sepulsa_ewallet_product(
    product: SepulsaProduct, customer_id: int, transaction_method_id: int
) -> Union[SepulsaProduct, AYCProduct]:
    """
    Determines if the product should be switched to an AYC product.
    """
    if is_applied_ayc_switching_flow(customer_id, transaction_method_id):
        ayo_product = AYCProduct.objects.filter(
            sepulsa_product_id=product.pk, is_active=True, category=product.category
        ).first()
        if ayo_product:
            product = ayo_product

    return product


def get_xfers_or_sepulsa_ewallet_product(
    product: SepulsaProduct, customer_id: int, transaction_method_id: int
) -> Union[SepulsaProduct, XfersProduct]:
    """
    Determines if the product should be switched to an Xfers product.
    """
    if (
        product.category in SepulsaProductCategory.xfers_ewallet_products()
        and is_applied_xfers_switching_flow(customer_id, transaction_method_id)
    ):
        xfers_product = XfersProduct.objects.filter(
            sepulsa_product_id=product.pk, is_active=True, category=product.category
        ).first()
        if xfers_product:
            product = xfers_product

    return product


def create_xfers_ewallet_transaction(loan: Loan, xfers_product: XfersProduct, phone_number: str):
    XfersEWalletTransaction.objects.create(
        loan_id=loan.pk,
        customer_id=loan.customer_id,
        xfers_product_id=xfers_product.pk,
        phone_number=phone_number,
        partner_price=xfers_product.partner_price,
        customer_price=xfers_product.customer_price,
        customer_price_regular=xfers_product.customer_price_regular,
    )


def get_xfers_ewallet_name_bank(
    account_number: str, customer_id: int, bank_category_id: int
) -> BankAccountDestination:
    return BankAccountDestination.objects.filter(
        account_number=account_number,
        customer_id=customer_id,
        bank_account_category_id=bank_category_id,
    ).first()


def validate_xfers_ewallet_bank_name_validation(loan: Loan) -> bool:
    """
    With DANA product in Xfers => we force PERMATA bank
    """
    phone_number = loan.xfers_ewallet_transaction.phone_number
    account_number = XfersEWalletConst.PREFIX_ACCOUNT_NUMBER + phone_number
    bank_category = BankAccountCategory.objects.get(category=BankAccountCategoryConst.EWALLET)
    bank = Bank.objects.filter(bank_name=XfersEWalletConst.PERMATA_BANK_NAME).first()

    # if validation_status == success => skip and update ops.loan.bank_account_destination_id
    bank_account_destination = get_xfers_ewallet_name_bank(
        account_number, loan.customer_id, bank_category.pk
    )
    if (
        bank_account_destination
        and bank_account_destination.name_bank_validation.validation_status
        == NameBankValidationStatus.SUCCESS
    ):
        loan.update_safely(bank_account_destination_id=bank_account_destination.pk)
        return True

    application = Application.objects.get(pk=loan.application_id2)
    name_bank_validation_id = (
        bank_account_destination.name_bank_validation_id if bank_account_destination else None
    )
    data_to_validate = {
        "bank_name": XfersEWalletConst.PERMATA_BANK_NAME,
        "account_number": account_number,
        "name_in_bank": '',
        "name_bank_validation_id": name_bank_validation_id,
        "mobile_phone": application.mobile_phone_1,
        "application": application,
    }
    is_success = False
    try:
        validation = trigger_name_in_bank_validation(
            data_to_validate, method=NameBankValidationVendors.XFERS, new_log=True
        )
        validation.validate(bypass_name_in_bank=True)
        is_success = validation.is_success()

    except XfersApiError as e:
        sentry_client = get_julo_sentry_client()
        sentry_client.captureException()
        logger.error(
            {
                'action': 'validate_xfers_ewallet_bank_name_validation_error',
                'error': str(e),
                'name_bank_validation': validation.name_bank_validation.id,
                'loan_id': loan.pk,
            }
        )

    name_bank_validation = validation.name_bank_validation
    bank_account_destination, _ = BankAccountDestination.objects.get_or_create(
        name_bank_validation_id=name_bank_validation.pk,
        defaults=dict(
            bank_account_category_id=bank_category.pk,
            customer_id=loan.customer_id,
            bank_id=bank.pk,
            account_number=name_bank_validation.account_number,
        ),
    )
    loan.update_safely(bank_account_destination_id=bank_account_destination.pk)

    return is_success


def xfers_ewallet_disbursement_process(loan: Loan):
    from juloserver.loan.services.lender_related import julo_one_disbursement_process

    logger.info({'action': 'xfers_ewallet_disbursement_process', 'loan_id': loan.pk})

    if not loan.bank_account_destination_id:
        is_success = validate_xfers_ewallet_bank_name_validation(loan)
        if not is_success:
            update_loan_status_and_loan_history(
                loan.id,
                new_status_code=LoanStatusCodes.TRANSACTION_FAILED,
                change_by_id=loan.customer.user_id,
                change_reason=LoanStatusChangeReason.INVALID_NAME_BANK_VALIDATION,
            )
            return

    julo_one_disbursement_process(loan)


def populate_xfers_or_ayc_ewallet_details(data: dict, loan: Loan):
    if loan.is_xfers_ewallet_transaction:
        ewallet_transaction = loan.xfers_ewallet_transaction
        ewallet_product = ewallet_transaction.xfers_product
    else:
        ewallet_transaction = AYCEWalletTransaction.objects.filter(loan_id=loan.pk).last()
        ewallet_product = ewallet_transaction.ayc_product

    data['topup_e_wallet'] = dict(
        product_category="Dompet Digital",
        product_kind=ewallet_product.product_name,
        price=ewallet_transaction.customer_price_regular,
        phone_number=ewallet_transaction.phone_number,
        type=ewallet_product.category,
        product_logo=get_ewallet_logo(ewallet_product.category),
    )


def get_ewallet_categories(customer_id: int) -> List[str]:
    """
    Get list of ewallet categories
    """
    # check if should apply ayconnect/xfers flow
    is_applied_ayc_flow = is_applied_ayc_switching_flow(
        customer_id=customer_id,
        transaction_method=TransactionMethodCode.DOMPET_DIGITAL.code,
    )
    is_applied_xfers_flow = is_applied_xfers_switching_flow(
        customer_id=customer_id,
        transaction_method=TransactionMethodCode.DOMPET_DIGITAL.code,
    )

    # get all categories
    categories = get_sepulsa_ewallet_categories()

    if is_applied_ayc_flow:
        categories += get_ayc_ewallet_categories()

    if is_applied_xfers_flow:
        categories += get_xfers_ewallet_categories()

    # make sure categories are unique
    categories = list(set(categories))

    return categories
