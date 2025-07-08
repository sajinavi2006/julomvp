import csv
import datetime
import io
import json
import logging
import os
import re
from itertools import chain

from django.conf import settings
from django.core.files import File
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Prefetch
from juloserver.account.models import (AccountLookup, AccountProperty,
                                       CreditLimitGeneration)
from juloserver.account.services.credit_limit import (
    get_credit_matrix, get_is_proven, get_proven_threshold, get_salaried,
    get_transaction_type, get_voice_recording, is_inside_premium_area,
    store_account_property_history, store_credit_limit_generated,
    store_related_data_for_generate_credit_limit,
    update_related_data_for_generate_credit_limit)
from juloserver.apiv2.models import AutoDataCheck
from juloserver.apiv2.serializers import ApplicationUpdateSerializer
from juloserver.apiv2.services import \
    remove_fdc_binary_check_that_is_not_in_fdc_threshold
from juloserver.customer_module.constants import BankAccountCategoryConst
from juloserver.customer_module.models import BankAccountCategory, BankAccountDestination
from juloserver.disbursement.constants import NameBankValidationStatus
from juloserver.employee_financing.constants import ProcessEFStatus, IMAGE_EXTENSION_FORMAT
from juloserver.employee_financing.exceptions import FailedUploadImageException
from juloserver.employee_financing.models import (
    Company,
    Employee,
    EmployeeFinancingFormURLEmailContent,
    EmFinancingWFAccessToken
)
from juloserver.employee_financing.serializers import (
    EmployeeSerializer,
    PilotUploadApplicationRegisterSerializer,
    PilotUploadDisbursementSerializer,
    PilotUploadRepaymentrSerializer,
    PreApprovalSerializer,
)
from juloserver.employee_financing.tasks.email_task import (
    send_email_sign_master_agreement_upload,
    send_email_at_rejected_for_pilot_ef_csv_upload,
    send_email_to_valid_employees)
from juloserver.employee_financing.utils import (
    employee_financing_format_data, format_phone_number, ef_pre_approval_format_data,
    create_or_update_token)
from juloserver.julo.constants import WorkflowConst, FeatureNameConst, UploadAsyncStateType
from juloserver.julo.models import (AffordabilityHistory, Application,
                                    ApplicationHistory, ApplicationNote, Bank,
                                    Customer, EmailHistory, Loan, ProductLine,
                                    Workflow, UploadAsyncState, MasterAgreementTemplate)
from juloserver.julo.services import (process_application_status_change)
from juloserver.julo.services2.payment_method import \
    generate_customer_va_for_julo_one
from juloserver.julo.statuses import ApplicationStatusCodes, LoanStatusCodes
from juloserver.julo.utils import upload_file_to_oss, check_email, upload_file_as_bytes_to_oss
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.tasks import create_application_checklist_async
from juloserver.pin.models import CustomerPin
from juloserver.pin.services import CustomerPinService
from juloserver.portal.object.bulk_upload.services import (
    get_julo_one_workflow_action, get_workflow_action, skippable_application_status_change)
from juloserver.julo.banks import BankManager

# Disbursement Import
import tempfile
import pdfkit

from babel.dates import format_date
from django.utils import timezone
from django.template.loader import render_to_string
from django.template import Template, Context


from juloserver.fdc.files import TempDir
from juloserver.loan.services.loan_related import (
    get_transaction_type as get_disbursement_transaction_type,
    determine_transaction_method_by_transaction_type,
    generate_loan_payment_julo_one
)

from juloserver.julo.models import (
    FeatureSetting,
    Document
)
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.loan.constants import LoanJuloOneConstant
from juloserver.loan.services.loan_related import get_loan_amount_by_transaction_type
from juloserver.account.models import AccountLimit
from juloserver.account.services.credit_limit import update_available_limit
from juloserver.loan.services.sphp import accept_julo_sphp
from juloserver.julo.tasks import upload_document
from juloserver.julo.utils import display_rupiah
from juloserver.account.constants import AccountConstant

from juloserver.account_payment.models import AccountPayment

# Repayment Import
import pytz
from datetime import (
    datetime, 
    timedelta
)

from juloserver.account_payment.services.payment_flow import process_repayment_trx
from juloserver.julo.models import PaybackTransaction
from juloserver.partnership.models import (
    PartnershipRepaymentUpload,
    PartnershipImage
)
from juloserver.partnership.constants import (
    PartnershipImageStatus,
    ErrorMessageConst,
    EFWebFormType,
    PartnershipImageProductType
)
from typing import List, Union

logger = logging.getLogger(__name__)


class ApplicationCheckException(Exception):
    pass


class CustomerCheckException(Exception):
    pass


class Application190Exception(Exception):
    pass


class Application190EFException(Exception):
    pass


class WrongStatusException(Exception):
    pass


class DuplicatedException(Exception):
    def __init__(self, application):
        self.application = application


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

approved_statuses = {
    ApplicationStatusCodes.LOC_APPROVED  # 190
}

CSV_HEADER = [
    'ktp number',
    'company_id',
    'fullname',
    'email',
    'jenis kelamin',
    'tempat lahir',
    'phone number',
    'ktp photo',
    'ktp selfie',
    'dob',
    'address',
    'province',
    'kabupaten',
    'kecamatan',
    'Kelurahan',
    'kodepos',
    'nama orang tua',
    'nomor hp orang tua',
    'nama pasangan',
    'nomor hp pasangan',
    'mulai perkerjaan',
    'tanggal gajian',
    'nama bank',
    'nomor rekening bank',
    'approved limit',
    'available limit',
    'interest',
    'provision fee',
    'late fee',
    'max tenor',
    'rejected reason',
    'application xid'
]

DISBURSEMENT_CSV_HEADER = [
    'ktp',
    'application xid',
    'disbursement request date',
    'disbursed date',
    'email',
    'amount request',
    'disbursed amount',
    'approved limit',
    'available limit',
    'tenor selected',
    'max tenor',
    'interest',
    'provision fee',
    'late fee',
    'loan_xid',
    'errors'
]

REPAYMENT_CSV_HEADER = [
    'account_payment_id',
    'application_xid',
    'full_name',
    'email',
    'paid_amount',
    'paid_date',
    'due_amount',
    'due_date',
    'errors'
]

PRE_APPROVAL_CSV_HEADERS = [
    'ktp number',
    'employer_id',
    'fullname',
    'email',
    'mulai perkerjaan',
    'selesai contract',
    'dob',
    'tanggal gajian',
    'Total penghasilan per bulan',
    'nama bank',
    'nomor rekening bank',
    'error'
]


