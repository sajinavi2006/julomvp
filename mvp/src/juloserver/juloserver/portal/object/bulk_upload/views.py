"""
views.py
handler request for icare page
"""

import csv
import logging
from builtins import str
from datetime import datetime

from django.shortcuts import render

from juloserver.grab.services.services import (
    grab_update_old_and_create_new_referral_whitelist,
)
from juloserver.julo.constants import UploadAsyncStateStatus, UploadAsyncStateType
from juloserver.julo.models import Agent, UploadAsyncState, Partner
from juloserver.julo.partners import PartnerConstant
from juloserver.merchant_financing.constants import (
    PARTNER_MF_DISBURSEMENT_UPLOAD_MAPPING_FIELDS,
    PARTNER_MF_REGISTER_UPLOAD_MAPPING_FIELDS,
    PARTNER_MF_ADJUST_LIMIT_UPLOAD_MAPPING_FIELDS,
)
from juloserver.merchant_financing.tasks import (
    process_merchant_financing_disbursement,
    process_merchant_financing_register, process_merchant_financing_adjust_limit,
)
from juloserver.partnership.constants import PartnershipFlag
from juloserver.partnership.models import PartnershipFlowFlag
from juloserver.portal.object import julo_login_required, julo_login_required_multigroup
from juloserver.portal.object.bulk_upload.constants import (
    MF_CSV_UPLOAD_UPGRADE_HEADERS,
    MF_DISBURSEMENT_KEY,
    MerchantFinancingCSVUploadPartner,
    MerchantFinancingCsvAdjustLimitPartner,
    MF_ADJUST_LIMIT_KEY,
    MerchantFinancingCsvUpgradePartner,
)
from juloserver.sdk.models import AxiataCustomerData, AxiataRepaymentData
from juloserver.sdk.services import xls_to_dict

from .constants import (
    ACTION_CHOICES,
    GRAB_REFERRAL_ACTION_CHOICES,
    GRAB_REFERRAL_LABEL,
    GRAB_REFERRAL_TEMPLATE_PATH,
    HALT_RESUME_TEMPLATE_PATH,
    ICARE_LABEL,
    LOAN_EARLY_WRITE_OFF_ACTION_CHOICES,
    LOAN_EARLY_WRITE_OFF_LABEL,
    LOAN_EARLY_WRITE_OFF_TEMPLATE_PATH,
    LOAN_HALT_ACTION_CHOICES,
    LOAN_HALT_LABEL,
    LOAN_RESTRUCTURING_ACTION_CHOICES,
    LOAN_RESTRUCTURING_LABEL,
    LOAN_RESTRUCTURING_TEMPLATE_PATH,
    MF_REGISTER_KEY,
    TEMPLATE_PATH,
)
from .forms import (
    GrabReferralUploadFileForm,
    LoanEarlyWriteOffUploadFileForm,
    LoanHaltResumeUploadFileForm,
    LoanRestructuringUploadFileForm,
    MerchantFinancingUploadFileForm,
    UploadFileForm,
)
from .serializers import (
    ApplicationPartnerUpdateSerializer,
    ApprovalContentSerializer,
    AxiataCustomerDataSerializer,
    DisbursementContentSerializer,
    GrabReferralSerializer,
    LoanGrabEarlyWriteOffSerializer,
    LoanGrabRestructureSerializer,
    LoanHaltResumeSerializer,
    MerchantFinancingCSVUploadUpgradeSerializer,
    RejectionContentSerializer,
    RepaymentDataSerializer,
)
from .services import (
    upgrade_efishery_customers,
)
from .tasks import (
    approval_application_async,
    generate_application_async,
    generate_application_axiata_async,
    grab_early_write_off_revert_task,
    grab_early_write_off_task,
    grab_loan_restructure_revert_task,
    grab_loan_restructure_task,
    grab_referral_program_task,
    loan_disbursement_async,
    loan_halt_task,
    loan_resume_task,
    reject_application_async,
    repayment_async,
)
from .utils import axiata_mapping_data
from juloserver.portal.object.bulk_upload.utils import (  # noqa
    validate_last_education,
    validate_home_status,
    validate_income,
    validate_certificate_number,
    validate_certificate_date,
    validate_npwp,
    validate_kin_name,
    validate_kin_mobile_phone,
)

