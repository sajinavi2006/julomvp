import json
import logging
import math
import os
import re
import tempfile
import random
from typing import Tuple

import pdfkit
from babel.dates import format_date
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Prefetch
from django.db.utils import IntegrityError
from django.template import Context
from django.template.loader import render_to_string
from django.utils import timezone

from juloserver.account.constants import (
    AccountConstant,
    TransactionType,
)
from juloserver.account.models import (
    Account,
    AccountLimit,
    AccountLookup,
    AccountProperty,
    CreditLimitGeneration,
    AccountLimitHistory,
)
from juloserver.account.services.account_related import is_new_loan_part_of_bucket5
from juloserver.account.services.credit_limit import (
    get_credit_matrix,
    get_is_proven,
    get_proven_threshold,
    get_salaried,
    get_transaction_type,
    get_voice_recording,
    is_inside_premium_area,
    store_account_property_history,
    store_credit_limit_generated,
    store_related_data_for_generate_credit_limit,
    update_available_limit,
    update_related_data_for_generate_credit_limit,
)
from juloserver.ana_api.models import FDCPlatformCheckBypass
from juloserver.apiv2.models import AutoDataCheck
from juloserver.apiv2.serializers import ApplicationUpdateSerializer
from juloserver.apiv2.services import (
    remove_fdc_binary_check_that_is_not_in_fdc_threshold,
)
from juloserver.application_flow.workflows import JuloOneWorkflowAction
from juloserver.customer_module.constants import BankAccountCategoryConst
from juloserver.customer_module.models import (
    BankAccountCategory,
    BankAccountDestination,
)
from juloserver.disbursement.constants import NameBankValidationStatus
from juloserver.fdc.constants import FDCLoanStatus
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.exceptions import JuloInvalidStatusChange
from juloserver.julo.formulas import round_rupiah
from juloserver.julo.models import (
    AffordabilityHistory,
    Application,
    ApplicationHistory,
    Bank,
    Customer,
    CreditScore,
    Device,
    Document,
    FDCActiveLoanChecking,
    FDCInquiry,
    FDCInquiryLoan,
    FDCRejectLoanTracking,
    FeatureSetting,
    Loan,
    Partner,
    Payment,
    PaymentMethod,
    StatusLookup,
    Workflow,
    WorkflowStatusPath, ProductLine,
)

from juloserver.julo.services import (
    ApplicationHistoryUpdated,
    process_application_status_change,
    update_customer_data,
)
from juloserver.julo.services2.payment_method import generate_customer_va_for_julo_one
from juloserver.julo.statuses import (
    ApplicationStatusCodes,
    LoanStatusCodes,
    PaymentStatusCodes,
)
from juloserver.julo.tasks import create_application_checklist_async, upload_document
from juloserver.julo.utils import display_rupiah
from juloserver.julo.workflows import WorkflowAction
from juloserver.julo.workflows2.handlers import execute_action
from juloserver.julocore.python2.utils import py2round
from juloserver.loan.constants import LoanJuloOneConstant
from juloserver.loan.models import LoanAdjustedRate
from juloserver.loan.services.adjusted_loan_matrix import get_daily_max_fee
from juloserver.loan.services.loan_related import (
    determine_transaction_method_by_transaction_type,
    get_loan_amount_by_transaction_type,
    update_loan_status_and_loan_history,
)
from juloserver.loan.services.loan_related import (
    get_transaction_type as get_disbursement_transaction_type,
)
from juloserver.loan.services.sphp import accept_julo_sphp
from juloserver.loan.services.views_related import validate_loan_concurrency
from juloserver.merchant_financing.utils import (
    validate_merchant_financing_max_interest_with_ojk_rule,
)
from juloserver.partnership.constants import (
    LoanDurationType,
    PartnershipImageType,
)
from juloserver.partnership.models import PartnerLoanRequest
from juloserver.partnership.tasks import download_image_from_url_and_upload_to_oss
from juloserver.pin.models import CustomerPin
from juloserver.pin.services import CustomerPinService
from juloserver.portal.object.bulk_upload.constants import (
    FeatureNameConst,
    MerchantFinancingCSVUploadPartner,
    MerchantFinancingCSVUploadPartnerDueDateType,
)
from juloserver.portal.object.bulk_upload.utils import compute_first_payment_installment, compute_payment_installment, pin_generator, validate_partner_disburse_data
from juloserver.portal.object.bulk_upload.skrtp_service.service import get_mf_skrtp_content
from juloserver.payment_point.models import TransactionMethod

from .tasks import send_email_at_190_for_pilot_product_csv_upload

logger = logging.getLogger(__name__)


class DuplicatedException(Exception):
    def __init__(self, application):
        self.application = application


class WrongStatusException(Exception):
    pass


class ExistingCustomerException(Exception):
    pass


class DoneException(Exception):
    def __init__(self, application):
        self.application = application

    def __str__(self):
        return 'Done | Application: {} | Email: {}'.format(
            self.application.application_xid, self.application.email
        )


graveyard_statuses = {
    ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,  # 106
    ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED,  # 136
    ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,  # 139
    ApplicationStatusCodes.APPLICATION_DENIED,  # 135
    ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,  # 137
    ApplicationStatusCodes.FORM_SUBMISSION_ABANDONED  # 111
}

BUKUWARUNG = MerchantFinancingCSVUploadPartner.BUKUWARUNG
EFISHERY = MerchantFinancingCSVUploadPartner.EFISHERY
DAGANGAN = MerchantFinancingCSVUploadPartner.DAGANGAN
KOPERASI_TUNAS = MerchantFinancingCSVUploadPartner.KOPERASI_TUNAS
EFISHERY_KABAYAN_LITE = MerchantFinancingCSVUploadPartner.EFISHERY_KABAYAN_LITE
EFISHERY_INTI_PLASMA = MerchantFinancingCSVUploadPartner.EFISHERY_INTI_PLASMA
EFISHERY_JAWARA = MerchantFinancingCSVUploadPartner.EFISHERY_JAWARA
RABANDO = MerchantFinancingCSVUploadPartner.RABANDO
KARGO = MerchantFinancingCSVUploadPartner.KARGO
KOPERASI_TUNAS_45 = MerchantFinancingCSVUploadPartner.KOPERASI_TUNAS_45
FISHLOG = MerchantFinancingCSVUploadPartner.FISHLOG
EFISHERY_KABAYAN_REGULER = MerchantFinancingCSVUploadPartner.EFISHERY_KABAYAN_REGULER
GAJIGESA = MerchantFinancingCSVUploadPartner.GAJIGESA

# TODO: move this to feature settings or add new column in partner
VALIDATE_PARTNER_PRODUCT_LINE = {
    KOPERASI_TUNAS,
    DAGANGAN,
    RABANDO,
    KARGO,
    KOPERASI_TUNAS_45,
    FISHLOG,
    MerchantFinancingCSVUploadPartner.AGRARI,
    MerchantFinancingCSVUploadPartner.EFISHERY_INTI_PLASMA,
    MerchantFinancingCSVUploadPartner.EFISHERY_JAWARA,
    MerchantFinancingCSVUploadPartner.EFISHERY_KABAYAN_REGULER,
    MerchantFinancingCSVUploadPartner.GAJIGESA,
}

# We hardcode this because for Efishery we will disburse the money to
# Efishery account first instead of the customer
EFISHERY_BANK_ACCOUNT_NUMBER = 2021313108
DAGANGAN_BANK_ACCOUNT_NUMBER = '0353354555'

MF_GENERAL_PAYMENT_METHOD = '0000'

VALIDATE_PARTNER_MF_EFISHERY = {
    EFISHERY,
    EFISHERY_KABAYAN_LITE,
    KOPERASI_TUNAS,
    EFISHERY_INTI_PLASMA,
    EFISHERY_JAWARA,
    EFISHERY_KABAYAN_REGULER,
    GAJIGESA,
}


