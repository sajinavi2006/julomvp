import csv
import decimal
import io
import logging
import os
from collections import namedtuple
from datetime import datetime
from typing import Dict, List, Tuple

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count, Sum, Prefetch
from django.utils import timezone

from juloserver.account.constants import AccountConstant
from juloserver.account.services.credit_limit import update_available_limit
from juloserver.apiv2.constants import FDCFieldsName
from juloserver.apiv2.models import AutoDataCheck
from juloserver.application_flow.models import TelcoScoringResult
from juloserver.application_flow.services import store_application_to_experiment_table
from juloserver.fdc.files import TempDir
from juloserver.followthemoney.models import LenderCurrent, LenderBucket
from juloserver.julo.constants import FeatureNameConst, WorkflowConst
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import (
    Application,
    ApplicationHistory,
    BlacklistCustomer,
    Customer,
    FDCInquiry,
    FDCInquiryLoan,
    FeatureSetting,
    Loan,
    Partner,
    Payment,
    ProductLine,
    ProductLookup,
    StatusLookup,
    UploadAsyncState,
    Workflow,
    CreditScore,
)
from juloserver.julo.partners import PartnerConstant
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services import process_application_status_change
from juloserver.julo.statuses import (
    ApplicationStatusCodes,
    LoanStatusCodes,
    PaymentStatusCodes,
)
from juloserver.julo.utils import trim_name, upload_file_to_oss
from juloserver.julo.workflows2.tasks import process_validate_bank_task
from juloserver.partnership.constants import (
    AGENT_ASSISTED_COMPLETE_DATA_STATUS_UPDATE_HEADERS,
    AGENT_ASSISTED_FDC_PRE_CHECK_HEADERS,
    AGENT_ASSISTED_PRE_CHECK_HEADERS,
    AGENT_ASSISTED_UPLOAD_USER_DATA_HEADERS,
    INDONESIA,
    PRE_CHECK_IDENTIFIER,
    PRE_CHECK_SUFFIX_EMAIL,
    PRODUCT_FINANCING_LOAN_CREATION_UPLOAD_HEADERS,
    AgentAssistedUploadType,
    PartnershipImageProductType,
    PartnershipImageType,
    PartnershipPreCheckFlag,
    PartnershipProductFlow,
    PartnershipRejectReason,
    PartnershipUploadImageDestination,
    ProductFinancingUploadActionType,
    PRODUCT_FINANCING_LOAN_DISBURSEMENT_UPLOAD_HEADERS,
    PartnershipFlag,
    PRODUCT_FINANCING_LENDER_APPROVAL_UPLOAD_HEADERS,
    PartnershipTelcoScoringStatus,
    PartnershipCLIKScoringStatus,
)
from juloserver.partnership.crm.pre_check_validator import PreCheckExistedValidator
from juloserver.partnership.crm.serializers import (
    AgentAssistedCompleteUserDataStatusUpdateSerializer,
    AgentAssistedFDCPreCheckSerializer,
    AgentAssistedPreCheckSerializer,
    AgentAssistedUploadScoringUserDataSerializer,
    ProductFinancingLoanCreationSerializer,
)
from juloserver.partnership.crm.utils import (
    format_product_financing_loan_creation_csv_upload,
)
from juloserver.partnership.models import (
    PartnerLoanRequest,
    PartnershipApplicationFlag,
    PartnershipCustomerData,
    PartnershipFlowFlag,
    PartnershipProduct,
    PartnershipApplicationFlagHistory,
    PartnershipClikModelResult,
)
from juloserver.partnership.services.clik import PartnershipCLIKClient
from juloserver.partnership.tasks import (
    partnership_run_fdc_inquiry_for_registration,
    send_email_agent_assisted,
    upload_partnership_image_from_url,
    send_email_skrtp_gosel,
    partnership_trigger_process_validate_bank,
)
from juloserver.partnership.telco_scoring import PartnershipTelcoScore
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.loan.services.loan_related import (
    update_loan_status_and_loan_history,
)
from juloserver.partnership.services.account_payment import (
    create_or_update_account_payments,
)
from juloserver.followthemoney.services import (
    assign_lenderbucket_xid_to_lendersignature_service,
    reassign_lender_julo_one,
    RedisCacheLoanBucketXidPast,
)
from juloserver.followthemoney.utils import (
    generate_lenderbucket_xid,
)

logger = logging.getLogger(__name__)


def upload_csv_data_to_oss(upload_async_state, file_path=None, product_name='agent_assisted'):
    if file_path:
        local_file_path = file_path
    else:
        local_file_path = upload_async_state.file.path
    path_and_name, extension = os.path.splitext(local_file_path)
    file_name_elements = path_and_name.split('/')
    dest_name = "{}/{}/{}".format(
        product_name, upload_async_state.id, file_name_elements[-1] + extension
    )
    upload_file_to_oss(settings.OSS_MEDIA_BUCKET, local_file_path, dest_name)

    if os.path.isfile(local_file_path):
        local_dir = os.path.dirname(local_file_path)
        upload_async_state.file.delete()
        if not file_path:
            os.rmdir(local_dir)

    upload_async_state.update_safely(url=dest_name)


def write_row_result(
    row: Dict,
    is_passed: bool,
    notes: str,
    application_xid: str = "",
    partner_name: str = "",
    type: str = AgentAssistedUploadType.PRE_CHECK_APPLICATION,
) -> List:
    if type == AgentAssistedUploadType.SCORING_DATA_UPLOAD:
        return [
            row.get("application_xid"),
            row.get("email"),
            row.get("ktp"),
            row.get("dob"),
            row.get("gender"),
            row.get("address_provinsi"),
            row.get("occupied_since"),
            row.get("home_status"),
            row.get("dependent"),
            row.get("mobile_phone_1"),
            row.get("job_type"),
            row.get("job_industry"),
            row.get("job_description"),
            row.get("job_start"),
            row.get("payday"),
            row.get("last_education"),
            row.get("monthly_income"),
            row.get("monthly_expenses"),
            row.get("monthly_housing_cost"),
            row.get("total_current_debt"),
            is_passed,
            notes,
        ]
    elif type == AgentAssistedUploadType.PRE_CHECK_APPLICATION:
        return [
            row.get('name'),
            row.get('nik'),
            row.get('email'),
            row.get('phone'),
            row.get('loan_purpose'),
            row.get('agent_code'),
            partner_name,
            str(application_xid),
            is_passed,
            notes,
        ]
    elif type == AgentAssistedUploadType.FDC_PRE_CHECK_APPLICATION:
        return [
            row.get("application_xid"),
            row.get('gender'),
            row.get('dob'),
            row.get('birth_place'),
            row.get('address_street_num'),
            row.get('address_kabupaten'),
            row.get('address_kecamatan'),
            row.get('address_kelurahan'),
            row.get('address_kodepos'),
            row.get('address_provinsi'),
            row.get('nik'),
            row.get('email'),
            row.get('phone'),
            row.get('name'),
            row.get('partner_name'),
            is_passed,
            notes,
        ]
    elif type == AgentAssistedUploadType.COMPLETE_USER_DATA_STATUS_UPDATE_UPLOAD:
        return [
            row.get("application_xid", ""),
            row.get("email", ""),
            row.get("mobile_phone_1", ""),
            row.get("birth_place", ""),
            row.get("mother_maiden_name", ""),
            row.get("address_street_num", ""),
            row.get("address_kabupaten", ""),
            row.get("address_kecamatan", ""),
            row.get("address_kelurahan", ""),
            row.get("address_kodepos", ""),
            row.get("marital_status", ""),
            row.get("close_kin_name", ""),
            row.get("close_kin_mobile_phone", ""),
            row.get("spouse_name", ""),
            row.get("spouse_mobile_phone", ""),
            row.get("kin_relationship", ""),
            row.get("kin_name", ""),
            row.get("kin_mobile_phone", ""),
            row.get("company_name", ""),
            row.get("company_phone_number", ""),
            row.get("bank_name", ""),
            row.get("bank_account_number", ""),
            row.get("ktp_photo", ""),
            row.get("selfie_photo", ""),
            row.get("photo_of_income_proof", ""),
            is_passed,
            notes,
        ]
    elif type == ProductFinancingUploadActionType.LOAN_CREATION:
        return [
            row.get("Application XID"),
            row.get('Name'),
            row.get('Product ID'),
            row.get('Amount Requested (Rp)'),
            row.get('Tenor'),
            row.get('Tenor type'),
            row.get('Interest Rate'),
            row.get('Provision Rate'),
            row.get('Loan Start Date'),
            is_passed,
            notes,
        ]
    elif type == ProductFinancingUploadActionType.LOAN_DISBURSEMENT:
        return [
            row.get("loan_xid"),
            row.get("disburse_time"),
            is_passed,
            notes,
        ]
    elif type == ProductFinancingUploadActionType.LENDER_APPROVAL:
        return [
            row.get("Loan XID"),
            row.get("Decision"),
            notes,
        ]


@transaction.atomic
def masking_pre_check_rejected_user(application: Application) -> None:
    nik = application.partnership_customer_data.nik
    phone = application.partnership_customer_data.phone_number
    application_id = application.id

    masked_email = '{}+{}'.format(nik, PRE_CHECK_SUFFIX_EMAIL)
    masked_phone = '{}{}'.format(ProductLineCodes.PARTNERSHIP_PRE_CHECK, phone)
    masked_nik = '{}{}{}'.format(
        PRE_CHECK_IDENTIFIER, ProductLineCodes.PARTNERSHIP_PRE_CHECK, application_id
    )

    customer = application.customer
    user = customer.user

    user.username = masked_nik
    user.email = masked_email
    user.save()

    customer.email = masked_email
    customer.phone = masked_phone
    customer.nik = masked_nik
    customer.save()

    application.email = masked_email
    application.ktp = masked_nik
    application.mobile_phone_1 = masked_phone
    application.save()