def upload_csv_data_to_oss(upload_async_state, file_path=None):
    if file_path:
        local_file_path = file_path
    else:
        local_file_path = upload_async_state.file.path
    path_and_name, extension = os.path.splitext(local_file_path)
    file_name_elements = path_and_name.split('/')
    dest_name = "employee_financing{}/{}".format(upload_async_state.id,
                                                 file_name_elements[-1] + extension)
    upload_file_to_oss(settings.OSS_MEDIA_BUCKET, local_file_path, dest_name)

    if os.path.isfile(local_file_path):
        local_dir = os.path.dirname(local_file_path)
        upload_async_state.file.delete()
        if not file_path:
            os.rmdir(local_dir)

    upload_async_state.update_safely(url=dest_name)


def create_ef_application_and_upload_result(upload_async_state):
    upload_file = upload_async_state.file
    f = io.StringIO(upload_file.read().decode('utf-8'))
    reader = csv.DictReader(f, delimiter=',')

    is_success_all = True
    local_file_path = upload_async_state.file.path
    with open(local_file_path, "w", encoding='utf-8-sig') as f:
        write = csv.writer(f)
        write.writerow(CSV_HEADER)
        j1_workflow = Workflow.objects.get(name=WorkflowConst.JULO_ONE)
        ef_product_line = ProductLine.objects.get(
            product_line_type="employee financing")
        company_list = Company.objects.all().select_related('partner').values('id', 'partner_id')
        fraud_app_history_queryset = ApplicationHistory.objects.select_related().filter(
            status_new=ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD
        ).values('id', 'application', 'application__ktp', 'application__mobile_phone_1', 'application__email')
        app_q = Application.objects.all()
        customer_q = Customer.objects.all()
        acc_limit_q = AccountLimit.objects.all()
        company_dict = dict((company['id'], company) for company in company_list)
        bank_names = BankManager.get_bank_names()
        for row in reader:
            clean_row = {key.lower().strip(): value for key, value in row.items()}
            formated_data = employee_financing_format_data(clean_row)
            serializer = PilotUploadApplicationRegisterSerializer(data=formated_data)
            if serializer.is_valid():
                try:
                    nik = formated_data.get('ktp')
                    email = formated_data.get('email')
                    job_start = formated_data.get('job_start')
                    bank_name = formated_data.get('bank_name')

                    # validate bank name
                    if bank_name not in bank_names:
                        raise ApplicationCheckException(ProcessEFStatus.BANK_NAME_NOT_FOUND)

                    # re format phone numbers
                    formatted_phone_number = {'mobile_phone_1': format_phone_number(
                        formated_data.get('mobile_phone_1'))}
                    formatted_parent_mobile_number = {'close_kin_mobile_phone': format_phone_number(
                        formated_data.get('close_kin_mobile_phone'))}
                    formatted_couple_phone_number = {'spouse_mobile_phone': format_phone_number(
                        formated_data.get('spouse_mobile_phone'))}
                    phone_formatted_dict = dict(chain.from_iterable(d.items() for d in (
                        formatted_phone_number,
                        formatted_parent_mobile_number,
                        formatted_couple_phone_number
                    )))

                    # update formatted phone number datas
                    formated_data.update(phone_formatted_dict)
                    phone_number = formated_data.get('mobile_phone_1')

                    # init availabel limit
                    formated_data['available_limit'] = int(
                        re.sub("[ ,.]", "", formated_data.get('loan_amount_request')))

                    # fraud application history check
                    ef_fraud_history_check(fraud_app_history_queryset, nik, email, phone_number)

                    # check customer
                    customer = customer_q.filter(nik=nik).first()

                    # update available limit if customer account exist
                    if customer and customer.account:
                        formated_data['available_limit'] = acc_limit_q.filter(
                            account=customer.account
                        ).values("available_limit").first().get("available_limit")

                    # company check
                    company = company_dict.get(int(formated_data.get('company_id')))
                    if not company:
                        raise ApplicationCheckException(ProcessEFStatus.COMPANY_NOT_FOUND)
                    partner_id = company.get('partner_id')

                    # check is application exist for nik and company
                    excluded_statutes = graveyard_statuses | approved_statuses
                    existing_application = app_q.filter(
                        ktp=nik, company__pk=company.get('id')).last()
                    if existing_application and existing_application.application_status_id not in excluded_statutes:
                        raise DuplicatedException(existing_application)

                    # application check
                    ef_application_check(nik, email, phone_number)

                    if settings.ENVIRONMENT != 'prod':
                        formated_data.update({'fullname': 'PROD ONLY'})

                    # create customer if customer doesnt exists
                    if not customer:
                        user, user_created = User.objects.get_or_create(
                            username=nik,
                            defaults={'email': email},
                        )
                        if user_created:
                            password = User.objects.make_random_password()
                            user.set_password(password)
                            user.save()

                        customer = Customer.objects.create(
                            nik=nik,
                            fullname=formated_data.get('fullname'),
                            phone=phone_number,
                            user=user,
                        )

                    formated_data['customer'] = customer.id
                    formated_data['partner'] = partner_id
                    formated_data['company'] = company.get('id')
                    formated_data['job_type'] = "Pegawai swasta"
                    formated_data['is_own_phone'] = True
                    formated_data['name_in_bank'] = formated_data.get('fullname')
                    formated_data['job_start'] = job_start if job_start else '2021-01-01'
                    formated_data['monthly_income'] = int(
                        re.sub("[ ,.]", "", formated_data.get('monthly_income')))
                    formated_data['loan_amount_request'] = int(
                        re.sub("[ ,.]", "", formated_data.get('loan_amount_request')))
                    formated_data['loan_duration_request'] = int(
                        re.sub("[ ,.]", "", formated_data.get('loan_duration_request')))
                    application_serializer = ApplicationUpdateSerializer(data=formated_data)
                    application_serializer.is_valid(raise_exception=True)
                    application = application_serializer.save()
                    application.workflow = j1_workflow
                    application.product_line = ef_product_line
                    application.save()

                    # update available limit after application created.
                    if application.account:
                        formated_data['available_limit'] = acc_limit_q.filter(
                            account=application.account).values("available_limit").first().get("available_limit")

                    # check and create employee
                    employee = Employee.objects.filter(
                        company_id=formated_data.get('company'), customer_id=formated_data.get('customer')).last()
                    if not employee:
                        formated_data['net_salary'] = formated_data.get('monthly_income')
                        formated_data['limit_to_be_given'] = formated_data.get('loan_amount_request')
                        employee_serializer = EmployeeSerializer(data=formated_data)
                        employee_serializer.is_valid(raise_exception=True)
                        employee = employee_serializer.save()

                    customer_pin = CustomerPin.objects.filter(user=customer.user).last()
                    if not customer_pin:
                        customer_pin_service = CustomerPinService()
                        customer_pin_service.init_customer_pin(customer.user)
                    write.writerow(write_row_result(
                        formated_data, application_xid=application.application_xid))

                    # construct note for sphp email later
                    note_dict = {
                        "approved_limit": formated_data.get('loan_amount_request'),
                        "interest": formated_data.get('interest'),
                        "provision_fee": formated_data.get('provision_fee'),
                        "late_fee": formated_data.get('late_fee'),
                        "max_tenor": formated_data.get('loan_duration_request')
                    }
                    constructed_note = json.dumps(note_dict)

                    # change application status to 100
                    process_application_status_change(
                        application.id, ApplicationStatusCodes.FORM_CREATED,
                        change_reason='system_triggered'
                    )
                    create_application_checklist_async.delay(application.id)
                    validate_step(application, 100)

                    # change application status to 105
                    process_application_status_change(
                        application.id, ApplicationStatusCodes.FORM_PARTIAL,
                        change_reason='system_triggered',
                        note=constructed_note
                    )
                except Exception as err_msg:
                    if isinstance(err_msg, Application190Exception):
                        write.writerow(write_row_result(
                            formated_data,
                            rejected_reason='Application already approved in J1/MTL/MF/....',
                            application_xid=str(err_msg)
                        ))
                        logger.info({
                            'action': 'create_ef_application_upload_result',
                            'error': 'application already approved in J1/MTL/MF/....',
                            'application_xid': str(err_msg),
                        })
                    elif isinstance(err_msg, Application190EFException):
                        # if application already approved in employee financing
                        write.writerow(write_row_result(
                            formated_data,
                            rejected_reason='Application already approved in Employee Financing',
                            application_xid=str(err_msg)
                        ))
                        logger.info({
                            'action': 'create_ef_application_upload_result',
                            'error': 'application already approved in Employee Financing',
                            'application_xid': str(err_msg),
                        })
                    elif isinstance(err_msg, DuplicatedException):
                        write.writerow(write_row_result(
                            formated_data,
                            rejected_reason='',
                            application_xid=str(err_msg.application.application_xid)
                        ))
                        logger.info({
                            'action': 'create_ef_application_upload_result',
                            'error': 'application already exist in Employee Financing',
                            'application_xid': str(err_msg.application.application_xid),
                        })
                        run_employee_financing_upload_csv(err_msg.application)
                    else:
                        error_str = str(err_msg)
                        logger.error({
                            'action': 'create_ef_application_upload_result',
                            'error': error_str
                        })
                        is_success_all = False

                        if not 'NoneType' in error_str:
                            write.writerow(write_row_result(formated_data, err_msg))

                            # check and send rejected email
                            today = timezone.localtime(timezone.now())
                            start_of_day = today.replace(hour=0, minute=0, second=0, microsecond=0)
                            end_of_day = start_of_day + timedelta(days=1)
                            sended_rejected_email_today = EmailHistory.objects.filter(
                                cdate__gte=start_of_day,
                                cdate__lt=end_of_day,
                                to_email=formated_data.get("email"),
                                template_code='employee_financing_rejected_email'
                            ).exists()
                            if not sended_rejected_email_today:
                                send_email_at_rejected_for_pilot_ef_csv_upload.delay(
                                    formated_data.get("fullname"), formated_data.get("email"))
            else:
                is_success_all = False
                write.writerow(write_row_result(formated_data, serializer.errors))
    upload_csv_data_to_oss(upload_async_state)
    return is_success_all