def run_merchant_financing_upload_csv(customer_data=None, partner=None, application=None):
    try:
        try:
            if application:
                raise DuplicatedException(application)
            return register_partner_application(customer_data, partner)
        except DuplicatedException as e:
            application = e.application

        try:
            update_partner_upload_status_105_to_124(application)
        except WrongStatusException:
            pass

        try:
            update_partner_upload_status_124_to_130(application)
        except WrongStatusException:
            pass

        try:
            update_partner_upload_status_130_to_190(application)
        except WrongStatusException:
            pass
        finally:
            raise DoneException(application)

    except Exception as exception:
        if hasattr(application, 'application_status_id'):
            status = application.application_status_id
        else:
            status = 0

        if status == ApplicationStatusCodes.APPLICATION_DENIED:
            return (False, 'Application Status {}'.format(status))
        return (False, 'Application Status {}: {}'.format(
            status, str(exception)))


def register_partner_application(customer_data, partner):
    partner_name = partner.name
    nik = customer_data['ktp']
    application = Application.objects.filter(
        ktp=nik, partner__name=partner_name
    ).select_related('partner').last()
    if application:
        partner_names = {EFISHERY, DAGANGAN, EFISHERY_KABAYAN_LITE,
                         EFISHERY_INTI_PLASMA, EFISHERY_JAWARA, EFISHERY_KABAYAN_REGULER, GAJIGESA}
        if application.partner.name not in partner_names or \
                (application.partner.name in partner_names and application.application_status_id not in
                 graveyard_statuses):
            raise DuplicatedException(application)
    customer_data['pin'] = pin_generator()
    customer_data['app_version'] = "3.0.0"
    customer_data['loan_purpose_desc'] = "buy something"
    customer_data['job_start'] = '1990-01-01'
    email = customer_data.get('email', None)

    if partner_name in {BUKUWARUNG, KARGO}:
        email = email.replace('@', ('__-__%s__-__%s__-__@' % (
            customer_data['approved_limit'], customer_data.get('provision'))))
        name_in_bank = customer_data.get('name_in_bank')
        if not name_in_bank:
            customer_data['name_in_bank'] = customer_data['fullname']
    else:
        if partner.is_disbursement_to_partner_bank_account or partner.is_disbursement_to_distributor_bank_account:
            customer_data['name_in_bank'] = None
            customer_data['bank_account_number'] = None
            customer_data['bank_name'] = partner.partner_bank_name

        if partner_name in {EFISHERY, EFISHERY_KABAYAN_LITE,
                            EFISHERY_INTI_PLASMA, EFISHERY_JAWARA}:
            customer_data['bank_name'] = 'BANK NEGARA INDONESIA (PERSERO), Tbk (BNI)'
        elif partner_name in {DAGANGAN, EFISHERY_KABAYAN_REGULER}:
            customer_data['bank_name'] = 'BANK CENTRAL ASIA, Tbk (BCA)'
        elif partner_name == GAJIGESA:
            customer_data['bank_name'] = 'BANK MANDIRI (PERSERO), Tbk'

        if not email:
            partner_name_without_space = partner_name.replace(" ", "_")
            email = partner_name_without_space + '+' + nik + ('__-__%s__-__' %
                                                              customer_data['approved_limit']) + '@julofinance.com'
        else:
            email = email.replace('@', ('__-__%s__-__@' % customer_data['approved_limit']))

    customer_data['email'] = email
    email = email.strip().lower()
    if settings.ENVIRONMENT != 'prod':
        customer_data['name_in_bank'] = 'prod only'

    if not customer_data.get('close_kin_mobile_phone'):
        customer_data.pop('close_kin_mobile_phone', None)

    if not customer_data.get('kin_mobile_phone'):
        customer_data.pop('kin_mobile_phone', None)

    customer_data['home_status'] = customer_data['home_status'].capitalize()

    customer_data['last_education'] = customer_data['last_education'].upper()
    if customer_data['last_education'] == 'DIPLOMA':
        customer_data['last_education'] = customer_data['last_education'].capitalize()

    customer_data['kin_name'] = customer_data['kin_name'].strip().lower()

    try:
        with transaction.atomic():
            user = User(username=nik, email=email)
            user.set_password(customer_data['pin'])
            user.save()

            customer = Customer.objects.create(
                user=user, email=email, nik=nik
            )

            device = Device.objects.create(customer=customer, gcm_reg_id='fake gcm')
            customer_data['customer'] = customer.id
            customer_data['partner'] = partner.id
            customer_data['device'] = device.id

            application_serializer = ApplicationUpdateSerializer(data=customer_data)
            application_serializer.is_valid(raise_exception=True)
            application = application_serializer.save()

            j1_workflow = Workflow.objects.get(name=WorkflowConst.JULO_ONE)
            application.application_number = 1
            application.product_line = partner.product_line
            application.workflow = j1_workflow
            if partner.is_disbursement_to_partner_bank_account or partner.is_disbursement_to_distributor_bank_account:
                bank_account_destination = BankAccountDestination.objects.filter(
                    account_number=partner.partner_bank_account_number,
                    bank_account_category__category=BankAccountCategoryConst.PARTNER,
                    customer=partner.user.customer
                ).last()
                if not bank_account_destination:
                    raise Exception("{} bank account doesn't exist".format(partner_name))
                application.name_bank_validation = bank_account_destination.name_bank_validation

            application.save()
            customer_pin_service = CustomerPinService()
            customer_pin_service.init_customer_pin(user)
            update_customer_data(application)
    except (IntegrityError, Exception) as ae:
        with transaction.atomic():
            if 'duplicate key value' in str(ae):
                try:
                    run_reapply_check(nik, email)
                    customer = Customer.objects.filter(nik=nik).last()
                    if not customer:
                        raise ExistingCustomerException(
                            'Customer dont exist for reapply application'
                        )
                    partner = Partner.objects.get(name=partner_name)
                    device = Device.objects.create(customer=customer, gcm_reg_id='fake gcm')

                    customer_data['customer'] = customer.id
                    customer_data['partner'] = partner.id
                    customer_data['device'] = device.id

                    applications_qs = customer.application_set.regular_not_deletes()
                    len_applications = len(applications_qs)
                    if len_applications == 0:
                        application_number = 1
                    else:
                        last_application = applications_qs.last()
                        if last_application.application_number:
                            application_number = last_application.application_number + 1
                        else:
                            application_number = len_applications + 1

                    application_serializer = ApplicationUpdateSerializer(data=customer_data)
                    application_serializer.is_valid(raise_exception=True)
                    application = application_serializer.save()

                    j1_workflow = Workflow.objects.get(name=WorkflowConst.JULO_ONE)
                    application.application_number = application_number
                    application.product_line = partner.product_line
                    application.workflow = j1_workflow
                    if partner.is_disbursement_to_partner_bank_account or partner.is_disbursement_to_distributor_bank_account:
                        bank_account_destination = BankAccountDestination.objects.filter(
                            account_number=partner.partner_bank_account_number,
                            bank_account_category__category=BankAccountCategoryConst.PARTNER,
                            customer=partner.user.customer
                        ).last()
                        if not bank_account_destination:
                            raise Exception("{} bank account doesn't exist".format(partner_name))
                        application.name_bank_validation = bank_account_destination.name_bank_validation

                    application.save()
                    user = customer.user
                    if not CustomerPin.objects.filter(user=user).exists():
                        user.set_password(customer_data['pin'])
                        user.save()
                        customer_pin_service = CustomerPinService()
                        customer_pin_service.init_customer_pin(user)
                    update_customer_data(application)

                except Exception as e:
                    return (False, e)
            else:
                return (False, ae)

    download_image_from_url_and_upload_to_oss.delay(
        customer_data['ktp_photo'], application.id, PartnershipImageType.KTP_SELF
    )
    download_image_from_url_and_upload_to_oss.delay(
        customer_data['selfie_photo'], application.id, PartnershipImageType.SELFIE
    )

    process_application_status_change(
        application.id, ApplicationStatusCodes.FORM_CREATED,
        change_reason='system_triggered'
    )
    create_application_checklist_async.delay(application.id)
    validate_step(application, 100)
    process_application_status_change(
        application.id, ApplicationStatusCodes.FORM_PARTIAL,
        change_reason='system_triggered')

    return (True, application.application_xid)


