from django.db import transaction
import semver
from juloserver.customer_module.models import BankAccountDestination
from juloserver.customer_module.models import BankAccountCategory
from juloserver.julo.models import Application, Bank
from juloserver.disbursement.models import NameBankValidation
from juloserver.application_flow.workflows import JuloOneWorkflowAction
from juloserver.disbursement.services import trigger_name_in_bank_validation
from juloserver.disbursement.constants import NameBankValidationStatus
from juloserver.sdk.constants import (
    PARTNER_PEDE,
)


# please use only on changing for primary bank account
# you can change it if this customer didn't have disbursement record on that bank account
# make sure to finops team, and you can change it only if this customer failed in xfers disbursement
def _change_bank_account_number(application_id, account_number, bank_id):
    with transaction.atomic():
        application = Application.objects.get(pk=application_id)
        bank = Bank.objects.get(pk=bank_id)
        application.update_safely(
            name_bank_validation=None, bank_name=bank.bank_name, bank_account_number=account_number
        )
        _manual_process_validate_bank(application)
        application.refresh_from_db()
        category = BankAccountCategory.objects.get(category='self')
        BankAccountDestination.objects.create(
            bank_account_category=category,
            customer=application.customer,
            bank=bank,
            account_number=application.bank_account_number,
            name_bank_validation=application.name_bank_validation,
        )
        return "Add new bank success"


# use to manually validate bank to xfers
# set force validate if previous validation is success
def _manual_process_validate_bank(application, is_experiment=None, force_validate=False):
    application.refresh_from_db()
    is_julo_one = application.is_julo_one()
    is_old_version = True
    loan = None
    if application.app_version:
        is_old_version = semver.match(
            application.app_version, NameBankValidationStatus.OLD_VERSION_APPS
        )

    if is_julo_one:
        name_bank_validation_id = application.name_bank_validation_id
    else:
        if hasattr(application, "loan"):
            loan = application.loan
            name_bank_validation_id = loan.name_bank_validation_id
        else:
            name_bank_validation_id = application.name_bank_validation_id

    data_to_validate = {
        'name_bank_validation_id': name_bank_validation_id,
        'bank_name': application.bank_name,
        'account_number': application.bank_account_number,
        'name_in_bank': application.name_in_bank,
        'mobile_phone': application.mobile_phone_1,
        'application': application,
    }
    validation = NameBankValidation.objects.get_or_none(pk=name_bank_validation_id)
    # checking is validation is not success already
    if (
        validation is None
        or validation.validation_status != NameBankValidationStatus.SUCCESS
        or force_validate
    ):
        validation = trigger_name_in_bank_validation(data_to_validate, new_log=True)
        validation_id = validation.get_id()
        if not is_julo_one and loan is not None:
            loan.name_bank_validation_id = validation_id
            loan.save(update_fields=['name_bank_validation_id'])
        application.update_safely(name_bank_validation_id=validation_id)
        validation.validate()
        validation_data = validation.get_data()
        if not validation.is_success():
            if (
                (is_old_version and not is_experiment)
                or validation_data['attempt'] >= 3
                or PARTNER_PEDE == application.partner_name
            ):
                validation_data['go_to_175'] = True
            if is_julo_one:
                return False

        else:
            # update table with new verified BA
            application.update_safely(
                bank_account_number=validation_data['account_number'],
                name_in_bank=validation_data['validated_name'],
            )
            return True

    else:
        # update table with new verified BA
        application.update_safely(
            bank_account_number=validation.account_number,
            name_in_bank=validation.validated_name,
        )
        return True


def _do_force_validate_with_new_account_number(app_id, account_number=None, bank_id=None):
    app = Application.objects.get(pk=app_id)
    nbv = NameBankValidation.objects.get(pk=app.name_bank_validation_id)
    if account_number is None:
        account_number = app.bank_account_number
    if bank_id is None:
        bank_id = Bank.objects.filter(xfers_bank_code=nbv.bank_code).last().id

    _change_bank_account_number(app_id, account_number, bank_id)


def force_validate_with_new_account_number(app_id, account_number=None, bank_id=None):
    _do_force_validate_with_new_account_number(app_id, account_number, bank_id)


def trigger_process_validate_bank(app_ids):

    for app_id in app_ids:
        with transaction.atomic():
            try:
                app = Application.objects.get(pk=app_id)
                last_app = Application.objects.filter(customer_id=app.customer_id).last()
                if last_app.id == app.id:
                    input = JuloOneWorkflowAction(app, None, None, None, None)
                    input.process_validate_bank()
            except Exception as e:
                return str(e)


def check_trigger_process_validate_bank(app_ids):
    result = {}
    for app_id in app_ids:
        result[app_id] = []

    for app_id in app_ids:
        app = Application.objects.get(pk=app_id)
        if app.name_bank_validation_id is None:
            result[app_id].append("need to fix! null name bank validation")
        else:
            result[app_id].append("correct! status is not 175")

    return result


def find_trigger_process_validate_bank():
    apps = Application.objects.filter(application_status__lt=105, name_bank_validation_id=None)
    result = ""
    for app in apps:
        result += str(app.id) + ","
    return result