logger = logging.getLogger(__name__)

REGISTER_KEY = ACTION_CHOICES[0][0]
APPROVAL_KEY = ACTION_CHOICES[1][0]
DISBURSEMENT_KEY = ACTION_CHOICES[2][0]
REJECTION_KEY = ACTION_CHOICES[3][0]
REPAYMENT_KEY = ACTION_CHOICES[4][0]

HALT_KEY = LOAN_HALT_ACTION_CHOICES[0][0]
RESUME_KEY = LOAN_HALT_ACTION_CHOICES[1][0]

GRAB_RESTRUCTURE_KEY = LOAN_RESTRUCTURING_ACTION_CHOICES[0][0]
GRAB_REVERT_KEY = LOAN_RESTRUCTURING_ACTION_CHOICES[1][0]

GRAB_EARLY_WRITE_OFF_KEY = LOAN_EARLY_WRITE_OFF_ACTION_CHOICES[0][0]
GRAB_EARLY_WRITE_OFF_REVERT_KEY = LOAN_EARLY_WRITE_OFF_ACTION_CHOICES[1][0]

GRAB_REFERRAL_KEY = GRAB_REFERRAL_ACTION_CHOICES[0][0]
GRAB_REFERRAL_WITHOUT_WHITELIST_UPDATION_KEY = GRAB_REFERRAL_ACTION_CHOICES[1][0]

ACTION_MAP = {
    "icare": {
        APPROVAL_KEY: {
            "serializer": ApprovalContentSerializer,
            'async_func': approval_application_async
        },
        REGISTER_KEY: {
            "serializer": ApplicationPartnerUpdateSerializer,
            'async_func': generate_application_async
        },
        DISBURSEMENT_KEY: {
            "serializer": DisbursementContentSerializer,
            'async_func': loan_disbursement_async
        },
        REJECTION_KEY: {
            "serializer": RejectionContentSerializer,
            'async_func': reject_application_async
        }
    },
    "axiata": {
        REGISTER_KEY: {
            "serializer": AxiataCustomerDataSerializer,
            'async_func': generate_application_axiata_async
        },
        DISBURSEMENT_KEY: {
            "serializer": DisbursementContentSerializer,
            'async_func': loan_disbursement_async
        },
        REPAYMENT_KEY: {
            "serializer": RepaymentDataSerializer,
            "async_func": repayment_async
        }
    }
}


LOAN_HALT_ACTION_MAP = {
    "grab": {
        HALT_KEY: {
            "serializer": LoanHaltResumeSerializer,
            'async_func': loan_halt_task
        },
        RESUME_KEY: {
            "serializer": LoanHaltResumeSerializer,
            'async_func': loan_resume_task
        },
    },
}

LOAN_RESTRUCTURING_ACTION_MAP = {
    "grab": {
        GRAB_RESTRUCTURE_KEY: {
            "serializer": LoanGrabRestructureSerializer,
            'async_func': grab_loan_restructure_task
        },
        GRAB_REVERT_KEY: {
            "serializer": LoanGrabRestructureSerializer,
            'async_func': grab_loan_restructure_revert_task
        },
    },
}

LOAN_EARLY_WRITE_OFF_ACTION_MAP = {
    "grab": {
        GRAB_EARLY_WRITE_OFF_KEY: {
            "serializer": LoanGrabEarlyWriteOffSerializer,
            'async_func': grab_early_write_off_task
        },
        GRAB_EARLY_WRITE_OFF_REVERT_KEY: {
            "serializer": LoanGrabEarlyWriteOffSerializer,
            'async_func': grab_early_write_off_revert_task
        },
    },
}


GRAB_REFERRAL_ACTION_MAP = {
    "grab": {
        GRAB_REFERRAL_KEY: {
            "serializer": GrabReferralSerializer,
            'async_func': grab_referral_program_task,
            "sync_func": grab_update_old_and_create_new_referral_whitelist
        },
        GRAB_REFERRAL_WITHOUT_WHITELIST_UPDATION_KEY: {
            "serializer": GrabReferralSerializer,
            'async_func': grab_referral_program_task
        }
    },
}


