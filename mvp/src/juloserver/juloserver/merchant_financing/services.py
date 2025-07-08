from __future__ import division, print_function

import base64
import csv
import io
import logging
import math
import os
import random
import string
import tempfile
from builtins import object, range, str
from collections import namedtuple
from datetime import (
    datetime,
    timedelta,
)
from typing import Dict, Optional, Union
from datetime import date
import requests
from babel.dates import format_date
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.auth.models import User
from django.core.files import File
from django.db import (
    connection,
    transaction,
)
from django.template.loader import render_to_string
from django.utils import timezone
from past.utils import old_div
from PIL import Image as Imagealias

from juloserver.account.constants import AccountConstant
from juloserver.account.models import (
    Account,
    AccountLimit,
    AccountLookup,
    AccountProperty,
    AccountTransaction,
)
from juloserver.account.services.credit_limit import (
    get_is_proven,
    get_proven_threshold,
    get_salaried,
    get_voice_recording,
    is_inside_premium_area,
    store_account_property_history,
    update_available_limit,
)
from juloserver.account.utils import round_down_nearest
from juloserver.account_payment.models import AccountPayment
from juloserver.api_token.authentication import make_never_expiry_token
from juloserver.apiv1.data.loan_purposes import (
    get_loan_purpose_dropdown_by_product_line,
)
from juloserver.customer_module.constants import BankAccountCategoryConst
from juloserver.customer_module.models import BankAccountDestination, CustomerLimit
from juloserver.disbursement.constants import (
    NameBankValidationStatus,
    NameBankValidationVendors,
    DisbursementStatus,
)
from juloserver.disbursement.exceptions import XfersApiError
from juloserver.disbursement.models import (
    BankNameValidationLog,
    NameBankValidation,
    Disbursement,
    Disbursement2History,
)
from juloserver.disbursement.services.xfers import XfersService
from juloserver.fdc.files import TempDir
from juloserver.julo.banks import BankCodes, BankManager
from juloserver.julo.constants import (
    EmailTemplateConst,
    FeatureNameConst,
    WorkflowConst,
)
from juloserver.julo.exceptions import JuloException
from juloserver.julo.formulas import round_rupiah
from juloserver.julo.models import (
    AffordabilityHistory,
    Application,
    Bank,
    Customer,
    Document,
    EmailHistory,
    FDCInquiry,
    FeatureSetting,
    GlobalPaymentMethod,
    Image,
    Loan,
    MobileFeatureSetting,
    OtpRequest,
    Partner,
    PartnerBankAccount,
    Payment,
    PaymentEvent,
    PaymentMethod,
    PaymentMethodLookup,
    StatusLookup,
    UploadAsyncState,
    Workflow,
)
from juloserver.julo.partners import PartnerConstant
from juloserver.julo.payment_methods import (
    PaymentMethodCodes,
    mf_excluded_payment_method_codes,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services import (
    process_application_status_change,
    trigger_name_in_bank_validation,
    update_customer_data,
)
from juloserver.julo.services2 import encrypt
from juloserver.julo.services2.payment_method import (
    is_global_payment_method_used,
    get_application_primary_phone,
)
from juloserver.julo.statuses import (
    ApplicationStatusCodes,
    LoanStatusCodes,
    PaymentStatusCodes,
)
from juloserver.julo.tasks import upload_document
from juloserver.julo.utils import (
    check_email,
    display_rupiah,
    execute_after_transaction_safely,
    upload_file_to_oss,
    format_mobile_phone,
)
from juloserver.julocore.python2.utils import py2round
from juloserver.loan.constants import FDCUpdateTypes, LoanJuloOneConstant
from juloserver.loan.exceptions import AccountLimitExceededException, LenderException
from juloserver.loan.services.adjusted_loan_matrix import get_daily_max_fee
from juloserver.loan.services.loan_related import (
    check_eligible_and_out_date_other_platforms,
    get_loan_amount_by_transaction_type,
    is_apply_check_other_active_platforms_using_fdc,
    is_eligible_other_active_platforms,
    update_loan_status_and_loan_history,
)
from juloserver.loan.tasks.lender_related import loan_lender_approval_process_task
from juloserver.merchant_financing.clients import AxiataClient
from juloserver.merchant_financing.constants import (
    MF_DISBURSEMENT_RABANDO_HEADERS,
    MF_DISBURSEMENT_HEADERS,
    MF_REGISTER_HEADERS,
    AxiataReportType,
    BulkDisbursementStatus,
    LoanDurationUnit,
    LoanDurationUnitDays,
    SPHPType, PARTNER_MF_DISBURSEMENT_UPLOAD_MAPPING_FIELDS, MF_CSV_UPLOAD_ADJUST_LIMIT_HEADERS,
)
from juloserver.merchant_financing.exceptions import AxiataLogicException
from juloserver.merchant_financing.models import (
    ApplicationSubmission,
    BulkDisbursementRequest,
    BulkDisbursementSchedule,
    Merchant,
    MerchantHistoricalTransactionTask,
    PartnerDisbursementRequest,
    SentCreditInformation,
    SentDisburseContract,
    SentUpdateRepaymentInfo,
)
from juloserver.merchant_financing.serializers import (
    ApplicationPartnerUpdateSerializer,
    CustomerSerializer,
    MerchantFinancingDistburseSerializer,
    MerchantFinancingUploadRegisterSerializer,
    MerchantSerializer, MerchantFinancingCSVUploadAdjustLimitSerializer,
)
from juloserver.merchant_financing.utils import (
    generate_loan_payment_merchant_financing,
    get_partner_product_line,
    is_account_forbidden_to_create_loan,
    is_loan_duration_valid,
    is_loan_more_than_one,
    merchant_financing_register_format_data,
    mf_disbursement_format_data,
    validate_merchant_financing_max_interest_with_ojk_rule,
    merchant_financing_adjust_limit_format_data,
    validate_kin_name, validate_kin_mobile_phone,
)
from juloserver.partnership.clients import get_julo_sentry_client
from juloserver.partnership.constants import (
    ErrorMessageConst,
    PartnershipFeatureNameConst,
    PartnershipTypeConstant,
    PartnershipFlag,
    PartnershipDisbursementType,
)
from juloserver.partnership.models import (
    MerchantHistoricalTransaction,
    PartnershipConfig,
    PartnershipFeatureSetting,
    PartnershipFlowFlag,
    PartnershipCustomerData,
    PartnershipUserOTPAction,
)
from juloserver.partnership.serializers import MerchantHistoricalTransactionSerializer
from juloserver.partnership.services.services import (
    get_product_lookup_by_merchant,
    process_add_partner_loan_request,
    update_customer_pin_used_status,
)
from juloserver.partnership.utils import generate_pii_filter_query_partnership
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.payment_point.models import TransactionMethod
from juloserver.portal.object.bulk_upload.constants import (
    MF_DISBURSEMENT_KEY,
    MF_REGISTER_KEY,
    MerchantFinancingCSVUploadPartner, MF_ADJUST_LIMIT_KEY,
)
from juloserver.portal.object.bulk_upload.services import (
    disburse_mf_partner_customer,
    run_merchant_financing_upload_csv, update_mf_customer_adjust_limit,
)
from juloserver.portal.object.bulk_upload.utils import merchant_financing_format_data
from juloserver.sdk.models import AxiataCustomerData
from juloserver.standardized_api_response.utils import (
    general_error_response,
    success_response,
)
from juloserver.urlshortener.services import shorten_url
from juloserver.followthemoney.utils import generate_lenderbucket_xid
from juloserver.followthemoney.models import LenderBucket
from juloserver.followthemoney.tasks import (
    assign_lenderbucket_xid_to_lendersignature,
    generate_summary_lender_loan_agreement,
)
from juloserver.followthemoney.services import RedisCacheLoanBucketXidPast
from juloserver.payment_gateway.constants import (
    TransferProcessStatus,
)
from juloserver.loan.services.lender_related import (
    julo_one_loan_disbursement_failed,
    julo_one_loan_disbursement_success,
)
from juloserver.partnership.tasks import partnership_trigger_process_validate_bank

logger = logging.getLogger(__name__)
julo_sentry_client = get_julo_sentry_client()


class PartnerAuthenticationService(object):
    @staticmethod
    def authenticate(username, password):
        user = User.objects.filter(username=username).first()
        if not user:
            raise AxiataLogicException("Username tidak terdaftar")
        pii_filter_dict = generate_pii_filter_query_partnership(
            Partner, {'name': PartnerConstant.AXIATA_PARTNER}
        )
        partner = Partner.objects.filter(user=user, **pii_filter_dict).last()
        if not partner:
            raise AxiataLogicException("Kredensial yang salah")

        is_password_correct = user.check_password(password)

        if not is_password_correct:
            raise AxiataLogicException("Password salah")

        response = {
            "token": user.auth_expiry_token.key
        }

        return response


class PartnerApplicationService(object):
    @staticmethod
    def check_concurrency(account):
        _filter = dict(
            loan_status__in=(
                LoanStatusCodes.CANCELLED_BY_CUSTOMER,
                LoanStatusCodes.SPHP_EXPIRED,
                LoanStatusCodes.FUND_DISBURSAL_FAILED,
                LoanStatusCodes.PAID_OFF,
            )
        )
        loans = account.loan_set.exclude(**_filter)
        if loans.count() >= 2:
            return False
        return True

    @staticmethod
    def submit(application_data):
        from juloserver.merchant_financing.tasks import (
            task_process_partner_application_async,
        )

        concurreny = True
        status = ""

        axiata_customer_data_obj = AxiataCustomerData.objects \
            .filter(partner_application_id=application_data['partner_application_id']).last()
        if axiata_customer_data_obj:
            application_submission = ApplicationSubmission.objects. \
                filter(axiata_customer_data=axiata_customer_data_obj).last()
            if axiata_customer_data_obj.application:
                pass
                # concurreny = PartnerApplicationService.check_concurrency(account)
        if not concurreny:
            response_data = {
                "partner_application_id": application_data['partner_application_id'],
                "status": "Maximum Concurrent loans are under processing",
                "application_xid": application_submission.loan_xid
            }
            return response_data

        axiata_customer_data = application_data
        axiata_customer_data['account_number'] = axiata_customer_data.pop('partner_merchant_code')
        axiata_customer_data['brand_name'] = axiata_customer_data.pop('shop_name')
        axiata_customer_data['ktp'] = axiata_customer_data.pop('nik')
        axiata_customer_data['interest_rate'] = axiata_customer_data.pop('interest')
        axiata_customer_data['shops_number'] = axiata_customer_data.pop('shop_number')
        axiata_customer_data['distributor'] = axiata_customer_data.pop('partner_distributor_id')
        axiata_customer_data['origination_fee'] = axiata_customer_data.pop('provision')
        axiata_customer_data['fullname'] = axiata_customer_data.pop('owner_name')
        axiata_customer_data['address_street_num'] = axiata_customer_data.pop('address')
        axiata_customer_data['monthly_installment'] = axiata_customer_data.\
            pop('monthly_instalment_amount')
        if not axiata_customer_data['date_of_establishment']:
            axiata_customer_data.pop('date_of_establishment')

        with transaction.atomic():
            # save data to axiata_customer_data
            if axiata_customer_data_obj:
                if axiata_customer_data_obj.application:
                    response_data = {
                        "partner_application_id": application_data['partner_application_id'],
                        "status": "Duplicate submission",
                        "application_xid": ""
                    }
                    return response_data
                else:
                    status = "Success"
                    axiata_customer_data_obj.update_safely(reject_reason=None, **axiata_customer_data)
            else:
                axiata_customer_data_obj = AxiataCustomerData.objects.create(**axiata_customer_data)
                status = "Success"
                # save to application_submission
                ApplicationSubmission.objects.create(
                    axiata_customer_data=axiata_customer_data_obj,
                    application_submission_response=200,
                    status=status

                )

            # Application Approval/Rejection Processing
            task_process_partner_application_async.delay(application_data, axiata_customer_data_obj)

        logger.info({
            'message': "Merchant Financing: Application form submission",
            'data': application_data
        })

        response_data = {
            "partner_application_id": application_data['partner_application_id'],
            "status": status
        }

        return response_data

    @staticmethod
    def process_partner_application_async(application_data, axiata_customer_data):
        application = None
        pii_filter_dict = generate_pii_filter_query_partnership(
            Partner, {'name': PartnerConstant.AXIATA_PARTNER}
        )
        partner = Partner.objects.filter(**pii_filter_dict).last()
        if not partner:
            logger.error({
                'message': "process_partner_application: partner not found",
                'axiata_customer_data': axiata_customer_data.id
            })
            raise AxiataLogicException("process_partner_application:  Partner not found")

        # Rejection checks
        is_reject_application, rejection_reason = PartnerApplicationService.\
            application_rejection_checks(axiata_customer_data, partner)
        if is_reject_application:
            axiata_customer_data.update_safely(reject_reason=rejection_reason)
        else:
            # approve and create application flow
            application, loan = PartnerApplicationService.\
                approve_application_flow(application_data, axiata_customer_data, partner)

        # callback to axiata for application status update
        PartnerApplicationService.axiata_callback_send_update_credit_information(
            axiata_customer_data,
            is_reject_application,
            rejection_reason,
            application)

    @staticmethod
    def application_rejection_checks(axiata_customer_data, partner):
        ktp = axiata_customer_data.ktp
        is_reject_application = False
        rejection_reason = None

        customer = Customer.objects.get_or_none(nik=ktp)
        if not customer:
            user = User.objects.filter(username=ktp).first()
            if user:
                customer_exist = Customer.objects.filter(user=user).first()
                if customer_exist:
                    is_reject_application = True
                    rejection_reason = "NIK already exists with different user"
                    return is_reject_application, rejection_reason
        else:
            if customer.email != axiata_customer_data.email:
                is_reject_application = True
                rejection_reason = "NIK already exists with different email address"
                return is_reject_application, rejection_reason

        customer_with_different_nik = Customer.objects.exclude(nik=ktp).\
            filter(email=axiata_customer_data.email).count()
        if customer_with_different_nik > 0:
            is_reject_application = True
            rejection_reason = "Email already exists with different NIK"
            return is_reject_application, rejection_reason

        if customer:
            multiple_loan_axiata = FeatureSetting.objects.get_or_none(
                is_active=True,
                feature_name=FeatureNameConst.AXIATA_MULTIPLE_LOAN)

            if multiple_loan_axiata and axiata_customer_data:
                # check if data axiata duplicate
                axiata_data_exist = AxiataCustomerData.objects\
                    .filter(ktp=ktp,
                            loan_amount=axiata_customer_data.loan_amount,
                            account_number=axiata_customer_data.account_number,
                            partner_application_id=axiata_customer_data.partner_application_id,
                            application__isnull=False).first()

                if axiata_data_exist:
                    is_reject_application = True
                    rejection_reason = "Duplicate data"
                    return is_reject_application, rejection_reason


        return is_reject_application, rejection_reason

    @staticmethod
    def approve_application_flow(application_data, axiata_customer_data, partner):
        application = None
        ktp = axiata_customer_data.ktp
        customer = Customer.objects.get_or_none(nik=ktp)
        product_line, product_lookup = get_partner_product_line(
            axiata_customer_data.interest_rate,
            axiata_customer_data.origination_fee,
            axiata_customer_data.admin_fee
        )

        with transaction.atomic():
            if not customer:
                user = User.objects.filter(username=ktp).first()
                if not user:
                    # generate random password
                    password = ''.join(random.choice(
                        string.ascii_lowercase + string.digits) for _ in range(8))
                    user = User(username=ktp)
                    user.set_password(password)
                    user.save()
                    make_never_expiry_token(user)

                customer_data = CustomerSerializer(application_data).data
                customer_data['user'] = user
                customer_data['nik'] = ktp
                customer_data['phone'] = application_data.get('phone_number', None)
                customer_data['can_notify'] = False
                customer = Customer.objects.create(**customer_data)

            # create merchant if not exist
            merchant = Merchant.objects.filter(customer=customer).last()
            if not merchant:
                merchant_data = MerchantSerializer(application_data).data
                merchant = Merchant.objects.create(**merchant_data)
                merchant.customer = customer
                merchant.save()


            # check if application already exist
            if customer.account:
                application = customer.account.application_set.last()
            # application = axiata_customer_data.application
            if not application or not application.is_axiata_flow():
                loan_purpose = get_loan_purpose_dropdown_by_product_line(
                    ProductLineCodes.AXIATA1)

                application_serializer = ApplicationPartnerUpdateSerializer(application_data)
                insert_application_data = application_serializer.data
                insert_application_data['customer'] = customer
                insert_application_data['partner'] = partner
                insert_application_data['application_number'] = 1
                insert_application_data['loan_amount_request'] = application_data['loan_amount']
                insert_application_data['loan_duration_request'] = \
                    application_data['loan_duration']
                insert_application_data['loan_purpose'] = loan_purpose['results'][0]
                insert_application_data['mobile_phone_1'] = application_data['phone_number']

                # get axiata bank data
                axiata_bank_data = PartnerBankAccount.objects.\
                    filter(distributor_id=application_data['distributor'],
                           partner=partner).last()
                if axiata_bank_data:
                    application_data['bank_name'] = axiata_bank_data.bank_name
                    application_data['bank_account_number'] = \
                        axiata_bank_data.bank_account_number
                    application_data['name_in_bank'] = axiata_bank_data.name_in_bank

                application = Application.objects.create(**insert_application_data)
                update_customer_data(application)

                workflow = Workflow.objects.get(name=WorkflowConst.MERCHANT_FINANCING_WORKFLOW)
                # assign more data to application
                application.workflow = workflow
                application.product_line = product_line
                application.change_status(ApplicationStatusCodes.NOT_YET_CREATED)
                application.save()

            if application.application_status_id != ApplicationStatusCodes.LOC_APPROVED:
                process_application_status_change(
                    application.id, ApplicationStatusCodes.LOC_APPROVED,
                    change_reason='Axiata Approved by script')

            if not axiata_customer_data.application:
                # assign application to axiata_data
                axiata_customer_data.update_safely(application=application)

            if application.is_axiata_flow():
                # Update or save account related information
                PartnerApplicationService.store_account_related_information(
                    application,
                    axiata_customer_data.loan_amount)

            axiata_customer_data.refresh_from_db()
            application.refresh_from_db()

            # Create Loan and payments
            loan = PartnerApplicationService.generate_loan(application, axiata_customer_data)

            if loan:
                axiata_customer_data.update_safely(loan_xid=loan.loan_xid)
                loan.product = product_lookup
                loan.save()
                # lender approval
                result_lender_approval = loan_lender_approval_process_task(loan.id)
                if result_lender_approval is False:
                    raise LenderException(
                        {
                            'action': 'approve_application_flow',
                            'message': 'no lender available for this loan!!',
                            'loan_id': loan.id,
                        }
                    )

                # Upload ktp and selfie image
                PartnerApplicationService.process_image(axiata_customer_data)

            return application, loan

    @staticmethod
    def store_account_related_information(application, max_limit):
        last_affordability = AffordabilityHistory.objects.filter(
            application=application
        ).last()

        account_lookup = AccountLookup.objects.filter(
            workflow=application.workflow
        ).last()
        account = Account.objects.filter(customer=application.customer,
                                         account_lookup=account_lookup
                                         ).last()
        if not account:
            account = Account.objects.create(
                customer=application.customer,
                status_id=AccountConstant.STATUS_CODE.active,
                account_lookup=account_lookup,
                cycle_day=0
            )
        logger.info({
            'message': "Merchant Financing: store_account_related_information accountid=%s " % account.id,
            'max_limit': max_limit
        })

        account_limit = AccountLimit.objects.filter(account=account).last()
        if account_limit:
            account_limit.available_limit = 0
            account_limit.max_limit += max_limit
            account_limit.set_limit += max_limit
            account_limit.used_limit += max_limit
            account_limit.latest_affordability_history = last_affordability
            account_limit.save()
        else:
            account_limit = AccountLimit.objects.create(
                account=account,
                max_limit=max_limit,
                set_limit=max_limit,
                used_limit=max_limit,
                available_limit=0,
                latest_affordability_history=last_affordability
            )

        customer_limit = CustomerLimit.objects.filter(customer=application.customer).last()
        if not customer_limit:
            CustomerLimit.objects.create(
                customer=application.customer,
                max_limit=account_limit.max_limit
            )
        else:
            customer_limit.update_safely(max_limit=account_limit.max_limit)

        application.update_safely(account=account)

    @staticmethod
    def get_first_payment_date(loan_duration_days):
        today_date = timezone.localtime(timezone.now()).date()
        first_payment_date = today_date + relativedelta(days=loan_duration_days)

        return first_payment_date

    @staticmethod
    def validate_image_from_base64(base64_image_data, partner_application_id):
        if base64_image_data.find("jpeg;base64") == -1:
            logger.info({
                'message': "Merchant Financing Image upload: partner_application_id id=%s invalid data" % partner_application_id
            })
            return False
        return True

    @staticmethod
    def process_image(axiata_customer_data):
        from juloserver.merchant_financing.tasks import (
            task_upload_image_merchant_financing_async,
        )

        if not axiata_customer_data:
            return
        image_data = dict(
            selfie=axiata_customer_data.selfie_image,
            ktp_self=axiata_customer_data.ktp_image,
        )

        if image_data:
            for image_key, image_value in list(image_data.items()):
                base64String = image_value
                if not PartnerApplicationService.validate_image_from_base64(
                        base64String,
                        axiata_customer_data.partner_application_id):
                    continue

                image = Image()
                image.image_type = image_key
                image.image_source = axiata_customer_data.id
                image.image_status = -1
                image.save()

                base64String = base64String.split("data:image/jpeg;base64,")
                filename = "merchant_financing_{}_{}_upload.jpg".format(image_key, axiata_customer_data.id)
                internal_path = os.path.join(tempfile.gettempdir(), filename)

                with open(internal_path, 'wb') as file:
                    file.write(base64.standard_b64decode(base64String[len(base64String) - 1]))

                image.image.save(filename, File(open(internal_path, 'rb')))

                # remove temp file
                if os.path.isfile(internal_path):
                    logger.info({
                        'action': 'deleting_local_file generate_application_async',
                        'image_path': internal_path,
                        'axiata_customer_data_id': image.image_source,
                        'image_type': image.image_type
                    })
                    os.remove(internal_path)
                execute_after_transaction_safely(
                    lambda im_id=image.id: task_upload_image_merchant_financing_async.delay(im_id) #noqa
                )


    @staticmethod
    def upload_image_merchant_financing_async(image_id, thumbnail=True):
        image = Image.objects.get_or_none(pk=image_id)
        if not image:
            logger.error({"image": image_id, "status": "not_found"})

        axiata_customer_data = AxiataCustomerData.objects. \
                filter(pk=image.image_source).last()
        if not axiata_customer_data:
            logger.info({
                'message': "Image upload: axiata_customer_data id=%s not found" % image.image_source
            })

        application_submission = ApplicationSubmission.objects. \
            filter(axiata_customer_data=axiata_customer_data).last()
        if application_submission:
            loan = Loan.objects.get_or_none(loan_xid=application_submission.loan_xid)
        if not loan:
            logger.info({'message':'Image upload: Loan not found'})
        # upload image to s3 and save s3url to field
        customer_id = loan.customer.id
        image_path = image.image.path

        image_remote_filepath = PartnerApplicationService.construct_remote_filepath(customer_id, image)
        upload_file_to_oss(settings.OSS_MEDIA_BUCKET, image.image.path, image_remote_filepath)
        image.url = image_remote_filepath
        image.image_status = 0
        image.save()

        logger.info({
            'status': 'successfull upload image to s3',
            'image_remote_filepath': image_remote_filepath,
            'loan_id': image.image_source,
            'image_type': image.image_type
        })

        # mark all other images with same type as 'deleted'
        images = list(
            Image.objects.exclude(id=image.id)
                .exclude(image_status=Image.DELETED)
                .filter(image_source=image.image_source,
                        image_type=image.image_type)
        )

        for img in images:
            logger.info({
                'action': 'marking_deleted',
                'image': img.id
            })
            img.image_status = Image.DELETED
            img.save()

        if image.image_ext != '.pdf' and thumbnail:

            # create thumbnail
            im = Imagealias.open(image.image.path)
            size = (150, 150)
            im.thumbnail(size, Imagealias.ANTIALIAS)
            image_thumbnail_path = image.thumbnail_path
            im.save(image_thumbnail_path)

            # upload thumbnail to s3
            thumbnail_dest_name = PartnerApplicationService.construct_remote_filepath(customer_id, image, suffix='thumbnail')
            upload_file_to_oss(
                settings.OSS_MEDIA_BUCKET, image_thumbnail_path, thumbnail_dest_name)
            image.thumbnail_url = thumbnail_dest_name
            image.save()

            logger.info({
                'status': 'successfull upload thumbnail to s3',
                'thumbnail_dest_name': thumbnail_dest_name,
                'loan_id': image.image_source,
                'image_type': image.image_type
            })

            # delete thumbnail from local disk
            if os.path.isfile(image_thumbnail_path):
                logger.info({
                    'action': 'deleting_thumbnail_local_file',
                    'image_thumbnail_path': image_thumbnail_path,
                    'loan_id': image.image_source,
                    'image_type': image.image_type
                })
                os.remove(image_thumbnail_path)

        # delete image
        if os.path.isfile(image_path):
            logger.info({
                'action': 'deleting_local_file',
                'image_path': image_path,
                'loan_id': image.image_source,
                'image_type': image.image_type
            })
            image.image.delete()

    @staticmethod
    def construct_remote_filepath(customer_id, image, suffix=None):
        """Using some input constructing folder structure in cloud storage"""
        folder_type = 'loan_'

        subfolder = folder_type + str(image.image_source)
        _, file_extension = os.path.splitext(image.image.name)
        if suffix:
            filename = "%s_%s_%s%s" % (
                image.image_type, str(image.id), suffix, file_extension)
        else:
            filename = "%s_%s%s" % (
                image.image_type, str(image.id), file_extension)

        dest_name = '/'.join(['cust_' + str(customer_id), subfolder, filename])
        logger.info({'remote_filepath': dest_name})
        return dest_name

    @staticmethod
    def get_loan_duration_days(axiata_customer_data):
        loan_duration_unit = axiata_customer_data.loan_duration_unit.lower()
        if loan_duration_unit == LoanDurationUnit.WEEKLY:
            loan_duration_days  = LoanDurationUnitDays.WEEKLY
        elif loan_duration_unit == LoanDurationUnit.BI_WEEKLY:
            loan_duration_days = LoanDurationUnitDays.BI_WEEKLY
        else:
            loan_duration_days = LoanDurationUnitDays.MONTHLY

        return float(loan_duration_days)

    @staticmethod
    def generate_loan(application, axiata_customer_data):
        interest_rate = float(axiata_customer_data.interest_rate) / float(100)
        loan_duration_days = PartnerApplicationService.get_loan_duration_days(axiata_customer_data)
        first_payment_date = PartnerApplicationService.get_first_payment_date(loan_duration_days)


        principal_rest, interest_rest, installment_rest = PartnerApplicationService.\
            compute_payment_installment(axiata_customer_data.loan_amount,
                                        axiata_customer_data.loan_duration,
                                        interest_rate)

        loan_disbursement_amount = axiata_customer_data.loan_amount - py2round(
                (axiata_customer_data.origination_fee / 100.0) * float(axiata_customer_data.loan_amount))\
                                   - float(axiata_customer_data.admin_fee)

        loan = Loan.objects.create(
            customer=application.customer,
            loan_status=StatusLookup.objects.get(status_code=LoanStatusCodes.INACTIVE),
            loan_amount=axiata_customer_data.loan_amount,
            loan_duration=axiata_customer_data.loan_duration,
            first_installment_amount=installment_rest,
            installment_amount=installment_rest,
            account=application.account,
            loan_purpose=application.loan_purpose,
            loan_disbursement_amount=loan_disbursement_amount
        )


        # update application_submission
        application_submission = ApplicationSubmission.objects.\
            filter(axiata_customer_data=axiata_customer_data).last()
        application_submission.loan_xid = loan.loan_xid
        application_submission.application_xid = application.application_xid
        application_submission.save()

        # set payment method for Loan
        customer_has_vas = PaymentMethod.objects.active_payment_method(application.customer)
        if customer_has_vas:
            primary_payment_method = customer_has_vas.filter(is_primary=True).last()
            if primary_payment_method:
                loan.julo_bank_name = primary_payment_method.payment_method_name
                loan.julo_bank_account_number = primary_payment_method.virtual_account
                loan.save()

        payment_status = StatusLookup.objects.get(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE)
        principal_deviation = loan.loan_amount - (principal_rest +
                                                  ((loan.loan_duration - 1) * principal_rest)
                                                  )
        for payment_number in range(loan.loan_duration):
            if payment_number == 0:
                due_date = first_payment_date
                principal, interest, installment = \
                    principal_rest, interest_rest, installment_rest
            else:
                due_date = first_payment_date + (int(loan_duration_days) * relativedelta(days=payment_number))
                principal, interest, installment = principal_rest, interest_rest, installment_rest
                if (payment_number + 1) == loan.loan_duration:
                    principal += principal_deviation
                    interest -= principal_deviation

            payment = Payment.objects.create(
                loan=loan,
                payment_status=payment_status,
                payment_number=payment_number + 1,
                due_date=due_date,
                due_amount=installment,
                installment_principal=principal,
                installment_interest=interest)

            logger.info({
                'action': 'generate_payment_axiata',
                'application': application.id,
                'loan': loan,
                'payment_number': payment_number,
                'payment_amount': payment.due_amount,
                'due_date': due_date,
                'payment_status': payment.payment_status.status,
                'status': 'payment_created'
            })

        return loan

    @staticmethod
    def update_payment_due_date(loan, axiata_customer_data):
        new_due_date = axiata_customer_data.first_payment_date
        loan_duration_days = PartnerApplicationService.get_loan_duration_days(axiata_customer_data)
        payments = list(
            Payment.objects.by_loan(loan).not_paid().order_by('payment_number')
        )
        for payment in payments:
            payment.update_safely(due_date=new_due_date)
            new_due_date = new_due_date + relativedelta(days=int(loan_duration_days))

        loan.cycle_day = axiata_customer_data.first_payment_date.day
        loan.save()

    @staticmethod
    def compute_payment_installment(loan_amount, loan_duration, interest_rate_perc):
        """
        Computes installment and interest for payments after first installment
        """
        principal = round(old_div(loan_amount, loan_duration))

        installment_amount = int((float(loan_amount) / float(loan_duration)) +
                                 math.ceil(float(loan_duration) * interest_rate_perc * float(loan_amount)))
        derived_interest = installment_amount - principal

        return principal, derived_interest, installment_amount

    @staticmethod
    def compute_first_payment_installment(loan_amount,
                                          loan_duration_days,
                                          loan_duration,
                                          interest_rate,
                                          start_date,
                                          end_date):
        delta_days = (end_date - start_date).days
        principal = int(math.floor(float(loan_amount) / float(loan_duration)))
        basic_interest = float(loan_amount) * interest_rate
        adjusted_interest = int(math.floor((float(delta_days) / loan_duration_days) * basic_interest))

        installment_amount = round_rupiah(principal + adjusted_interest)
        derived_adjusted_interest = installment_amount - principal

        return principal, derived_adjusted_interest, installment_amount

    @staticmethod
    def axiata_callback_send_update_credit_information(
            axiata_customer_data,
            is_reject_application,
            rejection_reason,
            application=None):
        sending_status = "Failed"
        application_submission = ApplicationSubmission.objects. \
            filter(axiata_customer_data=axiata_customer_data).last()
        application_xid = None
        loan_xid = None

        if is_reject_application:
            decision = "Rejected"
            # application will not be created
        else:
            decision = "Approved"
            loan_xid = application_submission.loan_xid
            application_xid = application.application_xid
            rejection_reason = ""
        # save to SentCreditInformation
        sent_credit_information = SentCreditInformation.objects.create(
            partner_application_id=axiata_customer_data.partner_application_id,
            application_xid=application_xid,
            loan_xid=loan_xid,
            sending_status=sending_status,
            reject_reason=rejection_reason,
            decision=decision
        )
        logger.info({
            "action": "axiata_callback_send_update_credit_information",
            "data": sent_credit_information.id})
        try:
            client = AxiataClient()
            data = {
                "partner_application_id": str(axiata_customer_data.partner_application_id),
                "application_xid": loan_xid,
                "decision": decision,
                "reject_reason": str(rejection_reason)
            }
            axiata_response = client.send_update_credit_information(data)
            if axiata_response['code'] == 200:
                sending_status = "Success"
                sent_credit_information.update_safely(sending_status=sending_status)
        except Exception as e:
            logger.error({"action": "axiata_callback_send_update_credit_information", "errors": e})
            raise AxiataLogicException(e)

    @staticmethod
    def get_status(partner_application_id, loan_xid):
        axiata_customer_data = AxiataCustomerData.objects. \
            filter(partner_application_id=partner_application_id).last()

        status = ""
        if not axiata_customer_data:
            status = "Application not found"
        elif loan_xid:
            loan = Loan.objects.get_or_none(loan_xid=loan_xid)
            if not loan:
                status = 'Loan not found'
            elif loan.loan_status_id == LoanStatusCodes.INACTIVE:
                status = "Application Approved"
            elif loan.loan_status_id == LoanStatusCodes.FUND_DISBURSAL_ONGOING:
                status = "Disbursement in progress"
            elif loan.loan_status_id == LoanStatusCodes.LENDER_APPROVAL:
                status = "Loan approved"
            elif loan.loan_status_id == LoanStatusCodes.CURRENT:
                status = "Disbursement successful"
            else:
                status = loan.loan_status.status
        else:
            status = "Application Rejected"

        response = {
            "status": status,
            "partner_application_id": str(partner_application_id)
        }

        return response


class PartnerDisbursementService(object):
    @staticmethod
    def disburse(disburse_data):
        from juloserver.merchant_financing.tasks import (
            task_process_disbursement_request_async,
        )

        response_code = 400
        status = ""
        partner_application_id = disburse_data['partner_application_id']
        loan_xid = disburse_data['application_xid']
        first_payment_date = disburse_data['first_payment_date']

        check_existing = AxiataCustomerData.objects.filter(
            partner_application_id=partner_application_id,
            loan_xid=loan_xid).exists()

        if not check_existing:
            raise ValueError('Customer not found')

        partner_disbursement_request = PartnerDisbursementRequest.objects.filter(
            partner_application_id=partner_application_id,
            loan_xid=loan_xid).last()
        if partner_disbursement_request:
            raise ValueError('Duplicate request')
            """
            response = {
                "application_xid": loan_xid,
                "partner_application_id": str(partner_application_id),
                "status": "Duplicate request",
                "response": response_code
            }
            """
            return response

        try:
            with transaction.atomic():
                loan = Loan.objects.get_or_none(loan_xid=loan_xid)
                axiata_customer_data = AxiataCustomerData.objects. \
                    filter(partner_application_id=partner_application_id,application__isnull=False).last()
                if not axiata_customer_data:
                    response = {
                        "application_xid": loan_xid,  # actually loan_xid
                        "partner_application_id": str(partner_application_id),
                        "status": "Invalid request",
                        "response": response_code
                    }
                    return response

                if not loan:
                    response = {
                        "application_xid": loan_xid,  # actually loan_xid
                        "partner_application_id": str(partner_application_id),
                        "status": "Loan not found",
                        "response": response_code
                    }
                    return response
                else:
                    if loan.loan_status_id >= LoanStatusCodes.FUND_DISBURSAL_ONGOING:
                        if loan.loan_status_id == LoanStatusCodes.FUND_DISBURSAL_ONGOING:
                            response_status = "Disburse already in process"
                        else:
                            response_status = "Disbursed"

                        response = {
                            "application_xid": loan_xid,  # actually loan_xid
                            "partner_application_id": str(partner_application_id),
                            "status": response_status,
                            "response": response_code
                        }
                        return response

                    if not axiata_customer_data.application.partner:
                        response = {
                            "application_xid": loan_xid,  # actually loan_xid
                            "partner_application_id": str(partner_application_id),
                            "status": "Partner info missing in application",
                            "response": response_code
                        }
                        return response

                    partner = axiata_customer_data.application.partner
                    axiata_bank_data = PartnerBankAccount.objects.\
                        filter(distributor_id=axiata_customer_data.distributor, partner=partner).last()
                    if not axiata_bank_data:
                        response = {
                            "application_xid": loan_xid,  # actually loan_xid
                            "partner_application_id": str(partner_application_id),
                            "status": "Partner bank account missing for distributor ",
                            "response": response_code
                        }
                        return response

                    if axiata_bank_data and axiata_bank_data.name_bank_validation_id:
                        name_bank_validation_id = axiata_bank_data.name_bank_validation_id
                    else:
                        # name bank validation
                        method = 'Xfers'
                        name_bank_validation_id, notebank_validation = PartnerDisbursementService.\
                            process_partner_bank_validation(partner,
                                                            method,
                                                            axiata_customer_data.distributor)
                        if not name_bank_validation_id:
                            status = "Bank validation Failed"

                if name_bank_validation_id:
                    # update first_payment_date
                    axiata_customer_data.update_safely(first_payment_date=first_payment_date)
                    axiata_customer_data.refresh_from_db()

                    # Update due date for payments
                    PartnerApplicationService.update_payment_due_date(loan, axiata_customer_data)

                    status = "Disbursement in progress"

                    axiata_bank_data.name_bank_validation_id = name_bank_validation_id
                    axiata_bank_data.save()

                    loan.name_bank_validation_id = name_bank_validation_id
                    loan.save()

                # record disbursement request staus
                response_code = 200
                partner_disbursement_request = PartnerDisbursementRequest.objects.create(
                    partner_application_id=partner_application_id,
                    loan_xid=loan_xid,
                    response=response_code,
                    status=status)

                logger.error(
                    {
                        "action": "Partner disbursement request",
                        "data": partner_disbursement_request.id
                    })

                # process disburse request async
                task_process_disbursement_request_async.delay(partner_application_id, loan_xid)

            response = {
                "application_xid": loan_xid,  # actually loan_xid
                "partner_application_id": str(partner_application_id),
                "status": status,
                "response": response_code
            }

            return response
        except Exception as e:
            logger.error({"action": "partner disbursement request", "errors": e})
            raise AxiataLogicException(e)

    @staticmethod
    def process_partner_bank_validation(partner, method, distributor=None):
        bank_account = PartnerBankAccount.objects.get(partner=partner, distributor_id=distributor)
        # prepare data to validate
        data_to_validate = {'name_bank_validation_id': bank_account.name_bank_validation_id,
                            'bank_name': bank_account.bank_name,
                            'account_number': bank_account.bank_account_number,
                            'name_in_bank': bank_account.name_in_bank,
                            'mobile_phone': str(bank_account.phone_number),
                            'application': None
                            }
        if method == 'Bca':
            method = 'Xfers'

        validation = trigger_name_in_bank_validation(data_to_validate, method)
        # assign validation_id to partner bank account
        validation_id = validation.get_id()
        logger.error(
            {
                "action": "Partner disbursement request",
                "validate_data": data_to_validate,
                "data": validation_id,
                "sub-action": "process_partner_bank_validation"
            })

        bank_account.name_bank_validation_id = validation_id
        bank_account.save(update_fields=['name_bank_validation_id'])
        validation.validate()
        validation_data = validation.get_data()

        if validation.is_success():
            note = 'Name in Bank Validation Success via %s' % (validation_data['method'])
            return validation_id, note

        elif validation.is_failed():
            note = 'Name in Bank Validation Failed via %s' % (validation_data['method'])
            return None, note

    @staticmethod
    def process_disbursement_request_async(partner_application_id, loan_xid):
        from juloserver.loan.services.lender_related import process_disburse

        loan = Loan.objects.get_or_none(loan_xid=loan_xid)
        axiata_customer_data = AxiataCustomerData.objects. \
            filter(partner_application_id=partner_application_id).last()
        if not axiata_customer_data:
            return

        data_to_disburse = PartnerDisbursementService.generate_disburse_bank_account_data(loan)
        logger.info(
            {
                "action": "Partner disbursement request",
                "data": data_to_disburse,
                "sub-action": "process_disbursement_request_async"
            })

        # check bulk disbursement turn on
        # make loan to bulk queue
        # end process
        bulk_disbursement_active = BulkDisbursementSchedule.objects.filter(
            product_line_code=loan.product.product_line,
            is_active=True,
        ).exists()

        if bulk_disbursement_active:
            move_to_bulk_queue(loan, data_to_disburse)
            return

        if data_to_disburse:
            process_disburse(data_to_disburse, loan)

    @staticmethod
    def generate_disburse_bank_account_data(loan):
        application_submission = ApplicationSubmission.objects.filter(loan_xid=loan.loan_xid).last()
        axiata_customer_data = AxiataCustomerData.objects. \
            filter(id=application_submission.axiata_customer_data_id).last()

        partner = axiata_customer_data.application.partner
        axiata_bank_data = PartnerBankAccount.objects.filter(
            distributor_id=axiata_customer_data.distributor,
            partner=partner,
            name_bank_validation_id__isnull=False).last()
        if axiata_bank_data:
            name_bank_validation_id = axiata_bank_data.name_bank_validation_id
        else:
            raise Exception('PartnerBankAccount not found')

        data_to_disburse = {
            'disbursement_id': loan.disbursement_id,
            'name_bank_validation_id': name_bank_validation_id,
            'amount': loan.loan_disbursement_amount,
            'external_id': loan.loan_xid,
            'type': 'loan',
            'original_amount': loan.loan_amount,
            'bank_name': axiata_bank_data.bank_name,
            'bank_account_number': axiata_bank_data.bank_account_number
        }
        return data_to_disburse

    @staticmethod
    def notify_partner(loan):
        loan_xid = loan.loan_xid

        application_submission = ApplicationSubmission.objects.filter(loan_xid=loan_xid).last()
        axiata_customer_data = AxiataCustomerData.objects. \
            filter(pk=application_submission.axiata_customer_data_id).last()

        sending_status = "Failed"
        disbursement_status = "Success"

        data = {
            "partner_application_id": axiata_customer_data.partner_application_id,
            "loan_xid": loan_xid,
            "disbursement_status": disbursement_status,
            "disbursed_amount": loan.loan_disbursement_amount,
            "fund_transfer_ts": timezone.localtime(timezone.now()),
            "sending_status": sending_status
        }

        # save to SentDisburseContract
        sent_disburse_contract = SentDisburseContract.objects.create(**data)
        logger.info(
            {
                "action": "Partner disbursement request",
                "data": data['partner_application_id'],
                "sub-action": "Merchant Financing Callback: disbursement status "
            })
        try:
            client = AxiataClient()

            data['application_xid'] = data.pop('loan_xid')
            data['disbursedAmount'] = data.pop('disbursed_amount')
            data.pop('sending_status')
            data.pop('disbursement_status')
            data['fund_transfer_ts'] = loan.udate.strftime('%m/%d/%Y %I:%M:%S %p')
            axiata_response = client.send_disbursement_contract(data)

            if axiata_response['code'] == 200:
                sending_status = "Success"
                sent_disburse_contract.update_safely(
                    sending_status=sending_status)
        except Exception as e:
            logger.error({"action": "callback_send_disbursement_contract", "errors": e})
            raise AxiataLogicException(e)


class PartnerLoanService(object):
    @staticmethod
    def notify_digital_signature_change_to_partner(loan_id):
        # loan = Loan.objects.get_or_none(id=loan_id)
        data = {
            "partner_application_id": "",
            "application_xid": "",
            "digital_signature_status": ""
        }

        client = AxiataClient()
        axiata_response = client.send_update_digital_signature(data)
        if axiata_response['code'] == 200:
            sending_status = "Success"
            print(sending_status)


class PartnerPaymentService(object):
    @staticmethod
    def notify_partner(payment_event):
        if payment_event:
            payment = payment_event.payment
            loan = payment.loan

            axiata_customer_data = AxiataCustomerData.objects.filter(loan_xid=loan.loan_xid).last()
            if not axiata_customer_data:
                application_submission = ApplicationSubmission.objects.\
                    filter(loan_xid=loan.loan_xid).last()
                axiata_customer_data = AxiataCustomerData.objects. \
                    filter(id=application_submission.axiata_customer_data_id).last()

                if not axiata_customer_data:
                    raise AxiataLogicException(
                        "Merchant Financing : repayment callback, axiata customer data has no loan_xid")

            if loan.status >= LoanStatusCodes.PAID_OFF:
                status = "Paid Off"
            else:
                status = "Not Paid Off"

            data = {
                "partner_application_id": axiata_customer_data.partner_application_id,
                "loan_xid": loan.loan_xid,
                "payment_number": payment.payment_number,
                "payment_amount": payment_event.event_payment,
                "payment_date": payment_event.event_date,
                "sending_status": "Failed",
                "status": status
            }
            # save to SentUpdateRepaymentInfo
            sent_update_repayment_info = SentUpdateRepaymentInfo.objects.create(**data)

            try:
                client = AxiataClient()

                data['application_xid'] = data.pop('loan_xid')
                data['payment_date'] = payment_event.cdate.strftime('%m/%d/%Y %I:%M:%S %p')
                data.pop('sending_status')

                axiata_response = client.send_repayment_information(data)

                if axiata_response['code'] == 200:
                    sending_status = "Success"
                    sent_update_repayment_info.update_safely(sending_status=sending_status)
            except Exception as e:
                logger.error({"action": "Merchant Financing callback send_repayment_information", "errors": e})
                raise AxiataLogicException(e)


def move_to_bulk_queue(loan, data_to_disburse, partner, distributor):
    BulkDisbursementRequest.objects.create(
        disbursement_status=BulkDisbursementStatus.QUEUE,
        loan=loan,
        product_line_code=loan.product.product_line,
        bank_account_number=data_to_disburse['bank_account_number'],
        bank_name=data_to_disburse['bank_name'],
        disbursement_amount=data_to_disburse['amount'],
        loan_amount=data_to_disburse['original_amount'],
        name_bank_validation_id=data_to_disburse['name_bank_validation_id'],
        partner=partner,
        distributor=distributor
    )
    update_loan_status_and_loan_history(
        loan.id,
        new_status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING,
        change_reason="Loan approved by lender"
    )


def sum_merchant_transaction(merchant, partner=None):
    current_date = datetime.now().date()
    historical_transaction_date_count = 30  # default
    month_duration = 6  # default

    # default for loan_duration is 1 days
    # if partnership_config.loan_duration exist, loan_duration is coming from the longest loan duration
    loan_duration = 1
    if partner:
        partnership_config = PartnershipConfig.objects.filter(partner=partner).first()
        if partnership_config and partnership_config.loan_duration:
            loan_duration = max(partnership_config.loan_duration)

        historical_transaction_date_count = partnership_config.historical_transaction_date_count
        month_duration = partnership_config.historical_transaction_month_duration

    """
        Find merchant historical transaction in range
        (current_date - historical_transaction_date_count, current_date)
        If transaction is found, use the latest transaction date as end_date
        and the start_date will be latest transaction date - 3 months
        based on PARTNER-1588
    """
    transaction_date_range = {
        'transaction_date__range': (
            current_date - relativedelta(days=historical_transaction_date_count), current_date
        )
    }
    historical_transaction = merchant.merchanthistoricaltransaction_set.filter(
        is_deleted=False,
        **transaction_date_range).order_by('-transaction_date').only('transaction_date').first()

    if historical_transaction:
        end_date = historical_transaction.transaction_date
        start_date = end_date - relativedelta(months=month_duration)

        transaction_date_range = {
            'transaction_date__range': (start_date, end_date)
        }
        unverified_transaction = merchant.merchanthistoricaltransaction_set.filter(
            payment_method=MerchantHistoricalTransaction.UNVERIFIED,
            is_deleted=False,
            **transaction_date_range).exists()

        if not unverified_transaction:
            """
                we should convert calculation result from float to int,
                if we didn't do that, float value can make the roundown process not accurate
            """
            return int(
                calculate_verified_transaction(merchant, transaction_date_range, loan_duration)
            )

        return int(calculate_all_transaction(merchant, transaction_date_range, loan_duration))
    else:
        # If transaction not found within the range, just return -1 so that it will got rejected by
        # business rule
        return -1


def calculate_verified_transaction(merchant, transaction_date_range, loan_duration):
    """
        calculation formula is regarding from this card:
        https://juloprojects.atlassian.net/browse/PARTNER-1127
    """
    verified_transactions = merchant.merchanthistoricaltransaction_set\
        .only('amount', 'id', 'merchant_id')\
        .filter(type=MerchantHistoricalTransaction.CREDIT,
                payment_method=MerchantHistoricalTransaction.VERIFIED,
                is_deleted=False,
                **transaction_date_range).iterator()

    total_amount = 0
    for vt in verified_transactions:
        total_amount += vt.amount

    return total_amount / 90 * loan_duration


def calculate_all_transaction(merchant, transaction_date_range, loan_duration):
    """
        Sum process are not execute in our database,
        because we must reduce the load to database
    """
    """
        calculation formula is regarding from this card:
        https://juloprojects.atlassian.net/browse/PARTNER-1127
    """
    only_fields = ['amount', 'id', 'merchant_id']
    total_income = get_total_income(merchant, transaction_date_range, only_fields)
    total_expense = get_total_expense(merchant, transaction_date_range, only_fields)

    return (total_income - total_expense) / 90 * loan_duration


def get_total_income(merchant, transaction_date_range, only_fields):
    verified_income_transactions = merchant.merchanthistoricaltransaction_set.only(*only_fields)\
        .filter(type=MerchantHistoricalTransaction.CREDIT,
                payment_method=MerchantHistoricalTransaction.VERIFIED,
                is_deleted=False,
                **transaction_date_range).iterator()
    unverified_income_transactions = merchant.merchanthistoricaltransaction_set\
        .only(*only_fields)\
        .filter(type=MerchantHistoricalTransaction.CREDIT,
                payment_method=MerchantHistoricalTransaction.UNVERIFIED,
                is_deleted=False,
                **transaction_date_range).iterator()

    total_verified_income = 0
    # vit is equal to verified_income_transactions
    for vit in verified_income_transactions:
        total_verified_income += vit.amount

    total_unverified_income = 0
    # uvit is equal to unverified_income_transactions
    for uvit in unverified_income_transactions:
        total_unverified_income += uvit.amount

    total_income = total_unverified_income * 0.7 + total_verified_income

    return total_income


def get_total_expense(merchant, transaction_date_range, only_fields):
    verified_expense_transactions = merchant.merchanthistoricaltransaction_set.only(*only_fields)\
        .filter(type=MerchantHistoricalTransaction.DEBIT,
                payment_method=MerchantHistoricalTransaction.VERIFIED,
                is_deleted=False,
                **transaction_date_range).iterator()
    unverified_expense_transactions = merchant.merchanthistoricaltransaction_set\
        .only(*only_fields)\
        .filter(type=MerchantHistoricalTransaction.DEBIT,
                payment_method=MerchantHistoricalTransaction.UNVERIFIED,
                is_deleted=False,
                **transaction_date_range).iterator()

    total_verified_expense = 0
    # vet is equal to verified_expense_transactions
    for vet in verified_expense_transactions:
        total_verified_expense += vet.amount

    total_unverified_expense = 0
    # uvet is equal to unverified_expense_transactions
    for uvet in unverified_expense_transactions:
        total_unverified_expense += uvet.amount

    total_expense = total_unverified_expense * 1.2 + total_verified_expense

    return total_expense


def get_credit_limit(merchant, total_amount):
    distributor = merchant.distributor
    if not distributor:
        raise JuloException("Merchant id: {} doesn't have distributor".format(merchant.id))

    partner = distributor.partner
    if not partner:
        raise JuloException(
            "Distributor id: {} from merchant id: {} doesn't have partner".format(
                distributor.id, merchant.id
            )
        )
    partner_affordability = partner.masterpartneraffordabilitythreshold
    if not partner_affordability:
        raise JuloException(
            "Partner id: {} doesn't have affordability threshold".format(partner.id)
        )
    max_threshold = partner_affordability.maximum_threshold
    min_threshold = partner_affordability.minimum_threshold
    historical_partner_affordability = partner_affordability\
        .historicalpartneraffordabilitythreshold_set\
        .filter(minimum_threshold=min_threshold, maximum_threshold=max_threshold)\
        .first()

    if not historical_partner_affordability:
        raise JuloException(
            "Historical Partner Affordability doesn't exists with "
            "minimum_threshold {} and maximum_threshold {}".format(min_threshold, max_threshold)
        )

    credit_limit_dict = {
        'is_qualified': True,
        'credit_limit': 0,
        'affordability_value': total_amount
    }
    # hpa is equal to historical_partner_affordability
    if total_amount < min_threshold:
        credit_limit_dict['is_qualified'] = False
    elif min_threshold <= total_amount < max_threshold:
        credit_limit_dict['credit_limit'] = round_down_credit_limit(total_amount)
        credit_limit_dict['hpa'] = historical_partner_affordability
    elif total_amount >= partner_affordability.maximum_threshold:
        credit_limit_dict['credit_limit'] = round_down_credit_limit(max_threshold)
        credit_limit_dict['hpa'] = historical_partner_affordability

    return credit_limit_dict


def round_down_credit_limit(credit_limit):
    """
        - if credit limit < 1 million round down per 50.000
        - if credit limit > 1 million round down per 500.000
    """
    one_million = 1000000
    if credit_limit <= one_million:
        return round_down_nearest(credit_limit, 50000)
    elif credit_limit >= one_million:
        return round_down_nearest(credit_limit, 500000)


def get_sphp_template_merhant_financing(application_id, sphp_type):
    application = Application.objects.get_or_none(pk=application_id)
    template = ''

    if not application:
        return None

    pks_number = '1.JTF.201707'
    sphp_date = timezone.now().date()
    application_history_x130 = application.applicationhistory_set.filter(
        status_new=ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL
    ).last()
    account_limit = AccountLimit.objects.filter(account=application.account).last()
    context = {
        'application_xid': application.application_xid,
        'dob': format_date(application.dob, 'dd-MM-yyyy', locale='id_ID'),
        'full_address': application.full_address,
        'date_today': format_date(sphp_date, 'd MMMM yyyy', locale='id_ID'),
        'julo_image': settings.SPHP_STATIC_FILE_PATH + 'scraoe-copy-3@3x.png',
        'agreement_letter_number': pks_number,
        'date_credit_limit_generated': format_date(
            application_history_x130.cdate.date(), 'd MMMM yyyy', locale='id_ID'
        ),
        'fullname': application.fullname,
        'ktp': application.ktp,
        'phone_number': application.mobile_phone_1,
        'set_limit': display_rupiah(account_limit.set_limit),
    }

    if sphp_type == SPHPType.DOCUMENT:
        template = render_to_string('julo_merchant_financing_sphp_document.html', context=context)
    elif sphp_type == SPHPType.WEBVIEW:
        template = render_to_string('julo_merchant_financing_sphp.html', context=context)

    return template


def emails_sign_sphp_merchant_financing_expired(application_id=None):
    today_timestamp = timezone.localtime(timezone.now())
    three_days_ago_timestamp = today_timestamp - timedelta(days=3)
    filter_email_sign_sphp_expired = dict(
        application__application_status_id=ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
        application__workflow__name=WorkflowConst.MERCHANT_FINANCING_WORKFLOW,
        cdate__lte=three_days_ago_timestamp,
        template_code=EmailTemplateConst.SIGN_SPHP_MERCHANT_FINANCING
    )
    if application_id:
        filter_email_sign_sphp_expired['application__id'] = application_id
        filter_email_sign_sphp_expired['application__application_status_id__in'] = [
            ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
            ApplicationStatusCodes.APPLICATION_DENIED
        ]
        del filter_email_sign_sphp_expired['application__application_status_id']
    emails_sphp_expired = EmailHistory.objects.exclude(
        application__product_line_id__in=ProductLineCodes.axiata()
    ).filter(**filter_email_sign_sphp_expired).select_related('application')

    return emails_sphp_expired


class LoanMerchantFinancing(object):
    def get_loan_duration(application, loan_amount_request):
        partnership_config = PartnershipConfig.objects.filter(
            partner=application.partner,
            partnership_type__partner_type_name=PartnershipTypeConstant.MERCHANT_FINANCING
        ).last()
        if not partnership_config:
            return

        available_duration = partnership_config.loan_duration
        if not available_duration or (len(available_duration) == 1 and available_duration[0] == 0):
            raise JuloException('Gagal mendapatkan durasi pinjamann')

        account = application.account
        account_limit = AccountLimit.objects.filter(account=account).last()
        if not account_limit:
            raise JuloException('akun tidak ditemukan')

        available_limit = account_limit.available_limit
        historical_partner_cpl = get_product_lookup_by_merchant(merchant=application.merchant)

        if not historical_partner_cpl:
            raise JuloException("Gagal mendapatkan historical partner config product lookup")

        product_lookup = historical_partner_cpl.product_lookup
        origination_fee_pct = product_lookup.origination_fee_pct

        # Calculationg amount depends partnership_config.is_loan_amount_adding_mdr_ppn
        loan_amount = is_loan_amount_adding_mdr_with_ppn(loan_amount_request,
                                                         origination_fee_pct,
                                                         partnership_config)

        if loan_amount > available_limit:
            raise JuloException(
                "Jumlah pinjaman tidak boleh lebih besar dari limit tersedia"
            )

        monthly_interest_rate = product_lookup.monthly_interest_rate
        provision_fee = origination_fee_pct
        loan_choice = []
        daily_max_fee_from_ojk = get_daily_max_fee()
        for duration in partnership_config.loan_duration:
            additional_loan_data = {
                'is_exceed': False,
                'max_fee_ojk': 0.0,
                'simple_fee': 0.0,
                'provision_fee_rate': 0.0,
                'new_interest_rate': 0.0
            }
            loan_requested = dict(
                original_loan_amount=loan_amount_request,
                loan_amount=loan_amount,
                loan_duration_in_days=duration,
                interest_rate_monthly=monthly_interest_rate,
                product_lookup=product_lookup,
                provision_fee=origination_fee_pct,
            )

            daily_interest_rate = product_lookup.daily_interest_rate
            if daily_max_fee_from_ojk:
                additional_loan_data = validate_merchant_financing_max_interest_with_ojk_rule(
                    loan_requested, additional_loan_data, daily_max_fee_from_ojk
                )
                if additional_loan_data['is_exceed']:

                    adjusted_loan_amount = is_loan_amount_adding_mdr_with_ppn(
                        loan_requested['original_loan_amount'],
                        additional_loan_data['provision_fee_rate'],
                        partnership_config
                    )
                    daily_interest_rate = py2round(
                        additional_loan_data['new_interest_rate'] / 30, 3
                    )
                    provision_fee = additional_loan_data['provision_fee_rate']
                    loan_amount = adjusted_loan_amount
                else:
                    adjusted_loan_amount = is_loan_amount_adding_mdr_with_ppn(
                        loan_requested['original_loan_amount'],
                        origination_fee_pct,
                        partnership_config
                    )
                    provision_fee = origination_fee_pct
                    loan_amount = adjusted_loan_amount

            disbursement_amount = py2round(loan_amount - (loan_amount * provision_fee))
            available_limit_after_transaction = available_limit - loan_amount
            installment_interest = (daily_interest_rate * loan_requested['loan_duration_in_days'])\
                * loan_requested['original_loan_amount']
            loan_choice.append({
                'loan_amount': loan_amount,
                'duration': duration,
                'monthly_installment': loan_amount + installment_interest,
                'provision_amount': provision_fee,
                'disbursement_amount': int(disbursement_amount),
                'cashback': int(py2round(
                    loan_amount * historical_partner_cpl.product_lookup.cashback_payment_pct
                )),
                'available_limit': available_limit,
                'available_limit_after_transaction': available_limit_after_transaction,
            })

        return loan_choice

    def get_range_loan_amount(application):
        account = application.account
        account_limit = AccountLimit.objects.filter(account=account).last()
        if not account_limit:
            raise JuloException('akun tidak ditemukan')

        available_limit = account_limit.available_limit
        historical_partner_cpl = get_product_lookup_by_merchant(merchant=application.merchant)

        if not historical_partner_cpl:
            raise JuloException("Gagal mendapatkan historical partner config product lookup")

        origination_fee = historical_partner_cpl.product_lookup.origination_fee_pct
        max_amount = available_limit - int(py2round(available_limit * origination_fee))
        min_amount_threshold = LoanJuloOneConstant.MIN_LOAN_AMOUNT_THRESHOLD
        min_amount = max_amount
        if min_amount_threshold < available_limit:
            min_amount = min_amount_threshold

        response_data = dict(
            min_amount=min_amount,
            max_amount=max_amount
        )
        return response_data


def process_create_loan(data, application, account):
    if is_loan_more_than_one(account):
        return general_error_response(ErrorMessageConst.CONCURRENCY_MESSAGE_CONTENT)

    if is_account_forbidden_to_create_loan(account):
        return general_error_response(ErrorMessageConst.STATUS_NOT_VALID)

    transaction_method_id = TransactionMethodCode.OTHER.code
    transaction_method = TransactionMethod.objects.filter(id=transaction_method_id).last()
    product_lookup = application.product_lookup
    partner = application.merchant.distributor.partner
    if not is_loan_duration_valid(data['loan_duration_in_days'], partner):
        return general_error_response('loan_duration yang dipilih tidak sesuai')

    origination_fee_pct = product_lookup.origination_fee_pct
    partnership_config = PartnershipConfig.objects.filter(
        partner=application.partner,
        partnership_type__partner_type_name=PartnershipTypeConstant.MERCHANT_FINANCING
    ).select_related('partnership_type').last()

    # Calculationg amount depends partnership_config.is_loan_amount_adding_mdr_ppn
    loan_amount = is_loan_amount_adding_mdr_with_ppn(
        data['loan_amount_request'],
        origination_fee_pct,
        partnership_config
    )
    interest_rate_monthly = product_lookup.monthly_interest_rate

    try:
        with transaction.atomic():
            account_limit = AccountLimit.objects.select_for_update().filter(
                account=application.account
            ).last()
            if loan_amount > account_limit.available_limit:
                raise AccountLimitExceededException(
                    "Jumlah pinjaman tidak boleh lebih besar dari limit tersedia"
                )
            """
                if product lookup from recalculate process is different
                with current product_lookup in merchant, then replace with a new one
            """
            product_lookup_from_merchant = application.merchant.historical_partner_config_product_lookup
            if application.product_lookup != product_lookup_from_merchant:
                application.merchant.historical_partner_config_product_lookup = application.hcpl_obj
                application.merchant.save()

            loan_requested = dict(
                original_loan_amount=data['loan_amount_request'],
                loan_amount=loan_amount,
                loan_duration_in_days=data['loan_duration_in_days'],
                interest_rate_monthly=interest_rate_monthly,
                product_lookup=product_lookup,
                provision_fee=origination_fee_pct,
            )
            distributor = application.merchant.distributor
            loan = generate_loan_payment_merchant_financing(application, loan_requested,
                                                            distributor)

            loan.update_safely(transaction_method=transaction_method)
            update_available_limit(loan)
    except AccountLimitExceededException as e:
        return general_error_response(str(e))

    monthly_interest_rate = loan.interest_rate_monthly
    if hasattr(loan, 'loanadjustedrate'):
        monthly_interest_rate = loan.loanadjustedrate.adjusted_monthly_interest_rate

    update_customer_pin_used_status(application)
    process_add_partner_loan_request(loan, application.merchant.distributor.partner, distributor,
                                     loan_original_amount=data['loan_amount_request'])
    response_data = {
        'loan_status': loan.partnership_status,
        'loan_amount': loan.loan_amount,
        'disbursement_amount': loan.loan_disbursement_amount,
        'loan_duration': loan.loan_duration,
        'installment_amount': loan.installment_amount,
        'monthly_interest': monthly_interest_rate,
        'loan_xid': loan.loan_xid,
    }

    return success_response(response_data)


def get_sphp_loan_merchant_financing(loan_id: int) -> Union[str, None]:
    loan = Loan.objects.prefetch_related('payment_set').select_related(
        'lender', 'account'
    ).filter(pk=loan_id).last()

    if not loan:
        return None
    sphp_date = loan.sphp_sent_ts
    application = loan.account.last_application
    account_limit = loan.account.accountlimit_set.last()
    context = {
        'loan': loan,
        'application': application,
        'dob': format_date(application.dob, 'dd-MM-yyyy', locale='id_ID'),
        'full_address': application.full_address,
        'loan_amount': display_rupiah(loan.loan_amount),
        'late_fee_amount': display_rupiah(loan.late_fee_amount),
        'julo_bank_name': loan.julo_bank_name,
        'julo_bank_code': '-',
        'julo_bank_account_number': loan.julo_bank_account_number,
        'date_today': format_date(sphp_date, 'd MMMM yyyy', locale='id_ID'),
        'background_image': settings.SPHP_STATIC_FILE_PATH + 'julo-a-4@3x.png',
        'julo_image': settings.SPHP_STATIC_FILE_PATH + 'scraoe-copy-3@3x.png',
        'sphp_general_signed_date': format_date(
            application.sphp_general_ts, 'd MMMM yyyy', locale='id_ID'
        ),
        'available_limit': display_rupiah(account_limit.available_limit)
    }

    if 'bca' not in loan.julo_bank_name.lower():
        payment_method = PaymentMethod.objects.filter(
            virtual_account=loan.julo_bank_account_number).first()
        if payment_method:
            context['julo_bank_code'] = payment_method.bank_code
    payments = loan.payment_set.all().order_by('id')
    for payment in payments:
        payment.due_date = format_date(payment.due_date, 'd MMM yy', locale='id_ID')
        payment.due_amount = display_rupiah(payment.due_amount + payment.paid_amount)
    context['payments'] = payments
    max_total_late_fee_amount = loan.late_fee_amount * 7
    context['max_total_late_fee_amount'] = display_rupiah(max_total_late_fee_amount)
    context['provision_fee_amount'] = display_rupiah(loan.provision_fee())
    context['interest_rate'] = display_rupiah(payments.last().installment_interest)
    template = render_to_string('julo_merchant_financing_sphp_loan_document.html',
                                context=context)

    return template


class BankAccount:
    def inquiry_bank_account(
            self, bank_code: str, bank_account_number: str, phone_number: str,
            name_in_bank: str
    ) -> dict:
        name_bank_validation = NameBankValidation(
            bank_code=bank_code,
            account_number=bank_account_number,
            name_in_bank=name_in_bank,
            mobile_phone=phone_number,
            method=NameBankValidationVendors.XFERS
        )
        name_bank_validation_log = BankNameValidationLog(
            account_number=name_bank_validation.account_number,
            method=name_bank_validation.method
        )
        xfers_service = XfersService()
        try:
            response_validate = xfers_service.validate(name_bank_validation)
            name_bank_validation_log.reason = response_validate['reason'],
            name_bank_validation_log.validation_status = response_validate['status']
            name_bank_validation_log.validated_name = response_validate['validated_name']
            name_bank_validation_log.validation_id = response_validate['id']
            name_bank_validation.validated_name = response_validate['validated_name']
            name_bank_validation.error_message = response_validate['error_message']
            name_bank_validation.validation_status = response_validate['status']
            name_bank_validation.validation_id = response_validate['id']

        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout, XfersApiError) as e:
            response_validate = dict(
                status=NameBankValidationStatus.FAILED,
                error_message=str(e)
            )
            name_bank_validation.error_message = str(e)
            name_bank_validation.validation_status = NameBankValidationStatus.FAILED
            name_bank_validation_log.validation_status = NameBankValidationStatus.FAILED

        name_bank_validation.save()
        name_bank_validation_log.save()

        response_validate['name_bank_validation'] = name_bank_validation

        return response_validate

    def validate_bank_account(
        self,
        bank_id: int,
        bank_code: str,
        bank_account_number: str,
        phone_number: str,
        name_in_bank: str,
    ) -> dict:
        """Validate bank account using new payment gateway service - January 2025
        Args:
            bank_id (int): id from table ops.bank
            bank_account_number (str): distributor bank account number
            phone_number (str): distributor phone number
            name_in_bank (str): distributor name in bank
        Returns:
            dict: Dictionary that consist of bank validation result status, reason, and error
        """
        from juloserver.julo.services2.client_paymet_gateway import ClientPaymentGateway

        fn_name = "BankAccount.validate_bank_account"
        response = {}

        try:
            payload = {
                "bank_account": bank_account_number,
                "bank_id": bank_id,
                "bank_account_name": name_in_bank,
            }
            client = ClientPaymentGateway(
                client_id=settings.PARTNERSHIP_PAYMENT_GATEWAY_CLIENT_ID,
                api_key=settings.PARTNERSHIP_PAYMENT_GATEWAY_API_KEY,
            )
            with transaction.atomic():
                name_bank_validation = NameBankValidation.objects.create(
                    bank_code=bank_code,
                    account_number=payload.get('bank_account'),
                    name_in_bank=payload.get('bank_account_name'),
                    mobile_phone=phone_number,
                    method='PG',  # set method using payment gateway(PG)
                )
                update_fields = [
                    'bank_code',
                    'account_number',
                    'name_in_bank',
                    'mobile_phone',
                    'method',
                ]
                name_bank_validation.create_history('create', update_fields)
                update_fields_for_log_name_bank_validation = [
                    'validation_status',
                    'validated_name',
                    'reason',
                ]

                result = client.verify_bank_account(payload)
                is_http_request_success = result.get('success')
                data = result.get('data')
                reason = None

                if is_http_request_success:  # handle status 200
                    validation_result_data = data.get('validation_result')
                    status = validation_result_data.get('status')
                    bank_account_info = validation_result_data.get('bank_account_info')
                    reason = validation_result_data.get('message')
                    if status == 'success':
                        name_bank_validation.validation_status = NameBankValidationStatus.SUCCESS
                        name_bank_validation.validated_name = bank_account_info.get(
                            'bank_account_name'
                        )
                    else:
                        # case if validation_result != success
                        name_bank_validation.validation_status = NameBankValidationStatus.FAILED
                else:
                    # case if error 400, 401, 429, 500
                    reason = result.get('errors')[0]
                    name_bank_validation.validation_status = NameBankValidationStatus.FAILED

                name_bank_validation.reason = reason
                name_bank_validation.save(update_fields=update_fields_for_log_name_bank_validation)
                name_bank_validation.create_history(
                    'update_status', update_fields_for_log_name_bank_validation
                )
                name_bank_validation.refresh_from_db()
                # create name_bank_validation_log
                name_bank_validation_log = BankNameValidationLog()
                name_bank_validation_log.validated_name = name_bank_validation.name_in_bank
                name_bank_validation_log.account_number = name_bank_validation.account_number
                name_bank_validation_log.method = name_bank_validation.method
                name_bank_validation_log.reason = reason
                name_bank_validation_log.validation_status = name_bank_validation.validation_status
                name_bank_validation_log.validated_name = name_bank_validation.validated_name
                name_bank_validation_log.save()

                name_bank_validation.refresh_from_db()
                # create name_bank_validation_log
                name_bank_validation_log = BankNameValidationLog()
                name_bank_validation_log.validated_name = name_bank_validation.name_in_bank
                name_bank_validation_log.account_number = name_bank_validation.account_number
                name_bank_validation_log.method = name_bank_validation.method
                name_bank_validation_log.reason = reason
                name_bank_validation_log.validation_status = name_bank_validation.validation_status
                name_bank_validation_log.validated_name = name_bank_validation.validated_name
                name_bank_validation_log.save()

                response['status'] = name_bank_validation.validation_status
                response['reason'] = reason
                response['error_message'] = ""

                logger.info({'action': fn_name, 'response': response})
                return response

        except Exception as error:
            julo_sentry_client.captureException()

            response['status'] = NameBankValidationStatus.NAME_INVALID
            response['reason'] = "Failed to add bank account"
            response['error_message'] = str(error)

            logger.error({'action': fn_name, 'response': response})
            return response