def write_row_result(row, rejected_reason=None, application_xid=None, type='Register'):
    if type == 'Register':
        return [
            row['ktp'], row['company_id'], row['fullname'], row['email'], row['gender'],
            row['birth_place'], row['mobile_phone_1'], row['ktp_photo'], row['ktp_selfie'],
            row['dob'], row['address_street_num'], row['address_provinsi'], row['address_kabupaten'],
            row['address_kecamatan'], row['address_kelurahan'], row['address_kodepos'], row['close_kin_name'],
            row['close_kin_mobile_phone'], row['spouse_name'], row['spouse_mobile_phone'],
            row['job_start'], row['payday'], row['bank_name'], row['bank_account_number'],
            row['loan_amount_request'], row['available_limit'], row['interest'], row['provision_fee'],
            row['late_fee'], row['loan_duration_request'], rejected_reason, application_xid
        ]
    elif type == 'Disbursement':
        return [
            row.get('ktp'), row.get('application_xid'), row.get('date_request_disbursement'), row.get('disbursed_date'),
            row.get('email'), row.get('loan_amount_request'), row.get('disbursed_amount'), row.get('approved_limit'),
            row.get('available_limit'), row.get('loan_duration'), row.get('max_tenor'), row.get('interest_rate'),
            row.get('origination_fee_pct'), row.get('late_fee'), row.get('loan_xid'), row.get('errors')
        ]
    elif type == UploadAsyncStateType.EMPLOYEE_FINANCING_PRE_APPROVAL:
        return [
            row['ktp'], row['company_id'], row['fullname'], row['email'], row['job_start'],
            row['contract_end'], row['dob'], row['payday'], row['monthly_income'], row['bank_name'],
            row['bank_account_number'], rejected_reason
        ]
    else:
        return row.values()


def ef_application_check(nik, email, phone_number):
    application_q = Application.objects.all()
    application_history_prefetch = Prefetch(
        'application_set__applicationhistory_set',
        queryset=ApplicationHistory.objects.filter(status_new=190),
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
        'application_set', queryset=application_q, to_attr='applications'
    )
    customer = Customer.objects.prefetch_related(
        application_prefetch, application_history_prefetch, loan_prefetch).filter(
        nik=nik
    ).last()

    not_graveyard_application_q = application_q.exclude(
        application_status_id__in=list(graveyard_statuses)
    )

    if customer:
        applications = customer.applications
        existing_app_190 = customer.application_set.filter(
            application_status=190).values('application_xid', 'product_line').first()
        if existing_app_190 and existing_app_190.get('product_line') != ProductLineCodes.EMPLOYEE_FINANCING:
            raise Application190Exception(existing_app_190.get('application_xid'))
        elif existing_app_190 and existing_app_190.get('product_line') == ProductLineCodes.EMPLOYEE_FINANCING:
            raise Application190EFException(existing_app_190.get('application_xid'))
        for application in applications:
            if application.application_status_id not in graveyard_statuses:
                raise ApplicationCheckException('Ongoing application already exists.')
            if customer.loans:
                raise ApplicationCheckException('Ongoing loan already exist')

    # check email exist in other application who dont have graveyard statuses
    email_in_application_exist = not_graveyard_application_q.filter(email=email).exists()
    if email_in_application_exist:
        raise ApplicationCheckException('Email is used before.')

    # check phone number exist in other application who dont have graveyard statuses
    phone_in_application_exist = not_graveyard_application_q.filter(
        mobile_phone_1=phone_number).exists()
    if phone_in_application_exist:
        raise ApplicationCheckException('Phone number is used before.')


def ef_fraud_history_check(fraud_app_history_queryset, nik, email, phone_number):
    if fraud_app_history_queryset.filter(application__ktp=nik).exists():
        raise ApplicationCheckException('Fraud history exist')

    if fraud_app_history_queryset.filter(application__mobile_phone_1=phone_number).exists():
        raise ApplicationCheckException('Fraud history exist')

    if fraud_app_history_queryset.filter(application__email=email).exists():
        raise ApplicationCheckException('Fraud history exist')