def validate_step(application, status):
    application.refresh_from_db()
    if application.application_status_id != status:
        raise WrongStatusException(
            'Application ID %s status %s',
            (application.id, application.application_status_id)
        )


def update_partner_upload_status_105_to_124(application):
    validate_step(application, 105)
    # check binary check ready
    if not AutoDataCheck.objects.filter(application_id=application.id).exists():
        raise Exception('Binary Check is not ready: %s' % application.id)

    bypass_checks = [
        'fraud_device', 'fraud_form_full', 'own_phone',
        'job_term_gt_3_month', 'fdc_inquiry_check', 'saving_margin']
    failed_checks = AutoDataCheck.objects.filter(
        application_id=application.id, is_okay=False)

    failed_checks = failed_checks.exclude(data_to_check__in=bypass_checks)
    if failed_checks.exists():
        process_application_status_change(
            application.id, ApplicationStatusCodes.APPLICATION_DENIED,
            change_reason='failed_binary'
        )
        return

    fdc_result = fdc_binary_check_merchant_financing_csv_upload(['fdc_inquiry_check'], application)

    if fdc_result is False:
        process_application_status_change(
            application.id, ApplicationStatusCodes.APPLICATION_DENIED,
            change_reason='failed_fdc'
        )
        return


    action = get_workflow_action(application)
    action.process_validate_bank()

    skippable_application_status_change(
        application, ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL,
        change_reason='system_triggered'
    )
    application.refresh_from_db()

    update_partner_upload_status_124_to_130(application)


def update_partner_upload_status_124_to_130(application):
    validate_step(application, 124)
    if not application.name_bank_validation:
        raise Exception('Please do name bank validation first')
    validation_status = application.name_bank_validation.validation_status
    if validation_status in [
            NameBankValidationStatus.NAME_INVALID, NameBankValidationStatus.INITIATED]:
        action = get_workflow_action(application)
        action.process_validate_bank()
        application.refresh_from_db()
        if validation_status == NameBankValidationStatus.NAME_INVALID:
            raise Exception("NameBankValidation failed name valid")

    if validation_status == NameBankValidationStatus.FAILED:
        process_application_status_change(
            application.id, ApplicationStatusCodes.APPLICATION_DENIED,
            change_reason='name_bank_validation_failed'
        )

    elif validation_status == NameBankValidationStatus.SUCCESS:
        customer = application.customer
        # limit is attach on customer email when creating the application
        limit = int(customer.email.split('__-__')[1])
        if not limit:
            raise Exception('Limit is invalid')
        with transaction.atomic():
            skippable_application_status_change(
                application, ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
                change_reason='system_triggered'
            )
            process_credit_limit_generation(application, limit, limit)
            generate_customer_va_for_julo_one(application)
            if application.partner.is_disbursement_to_partner_bank_account or application.partner.is_disbursement_to_distributor_bank_account:
                PaymentMethod.objects.create(
                    payment_method_code=MF_GENERAL_PAYMENT_METHOD,
                    payment_method_name=application.partner.name,
                    customer=customer
                )
            else:
                process_create_self_bank_account_destination(application)

        update_partner_upload_status_130_to_190(application)
    else:
        raise Exception("NameBankValidation pending")


def update_partner_upload_status_130_to_190(application):
    validate_step(application, 130)
    if application.customer.account_set.last():
            skippable_application_status_change(
                application, ApplicationStatusCodes.LOC_APPROVED,
                change_reason='system_triggered'
            )
            customer = application.customer
            email_split = customer.email.split('__-__')
            limit = email_split[1]

            provision = None
            if application.partner.name in {BUKUWARUNG, KARGO}:
                provision = email_split[2]

            new_email = str(email_split[0]) + str(email_split[-1])
            application.email = new_email
            customer.email = new_email
            customer.user.email = new_email
            customer.save()
            application.save()
            customer.user.save()
            # process_julo_one_at_190
            action = get_julo_one_workflow_action(application)
            action.process_julo_one_at_190()
            send_email_at_190_for_pilot_product_csv_upload.delay(application.id, limit, provision)


def skippable_application_status_change(application, new_status_code,
                                        change_reason, note=None, skip={'all'}):
    old_status_code = application.status
    with ApplicationHistoryUpdated(application, change_reason=change_reason):
        workflow = application.workflow
        if not workflow:
            workflow = Workflow.objects.get(name='LegacyWorkflow')  # use the default one
        status_path = WorkflowStatusPath.objects.get_or_none(
            workflow=workflow, status_previous=application.status,
            status_next=new_status_code, is_active=True)
        if not status_path:
            logger.error({'reason': 'Workflow not specified for status change',
                          'application_id': application.id,
                          'old_status_code': old_status_code,
                          'new_status_code': new_status_code})
            raise JuloInvalidStatusChange(
                "No path from status {} to {}".format(old_status_code, new_status_code))

        application.change_status(new_status_code)
        application.save()

        if "all" in skip:
            return

        if "post" not in skip:
            execute_action(application, old_status_code, new_status_code,
                           change_reason, note, workflow, 'post')
        if "async_task" not in skip:
            execute_action(application, old_status_code, new_status_code,
                           change_reason, note, workflow, 'async_task')
        if "after" not in skip:
            execute_action(application, old_status_code, new_status_code,
                           change_reason, note, workflow, 'after')


def get_workflow_action(application):
    return WorkflowAction(application, None, None, None, None)


def get_julo_one_workflow_action(application):
    return JuloOneWorkflowAction(application, None, None, None, None)


def process_credit_limit_generation(application, max_limit, set_limit):
    generate_credit_limit_merchant_financing_csv_upload(application, max_limit)
    account = application.customer.account_set.last()
    if not account:
        store_related_data_for_generate_credit_limit(application, max_limit, set_limit)
        application.refresh_from_db()

        # generate account_property and history
        store_account_property_merchant_financing_csv_upload(application, set_limit)
    else:
        update_related_data_for_generate_credit_limit(application,
                                                      max_limit,
                                                      set_limit)

    credit_limit_generation_obj = CreditLimitGeneration.objects.select_related("account").filter(
        application_id=application.id).last()
    if credit_limit_generation_obj:
        account = application.customer.account_set.last()
        credit_limit_generation_obj.account = account
        credit_limit_generation_obj.save()

        account_lookup = AccountLookup.objects.filter(
            name='JULO1'
        ).last()

        account.account_lookup = account_lookup
        account.save()


def store_account_property_merchant_financing_csv_upload(application, set_limit):
    is_proven = get_is_proven()

    input_params = dict(
        account=application.account,
        pgood=0.0,
        p0=0.0,
        is_salaried=get_salaried(application.job_type),
        is_proven=is_proven,
        is_premium_area=is_inside_premium_area(application),
        proven_threshold=get_proven_threshold(set_limit),
        voice_recording=get_voice_recording(is_proven),
        concurrency=True,
    )

    account_property = AccountProperty.objects.create(**input_params)
    # create history
    store_account_property_history(input_params, account_property)


class MerchantFinancingCsvUploadCreditModelResult():
    pgood = 0.8


def fdc_binary_check_merchant_financing_csv_upload(failed_checks, application):
    credit_model_result = MerchantFinancingCsvUploadCreditModelResult
    _failed_checks, fdc_result = remove_fdc_binary_check_that_is_not_in_fdc_threshold(
        credit_model_result,
        failed_checks,
        application
    )
    return fdc_result