def get_payment_methods(application, bank_name):
    payment_method_fields = [
        'is_shown', 'bank_code', 'virtual_account', 'is_primary', 'is_shown',
        'payment_method_name', 'payment_method_code', 'edited_by'
    ]
    if application.is_merchant_flow():
        payment_methods = PaymentMethod.objects.filter(
            customer_id=application.customer, is_shown=True,
            payment_method_name__in=PaymentMethodLookup.objects.
                exclude(code__in=mf_excluded_payment_method_codes).
                values_list('name', flat=True)
        ).values(*payment_method_fields)
    else:
        payment_methods = PaymentMethod.objects.filter(
            customer_id=application.customer, is_shown=True,
            payment_method_name__in=PaymentMethodLookup.objects.all().values_list('name', flat=True)
        ).exclude(payment_method_code=PaymentMethodCodes.GOPAY).values(*payment_method_fields)

    global_payment_methods_dict = {}
    if application.application_status_id >= ApplicationStatusCodes.LOC_APPROVED:
        global_payment_methods = GlobalPaymentMethod.objects.all()

        for payment_method in global_payment_methods:
            global_payment_methods_dict[payment_method.payment_method_name] = payment_method

    list_method_lookups = []
    last_payment_method = None
    for payment_method in payment_methods:
        payment_method_dict = {}
        payment_method_dict['is_shown'] = payment_method['is_shown']
        payment_method_dict['bank_code'] = payment_method['bank_code']
        payment_method_dict['virtual_account'] = payment_method['virtual_account']
        payment_method_dict['is_primary'] = payment_method['is_primary']
        payment_method_dict['payment_method_name'] = payment_method['payment_method_name']
        global_payment_method = global_payment_methods_dict.get(payment_method['payment_method_name'])
        payment_method_obj = namedtuple("PaymentMethod", payment_method.keys())(*payment_method.values())
        if global_payment_method and is_global_payment_method_used(payment_method_obj,
                                                                   global_payment_method):
            payment_method_dict['is_shown'] = global_payment_method.is_active

        if not payment_method['is_shown']:
            continue

        if "BCA" in bank_name:
            if payment_method['bank_code'] == BankCodes.BCA:
                list_method_lookups.insert(0, payment_method_dict)
            elif payment_method['payment_method_code'] == PaymentMethodCodes.PERMATA1:
                last_payment_method = payment_method_dict
            else:
                list_method_lookups.append(payment_method_dict)
        else:
            if payment_method['bank_code'] == BankCodes.PERMATA:
                if payment_method['payment_method_code'] == PaymentMethodCodes.PERMATA:
                    list_method_lookups.insert(0, payment_method_dict)
                else:
                    last_payment_method = payment_method_dict
            else:
                list_method_lookups.append(payment_method_dict)

    if last_payment_method:
        list_method_lookups.append(last_payment_method)

    return list_method_lookups