def update_ef_upload_status_105_to_124(application):
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

    fdc_result = fdc_binary_check_employee_financing(['fdc_inquiry_check'], application)

    if fdc_result is False:
        process_application_status_change(
            application.id, ApplicationStatusCodes.APPLICATION_DENIED,
            change_reason='failed_fdc'
        )
        return

    with transaction.atomic():
        skippable_application_status_change(
            application, ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL,
            change_reason='system_triggered'
        )

        application.refresh_from_db()
        try:
            action = get_workflow_action(application)
            action.process_validate_bank()
        except Exception as e:
            logger.error({
                'action': 'update_ef_upload_status_105_to_124',
                'error': str(e)
            })

    update_ef_upload_status_124_to_130(application)


def update_ef_upload_status_124_to_130(application):
    validate_step(application, 124)
    validation_status = application.name_bank_validation.validation_status
    if validation_status in {
        NameBankValidationStatus.NAME_INVALID,
        NameBankValidationStatus.INITIATED}:
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
        app_note = ApplicationNote.objects.filter(application_id=application.id).last()
        app_note_dict = json.loads(app_note.note_text)
        limit = int(app_note_dict.get("approved_limit"))
        if not limit:
            raise Exception('Limit is invalid')
        with transaction.atomic():
            skippable_application_status_change(
                application, ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
                change_reason='system_triggered'
            )

            try:
                process_ef_credit_limit_generation(application, limit, limit)
                generate_customer_va_for_julo_one(application)
                process_create_self_bank_account_destination(application)
            except Exception as e:
                logger.error({
                    'action': 'update_ef_upload_status_124_to_130',
                    'error': str(e)
                })

        update_ef_upload_status_130_to_190(application)
    else:
        raise Exception("NameBankValidation pending")


def update_ef_upload_status_130_to_190(application):
    validate_step(application, 130)
    if application.customer.account_set.last():
        skippable_application_status_change(
            application, ApplicationStatusCodes.LOC_APPROVED,
            change_reason='system_triggered'
        )
        # process_julo_one_at_190
        action = get_julo_one_workflow_action(application)
        action.process_julo_one_at_190()

        # Send master agreement
        send_email_sign_master_agreement_upload.delay(application.id)


class EFCreditModelResult():
    pgood = 0.8


def fdc_binary_check_employee_financing(failed_checks, application):
    credit_model_result = EFCreditModelResult
    _failed_checks, fdc_result = remove_fdc_binary_check_that_is_not_in_fdc_threshold(
        credit_model_result,
        failed_checks,
        application
    )
    return fdc_result


def process_ef_credit_limit_generation(application, max_limit, set_limit):
    generate_credit_limit_employee_financing(application, max_limit)
    account = application.customer.account_set.last()
    if not account:
        store_related_data_for_generate_credit_limit(application, max_limit, set_limit)
        application.refresh_from_db()

        # generate account_property and history
        store_account_property_employee_financing(application, set_limit)
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