def generate_credit_limit_merchant_financing_csv_upload(application, limit):
    affordability_history = AffordabilityHistory.objects.create(
        application_id=application.id,
        application_status=application.application_status,
        affordability_value=0.8,
        affordability_type='',
        reason=application.partner.name
    )

    credit_matrix_parameters = dict(
        min_threshold__lte=0.8,
        max_threshold__gte=0.8,
        credit_matrix_type="julo1",
        is_salaried=False,
        is_premium_area=False
    )
    transaction_type = get_transaction_type()
    credit_matrix = get_credit_matrix(credit_matrix_parameters, transaction_type)

    log_data = {
        'simple_limit': limit,
    }
    reason = "130 {} Credit Limit Generation".format(application.partner.name)

    store_credit_limit_generated(
        application,
        None,
        credit_matrix,
        affordability_history,
        limit,
        limit,
        json.dumps(log_data),
        reason
    )


def run_reapply_check(nik, email):
    application_history_prefetch = Prefetch(
        'applicationhistory_set',
        queryset=ApplicationHistory.objects.filter(status_new=ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD),
        to_attr='application_histories')
    loan_prefetch = Prefetch(
        'loan_set', queryset=Loan.objects.filter(
            loan_status__in=[
                LoanStatusCodes.CURRENT,
                LoanStatusCodes.LOAN_1DPD,
                LoanStatusCodes.LOAN_5DPD,
                LoanStatusCodes.LOAN_30DPD,
                LoanStatusCodes.LOAN_60DPD,
                LoanStatusCodes.LOAN_90DPD,
                LoanStatusCodes.LOAN_120DPD,
                LoanStatusCodes.LOAN_150DPD,
                LoanStatusCodes.LOAN_180DPD,
                LoanStatusCodes.RENEGOTIATED
            ],
        ),
        to_attr='loans'
    )
    application_prefetch = Prefetch(
        'application_set',
        queryset=Application.objects.all().prefetch_related(application_history_prefetch),
        to_attr='applications'
    )
    prefetch_join_tables = [
        loan_prefetch,
        application_prefetch
    ]
    customer = Customer.objects.prefetch_related(*prefetch_join_tables).filter(
        nik=nik
    ).last()
    if customer.loans:
        raise ExistingCustomerException('Ongoing loan already exist')
    applications = customer.applications
    for application in applications:
        if application.application_status_id not in graveyard_statuses\
            and application.application_status_id != ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL:
            raise ExistingCustomerException('Ongoing application already exists.')
        if application.application_histories:
            raise ExistingCustomerException('Fraud history exist')


def disburse_mf_partner_customer(disburse_data, partner):
    disburse_data, message = validate_partner_disburse_data(disburse_data)
    if message:
        return False, message

    loan_amount_request = disburse_data['loan_amount_request']
    loan_duration = disburse_data['loan_duration']
    interest_rate = disburse_data['interest_rate']
    origination_fee_pct = disburse_data['origination_fee_pct']
    application_xid = disburse_data['application_xid']

    application = Application.objects.select_related(
        "partner", "account", "product_line", "customer"
    ).filter(application_xid=application_xid, partner=partner).last()
    if not application:
        return False, "Application not exist or wrong partner"

    application.update_safely(job_type="Pengusaha", company_name=partner.name, job_industry="Pedagang")
    account = application.account
    if account is None:
        return False, "Account not found"
    loan = account.loan_set.last()

    if loan and loan.loan_status.status_code == LoanStatusCodes.INACTIVE:
        return False, "Loan process on-going"

    if loan and loan.loan_status.status_code == LoanStatusCodes.LENDER_APPROVAL:
        update_loan_status_and_loan_history(
            loan.id,
            new_status_code=LoanStatusCodes.CANCELLED_BY_CUSTOMER,
            change_reason="Stuck at 211",
        )
    _, concurrency_messages = validate_loan_concurrency(account)
    if concurrency_messages:
        return False, concurrency_messages['content']

    mobile_number = application.mobile_phone_1
    if mobile_number:
        feature_setting = FeatureSetting.objects.filter(
            feature_name=LoanJuloOneConstant.PHONE_NUMBER_BLACKLIST,
            is_active=True).last()
        if feature_setting:
            params = feature_setting.parameters
            blacklist_phone_number = params['blacklist_phone_numnber']
            if mobile_number in blacklist_phone_number:
                return False, "Invalid phone number"

    bank_account_destination = None
    self_bank_account = True
    if partner.is_disbursement_to_partner_bank_account or \
            partner.is_disbursement_to_distributor_bank_account:
        self_bank_account = False
    data = dict(
        loan_amount_request=loan_amount_request,
        account_id=account.id,
        loan_duration=loan_duration,
        bank_account_number=application.bank_account_number,
        self_bank_account=self_bank_account,
        loan_purpose=application.loan_purpose,
    )

    if partner.is_disbursement_to_partner_bank_account:
        bank_account_destination = BankAccountDestination.objects.filter(
            account_number=partner.partner_bank_account_number,
            customer=application.partner.user.customer,
            bank_account_category__category=BankAccountCategoryConst.PARTNER
        ).last()
    elif partner.is_disbursement_to_distributor_bank_account:
        if not application.name_bank_validation:
            return False, "Name bank validation not found in application xid {}".format(
                application.application_xid
            )

        bank_account_destination = BankAccountDestination.objects.filter(
            account_number=application.bank_account_number,
            customer=application.customer,
            name_bank_validation=application.name_bank_validation,
            bank_account_category__category=BankAccountCategoryConst.SELF
        ).last()
    else:
        bank_account_destination = BankAccountDestination.objects.filter(
            account_number=application.bank_account_number,
            customer=application.customer,
            bank_account_category__category=BankAccountCategoryConst.SELF
        ).last()

    if not bank_account_destination:
        return False, "Bank account destination not found"

    data['bank_account_destination_id'] = bank_account_destination.id
    product = application.product_line.productlookup_set.filter(
        interest_rate=interest_rate,
        origination_fee_pct=origination_fee_pct,
    ).last()
    if not product:
        return False, "Product not found"

    if data['loan_duration'] != application.product_line.max_duration and partner.name \
            in {DAGANGAN, KOPERASI_TUNAS_45}:
        return False, 'Tenor tidak {} hari'.format(application.product_line.max_duration)

    if data['loan_duration'] > application.product_line.max_duration and partner.name == KOPERASI_TUNAS:
        return False, 'Tenor tidak boleh lebih dari {} bulan'.format(application.product_line.max_duration)

    if partner.name in VALIDATE_PARTNER_PRODUCT_LINE:
        if data['loan_amount_request'] < application.product_line.min_amount or \
                data['loan_amount_request'] > application.product_line.max_amount:
            return False, 'Amount Requested (Rp) harus lebih besar sama dengan {} dan lebih kecil sama dengan {}' \
                .format(display_rupiah(application.product_line.min_amount),
                        display_rupiah(application.product_line.max_amount))

    loan_amount = get_loan_amount_by_transaction_type(loan_amount_request,
                                                      origination_fee_pct,
                                                      data['self_bank_account'])
    loan_duration_type = (
        disburse_data.get("loan_duration_type")
        if disburse_data.get("loan_duration_type")
        else LoanDurationType.MONTH
    )
    loan_requested = dict(
        loan_amount=int(loan_amount),
        original_loan_amount_requested=loan_amount_request,
        loan_duration_request=int(data['loan_duration']),
        interest_rate_monthly=product.monthly_interest_rate,
        is_buku_warung=True if partner == MerchantFinancingCSVUploadPartner.BUKUWARUNG else False,
        product=product,
        provision_fee=origination_fee_pct,
        is_withdraw_funds=data['self_bank_account'],
        is_loan_amount_adjusted=True,
        is_dagangan=True if partner == MerchantFinancingCSVUploadPartner.DAGANGAN else False,
        loan_duration_type=loan_duration_type
    )
    loan_purpose = data['loan_purpose']

    try:
        with transaction.atomic():
            account_limit = AccountLimit.objects.select_for_update().filter(
                account=account).last()
            if loan_amount_request > account_limit.available_limit:
                return False, "Jumlah pinjaman tidak boleh lebih besar dari limit tersedia"

            loan = generate_loan_payment_mf(
                application, loan_requested, loan_purpose,
                None, bank_account_destination
            )

            transaction_type = get_disbursement_transaction_type(
                data['self_bank_account'], False, bank_account_destination)
            transaction_method = determine_transaction_method_by_transaction_type(
                transaction_type)

            loan.update_safely(transaction_method=transaction_method)
            update_available_limit(loan)
    except Exception as e:
        return False, str(e)

    if loan_duration_type == LoanDurationType.DAYS:
        monthly_interest = loan_requested['product'].interest_rate / 12
    else:
        monthly_interest = product.monthly_interest_rate

    if hasattr(loan, 'loanadjustedrate'):
        origination_fee_pct = loan.loanadjustedrate.adjusted_provision_rate
        monthly_interest = loan.loanadjustedrate.adjusted_monthly_interest_rate

    if application.partner.name in VALIDATE_PARTNER_MF_EFISHERY:
        disbursement_amount = loan.loan_disbursement_amount
    else:
        disbursement_amount = py2round(loan.loan_amount - (loan.loan_amount * origination_fee_pct))

    sphp_message = create_mf_sphp(application, loan, account_limit)
    accept_julo_sphp(loan, "JULO")
    loan.refresh_from_db()

    return True, "Success with loan_id %s, monthly_interest %s, disbursement_amount %s, sphp_message %s" % (
        loan.id, monthly_interest, disbursement_amount, sphp_message)


