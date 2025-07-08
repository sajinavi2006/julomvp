import re

from django.db import transaction
from django.utils import timezone

from juloserver.customer_module.constants import BankAccountCategoryConst
from juloserver.customer_module.models import (
    BankAccountCategory,
    BankAccountDestination,
)
from juloserver.disbursement.constants import NameBankValidationStatus
from juloserver.disbursement.models import NameBankValidation
from juloserver.disbursement.services import get_name_bank_validation_process_by_id
from juloserver.julo.banks import BankManager
from juloserver.julo.models import (
    ApplicationFieldChange,
    ApplicationNote,
    Bank,
    FeatureSetting,
    Application,
)
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.workflows import WorkflowAction
from juloserver.julolog.julolog import JuloLog

juloLogger = JuloLog()


class BankValidationError(Exception):
    pass


def validate_bank(application, data):
    """

    :param application:
    :param data:
         :data name_bank_validation_id
         :data validation_method
         :data bank_name
         :data bank_account_number
         :data name_in_bank
    :return:
    """

    from juloserver.grab.services.services import process_grab_bank_validation_v2

    # Do some validation first
    if not data['bank_account_number'].isnumeric():
        raise BankValidationError("Bank account number should contain only numbers")
    if not data['name_bank_validation_id']:
        raise BankValidationError("name_bank_validation_id is None")
    if data['bank_name']:
        bank_entry = BankManager.get_by_name_or_none(data['bank_name'])
        if not bank_entry:
            raise BankValidationError("bank %s not in the bank list" % data['bank_name'])

    name_bank_validation_id = int(data['name_bank_validation_id'])
    validation = get_name_bank_validation_process_by_id(name_bank_validation_id)

    with transaction.atomic():
        if data['validation_method']:
            new_method = data['validation_method']
            old_method = validation.get_method()
            if new_method != old_method:
                validation.change_method(new_method)
                note = 'change name bank validation method from %s to %s' % (old_method, new_method)
                ApplicationNote.objects.create(application_id=application.id, note_text=note)

        for field in ['bank_name', 'bank_account_number', 'name_in_bank']:
            new_value = data[field]
            old_value = getattr(application, field)
            if new_value != old_value:
                application.update_safely(**{field: new_value})
                note = 'change %s from %s to %s' % (field, old_value, new_value)
                ApplicationNote.objects.create(application_id=application.id, note_text=note)
                ApplicationFieldChange.objects.create(
                    application=application,
                    field_name=field,
                    old_value=old_value,
                    new_value=new_value,
                )

    workflow_action = WorkflowAction(
        application=application,
        new_status_code=application.application_status,
        old_status_code=application.application_status,
        change_reason='',
        note='',
    )

    if (
        application.is_julo_one() or application.is_grab()
    ) and application.status == ApplicationStatusCodes.LOC_APPROVED:

        if not application.is_grab():
            workflow_action.process_validate_bank(force_validate=True, new_data=data)
        else:
            process_grab_bank_validation_v2(
                workflow_action.application.id, force_validate=True, new_data=data
            )

        if application.name_bank_validation.validation_status == NameBankValidationStatus.SUCCESS:
            application.update_safely(
                bank_name=data['bank_name'],
                bank_account_number=data['bank_account_number'],
                name_in_bank=data['name_in_bank'],
            )
            category = BankAccountCategory.objects.get(category=BankAccountCategoryConst.SELF)
            bank = Bank.objects.get(bank_name__iexact=data["bank_name"])
            bank_account_destination = BankAccountDestination.objects.create(
                bank_account_category=category,
                customer=application.customer,
                bank=bank,
                account_number=data["bank_account_number"],
                name_bank_validation=application.name_bank_validation,
            )

            if application.is_grab():
                application.account.loan_set.last().update_safely(
                    bank_account_destination=bank_account_destination
                )
    elif (
        application.is_julover()
        and application.status == ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER
    ):
        from juloserver.julovers.workflows import JuloverWorkflowAction

        julover_workflow_action = JuloverWorkflowAction(
            application, application.application_status, '', '', application.application_status
        )
        julover_workflow_action.process_bank_validation()
    else:
        workflow_action.process_validate_bank(force_validate=True)