def agent_assisted_upload_user_pre_check(
    upload_async_state: UploadAsyncState,
    partner: Partner
) -> bool:
    upload_file = upload_async_state.file
    file_io = io.StringIO(upload_file.read().decode('utf-8'))
    reader = csv.DictReader(file_io, delimiter=',')
    is_success_all = True
    local_file_path = upload_async_state.file.path
    partner_name = partner.name

    with TempDir(dir="/media") as tempdir:
        path_and_name, extension = os.path.splitext(local_file_path)
        file_name_elements = path_and_name.split('/')
        filename = file_name_elements[-1] + extension
        dir_path = tempdir.path
        file_path = os.path.join(dir_path, filename)

        with open(file_path, "w", encoding='utf-8-sig') as f:
            write = csv.writer(f)
            write.writerow(AGENT_ASSISTED_PRE_CHECK_HEADERS)

            for row in reader:
                formatted_data = dict(row)

                if partner_name == PartnerConstant.GOSEL:
                    formatted_data['loan_purpose'] = 'Membeli elektronik'

                serializer = AgentAssistedPreCheckSerializer(
                    data=formatted_data,
                )

                is_passed = False
                application_xid = "-"
                if not serializer.is_valid():
                    error_list = serializer.errors.get('non_field_errors')
                    notes = ', '.join(error_list)
                    write.writerow(
                        write_row_result(
                            formatted_data,
                            is_passed,
                            notes,
                            application_xid,
                            partner_name
                        )
                    )
                    is_success_all = False
                    continue

                validated_data = serializer.validated_data
                name = validated_data['name']
                nik = validated_data['nik']
                email = validated_data['email']
                phone = validated_data['phone']
                loan_purpose = validated_data['loan_purpose']

                application_data = None
                is_existing_user_id = (
                    User.objects.filter(username=nik).values_list('id', flat=True).first()
                )
                if is_existing_user_id:
                    application_data = (
                        Application.objects.filter(customer__user__id=is_existing_user_id)
                        .values('id', 'application_status', 'customer_id', 'application_xid')
                        .last()
                    )
                    if not application_data:
                        notes = (
                            "nik sudah terdaftar ditable user dan tidak memiliki application data"
                        )
                        write.writerow(
                            write_row_result(
                                formatted_data,
                                is_passed,
                                notes,
                                application_xid,
                                partner_name
                            )
                        )
                        is_success_all = False
                        continue

                    pre_check_validator = PreCheckExistedValidator(application_data)
                    application_id = application_data['id']
                    application_xid = application_data['application_xid']

                    if not pre_check_validator.is_have_application_status():
                        notes = "nik sudah terdaftar ditable user dan application status kosong"
                        write.writerow(
                            write_row_result(
                                formatted_data,
                                is_passed,
                                notes,
                                application_xid,
                                partner_name
                            )
                        )
                        is_success_all = False
                        continue

                    if not pre_check_validator.is_have_partnership_customer_data():
                        notes = "nik sudah terdaftar, tidak memiliki data di partnership customer"
                        write.writerow(
                            write_row_result(
                                formatted_data,
                                is_passed,
                                notes,
                                application_xid,
                                partner_name
                            )
                        )
                        is_success_all = False
                        continue

                    if not pre_check_validator.is_application_have_flag():
                        notes = "nik sudah terdaftar dan application flag tidak valid"
                        write.writerow(
                            write_row_result(
                                formatted_data,
                                is_passed,
                                notes,
                                application_xid,
                                partner_name
                            )
                        )
                        is_success_all = False
                        continue

                    if not pre_check_validator.is_passed_application():
                        notes = "nik sudah terdaftar dan application bukan 100 / 106 status"
                        write.writerow(
                            write_row_result(
                                formatted_data,
                                is_passed,
                                notes,
                                application_xid,
                                partner_name
                            )
                        )
                        is_success_all = False
                        continue

                # Customer Data Checking
                is_existing_customer_nik_id = Customer.objects.filter(
                    nik=nik
                ).values_list('id', flat=True).last()

                if is_existing_customer_nik_id:
                    customer_result_checking = check_existing_customer_data(
                        customer_id=is_existing_customer_nik_id,
                        existing_user_id=is_existing_user_id
                    )

                    application_data = customer_result_checking.application_data
                    application_id = application_data.get('id')
                    application_xid = application_data.get('application_xid', '-')
                    if not customer_result_checking.is_valid:
                        notes = customer_result_checking.notes
                        write.writerow(
                            write_row_result(
                                formatted_data,
                                is_passed,
                                notes,
                                application_xid,
                                partner_name
                            )
                        )
                        is_success_all = False
                        continue

                is_existing_customer_email_id = Customer.objects.filter(
                    email=email
                ).values_list('id', flat=True).last()

                if is_existing_customer_email_id:
                    customer_result_checking = check_existing_customer_data(
                        customer_id=is_existing_customer_email_id,
                        existing_user_id=is_existing_user_id
                    )

                    application_data = customer_result_checking.application_data
                    application_id = application_data.get('id')
                    application_xid = application_data.get('application_xid', '-')
                    if not customer_result_checking.is_valid:
                        notes = customer_result_checking.notes
                        write.writerow(
                            write_row_result(
                                formatted_data,
                                is_passed,
                                notes,
                                application_xid,
                                partner_name
                            )
                        )
                        is_success_all = False
                        continue

                is_existing_customer_phone_id = Customer.objects.filter(
                    phone=phone
                ).values_list('id', flat=True).last()

                if is_existing_customer_phone_id:
                    customer_result_checking = check_existing_customer_data(
                        customer_id=is_existing_customer_phone_id,
                        existing_user_id=is_existing_user_id
                    )

                    application_data = customer_result_checking.application_data
                    application_id = application_data.get('id')
                    application_xid = application_data.get('application_xid', '-')
                    if not customer_result_checking.is_valid:
                        notes = customer_result_checking.notes
                        write.writerow(
                            write_row_result(
                                formatted_data,
                                is_passed,
                                notes,
                                application_xid,
                                partner_name
                            )
                        )
                        is_success_all = False
                        continue

                # Check partnership customer data
                partnership_customer_data_nik = PartnershipCustomerData.objects.filter(
                    nik=nik, partner=partner
                ).last()

                if partnership_customer_data_nik:
                    partner_cust_data_result = check_existing_partnership_customer_data(
                        partnership_customer_data=partnership_customer_data_nik,
                        application_data=application_data
                    )
                    if not partner_cust_data_result.is_valid:
                        notes = partner_cust_data_result.notes
                        application_xid = partner_cust_data_result.existing_application_xid
                        write.writerow(
                            write_row_result(
                                formatted_data,
                                is_passed,
                                notes,
                                application_xid,
                                partner_name
                            )
                        )
                        is_success_all = False
                        continue

                partnership_customer_data_email = PartnershipCustomerData.objects.filter(
                    email=email, partner=partner
                ).last()

                if partnership_customer_data_email:
                    partner_cust_data_result = check_existing_partnership_customer_data(
                        partnership_customer_data=partnership_customer_data_email,
                        application_data=application_data
                    )
                    if not partner_cust_data_result.is_valid:
                        notes = partner_cust_data_result.notes
                        application_xid = partner_cust_data_result.existing_application_xid
                        write.writerow(
                            write_row_result(
                                formatted_data,
                                is_passed,
                                notes,
                                application_xid,
                                partner_name
                            )
                        )
                        is_success_all = False
                        continue

                partnership_customer_data_phone = PartnershipCustomerData.objects.filter(
                    phone_number=phone, partner=partner
                ).last()

                if partnership_customer_data_phone:
                    partner_cust_data_result = check_existing_partnership_customer_data(
                        partnership_customer_data=partnership_customer_data_phone,
                        application_data=application_data
                    )
                    if not partner_cust_data_result.is_valid:
                        notes = partner_cust_data_result.notes
                        application_xid = partner_cust_data_result.existing_application_xid
                        write.writerow(
                            write_row_result(
                                formatted_data,
                                is_passed,
                                notes,
                                application_xid,
                                partner_name
                            )
                        )
                        is_success_all = False
                        continue

                is_reapply = False
                if application_data:
                    application_xid = application_data['application_xid']

                    flag_name = PartnershipApplicationFlag.objects.filter(
                        application_id=application_data['id']
                    ).values_list('name', flat=True).last()

                    if (
                        application_data['application_status']
                        == ApplicationStatusCodes.FORM_CREATED
                    ):
                        if flag_name == PartnershipPreCheckFlag.PASSED_PRE_CHECK:
                            notes = (
                                "nik / email / phone terdaftar dan application sudah di cek "
                                "sebelumnya silahkan lanjut ke FDC Check"
                            )
                            is_passed = True
                            write.writerow(
                                write_row_result(
                                    formatted_data,
                                    is_passed,
                                    notes,
                                    application_xid,
                                    partner_name
                                )
                            )
                            is_success_all = False
                            continue
                        elif flag_name == PartnershipPreCheckFlag.REGISTER_FROM_PORTAL:
                            application = Application.objects.filter(
                                application_xid=application_xid
                            ).last()

                            notes = set()
                            if application.partner.name.lower() != partner_name.lower():
                                notes.add(
                                    "Selected partner name {} tidak sama dengan "
                                    "existing application partner name {}"
                                    .format(partner_name, application.partner.name)
                                )
                            if email.lower() != application.email.lower():
                                notes.add(
                                    "Email yang diupload {} "
                                    "tidak sama dengan existing application email {}"
                                    .format(email, application.email)
                                )
                            if nik != application.ktp:
                                notes.add(
                                    "NIK yang diupload {} "
                                    "tidak sama dengan existing application NIK {}"
                                    .format(nik, application.ktp)
                                )
                            if phone != application.mobile_phone_1:
                                notes.add(
                                    "Phone Number yang diupload {} tidak sama dengan "
                                    "existing application phone number {}"
                                    .format(phone, application.mobile_phone_1)
                                )
                            if name.lower() != application.fullname.lower():
                                notes.add(
                                    "Nama yang diupload {} tidak sama dengan "
                                    "existing application fullname {}"
                                    .format(name, application.fullname)
                                )

                            if notes:
                                write.writerow(
                                    write_row_result(
                                        formatted_data,
                                        is_passed,
                                        ", ".join(notes),
                                        application_xid,
                                        partner_name,
                                    )
                                )
                                is_success_all = False
                                continue

                    elif (
                        application_data['application_status']
                        == ApplicationStatusCodes.FORM_PARTIAL_EXPIRED
                    ):
                        # Re-apply
                        existed_partnership_customer_data = PartnershipCustomerData.objects.filter(
                            customer_id=application_data['customer_id']
                        ).last()

                        if not existed_partnership_customer_data:
                            notes = (
                                "Gagal Re-apply, karena existing data"
                                "tidak memiliki partnership customer data"
                            )
                            write.writerow(
                                write_row_result(
                                    formatted_data, is_passed, notes, application_xid, partner_name
                                )
                            )
                            is_success_all = False
                            continue

                        is_reapply = True
                        application = pre_check_create_user_data(
                            partner=partner,
                            nik=nik,
                            name=name,
                            email=email,
                            phone=phone,
                            loan_purpose=loan_purpose,
                            re_apply=True,
                            customer_id=application_data['customer_id'],
                            referral_code=validated_data['agent_code'],
                        )

                        existed_partnership_customer_data.update_safely(
                            application_id=application.id
                        )
                    else:
                        notes = (
                            "Customer data terdaftar, application status {} tidak valid"
                        ).format(application_data['application_status'])
                        write.writerow(
                            write_row_result(
                                formatted_data,
                                is_passed,
                                notes,
                                application_xid,
                                partner_name
                            )
                        )
                        is_success_all = False
                        continue
                else:
                    # Create User, Customer, Application
                    application = pre_check_create_user_data(
                        partner=partner,
                        nik=nik,
                        name=name,
                        email=email,
                        phone=phone,
                        loan_purpose=loan_purpose,
                        re_apply=False,
                        referral_code=validated_data['agent_code'],
                    )

                # Validate blacklist customer
                stripped_name = trim_name(name)
                black_list_customer = BlacklistCustomer.objects.filter(
                    fullname_trim=stripped_name, citizenship=INDONESIA
                ).exists()

                application_id = application.id
                application_xid = application.application_xid
                customer_id = application.customer.id

                if black_list_customer:
                    notes = "nama customer sudah diblacklist"
                    write.writerow(
                        write_row_result(
                            formatted_data,
                            is_passed,
                            notes,
                            application_xid,
                            partner_name
                        )
                    )
                    is_success_all = False

                    # Change application flag to NOT_PASSED_PRE_CHECK
                    pre_check_rejected_application(
                        application,
                        PartnershipPreCheckFlag.NOT_PASSED_PRE_CHECK,
                        ApplicationStatusCodes.APPLICATION_DENIED,
                        PartnershipRejectReason.BLACKLISTED,
                        is_reapply,
                    )
                    continue

                # Fraud Check
                fraud_status = ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD
                fraud_account_status = {
                    AccountConstant.STATUS_CODE.fraud_reported,
                    AccountConstant.STATUS_CODE.application_or_friendly_fraud,
                }

                nik_application = (
                    Application.objects.filter(ktp=nik)
                    .exclude(id=application.id)
                    .values('id', 'account__status')
                    .last()
                )
                if nik_application:
                    nik_application_id = nik_application['id']
                    account_status = nik_application['account__status']
                    if ApplicationHistory.objects.filter(
                        application_id=nik_application_id, status_new=fraud_status
                    ).exists():
                        notes = "nik ini memiliki application fraud"
                        write.writerow(
                            write_row_result(
                                formatted_data,
                                is_passed,
                                notes,
                                application_xid,
                                partner_name
                            )
                        )
                        is_success_all = False

                        # Change application flag to NOT_PASSED_PRE_CHECK
                        pre_check_rejected_application(
                            application,
                            PartnershipPreCheckFlag.NOT_PASSED_PRE_CHECK,
                            ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                            PartnershipRejectReason.FRAUD,
                            is_reapply,
                        )
                        continue

                    if account_status in fraud_account_status:
                        notes = "nik ini memiliki account status fraud"
                        write.writerow(
                            write_row_result(
                                formatted_data,
                                is_passed,
                                notes,
                                application_xid,
                                partner_name
                            )
                        )
                        is_success_all = False

                        pre_check_rejected_application(
                            application,
                            PartnershipPreCheckFlag.NOT_PASSED_PRE_CHECK,
                            ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                            PartnershipRejectReason.FRAUD,
                            is_reapply,
                        )
                        continue

                phone_application = (
                    Application.objects.filter(mobile_phone_1=phone)
                    .exclude(id=application.id)
                    .values('id', 'account__status')
                    .last()
                )
                if phone_application:
                    phone_application_id = phone_application['id']
                    account_status = phone_application['account__status']
                    if ApplicationHistory.objects.filter(
                        application_id=phone_application_id, status_new=fraud_status
                    ).exists():
                        notes = "phone number ini memiliki application fraud"
                        write.writerow(
                            write_row_result(
                                formatted_data,
                                is_passed,
                                notes,
                                application_xid,
                                partner_name
                            )
                        )
                        is_success_all = False

                        # Change application flag to NOT_PASSED_PRE_CHECK
                        pre_check_rejected_application(
                            application,
                            PartnershipPreCheckFlag.NOT_PASSED_PRE_CHECK,
                            ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                            PartnershipRejectReason.FRAUD,
                            is_reapply,
                        )
                        continue

                    if account_status in fraud_account_status:
                        notes = "phone number ini memiliki account status fraud"
                        write.writerow(
                            write_row_result(
                                formatted_data,
                                is_passed,
                                notes,
                                application_xid,
                                partner_name
                            )
                        )
                        is_success_all = False

                        # Change application flag to NOT_PASSED_PRE_CHECK
                        pre_check_rejected_application(
                            application,
                            PartnershipPreCheckFlag.NOT_PASSED_PRE_CHECK,
                            ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                            PartnershipRejectReason.FRAUD,
                            is_reapply,
                        )
                        continue

                spouse_phone_number_application_fraud = (
                    Application.objects.filter(
                        spouse_mobile_phone=phone,
                        applicationhistory__status_new=fraud_status,
                    )
                    .exclude(id=application.id)
                    .exists()
                )
                if spouse_phone_number_application_fraud:
                    notes = "phone number ini memiliki spouse phone application fraud"
                    write.writerow(
                        write_row_result(
                            formatted_data,
                            is_passed,
                            notes,
                            application_xid,
                            partner_name
                        )
                    )
                    is_success_all = False

                    # Change application flag to NOT_PASSED_PRE_CHECK
                    pre_check_rejected_application(
                        application,
                        PartnershipPreCheckFlag.NOT_PASSED_PRE_CHECK,
                        ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                        PartnershipRejectReason.FRAUD,
                        is_reapply,
                    )
                    continue

                kin_phone_number_application_fraud = (
                    Application.objects.filter(
                        kin_mobile_phone=phone,
                        applicationhistory__status_new=fraud_status,
                    )
                    .exclude(id=application.id)
                    .exists()
                )

                if kin_phone_number_application_fraud:
                    notes = "phone number ini memiliki kin phone application fraud"
                    write.writerow(
                        write_row_result(
                            formatted_data,
                            is_passed,
                            notes,
                            application_xid,
                            partner_name
                        )
                    )
                    is_success_all = False

                    # Change application flag to NOT_PASSED_PRE_CHECK
                    pre_check_rejected_application(
                        application,
                        PartnershipPreCheckFlag.NOT_PASSED_PRE_CHECK,
                        ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                        PartnershipRejectReason.FRAUD,
                        is_reapply,
                    )
                    continue

                mobile_phone_2_application_fraud = (
                    Application.objects.filter(
                        mobile_phone_2=phone,
                        applicationhistory__status_new=fraud_status,
                    )
                    .exclude(id=application.id)
                    .exists()
                )

                if mobile_phone_2_application_fraud:
                    notes = "phone number ini memiliki mobile_phone_2 application fraud"
                    write.writerow(
                        write_row_result(
                            formatted_data,
                            is_passed,
                            notes,
                            application_xid,
                            partner_name
                        )
                    )
                    is_success_all = False

                    # Change application flag to NOT_PASSED_PRE_CHECK
                    pre_check_rejected_application(
                        application,
                        PartnershipPreCheckFlag.NOT_PASSED_PRE_CHECK,
                        ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                        PartnershipRejectReason.FRAUD,
                        is_reapply,
                    )
                    continue

                is_passed = True

                # Change application flag to PASSED_PRE_CHECK
                passed_application_id = application.id
                PartnershipApplicationFlag.objects.update_or_create(
                    application_id=passed_application_id,
                    defaults={
                        'name': PartnershipPreCheckFlag.PASSED_PRE_CHECK
                    }
                )

                PartnershipApplicationFlagHistory.objects.create(
                    old_application_id=passed_application_id,
                    application_id=passed_application_id,
                    status_old=None,
                    status_new=PartnershipPreCheckFlag.PASSED_PRE_CHECK,
                )

                fdc_inquiry = FDCInquiry.objects.create(
                    nik=nik, customer_id=customer_id, application_id=application_id
                )
                fdc_inquiry_data = {'id': fdc_inquiry.id, 'nik': nik}
                partnership_run_fdc_inquiry_for_registration.delay(fdc_inquiry_data, 1)

                notes = 'Application berhasil dibuat'
                write.writerow(
                    write_row_result(
                        formatted_data,
                        is_passed,
                        notes,
                        application_xid,
                        partner_name
                    )
                )

        upload_csv_data_to_oss(upload_async_state, file_path=file_path)

    return is_success_all