def get_account_payments_and_virtual_accounts(application_xid, data):
    is_paid_off = data['is_paid_off']
    virtual_accounts = None
    only_fields = [
        'id',
        'account_id',
        'customer_id',
        'application_status_id'
    ]
    join_tables = [
        'account',
        'customer'
    ]

    application = Application.objects.select_related(*join_tables) \
        .only(*only_fields).filter(application_xid=application_xid).first()
    filter_data = dict(
        account=application.account
    )

    if data.get('filter_type') and data['filter_type']:
        filter_type = data['filter_type']
        start_date = data['start_date']
        end_date = data['end_date']
    else:
        filter_type = 'cdate'
        start_date = None
        end_date = None

    if filter_type == 'due_date':
        filter_data.update(
            due_date__range=(start_date, end_date)
        )
        order_by = 'due_date'
    else:
        if start_date is not None and end_date is not None:
            filter_data.update(
                cdate__date__range=(start_date, end_date)
            )
        order_by = 'cdate'

    account_payment_query_set = AccountPayment.objects.filter(
        **filter_data
    ).exclude(due_amount=0, paid_amount=0).order_by(order_by)

    if is_paid_off:
        account_payments = account_payment_query_set.paid()
    else:
        account_payments = account_payment_query_set.not_paid_active()
        if not account_payments:
            loan = []
        else:
            loan = account_payment_query_set.first().payment_set.order_by('due_date').first().loan

        julo_bank_name = ''
        if account_payments.first():
            loan = account_payments.first().payment_set.order_by('due_date').first().loan
            julo_bank_name = loan.julo_bank_name

        virtual_accounts = get_payment_methods(application, julo_bank_name)

    return account_payments, virtual_accounts