@julo_login_required
@julo_login_required_multigroup(['bo_data_verifier'])
def bulk_upload_view(request):
    """handle get request"""
    template_name = 'object/bulk_upload/bulk_upload.html'
    from juloserver.portal.object.bulk_upload.utils import get_bulk_upload_options
    logs = ""
    upload_form = None
    ok_couter = 0
    nok_couter = 0
    LABELS = get_bulk_upload_options(type='label')
    TEMPLATE_PATHS = get_bulk_upload_options(type='path')
    def _render():
        """lamda func to reduce code"""
        return render(request, template_name, {'form': upload_form,
                                               'logs': logs,
                                               'ok': ok_couter,
                                               'nok': nok_couter,
                                               'label': LABELS,
                                               'path': TEMPLATE_PATHS})

    if request.method == 'POST':
        upload_form = UploadFileForm(request.POST, request.FILES)
        if not upload_form.is_valid():
            logs = 'Invalid form'
            return _render()

        file_ = upload_form.cleaned_data['file_field']
        action_key = upload_form.cleaned_data['action_field']
        partner_obj = upload_form.cleaned_data['partner_field']
        extension = file_.name.split('.')[-1]

        if extension not in ['xls', 'xlsx', 'csv']:
            logs = 'Please upload correct file excel'
            return _render()

        delimiter = ","
        if str(partner_obj) == str(PartnerConstant.AXIATA_PARTNER) and extension in ['csv']:
            delimiter = "|"

        try:
            excel_datas = xls_to_dict(file_, delimiter)
        except Exception as error:
            logs = str(error)
            return _render()

        partner = Partner.objects.filter(name=PartnerConstant.AXIATA_PARTNER).last()
        field_flag = PartnershipFlowFlag.objects.filter(
            partner_id=partner.id, name=PartnershipFlag.FIELD_CONFIGURATION
        ).last()
        config = field_flag.configs

        # get serializer and async func from defined map
        action_obj = ACTION_MAP.get(str(partner_obj)).get(str(action_key))
        if not action_obj:
            logs = "Not supported"
            return _render()

        for idx_sheet, sheet in enumerate(excel_datas):
            if str(partner_obj) == str(PartnerConstant.AXIATA_PARTNER):
                if str(action_key) == REGISTER_KEY:
                    excel_datas[sheet] = axiata_mapping_data(excel_datas[sheet])
            for idx_rpw, row in enumerate(excel_datas[sheet]):
                serializer = action_obj['serializer'](data=row)
                logs += "Sheet: %d   |   Row: %d   |   " % (idx_sheet + 1, idx_rpw + 2)

                additional_message = []
                invalid_fields = []
                additional_field_list = [
                    'income',
                    'certificate_number',
                    'certificate_date',
                    'npwp',
                    'last_education',
                    'home_status',
                    'kin_name',
                    'kin_mobile_phone',
                ]
                for field in additional_field_list:
                    validate_func = eval('validate_{}'.format(field))
                    is_mandatory = config['fields'].get(field, False)
                    is_valid, error_notes = validate_func(
                        value=row.get(field), is_mandatory=is_mandatory
                    )

                    if not is_valid:
                        additional_message.append(error_notes)
                        invalid_fields.append(field)

                if row.get('user_type') and row.get('user_type', '').lower() not in [
                    'perorangan',
                    'lembaga',
                ]:
                    additional_message.append(
                        'jenis pengguna tidak sesuai, mohon isi sesuai master perorangan, lembaga'
                    )
                    invalid_fields.append('user_type')

                if serializer.is_valid():
                    data = serializer.data
                    if str(action_key) == REPAYMENT_KEY:
                        data['collected_by'] = request.user.id

                    if str(action_key) == REGISTER_KEY:
                        for field in invalid_fields:
                            data[field] = None

                    # call async func to handle
                    ok_couter += 1
                    action_obj['async_func'].delay(data, partner_obj.pk)

                    if additional_message:
                        logs += "Success. " + ". ".join(additional_message) + "\n"
                    else:
                        logs += "Success.\n"
                else:
                    nok_couter += 1
                    logs += "Error: %s \n" % str(serializer.errors)
                    # save axiata data that failed to upload
                    if str(action_key) == REGISTER_KEY:
                        axiata_data = serializer.data
                        axiata_data['reject_reason'] = str(serializer.errors)

                        for field in invalid_fields:
                            axiata_data[field] = None

                    if str(action_key) == REPAYMENT_KEY:
                        axiata_repayment_data = serializer.data
                        axiata_repayment_data['messages'] = str(serializer.errors)

                    if str(partner_obj) == str(PartnerConstant.AXIATA_PARTNER):
                        if "axiata_temporary_data_id" in axiata_data:
                            del axiata_data["axiata_temporary_data_id"]

                        if axiata_data.get('certificate_date'):
                            try:
                                axiata_data['certificate_date'] = datetime.strptime(
                                    axiata_data['certificate_date'], "%m/%d/%Y"
                                )
                            except:
                                axiata_data['certificate_date'] = None

                        if axiata_data.get('income'):
                            try:
                                axiata_data['income'] = int(axiata_data['income'])
                            except:
                                axiata_data['income'] = None

                        if axiata_data.get('user_type'):
                            axiata_data['user_type'] = axiata_data['user_type'].lower()

                        if axiata_data.get('home_status'):
                            axiata_data['home_status'] = axiata_data['home_status'].capitalize()

                        if axiata_data.get('last_education'):
                            axiata_data['last_education'] = axiata_data['last_education'].upper()
                            if axiata_data['last_education'] == 'DIPLOMA':
                                axiata_data['last_education'] = axiata_data[
                                    'last_education'
                                ].capitalize()

                        if axiata_data.get('kin_name'):
                            axiata_data['kin_name'] = axiata_data['kin_name']

                        if axiata_data.get('kin_mobile_phone'):
                            axiata_data['kin_mobile_phone'] = axiata_data['kin_mobile_phone']

                        if str(action_key) == REGISTER_KEY:
                            AxiataCustomerData.objects.create(**axiata_data)
                        if str(action_key) == REPAYMENT_KEY:
                            AxiataRepaymentData.objects.create(**axiata_repayment_data)

                logs += "---" * 20 + "\n"

    else:
        upload_form = UploadFileForm()
    return _render()


