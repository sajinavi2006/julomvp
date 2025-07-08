import logging
from django.utils import timezone
from celery import task

from juloserver.customer_module.models import BankAccountDestination
from juloserver.disbursement.constants import (
    DisbursementVendors,
    DisbursementStatus,
    AyoconnectErrorReason,
)
from juloserver.disbursement.models import Disbursement
from juloserver.disbursement.exceptions import AyoconnectServiceError
from juloserver.disbursement.services import (
    AyoconnectService,
    create_disbursement_history_ayoconnect,
)
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting, Customer, ApplicationFieldChange, Loan, Bank
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import ApplicationStatusCodes, LoanStatusCodes

logger = logging.getLogger(__name__)


@task(queue="grab_global_queue")
def trigger_create_or_update_ayoconnect_beneficiary(customer_id, update_phone=False):
    from juloserver.loan.services.loan_related import update_loan_status_and_loan_history
    from juloserver.loan.tasks import ayoconnect_loan_disbursement_retry

    pg_ratio_feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.GRAB_PAYMENT_GATEWAY_RATIO, is_active=True
    ).first()

    if not pg_ratio_feature_setting:
        return

    if not pg_ratio_feature_setting.parameters:
        return

    ayoconnect_ratio_str = pg_ratio_feature_setting.parameters.get("ac_ratio")
    ayoconnect_ratio_float = float(ayoconnect_ratio_str.strip('%')) / 100
    if ayoconnect_ratio_float <= 0:
        return

    today_date = timezone.localtime(timezone.now()).date()
    customer_qs = Customer.objects.get_or_none(pk=customer_id)
    if not customer_qs:
        logger.info(
            {
                "action": "trigger_create_or_update_ayoconnect_beneficiary",
                "customer_id": customer_id,
                "message": "Customer doesn't exist for customer_id {}".format(customer_id),
            }
        )
        return

    last_active_app = customer_qs.application_set.filter(
        application_status_id=ApplicationStatusCodes.LOC_APPROVED,
        product_line_id=ProductLineCodes.GRAB,
    ).last()
    if not last_active_app:
        logger.info(
            {
                "action": "trigger_create_or_update_ayoconnect_beneficiary",
                "customer_id": customer_id,
                "message": "Customer doesn't have active GRAB application",
            }
        )
        return

    old_phone_number = customer_qs.phone
    new_phone_number = customer_qs.phone

    if update_phone:
        app_field_change = ApplicationFieldChange.objects.filter(
            application=last_active_app, field_name='mobile_phone_1', cdate__date=today_date
        ).last()
        if app_field_change:
            old_phone_number = app_field_change.old_value
            new_phone_number = app_field_change.new_value

    if not last_active_app.name_bank_validation_id:
        logger.info(
            {
                "action": "trigger_create_or_update_ayoconnect_beneficiary",
                "customer_id": customer_id,
                "application": last_active_app.id,
                "message": "Customer doesn't have active GRAB application with name bank validation",
            }
        )
        return

    name_bank_validation_id = last_active_app.name_bank_validation_id
    bank_account_dest = BankAccountDestination.objects.filter(
        customer_id=customer_id, name_bank_validation_id=name_bank_validation_id
    ).last()

    if not bank_account_dest:
        logger.info(
            {
                "action": "trigger_create_or_update_ayoconnect_beneficiary",
                "customer_id": customer_id,
                "name_bank_validation_id": name_bank_validation_id,
                "message": "Customer doesn't have bank account destination",
            }
        )
        return

    account_number = bank_account_dest.account_number
    bank = Bank.objects.get(pk=bank_account_dest.bank_id)

    ayo_service = AyoconnectService()
    ayoconnect_bank = ayo_service.get_payment_gateway_bank(bank_id=bank.id)
    if not ayoconnect_bank:
        logger.info(
            {
                "action": "trigger_create_or_update_ayoconnect_beneficiary",
                "customer_id": customer_id,
                "account_number": account_number,
                "message": "payment_gateway_bank doesn't exist for bank with id {}".format(
                    bank_account_dest.bank_id
                ),
            }
        )
        return
    swift_bank_code = ayoconnect_bank.swift_bank_code
    try:
        loan_id = None
        disbursement_id = None
        loan = Loan.objects.filter(customer_id=customer_id).values('id', 'disbursement_id').last()
        if loan:
            loan_id = loan.get('id')
            disbursement_id = loan.get('disbursement_id')

        logger.info(
            {
                "action": "trigger_create_or_update_ayoconnect_beneficiary",
                "customer_id": customer_id,
                "application_id": last_active_app.id,
                "account_number": account_number,
                "swift_bank_code": swift_bank_code,
                "new_phone_number": new_phone_number,
                "old_phone_number": old_phone_number,
                "loan_id": loan_id,
                "disbursement_id": disbursement_id,
            }
        )
        ayo_service.create_or_update_beneficiary(
            customer_id,
            last_active_app.id,
            account_number,
            swift_bank_code,
            new_phone_number,
            old_phone_number,
        )
    except AyoconnectServiceError as err:
        logger.info(
            {
                "action": "trigger_create_or_update_ayoconnect_beneficiary",
                "customer_id": customer_id,
                "account_number": account_number,
                "message": err,
            }
        )

        # if an error happens when triggering Ayoconnect beneficiary
        # check, if the customer has a loan
        # check, is it Ayoconnect or not
        last_loan = Loan.objects.filter(customer_id=customer_id).last()
        if not last_loan:
            logger.info(
                {
                    "action": "trigger_create_or_update_ayoconnect_beneficiary",
                    "customer_id": customer_id,
                    "account_number": account_number,
                    "message": "customer does not have a loan",
                }
            )
            return
        if not last_loan.disbursement_id:
            logger.info(
                {
                    "action": "trigger_create_or_update_ayoconnect_beneficiary",
                    "customer_id": customer_id,
                    "account_number": account_number,
                    "message": "customer does not have a disbursement",
                }
            )
            return

        if not last_loan.is_ongoing_grab_loan:
            logger.info(
                {
                    "action": "trigger_create_or_update_ayoconnect_beneficiary",
                    "customer_id": customer_id,
                    "account_number": account_number,
                    "message": "customer does not have a ongoing (212) grab loan",
                }
            )
            return

        disbursement_id = last_loan.disbursement_id
        disbursement = Disbursement.objects.get_or_none(id=disbursement_id)

        if disbursement and disbursement.method == DisbursementVendors.AYOCONNECT:
            update_fields = ['disburse_status', 'reason', 'retry_times']
            disbursement.disburse_status = DisbursementStatus.FAILED
            disbursement.reason = AyoconnectErrorReason.ERROR_BENEFICIARY_REQUEST
            disbursement.retry_times += 3
            disbursement.save(update_fields=update_fields)
            disbursement.create_history('update_status', update_fields)
            create_disbursement_history_ayoconnect(disbursement)

            last_loan.refresh_from_db()
            update_loan_status_and_loan_history(
                last_loan.id,
                new_status_code=LoanStatusCodes.FUND_DISBURSAL_FAILED,
                change_reason=AyoconnectErrorReason.ERROR_BENEFICIARY_REQUEST,
            )
            ayoconnect_loan_disbursement_retry(loan_id=last_loan.id, max_retries=3)
