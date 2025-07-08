import logging

from django.db import transaction

from juloserver.julo.utils import format_mobile_phone
from juloserver.julo.models import (
    Application,
    ApplicationFieldChange
)
from juloserver.grab.utils import GrabUtils
from juloserver.grab.exceptions import GrabLogicException
from juloserver.grab.constants import (
    GrabErrorMessage,
    GrabErrorCodes,
    GrabBankValidationStatus
)
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.statuses import ApplicationStatusCodes, LoanStatusCodes
from juloserver.disbursement.services import (
    trigger_name_in_bank_validation
)
from juloserver.grab.tasks import trigger_name_bank_validation_grab
from juloserver.disbursement.models import (
    BankNameValidationLog,
    NameBankValidation,
    Loan
)
from juloserver.julo.banks import BankManager
from juloserver.grab.serializers import NameBankValidationStatusSerializer
from juloserver.customer_module.models import (
    BankAccountCategory,
    BankAccountDestination
)
from juloserver.disbursement.constants import NameBankValidationStatus


logger = logging.getLogger(__name__)


class GrabChangeBankAccountService(object):
    bank = None
    name_bank_validation = None

    def is_valid_application(self, application_id, customer):
        application = Application.objects.get_or_none(
            id=application_id,
            customer=customer
        )
        if not application:
            raise GrabLogicException(GrabUtils.create_error_message(
                GrabErrorCodes.GAX_ERROR_CODE.format('1'),
                GrabErrorMessage.BANK_VALIDATION_GENERAL_ERROR_MESSAGE))

        is_grab = application.workflow.name == WorkflowConst.GRAB
        is_eligible_for_update = application.application_status_id in {
            ApplicationStatusCodes.APPLICATION_DENIED,
            ApplicationStatusCodes.LOC_APPROVED
        }

        if not is_grab or not is_eligible_for_update:
            raise GrabLogicException(GrabUtils.create_error_message(
                GrabErrorCodes.GAX_ERROR_CODE.format('1'),
                GrabErrorMessage.BANK_VALIDATION_GENERAL_ERROR_MESSAGE))

        if application.application_status_id == ApplicationStatusCodes.LOC_APPROVED:
            is_have_loans = Loan.objects.filter(loan_status__in=[
                LoanStatusCodes.INACTIVE,
                LoanStatusCodes.LENDER_APPROVAL,
                LoanStatusCodes.FUND_DISBURSAL_ONGOING,
                LoanStatusCodes.MANUAL_FUND_DISBURSAL_ONGOING,
                LoanStatusCodes.FUND_DISBURSAL_FAILED,
            ], application=application).exists()

            if is_have_loans:
                raise GrabLogicException(GrabUtils.create_error_message(
                    GrabErrorCodes.GAX_ERROR_CODE.format('1'),
                    GrabErrorMessage.BANK_VALIDATION_HAS_LOANS_ACTIVE))

        return application, True

    def trigger_grab_name_bank_validation(self, application, bank_name, bank_account_number):
        base_logger = {
            "task": "trigger_grab_name_bank_validation",
            "application_id": application.id
        }

        logger.info({
            **base_logger,
            "status": "starting_service"
        })

        data_to_validate = {
            'name_bank_validation_id': None,
            'bank_name': bank_name,
            'account_number': bank_account_number,
            'name_in_bank': application.name_in_bank,
            'mobile_phone': format_mobile_phone(application.mobile_phone_1),
            'application': application
        }

        # actually this is not really the validation process
        # it's just create name bank validation entry
        # then return the class/object of ValidationProcess
        validation_process_obj = trigger_name_in_bank_validation(data_to_validate, new_log=True)
        # get name_bank_validation_id (the pk)
        name_bank_validation_id = validation_process_obj.get_id()

        # the actual trigger name bank validation
        # this also will create a log of BankNameValidationLog
        trigger_name_bank_validation_grab.delay(
            name_bank_validation_id,
            data_to_validate['name_in_bank'],
            data_to_validate['bank_name'],
            data_to_validate['account_number'],
            data_to_validate['mobile_phone'],
            application.id
        )

        # data preparation that will return to the user
        logger.info({
            **base_logger,
            "status": "ending_service"
        })

        data_to_validate.pop("application", None)
        data_to_validate['name_bank_validation_id'] = name_bank_validation_id
        data_to_validate['validation_status'] = GrabBankValidationStatus.IN_PROGRESS
        data_to_validate['application_status'] = application.application_status_id
        data_to_validate['bank_account_number'] = data_to_validate["account_number"]
        data_to_validate['bank_name'] = bank_name
        data_to_validate['application_id'] = application.id
        data_to_validate['validation_id'] = None
        data_to_validate['reason'] = None
        serializer = NameBankValidationStatusSerializer(data=data_to_validate)
        serializer.is_valid(raise_exception=True)
        return serializer.data

    # because there is no relation between application and name bank validation
    # we can only use the log to make sure the name bank validation is valid
    # we only process the last name bank validation
    def is_name_bank_validation_valid(self, name_bank_validation_id, application_id):
        name_bank_validation = NameBankValidation.objects.get_or_none(id=name_bank_validation_id)
        if not name_bank_validation:
            return None, False

        bank_name_validation_log = BankNameValidationLog.objects.filter(
            application_id=application_id).last()
        if not bank_name_validation_log:
            return None, False

        # validation id is not name_bank_validation_id
        # the validation comes from response['id'] (see ValidationProcess.validate)
        if bank_name_validation_log.validation_id != name_bank_validation.validation_id:
            return None, False

        self.name_bank_validation = name_bank_validation
        return name_bank_validation, True

    def get_name_bank_validation_status(self, name_bank_validation_id, application_id):
        name_bank_validation, is_valid = self.is_name_bank_validation_valid(
            name_bank_validation_id, application_id
        )

        if not is_valid:
            raise GrabLogicException(GrabUtils.create_error_message(
                GrabErrorCodes.GAX_ERROR_CODE.format('8'),
                GrabErrorMessage.GRAB_API_LOG_EXPIRED_FOR_PRE_DISBURSAL_CHECK))

        result = name_bank_validation.__dict__
        result.update({
            "name_bank_validation_id": name_bank_validation_id,
            "application_id": application_id,
            "bank_account_number": result["account_number"]
        })

        if name_bank_validation.validation_status == NameBankValidationStatus.INITIATED:
            result.update({
                "validation_status": GrabBankValidationStatus.IN_PROGRESS
            })

        bank = BankManager().get_by_method_bank_code(name_bank_validation.bank_code)
        if not bank:
            raise GrabLogicException(GrabUtils.create_error_message(
                GrabErrorCodes.GAX_ERROR_CODE.format('2'),
                GrabErrorMessage.BANK_VALIDATION_INCORRECT_ACCOUNT_NUMBER))
        else:
            result.update({
                "bank_name": bank.bank_name
            })

        serializer = NameBankValidationStatusSerializer(data=result)
        serializer.is_valid()
        self.bank = bank
        return serializer.data

    def update_bank_application(self, application, validation_status_data):
        with transaction.atomic():
            for field in ["name_bank_validation_id", "bank_name", "bank_account_number"]:
                ApplicationFieldChange.objects.create(
                    application=application,
                    field_name=field,
                    old_value=getattr(application, field),
                    new_value=validation_status_data.get(field)
                )

            try:
                application.name_bank_validation_id = validation_status_data["name_bank_validation_id"]
                application.bank_name = validation_status_data["bank_name"]
                application.bank_account_number = validation_status_data["bank_account_number"]
                application.save()
            except KeyError as err:
                return False, "key error: {}".format(str(err))
            return True, None

    def create_new_bank_destination(self, customer):
        if not self.bank:
            raise GrabLogicException(GrabUtils.create_error_message(
                GrabErrorCodes.GAX_ERROR_CODE.format('2'),
                GrabErrorMessage.BANK_VALIDATION_INCORRECT_ACCOUNT_NUMBER))

        if not self.name_bank_validation:
            raise GrabLogicException(GrabUtils.create_error_message(
                GrabErrorCodes.GAX_ERROR_CODE.format('8'),
                GrabErrorMessage.GRAB_API_LOG_EXPIRED_FOR_PRE_DISBURSAL_CHECK))

        # the bank account category is always pribadi for grab driver
        bank_account_category = BankAccountCategory.objects.get_or_none(category='self')
        if not bank_account_category:
            raise GrabLogicException("Invalid bank account category")

        BankAccountDestination.objects.create(
            bank_account_category=bank_account_category,
            customer=customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number=self.name_bank_validation.account_number
        )