def generate_encrypted_application_xid(application_xid, partnership_type=None):
    encrypter = encrypt()
    if partnership_type is None:
        xid = encrypter.encode_string(str(application_xid))
    else:
        xid = encrypter.encode_string(
            str("{}{}").format(partnership_type,
                               application_xid))

    return xid


def get_urls_axiata_report(report_date_str: str, report_type: Optional[str] = None) -> \
        Union[dict, None]:
    filter_document = dict(
        document_source=int(report_date_str.replace('-', '')),
        document_type__in=AxiataReportType.all()
    )

    if report_type:
        filter_document.pop('document_type__in')
        if report_type == AxiataReportType.DISBURSEMENT:
            filter_document['document_type'] = AxiataReportType.DISBURSEMENT
        elif report_type == AxiataReportType.REPAYMENT:
            filter_document['document_type'] = AxiataReportType.REPAYMENT
    documents = Document.objects.filter(**filter_document)

    if not documents:
        return None

    urls = {}

    for document in documents:
        document_url = document.document_url
        if not document_url:
            continue
        urls['{}_url'.format(document.document_type)] = shorten_url(document_url)

    return urls


def get_axiata_disbursement_data(date_str: str) -> list:
    with connection.cursor() as cursor:
        cursor.execute("select distinct (ead.register_date AT TIME ZONE 'asia/jakarta')::timestamp::text "
                       "AS register_date , ead.application_xid, ead.fullname, ead.brand_name, "
                       "ead.ktp, ead.mobile_phone_1, ead.distributor_name, ead.loan_amount, "
                       "ead.disbursed_amount, ead.status_disbursement, ead.disbursed_date::text, "
                       "(ead.partner_application_date AT TIME ZONE 'asia/jakarta')::timestamp::text"
                       " as partner_application_date, (ead.acceptance_date AT TIME ZONE"
                       " 'asia/jakarta')::timestamp::text as acceptance_date, ead.account_number, "
                       "ead.funder, far.due_date::text, far.due_amount, far.interest_amount, ead.provision_fee "
                       "from sb.eunike_axiata_disbursement ead inner join "
                       "ops.application a on ead.application_xid::bigint = a.application_xid "
                       "inner join sb.farandi_axiata_repayment far  "
                       "on far.application_xid::bigint = a.application_xid "
                       "inner join ops.axiata_customer_data acd on a.application_id = "
                       "acd.application_id where acd.cdate::date = '{}'::date".format(date_str))

        data_axiata_disbursement = cursor.fetchall()

    return data_axiata_disbursement