def generate_credit_limit_employee_financing(application, limit):
    affordability_history = AffordabilityHistory.objects.create(
        application_id=application.id,
        application_status=application.application_status,
        affordability_value=0.8,
        affordability_type='',
        reason='employee financing'
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
    reason = "130 Employee Financing Credit Limit Generation"

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


def store_account_property_employee_financing(application, set_limit):
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


def run_employee_financing_upload_csv(application):
    try:
        try:
            update_ef_upload_status_105_to_124(application)
        except WrongStatusException:
            pass

        try:
            update_ef_upload_status_124_to_130(application)
        except WrongStatusException:
            pass

        try:
            update_ef_upload_status_130_to_190(application)
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


def disburse_employee_financing(upload_async_state):
    upload_file = upload_async_state.file
    freader = io.StringIO(upload_file.read().decode('utf-8'))
    reader = csv.DictReader(freader, delimiter=',')

    is_success_all = True
    local_file_path = upload_async_state.file.path

    with TempDir(dir="/media") as tempdir:
        path_and_name, extension = os.path.splitext(local_file_path)
        file_name_elements = path_and_name.split('/')
        filename = file_name_elements[-1] + extension
        dir_path = tempdir.path
        file_path = os.path.join(dir_path, filename)
        with open(file_path, "w", encoding='utf-8-sig') as f:
            write = csv.writer(f)
            write.writerow(DISBURSEMENT_CSV_HEADER)

            feature_setting = FeatureSetting.objects.filter(
                feature_name=LoanJuloOneConstant.PHONE_NUMBER_BLACKLIST,
                is_active=True).last()
            application_xids = []
            for row in reader:
                if row['application xid'] and row['application xid'].isnumeric():
                    application_xids.append(row['application xid'])

            account_payment_prefetch = Prefetch(
                'account__accountpayment_set',
                queryset=AccountPayment.objects.filter(
                    status__in=[
                        PaymentStatusCodes.PAYMENT_NOT_DUE,
                        PaymentStatusCodes.PAYMENT_DUE_IN_3_DAYS,
                        PaymentStatusCodes.PAYMENT_DUE_TODAY,
                        PaymentStatusCodes.PAYMENT_DUE_IN_1_DAYS,
                        PaymentStatusCodes.PAYMENT_1DPD,
                        PaymentStatusCodes.PAYMENT_5DPD,
                        PaymentStatusCodes.PAYMENT_30DPD,
                        PaymentStatusCodes.PAYMENT_60DPD,
                        PaymentStatusCodes.PAYMENT_90DPD,
                        PaymentStatusCodes.PAYMENT_120DPD,
                        PaymentStatusCodes.PAYMENT_150DPD,
                        PaymentStatusCodes.PAYMENT_180DPD,
                    ]
                ).order_by('due_date'),
                to_attr='account_payments'
            )
            bank_account_destination_prefetch = Prefetch(
                'customer__bankaccountdestination_set',
                queryset=BankAccountDestination.objects.all(),
                to_attr='bank_account_destinations'
            )
            loan_prefetch = Prefetch(
                'account__loan_set',
                queryset=Loan.objects.filter(
                    loan_status=LoanStatusCodes.INACTIVE
                ),
                to_attr='loans'
            )
            prefetch_join_tables = [
                account_payment_prefetch,
                bank_account_destination_prefetch,
                loan_prefetch
            ]
            applications = Application.objects.filter(
                application_xid__in=application_xids
            ).select_related(
                'partner', 'account', 'product_line', 'customer', 'company__companyconfig'
            ).prefetch_related(*prefetch_join_tables)

            application_dict = dict()
            for application in applications:
                application_dict[application.application_xid] = application
            freader.seek(0)
            reader.__init__(freader, delimiter=',')

            for row in reader:
                clean_row = {key.strip(): value for key, value in row.items()}
                formated_data = employee_financing_format_data(clean_row, 'Disbursement')
                serializer = PilotUploadDisbursementSerializer(data=formated_data)
                if serializer.is_valid():
                    try:
                        application = application_dict.get(serializer.validated_data['application_xid'])
                        if not application:
                            raise Exception('application not found')
                        if application.product_line_code != ProductLineCodes.EMPLOYEE_FINANCING:
                            raise Exception('application product line is not employee financing')
                        if application.application_status_id != ApplicationStatusCodes.LOC_APPROVED:
                            raise Exception('application not yet 190')

                        account = application.account
                        if account is None:
                            raise Exception('account is not exists')
                        with transaction.atomic():
                            # Need to select_for_update to remove posibility the account limit to be use
                            # even though the limit already 0
                            account_limit = AccountLimit.objects.select_for_update().filter(
                                account=account).last()
                            if not account_limit:
                                raise Exception('Account Limit is not exists')
                            formated_data['approved_limit'] = account_limit.set_limit
                            formated_data['available_limit'] = account_limit.available_limit

                            if account.status_id not in {AccountConstant.STATUS_CODE.active,
                                                         AccountConstant.STATUS_CODE.active_in_grace}:
                                raise Exception('the account status is not active or not active in grace')
                            if account.account_payments and account.account_payments[0].dpd > 5:
                                raise Exception('has existing loans past grace period')
                            if account.loans:
                                raise Exception('has existing inactive loan')

                            mobile_number = application.mobile_phone_1
                            if mobile_number and feature_setting:
                                params = feature_setting.parameters
                                blacklist_phone_number = params['blacklist_phone_numnber']
                                if mobile_number in blacklist_phone_number:
                                    raise Exception('Invalid phone number')

                            product = application.product_line.productlookup_set.filter(
                                interest_rate=serializer.validated_data['interest_rate'],
                                origination_fee_pct=serializer.validated_data['origination_fee_pct'],
                            ).last()
                            if not product:
                                raise Exception('Product not found')

                            # There is a posibility of customer have a multiple bank account destination
                            # So we need to look every bank account destination that customer have
                            # and compare it with bank account number in application.bank_account_number
                            customer = application.customer
                            bank_account_destination = None
                            for bank_account_destination in customer.bank_account_destinations:
                                if bank_account_destination.account_number == application.bank_account_number:
                                    break
                                bank_account_destination = None  # If the bank_account_number is not equal, reset to None

                            if not bank_account_destination:
                                raise Exception('Bank account destination not found')

                            allow_disburse_config = True
                            if hasattr(application.company, 'companyconfig'):
                                allow_disburse_config = application.company.companyconfig.allow_disburse

                            loan_duration = serializer.validated_data['loan_duration']
                            if loan_duration > serializer.validated_data['max_tenor']:
                                if allow_disburse_config:
                                    loan_duration = serializer.validated_data['max_tenor']
                                    formated_data['errors'] = formated_data[
                                                                  'errors'] + ' - ' + 'Max tenor is use as loan duration'
                                else:
                                    raise Exception(
                                        'Tenor selected is exceed Max Tenor'
                                    )

                            if serializer.validated_data['loan_amount_request'] > account_limit.available_limit:
                                if allow_disburse_config:
                                    if account_limit.available_limit >= 300000:
                                        serializer.validated_data['loan_amount_request'] = account_limit.available_limit
                                        formated_data['errors'] = formated_data[
                                                                      'errors'] + ' - ' + 'Disburse with current available limit: %s' % display_rupiah(
                                            account_limit.available_limit)
                                    else:
                                        raise Exception(
                                            'Jumlah pinjaman tidak boleh lebih besar dari limit tersedia'
                                        )
                                else:
                                    raise Exception(
                                        'Amount request is exceeded current limit'
                                    )

                            data = dict(
                                loan_amount_request=serializer.validated_data['loan_amount_request'],
                                account_id=account.id,
                                loan_duration=loan_duration,
                                bank_account_number=application.bank_account_number,
                                self_bank_account=True,
                                loan_purpose=application.loan_purpose,
                                bank_account_destination_id=bank_account_destination.id,
                            )

                            loan_amount = get_loan_amount_by_transaction_type(
                                serializer.validated_data['loan_amount_request'],
                                serializer.validated_data['origination_fee_pct'],
                                data['self_bank_account']
                            )

                            loan_requested = dict(
                                loan_amount=int(loan_amount),
                                original_loan_amount_requested=serializer.validated_data['loan_amount_request'],
                                loan_duration_request=int(data['loan_duration']),
                                interest_rate_monthly=product.monthly_interest_rate,
                                is_buku_warung=False,
                                product=product,
                                provision_fee=serializer.validated_data['origination_fee_pct'],
                                is_withdraw_funds=data['self_bank_account'],
                                is_loan_amount_adjusted=True
                            )
                            loan_purpose = data['loan_purpose']
                            loan = generate_loan_payment_julo_one(
                                application, loan_requested, loan_purpose,
                                None, bank_account_destination
                            )
                            transaction_type = get_disbursement_transaction_type(
                                data['self_bank_account'], False, bank_account_destination)
                            transaction_method = determine_transaction_method_by_transaction_type(
                                transaction_type)

                            loan.update_safely(transaction_method=transaction_method)
                            update_available_limit(loan)

                        create_employee_financing_sphp(application, loan)
                        accept_julo_sphp(loan, "JULO")
                        loan.refresh_from_db()
                        formated_data['approved_limit'] = account_limit.set_limit
                        formated_data['available_limit'] = account_limit.available_limit
                        formated_data['disbursed_amount'] = loan.loan_disbursement_amount
                        formated_data['disbursed_date'] = loan.cdate
                        formated_data['loan_xid'] = loan.loan_xid
                        write.writerow(write_row_result(
                            formated_data, type='Disbursement'))
                    except Exception as e:
                        logger.error({
                            'action': 'disburse_employee_financing_upload_result',
                            'error': str(e)
                        })
                        is_success_all = False
                        formated_data['loan_xid'] = ''
                        formated_data['errors'] = str(e)
                        write.writerow(write_row_result(
                            formated_data, rejected_reason=str(e), type='Disbursement'))
                else:
                    logger.error({
                        'action': 'disburse_employee_financing_upload_result',
                        'error': serializer.errors
                    })
                    is_success_all = False
                    formated_data['loan_xid'] = ''
                    formated_data['errors'] = formated_data['errors'] + ' - ' + str(serializer.errors)
                    write.writerow(write_row_result(
                        formated_data, rejected_reason=serializer.errors, type='Disbursement')
                    )
        upload_csv_data_to_oss(upload_async_state, file_path=file_path)
    return is_success_all


def create_employee_financing_sphp(application, loan):
    document = Document.objects.get_or_none(
        document_source=loan.id,
        document_type="employee_financing_sphp"
    )
    if document:
        return "document has found"

    template = get_employee_financing_sphp_content(loan)
    now = timezone.localtime(timezone.now()).date()
    filename = '{}_{}_{}_{}.pdf'.format(
        application.fullname,
        loan.loan_xid,
        now.strftime("%Y%m%d"),
        now.strftime("%H%M%S"))
    file_path = os.path.join(tempfile.gettempdir(), filename)

    try:
        pdfkit.from_string(template, file_path)
    except Exception:
        raise "failed created PDF"

    sphp_julo = Document.objects.create(
        document_source=loan.id,
        document_type='employee_financing_sphp',
        filename=filename,
        loan_xid=loan.loan_xid
    )
    upload_document(sphp_julo.id, file_path, is_loan=True)
    return "success create PDF"


def get_employee_financing_sphp_content(loan):
    from juloserver.loan.services.sphp import get_loan_type_sphp_content

    if not loan:
        return None
    loan_type = get_loan_type_sphp_content(loan)
    lender = loan.lender
    pks_number = '1.JTF.201707'
    if lender and lender.pks_number:
        pks_number = lender.pks_number
    sphp_date = loan.sphp_sent_ts
    application = loan.account.application_set.last()
    account_limit = loan.account.accountlimit_set.only('available_limit').last()
    context = {
        'loan': loan,
        'application': application,
        'dob': format_date(application.dob, 'dd-MM-yyyy', locale='id_ID'),
        'full_address': application.full_address,
        'company': application.company.name,
        'loan_amount': display_rupiah(loan.loan_amount),
        'late_fee_amount': display_rupiah(loan.late_fee_amount),
        'julo_bank_name': loan.julo_bank_name,
        'julo_bank_code': '-',
        'julo_bank_account_number': loan.julo_bank_account_number,
        'date_today': format_date(sphp_date, 'd MMMM yyyy', locale='id_ID'),
        'background_image': settings.SPHP_STATIC_FILE_PATH + 'julo-a-4@3x.png',
        'julo_image': settings.SPHP_STATIC_FILE_PATH + 'scraoe-copy-3@3x.png',
        'agreement_letter_number': pks_number,
        'available_limit': display_rupiah(account_limit.available_limit),
        'loan_type': loan_type
    }

    payments = loan.payment_set.exclude(is_restructured=True).order_by('id')

    for payment in payments:
        payment.due_date = format_date(payment.due_date, 'd MMM yy', locale='id_ID')
        payment.due_amount = display_rupiah(payment.due_amount + payment.paid_amount)
    context['payments'] = payments
    context['max_total_late_fee_amount'] = display_rupiah(loan.max_total_late_fee_amount)
    context['provision_fee_amount'] = display_rupiah(loan.provision_fee())
    context['interest_rate'] = '{}%'.format(loan.interest_percent_monthly())
    template = render_to_string(
        'sphp_pilot_employee_financing_disbursement_upload_template.html',
        context=context
    )

    return template


def ef_customer_check(email, phone_number, customer_queryset):
    email_exists = customer_queryset.filter(email=email).exists()
    if email_exists:
        raise CustomerCheckException('Email is used before')


def validate_step(application, status):
    application.refresh_from_db()
    if application.application_status_id != status:
        raise WrongStatusException(
            'Application ID %s status %s',
            (application.id, application.application_status_id)
        )


def repayment_employee_financing(upload_async_state):
    upload_file = upload_async_state.file
    freader = io.StringIO(upload_file.read().decode('utf-8'))
    reader = csv.DictReader(freader, delimiter=',')
    if not reader.fieldnames == REPAYMENT_CSV_HEADER[:-1]:
        raise Exception('Header is not valid')

    is_success_all = True
    local_file_path = upload_async_state.file.path

    with TempDir(dir="/media") as tempdir:
        path_and_name, extension = os.path.splitext(local_file_path)
        file_name_elements = path_and_name.split('/')
        filename = file_name_elements[-1] + extension
        dir_path = tempdir.path
        file_path = os.path.join(dir_path, filename)
        with open(file_path, "w", encoding='utf-8-sig') as f:
            write = csv.writer(f)
            write.writerow(REPAYMENT_CSV_HEADER)

            account_payment_ids = []
            for row in reader:
                if row['account_payment_id'] and row['account_payment_id'].isnumeric():
                    account_payment_ids.append(row['account_payment_id'])

            application_prefetch = Prefetch(
                'account__application_set',
                queryset=Application.objects.all(),
                to_attr='applications'
            )
            account_payments = AccountPayment.objects.filter(
                id__in=account_payment_ids
            ).select_related('account', 'account__customer').prefetch_related(application_prefetch)

            account_payment_dict = dict()
            for account_payment in account_payments:
                account_payment_dict[account_payment.id] = account_payment
            freader.seek(0)
            reader.__init__(freader, delimiter=',')

            parntership_repayment_uploads = []
            for row in reader:
                row['errors'] = ''
                clean_row = {key.strip(): value for key, value in row.items()}
                clean_row['fullname'] = row['full_name']
                clean_row['payment_date'] = row['paid_date']
                clean_row['payment_amount'] = row['paid_amount']
                serializer = PilotUploadRepaymentrSerializer(data=clean_row)
                if serializer.is_valid():
                    try:
                        account_payment = \
                            account_payment_dict.get(serializer.validated_data['account_payment_id'])
                        if not account_payment:
                            raise Exception('Account payment not found')
                        if not account_payment.account.applications:
                            raise Exception('Account payment have no application')
                        if account_payment.account.applications[0].application_xid != serializer.validated_data[
                            'application_xid']:
                            raise Exception('Application xid is not match with the account payment application')
                        if serializer.validated_data['email'] and account_payment.account.applications[0].email != \
                                serializer.validated_data['email']:
                            raise Exception('Email is not match with the account payment email')
                        if account_payment.status.status_code in PaymentStatusCodes.paid_status_codes():
                            raise Exception('Status for the account payment already paid')
                        if serializer.validated_data['payment_amount'] > account_payment.due_amount:
                            raise Exception('Paid amount exceed total due amount')

                        parntership_repayment_uploads.append(
                            PartnershipRepaymentUpload(
                                application_xid=serializer.validated_data['application_xid'],
                                payment_amount=serializer.validated_data['payment_amount'],
                                due_date=serializer.validated_data['due_date'] if serializer.validated_data[
                                    'due_date'] else None,
                                payment_date=serializer.validated_data['payment_date'],
                                account_payment_id=account_payment,
                            )
                        )

                        paid_date = datetime.strptime(
                            serializer.validated_data['payment_date'], '%Y-%m-%d')
                        with transaction.atomic():
                            local_timezone = pytz.timezone('Asia/Jakarta')
                            payback_transaction = PaybackTransaction.objects.create(
                                is_processed=False,
                                customer=account_payment.account.customer,
                                payback_service='employee financing upload',
                                status_desc='employee financing upload by crm',
                                transaction_date=local_timezone.localize(paid_date),
                                amount=serializer.validated_data['payment_amount'],
                                account=account_payment.account,
                            )
                            process_repayment_trx(payback_transaction)
                            account_payment.refresh_from_db(fields=['status', 'due_amount'])
                            write.writerow(write_row_result(row, type='Repayment'))
                    except Exception as e:
                        if not account_payment:
                            account_payment_id = None
                        else:
                            account_payment_id = serializer.validated_data['account_payment_id']
                        parntership_repayment_uploads.append(
                            PartnershipRepaymentUpload(
                                application_xid=serializer.validated_data['application_xid'],
                                payment_amount=serializer.validated_data['payment_amount'],
                                due_date=serializer.validated_data['due_date'] if serializer.validated_data[
                                    'due_date'] else None,
                                payment_date=serializer.validated_data['payment_date'],
                                account_payment_id_id=account_payment_id,
                                messages=e
                            )
                        )
                        is_success_all = False
                        row['errors'] = e
                        logger.error({"action": "employee_financing_repayment_log", "errors": e})
                        write.writerow(write_row_result(row, type='Repayment'))
                else:
                    if row['paid_date'] and 'payment_date' not in serializer.errors:
                        payment_date = row['paid_date']
                    else:
                        payment_date = None
                    if row['due_date'] and 'due_date' not in serializer.errors:
                        due_date = row['due_date']
                    else:
                        due_date = None

                    parntership_repayment_uploads.append(
                        PartnershipRepaymentUpload(
                            application_xid=clean_row[
                                'application_xid'] if 'application_xid' not in serializer.errors else 0,
                            payment_amount=row['paid_amount'] if 'payment_amount' not in serializer.errors else 0,
                            due_date=due_date,
                            payment_date=payment_date,
                            account_payment_id_id=clean_row['account_payment_id'] if account_payment_dict.get(
                                clean_row['account_payment_id']) else None,
                            messages=serializer.errors
                        )
                    )
                    is_success_all = False
                    row['errors'] = serializer.errors
                    logger.error({"action": "employee_financing_repayment_log", "errors": serializer.errors})
                    write.writerow(write_row_result(row, type='Repayment'))
            PartnershipRepaymentUpload.objects.bulk_create(
                parntership_repayment_uploads, batch_size=25
            )
        upload_csv_data_to_oss(upload_async_state, file_path=file_path)
    return is_success_all


def create_ef_pre_approval_upload_result(upload_async_state):
    upload_file = upload_async_state.file
    f = io.StringIO(upload_file.read().decode('utf-8'))
    reader = csv.DictReader(f, delimiter=',')
    is_success_all = True
    local_file_path = upload_async_state.file.path
    with open(local_file_path, "w", encoding='utf-8-sig') as f:
        write = csv.writer(f)
        write.writerow(PRE_APPROVAL_CSV_HEADERS)
        bank_names = BankManager.get_bank_names()
        pre_approval_feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.EF_PRE_APPROVAL,
            is_active=True
        ).first()
        for row in reader:
            clean_row = {key.lower().strip(): value for key, value in row.items()}
            formatted_data = ef_pre_approval_format_data(clean_row)

            if not pre_approval_feature_setting:
                is_success_all = False
                write.writerow(
                    write_row_result(formatted_data, "pre approval feature setting doesn't exist or inactive",
                                     type=UploadAsyncStateType.EMPLOYEE_FINANCING_PRE_APPROVAL)
                )
                continue

            serializer = PreApprovalSerializer(
                data=formatted_data,
                context={
                    'minimum_age': pre_approval_feature_setting.parameters.get('minimum_age'),
                    'maximum_age': pre_approval_feature_setting.parameters.get('maximum_age'),
                    'minimum_job_term': pre_approval_feature_setting.parameters.get('minimum_job_term'),
                    'minimum_income': pre_approval_feature_setting.parameters.get('minimum_income'),
                    'bank_names': bank_names
                }
            )
            if not serializer.is_valid():
                is_success_all = False
                error_list = serializer.errors.get('non_field_errors')
                error_str = ', '.join(error_list)
                write.writerow(write_row_result(formatted_data, error_str,
                                                type=UploadAsyncStateType.EMPLOYEE_FINANCING_PRE_APPROVAL))
                continue

            write.writerow(write_row_result(formatted_data, type=UploadAsyncStateType.EMPLOYEE_FINANCING_PRE_APPROVAL))
            validated_data = serializer.validated_data
            send_email_to_valid_employees.delay(
                validated_data,
                pre_approval_feature_setting.parameters.get('email_content'),
                pre_approval_feature_setting.parameters.get('email_subject'),
                pre_approval_feature_setting.parameters.get('email_salutation'),
            )
    upload_csv_data_to_oss(upload_async_state)
    return is_success_all