@transaction.atomic
def pre_check_create_user_data(
    partner: Partner,
    nik: str,
    name: str,
    email: str,
    phone: str,
    loan_purpose: str,
    re_apply: bool = False,
    customer_id: int = None,
    register_from_portal: bool = False,
    other_phone_number: str = None,
    referral_code: str = None,
) -> Application:
    workflow = Workflow.objects.get(name=WorkflowConst.JULO_ONE)
    product_line = ProductLine.objects.get(pk=ProductLineCodes.J1)

    if not re_apply:
        user = User(username=nik, email=email)
        user.save()

        customer = Customer.objects.create(
            user=user,
            fullname=name,
            email=email,
            phone=phone,
            nik=nik,
            appsflyer_device_id=None,
            advertising_id=None,
            mother_maiden_name=None,
        )

        application_data = {
            "customer": customer,
            "email": email,
            "fullname": name,
            "partner": partner,
            "ktp": nik,
            "mobile_phone_1": phone,
            "loan_purpose": loan_purpose,
            "workflow": workflow,
            "product_line": product_line,
            "payday": 1,
            "referral_code": referral_code,
        }

        if other_phone_number:
            application_data.update({"mobile_phone_2": other_phone_number})

        application = Application.objects.create(**application_data)

        PartnershipCustomerData.objects.create(
            email=email,
            phone_number=phone,
            application=application,
            customer=customer,
            nik=nik,
            partner=partner,
        )

        if register_from_portal:
            application_id = application.id
            PartnershipApplicationFlag.objects.update_or_create(
                application_id=application_id,
                name=PartnershipPreCheckFlag.REGISTER_FROM_PORTAL,
            )
    else:
        if not customer_id:
            raise JuloException('Re apply case but customer_id is set None')

        application = Application.objects.create(
            customer_id=customer_id,
            email=email,
            fullname=name,
            partner=partner,
            ktp=nik,
            mobile_phone_1=phone,
            loan_purpose=loan_purpose,
            workflow=workflow,
            product_line=product_line,
            payday=1,
            referral_code=referral_code,
        )

    # Set application STATUS to 100
    application.change_status(ApplicationStatusCodes.FORM_CREATED)
    application.save(update_fields=['application_status_id'])

    return application


def pre_check_rejected_application(
    application: Application,
    application_flag_name: str,
    new_status_code: int,
    change_reason: str,
    is_reapply: bool = False,
) -> None:
    old_application_flag_name = None
    old_partnership_application_flag = PartnershipApplicationFlag.objects.filter(
        application_id=application.id
    ).last()
    if old_partnership_application_flag:
        old_application_flag_name = old_partnership_application_flag.name

    # If not re-apply not masking the user data
    application_id = application.id
    PartnershipApplicationFlag.objects.update_or_create(
        application_id=application.id,
        defaults={
            'name': application_flag_name
        }
    )

    PartnershipApplicationFlagHistory.objects.create(
        old_application_id=application_id,
        application_id=application_id,
        status_old=old_application_flag_name,
        status_new=application_flag_name,
    )

    if not is_reapply:
        masking_pre_check_rejected_user(application)

    process_application_status_change(
        application_id,
        new_status_code,
        change_reason=change_reason,
    )


def check_existing_customer_data(customer_id: int, existing_user_id: int = None) -> Tuple:
    application_data = (
        Application.objects.filter(customer__id=customer_id)
        .values(
            'id',
            'application_status',
            'customer_id',
            'customer__user_id',
            'application_xid',
        )
        .last()
    ) or {}

    ValidationResult = namedtuple('Result', ['is_valid', 'notes', 'application_data'])
    if not application_data:
        notes = "nik / email / phone terdaftar dan tidak memiliki application data"
        return ValidationResult(False, notes, application_data)

    pre_check_validator = PreCheckExistedValidator(application_data)
    if not pre_check_validator.is_have_application_status():
        notes = "nik sudah terdaftar ditable user dan application status kosong"
        return ValidationResult(False, notes, application_data)

    if not pre_check_validator.is_have_partnership_customer_data():
        notes = (
            "nik / email / phone terdaftar dan "
            "tidak memiliki data di partnership customer"
        )
        return ValidationResult(False, notes, application_data)

    if not pre_check_validator.is_application_have_flag():
        notes = "nik / email / phone terdaftar dan application flag tidak valid"
        return ValidationResult(False, notes, application_data)

    if not pre_check_validator.is_passed_application():
        notes = (
            "nik / email / phone terdaftar dan application bukan 100 / 106 status"
        )
        return ValidationResult(False, notes, application_data)

    if existing_user_id != application_data['customer__user_id']:
        notes = (
            "user id yang terdaftar tidak sama"
            " dengan data customer yang terdaftar"
        )
        return ValidationResult(False, notes, application_data)

    return ValidationResult(True, "-", application_data)


def check_existing_partnership_customer_data(
    partnership_customer_data: PartnershipCustomerData,
    application_data: Dict = None
) -> Tuple:
    existing_application_xid = '-'
    ValidationResult = namedtuple('Result', ['is_valid', 'notes', 'existing_application_xid'])
    if not partnership_customer_data.application:
        notes = (
            "nik / email / phone sudah terdaftar di partnership "
            "customer data dan application tidak ditemukan"
        )
        return ValidationResult(False, notes, existing_application_xid)

    if not partnership_customer_data.customer:
        notes = (
            "nik / email / phone sudah terdaftar di partnership "
            "customer data dan customer data tidak ditemukan"
        )
        return ValidationResult(False, notes, existing_application_xid)

    application = partnership_customer_data.application
    customer = partnership_customer_data.customer

    existing_application_xid = application.application_xid

    # not agent assisted flow
    application_id = application.id
    flag_name = (
        PartnershipApplicationFlag.objects.filter(application_id=application_id)
        .values_list('name', flat=True)
        .last()
    )
    if not flag_name:
        notes = (
            "nik / email / phone sudah terdaftar di partnership "
            "customer data dan application ini bukan agent assisted flow"
        )
        return ValidationResult(False, notes, existing_application_xid)

    # Handle if exisitng application founded but mismatch application_id
    # Maybe application_id is used on other product flow
    if application_data:
        if application.id != application_data['id']:
            notes = (
                "nik / email / phone sudah terdaftar di partnership "
                "dan application id mismatch dengan existing data"
            )
            return ValidationResult(False, notes, existing_application_xid)

        if customer.id != application_data['customer_id']:
            notes = (
                "nik / email / phone sudah terdaftar di partnership "
                "dan customer id mismatch dengan existing data"
            )
            return ValidationResult(False, notes, existing_application_xid)
    else:
        # Showing reject information
        # because on this step this application should be rejected
        application_status = application.status

        notes = (
            "Data sudah terdaftar di partnership customer data "
            "application_status: {}, flag: {}, "
            "tidak memenuhi syarat"
        ).format(application_status, flag_name)
        return ValidationResult(False, notes, existing_application_xid)

    return ValidationResult(True, '-', '-')