def get_axiata_repayment_data(date_str: str) -> list:
    with connection.cursor() as cursor:
        cursor.execute("select (far.register_date AT TIME ZONE 'asia/jakarta')::timestamp::text "
                       "as register_date, far.application_xid, "
                       "far.payment_amount, far.payment_number, far.invoice_idip_address, "
                       "far.due_date::text, far.payment_date::text, far.payment_upload_date::text, "
                       "far.dpd, far.interest_amount, far.late_fee_amount, far.mobile_phone_1, "
                       "far.fullname, far.brand_name, far.distributor_name, far.loan_amount, "
                       "far.due_amount, far.paid_amount, far.status, far.julo_bank_name, "
                       "far.julo_bank_account_number, far.funder from "
                       "sb.farandi_axiata_repayment far inner join ops.application a "
                       "on far.application_xid::bigint = a.application_xid inner join "
                       "ops.axiata_customer_data acd on a.application_id = acd.application_id"
                       " where far.payment_date::date = '{}'::date".format(date_str))
        data_axiata_disbursement = cursor.fetchall()

    return data_axiata_disbursement


def generate_merchant_historical_csv_file(data: list, unique_id: int,
                                          csv_type: str = 'raw', dir_path: str = '') -> str:
    if dir_path:
        temp_dir = dir_path
    else:
        temp_dir = tempfile.gettempdir()
    csv_filename = 'merchant_historical_transaction_{}_{}.csv'.format(unique_id, csv_type)
    csv_filepath = os.path.join(temp_dir, csv_filename)
    field_names = ['type', 'transaction_date', 'booking_date',
                   'payment_method', 'amount', 'term_of_payment']
    if csv_type == 'error':
        field_names.insert(0, 'errors')
    with open(csv_filepath, 'w') as csv_file:
        dict_writer = csv.DictWriter(csv_file, fieldnames=field_names, extrasaction='ignore')
        dict_writer.writeheader()
        dict_writer.writerows(data)

    return csv_filepath