def generate_loan_payment_mf(application, loan_requested, loan_purpose,
                                   credit_matrix, bank_account_destination=None,
                                   draft_loan=False):
    from juloserver.loan.services.adjusted_loan_matrix import (
        validate_max_fee_rule_by_loan_requested,
    )
    from juloserver.loan.services.loan_related import (
        get_loan_amount_by_transaction_type,
    )

    with transaction.atomic():
        loan_duration_type = loan_requested.get("loan_duration_type")
        today_date = timezone.localtime(timezone.now()).date()
        if application.partner.name == KOPERASI_TUNAS_45:
            first_payment_date = today_date + relativedelta(days=45)
        elif loan_duration_type == LoanDurationType.DAYS:
            first_payment_date = today_date + relativedelta(
                days=loan_requested['loan_duration_request']
            )
        else:
            first_payment_date = today_date + relativedelta(months=1)

        original_provision_rate = loan_requested['provision_fee']
        kwargs = {}
        if loan_requested.get('is_buku_warung'):
            kwargs = {
                'is_buku_warung': loan_requested.get('is_buku_warung'),
                'duration_in_days': loan_requested.get('duration_in_days')
            }
        """
            This is For Dagangan calculation only, since it have a difficult calculation of interest
            because the tenor will be 14 days and it will have a static interest rate for 1.5/1.75/2 %
            And since we need to save the interest in year on product line table
            so 1.5% = 0.386, 1.75% = 0.45, 2% = 0.514
            and since our general monthly interest will be round to the last 3 digits the calculation will be off
            For example we take yearly interest of 0.45 (the last result should be 0.0175):
            monthly = 0.45 / 12 = 0.0375 -> 0.038 (got round to 3 digits)
            daily = 0.038 / 30 = 0.001266667
            interest_for_14_days = 0.001266667 * 14 = 0.017733333 (1.77%) Not correct
        """
        if application.partner.name == DAGANGAN:
            loan_duration_type = LoanDurationType.DAYS
            loan_amount = loan_requested['loan_amount']
            is_max_fee_exceeded = False
            daily_max_fee_from_ojk = get_daily_max_fee()
            additional_loan_data = {
                'is_exceed': is_max_fee_exceeded,
                'max_fee_ojk': 0.0,
                'simple_fee': 0.0,
                'provision_fee_rate': 0.0,
                'new_interest_rate': 0.0
            }
            """
                here is the difference calculation takes place where we usually
                get the monthly_interest_rate by loan_requested.product.monthly_interest_rate
                but here we calculate it manually so that it will not get round up to 3 digits
            """
            monthly_interest_rate = loan_requested['product'].interest_rate / 12  # 12 is for 12 month
            """
                Since Dagangan loan duration is in days, then we can directly assign
                loan_duration_request to loan_duration_in_days
            """
            loan_requested['loan_duration_in_days'] = loan_requested['loan_duration_request']
            if daily_max_fee_from_ojk:
                additional_loan_data = validate_merchant_financing_max_interest_with_ojk_rule(
                    loan_requested, additional_loan_data, daily_max_fee_from_ojk
                )
                is_max_fee_exceeded = additional_loan_data['is_exceed']
                if is_max_fee_exceeded:
                    from juloserver.loan.services.loan_related import (
                        get_loan_amount_by_transaction_type,
                    )
                    monthly_interest_rate = additional_loan_data['new_interest_rate']
                    adjusted_loan_amount = get_loan_amount_by_transaction_type(
                        loan_requested['original_loan_amount_requested'],
                        additional_loan_data['provision_fee_rate'], False
                    )
                    loan_requested['provision_fee'] = additional_loan_data['provision_fee_rate']
                    loan_requested['loan_amount'] = adjusted_loan_amount
                    max_fee = additional_loan_data['max_fee_ojk']
                    total_fee = additional_loan_data['simple_fee']

            interest_rate = py2round(monthly_interest_rate / 30 * loan_requested['loan_duration_request'], 4)  # 30 is for 30 days
            interest_rest = loan_amount * interest_rate
            installment_rest = loan_requested['loan_amount'] + interest_rest
        elif application.partner.name == KOPERASI_TUNAS_45:
            loan_duration_type = LoanDurationType.DAYS
            is_max_fee_exceeded = False
            loan_amount = loan_requested['loan_amount']
            monthly_interest_rate = loan_requested['product'].interest_rate / 12  # 12 is for 12 month
            interest_rate = monthly_interest_rate
            interest_rest = loan_amount * interest_rate
            installment_rest = loan_requested['loan_amount'] + interest_rest
        else:
            if application.partner.name in VALIDATE_PARTNER_MF_EFISHERY:
                loan_amount = loan_requested['original_loan_amount_requested']
            else:
                loan_amount = loan_requested['loan_amount']

            (
                is_max_fee_exceeded,
                total_fee,
                max_fee,
                monthly_interest_rate,
                _,
                _,
                _,
            ) = validate_max_fee_rule_by_loan_requested(first_payment_date, loan_requested, kwargs)
            if is_max_fee_exceeded:
                if loan_requested['is_loan_amount_adjusted'] and \
                        not loan_requested['is_withdraw_funds'] and \
                        loan_requested['provision_fee'] != original_provision_rate:
                    readjusted_loan_amount = get_loan_amount_by_transaction_type(
                        loan_requested['original_loan_amount_requested'],
                        loan_requested['provision_fee'],
                        loan_requested['is_withdraw_funds'])
                    loan_requested['loan_amount'] = readjusted_loan_amount

                principal_rest, interest_rest, installment_rest = compute_payment_installment(
                    loan_requested['loan_amount'], loan_requested['loan_duration_request'],
                    monthly_interest_rate)

                principal_first = principal_rest
                interest_first = interest_rest
                installment_first = installment_rest
            else:
                if loan_duration_type == LoanDurationType.DAYS:
                    monthly_interest_rate = loan_requested['product'].interest_rate / 12
                    loan_duration = 1
                else:
                    monthly_interest_rate = loan_requested['interest_rate_monthly']
                    loan_duration = loan_requested['loan_duration_request']

                principal_rest, interest_rest, installment_rest = compute_payment_installment(
                    loan_amount, loan_duration,
                    monthly_interest_rate)

                principal_first, interest_first, installment_first = compute_first_payment_installment(
                    loan_amount, loan_duration,
                    monthly_interest_rate, today_date, first_payment_date)

        installment_amount = installment_rest
        initial_status = LoanStatusCodes.DRAFT if draft_loan else LoanStatusCodes.INACTIVE

        loan = Loan.objects.create(
            customer=application.customer,
            loan_status=StatusLookup.objects.get(status_code=initial_status),
            product=loan_requested['product'],
            loan_amount=loan_amount,
            loan_duration=loan_requested['loan_duration_request'],
            first_installment_amount=installment_amount,
            installment_amount=installment_amount,
            bank_account_destination=bank_account_destination,
            account=application.account,
            loan_purpose=loan_purpose,
            credit_matrix=credit_matrix,
            application_id2 = application.id
        )
        if is_max_fee_exceeded:
            LoanAdjustedRate.objects.create(
                loan=loan,
                adjusted_monthly_interest_rate=monthly_interest_rate,
                adjusted_provision_rate=loan_requested['provision_fee'],
                max_fee=max_fee,
                simple_fee=total_fee
            )

        PartnerLoanRequest.objects.create(
            loan=loan,
            partner=application.partner,
            loan_amount=loan_amount,
            loan_disbursement_amount=loan.loan_disbursement_amount,
            loan_original_amount=loan_amount,
            loan_duration_type=loan_duration_type
        )

        if (
            application.partner.name in {DAGANGAN, KOPERASI_TUNAS_45}
            or loan_duration_type == LoanDurationType.DAYS
        ):
            due_date = today_date + relativedelta(days=loan_requested['loan_duration_request'])
            loan.cycle_day = due_date.day
        else:
            loan.cycle_day = application.account.cycle_day

        loan.set_disbursement_amount()
        loan.set_sphp_expiration_date()
        loan.sphp_sent_ts = timezone.localtime(timezone.now())

        # set payment method for Loan
        customer_has_vas = PaymentMethod.objects.active_payment_method(application.customer)
        if customer_has_vas:
            primary_payment_method = customer_has_vas.filter(is_primary=True).last()
            if primary_payment_method:
                loan.julo_bank_name = primary_payment_method.payment_method_name
                loan.julo_bank_account_number = primary_payment_method.virtual_account

        if is_new_loan_part_of_bucket5(application.account):
            loan.ever_entered_B5 = True
        loan.save()
        payment_status = StatusLookup.objects.get(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE)

        if (
            application.partner.name in {DAGANGAN, KOPERASI_TUNAS_45}
            or loan_duration_type == LoanDurationType.DAYS
        ):
            if application.partner.name in VALIDATE_PARTNER_MF_EFISHERY:
                loan.update_safely(
                    loan_disbursement_amount=loan_amount
                )
                platform_fee = loan_requested['provision_fee'] * loan_amount
                total_interest = interest_rest + platform_fee
                due_amount = round_rupiah(loan_amount + total_interest)
                loan_requested['loan_amount'] = loan_amount
            else:
                due_amount = loan_requested['loan_amount'] + interest_rest

            Payment.objects.create(
                loan=loan, payment_status=payment_status,
                payment_number=1, due_date=due_date,
                due_amount=due_amount,
                installment_principal=loan_requested['loan_amount'],
                installment_interest=due_amount - loan_requested['loan_amount']
            )
            loan.update_safely(
                first_installment_amount=due_amount,
                installment_amount=due_amount
            )

        elif application.partner.due_date_type in {MerchantFinancingCSVUploadPartnerDueDateType.MONTHLY,
                                                   MerchantFinancingCSVUploadPartnerDueDateType.END_OF_TENOR}:
            bulk_payment = []
            principal_deviation = loan.loan_amount - (
                principal_first + (
                    (loan.loan_duration - 1) * principal_rest)
            )
            total_interest = 0
            total_installment = 0
            total_principal = 0
            for payment_number in range(loan.loan_duration):
                if application.partner.due_date_type == \
                        MerchantFinancingCSVUploadPartnerDueDateType.MONTHLY:
                    if payment_number == 0:
                        due_date = first_payment_date
                        principal, interest, installment = \
                            principal_first, interest_first, installment_first
                    else:
                        due_date = first_payment_date + relativedelta(months=payment_number)
                        principal, interest, installment = principal_rest, interest_rest, installment_rest
                        if (payment_number + 1) == loan.loan_duration:
                            # special case to handle interest 0% caused by max_fee rule
                            if principal == installment and interest == 0:
                                principal += principal_deviation
                                installment = principal
                            else:
                                principal += principal_deviation
                                interest -= principal_deviation

                    payment = Payment(
                        loan=loan,
                        payment_status=payment_status,
                        payment_number=payment_number + 1,
                        due_date=due_date,
                        due_amount=installment,
                        installment_principal=principal,
                        installment_interest=0 if interest < 0 else interest
                    )
                    bulk_payment.append(payment)

                elif application.partner.due_date_type == \
                        MerchantFinancingCSVUploadPartnerDueDateType.END_OF_TENOR:
                    due_date = first_payment_date + relativedelta(months=payment_number)
                    principal, interest, installment = principal_rest, interest_rest, installment_rest
                    if (payment_number + 1) == loan.loan_duration:
                        # special case to handle interest 0% caused by max_fee rule
                        if principal == installment and interest == 0:
                            principal += principal_deviation
                            installment = principal
                        else:
                            principal += principal_deviation
                            interest -= principal_deviation

                    total_interest += interest
                    total_principal += principal
                    total_installment += installment

                    logger.info(
                        {
                            'action': 'generate_loan_payment_mf',
                            'loan_id': loan.id,
                            'loan_amount': loan_amount,
                            'loan_duration': loan.loan_duration,
                            'principal': principal,
                            'interest': interest,
                            'installment': installment,
                            'total_interest': total_interest,
                            'additional_info_data': {
                                'interest_rest': interest_rest,
                                'principal_deviation': principal_deviation,
                                'provision_fee': loan_requested['provision_fee'],
                                'monthly_interest_rate': monthly_interest_rate,
                                'is_max_fee_exceeded': is_max_fee_exceeded,
                            },
                            'message': 'calculation inside looping for end of tenor',
                        }
                    )

                    if (payment_number + 1) == loan.loan_duration:
                        # PARTNER-2056: calculation only for Efishery
                        if application.partner.name in VALIDATE_PARTNER_MF_EFISHERY:
                            loan.update_safely(
                                loan_disbursement_amount=loan_amount
                            )
                            platform_fee = loan_requested['provision_fee'] * loan_amount
                            total_interest = total_interest + platform_fee
                            due_amount = round_rupiah(loan_amount + total_interest)
                            logger.info(
                                {
                                    'action': 'generate_loan_payment_mf',
                                    'loan_id': loan.id,
                                    'loan_amount': loan_amount,
                                    'loan_duration': loan.loan_duration,
                                    'provision_fee': loan_requested['provision_fee'],
                                    'platform_fee': platform_fee,
                                    'total_interest': total_interest,
                                    'due_amount': due_amount,
                                    'due_amount_before_rounded': loan_amount + total_interest,
                                    'message': 'calculating last for partner {}'.format(
                                        VALIDATE_PARTNER_MF_EFISHERY
                                    ),
                                }
                            )
                        else:
                            due_amount = total_installment
                            if total_interest > 0:
                                due_amount = round_rupiah(total_installment)
                                rounding_rupiah_amount = int((total_installment - due_amount))
                                total_interest = total_interest - rounding_rupiah_amount
                                if total_interest < 0:
                                    total_interest = 0
                            logger.info(
                                {
                                    'action': 'generate_loan_payment_mf',
                                    'loan_id': loan.id,
                                    'total_installment': total_installment,
                                    'due_amount': due_amount,
                                    'rounding_rupiah_amount': rounding_rupiah_amount,
                                    'total_interest': total_interest,
                                    'due_amount_before_rounded': loan_amount + total_interest,
                                    'message': 'calculating last for partner {}'.format(
                                        application.partner.name
                                    ),
                                }
                            )

                        # PARTNER-2045; validate the sum of interest and principal
                        if int(total_interest) + int(loan_amount) != due_amount:
                            total_interest = due_amount - int(loan_amount)
                            logger.info(
                                {
                                    'action': 'generate_loan_payment_mf',
                                    'loan_id': loan.id,
                                    'total_interest': total_interest,
                                    'due_amount': due_amount,
                                    'loan_amount': int(loan_amount),
                                    'message': 'validate sum interest and principal',
                                }
                            )

                        payment = Payment(
                            loan=loan,
                            payment_status=payment_status,
                            payment_number=1,
                            due_date=due_date,
                            due_amount=due_amount,
                            installment_principal=loan_amount,
                            installment_interest=total_interest)
                        bulk_payment.append(payment)

                        loan.update_safely(first_installment_amount=payment.due_amount,
                                           installment_amount=payment.due_amount)

            Payment.objects.bulk_create(bulk_payment, batch_size=25)
        return loan