def partnership_pre_check_application(
    application: Application,
    flag_name: str,
) -> bool:
    """
        This function will do these:
        - flag == passed_binary_pre_check will continue to running usuall J1 Underwriting
        - flag == passed_fdc_pre_check will continue to check binary and C score
        - else will stuck the application on 105 because doesn't have flag path

        On flag passed_fdc_pre_check process:
        - Expired Application to 106 status
        - if not C Score / pass binary check update flag and re-create application
        with flag passed_binary_pre_check
        - If C Score / not pass binary check update flag to not_passed_binary_pre_check
    """
    from juloserver.partnership.tasks import async_process_partnership_application_binary_pre_check

    is_pre_check_stage = False
    if flag_name == PartnershipPreCheckFlag.APPROVED:
        logger.info(
            {
                'action': 'partnership_pre_check_application',
                'message': 'No need re-create application, will continue Underwriting as usual',
                'application_status': str(application.status),
                'application': application.id,
                'application_flag_name': flag_name,
            }
        )

        return is_pre_check_stage
    elif flag_name in {
        PartnershipPreCheckFlag.ELIGIBLE_TO_BINARY_PRE_CHECK,
        PartnershipPreCheckFlag.PENDING_CREDIT_SCORE_GENERATION,
    }:
        # Handling if credit score not yet generated we pass as async and do retry mechanism
        is_pre_check_stage = True
        is_credit_score_generated = CreditScore.objects.filter(
            application_id=application.id
        ).exists()
        if is_credit_score_generated:
            partnership_application_binary_pre_check(application, flag_name)
        else:
            async_process_partnership_application_binary_pre_check.delay(application.id)

        return is_pre_check_stage
    else:
        logger.error(
            {
                'action': 'partnership_pre_check_application',
                'message': (
                    'Agent Assisted flag not valid, only allowed flag eligible_to_binary_pre_check'
                ),
                'application_status': str(application.status),
                'application': application.id,
                'application_flag_name': flag_name,
            }
        )

        return is_pre_check_stage


def agent_assisted_upload_scoring_user_data(upload_async_state: UploadAsyncState) -> bool:
    upload_file = upload_async_state.file
    file_io = io.StringIO(upload_file.read().decode('utf-8'))
    reader = csv.DictReader(file_io, delimiter=',')
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
            write.writerow(AGENT_ASSISTED_UPLOAD_USER_DATA_HEADERS)

            application_xids = []
            for row in reader:
                if row['application_xid'] and row['application_xid'].isnumeric():
                    application_xids.append(int(row["application_xid"]))

            applications = Application.objects.filter(
                application_xid__in=application_xids
            ).select_related('partner')
            application_dict = dict()
            for application in applications:
                application_dict[application.application_xid] = application

            file_io.seek(0)
            reader.__init__(file_io, delimiter=',')
            for row in reader:
                is_passed = False
                notes = ""

                if not row.get('payday'):
                    row['payday'] = None

                if not row.get('job_start'):
                    row['job_start'] = None

                if not row['application_xid'].isnumeric():
                    notes = 'application_xid tidak numerik'
                    is_success_all = False
                    write.writerow(
                        write_row_result(
                            row,
                            is_passed,
                            notes,
                            row['application_xid'],
                            type=AgentAssistedUploadType.SCORING_DATA_UPLOAD,
                        )
                    )
                    continue

                application_xid = int(row['application_xid'])
                application = application_dict.get(application_xid)
                if not application:
                    notes = 'application tidak ditemukan'
                    is_success_all = False
                    write.writerow(
                        write_row_result(
                            row,
                            is_passed,
                            notes,
                            application_xid,
                            type=AgentAssistedUploadType.SCORING_DATA_UPLOAD,
                        )
                    )
                    continue

                if application.application_status_id != ApplicationStatusCodes.FORM_CREATED:
                    notes = 'application status tidak 100'
                    is_success_all = False
                    write.writerow(
                        write_row_result(
                            row,
                            is_passed,
                            notes,
                            application_xid,
                            type=AgentAssistedUploadType.SCORING_DATA_UPLOAD,
                        )
                    )
                    continue

                application_id = application.id
                application_flag = PartnershipApplicationFlag.objects.filter(
                    application_id=application_id,
                    name=PartnershipPreCheckFlag.ELIGIBLE_TO_BINARY_PRE_CHECK,
                ).exists()
                if not application_flag:
                    notes = 'application flag tidak pass eligibility check'
                    is_success_all = False
                    write.writerow(
                        write_row_result(
                            row,
                            is_passed,
                            notes,
                            application_xid,
                            type=AgentAssistedUploadType.SCORING_DATA_UPLOAD,
                        )
                    )
                    continue

                # CLIK model result check
                clik_model_result = PartnershipClikModelResult.objects.get_or_none(
                    application_id=application_id
                )
                if clik_model_result:
                    if clik_model_result.status != 'success':
                        notes = 'clik model status tidak valid'
                        is_success_all = False
                        write.writerow(
                            write_row_result(
                                row,
                                is_passed,
                                notes,
                                application_xid,
                                type=AgentAssistedUploadType.SCORING_DATA_UPLOAD,
                            )
                        )
                        continue
                    else:
                        clik = PartnershipCLIKClient(application)
                        eligibile_clik_model = clik.leadgen_eligible_passed_clik_model()

                        if eligibile_clik_model in PartnershipCLIKScoringStatus.bad_result_list():
                            notes = 'clik model not passed'
                            is_success_all = False

                            write.writerow(
                                write_row_result(
                                    row,
                                    is_passed,
                                    notes,
                                    application_xid,
                                    type=AgentAssistedUploadType.SCORING_DATA_UPLOAD,
                                )
                            )
                            flag_name = PartnershipPreCheckFlag.NOT_PASSED_CLIK_PRE_CHECK
                            pre_check_rejected_application(
                                application=application,
                                application_flag_name=flag_name,
                                new_status_code=ApplicationStatusCodes.APPLICATION_DENIED,
                                change_reason=PartnershipRejectReason.BLACKLISTED,
                            )
                            logger.info(
                                {
                                    'action': "agent_assisted_upload_scoring_user_data",
                                    'message': notes,
                                    'application_status': str(application.status),
                                    'application': application_id,
                                    'application_flag_name': flag_name,
                                }
                            )
                            continue

                        elif eligibile_clik_model == PartnershipCLIKScoringStatus.EMPTY_RESULT:
                            # Since the CLIK result is empty, it is necessary to check whether
                            # the other pre-checks are also empty.
                            is_fdc_telco_empty = check_fdc_and_telco_empty(application)

                            # Reject application if FDC and Telco have empty result
                            if is_fdc_telco_empty:
                                notes = (
                                    'Not passed FDC, CLIK and Telco pre check. '
                                    'Pre check has not result'
                                )
                                is_success_all = False

                                write.writerow(
                                    write_row_result(
                                        row,
                                        is_passed,
                                        notes,
                                        application_xid,
                                        type=AgentAssistedUploadType.SCORING_DATA_UPLOAD,
                                    )
                                )
                                flag_name = PartnershipPreCheckFlag.NOT_PASSED_CLIK_PRE_CHECK
                                pre_check_rejected_application(
                                    application=application,
                                    application_flag_name=flag_name,
                                    new_status_code=ApplicationStatusCodes.APPLICATION_DENIED,
                                    change_reason=PartnershipRejectReason.BLACKLISTED,
                                )
                                logger.info(
                                    {
                                        'action': "agent_assisted_upload_scoring_user_data",
                                        'message': notes,
                                        'application_status': str(application.status),
                                        'application': application_id,
                                        'application_flag_name': flag_name,
                                    }
                                )
                                continue

                check_identical_rows = ['email', 'ktp', 'mobile_phone_1']
                identical = True
                for check_identical_row in check_identical_rows:
                    if getattr(application, check_identical_row) != row[check_identical_row]:
                        notes = '{} tidak sama'.format(check_identical_row)
                        is_success_all = False
                        write.writerow(
                            write_row_result(
                                row,
                                is_passed,
                                notes,
                                application_xid,
                                type=AgentAssistedUploadType.SCORING_DATA_UPLOAD,
                            )
                        )
                        identical = False
                        break

                if not identical:
                    continue

                row['bank_name'] = ''
                partner = application.partner
                if not partner:
                    notes = 'data partner pada application tidak valid'
                    is_success_all = False
                    write.writerow(
                        write_row_result(
                            row,
                            is_passed,
                            notes,
                            application_xid,
                            type=AgentAssistedUploadType.SCORING_DATA_UPLOAD,
                        )
                    )
                    continue
                """
                For now we Hardcode this field:
                -job_type
                -job_industry
                -job_description
                -payday
                this only for Partner gojektsel
                """
                if partner.name == PartnerConstant.GOSEL:
                    row['job_type'] = 'Freelance'
                    row['job_industry'] = 'Transportasi'
                    row['job_description'] = 'Supir / Ojek'
                    row['payday'] = 15

                field_flag = PartnershipFlowFlag.objects.filter(
                    partner_id=partner.id,
                    name=PartnershipFlag.FIELD_CONFIGURATION
                ).last()
                field_configs = {}
                if field_flag and field_flag.configs:
                    field_configs = field_flag.configs

                # Remove DOB, gender & address_provinsi field if exists,
                # because already saved on step 2
                data = row
                if 'dob' in data.keys():
                    data.pop("dob")

                if 'gender' in data.keys():
                    data.pop("gender")

                if 'address_provinsi' in data.keys():
                    data.pop("address_provinsi")

                serializer = AgentAssistedUploadScoringUserDataSerializer(
                    application, data=data, partial=True, context={'field_config': field_configs}
                )

                if not serializer.is_valid():
                    notes = serializer.errors
                    is_success_all = False
                    write.writerow(
                        write_row_result(
                            row,
                            is_passed,
                            notes,
                            application_xid,
                            type=AgentAssistedUploadType.SCORING_DATA_UPLOAD,
                        )
                    )
                    continue

                # Set to None if data is empty to avoid error when saving to database
                if not serializer.validated_data['dependent']:
                    serializer.validated_data['dependent'] = None

                if not serializer.validated_data['monthly_expenses']:
                    serializer.validated_data['monthly_expenses'] = None

                if not serializer.validated_data['occupied_since']:
                    serializer.validated_data['occupied_since'] = None

                application = serializer.save()
                process_application_status_change(
                    application,
                    ApplicationStatusCodes.FORM_PARTIAL,
                    change_reason='agent_assisted',
                )
                is_passed = True
                write.writerow(
                    write_row_result(
                        row,
                        is_passed,
                        notes,
                        application_xid,
                        type=AgentAssistedUploadType.SCORING_DATA_UPLOAD,
                    )
                )

        upload_csv_data_to_oss(upload_async_state, file_path=file_path)
    return is_success_all