@julo_login_required
@julo_login_required_multigroup(['bo_data_verifier'])
def merchant_financing_csv_upload_view(request):
    """
    This view is used for uploading CSV for creating application/disbursement process
    for Merchant Financing partner where the partner is still not ready to do API inregration
    """
    template_name = 'object/bulk_upload/merchant_financing_upload.html'
    logs = ""
    upload_form = None
    ok_couter = 0
    nok_couter = 0
    in_processed_status = {
        UploadAsyncStateStatus.WAITING,
        UploadAsyncStateStatus.PROCESSING,
    }

    def _render():
        """lamda func to reduce code"""
        return render(request, template_name, {'form': upload_form,
                                               'logs': logs,
                                               'ok': ok_couter,
                                               'nok': nok_couter,
                                               'label': ICARE_LABEL,
                                               'path': TEMPLATE_PATH})

    if request.method == 'POST':
        upload_form = MerchantFinancingUploadFileForm(request.POST, request.FILES)
        if not upload_form.is_valid():
            for key in upload_form.errors:
                logs += upload_form.errors[key][0] + "\n"
                logs += "---" * 20 + "\n"
            return _render()

        file_ = upload_form.cleaned_data['file_field']
        action_key = upload_form.cleaned_data['action_field']
        partner = upload_form.cleaned_data['partner_field']
        extension = file_.name.split('.')[-1]

        if partner in PartnerConstant.list_partner_merchant_financing_standard():
            logs = 'Partner already migrated to merchant financing standard.'
            return _render()

        if extension != 'csv':
            logs = 'Please upload the correct file type: CSV'
            return _render()

        decoded_file = file_.read().decode('utf-8').splitlines()
        reader = csv.DictReader(decoded_file)
        if action_key == MF_REGISTER_KEY:
            not_exist_headers = []
            for header in range(len(PARTNER_MF_REGISTER_UPLOAD_MAPPING_FIELDS)):
                if PARTNER_MF_REGISTER_UPLOAD_MAPPING_FIELDS[header][0] not in reader.fieldnames:
                    not_exist_headers.append(PARTNER_MF_REGISTER_UPLOAD_MAPPING_FIELDS[header][0])

            if len(not_exist_headers) == len(PARTNER_MF_REGISTER_UPLOAD_MAPPING_FIELDS):
                logs = 'CSV format is not correct'
                return _render()

            if not_exist_headers:
                logs = 'CSV format is not correct. Headers not exists: %s' % not_exist_headers
                return _render()

            if (partner.name == MerchantFinancingCSVUploadPartner.BUKUWARUNG and
                    'Percentage' not in reader.fieldnames) or\
                    (partner.name in {
                        MerchantFinancingCSVUploadPartner.EFISHERY,
                        MerchantFinancingCSVUploadPartner.DAGANGAN,
                        MerchantFinancingCSVUploadPartner.EFISHERY_KABAYAN_LITE,
                        MerchantFinancingCSVUploadPartner.KARGO
                    } and
                        'Percentage' in reader.fieldnames):
                logs = 'Partner and CSV File Format is not matching'
                return _render()

            agent = Agent.objects.filter(user=request.user).last()
            is_upload_in_waiting = UploadAsyncState.objects.filter(
                task_type=UploadAsyncStateType.MERCHANT_FINANCING_REGISTER,
                task_status__in=in_processed_status,
                agent=agent,
                service='oss',
            ).exists()

            if is_upload_in_waiting:
                logs = 'Another process in waiting or process please wait and try again later'
                return _render()

            upload_async_state = UploadAsyncState(
                task_type=UploadAsyncStateType.MERCHANT_FINANCING_REGISTER,
                task_status=UploadAsyncStateStatus.WAITING,
                agent=agent,
                service='oss',
            )

            upload_async_state.save()
            upload = file_
            upload_async_state.file.save(
                upload_async_state.full_upload_name(upload.name), upload
            )
            upload_async_state_id = upload_async_state.id
            process_merchant_financing_register.delay(upload_async_state_id, partner.id)
            logs = 'Your file is being processed. Please check Upload History to see the status'
            return _render()

        elif action_key == MF_DISBURSEMENT_KEY:
            if partner.is_disbursement_to_distributor_bank_account:
                """
                currently only using RABANDO partner
                This flow slightly different from previous partner like bukuwarung,
                The disburseement will be disburse to bank account that filled in csv
                """
                mapping_fields_set = {field[0] for field in PARTNER_MF_DISBURSEMENT_UPLOAD_MAPPING_FIELDS}
                fieldnames_set = set(reader.fieldnames)

                # Check if headers from PARTNER_MF_DISBURSEMENT_UPLOAD_MAPPING_FIELDS exist in the CSV
                not_exist_headers = [field for field in mapping_fields_set if field not in fieldnames_set]

                if len(not_exist_headers) == len(PARTNER_MF_DISBURSEMENT_UPLOAD_MAPPING_FIELDS):
                    logs = 'CSV format is not correct'
                    return _render()

                if not_exist_headers:
                    logs = 'CSV format is not correct. Headers not exists: %s' % not_exist_headers
                    return _render()

            agent = Agent.objects.filter(user=request.user).last()
            is_upload_in_waiting = UploadAsyncState.objects.filter(
                task_type=UploadAsyncStateType.MERCHANT_FINANCING_DISBURSEMENT,
                task_status__in=in_processed_status,
                agent=agent,
                service='oss',
            ).exists()

            if is_upload_in_waiting:
                logs = 'Another process in waiting or process please wait and try again later'
                return _render()

            task_type = UploadAsyncStateType.MERCHANT_FINANCING_DISBURSEMENT
            upload_async_state = UploadAsyncState(
                task_type=task_type,
                task_status=UploadAsyncStateStatus.WAITING,
                agent=agent,
                service='oss',
            )

            upload_async_state.save()
            upload = file_
            upload_async_state.file.save(
                upload_async_state.full_upload_name(upload.name), upload
            )
            upload_async_state_id = upload_async_state.id

            process_merchant_financing_disbursement.delay(upload_async_state_id, partner.id)
            logs = 'Your file is being processed. Please check Upload History to see the status'
            return _render()

        elif action_key == "Upgrade":
            if partner.name not in MerchantFinancingCsvUpgradePartner:
                logs = 'Partner and CSV File Format is not matching'
                return _render()

            not_exist_headers = []
            header_fieldnames = set(reader.fieldnames)
            for header in MF_CSV_UPLOAD_UPGRADE_HEADERS:
                if header not in header_fieldnames:
                    not_exist_headers.append(header)

            if not_exist_headers:
                logs = 'CSV format is not correct. Headers not exists: %s' % not_exist_headers
                return _render()

            for idx, row in enumerate(reader, start=2):
                serializer = MerchantFinancingCSVUploadUpgradeSerializer(data=row)
                if serializer.is_valid():
                    validated_data = serializer.validated_data
                    thread_name = 'Application_Xid-%s' % validated_data["application_xid"]
                    is_success, message = upgrade_efishery_customers(
                        validated_data["application_xid"],
                        validated_data["limit_upgrading"],
                        partner
                    )
                else:
                    thread_name = 'Data baris ke-%s' % idx
                    is_success = False
                    message = serializer.errors

                if is_success:
                    ok_couter += 1
                else:
                    nok_couter += 1

                logs += "%s %s" % (thread_name, message) + '\n'
                logs += "---" * 20 + "\n"

        elif action_key == MF_ADJUST_LIMIT_KEY:
            if partner.name not in MerchantFinancingCsvAdjustLimitPartner:
                logs = 'Partner not supported for adjust limit'
                return _render()

            not_exist_headers = []
            for header in range(len(PARTNER_MF_ADJUST_LIMIT_UPLOAD_MAPPING_FIELDS)):
                if PARTNER_MF_ADJUST_LIMIT_UPLOAD_MAPPING_FIELDS[header][0] not in reader.fieldnames:
                    not_exist_headers.append(PARTNER_MF_ADJUST_LIMIT_UPLOAD_MAPPING_FIELDS[header][0])

            if not_exist_headers:
                logs = 'CSV format is not correct. Headers not exists: %s' % not_exist_headers
                return _render()

            agent = Agent.objects.filter(user=request.user).last()
            is_upload_in_waiting = UploadAsyncState.objects.filter(
                task_type=UploadAsyncStateType.MERCHANT_FINANCING_ADJUST_LIMIT,
                task_status__in=in_processed_status,
                agent=agent,
                service='oss',
            ).exists()

            if is_upload_in_waiting:
                logs = 'Another process in waiting or process please wait and try again later'
                return _render()

            upload_async_state = UploadAsyncState(
                task_type=UploadAsyncStateType.MERCHANT_FINANCING_ADJUST_LIMIT,
                task_status=UploadAsyncStateStatus.WAITING,
                agent=agent,
                service='oss',
            )

            upload_async_state.save()
            upload = file_
            upload_async_state.file.save(
                upload_async_state.full_upload_name(upload.name), upload
            )
            upload_async_state_id = upload_async_state.id
            process_merchant_financing_adjust_limit.delay(upload_async_state_id, partner.id)
            logs = 'Your file is being processed. Please check Upload History to see the status'
            return _render()


    else:
        upload_form = MerchantFinancingUploadFileForm()
    return _render()