def create_mf_sphp(application, loan, account_limit=None):
    partner_name = application.partner.name
    document = Document.objects.get_or_none(
        document_source=loan.id,
        document_type=f"{partner_name.lower()}_skrtp"
    )
    if document:
        return "document has found"

    template = get_mf_skrtp_content(application, loan, account_limit)
    if not template:
        return "SKRTP template not found"

    now = timezone.localtime(timezone.now()).date()
    filename = '{}_{}_{}_{}.pdf'.format(
        application.fullname,
        loan.loan_xid,
        now.strftime("%Y%m%d"),
        now.strftime("%H%M%S"))
    file_path = os.path.join(tempfile.gettempdir(), filename )

    try:
        pdfkit.from_string(template, file_path)
    except Exception:
        return "failed created PDF"

    sphp_julo = Document.objects.create(
        document_source=loan.id,
        document_type=f"{partner_name.lower()}_skrtp",
        filename=filename,
        loan_xid=loan.loan_xid
    )
    upload_document(sphp_julo.id, file_path, is_loan=True)
    return "success create PDF"


def process_create_self_bank_account_destination(application):
    customer = application.customer
    bank_account_category = BankAccountCategory.objects.filter(
        category=BankAccountCategoryConst.SELF,
    ).last()

    if not bank_account_category:
        raise Exception('kategori akun bank tidak ditemukan')
    bank = Bank.objects.filter(xfers_bank_code=application.name_bank_validation.bank_code).last()

    BankAccountDestination.objects.create(
        bank_account_category=bank_account_category,
        customer=customer,
        bank=bank,
        account_number=application.bank_account_number,
        name_bank_validation=application.name_bank_validation,
    )