def process_upload_image(image_data: File, image_type: str,
                         em_financing_wf_application_id: int) -> None:
    """
        This process same like process_image_upload_partnership function
        But because we will stored image in different table need to adjusting
        The photo will be stored in OSS, and do soft delete if photo already exists
    """
    image = PartnershipImage()
    image.image_type =  image_type

    full_image_name = image.full_image_name(image_data.name)
    extension_data = full_image_name.split('.')[-1]

    if not extension_data:
        raise FailedUploadImageException('Invalid format image')

    if extension_data.lower() not in IMAGE_EXTENSION_FORMAT:
        raise FailedUploadImageException('Invalid format image')

    image_source = em_financing_wf_application_id
    image.ef_image_source = int(image_source)
    image.product_type = PartnershipImageProductType.EMPLOYEE_FINANCING

    _, file_extension = os.path.splitext(full_image_name)
    filename = "%s_%s%s" % (image.image_type, str(image.id), file_extension)
    image_remote_filepath = '/'.join(['cust_wf_' + str(image_source),
                                      'employee_financing_web_form', filename])

    try:
        # Read the image file in binary mode (as bytes)
        image_data.seek(0)
        image_bytes = image_data.read()
        upload_file_as_bytes_to_oss(settings.OSS_MEDIA_BUCKET, image_bytes, image_remote_filepath)
        image.url = image_remote_filepath
        image.save()

        logger.info(
            {
                'status': 'successfull upload image to s3',
                'image_remote_filepath': image_remote_filepath,
                'em_financing_web_form_application_id': image.ef_image_source,
                'image_type': image.image_type,
            }
        )
    except Exception as error:
        logger.error(
            {
                'status': 'failed upload image to s3',
                'image_remote_filepath': image_remote_filepath,
                'em_financing_web_form_application_id': image.ef_image_source,
                'image_type': image.image_type,
                'error': error,
            }
        )

    images = (
        PartnershipImage.objects.exclude(id=image.id)
        .exclude(image_status=PartnershipImageStatus.INACTIVE)
        .filter(ef_image_source=image.ef_image_source, image_type=image.image_type)
    )

    # Soft deleted
    for img in images:
        logger.info({'action': 'marking_deleted', 'image': img.id})
        img.image_status = PartnershipImageStatus.INACTIVE
        img.save()