@julo_login_required
@julo_login_required_multigroup(['bo_data_verifier'])
def loan_halt_or_resume(request):
    template_name = 'object/bulk_upload/bulk_upload.html'
    logs = ""
    upload_form = None
    ok_couter = 0
    nok_couter = 0

    def _render():
        """lamda func to reduce code"""
        return render(request, template_name, {'form':upload_form,
                                               'logs':logs,
                                               'ok':ok_couter,
                                               'nok':nok_couter,
                                               'label': LOAN_HALT_LABEL,
                                               'path': HALT_RESUME_TEMPLATE_PATH})

    if request.method == 'POST':
        upload_form = LoanHaltResumeUploadFileForm(request.POST, request.FILES)
        if not upload_form.is_valid():
            logs = 'Invalid form'
            return _render()

        file_ = upload_form.cleaned_data['file_field']
        action_key = upload_form.cleaned_data['action_field']
        partner_obj = upload_form.cleaned_data['partner_field']
        extension = file_.name.split('.')[-1]

        if extension not in ['xls', 'xlsx', 'csv']:
            logs = 'Please upload correct file excel'
            return _render()

        delimiter = ","
        try:
            excel_datas = xls_to_dict(file_, delimiter)
        except Exception as error:
            logs = str(error)
            return _render()

        # get serializer and async func from defined map
        action_obj = LOAN_HALT_ACTION_MAP.get(str(partner_obj)).get(str(action_key))
        if not action_obj:
            logs = "Not supported"
            return _render()

        for idx_sheet, sheet in enumerate(excel_datas):
            for idx_rpw, row in enumerate(excel_datas[sheet]):
                row['action_key'] = action_key
                row['partner'] = partner_obj
                serializer = action_obj['serializer'](data=row)
                logs += "Sheet: %d   |   Row: %d   |   " % (idx_sheet+1, idx_rpw+2)
                if serializer.is_valid():
                    data = serializer.data
                    data['agent_user_id'] = request.user.id
                    # call async func to handle
                    ok_couter += 1
                    action_obj['async_func'].delay(data, partner_obj.pk)
                    logs += "Success.\n"
                else:
                    nok_couter += 1
                    logs += "Error: %s \n" % str(serializer.errors)

                logs += "---"*20 + "\n"

    else:
        upload_form = LoanHaltResumeUploadFileForm()
    return _render()