def upgrade_efishery_customers(
    application_xid: str, new_limit: int, partner: Partner
) -> Tuple[bool, str]:
    application = (
        Application.objects.filter(application_xid=application_xid).select_related("account").last()
    )
    if not application:
        return (False, "Application not found with application_xid: {}".format(application_xid))

    if application.application_status_id != ApplicationStatusCodes.LOC_APPROVED:
        return (False, "Application status is not 190: {}".format(application_xid))

    if application.account.status_id != AccountConstant.STATUS_CODE.active:
        return (False, "Account status is not 420: {}".format(application_xid))

    if not application.partner:
        return (False, "Application doesn't have a partner")

    # 'Efishery Kabayan Lite' can only be upgraded from the 'Efishery' application
    if partner.name == MerchantFinancingCSVUploadPartner.EFISHERY_KABAYAN_LITE:
        if application.partner.name != MerchantFinancingCSVUploadPartner.EFISHERY:
            return (False, "Application partner is not efishery")

    # 'Efishery Kabayan Regular' can only be upgraded from the 'Efishery Kabayan Lite' application
    if partner.name == MerchantFinancingCSVUploadPartner.EFISHERY_KABAYAN_REGULER:
        if application.partner.name != MerchantFinancingCSVUploadPartner.EFISHERY_KABAYAN_LITE:
            return (False, "Application partner is not efishery kabayan lite")

    # 'Efishery Kabayan Jawara' can only be upgraded from the 'Efishery Jawara' application
    if partner.name == MerchantFinancingCSVUploadPartner.EFISHERY_JAWARA:
        if application.partner.name != MerchantFinancingCSVUploadPartner.EFISHERY_KABAYAN_REGULER:
            return (
                False,
                "Application partner {} cannot be upgraded to {}".format(application.partner.name, partner.name)
            )

    if application.product_line != application.partner.product_line:
        return (False, "Product Line is not efishery")

    # can not upgrade to same product line
    if application.product_line == partner.product_line:
        return (False, "Product Line is already {}".format(partner.name))

    fdc_result = fdc_binary_check_merchant_financing_csv_upload(['fdc_inquiry_check'], application)
    if fdc_result is False:
        return (False, "Fail FDC Check: {}".format(application_xid))

    account_limit = application.account.accountlimit_set.last()
    if float(new_limit) < float(account_limit.set_limit):
        return (
            False,
            "New limit: {}; is smaller than current limit: {}".format(
                new_limit, account_limit.set_limit
            ),
        )

    product_line_max_amount = partner.product_line.max_amount

    if float(new_limit) > float(product_line_max_amount):
        return (
            False,
            "New limit: {}; is greater than max product line amount: {}".format(
                new_limit, product_line_max_amount
            )
        )

    new_available_limit = new_limit - account_limit.used_limit
    try:
        with transaction.atomic():
            account_limit.update_safely(
                max_limit=new_limit, set_limit=new_limit, available_limit=new_available_limit
            )

            application.update_safely(partner=partner, product_line=partner.product_line)
    except Exception as e:
        return (False, "Have exception when update: {}".format(e))

    return (True, "Success update limit and product line")


def update_mf_customer_adjust_limit(
    application_xid: str, new_limit: str, partner: Partner
) -> Tuple[bool, str]:
    application = Application.objects.filter(application_xid=application_xid).select_related("account").last()

    # Data validation
    if not application:
        return (False, "Application not found with application_xid: {}".format(application_xid))

    if application.application_status.status_code != ApplicationStatusCodes.LOC_APPROVED:
        return (False, "Application status is not 190: {}".format(application_xid))

    if not application.partner:
        return (False, "Application doesn't have a partner")

    if application.partner.name != partner.name:
        return (False, "Partner is not {}".format(partner.name))

    fdc_result = fdc_binary_check_merchant_financing_csv_upload(['fdc_inquiry_check'], application)
    if fdc_result is False:
        return (False, "Fail FDC Check: {}".format(application_xid))

    # Process upgrade account limit
    account_limit = application.account.accountlimit_set.last()
    old_available_limit = account_limit.available_limit
    old_set_limit = account_limit.set_limit
    old_max_limit = account_limit.max_limit

    try:
        with transaction.atomic():
            new_available_limit = int(new_limit) - account_limit.used_limit
            account_limit.update_safely(
                max_limit=new_limit, set_limit=new_limit, available_limit=new_available_limit
            )

            available_account_limit_history = AccountLimitHistory(
                account_limit=account_limit,
                field_name='available_limit',
                value_old=str(old_available_limit),
                value_new=str(account_limit.available_limit),
            )

            set_limit_account_limit_history = AccountLimitHistory(
                account_limit=account_limit,
                field_name='set_limit',
                value_old=str(old_set_limit),
                value_new=str(account_limit.set_limit),
            )

            max_limit_account_limit_history = AccountLimitHistory(
                account_limit=account_limit,
                field_name='max_limit',
                value_old=str(old_max_limit),
                value_new=str(account_limit.max_limit),
            )

            AccountLimitHistory.objects.bulk_create(
                [
                    available_account_limit_history,
                    set_limit_account_limit_history,
                    max_limit_account_limit_history,
                ]
            )

    except Exception as e:
        return (False, "Have exception when update: {}".format(e))

    return (True, "Success update limit and product line")