def validate_merchant_historical_transaction_data(merchant_historical_transactions):
    is_valid = True
    errors = []
    validated_data = []
    for merchant_historical_transaction in merchant_historical_transactions:
        serializer = MerchantHistoricalTransactionSerializer(
            data=merchant_historical_transaction,
        )

        if not serializer.is_valid():
            is_valid = False
            error = serializer.data
            error['errors'] = serializer.errors
            errors.append(error)
        else:
            validated_data.append(serializer.validated_data)

    if is_valid:
        return (True, validated_data)
    else:
        return (False, errors)


def store_data_merchant_historical_transaction(
    file_path: str, application_id: int,
    merchant_historical_transaction_task_id: int,
    document_type: str,
) -> None:
    filename = os.path.basename(file_path)
    document = Document.objects.create(
        document_source=application_id,
        document_type=document_type,
        filename=filename,
        service='oss'
    )
    upload_document(document.id, file_path)
    with transaction.atomic():
        merchant_historical_transaction_task = MerchantHistoricalTransactionTask.objects.\
            select_for_update().get(id=merchant_historical_transaction_task_id)
        document.refresh_from_db()

        if document_type == 'merchant_historical_transaction_data':
            merchant_historical_transaction_task.path = document.url
        elif document_type == 'merchant_historical_transaction_data_invalid':
            merchant_historical_transaction_task.error_path = document.url

        merchant_historical_transaction_task.save()


def is_customer_pass_otp(customer: Customer, action_logs: str = None) -> bool:
    mobile_feature_setting = MobileFeatureSetting.objects.get_or_none(
        feature_name='mobile_phone_1_otp',
        is_active=True
    )

    if mobile_feature_setting:
        otp_request = OtpRequest.objects.filter(
            customer=customer
        ).only('is_used').last()

        if not otp_request:
            return False
        elif not otp_request.is_used:
            return False

        partner_otp_action = PartnershipUserOTPAction.objects.filter(
            otp_request=otp_request.id
        ).last()
        if not partner_otp_action:
            return False
        elif partner_otp_action.is_used:
            return False

        partner_otp_action.is_used = True
        partner_otp_action.action_logs = action_logs
        partner_otp_action.save(update_fields=['is_used', 'action_logs'])

    return True


def get_partner_loan_amount_by_transaction_type(loan_amount: float,
                                                origination_fee_percentage: float,
                                                is_withdraw_funds: bool) -> float:
    if not is_withdraw_funds:
        return int(py2round(old_div(loan_amount, (1 - origination_fee_percentage))))
    return loan_amount


def is_loan_amount_adding_mdr_with_ppn(loan_amount_request: float,
                                       product_origination_fee_pct: float,
                                       partnership_config: PartnershipConfig = None) -> float:
    if partnership_config and partnership_config.is_loan_amount_adding_mdr_ppn:
        loan_amount = get_partner_loan_amount_by_transaction_type(
            loan_amount_request,
            product_origination_fee_pct,
            True
        )
    else:
        loan_amount = get_loan_amount_by_transaction_type(
            loan_amount_request,
            product_origination_fee_pct,
            False
        )
    return loan_amount


def store_account_property_merchant_financing(application: Application,
                                              set_limit: int) -> None:
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


def list_all_axiata_data() -> list:
    pii_filter_dict = generate_pii_filter_query_partnership(
        Partner, {'name': PartnerConstant.AXIATA_PARTNER}
    )
    partner = Partner.objects.filter(**pii_filter_dict).last()
    axiata_data = []
    if partner:
        with connection.cursor() as cursor:
            query = "select ah.cdate::date::text as loan_date" \
                    ", acd.fullname" \
                    ", a.ktp" \
                    ", acd.distributor as distributor_id" \
                    ", acd.partner_product_line as distributor_name" \
                    ", 'Modal Usaha' as tujuan_pinjaman" \
                    ", sum(l.loan_amount) as loan_amount" \
                    ", min(acd.loan_duration) as tenor" \
                    ", max(acd.origination_fee) as provisi" \
                    ", max(acd.interest_rate) as interest " \
                    "from ops.application a " \
                    "join (select ah.application_id,max(ah.cdate) as cdate " \
                    "from ops.application_history ah " \
                    "where ah.status_new = 177 " \
                    "and ah.application_id in " \
                    "(select application_id from ops.application where partner_id = {}) " \
                    "group by 1" \
                    ")ah on a.application_id = ah.application_id " \
                    "join ops.loan l on l.application_id = a.application_id " \
                    "join ops.axiata_customer_data acd on a.application_id = acd.application_id " \
                    "left join ops.partner_origination_data pod on " \
                    "pod.partner_origination_data_id::text = acd.distributor " \
                    "left join sb.axiata_distributor ad on acd.distributor = ad.distributor_id::text " \
                    "where " \
                    "a.application_status_code in (177) and a.partner_id = {} " \
                    "group by 1,2,3,4,5,6 order by 1 desc".format(partner.id, partner.id)
            cursor.execute(query)
            axiata_data = cursor.fetchall()

    return axiata_data


def write_row_result(
        row: Dict,
        is_success: bool,
        message: str = None,
        type: str = MF_DISBURSEMENT_KEY,
        partner_name: str = None,
):
    if type == MF_DISBURSEMENT_KEY:
        if partner_name == MerchantFinancingCSVUploadPartner.RABANDO:
            return [
                is_success,
                row.get('application_xid'),
                row.get('no'),
                row.get('business_name'),
                row.get('name'),
                row.get('phone_number'),
                row.get('date_request_disbursement'),
                row.get('time_request'),
                row.get('loan_amount_request'),
                row.get('status'),
                row.get('reason'),
                row.get('date_disbursement'),
                row.get('amount_disbursement'),
                row.get('loan_duration'),
                row.get('origination_fee_pct'),
                row.get('amount_due'),
                row.get('due_date'),
                row.get('date_submit_disbursement'),
                row.get('interest_rate'),
                row.get('name_in_bank'),
                row.get('bank_name'),
                row.get('bank_account_number'),
                row.get('distributor_mobile_number'),
                row.get('loan_duration_type'),
                message,
            ]
        else:
            return [
                is_success,
                row.get('application_xid'),
                row.get('no'),
                row.get('business_name'),
                row.get('name'),
                row.get('phone_number'),
                row.get('date_request_disbursement'),
                row.get('time_request'),
                row.get('loan_amount_request'),
                row.get('status'),
                row.get('reason'),
                row.get('date_disbursement'),
                row.get('amount_disbursement'),
                row.get('loan_duration'),
                row.get('origination_fee_pct'),
                row.get('amount_due'),
                row.get('due_date'),
                row.get('date_submit_disbursement'),
                row.get('interest_rate'),
                row.get('loan_duration_type'),
                message,
            ]

    elif type == MF_REGISTER_KEY:
        return [
            row.get("ktp_photo"),
            row.get("selfie_photo"),
            row.get("fullname"),
            row.get("mobile_phone_1"),
            row.get("ktp"),
            row.get("email"),
            row.get("gender"),
            row.get("birth_place"),
            row.get("dob"),
            row.get("marital_status"),
            row.get("close_kin_name"),
            row.get("close_kin_mobile_phone"),
            row.get("address_provinsi"),
            row.get("address_kabupaten"),
            row.get("address_kecamatan"),
            row.get("address_kodepos"),
            row.get("address_street_num"),
            row.get("bank_name"),
            row.get("bank_account_number"),
            row.get("loan_purpose"),
            row.get("monthly_income"),
            row.get("monthly_expenses"),
            row.get("pegawai"),
            row.get("usaha"),
            row.get("selfie_n_ktp"),
            row.get("approved_limit"),
            row.get("application_xid"),
            row.get("last_education"),
            row.get("kin_name"),
            row.get("kin_mobile_phone"),
            row.get("home_status"),
            message,
        ]

    elif type == MF_ADJUST_LIMIT_KEY:
        return [
            row.get('application_xid'),
            row.get('limit_upgrading'),
            message
        ]


def mf_upload_csv_data_to_oss(
    upload_async_state, file_path=None, action_type=MF_DISBURSEMENT_KEY
):
    if file_path:
        local_file_path = file_path
    else:
        local_file_path = upload_async_state.file.path
    path_and_name, extension = os.path.splitext(local_file_path)
    file_name_elements = path_and_name.split('/')

    if action_type == MF_DISBURSEMENT_KEY:
        folder_name = 'mf_disbursement'
    elif action_type == MF_REGISTER_KEY:
        folder_name = 'mf_register'
    elif action_type == MF_ADJUST_LIMIT_KEY:
        folder_name = 'mf_adjust_limit'

    dest_name = "{}_{}/{}".format(folder_name, upload_async_state.id,
                                  file_name_elements[-1] + extension)
    upload_file_to_oss(settings.OSS_MEDIA_BUCKET, local_file_path, dest_name)

    if os.path.isfile(local_file_path):
        local_dir = os.path.dirname(local_file_path)
        upload_async_state.file.delete()
        if not file_path:
            os.rmdir(local_dir)

    upload_async_state.update_safely(url=dest_name)


