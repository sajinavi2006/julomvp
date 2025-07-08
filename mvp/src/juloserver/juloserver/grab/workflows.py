"""workflows.py"""

import logging
from django.db import transaction
from django.core.exceptions import MultipleObjectsReturned
from juloserver.julo.workflows import WorkflowAction
from juloserver.julo.utils import remove_current_user

from juloserver.customer_module.constants import BankAccountCategoryConst
from juloserver.customer_module.models import BankAccountCategory, BankAccountDestination

from juloserver.account.models import Account, AccountLimit

from juloserver.julo.models import Bank, CreditScore
from juloserver.julo.formulas.underwriting import compute_affordable_payment
from juloserver.account.services.credit_limit import (
    generate_credit_limit,
    store_related_data_for_generate_credit_limit,
    store_account_property,
    # update_related_data_for_generate_credit_limit
)
from juloserver.apiv2.services import check_iti_repeat
from juloserver.julo.constants import ApplicationStatusCodes, FeatureNameConst
from juloserver.account.services.account_related import process_change_account_status
from ..julo.services2.payment_method import generate_customer_va_for_julo_one

from juloserver.julo.services import (
    process_application_status_change)
from juloserver.account.constants import AccountConstant

from juloserver.application_flow.constants import JuloOneChangeReason
from juloserver.application_flow.services import JuloOneService, JuloOneByPass
from juloserver.grab.services.services import GrabLoanService
from juloserver.grab.models import GrabLoanInquiry, GrabCustomerData
from juloserver.grab.exceptions import GrabLogicException
from juloserver.julo.clients.xfers import XfersApiError
from juloserver.disbursement.services.xfers import XfersService
from juloserver.disbursement.services import get_validation_method
from juloserver.disbursement.models import NameBankValidation, BankNameValidationLog
from juloserver.disbursement.constants import NameBankValidationStatus, NameBankValidationVendors
from juloserver.grab.services.services import verify_grab_loan_offer
from juloserver.grab.tasks import grab_auto_apply_loan_task
from juloserver.grab.constants import (
    GRAB_ACCOUNT_LOOKUP_NAME,
    GRAB_MAX_CREDITORS_REACHED_ERROR_MESSAGE
)
from juloserver.disbursement.services import trigger_name_in_bank_validation
from juloserver.julo.utils import format_mobile_phone
from juloserver.grab.segmented_tasks.disbursement_tasks import (
    trigger_create_or_update_ayoconnect_beneficiary,
)
from juloserver.julo.workflows2.tasks import (
    send_grab_sms_status_change_131_task,
    send_grab_email_status_change_131_task
)
from juloserver.loan.services.loan_related import (
    get_parameters_fs_check_other_active_platforms_using_fdc,
    is_apply_check_other_active_platforms_using_fdc,
)
from juloserver.grab.services.loan_related import (
    is_dax_eligible_other_active_platforms
)

logger = logging.getLogger(__name__)