def axiata_mtl_fill_data_for_pusdafil(partner, application, loan):
    loan.refresh_from_db()
    loan.generate_xid()
    list_score = ['A', 'A-', 'B']
    random.shuffle(list_score)
    credit_score = CreditScore.objects.filter(application_id=application.id).first()
    if not credit_score:
        CreditScore.objects.create(
            application_id=application.id,
            score=list_score[0],
        )

    account_lookup = partner.accountlookup_set.first()
    account = loan.account
    if not account:
        account = Account.objects.create(
            customer=application.customer,
            status_id=AccountConstant.STATUS_CODE.active,
            account_lookup=account_lookup,
            cycle_day=0,
        )

        is_proven = get_is_proven()
        input_params = dict(
            account=account,
            pgood=0.0,
            p0=0.0,
            is_salaried=get_salaried(application.job_type),
            is_proven=is_proven,
            is_premium_area=is_inside_premium_area(application),
            proven_threshold=get_proven_threshold(loan.loan_amount),
            voice_recording=get_voice_recording(is_proven),
            concurrency=True,
        )
        account_property = AccountProperty.objects.create(**input_params)
        store_account_property_history(input_params, account_property)

    account_limit = AccountLimit.objects.filter(account=account).first()
    if account_limit:
        account_limit.update_safely(
            set_limit=loan.loan_amount,
        )
    else:
        AccountLimit.objects.create(account=account, set_limit=loan.loan_amount)

    payment = loan.payment_set.first()
    loan_duration = payment.due_date - payment.cdate.date()
    partner_loan_request = PartnerLoanRequest.objects.filter(loan=loan).first()
    if not partner_loan_request:
        PartnerLoanRequest.objects.create(
            loan=loan,
            partner=partner,
            loan_amount=loan.loan_amount,
            loan_disbursement_amount=loan.loan_disbursement_amount,
            loan_original_amount=loan.loan_amount,
            loan_duration_type='days',
        )

    transaction_method = TransactionMethod.objects.get(method=TransactionType.OTHER)

    application.account_id = account.id
    application.save(update_fields=["account_id"])

    loan.account = account
    loan.loan_duration = loan_duration.days
    loan.transaction_method = transaction_method
    loan.save()


def get_mtl_parameters_fs_check_other_active_platforms_using_fdc():
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.MTL_CHECK_OTHER_ACTIVE_PLATFORMS_USING_FDC,
        is_active=True,
    ).last()
    return feature_setting.parameters if feature_setting else None


def is_apply_check_other_active_platforms_using_fdc_mtl(
    application=None,
    parameters=None,
):
    """
    Parameter Application Object is used by partnership to check partner
    check whether application_id is applied check active loans using fdc or not
    :param application_nik:
    :param parameters: parameters of feature setting, if not pass in, will get from db
    :return: boolean
    """
    if parameters is None:
        parameters = get_mtl_parameters_fs_check_other_active_platforms_using_fdc()

    if not parameters:
        return False

    # when enable whitelist, only application_id in whitelist will be applied
    if parameters['whitelist']['is_active']:
        if application.ktp in parameters['whitelist']['list_nik']:
            return True
        else:
            return False

    # when enable bypass, only application_id NOT in bypass list will be applied
    if parameters['bypass']['is_active']:
        if FDCPlatformCheckBypass.objects.filter(application_id=application.id).exists():
            return False

        if application.ktp in parameters['bypass']['list_nik']:
            return False

    # if the above conditions are not met, always apply check active loans using fdc
    return True


def is_eligible_other_active_platforms_for_mtl(
    application,
    fdc_data_outdated_threshold_days,
    number_of_allowed_platforms,
):
    customer_id = application.customer_id

    fdc_active_loan_checking, is_created = FDCActiveLoanChecking.objects.get_or_create(
        customer_id=customer_id
    )
    if not is_created:
        fdc_active_loan_checking.last_access_date = timezone.localtime(timezone.now()).date()
        fdc_active_loan_checking.save()

    if fdc_active_loan_checking.product_line_id != application.product_line_id:
        fdc_active_loan_checking.product_line_id = application.product_line_id
        fdc_active_loan_checking.save()

    if Loan.objects.filter(
        customer_id=customer_id,
        loan_status_id__gte=LoanStatusCodes.CURRENT,
        loan_status_id__lt=LoanStatusCodes.PAID_OFF,
    ).exists():
        # when already had active loans, return True to allow to create another loan
        return True

    fdc_inquiries, fdc_inquiry_ids = mtl_get_or_non_fdc_inquiry_not_out_date(
        nik=application.ktp, day_diff=fdc_data_outdated_threshold_days
    )
    if not fdc_inquiries:
        # return True to continue the loan to x210, cronjob will update the status before go to x211
        return True

    _, count_other_platforms, _ = mtl_get_info_active_loan_from_platforms(
        fdc_inquiry_ids=fdc_inquiry_ids
    )

    fdc_active_loan_checking.number_of_other_platforms = count_other_platforms
    fdc_active_loan_checking.save()

    if count_other_platforms < number_of_allowed_platforms:
        return True

    mtl_create_tracking_record_when_customer_get_rejected(
        customer_id, fdc_inquiries, count_other_platforms
    )

    return False


def mtl_get_or_non_fdc_inquiry_not_out_date(nik: str, day_diff: int):
    """
    :params nik
    :params day_diff: it's from fs. used to check data is out of date or not.
    """
    fdc_inquiry_list = []
    fdc_inquiry_ids = []
    fdc_inquiries = FDCInquiry.objects.filter(nik=nik, inquiry_status='success')

    for fdc_inquiry in fdc_inquiries:
        if day_diff:
            day_after_day_diff = timezone.now().date() - relativedelta(days=day_diff)
            if not fdc_inquiry or fdc_inquiry.udate.date() < day_after_day_diff:
                continue
            else:
                fdc_inquiry_list.append(fdc_inquiry)
                fdc_inquiry_ids.append(fdc_inquiry.id)

    return fdc_inquiry_list, fdc_inquiry_ids


def mtl_get_info_active_loan_from_platforms(fdc_inquiry_ids):
    """
    Check data from FDC to know the user has how many active loans from platforms
    :params fdc_inquiry_id: it's from FDCInquiry
    """

    fdc_inquiry_loans = (
        FDCInquiryLoan.objects.filter(fdc_inquiry_id__in=fdc_inquiry_ids, is_julo_loan__isnull=True)
        .filter(status_pinjaman=FDCLoanStatus.OUTSTANDING)
        .values('id_penyelenggara', 'tgl_jatuh_tempo_pinjaman')
        .order_by('tgl_jatuh_tempo_pinjaman')
    )

    count_platforms = len(set([inquiry['id_penyelenggara'] for inquiry in fdc_inquiry_loans]))
    nearest_due_date = (
        fdc_inquiry_loans[0]['tgl_jatuh_tempo_pinjaman'] if fdc_inquiry_loans else None
    )
    count_active_loans = len(fdc_inquiry_loans)

    return nearest_due_date, count_platforms, count_active_loans


@transaction.atomic
def mtl_create_tracking_record_when_customer_get_rejected(
    customer_id, fdc_inquiries, number_other_platforms
):
    rejected_date = timezone.localtime(timezone.now()).date()

    existing_fdc_inquiry_ids = FDCRejectLoanTracking.objects.filter(
        customer_id=customer_id,
        rejected_date=rejected_date,
        fdc_inquiry_id__in=[fdc_inquiry.id for fdc_inquiry in fdc_inquiries],
    ).values_list('fdc_inquiry_id', flat=True)

    new_records = []
    for fdc_inquiry in fdc_inquiries:
        if fdc_inquiry.id not in existing_fdc_inquiry_ids:
            new_records.append(
                FDCRejectLoanTracking(
                    customer_id=customer_id,
                    rejected_date=rejected_date,
                    fdc_inquiry_id=fdc_inquiry.id,
                    number_of_other_platforms=number_other_platforms,
                )
            )

    FDCRejectLoanTracking.objects.bulk_create(new_records)


def insert_data_to_fdc(application):
    from juloserver.fdc.services import get_and_save_fdc_data

    nik = application.customer.nik

    fdc_inquiry = FDCInquiry(
        application_id=application.id,
        nik=nik,
        application_status_code=application.status,
        customer_id=application.customer.id,
    )
    fdc_inquiry.save()

    fdc_inquiry_data = {'id': fdc_inquiry.id, 'nik': nik}
    get_and_save_fdc_data(fdc_inquiry_data, 1, False)