def process_mf_customer_validate_bank(data, application):
    try:
        data_to_validate = {
            'bank_name': data['bank_name'],
            'account_number': data['account_number'],
            'name_in_bank': data['name_in_bank'],
            'name_bank_validation_id': None,
            'mobile_phone': data['mobile_phone'],
            'application': application
        }
        try:
            validation = trigger_name_in_bank_validation(data_to_validate, new_log=True)
        except Exception as e:
            logger.exception({
                'action': 'mf_process_validate_bank',
                'error': str(e)
            })

        validation_id = validation.get_id()
        validation.validate()
        validation_data = validation.get_data()
        is_success = False
        note = 'Name in Bank Validation Failed'
        if validation.is_success():
            application.update_safely(
                bank_account_number=validation_data['account_number'],
                name_in_bank=validation_data['validated_name'],
                name_bank_validation_id=validation_id
            )
            note = 'Name in Bank Validation Success via %s' % (validation_data['method'])
            is_success = True
        elif validation.is_failed():
            note = 'Name in Bank Validation Failed via %s' % (validation_data['method'])

        return is_success, note

    except Exception:
        return False, "Xfer timeout"


def register_mf_upload(upload_async_state: UploadAsyncState, partner: Partner) -> bool:
    upload_file = upload_async_state.file
    f = io.StringIO(upload_file.read().decode('utf-8'))
    reader = csv.DictReader(f, delimiter=',')
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
            write.writerow(MF_REGISTER_HEADERS)
            bank_names = BankManager.get_bank_names()

            field_flag = PartnershipFlowFlag.objects.filter(
                partner_id=partner.id,
                name=PartnershipFlag.FIELD_CONFIGURATION
            ).last()
            field_configs = {}
            if field_flag and field_flag.configs:
                field_configs = field_flag.configs

            for row in reader:
                is_success = True
                formatted_data = merchant_financing_register_format_data(row)
                serializer = MerchantFinancingUploadRegisterSerializer(
                    data=formatted_data,
                    context={'field_config': field_configs}
                )

                if serializer.is_valid():
                    if not (
                        partner.is_disbursement_to_partner_bank_account
                        or partner.is_disbursement_to_distributor_bank_account
                    ):
                        errors = {}
                        if not formatted_data['bank_account_number']:
                            msg = 'No rek bank Harus Diisi'
                            errors['bank_account_number'] = [msg]
                            is_success = False
                        if partner.is_email_send_to_customer and \
                                not check_email(formatted_data['email']):
                            msg = 'Alamat email Harus Diisi'
                            errors['email'] = [msg]
                            is_success = False
                        if formatted_data['bank_name'] not in bank_names:
                            msg = 'Nama Bank Harus Diisi'
                            errors['bank_name'] = [msg]
                            is_success = False

                        if not is_success:
                            is_success_all = False
                            write.writerow(
                                write_row_result(
                                    formatted_data,
                                    is_success,
                                    errors,
                                    type=MF_REGISTER_KEY
                                )
                            )
                            continue

                    # If field config false (optional), we can still upload but the field validations should still run.
                    # If it's invalid, we just don't read the fields
                    last_education_choices = [x[0].upper() for x in Application.LAST_EDUCATION_CHOICES]
                    home_status_choices = [x[0] for x in Application.HOME_STATUS_CHOICES]
                    additional_message = []

                    if not field_configs.get('last_education') and formatted_data['last_education']:
                        formatted_data['last_education'] = formatted_data['last_education'].upper()
                        if formatted_data['last_education'] not in last_education_choices:
                            additional_message.append(
                                'SUCCESS. Tapi pendidikan tidak sesuai, mohon isi sesuai master '
                                'SLTA,S1,SLTP,Diploma,S2,SD,S3'
                            )
                            formatted_data['last_education'] = ''

                    if not field_configs.get('home_status') and formatted_data['home_status']:
                        formatted_data['home_status'] = formatted_data['home_status'].capitalize()
                        if formatted_data['home_status'] not in home_status_choices:
                            additional_message.append(
                                "SUCCESS. Tapi status domisili tidak sesuai, mohon isi sesuai master "
                                "'Milik sendiri, lunas', Milik keluarga,Kontrak,'Milik sendiri, mencicil', "
                                "Mess karyawan,Kos,Milik orang tua"
                            )
                            formatted_data['home_status'] = ''

                    if not field_configs.get('kin_name') and formatted_data['kin_name']:
                        is_valid_kin_name, notes_kin_name = validate_kin_name(formatted_data['kin_name'])
                        if not is_valid_kin_name:
                            additional_message.append(
                                'SUCCESS. Tapi nama kontak darurat tidak sesuai, {}'.format(notes_kin_name)
                            )
                            formatted_data['kin_name'] = ''

                    if not field_configs.get('kin_mobile_phone') and formatted_data['kin_mobile_phone']:
                        is_valid_kin_mobile_phone, notes_kin_mobile_phone = validate_kin_mobile_phone(
                            formatted_data['kin_mobile_phone'],
                            formatted_data['close_kin_mobile_phone'],
                            formatted_data['mobile_phone_1']
                        )
                        if not is_valid_kin_mobile_phone:
                            additional_message.append(
                                'SUCCESS. Tapi nomor kontak darurat tidak sesuai, {}'.format(notes_kin_mobile_phone)
                            )
                            formatted_data['kin_mobile_phone'] = ''

                    # For efishery don't need to check Bank Name because we hardcoded it in the
                    # run_merchant_financing_upload_csv function
                    # For Rabando don't need to check Bank Name
                    customer_data = formatted_data.copy()
                    is_success, message = run_merchant_financing_upload_csv(
                        customer_data=customer_data, partner=partner
                    )
                    if is_success:
                        formatted_data["application_xid"] = message
                        message = "Success"

                        if additional_message:
                            message = ". ".join(additional_message)

                    else:
                        formatted_data["application_xid"] = ""
                        is_success_all = False

                    write.writerow(
                        write_row_result(
                            formatted_data,
                            is_success,
                            message,
                            type=MF_REGISTER_KEY
                        )
                    )

                else:
                    is_success_all = False
                    write.writerow(
                        write_row_result(
                            formatted_data,
                            is_success,
                            serializer.errors,
                            type=MF_REGISTER_KEY
                        )
                    )
        mf_upload_csv_data_to_oss(
            upload_async_state, file_path=file_path, action_type=MF_REGISTER_KEY
        )

    return is_success_all


def disburse_mf_upload(upload_async_state: UploadAsyncState, partner: Partner) -> bool:
    from juloserver.julo.banks import BankManager
    upload_file = upload_async_state.file
    f = io.StringIO(upload_file.read().decode('utf-8'))
    reader = csv.DictReader(f, delimiter=',')
    is_disburse_to_distributor = partner.is_disbursement_to_distributor_bank_account
    action_key = MF_DISBURSEMENT_KEY
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
            if partner.name == MerchantFinancingCSVUploadPartner.RABANDO:
                write.writerow(MF_DISBURSEMENT_RABANDO_HEADERS)
            else:
                write.writerow(MF_DISBURSEMENT_HEADERS)
            success_data = list()
            bank_names = BankManager.get_bank_names()
            for row in reader:
                clean_row = {key.lower().strip(): value for key, value in row.items()}
                try:
                    if is_disburse_to_distributor:
                        formatted_data = mf_disbursement_format_data(clean_row)
                    else:
                        formatted_data = merchant_financing_format_data(row, action_key)
                except KeyError as e:
                    is_success_all = False
                    write.writerow('Error some header not found', str(e))
                    break

                formatted_data["loan_duration_type"] = clean_row.get("tenor type")
                if str(formatted_data['application_xid']) in success_data:
                    is_success = False
                    message = 'Loan untuk Application XID {} sudah diajukan pada file ini'.format(formatted_data['application_xid'])
                    write.writerow(
                        write_row_result(
                            formatted_data,
                            is_success,
                            message,
                            partner_name=partner.name,
                        )
                    )
                    continue

                mfsp_nik = (
                    PartnershipCustomerData.objects.filter(
                        application_id__application_xid=formatted_data["application_xid"]
                    )
                    .values_list("nik", flat=True)
                    .last()
                )
                if mfsp_nik:
                    is_success_all = False
                    is_success = False
                    message = "NIK {} sudah dimigrasi pada platform MF standard".format(mfsp_nik)
                    write.writerow(
                        write_row_result(
                            formatted_data,
                            is_success,
                            message,
                            partner_name=partner.name,
                        )
                    )
                    continue

                application = (
                    Application.objects.filter(application_xid=formatted_data["application_xid"])
                    .exclude(product_line=ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT)
                    .last()
                )

                if is_disburse_to_distributor:
                    if str(formatted_data['bank_name']) not in bank_names:
                        is_success_all = True
                        is_success = False
                        message = 'Nama Bank Tidak Valid'
                        write.writerow(
                            write_row_result(
                                formatted_data,
                                is_success,
                                message,
                                partner_name=partner.name,
                            )
                        )
                        continue

                    serializer = MerchantFinancingDistburseSerializer(
                        data=formatted_data
                    )

                    if not serializer.is_valid():
                        is_success_all = True
                        is_success = False
                        error_list = serializer.errors.get('non_field_errors')
                        message = ', '.join(error_list)
                        write.writerow(
                            write_row_result(
                                formatted_data,
                                is_success,
                                message,
                                partner_name=partner.name,
                            )
                        )
                        continue

                    is_error = False
                    if not application:
                        is_error = True
                        message = 'Application tidak ditemukan'
                    elif not application.partner:
                        is_error = True
                        message = 'Invalid partner'
                    elif application.partner.name != MerchantFinancingCSVUploadPartner.RABANDO:
                        is_error = True
                        message = 'Invalid partner'
                    elif application.application_status_id != ApplicationStatusCodes.LOC_APPROVED:
                        is_error = True
                        message = 'Application status is not 190'
                    elif not application.account:
                        is_error = True
                        message = 'Account not found'
                    elif application.account.status_id \
                            not in {AccountConstant.STATUS_CODE.active,
                                    AccountConstant.STATUS_CODE.active_in_grace}:
                        is_error = True
                        message = 'Account inactive'

                    if is_error:
                        is_success_all = True
                        is_success = False
                        write.writerow(
                            write_row_result(
                                formatted_data,
                                is_success,
                                message,
                                partner_name=partner.name,
                            )
                        )
                        continue

                    csv_bank_account_number = formatted_data['bank_account_number']
                    csv_bank_name = formatted_data['bank_name']
                    csv_name_in_bank = formatted_data['name_in_bank']
                    csv_mobile_number = formatted_data['distributor_mobile_number']

                    bank = Bank.objects.filter(bank_name=csv_bank_name).first()
                    if not bank:
                        is_success = False
                        message = 'Nama Bank tidak ditemukan'
                        write.writerow(
                            write_row_result(
                                formatted_data,
                                is_success,
                                message,
                                partner_name=partner.name,
                            )
                        )
                        continue

                    bank_account_destination = BankAccountDestination.objects.filter(
                        account_number=application.bank_account_number,
                        customer=application.customer,
                        bank_account_category__category=BankAccountCategoryConst.SELF,
                    ).last()
                    validate_bank_data = {
                        'bank_name': csv_bank_name,
                        'account_number': csv_bank_account_number,
                        'name_in_bank': csv_name_in_bank,
                        'mobile_phone': csv_mobile_number,
                    }
                    is_success = True
                    if bank_account_destination:
                        name_bank_validation = bank_account_destination.name_bank_validation
                        is_same_account_number = (bank_account_destination.account_number == csv_bank_account_number)
                        is_same_bank_name = (True if bank and bank_account_destination.bank == bank else False)
                        is_same_name_bank_validation = (
                            name_bank_validation.account_number == csv_bank_account_number
                        )

                        if not is_same_account_number or not is_same_bank_name or not is_same_name_bank_validation:
                            is_success, message = proces_mf_customer_data(validate_bank_data, application)
                    else:
                        is_success, message = proces_mf_customer_data(validate_bank_data, application)

                    if not is_success:
                        is_success_all = True
                        write.writerow(
                            write_row_result(
                                formatted_data,
                                is_success,
                                message,
                                partner_name=partner.name,
                            )
                        )
                        continue

                # SEOJK Update -> max 3 platform checking
                if application:
                    is_error, message = max_3_platform_checking(application, partner)

                    if is_error:
                        is_success_all = True
                        is_success = False
                        write.writerow(
                            write_row_result(
                                formatted_data,
                                is_success,
                                message,
                                partner_name=partner.name,
                            )
                        )
                        continue

                is_success, message = disburse_mf_partner_customer(formatted_data, partner)
                write.writerow(
                    write_row_result(
                        formatted_data,
                        is_success,
                        message,
                        partner_name=partner.name,
                    )
                )

                if is_success:
                    success_data.append(str(formatted_data['application_xid']))
                else:
                    is_success_all = False

        mf_upload_csv_data_to_oss(upload_async_state, file_path=file_path)

    return is_success_all


def max_3_platform_checking(application, partner):
    is_error = False
    message = ""

    partnership_feature_setting = PartnershipFeatureSetting.objects.filter(
        feature_name=PartnershipFeatureNameConst.PARTNERSHIP_MAX_PLATFORM_CHECK_USING_FDC,
        is_active=True,
    ).first()

    if partnership_feature_setting and partner.is_csv_upload_applicable:
        parameters = partnership_feature_setting.parameters
        if is_apply_check_other_active_platforms_using_fdc(application.id, parameters, application):
            if not is_eligible_other_active_platforms(
                    application.id,
                    parameters['fdc_data_outdated_threshold_days'],
                    parameters['number_of_allowed_platforms'],
            ):
                is_error = True
                message = 'User has active loan on at least 3 other platforms'
    return is_error, message


def mf_standard_max_3_platform_check(application, partner):
    from juloserver.merchant_financing.web_app.non_onboarding.services import (
        mf_standard_fdc_inquiry_for_outdated_condition,
    )

    is_error = False
    message = ""

    partnership_feature_setting = PartnershipFeatureSetting.objects.filter(
        feature_name=PartnershipFeatureNameConst.PARTNERSHIP_MAX_PLATFORM_CHECK_USING_FDC,
        is_active=True,
    ).first()

    if partnership_feature_setting and partner.is_csv_upload_applicable:
        parameters = partnership_feature_setting.parameters
        if is_apply_check_other_active_platforms_using_fdc(application.id, parameters, application):
            outdated_threshold_days = parameters["fdc_data_outdated_threshold_days"]
            number_allowed_platforms = parameters["number_of_allowed_platforms"]
            if not is_eligible_other_active_platforms(
                application.id,
                outdated_threshold_days,
                number_allowed_platforms,
            ):
                is_error = True
                message = 'User has active loan on at least 3 other platforms'

            customer = application.customer
            is_eligible, is_outdated = check_eligible_and_out_date_other_platforms(
                customer.id,
                application.id,
                outdated_threshold_days,
                number_allowed_platforms,
            )
            if is_outdated:
                partnership_customer_data = application.partnership_customer_data
                fdc_inquiry = FDCInquiry.objects.create(
                    nik=partnership_customer_data.nik,
                    customer_id=customer.id,
                    application_id=application.id,
                )
                fdc_inquiry_data = {
                    "id": fdc_inquiry.id,
                    "nik": partnership_customer_data.nik,
                    "fdc_inquiry_id": fdc_inquiry.id,
                }
                params = {
                    "application_id": application.id,
                    "outdated_threshold_days": outdated_threshold_days,
                    "number_allowed_platforms": number_allowed_platforms,
                    "fdc_inquiry_api_config": parameters["fdc_inquiry_api_config"],
                }

                is_eligible = mf_standard_fdc_inquiry_for_outdated_condition(
                    fdc_inquiry_data, customer.id, params
                )
                if not is_eligible:
                    is_error = True
                    message = 'User has active loan on at least 3 other platforms'

    return is_error, message