def send_form_url_to_email_service(
    upload_async_state: UploadAsyncState, task_type: str, company: Company
) -> bool:
    from juloserver.julo.clients import get_julo_email_client

    upload_file = upload_async_state.file
    freader = io.StringIO(upload_file.read().decode('utf-8'))
    reader = csv.DictReader(freader, delimiter=',')
    is_success_all = True
    local_file_path = upload_async_state.file.path

    with TempDir(dir="/media") as tempdir:
        path_and_name, extension = os.path.splitext(local_file_path)
        file_name_elements = path_and_name.split('/')
        filename = file_name_elements[-1] + extension
        dir_path = tempdir.path
        file_path = os.path.join(dir_path, filename)

        with open(file_path, "w", encoding='utf-8-sig') as f:
            write = csv.writer(f)
            write.writerow(['email', 'errors'])
            for row in reader:
                if check_email(row['email']):
                    email_to = row['email']
                    expired_date = timezone.localtime(timezone.now()).replace(hour=23, minute=59, second=59)

                    if task_type == UploadAsyncStateType.EMPLOYEE_FINANCING_SEND_APPLICATION_FORM_URL:
                        form_type = EFWebFormType.APPLICATION
                    elif task_type == UploadAsyncStateType.EMPLOYEE_FINANCING_SEND_DISBURSEMENT_FORM_URL:
                        form_type = EFWebFormType.DISBURSEMENT

                    access_token = create_or_update_token(email_to, company, expired_date, form_type)
                    em_email_content = EmployeeFinancingFormURLEmailContent.objects.filter(
                        form_type=form_type).last()
                    email_template = Template(em_email_content.email_content)
                    base_julo_web_url = settings.JULO_WEB_URL
                    if settings.ENVIRONMENT == 'staging':
                        base_julo_web_url = "https://app-staging2.julo.co.id"

                    email_context = Context(
                        {
                            'limit_token_creation': access_token.limit_token_creation,
                            'expired_at': access_token.expired_at,
                            'url': '{}/ef-pilot/{}?token={}'.format(
                                base_julo_web_url, form_type,
                                access_token.token
                            )
                        }
                    )
                    context = {
                        'fullname': email_to,
                        'content': email_template.render(email_context)
                    }

                    email_template = render_to_string(
                        'email_template_ef_send_form_url_to_email.html', context=context
                    )
                    email_from = "ops.employee_financing@julo.co.id"
                    email_to = row['email']
                    subject = em_email_content.email_subject
                    julo_email_client = get_julo_email_client()
                    julo_email_client.send_email(
                        subject, email_template, email_to, email_from=email_from, content_type="text/html")
                    EmailHistory.objects.create(
                        to_email=email_to,
                        subject=subject,
                        message_content=email_template,
                        template_code='email_template_ef_send_form_url_to_email'
                    )
                else:
                    is_success_all = False
                    write.writerow([row['email'], "Email {}".format(ErrorMessageConst.INVALID_DATA)])
    upload_csv_data_to_oss(upload_async_state)
    return is_success_all