def agent_assisted_upload_user_fdc_pre_check(
    upload_async_state: UploadAsyncState, partner: Partner
) -> bool:
    upload_file = upload_async_state.file
    file_io = io.StringIO(upload_file.read().decode('utf-8'))
    reader = csv.DictReader(file_io, delimiter=',')
    is_success_all = True
    local_file_path = upload_async_state.file.path
    partner_name = partner.name

    with TempDir(dir="/media") as tempdir:
        path_and_name, extension = os.path.splitext(local_file_path)
        file_name_elements = path_and_name.split('/')
        filename = file_name_elements[-1] + extension
        dir_path = tempdir.path
        file_path = os.path.join(dir_path, filename)

        with open(file_path, "w", encoding='utf-8-sig') as f:
            write = csv.writer(f)
            write.writerow(AGENT_ASSISTED_FDC_PRE_CHECK_HEADERS)
            has_rows = any(True for row in reader)
            if not has_rows:
                raise JuloException('The CSV file does not contain any data')

            file_io.seek(0)
            reader.__init__(file_io, delimiter=',')
            for row in reader:
                formatted_data = dict(row)
                formatted_data['nik'] = "-"
                formatted_data['email'] = "-"
                formatted_data['phone'] = "-"
                formatted_data['partner_name'] = partner_name
                formatted_data['name'] = "-"
                serializer = AgentAssistedFDCPreCheckSerializer(
                    data=formatted_data,
                )
                is_passed = False
                if not serializer.is_valid():
                    error_list = serializer.errors.get('non_field_errors')
                    notes = ', '.join(error_list)
                    write.writerow(
                        write_row_result(
                            row=formatted_data,
                            is_passed=is_passed,
                            notes=notes,
                            type=AgentAssistedUploadType.FDC_PRE_CHECK_APPLICATION,
                        )
                    )
                    is_success_all = False
                    continue

                validated_data = serializer.validated_data
                application = validated_data['application']
                application_id = application.id
                formatted_data['nik'] = application.ktp
                formatted_data['email'] = application.email
                formatted_data['phone'] = application.mobile_phone_1
                formatted_data['name'] = application.fullname

                if application.status != ApplicationStatusCodes.FORM_CREATED:
                    notes = "application sudah terdaftar dan application status bukan 100"
                    write.writerow(
                        write_row_result(
                            row=formatted_data,
                            is_passed=is_passed,
                            notes=notes,
                            type=AgentAssistedUploadType.FDC_PRE_CHECK_APPLICATION,
                        )
                    )
                    is_success_all = False
                    continue

                partnership_application_flag = PartnershipApplicationFlag.objects.filter(
                    application_id=application_id,
                    name=PartnershipPreCheckFlag.PASSED_PRE_CHECK,
                ).last()

                if not partnership_application_flag:
                    notes = "application sudah terdaftar dan application flag tidak pass pre check"
                    write.writerow(
                        write_row_result(
                            row=formatted_data,
                            is_passed=is_passed,
                            notes=notes,
                            type=AgentAssistedUploadType.FDC_PRE_CHECK_APPLICATION,
                        )
                    )
                    is_success_all = False
                    continue

                # Save Application data
                application.update_safely(
                    gender=serializer.validated_data['gender'],
                    dob=serializer.validated_data['dob'],
                    birth_place=serializer.validated_data['birth_place'],
                    address_street_num=serializer.validated_data['address_street_num'],
                    address_kabupaten=serializer.validated_data['address_kabupaten'],
                    address_kecamatan=serializer.validated_data['address_kecamatan'],
                    address_kelurahan=serializer.validated_data['address_kelurahan'],
                    address_kodepos=serializer.validated_data['address_kodepos'],
                    address_provinsi=serializer.validated_data['address_provinsi'],
                )
                application.refresh_from_db()

                # FDC check
                data_precheck_fdc = fdc_binary_check_agent_assisted(application_id)
                is_fdc_check_pass = data_precheck_fdc.get('status')
                inquiry_status = data_precheck_fdc.get('inquiry_status')
                fdc_result_notes = data_precheck_fdc.get('fdc_result')
                is_empty_fdc_result = False

                if not is_fdc_check_pass:
                    notes = 'fdc pre check not passed'
                    if inquiry_status in {'pending', 'error'}:
                        is_success_all = False
                        """
                        This case to handle if user have status fdc pending or error
                        """
                        notes = fdc_result_notes
                        write.writerow(
                            write_row_result(
                                row=formatted_data,
                                is_passed=is_passed,
                                notes=notes,
                                type=AgentAssistedUploadType.FDC_PRE_CHECK_APPLICATION,
                            )
                        )
                        logger.info(
                            {
                                'action': 'partnership_fdc_pre_check_application',
                                'message': fdc_result_notes,
                                'application_status': str(application.status),
                                'application': application_id,
                            }
                        )
                        continue

                    elif inquiry_status == 'not_found':
                        is_empty_fdc_result = True
                        logger.info(
                            {
                                'action': 'partnership_fdc_pre_check_application',
                                'message': fdc_result_notes,
                                'application_status': str(application.status),
                                'application': application_id,
                            }
                        )

                    else:
                        is_success_all = False
                        """
                        This case to handle if user not passed FDC Pre check
                        We will rejected the application
                        """
                        write.writerow(
                            write_row_result(
                                row=formatted_data,
                                is_passed=is_passed,
                                notes=notes,
                                type=AgentAssistedUploadType.FDC_PRE_CHECK_APPLICATION,
                            )
                        )
                        flag_name = PartnershipPreCheckFlag.NOT_PASSED_FDC_PRE_CHECK
                        pre_check_rejected_application(
                            application=application,
                            application_flag_name=flag_name,
                            new_status_code=ApplicationStatusCodes.APPLICATION_DENIED,
                            change_reason=PartnershipRejectReason.BLACKLISTED,
                        )
                        logger.info(
                            {
                                'action': 'partnership_fdc_pre_check_application',
                                'message': fdc_result_notes,
                                'application_status': str(application.status),
                                'application': application_id,
                                'application_flag_name': flag_name,
                            }
                        )
                        continue

                # Telco scoring check
                telco = PartnershipTelcoScore(application=application)
                telco_scoring_result = telco.run_in_eligibility_check()
                is_empty_telco_result = False
                if telco_scoring_result in PartnershipTelcoScoringStatus.bad_result_list():
                    notes = 'telco score pre check not passed'
                    is_success_all = False

                    write.writerow(
                        write_row_result(
                            row=formatted_data,
                            is_passed=is_passed,
                            notes=notes,
                            type=AgentAssistedUploadType.FDC_PRE_CHECK_APPLICATION,
                        )
                    )
                    flag_name = PartnershipPreCheckFlag.NOT_PASSED_TELCO_PRE_CHECK
                    pre_check_rejected_application(
                        application=application,
                        application_flag_name=flag_name,
                        new_status_code=ApplicationStatusCodes.APPLICATION_DENIED,
                        change_reason=PartnershipRejectReason.BLACKLISTED,
                    )
                    logger.info(
                        {
                            'action': "partnership_fdc_pre_check_application",
                            'message': notes,
                            'application_status': str(application.status),
                            'application': application_id,
                            'application_flag_name': flag_name,
                        }
                    )
                    continue

                elif telco_scoring_result in PartnershipTelcoScoringStatus.FAILED_TELCO_SCORING:
                    notes = (
                        "Telco check failed due to a network error. "
                        "Please try again to upload this data."
                    )
                    is_success_all = False

                    write.writerow(
                        write_row_result(
                            row=formatted_data,
                            is_passed=is_passed,
                            notes=notes,
                            type=AgentAssistedUploadType.FDC_PRE_CHECK_APPLICATION,
                        )
                    )
                    logger.info(
                        {
                            'action': "partnership_fdc_pre_check_application",
                            'message': notes,
                            'application_status': str(application.status),
                            'application': application_id,
                        }
                    )
                    continue

                elif telco_scoring_result in PartnershipTelcoScoringStatus.not_found_result_list():
                    is_empty_telco_result = True

                # CLICK scoring check
                clik = PartnershipCLIKClient(application)
                click_model_process = clik.partnership_process_clik_model()

                if click_model_process in PartnershipCLIKScoringStatus.bad_result_list():
                    notes = 'clik score pre check not passed'
                    is_success_all = False

                    write.writerow(
                        write_row_result(
                            row=formatted_data,
                            is_passed=is_passed,
                            notes=notes,
                            type=AgentAssistedUploadType.FDC_PRE_CHECK_APPLICATION,
                        )
                    )
                    flag_name = PartnershipPreCheckFlag.NOT_PASSED_CLIK_PRE_CHECK
                    pre_check_rejected_application(
                        application=application,
                        application_flag_name=flag_name,
                        new_status_code=ApplicationStatusCodes.APPLICATION_DENIED,
                        change_reason=PartnershipRejectReason.BLACKLISTED,
                    )
                    logger.info(
                        {
                            'action': "partnership_fdc_pre_check_application",
                            'message': notes,
                            'application_status': str(application.status),
                            'application': application_id,
                            'application_flag_name': flag_name,
                        }
                    )
                    continue

                elif click_model_process == PartnershipCLIKScoringStatus.FAILED_CLICK_SCORING:
                    notes = (
                        "CLIK check failed due to a network error. "
                        "Please try again to upload this data."
                    )
                    is_success_all = False

                    write.writerow(
                        write_row_result(
                            row=formatted_data,
                            is_passed=is_passed,
                            notes=notes,
                            type=AgentAssistedUploadType.FDC_PRE_CHECK_APPLICATION,
                        )
                    )
                    logger.info(
                        {
                            'action': "partnership_fdc_pre_check_application",
                            'message': notes,
                            'application_status': str(application.status),
                            'application': application_id,
                        }
                    )
                    continue

                # Reject application if FDC and Telco have empty result
                if is_empty_fdc_result and is_empty_telco_result:
                    notes = 'Not passed FDC and Telco pre check. Pre check has not result'
                    is_success_all = False

                    write.writerow(
                        write_row_result(
                            row=formatted_data,
                            is_passed=is_passed,
                            notes=notes,
                            type=AgentAssistedUploadType.FDC_PRE_CHECK_APPLICATION,
                        )
                    )
                    flag_name = PartnershipPreCheckFlag.NOT_ELIGIBLE_TO_BINARY_PRE_CHECK
                    pre_check_rejected_application(
                        application=application,
                        application_flag_name=flag_name,
                        new_status_code=ApplicationStatusCodes.APPLICATION_DENIED,
                        change_reason=PartnershipRejectReason.BLACKLISTED,
                    )
                    logger.info(
                        {
                            'action': "partnership_fdc_pre_check_application",
                            'message': notes,
                            'application_status': str(application.status),
                            'application': application_id,
                            'application_flag_name': flag_name,
                            'is_empty_telco_result': is_empty_telco_result,
                            'is_fdc_check_pass': is_fdc_check_pass,
                        }
                    )
                    continue

                # Update Flag to Passed FDC Pre-check
                partnership_application_flag.update_safely(
                    name=PartnershipPreCheckFlag.ELIGIBLE_TO_BINARY_PRE_CHECK
                )
                PartnershipApplicationFlagHistory.objects.create(
                    old_application_id=application_id,
                    application_id=application_id,
                    status_old=PartnershipPreCheckFlag.PASSED_PRE_CHECK,
                    status_new=PartnershipPreCheckFlag.ELIGIBLE_TO_BINARY_PRE_CHECK,
                )
                notes = 'Passed FDC and Telco pre check'
                if click_model_process == PartnershipCLIKScoringStatus.bypass_result_list():
                    notes += '. CLIK checking not active'

                if telco_scoring_result == PartnershipTelcoScoringStatus.bypass_result_list():
                    notes += '. Telco scoring is not active'

                if is_empty_fdc_result:
                    notes += '. FDC inquiry not found'

                is_passed = True
                write.writerow(
                    write_row_result(
                        row=formatted_data,
                        is_passed=is_passed,
                        notes=notes,
                        type=AgentAssistedUploadType.FDC_PRE_CHECK_APPLICATION,
                    )
                )

        upload_csv_data_to_oss(upload_async_state, file_path=file_path)
    return is_success_all


def fdc_binary_check_agent_assisted(application_id: int) -> Dict:
    data = {
        'status': False,
        'inquiry_status': '-',
        'fdc_result': '-',
    }
    fdc_agent_assisted_setting = FeatureSetting.objects.filter(
        is_active=True, feature_name=FeatureNameConst.FDC_PRE_CHECK_AGENT_ASSISTED
    ).last()

    if not fdc_agent_assisted_setting:
        data = {
            'status': True,
            'inquiry_status': '-',
            'fdc_result': 'FDC passed due to feature setting turned off, please ask administrator',
        }
        return data

    fdc_inquiry = FDCInquiry.objects.filter(
        application_id=application_id,
        inquiry_date__isnull=False,
        inquiry_reason='1 - Applying loan via Platform'
    ).last()

    if not fdc_inquiry or (
        fdc_inquiry and fdc_inquiry.inquiry_status not in {'pending', 'error', 'success'}
    ):
        error_msg = 'Unexpected error in FDC, please contact PRE to run script then upload again'
        data = {
            'status': False,
            'inquiry_status': 'error',
            'fdc_result': error_msg,
        }
        return data

    inquiry_status = fdc_inquiry.inquiry_status

    if inquiry_status == 'pending':
        data = {
            'status': False,
            'inquiry_status': inquiry_status,
            'fdc_result': 'FDC still on process, Please try to upload the file again later',
        }
        return data

    if inquiry_status == 'error':
        error_msg = 'Unexpected error in FDC, please contact PRE to run script then upload again'
        data = {
            'status': False,
            'inquiry_status': inquiry_status,
            'fdc_result': error_msg,
        }
        return data

    if fdc_inquiry.status.lower() == 'not found':
        error_msg = 'FDC inquiry not found.'
        data = {
            'status': False,
            'inquiry_status': 'not_found',
            'fdc_result': error_msg,
        }
        return data

    # check tidak_lancar / macet count
    bad_loans = FDCInquiryLoan.objects.filter(
        fdc_inquiry=fdc_inquiry,
        tgl_pelaporan_data__gte=fdc_inquiry.inquiry_date - relativedelta(years=1),
        kualitas_pinjaman__in=(
            FDCFieldsName.TIDAK_LANCAR,
            FDCFieldsName.MACET,
            FDCFieldsName.LANCAR,
        ),
    )

    total_non_smooth_credit = 0
    total_bad_credit = 0
    total_current_credit = 0
    bad_loans = bad_loans.values('kualitas_pinjaman').annotate(total=Count('kualitas_pinjaman'))

    for bad_loan in bad_loans:
        if bad_loan['kualitas_pinjaman'] == FDCFieldsName.TIDAK_LANCAR:
            total_non_smooth_credit = bad_loan['total']

        elif bad_loan['kualitas_pinjaman'] == FDCFieldsName.MACET:
            total_bad_credit = bad_loan['total']

        elif bad_loan['kualitas_pinjaman'] == FDCFieldsName.LANCAR:
            total_current_credit = bad_loan['total']
    total_credit = total_current_credit + total_bad_credit + total_non_smooth_credit

    criteria_value = 0
    if total_credit:
        criteria_value = float(total_bad_credit) / total_credit

    min_macet_pct_setting = fdc_agent_assisted_setting.parameters['min_macet_pct']
    max_paid_percentage_setting = fdc_agent_assisted_setting.parameters['max_paid_pct']

    exists_fdc_inquiry_check = min_macet_pct_setting < criteria_value

    if exists_fdc_inquiry_check:
        data = {
            'status': False,
            'inquiry_status': inquiry_status,
            'fdc_result': 'FDC failed due to criteria value ({}) > min_macet_setting'.format(
                round(criteria_value, 2)
            ),
        }
        return data

    # check paid_pct
    today = timezone.localtime(timezone.now()).date()
    get_loans = FDCInquiryLoan.objects.filter(
        fdc_inquiry=fdc_inquiry,
        tgl_pelaporan_data__gte=fdc_inquiry.inquiry_date - relativedelta(days=1),
        tgl_jatuh_tempo_pinjaman__lt=today,
    )

    if not get_loans:
        data = {
            'status': True,
            'inquiry_status': inquiry_status,
            'fdc_result': 'FDC passed due to passing all criteria',
        }
        return data

    get_loans = get_loans.aggregate(
        outstanding_amount=Sum('nilai_pendanaan') - Sum('sisa_pinjaman_berjalan'),
        total_amount=Sum('nilai_pendanaan'),
    )

    paid_pct, outstanding_amount, total_amount = 0, 0, 0
    if get_loans['outstanding_amount']:
        outstanding_amount = get_loans['outstanding_amount']

    if get_loans['total_amount']:
        total_amount = get_loans['total_amount']

    if total_amount > 0:
        paid_pct = float(outstanding_amount) / float(total_amount)

    exists_fdc_inquiry_check = max_paid_percentage_setting > paid_pct

    if exists_fdc_inquiry_check:
        data = {
            'status': False,
            'inquiry_status': inquiry_status,
            'fdc_result': 'FDC failed due to paid_pct ({}) < max_paid_pct_setting'.format(
                round(paid_pct, 2)
            ),
        }
        return data

    data = {
        'status': True,
        'inquiry_status': inquiry_status,
        'fdc_result': 'FDC passed due to passing all criteria',
    }
    return data