def proces_mf_customer_data(validate_bank_data, application):
    from juloserver.portal.object.bulk_upload.services import (
        process_create_self_bank_account_destination,
    )
    is_success, message = process_mf_customer_validate_bank(validate_bank_data, application)
    if is_success:
        application.refresh_from_db()
        process_create_self_bank_account_destination(application)

    return is_success, message


def adjust_limit_mf_upload(upload_async_state: UploadAsyncState, partner: Partner) -> bool:
    upload_file = upload_async_state.file
    f = io.StringIO(upload_file.read().decode('utf-8'))
    reader = csv.DictReader(f, delimiter=',')
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
            write.writerow(MF_CSV_UPLOAD_ADJUST_LIMIT_HEADERS)
            success_data = list()

            for row in reader:
                is_success = True
                formatted_data = merchant_financing_adjust_limit_format_data(row)
                serializer = MerchantFinancingCSVUploadAdjustLimitSerializer(data=formatted_data)

                if serializer.is_valid():
                    if str(formatted_data['application_xid']) in success_data:
                        is_success = False
                        message = 'Adjust limit untuk Application XID {} sudah diajukan pada file ini'.format(
                            formatted_data['application_xid'])
                    else:
                        validated_data = serializer.validated_data
                        is_success, message = update_mf_customer_adjust_limit(
                            validated_data["application_xid"],
                            validated_data["limit_upgrading"],
                            partner
                        )

                        if is_success:
                            success_data.append(str(formatted_data['application_xid']))
                        else:
                            is_success_all = False

                    write.writerow(
                        write_row_result(
                            formatted_data,
                            is_success,
                            message,
                            type=MF_ADJUST_LIMIT_KEY
                        )
                    )

                else:
                    is_success_all = False
                    write.writerow(
                        write_row_result(
                            formatted_data,
                            is_success,
                            serializer.errors,
                            type=MF_ADJUST_LIMIT_KEY
                        )
                    )
        mf_upload_csv_data_to_oss(
            upload_async_state, file_path=file_path, action_type=MF_ADJUST_LIMIT_KEY
        )

    return is_success_all


def mf_generate_va_for_bank_bca(application):
    partner_app_data = application.partnershipapplicationdata_set.last()
    mobile_phone_1 = format_mobile_phone(
        partner_app_data.mobile_phone_1
    )
    product_line_code = str(application.product_line_code)

    prefix = settings.PREFIX_BCA
    suffix = "".join([product_line_code, mobile_phone_1])

    va_number = "".join([prefix, suffix])

    PaymentMethod.objects.create(
        payment_method_code=prefix,
        payment_method_name='Bank BCA',
        bank_code=BankCodes.BCA,
        customer=application.customer,
        is_shown=True,
        is_primary=True,
        virtual_account=va_number,
    )

    return


@transaction.atomic
def update_late_fee_amount_mf_std(payment_id: int) -> None:
    applied_dude_date = [5, 30, 60, 90, 120, 150, 180]
    payment = Payment.objects.filter(id=payment_id).select_related('loan').first()
    if not payment:
        logger.error(
            {
                "action": "update_late_fee_amount_mf_std",
                "message": "Failed to get payment object",
                "payment_id": payment_id,
            }
        )
        return

    if payment.status in PaymentStatusCodes.paid_status_codes():
        logger.warning(
            {
                "action": "update_late_fee_amount_mf_std",
                "message": "payment in paid status",
                "payment_id": payment_id,
            }
        )
        return

    if payment.due_late_days not in applied_dude_date:
        logger.info(
            {
                "action": "update_late_fee_amount_mf_std",
                "message": "not in due date to apply the late fee",
                "payment_id": payment_id,
            }
        )
        return

    merchant_financing_late_fee_fs = PartnershipFeatureSetting.objects.filter(
        feature_name=PartnershipFeatureNameConst.MERCHANT_FINANCING_LATE_FEE, is_active=True
    ).first()
    if not merchant_financing_late_fee_fs:
        logger.error(
            {
                "action": "update_late_fee_amount_mf_std",
                "message": "merchant_financing_late_fee is not active",
                "payment_id": payment_id,
            }
        )
        return

    parameters = merchant_financing_late_fee_fs.parameters
    product_lookup = payment.loan.product
    if parameters.get(str(payment.due_late_days)):
        late_fee_percentage = parameters.get(str(payment.due_late_days))
    else:
        late_fee_percentage = product_lookup.late_fee_pct

    today = date.today()
    due_late_days = relativedelta(date.today(), payment.due_date)
    due_amount_before = payment.due_amount
    old_late_fee_amount = payment.late_fee_amount
    late_fee = late_fee_percentage * payment.remaining_principal
    late_fee = py2round(late_fee, -2)
    payment.apply_late_fee(late_fee)
    payment.refresh_from_db()

    payment_event = PaymentEvent.objects.create(
        payment=payment,
        event_payment=-late_fee,
        event_due_amount=due_amount_before,
        event_date=today,
        event_type='late_fee',
    )
    account_payment = AccountPayment.objects.select_for_update().get(pk=payment.account_payment_id)
    account_payment.update_late_fee_amount(payment_event.event_payment)
    account_transaction, created = AccountTransaction.objects.get_or_create(
        account=account_payment.account,
        transaction_date=payment_event.event_date,
        transaction_type='late_fee',
        defaults={
            'transaction_amount': 0,
            'towards_latefee': 0,
            'towards_principal': 0,
            'towards_interest': 0,
            'accounting_date': payment_event.event_date,
        },
    )
    if created:
        account_transaction.transaction_amount = payment_event.event_payment
        account_transaction.towards_latefee = payment_event.event_payment
    else:
        account_transaction.transaction_amount += payment_event.event_payment
        account_transaction.towards_latefee += payment_event.event_payment

    account_transaction.save(update_fields=['transaction_amount', 'towards_latefee'])
    payment_event.account_transaction = account_transaction
    payment_event.save(update_fields=['account_transaction'])

    logger.info(
        {
            'action': 'update_late_fee_amount_mf_std',
            'message': 'success update late fee',
            'payment_id': payment.id,
            'due_late_days': due_late_days,
            'old_late_fee': old_late_fee_amount,
            'late_fee_amount_added': late_fee,
        }
    )


def merchant_financing_generate_auto_lender_agreement_document(loan_id):
    from juloserver.merchant_financing.tasks import (
        generate_mf_std_skrtp,
        merchant_financing_disbursement_process_task,
    )

    loan = Loan.objects.filter(id=loan_id).last()

    if not loan:
        logger.info(
            {
                'action': 'julo_one_auto_generate_lla_document',
                'message': 'Loan not found!!',
                'loan_id': loan_id,
            }
        )
        return

    lender = loan.lender
    if not lender:
        logger.info(
            {
                'action': 'julo_one_auto_generate_lla_document',
                'message': 'Lender not found!!',
                'loan_id': loan_id,
            }
        )
        return

    existing_lender_bucket = LenderBucket.objects.filter(
        total_approved=1,
        total_disbursement=loan.loan_disbursement_amount,
        total_loan_amount=loan.loan_amount,
        loan_ids__approved__contains=[loan_id],
    )
    if existing_lender_bucket:
        logger.info(
            {
                'action': 'julo_one_auto_generate_lla_document',
                'message': 'Lender bucket already created!!',
                'loan_id': loan_id,
                'lender_bucket_id': existing_lender_bucket.values_list('id', flat=True),
            }
        )
        return

    is_disbursed = False
    if loan.status >= LoanStatusCodes.CURRENT:
        is_disbursed = True

    action_time = timezone.localtime(timezone.now())
    use_fund_transfer = False

    # Handle axiata loan to define transaction time based on
    if loan.is_axiata_loan():
        if loan.fund_transfer_ts:
            action_time = loan.fund_transfer_ts
        else:
            action_time = loan.cdate

        use_fund_transfer = True

    lender_bucket = LenderBucket.objects.create(
        partner_id=lender.user.partner.id,
        total_approved=1,
        total_rejected=0,
        total_disbursement=loan.loan_disbursement_amount,
        total_loan_amount=loan.loan_amount,
        loan_ids={"approved": [loan_id], "rejected": []},
        is_disbursed=is_disbursed,
        is_active=False,
        action_time=action_time,
        action_name='Disbursed',
        lender_bucket_xid=generate_lenderbucket_xid(),
    )

    # generate summary lla
    assign_lenderbucket_xid_to_lendersignature(
        [loan_id], lender_bucket.lender_bucket_xid, is_loan=True
    )
    generate_summary_lender_loan_agreement.delay(lender_bucket.id, use_fund_transfer)

    # cache lender bucket xid for getting application past in lender dashboard
    redis_cache = RedisCacheLoanBucketXidPast()
    redis_cache.set(loan_id, lender_bucket.lender_bucket_xid)

    if loan.is_mf_std_loan():
        generate_mf_std_skrtp.delay(loan.id)
        merchant_financing_disbursement_process_task.delay(loan.id)


def mfsp_disbursement_pg_service(loan_id) -> str:
    from juloserver.julo.services2.client_paymet_gateway import ClientPaymentGateway

    try:
        with transaction.atomic():
            loan = Loan.objects.select_for_update().filter(id=loan_id).last()
            if not loan:
                return "loan not found"
            if loan.loan_status.status_code != LoanStatusCodes.FUND_DISBURSAL_ONGOING:
                return "invalid loan status"
            if loan.disbursement_id:
                return "this loan already has a disbursement_id"
            application = loan.get_application
            if not application:
                return "application not found"
            bank_account_destination = loan.bank_account_destination
            if not bank_account_destination:
                return "bank_account_destination not found"
            name_bank_validation = bank_account_destination.name_bank_validation

            client_pg = ClientPaymentGateway(
                client_id=settings.PARTNERSHIP_PAYMENT_GATEWAY_CLIENT_ID,
                api_key=settings.PARTNERSHIP_PAYMENT_GATEWAY_API_KEY,
            )
            if not name_bank_validation:
                partnership_trigger_process_validate_bank(application.id)
                application.refresh_from_db()
                if (
                    not application.name_bank_validation
                    or application.name_bank_validation != NameBankValidationStatus.SUCCESS
                ):
                    return "name_bank_validation failed"
                name_bank_validation = application.name_bank_validation

            disbursement = Disbursement.objects.create(
                disbursement_type=PartnershipDisbursementType.LOAN,
                name_bank_validation=name_bank_validation,
                amount=loan.loan_disbursement_amount,
                method=name_bank_validation.method,
                original_amount=loan.loan_amount,
                external_id=loan.id,
                step=0,
            )
            update_fields = [
                'disbursement_type',
                'name_bank_validation',
                'amount',
                'original_amount',
                'external_id',
                'step',
            ]
            disbursement.create_history('create', update_fields)
            Disbursement2History.objects.create(
                disbursement=disbursement,
                amount=disbursement.amount,
                method=disbursement.method,
                disburse_status=disbursement.disburse_status,
                step=disbursement.step,
            )

            callback_url = "/api/merchant-financing/v1/pg-service/callback/transfer-result"
            req_pg_transfer = {
                "object_transfer_id": loan.id,
                "object_transfer_type": disbursement.disbursement_type,
                "bank_account": name_bank_validation.account_number,
                "bank_id": loan.bank_account_destination.bank.id,
                "bank_account_name": name_bank_validation.validated_name,
                "amount": loan.loan_disbursement_amount,
                "callback_url": settings.BASE_URL + callback_url,
            }

            req_ts = timezone.localtime(datetime.now())
            resp_pg_transfer = client_pg.disbursement_transfer_bank(loan.id, req_pg_transfer)
            res_ts = timezone.localtime(datetime.now())

            if resp_pg_transfer.get("success"):
                disbursement.disburse_status = DisbursementStatus.PENDING
                disbursement.reason = "Transfer request is success, waiting for callback result"
            else:
                disbursement_reason = "Transfer request got error response "
                errs = resp_pg_transfer.get("data").get("errors")
                if errs:
                    disbursement_reason += str(errs)

                disbursement.disburse_status = DisbursementStatus.FAILED
                disbursement.reason = disbursement_reason
                julo_one_loan_disbursement_failed(loan)

            disbursement.step = 1
            disbursement.disburse_id = (
                resp_pg_transfer.get("data").get("data").get("transaction_id")
            )
            disbursement.save(update_fields=['step', 'disburse_id', 'disburse_status', 'reason'])
            disbursement.create_history('update', ['disburse_status', 'reason'])
            Disbursement2History.objects.create(
                disbursement=disbursement,
                amount=disbursement.amount,
                method=disbursement.method,
                idempotency_id=disbursement.disburse_id,
                disburse_status=disbursement.disburse_status,
                reason=disbursement.reason,
                step=disbursement.step,
                transaction_request_ts=req_ts,
                transaction_response_ts=res_ts,
                attempt=0,
            )

            loan.disbursement_id = disbursement.id
            loan.save(update_fields=['disbursement_id'])

    except Exception as e:
        return "Error Exception - {}".format(str(e))


def process_callback_transfer_result(transaction_id, status) -> str:
    with transaction.atomic():
        err_msg = ""
        disbursement = (
            Disbursement.objects.select_for_update().filter(disburse_id=transaction_id).last()
        )
        if not disbursement:
            err_msg = "disbursement not found"
        if disbursement.disburse_status != DisbursementStatus.PENDING:
            err_msg = "disbursement status not pending"

        loan = Loan.objects.filter(disbursement_id=disbursement.id).first()
        if not loan:
            err_msg = "loan not found"
        if loan.status != LoanStatusCodes.FUND_DISBURSAL_ONGOING:
            err_msg = "invalid loan status"

        if not err_msg and status == TransferProcessStatus.SUCCESS.value:
            julo_one_loan_disbursement_success(loan)
            disbursement.disburse_status = DisbursementStatus.COMPLETED
            disbursement.reason = "callback result success"
        else:
            julo_one_loan_disbursement_failed(loan)
            disbursement.disburse_status = DisbursementStatus.FAILED
            disbursement.reason = "callback result failed"
            if err_msg:
                disbursement.reason = "callback result failed - {}".format(err_msg)

        disbursement.step = 2
        disbursement.save(update_fields=['step', 'disburse_status', 'reason'])
        disbursement.create_history('update', ['disburse_status', 'reason'])
        Disbursement2History.objects.create(
            disbursement=disbursement,
            amount=disbursement.amount,
            method=disbursement.method,
            idempotency_id=transaction_id,
            disburse_status=disbursement.disburse_status,
            reason=disbursement.reason,
            step=disbursement.step,
            attempt=0,
        )

        return err_msg