class GrabWorkflowAction(WorkflowAction):

    def process_bypass_grab_at_122(self):
        pass
        """bypass 122 for julo1"""
        remove_current_user()
        julo_one_service = JuloOneService()
        if check_iti_repeat(self.application.id) and \
                julo_one_service.check_affordability_julo_one(self.application):
            by_pass_service = JuloOneByPass()
            by_pass_service.bypass_julo_one_iti_122_to_124(self.application)

    def process_grab_at_190(self):
        account = Account.objects.filter(
            customer=self.application.customer).last()
        if not account:
            logger.info({
                'action': 'julo one update account to active at 190',
                'application_id': self.application.id,
                'message': 'Account Not Found'
            })
            return

        with transaction.atomic():
            process_change_account_status(
                account,
                AccountConstant.STATUS_CODE.active,
                change_reason="Grab application approved",
            )
            account_limit = AccountLimit.objects.filter(account=account).last()
            if not account_limit:
                logger.info({
                    'action': 'julo one update account limit available limit',
                    'application_id': self.application.id,
                    'message': 'Account Limit Not Found'
                })
                return
            account_limit.update_safely(available_limit=account_limit.set_limit)
            # try:
            #     check_referral_cashback_julo_one(self.application)
            # except MultipleObjectsReturned as e:
            #     logger.warning('Process for julo one at 190 status error | error_message=%s' % e)
            #     sentry_client = get_julo_sentry_client()
            #     sentry_client.captureException()

    def verify_loan_offer(self):
        verify_loan_flag = verify_grab_loan_offer(self.application)
        if not verify_loan_flag:
            with transaction.atomic():
                process_application_status_change(
                    self.application.id,
                    ApplicationStatusCodes.APPLICATION_DENIED,
                    'loan_offer_no_longer_active',
                    'No active Loan Offer for this Customer'
                )
        return verify_loan_flag


    def process_affordability_calculation(self):
        app_sonic = self.application.applicationhistory_set.filter(
            change_reason=JuloOneChangeReason.SONIC_AFFORDABILITY)
        if app_sonic:
            return
        julo_one_service = JuloOneService()
        input_params = julo_one_service.construct_params_for_affordability(self.application)
        compute_affordable_payment(**input_params)

    def process_credit_limit_generation(self):
        # max_limit, set_limit = generate_credit_limit(self.application)
        #
        # if max_limit >= 0:

        # Store related data
        account = self.application.customer.account_set.filter(
            account_lookup__name=GRAB_ACCOUNT_LOOKUP_NAME).last()
        if not account:
            store_related_data_for_generate_credit_limit(self.application, 0, 0)
            self.application.refresh_from_db()

            # generate account_property and history
            store_account_property(self.application, 0)
            # else:
            #     update_related_data_for_generate_credit_limit(self.application,
            #                                                   max_limit,
            #                                                   set_limit)
        # else:
        #     new_status_code = ApplicationStatusCodes.OFFER_DECLINED_BY_CUSTOMER
        #     change_reason = 'Credit limit generation failed'

        self.application.refresh_from_db()

    def populate_bank_account_destination(self):
        category = BankAccountCategory.objects.get(category=BankAccountCategoryConst.SELF)
        bank = Bank.objects.get(bank_name__iexact=self.application.bank_name)

        BankAccountDestination.objects.create(
            bank_account_category=category,
            customer=self.application.customer,
            bank=bank,
            account_number=self.application.bank_account_number,
            name_bank_validation=self.application.name_bank_validation
        )

    def generate_payment_method(self):
        generate_customer_va_for_julo_one(self.application)

    def process_documents_resubmission_action_j1(self):
        if self.old_status_code is not ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR:
            self.application.is_document_submitted = False
            self.application.save()

    def create_grab_loan(self):
        application = self.application
        grab_customer_data = GrabCustomerData.objects.get_or_none(customer=application.customer)
        if not grab_customer_data:
            raise GrabLogicException("Grab Customer Not Found")
        grab_loan_inquiry = GrabLoanInquiry.objects.filter(
            grab_customer_data=grab_customer_data).last()
        if not grab_loan_inquiry:
            raise GrabLogicException("Grab Loan Inquiry Not Found")
        grab_loan_data = grab_loan_inquiry.grabloandata_set.last()
        if not grab_loan_inquiry:
            raise GrabLogicException("Grab Loan Data Not Found")
        customer = grab_customer_data.customer
        program_id = grab_loan_inquiry.program_id
        tenure = grab_loan_data.selected_tenure
        user = customer.user
        loan_amount = grab_loan_data.selected_amount
        grab_auto_apply_loan_task.apply_async(
            (customer.id, program_id, application.id), countdown=30
        )

    def change_status_130_to_141(self):
        process_application_status_change(
            self.application.id,
            ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
            "Offer auto-accepted by system"
        )

    def change_status_141_to_150(self):
        process_application_status_change(
            self.application.id,
            ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING,
            "Credit approved"
        )

    def update_grab_limit(self):
        new_status_code = ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER
        change_reason = 'Credit limit generated'

        account = self.application.account
        if account:
            grab_customer = GrabCustomerData.objects.filter(customer=self.application.customer).last()
            if grab_customer:
                grab_loan_inquiry = GrabLoanInquiry.objects.filter(grab_customer_data=grab_customer).last()
                account_limit = AccountLimit.objects.filter(account=account).last()
                account_limit.max_limit = grab_loan_inquiry.max_loan_amount
                account_limit.available_limit = grab_loan_inquiry.max_loan_amount
                account_limit.set_limit = grab_loan_inquiry.max_loan_amount
                account_limit.save()
        if self.application.application_status_id != new_status_code:
            process_application_status_change(
                self.application.id,
                new_status_code,
                change_reason=change_reason
            )

    def process_grab_validate_bank(self):
        method = get_validation_method(self.application)
        bank = Bank.objects.filter(bank_name=self.application.bank_name).last()
        name_bank_validation = NameBankValidation(
            bank_code=bank.xfers_bank_code,
            account_number=self.application.bank_account_number,
            mobile_phone=self.application.mobile_phone_1,
            method=method
        )
        xfers_service = XfersService()
        response_validate = xfers_service.validate(name_bank_validation)
        BankNameValidationLog.objects.create(
            account_number=self.application.bank_account_number,
            method=method,
            application=self.application,
            validation_id=response_validate['id'],
            validation_status=response_validate['status'],
            validated_name=response_validate['validated_name'],
            reason=response_validate['reason'],
        )

        if response_validate['reason'].lower() == NameBankValidationStatus.SUCCESS.lower():
            self.application.update_safely(name_in_bank=response_validate['validated_name'])
            self.application.refresh_from_db()

    def process_grab_bank_validation_v2(self, force_validate=False, new_data=None):
        application = self.application
        is_grab = application.is_grab()
        if not is_grab:
            raise GrabLogicException("INVALID GRAB APPLICATION - FAILED BANK VALIDATION")

        name_bank_validation_id = application.name_bank_validation_id

        data_to_validate = {'name_bank_validation_id': name_bank_validation_id,
                            'bank_name': application.bank_name,
                            'account_number': application.bank_account_number,
                            'name_in_bank': application.name_in_bank,
                            'mobile_phone': application.mobile_phone_1,
                            'application': application
                            }
        if new_data:
            data_to_validate['name_in_bank'] = new_data['name_in_bank']
            data_to_validate['bank_name'] = new_data['bank_name']
            data_to_validate['account_number'] = new_data['bank_account_number']
            data_to_validate['name_bank_validation_id'] = None
            if is_grab:
                data_to_validate['mobile_phone'] = format_mobile_phone(application.mobile_phone_1)
        validation = NameBankValidation.objects.get_or_none(pk=name_bank_validation_id)

        # checking is validation is not success already
        if validation is None or validation.validation_status != NameBankValidationStatus.SUCCESS \
                or force_validate:
            validation = trigger_name_in_bank_validation(data_to_validate, new_log=True)
            validation_id = validation.get_id()
            application.update_safely(name_bank_validation_id=validation_id)
            if (
                is_grab
                and validation.name_bank_validation.method
                == NameBankValidationVendors.PAYMENT_GATEWAY
            ):
                validation.validate_grab()
            else:
                validation.validate()
            validation_data = validation.get_data()
            if not validation.is_success():
                if validation_data['attempt'] >= 3:
                    validation_data['go_to_175'] = True
                if application.status == ApplicationStatusCodes.LOC_APPROVED:
                    logger.warning('Julo one name bank validation error | application_id=%s, '
                                   'validation_data=%s' % (application.id, validation_data))
                    return

                process_application_status_change(
                    application.id,
                    ApplicationStatusCodes.NAME_VALIDATE_FAILED,
                    'name_bank_validation_failed'
                )
                return
            else:
                # update application with new verified BA
                application.update_safely(
                    bank_account_number=validation_data['account_number'],
                    name_in_bank=validation_data['validated_name'],
                )
                if application.status != ApplicationStatusCodes.LOC_APPROVED:
                    process_application_status_change(
                        self.application.id,
                        ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
                        "system_triggered"
                    )
        else:
            # update table with new verified BA
            application.update_safely(
                bank_account_number=validation.account_number,
                name_in_bank=validation.validated_name,
            )
            if application.status != ApplicationStatusCodes.LOC_APPROVED:
                process_application_status_change(
                    self.application.id,
                    ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
                    "system_triggered"
                )

    def generate_grab_credit_score(self):
        try:
            obj, created = CreditScore.objects.get_or_create(
                application_id=self.application.id,
                defaults={'score': 'B-'})
        except Exception as err:
            logger.exception({
                'action': 'generate_grab_credit_score',
                'application_id': self.application.id,
                'message': str(err)
            })

    def trigger_ayoconnect_beneficiary(self):
        trigger_create_or_update_ayoconnect_beneficiary.apply_async(
            (self.application.customer_id,), countdown=10)

    def send_grab_sms_status_change_131(self):
        send_grab_sms_status_change_131_task.delay(self.application.id)

    def send_grab_email_status_change_131(self):
        send_grab_email_status_change_131_task.delay(
            self.application.id
        )

    def request_fdc_data(self):
        # if grab application stuck at 150 because fdc data out date and pending
        # the handler will call this function to request fdc data again to fdc server
        from juloserver.grab.services.loan_related import (
            create_fdc_inquiry_and_execute_check_active_loans_for_grab
        )
        from juloserver.loan.constants import FDCUpdateTypes

        parameters = get_parameters_fs_check_other_active_platforms_using_fdc(
            feature_name=FeatureNameConst.GRAB_3_MAX_CREDITORS_CHECK
        )
        outdated_threshold_days = parameters['fdc_data_outdated_threshold_days']
        number_allowed_platforms = parameters['number_of_allowed_platforms']

        params = dict(
            application_id=self.application.pk,
            loan_id=None,
            fdc_data_outdated_threshold_days=outdated_threshold_days,
            number_of_allowed_platforms=number_allowed_platforms,
            fdc_inquiry_api_config=parameters['fdc_inquiry_api_config'],
        )

        create_fdc_inquiry_and_execute_check_active_loans_for_grab(
            customer=self.application.customer,
            params=params,
            update_type=FDCUpdateTypes.GRAB_STUCK_150
        )

    def is_max_creditors_reached(self):
        parameters = get_parameters_fs_check_other_active_platforms_using_fdc(
            feature_name=FeatureNameConst.GRAB_3_MAX_CREDITORS_CHECK
        )

        if parameters is None:
            return {
                "is_eligible": True,
                "is_fdc_exists": True
            }

        result = {}
        if is_apply_check_other_active_platforms_using_fdc(self.application.id,
                                                           parameters=parameters):
            is_eligible_dict = is_dax_eligible_other_active_platforms(
                application_id=self.application.id,
                fdc_data_outdated_threshold_days=parameters['fdc_data_outdated_threshold_days'],
                number_of_allowed_platforms=parameters['number_of_allowed_platforms'],
                is_grab=True
            )

            if not is_eligible_dict.get("is_eligible"):
                result.update({"is_max_creditors_reached": True})

            result.update(**is_eligible_dict)

        return result

    def change_status_150_to_180(self):
        process_application_status_change(
            self.application.id,
            ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
            GRAB_MAX_CREDITORS_REACHED_ERROR_MESSAGE.format(3)
        )