def agent_assisted_process_complete_user_data_update_status(
    upload_async_state: UploadAsyncState,
) -> bool:
    upload_file = upload_async_state.file
    file_io = io.StringIO(upload_file.read().decode('utf-8'))
    reader = csv.DictReader(file_io, delimiter=',')
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
            write.writerow(AGENT_ASSISTED_COMPLETE_DATA_STATUS_UPDATE_HEADERS)

            process_type = AgentAssistedUploadType.COMPLETE_USER_DATA_STATUS_UPDATE_UPLOAD
            for row in reader:
                formatted_data = dict(row)

                serializer = AgentAssistedCompleteUserDataStatusUpdateSerializer(
                    data=formatted_data
                )

                is_need_create_ktp_image = False
                is_need_create_selfie_image = False
                is_passed = False
                if not serializer.is_valid():
                    error_list = serializer.errors.get('non_field_errors')
                    notes = ', '.join(error_list)
                    write.writerow(
                        write_row_result(
                            formatted_data,
                            is_passed,
                            notes,
                            type=process_type
                        )
                    )
                    is_success_all = False
                    continue

                validated_data = serializer.validated_data
                application = validated_data['application']

                application_id = application.id
                application_flag = PartnershipApplicationFlag.objects.filter(
                    application_id=application_id,
                    name=PartnershipPreCheckFlag.APPROVED,
                ).exists()
                if not application_flag:
                    notes = 'Application data tidak memiliki flag approved'
                    write.writerow(
                        write_row_result(
                            formatted_data,
                            is_passed,
                            notes,
                            type=process_type,
                        )
                    )
                    is_success_all = False
                    continue

                if application.status != ApplicationStatusCodes.FORM_CREATED:
                    notes = 'Application harus memiliki status code 100'
                    write.writerow(
                        write_row_result(
                            formatted_data,
                            is_passed,
                            notes,
                            type=process_type,
                        )
                    )
                    is_success_all = False
                    continue

                if validated_data.get('is_need_create_ktp_image'):
                    if not validated_data.get('ktp_photo'):
                        notes = 'ktp_photo tidak ditemukan'
                        write.writerow(
                            write_row_result(
                                formatted_data,
                                is_passed,
                                notes,
                                type=process_type,
                            )
                        )
                        is_success_all = False
                        continue

                    is_need_create_ktp_image = True

                if validated_data.get('is_need_create_selfie_image'):
                    if not validated_data.get('selfie_photo'):
                        notes = 'selfie_photo tidak ditemukan'
                        write.writerow(
                            write_row_result(
                                formatted_data,
                                is_passed,
                                notes,
                                type=process_type,
                            )
                        )
                        is_success_all = False
                        continue

                    is_need_create_selfie_image = True

                # Upload Image
                if is_need_create_ktp_image:
                    ktp_image_url = validated_data.get('ktp_photo')
                    upload_partnership_image_from_url.delay(
                        image_url=ktp_image_url,
                        image_type=PartnershipImageType.KTP_SELF,
                        application_id=application.id,
                        product_type=PartnershipImageProductType.LEADGEN,
                        upload_to=PartnershipUploadImageDestination.IMAGE_TABLE,
                    )

                if is_need_create_selfie_image:
                    selfie_image_url = validated_data.get('selfie_photo')
                    upload_partnership_image_from_url.delay(
                        image_url=selfie_image_url,
                        image_type=PartnershipImageType.SELFIE,
                        application_id=application.id,
                        product_type=PartnershipImageProductType.LEADGEN,
                        upload_to=PartnershipUploadImageDestination.IMAGE_TABLE,
                    )

                if validated_data.get('photo_of_income_proof'):
                    income_image_url = validated_data.get('photo_of_income_proof')
                    upload_partnership_image_from_url.delay(
                        image_url=income_image_url,
                        image_type=PartnershipImageType.PAYSTUB,
                        application_id=application.id,
                        product_type=PartnershipImageProductType.LEADGEN,
                        upload_to=PartnershipUploadImageDestination.IMAGE_TABLE,
                    )

                customer = application.customer
                name_in_bank = application.fullname
                application.update_safely(
                    marital_status=validated_data.get('marital_status'),
                    close_kin_name=validated_data.get('close_kin_name'),
                    close_kin_mobile_phone=validated_data.get('close_kin_mobile_phone'),
                    spouse_name=validated_data.get('spouse_name'),
                    spouse_mobile_phone=validated_data.get('spouse_mobile_phone'),
                    kin_relationship=validated_data.get('kin_relationship'),
                    kin_name=validated_data.get('kin_name'),
                    kin_mobile_phone=validated_data.get('kin_mobile_phone'),
                    company_name=validated_data.get('company_name'),
                    company_phone_number=validated_data.get('company_phone_number'),
                    name_in_bank=name_in_bank,
                    bank_name=validated_data.get('bank_name'),
                    bank_account_number=validated_data.get('bank_account_number'),
                )

                customer.update_safely(mother_maiden_name=validated_data.get('mother_maiden_name'))

                """
                validating the bank if the bank information is empty we do bypass
                """
                partner_id = application.partner_id
                partnership_application_flag = (
                    PartnershipFlowFlag.objects.filter(
                        partner_id=partner_id,
                        name=PartnershipFlag.PAYMENT_GATEWAY_SERVICE,
                    )
                    .values_list('configs', flat=True)
                    .last()
                )
                if partnership_application_flag and partnership_application_flag.get(
                    'payment_gateway_service', True
                ):
                    if not application.bank_name or not application.bank_account_number:
                        # no validation when the config is not there since already handled
                        # on serializer
                        field_flag = PartnershipFlowFlag.objects.filter(
                            partner_id=application.partner.id,
                            name=PartnershipFlag.FIELD_CONFIGURATION,
                        ).last()
                        if field_flag:
                            # If flag set to False, we do bypass name bank validation
                            if not field_flag.configs.get(
                                'bank_name'
                            ) or not field_flag.configs.get('bank_account_number'):
                                from juloserver.partnership.services.services import (
                                    bypass_name_bank_validation,
                                )

                                bypass_name_bank_validation(application)
                    else:
                        partnership_trigger_process_validate_bank.delay(application.id)
                else:
                    process_validate_bank_task.apply_async(args=(application.id,))

                # Process applicaiton to 105
                process_application_status_change(
                    application.id,
                    ApplicationStatusCodes.FORM_PARTIAL,
                    change_reason='system_triggered',
                )
                is_passed = True
                notes = 'Success'
                write.writerow(
                    write_row_result(
                        formatted_data,
                        is_passed,
                        notes,
                        type=process_type,
                    )
                )

        upload_csv_data_to_oss(upload_async_state, file_path=file_path)

    return is_success_all


def product_financing_loan_creation_upload(upload_async_state: UploadAsyncState) -> bool:
    upload_file = upload_async_state.file
    file_io = io.StringIO(upload_file.read().decode("utf-8"))
    reader = csv.DictReader(file_io, delimiter=",")
    is_success_all = True
    local_file_path = upload_async_state.file.path

    with TempDir(dir="/media") as tempdir:
        path_and_name, extension = os.path.splitext(local_file_path)
        file_name_elements = path_and_name.split("/")
        filename = file_name_elements[-1] + extension
        dir_path = tempdir.path
        file_path = os.path.join(dir_path, filename)

        with open(file_path, "w", encoding="utf-8-sig") as f:
            write = csv.writer(f)
            write.writerow(PRODUCT_FINANCING_LOAN_CREATION_UPLOAD_HEADERS)

            application_xids = []
            partnership_products_ids = []
            for row in reader:
                if row["Application XID"] and row["Application XID"].isnumeric():
                    application_xids.append(row["Application XID"])
                if row["Product ID"] and row["Application XID"].isnumeric():
                    partnership_products_ids.append(row["Product ID"])

            applications = Application.objects.filter(
                application_xid__in=application_xids
            ).select_related("account", "partner", "customer")
            application_dict = dict()
            for application in applications:
                application_dict[application.application_xid] = application

            partnership_products = PartnershipProduct.objects.filter(
                id__in=partnership_products_ids
            )
            partnership_product_dict = {}
            for partnership_product in partnership_products:
                partnership_product_dict[partnership_product.id] = partnership_product

            file_io.seek(0)
            reader.__init__(file_io, delimiter=",")
            for row in reader:
                is_passed = False
                notes = ""

                formatted_data = format_product_financing_loan_creation_csv_upload(row)
                serializer = ProductFinancingLoanCreationSerializer(data=formatted_data)
                if not serializer.is_valid():
                    notes = serializer.errors
                    is_success_all = False
                    write.writerow(
                        write_row_result(
                            row,
                            is_passed,
                            notes,
                            row["Application XID"],
                            type=ProductFinancingUploadActionType.LOAN_CREATION,
                        )
                    )
                    continue

                application_xid = int(row["Application XID"])
                application = application_dict.get(application_xid)
                if not application:
                    notes = "application/user tidak ditemukan"
                    is_success_all = False
                    write.writerow(
                        write_row_result(
                            row,
                            is_passed,
                            notes,
                            row["Application XID"],
                            type=ProductFinancingUploadActionType.LOAN_CREATION,
                        )
                    )
                    continue

                partnership_product = partnership_product_dict.get(int(row["Product ID"]))
                if not partnership_product:
                    notes = "ID Product Invalid"
                    is_success_all = False
                    write.writerow(
                        write_row_result(
                            row,
                            is_passed,
                            notes,
                            row["Application XID"],
                            type=ProductFinancingUploadActionType.LOAN_CREATION,
                        )
                    )
                    continue

                is_success, message = create_product_financing_loan(
                    application, partnership_product, serializer.validated_data
                )
                if not is_success:
                    is_success_all = False

                write.writerow(
                    write_row_result(
                        row,
                        is_success,
                        message,
                        row["Application XID"],
                        type=ProductFinancingUploadActionType.LOAN_CREATION,
                    )
                )

        upload_csv_data_to_oss(
            upload_async_state, file_path=file_path, product_name="product_financing"
        )

    return is_success_all