def remove_prefix(name):

    regex = r"^\s*((mr|mrs|ms|bpk|bapak|ibu|sdr|sdri|sdra|dr|prof)+(\W|\d)+)+"
    if isinstance(name, str):
        name = re.sub(regex, "", name, flags=re.IGNORECASE)
    return name


def remove_non_alphabet(name):
    regex = r"\W+"
    if isinstance(name, str):
        name = re.sub(regex, "", name, flags=re.IGNORECASE)
    return name


def preprocess_name(name):
    """Preprocess string to get the correct result"""
    if name is None:
        juloLogger.warning({"msg": "Preprocessing name failed with null value"})
        return ""

    name = name.lower().strip()
    name = remove_prefix(name)
    name = remove_non_alphabet(name)
    return name


def has_levenshtein_distance_similarity(application, name_bank_validation, setting=None) -> bool:
    from Levenshtein import distance
    from juloserver.application_flow.models import LevenshteinLog

    juloLogger.info(
        {
            "msg": "has_levenshtein_distance_similarity starting",
            "application_id": application.id,
            "status": application.status,
        }
    )

    if name_bank_validation is None:
        juloLogger.info(
            {
                "msg": "has_levenshtein_distance_similarity name_bank_validation is None",
                "application_id": application.id,
                "status": application.status,
            }
        )

        return False

    if setting is None:
        setting = FeatureSetting.objects.filter(
            feature_name="bank_validation", is_active=True
        ).last()
    if not setting:
        juloLogger.warning(
            {
                "msg": "check_bank_name_similarity no Levenshtein feature setting",
                "application_id": application.id,
            }
        )

        return False

    log = LevenshteinLog.objects.create(application=application, start_sync_at=timezone.now())

    juloLogger.info(
        {
            "msg": "Trying to preprocess input",
            "application": application.id,
            "name_validation_status": name_bank_validation.validation_status,
            "name_in_bank": name_bank_validation.name_in_bank,
            "validated_name": name_bank_validation.validated_name,
        }
    )

    inputted_name = preprocess_name(name_bank_validation.name_in_bank)
    validated_name = preprocess_name(name_bank_validation.validated_name)
    name_logs = {
        "inputted_name": {"original": name_bank_validation.name_in_bank, "cleanup": inputted_name},
        "validated_name": {
            "original": name_bank_validation.validated_name,
            "cleanup": validated_name,
        },
    }
    if inputted_name == validated_name:
        juloLogger.info(
            {
                "msg": "has_levenshtein_distance_similarity Pass cleanup",
                "application_id": application.id,
                "status": application.status,
            }
        )

        force_levenshtein_success(application, name_bank_validation, validated_name)

        log.calculation = name_logs
        log.end_sync_at = timezone.now()
        log.is_passed = True
        log.end_reason = "Preprocess name all clean."
        log.save()

        return True

    threshold = float(setting.parameters['similarity_threshold'])

    # Do levenshtein logic here
    distance_num = distance(inputted_name, validated_name)
    character_length = len(inputted_name)
    juloLogger.info(
        {
            "msg": "has_levenshtein_distance_similarity has distance",
            "value": (distance_num / character_length),
            "application_id": application.id,
            "status": application.status,
        }
    )

    is_passed = distance_num / character_length <= threshold
    distance_logs = {
        "distance_num": distance_num,
        "input_character_length": character_length,
        "threshold": threshold,
        "ratio": distance_num / character_length,
    }

    log.calculation = {**distance_logs, **name_logs}

    if is_passed:
        juloLogger.info({"application_id": application.id, "msg": "Pass real Levenshtein"})
        force_levenshtein_success(application, name_bank_validation, validated_name)

    log.end_sync_at = timezone.now()
    log.is_passed = is_passed
    log.end_reason = "Levenshtein distance calculated"
    log.save()

    return is_passed


def force_levenshtein_success(
    application: Application, name_bank_validation: NameBankValidation, validated_name: str
):
    from juloserver.disbursement.models import BankNameValidationLog

    with transaction.atomic():
        BankNameValidationLog.objects.create(
            application=application,
            validation_id=name_bank_validation.validation_id,
            validation_status=NameBankValidationStatus.SUCCESS,
            validated_name=validated_name,
            account_number=name_bank_validation.account_number,
            reason="levenshtein success",
            method="Levenshtein",
            validation_status_old=name_bank_validation.validation_status,
        )
        name_bank_validation.update_safely(validation_status=NameBankValidationStatus.SUCCESS)