@julo_login_required
@julo_login_required_multigroup(['bo_data_verifier'])
def grab_loan_restructuring(request):
    template_name = 'object/bulk_upload/bulk_upload.html'
    logs = ""
    upload_form = None
    ok_couter = 0
    nok_couter = 0

    def _render():
        """lamda func to reduce code"""
        return render(request, template_name, {
            'form': upload_form,
            'logs': logs,
            'ok': ok_couter,
            'nok': nok_couter,
            'label': LOAN_RESTRUCTURING_LABEL,
            'path': LOAN_RESTRUCTURING_TEMPLATE_PATH})

    if request.method == 'POST':
        upload_form = LoanRestructuringUploadFileForm(request.POST, request.FILES)
        if not upload_form.is_valid():
            logs = 'Invalid form'
            return _render()

        file_ = upload_form.cleaned_data['file_field']
        action_key = upload_form.cleaned_data['action_field']
        partner_obj = upload_form.cleaned_data['partner_field']
        extension = file_.name.split('.')[-1]

        if extension not in ['xls', 'xlsx', 'csv']:
            logs = 'Please upload correct file excel'
            return _render()

        delimiter = ","
        try:
            excel_datas = xls_to_dict(file_, delimiter)
        except Exception as error:
            logs = str(error)
            return _render()

        # get serializer and async func from defined map
        action_obj = LOAN_RESTRUCTURING_ACTION_MAP.get(str(partner_obj)).get(str(action_key))
        if not action_obj:
            logs = "Not supported"
            return _render()

        for idx_sheet, sheet in enumerate(excel_datas):
            for idx_rpw, row in enumerate(excel_datas[sheet]):
                row['action_key'] = action_key
                row['partner'] = partner_obj
                serializer = action_obj['serializer'](data=row)
                logs += "Sheet: %d   |   Row: %d   |   " % (idx_sheet+1, idx_rpw+2)
                if serializer.is_valid():
                    data = serializer.data
                    data['agent_user_id'] = request.user.id
                    # call async func to handle
                    ok_couter += 1
                    action_obj['async_func'](data, partner_obj.pk)
                    logs += "Success.\n"
                else:
                    nok_couter += 1
                    logs += "Error: %s \n" % str(serializer.errors)

                logs += "---"*20 + "\n"

    else:
        upload_form = LoanRestructuringUploadFileForm()
    return _render()