def create_product_financing_loan(
    application: Application,
    partnership_product: PartnershipProduct,
    loan_request_data: dict,
) -> (bool, str):
    loan_request_data_key = {
        "loan_amount_request",
        "loan_duration",
        "loan_duration_type",
        "interest_rate",
        "origination_fee_pct",
        "loan_start_date",
    }
    for key in loan_request_data_key:
        if key not in loan_request_data:
            return False, "loan_request_data tidak memiliki key: {}".format(key)

    application_not_190 = application.application_status_id != ApplicationStatusCodes.LOC_APPROVED
    if application_not_190:
        return False, "application status tidak 190"

    account_not_420 = (
        not application.account
        or application.account.status_id != AccountConstant.STATUS_CODE.active
    )
    if account_not_420:
        return False, "account status tidak 420"

    partner_not_gosel = not application.partner or application.partner.name != PartnerConstant.GOSEL
    if partner_not_gosel:
        return False, "partner tidak gosel"

    if partnership_product.product_price != loan_request_data["loan_amount_request"]:
        return False, "jumlah pinjaman invalid"

    account_limit = application.account.accountlimit_set.first()
    if account_limit.available_limit < loan_request_data["loan_amount_request"]:
        return False, "limit tidak mencukupi"

    product_lookup = ProductLookup.objects.filter(
        product_line=application.product_line,
        interest_rate=loan_request_data["interest_rate"],
        origination_fee_pct=loan_request_data["origination_fee_pct"],
        late_fee_pct=0,
    ).first()
    if not product_lookup:
        return False, "product lookup tidak ditemukan"

    jtp = LenderCurrent.objects.filter(lender_name="jtp").first()
    if not jtp:
        return False, "lender tidak ditemukan"

    origination_fee_amount = (
        loan_request_data["loan_amount_request"] * product_lookup.origination_fee_pct
    )
    loan_amount = loan_request_data["loan_amount_request"] + origination_fee_amount
    rounded_loan_amount = decimal.Decimal(loan_amount).to_integral_value(
        rounding=decimal.ROUND_HALF_UP
    )

    installment_principal = rounded_loan_amount / loan_request_data["loan_duration"]
    rounded_installment_principal = decimal.Decimal(installment_principal).to_integral_value(
        rounding=decimal.ROUND_HALF_UP
    )

    installment_interest = (
        loan_request_data["loan_amount_request"] * product_lookup.monthly_interest_rate
    )
    rounded_installment_interest = decimal.Decimal(installment_interest).to_integral_value(
        rounding=decimal.ROUND_HALF_UP
    )

    total_installment_amount = rounded_installment_principal + rounded_installment_interest
    with transaction.atomic():
        loan = Loan.objects.create(
            customer=application.customer,
            application_id2=application.id,
            loan_amount=rounded_loan_amount,
            loan_duration=loan_request_data["loan_duration"],
            installment_amount=total_installment_amount,
            first_installment_amount=total_installment_amount,
            loan_status=StatusLookup.objects.get(status_code=LoanStatusCodes.INACTIVE),
            loan_disbursement_amount=loan_request_data["loan_amount_request"],
            account=application.account,
            lender=jtp,
            product=product_lookup,
            loan_purpose="modal usaha",
            transaction_method_id=TransactionMethodCode.OTHER.code,  # Kirim Dana,
        )
        PartnerLoanRequest.objects.create(
            loan=loan,
            partner=application.partner,
            loan_amount=loan_request_data["loan_amount_request"],
            loan_disbursement_amount=loan.loan_disbursement_amount,
            loan_original_amount=loan_request_data["loan_amount_request"],
            loan_request_date=loan.cdate,
            interest_rate=loan_request_data["interest_rate"],
            provision_rate=loan_request_data["origination_fee_pct"],
            loan_duration_type=loan_request_data["loan_duration_type"].lower(),
            partnership_product=partnership_product,
        )
        update_available_limit(loan)

        payment_status = StatusLookup.objects.get(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE)
        payments = []
        for payment_number in range(loan_request_data["loan_duration"]):
            due_date = loan_request_data["loan_start_date"] + relativedelta(months=payment_number)
            payment = Payment(
                loan=loan,
                payment_status=payment_status,
                payment_number=payment_number + 1,
                due_date=due_date,
                due_amount=total_installment_amount,
                installment_principal=rounded_installment_principal,
                installment_interest=rounded_installment_interest,
            )
            payments.append(payment)

        Payment.objects.bulk_create(payments)

    send_email_skrtp_gosel.delay(
        loan.id,
        round((product_lookup.monthly_interest_rate * 100), 2),
        loan.cdate,
        partnership_product.product_name,
    )

    return True, "Loan data valid dengan loan_xid: {}".format(loan.loan_xid)


def product_financing_loan_disbursement_upload(upload_async_state: UploadAsyncState) -> bool:
    upload_file = upload_async_state.file
    upload_time = upload_async_state.cdate
    file_io = io.StringIO(upload_file.read().decode("utf-8"))
    reader = csv.DictReader(file_io, delimiter=",")
    is_success_all = True
    local_file_path = upload_async_state.file.path

    with TempDir(dir="/media") as tempdir:
        path_and_name, extension = os.path.splitext(local_file_path)
        file_name_elements = path_and_name.split("/")
        filename = file_name_elements[-1] + extension
        dir_path = tempdir.path
        file_path = os.path.join(dir_path, filename)

        with open(file_path, "w", encoding="utf-8-sig") as f:
            write = csv.writer(f)
            write.writerow(PRODUCT_FINANCING_LOAN_DISBURSEMENT_UPLOAD_HEADERS)

            loan_xids = []
            for row in reader:
                if row["loan_xid"] and row["loan_xid"].isnumeric():
                    loan_xids.append(row["loan_xid"])

            payment_prefetch = Prefetch(
                'payment_set',
                queryset=Payment.objects.all()
                .select_related("account_payment")
                .order_by('payment_number'),
                to_attr='payments',
            )
            loans = (
                Loan.objects.prefetch_related('payment_set')
                .select_related("account")
                .prefetch_related(payment_prefetch)
                .filter(loan_xid__in=loan_xids)
            )

            loan_dict = dict()
            account_dict = dict()
            for loan in loans:
                loan_dict[loan.loan_xid] = loan
                account_dict[loan.loan_xid] = loan.account

            file_io.seek(0)
            reader.__init__(file_io, delimiter=",")
            for row in reader:
                is_passed = False
                notes = ""

                if not row["loan_xid"].isnumeric():
                    notes = "loan_xid must be a number"
                    is_success_all = False
                    write.writerow(
                        write_row_result(
                            row,
                            is_passed,
                            notes,
                            type=ProductFinancingUploadActionType.LOAN_DISBURSEMENT,
                        )
                    )
                    continue

                try:
                    disburse_time = datetime.strptime(row.get('disburse_time'), '%d/%m/%Y %H:%M:%S')
                except ValueError as e:
                    is_success_all = False
                    write.writerow(
                        write_row_result(
                            row,
                            is_passed,
                            e,
                            type=ProductFinancingUploadActionType.LOAN_DISBURSEMENT,
                        )
                    )
                    continue

                if disburse_time.timestamp() >= upload_time.timestamp():
                    is_success_all = False
                    write.writerow(
                        write_row_result(
                            row,
                            is_passed,
                            "loan disbursed time cannot be later than upload time",
                            type=ProductFinancingUploadActionType.LOAN_DISBURSEMENT,
                        )
                    )
                    continue

                loan_xid = int(row["loan_xid"])
                loan = loan_dict.get(loan_xid)
                if not loan:
                    notes = "loan not found"
                    is_success_all = False
                    write.writerow(
                        write_row_result(
                            row,
                            is_passed,
                            notes,
                            type=ProductFinancingUploadActionType.LOAN_DISBURSEMENT,
                        )
                    )
                    continue

                if loan.loan_status_id != LoanStatusCodes.FUND_DISBURSAL_ONGOING:
                    notes = "invalid loan status"
                    is_success_all = False
                    write.writerow(
                        write_row_result(
                            row,
                            is_passed,
                            notes,
                            type=ProductFinancingUploadActionType.LOAN_DISBURSEMENT,
                        )
                    )
                    continue

                account = account_dict.get(loan_xid)
                if not account:
                    notes = "account not found"
                    is_success_all = False
                    write.writerow(
                        write_row_result(
                            row,
                            is_passed,
                            notes,
                            type=ProductFinancingUploadActionType.LOAN_DISBURSEMENT,
                        )
                    )
                    continue

                if account.status_id != AccountConstant.STATUS_CODE.active:
                    notes = "invalid account status"
                    is_success_all = False
                    write.writerow(
                        write_row_result(
                            row,
                            is_passed,
                            notes,
                            type=ProductFinancingUploadActionType.LOAN_DISBURSEMENT,
                        )
                    )
                    continue

                partner_loan_request = loan.partnerloanrequest_set.select_related('partner').last()
                if not partner_loan_request:
                    notes = "partner_loan_request not found"
                    is_success_all = False
                    write.writerow(
                        write_row_result(
                            row,
                            is_passed,
                            notes,
                            type=ProductFinancingUploadActionType.LOAN_DISBURSEMENT,
                        )
                    )
                    continue

                if partner_loan_request.partner.name != PartnerConstant.GOSEL:
                    notes = "invalid partner"
                    is_success_all = False
                    write.writerow(
                        write_row_result(
                            row,
                            is_passed,
                            notes,
                            type=ProductFinancingUploadActionType.LOAN_DISBURSEMENT,
                        )
                    )
                    continue

                try:
                    with transaction.atomic():
                        payments = []
                        for index, payment in enumerate(loan.payments, 1):
                            due_date = disburse_time + relativedelta(months=index)
                            payment.due_date = due_date
                            payment.save(update_fields=['due_date'])
                            payments.append(payment)

                        create_or_update_account_payments(payments, loan.account)

                        update_loan_status_and_loan_history(
                            loan_id=loan.id,
                            new_status_code=LoanStatusCodes.CURRENT,
                            change_by_id=loan.account.id,
                            change_reason="upload loan disbursement",
                        )

                        loan.fund_transfer_ts = disburse_time
                        loan.save(update_fields=['fund_transfer_ts'])

                except Exception as e:
                    is_success_all = False
                    write.writerow(
                        write_row_result(
                            row,
                            is_passed,
                            str(e),
                            type=ProductFinancingUploadActionType.LOAN_DISBURSEMENT,
                        )
                    )
                    continue

                write.writerow(
                    write_row_result(
                        row,
                        True,
                        "Success",
                        type=ProductFinancingUploadActionType.LOAN_DISBURSEMENT,
                    )
                )

        upload_csv_data_to_oss(
            upload_async_state, file_path=file_path, product_name="product_financing"
        )

    return is_success_all