def re_create_batch_user_tokens(form_type: str) -> List:
    """
        Only valid 2 form_type: application, disbursement
        Re Create all user tokens based on form_type
    """

    if form_type not in {EFWebFormType.APPLICATION, EFWebFormType.DISBURSEMENT}:
        raise ValueError("Invalid Employee Financing Form Type")

    today = timezone.localtime(timezone.now())
    employee_financing_tokens = EmFinancingWFAccessToken.objects.filter(
        expired_at__lt=today, form_type=form_type,
        is_used=False, limit_token_creation__gt=0).order_by('id')

    token_ids = []
    if not employee_financing_tokens:
        return token_ids

    for employee_financing_token in employee_financing_tokens.iterator():
        email = employee_financing_token.email
        name = employee_financing_token.name
        company = employee_financing_token.company
        form_type = employee_financing_token.form_type
        token = employee_financing_token.token  # Old token
        expired_at = timezone.localtime(timezone.now()).replace(hour=23, minute=59, second=59)
        user_token_created = create_or_update_token(
            email=email, company=company, expired_at=expired_at,
            form_type=form_type, token=token, name=name
        )
        user_token_created.refresh_from_db()
        token_ids.append(user_token_created.id)

    return token_ids


def ef_master_agreement_template(application: Application) -> Union[bool, str]:
    """
        This function will be return a template master agreement Employee Financing
    """
    ma_template = MasterAgreementTemplate.objects.filter(product_name='EF', is_active=True) \
        .last()

    if not ma_template:
        logger.error({
            'action_view': 'Master Agreement EF - get_master_agreement_template',
            'data': {},
            'errors': 'Master Agreement EF Template tidak ditemukan'
        })
        return False

    template = ma_template.parameters
    if len(template) == 0:
        logger.error({
            'action_view': 'Master Agreement EF - get_master_agreement_template',
            'data': {},
            'errors': 'Body content tidak ada'
        })
        return False

    customer = application.customer
    if not customer:
        logger.error({
            'action_view': 'Master Agreement EF - master_agreement_content',
            'data': {},
            'errors': 'Customer tidak ditemukan'
        })
        return False

    account = customer.account
    if not account:
        logger.error({
            'action_view': 'Master Agreement EF - master_agreement_content',
            'data': {},
            'errors': 'Customer tidak ditemukan'
        })
        return False

    first_credit_limit = account.accountlimit_set.first().set_limit
    if not first_credit_limit:
        logger.error({
            'action_view': 'Master Agreement EF - master_agreement_content',
            'data': {},
            'errors': 'First Credit Limit tidak ditemukan'
        })
        return False

    customer_name = customer.fullname
    today = datetime.now()
    hash_digi_sign = "PPFP-" + str(application.application_xid)
    dob = application.dob.strftime("%d %B %Y")
    signature = ('<table border="0" cellpadding="1" cellspacing="1" style="border:none;">'
                 '<tbody><tr><td><p>PT. JULO Teknologi Finansial<br>'
                 '(dalam kedudukan selaku kuasa Pemberi Dana)<br>'
                 'Jabatan: Direktur</p></td>'
                 '<td><p style="text-align:right">'
                 'Jakarta, ' + today.strftime("%d %B %Y") + '</p>'
                 '<p style="text-align:right">Penerima&nbsp;Dana,</p>'
                 '<p style="text-align:right"><span style="font-family:Allura">'
                 '<cite><tt>' + customer_name + '</tt></cite></span></p>'
                 '<p style="text-align:right">' + customer_name + '</p></td>'
                 '</tr></tbody></table>')

    ma_content = template.format(
        hash_digi_sign=hash_digi_sign,
        date_today=today.strftime("%d %B %Y, %H:%M:%S"),
        customer_name=customer_name,
        dob=dob,
        customer_nik=application.ktp,
        customer_phone=application.mobile_phone_1,
        full_address=application.full_address,
        first_credit_limit=first_credit_limit,
        link_history_transaction=settings.BASE_URL + "/account/v1/account/account_payment",
        tnc_link="https://www.julo.co.id/privacy-policy",
        signature=signature
    )

    return ma_content