@julo_login_required
@julo_login_required_multigroup(['product_manager'])
def early_write_off(request):
    template_name = 'object/bulk_upload/bulk_upload.html'
    logs = ""
    upload_form = None
    ok_couter = 0
    nok_couter = 0

    def _render():
        """lamda func to reduce code"""
        return render(request, template_name, {
            'form': upload_form,
            'logs': logs,
            'ok': ok_couter,
            'nok': nok_couter,
            'label': LOAN_EARLY_WRITE_OFF_LABEL,
            'path': LOAN_EARLY_WRITE_OFF_TEMPLATE_PATH})

    if request.method == 'POST':
        upload_form = LoanEarlyWriteOffUploadFileForm(request.POST, request.FILES)
        if not upload_form.is_valid():
            logs = 'Invalid form'
            return _render()

        file_ = upload_form.cleaned_data['file_field']
        action_key = upload_form.cleaned_data['action_field']
        partner_obj = upload_form.cleaned_data['partner_field']
        extension = file_.name.split('.')[-1]

        if extension not in ['xls', 'xlsx', 'csv']:
            logs = 'Please upload correct file excel'
            return _render()

        delimiter = ","
        try:
            excel_datas = xls_to_dict(file_, delimiter)
        except Exception as error:
            logs = str(error)
            return _render()

        # get serializer and async func from defined map
        action_obj = LOAN_EARLY_WRITE_OFF_ACTION_MAP.get(str(partner_obj)).get(str(action_key))
        if not action_obj:
            logs = "Not supported"
            return _render()

        for idx_sheet, sheet in enumerate(excel_datas):
            for idx_rpw, row in enumerate(excel_datas[sheet]):
                row['action_key'] = action_key
                row['partner'] = partner_obj
                serializer = action_obj['serializer'](data=row)
                logs += "Sheet: %d   |   Row: %d   |   " % (idx_sheet+1, idx_rpw+2)
                if serializer.is_valid():
                    data = serializer.data
                    data['agent_user_id'] = request.user.id
                    # call async func to handle
                    ok_couter += 1
                    action_obj['async_func'].apply_async((data, partner_obj.pk))
                    logs += "Success.\n"
                else:
                    nok_couter += 1
                    logs += "Error: %s \n" % str(serializer.errors)

                logs += "---"*20 + "\n"

    else:
        upload_form = LoanEarlyWriteOffUploadFileForm()
    return _render()