def product_financing_lender_approval_upload(upload_async_state: UploadAsyncState) -> bool:
    from juloserver.followthemoney.tasks import generate_summary_lender_loan_agreement

    upload_file = upload_async_state.file
    file_io = io.StringIO(upload_file.read().decode("utf-8"))
    reader = csv.DictReader(file_io, delimiter=",")
    is_success_all = True
    local_file_path = upload_async_state.file.path

    with TempDir(dir="/media") as tempdir:
        path_and_name, extension = os.path.splitext(local_file_path)
        file_name_elements = path_and_name.split("/")
        filename = file_name_elements[-1] + extension
        dir_path = tempdir.path
        file_path = os.path.join(dir_path, filename)
        loan_xid_str = "Loan XID"
        approved_loans = []
        approved_loan_ids = []
        rejected_loan_ids = []
        total_loan_amount = 0
        total_disbursement_amount = 0

        with open(file_path, "w", encoding="utf-8-sig") as f:
            write = csv.writer(f)
            write.writerow(PRODUCT_FINANCING_LENDER_APPROVAL_UPLOAD_HEADERS)

            loan_xids = []
            for row in reader:
                if row[loan_xid_str] and row[loan_xid_str].isnumeric():
                    loan_xids.append(row[loan_xid_str])
            loans = Loan.objects.select_related("account").filter(loan_xid__in=loan_xids)

            loan_dict = dict()
            account_dict = dict()
            for loan in loans:
                loan_dict[loan.loan_xid] = loan
                account_dict[loan.loan_xid] = loan.account

            file_io.seek(0)
            reader.__init__(file_io, delimiter=",")
            for row in reader:
                notes = ""

                if not row[loan_xid_str].isnumeric():
                    notes = "loan_xid must be a number"
                    is_success_all = False
                    write.writerow(
                        write_row_result(
                            row,
                            False,
                            notes,
                            type=ProductFinancingUploadActionType.LENDER_APPROVAL,
                        )
                    )
                    continue

                loan_xid = int(row[loan_xid_str])
                loan = loan_dict.get(loan_xid)
                if not loan:
                    notes = "loan tidak ditemukan"
                    is_success_all = False
                    write.writerow(
                        write_row_result(
                            row,
                            False,
                            notes,
                            type=ProductFinancingUploadActionType.LENDER_APPROVAL,
                        )
                    )
                    continue

                if loan.loan_status_id != LoanStatusCodes.LENDER_APPROVAL:
                    notes = "loan tidak ditemukan (invalid loan status)"
                    is_success_all = False
                    write.writerow(
                        write_row_result(
                            row,
                            False,
                            notes,
                            type=ProductFinancingUploadActionType.LENDER_APPROVAL,
                        )
                    )
                    continue

                account = account_dict.get(loan_xid)
                if not account:
                    notes = "user tidak ditemukan"
                    is_success_all = False
                    write.writerow(
                        write_row_result(
                            row,
                            False,
                            notes,
                            type=ProductFinancingUploadActionType.LENDER_APPROVAL,
                        )
                    )
                    continue

                if account.status_id != AccountConstant.STATUS_CODE.active:
                    notes = "user tidak ditemukan (invalid account status)"
                    is_success_all = False
                    write.writerow(
                        write_row_result(
                            row,
                            False,
                            notes,
                            type=ProductFinancingUploadActionType.LENDER_APPROVAL,
                        )
                    )
                    continue

                partner_loan_request = loan.partnerloanrequest_set.select_related('partner').last()
                if not partner_loan_request:
                    notes = "partner_loan_request not found"
                    is_success_all = False
                    write.writerow(
                        write_row_result(
                            row,
                            False,
                            notes,
                            type=ProductFinancingUploadActionType.LENDER_APPROVAL,
                        )
                    )
                    continue

                if partner_loan_request.partner.name != PartnerConstant.GOSEL:
                    notes = "invalid partner"
                    is_success_all = False
                    write.writerow(
                        write_row_result(
                            row,
                            False,
                            notes,
                            type=ProductFinancingUploadActionType.LENDER_APPROVAL,
                        )
                    )
                    continue

                try:
                    with transaction.atomic():
                        if row["Decision"] == "Approve":
                            update_loan_status_and_loan_history(
                                loan_id=loan.id,
                                new_status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING,
                                change_by_id=loan.account.id,
                                change_reason="upload lender approval",
                            )
                            total_loan_amount += loan.loan_amount
                            total_disbursement_amount += loan.loan_disbursement_amount
                            approved_loans.append(loan)
                            approved_loan_ids.append(loan.id)
                            loan.loan_status_id = LoanStatusCodes.FUND_DISBURSAL_ONGOING
                            loan_dict[loan.loan_xid] = loan

                        elif row["Decision"] == "Reject":
                            update_loan_status_and_loan_history(
                                loan_id=loan.id,
                                new_status_code=LoanStatusCodes.LENDER_REJECT,
                                change_by_id=loan.account.id,
                                change_reason="upload lender approval",
                            )

                            reassign_lender_julo_one(loan.id)
                            rejected_loan_ids.append(loan.id)
                            loan.loan_status_id = LoanStatusCodes.LENDER_REJECT
                            loan_dict[loan.loan_xid] = loan

                        else:
                            notes = "isi tidak sesuai format"
                            is_success_all = False
                            write.writerow(
                                write_row_result(
                                    row,
                                    False,
                                    notes,
                                    type=ProductFinancingUploadActionType.LENDER_APPROVAL,
                                )
                            )
                            continue

                except Exception as e:
                    is_success_all = False
                    write.writerow(
                        write_row_result(
                            row,
                            False,
                            str(e),
                            type=ProductFinancingUploadActionType.LENDER_APPROVAL,
                        )
                    )
                    continue

                write.writerow(
                    write_row_result(
                        row,
                        True,
                        "Success",
                        type=ProductFinancingUploadActionType.LENDER_APPROVAL,
                    )
                )

        if len(approved_loan_ids) > 0:
            partner = Partner.objects.filter(name=PartnerConstant.GOSEL).last()
            lender_bucket_xid = generate_lenderbucket_xid()
            lender_bucket = LenderBucket.objects.create(
                partner=partner,
                total_approved=len(approved_loan_ids),
                total_rejected=len(rejected_loan_ids),
                total_disbursement=total_disbursement_amount,
                total_loan_amount=total_loan_amount,
                loan_ids=approved_loan_ids,
                is_disbursed=False,
                is_active=True,
                action_time=timezone.now(),
                action_name='Disbursed',
                lender_bucket_xid=lender_bucket_xid,
            )

            # cache lender bucket xid for getting application past in lender dashboard
            redis_cache = RedisCacheLoanBucketXidPast()
            redis_cache.set_keys(approved_loan_ids, lender_bucket_xid)

            # generate summary lla
            assign_lenderbucket_xid_to_lendersignature_service(approved_loans, lender_bucket_xid)
            generate_summary_lender_loan_agreement.delay(lender_bucket.id)

        upload_csv_data_to_oss(
            upload_async_state, file_path=file_path, product_name="product_financing"
        )

    return is_success_all


def partnership_application_binary_pre_check(application: Application, flag_name: str) -> None:
    import juloserver.pin.services as pin_services
    from juloserver.julo.models import XidLookup

    credit_score = CreditScore.objects.filter(application_id=application.id).last()
    if not credit_score:
        raise JuloException('credit_score application_id={} not found'.format(application.id))

    if flag_name not in {
        PartnershipPreCheckFlag.PENDING_CREDIT_SCORE_GENERATION,
        PartnershipPreCheckFlag.ELIGIBLE_TO_BINARY_PRE_CHECK,
    }:
        raise JuloException(
            'application_id={}, flag_name={} not valid'.format(application.id, flag_name)
        )

    is_application_c_score = True if credit_score.score in ['C', '--'] else False
    is_not_pass_binary_check = AutoDataCheck.objects.filter(
        application_id=application.id,
        is_okay=False,
    ).exclude(data_to_check='inside_premium_area').exists()
    if is_application_c_score or is_not_pass_binary_check:
        logger.error(
            {
                'action': 'partnership_pre_check_application',
                'message': 'Is C Score application or not passed binary pre check',
                'application_status': str(application.status),
                'application': application.id,
                'application_flag_name': flag_name,
            }
        )

        application_id = application.id
        PartnershipApplicationFlag.objects.update_or_create(
            application_id=application_id,
            defaults={
                'name': PartnershipPreCheckFlag.NOT_PASSED_BINARY_PRE_CHECK,
            }
        )

        PartnershipApplicationFlagHistory.objects.create(
            old_application_id=application_id,
            application_id=application_id,
            status_old=PartnershipPreCheckFlag.ELIGIBLE_TO_BINARY_PRE_CHECK,
            status_new=PartnershipPreCheckFlag.NOT_PASSED_BINARY_PRE_CHECK,
        )

        process_application_status_change(
            application_id,
            ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
            change_reason="system_triggered"
        )

        customer = application.customer
        customer.can_reapply = True
        customer.save()

        # Check if customer already create pin
        is_pin_created = pin_services.does_user_have_pin(customer.user)

        if is_pin_created:
            filters = {
                'partner': application.partner,
                'name': PartnershipProductFlow.AGENT_ASSISTED,
                'configs__reject_c_score_agent_assisted_email__without_create_pin': True,
            }
        else:
            filters = {
                'partner': application.partner,
                'name': PartnershipProductFlow.AGENT_ASSISTED,
                'configs__reject_c_score_agent_assisted_email__with_create_pin': True,
            }

        partnership_flow_configs = PartnershipFlowFlag.objects.filter(
            **filters
        ).exists()

        logger.info(
            {
                "action": "send_email_106_c_score_for_agent_assisted_application",
                "application_id": application.id,
                "partnership_flow_configs": partnership_flow_configs,
                "configs": "reject_c_score_agent_assisted_email",
                "has_pin": is_pin_created
            }
        )

        if partnership_flow_configs:
            send_email_agent_assisted.delay(
                application_id=application.id, is_reject=True, is_x190=False
            )
    else:
        # Copied Application and create new application with status 100
        old_application_id = application.id

        PartnershipApplicationFlag.objects.update_or_create(
            application_id=old_application_id,
            defaults={
                'name': PartnershipPreCheckFlag.PASSED_BINARY_PRE_CHECK,
            },
        )

        # Expired old application to 106
        process_application_status_change(
            old_application_id,
            ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
            change_reason="system_triggered"
        )

        application.refresh_from_db()
        logger.info(
            {
                'action': 'partnership_pre_check_application',
                'message': 'Expired old application to 106',
                'application_status': str(application.status),
                'application': old_application_id,
                'application_flag_name': PartnershipPreCheckFlag.PASSED_BINARY_PRE_CHECK,
            }
        )

        # Re-create application with status 100
        application.id = None
        application.change_status(ApplicationStatusCodes.FORM_CREATED)
        application.web_version = '0.0.1'
        application.application_xid = XidLookup.get_new_xid()
        application.save()
        application.refresh_from_db()

        new_application_id = application.id
        PartnershipApplicationFlag.objects.update_or_create(
            application_id=new_application_id,
            defaults={
                'name': PartnershipPreCheckFlag.APPROVED,
            }
        )

        # Create 2 partnership application flag history
        # For old application and new application
        PartnershipApplicationFlagHistory.objects.create(
            old_application_id=old_application_id,
            application_id=old_application_id,
            status_old=PartnershipPreCheckFlag.ELIGIBLE_TO_BINARY_PRE_CHECK,
            status_new=PartnershipPreCheckFlag.PASSED_BINARY_PRE_CHECK,
        )
        PartnershipApplicationFlagHistory.objects.create(
            old_application_id=old_application_id,
            application_id=new_application_id,
            status_old=PartnershipPreCheckFlag.PASSED_BINARY_PRE_CHECK,
            status_new=PartnershipPreCheckFlag.APPROVED,
        )

        # Update link application <--> partnership_customer_data
        partnership_customer_data = PartnershipCustomerData.objects.filter(
            application_id=old_application_id
        ).last()

        if partnership_customer_data:
            partnership_customer_data.update_safely(
                application_id=application.id
            )

        store_application_to_experiment_table(application, 'ExperimentUwOverhaul')

        # replicate telco score from old application to new application if exists
        old_application = Application.objects.filter(id=old_application_id).last()
        telco_scoring = PartnershipTelcoScore(application=old_application)
        if telco_scoring.has_record():
            old_telco_scoring_result = telco_scoring.result

            # Create new telco result record for new application
            TelcoScoringResult.objects.create(
                application_id=new_application_id,
                score=old_telco_scoring_result.score,
                scoring_type=old_telco_scoring_result.scoring_type,
                type=old_telco_scoring_result.type,
                raw_response=old_telco_scoring_result.raw_response,
            )

            # Create application path tag for new application
            # Tag status set to TAG_STATUS_PASS_SWAP_IN because if telco scoring not passed
            # old application status will be x135 and will not enter this function
            # QOALA PARTNERSHIP - Leadgen Agent Assisted 03-12-2024
            from juloserver.application_flow.tasks import application_tag_tracking_task

            application_tag_tracking_task.delay(
                new_application_id,
                None,
                None,
                None,
                telco_scoring.TAG,
                telco_scoring.TAG_STATUS_PASS_SWAP_IN,
            )


def check_fdc_and_telco_empty(application: Application) -> bool:
    is_empty_fdc_result = False
    is_empty_telco_result = False

    # FDC check
    data_precheck_fdc = fdc_binary_check_agent_assisted(application.id)
    is_fdc_check_pass = data_precheck_fdc.get('status')
    fdc_inquiry_status = data_precheck_fdc.get('inquiry_status')
    if not is_fdc_check_pass and fdc_inquiry_status == 'not_found':
        is_empty_fdc_result = True

    # Telco scoring check
    telco = PartnershipTelcoScore(application=application)
    telco_scoring_result = telco.run_in_eligibility_check()
    if telco_scoring_result in PartnershipTelcoScoringStatus.not_found_result_list():
        is_empty_telco_result = True

    logger.info(
        {
            'action': 'check_fdc_and_telco_empty',
            'fdc_inquiry_status': fdc_inquiry_status,
            'telco_scoring_result': telco_scoring_result,
            'application': application.id,
        }
    )

    # Reject application if FDC and Telco have empty result
    if is_empty_fdc_result and is_empty_telco_result:
        return True

    return False