@julo_login_required
@julo_login_required_multigroup(['product_manager'])
def grab_referral_program(request):
    template_name = 'object/bulk_upload/bulk_upload.html'
    logs = ""
    upload_form = None
    ok_couter = 0
    nok_couter = 0

    def _render():
        """lamda func to reduce code"""
        return render(request, template_name, {
            'form': upload_form,
            'logs': logs,
            'ok': ok_couter,
            'nok': nok_couter,
            'label': GRAB_REFERRAL_LABEL,
            'path': GRAB_REFERRAL_TEMPLATE_PATH})

    if request.method == 'POST':
        upload_form = GrabReferralUploadFileForm(request.POST, request.FILES)
        if not upload_form.is_valid():
            logs = 'Invalid form'
            return _render()

        file_ = upload_form.cleaned_data['file_field']
        action_key = upload_form.cleaned_data['action_field']
        partner_obj = upload_form.cleaned_data['partner_field']
        extension = file_.name.split('.')[-1]

        if extension not in ['xls', 'xlsx', 'csv']:
            logs = 'Please upload correct file excel'
            return _render()

        delimiter = ","
        try:
            excel_datas = xls_to_dict(file_, delimiter)
        except Exception as error:
            logs = str(error)
            return _render()

        # get serializer and async func from defined map
        action_obj = GRAB_REFERRAL_ACTION_MAP.get(str(partner_obj)).get(str(action_key))
        if not action_obj:
            logs = "Not supported"
            return _render()
        if 'sync_func' in action_obj:
            action_obj['sync_func']()
        for idx_sheet, sheet in enumerate(excel_datas):
            for idx_rpw, row in enumerate(excel_datas[sheet]):
                row['action_key'] = action_key
                row['partner'] = partner_obj
                row['partner_id'] = partner_obj.id
                action_obj['async_func'].apply_async((row,))
                logs += "Sheet: %d   |   Row: %d   |   " % (idx_sheet+1, idx_rpw+2)
                ok_couter += 1
                logs += "Success.\n"
                logs += "---"*20 + "\n"

    else:
        upload_form = GrabReferralUploadFileForm()
    return _render()
