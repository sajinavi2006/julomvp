from __future__ import print_function

import json
import logging
import re
import sys
import time
from builtins import object, range, str
from datetime import date, datetime, timedelta
from operator import itemgetter
from juloserver.customer_module.services.customer_related import (
    get_ongoing_account_deletion_request,
)

import pyotp
from babel.dates import format_date
from cuser.middleware import CuserMiddleware
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.auth import authenticate

# from django.contrib.auth.models import User
from django.core.exceptions import MultipleObjectsReturned, ObjectDoesNotExist
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.db import DatabaseError, transaction
from django.db.models import Q, Sum
from django.db.utils import IntegrityError
from django.forms.models import model_to_dict
from django.http import StreamingHttpResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from oauth2client import client as oauth2_client
from rest_framework import generics
from rest_framework.exceptions import APIException
from rest_framework.generics import UpdateAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.status import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_400_BAD_REQUEST,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
)
from rest_framework.views import APIView
from rest_framework.viewsets import ViewSet

from juloserver.customer_module.constants import disabled_feature_setting_account_deletion
from juloserver.ana_api.models import EtlRepeatStatus
from juloserver.androidcard.services import get_android_card_from_database
from juloserver.apiv1.exceptions import ResourceNotFound, ResourceWithDetailNotFound
from juloserver.apiv1.filters import ApplicationFilter
from juloserver.apiv1.serializers import (
    ApplicationSerializer,
    CustomerSerializer,
    FacebookDataSerializer,
    PartnerReferralSerializer,
    ProductLineSerializer,
    VoiceRecordHyperSerializer,
)

# hide Julo Mini to remove STL remove STL product from APP for google rules
# from ..apiv1.services import render_julomini_card
from juloserver.apiv1.services import (
    render_account_summary_cards,
    render_campaign_card,
    render_loan_sell_off_card,
    render_season_card,
    render_sphp_card,
)
from juloserver.apiv2.constants import (
    ErrorCode,
    ErrorMessage,
    PromoType,
    DropdownResponseCode,
)
from juloserver.apiv2.models import AutoDataCheck, EtlStatus, FinfiniStatus
from juloserver.apiv2.serializers import (
    AdditionalInfoSerializer,
    ApplicationUpdateSerializer,
    BankApplicationSerializer,
    CashbackSepulsaSerializer,
    CashbackTransferSerializer,
    ChangeEmailSerializer,
    ChangePasswordSerializer,
    CreditScoreSerializer,
    FacebookDataCreateUpdateSerializer,
    FAQItemsSerializer,
    FAQSerializer,
    JULOContactSerializer,
    Login2Serializer,
    LoginSerializer,
    OtpRequestSerializer,
    OtpValidationSerializer,
    ReapplySerializer,
    RegisterUserSerializer,
    RegisterV2Serializer,
    SepulsaInqueryElectricitySerializer,
    SepulsaProductListSerializer,
    SkipTraceSerializer,
    SubmitProductSerializer,
    UserFeedbackSerializer,
    HelpCenterSerializer,
    HelpCenterItemsSerializer,
    FormAlertMessageSerializer,
)
from juloserver.apiv2.services import (
    add_facebook_data,
    check_application,
    check_fraud_model_exp,
    check_payslip_mandatory,
    create_bank_validation_card,
    determine_product_line_v2,
    get_credit_score1,
    get_credit_score3,
    get_customer_app_actions,
    get_device_app_actions,
    get_last_application,
    get_latest_app_version,
    get_product_lines,
    get_referral_home_content,
    store_device_geolocation,
    switch_to_product_default_workflow,
    update_facebook_data,
    update_response_false_rejection,
    update_response_fraud_experiment,
    get_countdown_suspicious_domain_from_feature_settings,
    is_otp_validated,
    modify_change_phone_number_related_response,
)
from juloserver.apiv2.tasks import (
    generate_address_from_geolocation_async,
    populate_zipcode,
    record_payment_detail_page_access_history,
)
from juloserver.apiv2.utils import (
    application_have_facebook_data,
    failure_template,
    get_type_transaction_sepulsa_product,
    success_template,
    mask_fullname_each_word,
)
from juloserver.application_flow.services import (
    is_active_julo1,
    is_experiment_application,
    is_suspicious_domain,
)
from juloserver.application_flow.tasks import (
    fraud_bpjs_or_bank_scrape_checking,
    move_application_to_x133_for_blacklisted_device,
    move_application_to_x133_for_suspicious_email,
    suspicious_hotspot_app_fraud_check_task,
)
from juloserver.boost.services import add_boost_button_and_message
from juloserver.cashback.constants import (
    CASHBACK_FROZEN_MESSAGE,
    CashbackChangeReason,
    CashbackMethodName,
)
from juloserver.cfs.services.core_services import (
    get_cfs_transaction_note,
    get_customer_tier_info,
)
from juloserver.disbursement.services.gopay import GopayConst
from juloserver.followthemoney.constants import LoanAgreementType
from juloserver.followthemoney.models import LenderBucket, LoanAgreementTemplate
from juloserver.followthemoney.tasks import (
    generate_sphp,
    generate_summary_lender_loan_agreement,
)
from juloserver.google_analytics.constants import GAEvent
from juloserver.google_analytics.tasks import send_event_to_ga_task_async
from juloserver.julo.banks import BankManager
from juloserver.julo.clients import (
    get_julo_bri_client,
    get_julo_digisign_client,
    get_julo_sentry_client,
)
from juloserver.julo.clients.constants import DigisignResultCode
from juloserver.julo.clients.sepulsa import SepulsaResponseCodes
from juloserver.julo.constants import (
    CashbackTransferConst,
    CollateralDropdown,
    ExperimentConst,
    FeatureNameConst,
    SPHPConst,
    VendorConst,
    OnboardingIdConst,
    MobileFeatureNameConst,
    IdentifierKeyHeaderAPI,
)
from juloserver.julo.exceptions import (
    DuplicateCashbackTransaction,
    JuloException,
    SmsNotSent,
    BlockedDeductionCashback,
)
from juloserver.julo.models import (
    PTP,
    AddressGeolocation,
    Application,
    ApplicationExperiment,
    ApplicationHistory,
    ApplicationScrapeAction,
    AppVersion,
    AwsFaceRecogLog,
    BankApplication,
    CashbackTransferTransaction,
    CenterixCallbackResults,
    CreditScore,
    Customer,
    CustomerAppAction,
    CustomerFieldChange,
    CustomerWalletHistory,
    Device,
    DigisignConfiguration,
    Document,
    Experiment,
    FaceRecognition,
    FaqItem,
    FaqSection,
    FeatureSetting,
    FrontendView,
    Image,
    JuloContactDetail,
    KycRequest,
    Loan,
    Mantri,
    MobileFeatureSetting,
    MobileOperator,
    OtpRequest,
    PartnerReferral,
    Payment,
    PaymentMethod,
    PaymentNote,
    ProductLine,
    ReferralSystem,
    ScrapingButton,
    SepulsaProduct,
    SignatureMethodHistory,
    Skiptrace,
    SkiptraceHistory,
    SkiptraceHistoryCentereix,
    SkiptraceResultChoice,
    SmsHistory,
    StatusLabel,
    VoiceRecord,
    Workflow,
    PaymentMethodLookup,
    HelpCenterItem,
    HelpCenterSection,
    FormAlertMessageConfig,
    WarningLetterHistory,
    PaymentDetailUrlLog,
    AuthUser as User,
)
from juloserver.julo.models import UserFeedback as UserFeedbackModel
from juloserver.julo.partners import PartnerConstant
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services import (
    get_sphp_template,
    is_bank_name_validated,
    link_to_partner_by_product_line,
    link_to_partner_if_exists,
    prevent_web_login_cases_check,
    process_application_status_change,
    ptp_create,
    update_customer_data,
)
from juloserver.julo.services2 import (
    get_cashback_redemption_service,
    get_customer_service,
    encrypt,
)
from juloserver.julo.services2.cashback import (
    ERROR_MESSAGE_TEMPLATE_1,
    ERROR_MESSAGE_TEMPLATE_2,
    ERROR_MESSAGE_TEMPLATE_3,
    ERROR_MESSAGE_TEMPLATE_4,
    ERROR_MESSAGE_TEMPLATE_5,
    CashbackRedemptionService,
    SepulsaService,
)
from juloserver.julo.services2.digisign import (
    is_digisign_feature_active,
    is_digisign_web_browser,
)
from juloserver.julo.statuses import (
    ApplicationStatusCodes,
    LoanStatusCodes,
    PaymentStatusCodes,
)
from juloserver.julo.tasks import create_application_checklist_async, send_sms_otp_token
from juloserver.julo.tasks2.application_tasks import send_deprecated_apps_push_notif
from juloserver.julo.utils import (
    display_rupiah,
    email_blacklisted,
    format_e164_indo_phone_number,
    get_file_from_oss,
    redirect_post_to_anaserver,
    verify_nik,
)
from juloserver.julo.workflows2.tasks import (
    create_application_original_task,
    signature_method_history_task,
    upload_sphp_from_digisign_task,
)
from juloserver.julolog.julolog import JuloLog
from juloserver.line_of_credit.services import LineOfCreditService
from juloserver.minisquad.tasks import trigger_insert_col_history
from juloserver.pin.services import (
    CustomerPinChangeService,
    alert_suspicious_login_to_user,
    does_user_have_pin,
    get_customer_nik,
    get_device_model_name,
    is_blacklist_android,
)
from juloserver.promo.models import PromoHistory
from juloserver.referral.services import (
    get_total_referral_invited_and_total_referral_benefits,
    show_referral_code,
)
from juloserver.standardized_api_response.mixin import (
    StandardizedExceptionHandlerMixin,
    StandardizedExceptionHandlerMixinV2,
)
from juloserver.standardized_api_response.utils import (
    success_response,
    general_error_response,
    not_found_response,
)
from juloserver.account_payment.models import AccountPayment
from juloserver.pii_vault.constants import PiiSource
from juloserver.pii_vault.services import detokenize_for_model_object

from .credit_matrix2 import messages
from .services import can_reapply_validation
from .services2.promo import create_june2022_promotion_card
from .services2.dropdown import generate_dropdown_data
from .utils import CustomExceptionHandlerMixin, response_failed
from juloserver.account_payment.services.account_payment_related import (
    get_potential_cashback_for_crm,
)
from ..cashback.services import is_cashback_method_active, determine_cashback_faq_experiment
from juloserver.account_payment.services.earning_cashback import get_paramters_cashback_new_scheme
from juloserver.fraud_score.serializers import fetch_android_id
from juloserver.autodebet.services.account_services import process_tnc_message_with_deduction_day
from juloserver.apiv4.constants import ListOfApplicationSerializers
from juloserver.apiv4.services.application_service import check_and_storing_location
from juloserver.application_form.services.application_service import (
    is_user_offline_activation_booth,
)
from juloserver.minisquad.services2.dialer_related import (
    get_uninstall_indicator_from_moengage_by_customer_id,
)
from juloserver.julo.services2.payment_method import filter_payment_methods_by_lender
from juloserver.pin.decorators import parse_device_ios_user
from juloserver.application_flow.models import HsfbpIncomeVerification

logger = JuloLog(__name__)
julo_sentry_client = get_julo_sentry_client()
cashback_redemption_service = get_cashback_redemption_service()


class GetUserOwnedQuerySetMixin(object):
    def get_queryset(self):
        user = self.request.user
        return self.__class__.model_class.objects.filter(customer=user.customer)


class UserOwnedListCreateView(GetUserOwnedQuerySetMixin, generics.ListCreateAPIView):
    # To be set by the child class
    model_class = None

    def perform_create(self, serializer):
        user = self.request.user
        serializer.save(customer=user.customer)


class ApplicationListCreateView(UserOwnedListCreateView):
    """
    API endpoint that allows current user's applications to be submitted and
    listed.
    """

    model_class = Application
    serializer_class = ApplicationSerializer
    filter_class = ApplicationFilter

    def perform_create(self, serializer):
        customer = self.request.user.customer
        device_id = self.request.data.get('device_id')
        web_version = self.request.data.get('web_version', None)
        app_version = self.request.data.get('app_version', None)
        if not app_version and not web_version:
            app_version = get_latest_app_version()
        device = None

        if not can_reapply_validation(customer):
            logger.warning(
                {
                    'message': 'creating application when can_reapply_validation is false',
                    'customer_id': customer.id,
                }
            )

        if device_id:
            device = Device.objects.get_or_none(id=device_id, customer=customer)
            if device is None:
                raise ResourceNotFound(resource_id=device_id)

        if 'application_number' in self.request.data:
            application_number = self.request.data.get('application_number')
            submitted_application = (
                Application.objects.regular_not_deletes()
                .filter(customer=customer, application_number=application_number)
                .first()
            )
            if submitted_application is not None:
                logger.warning(
                    {
                        'status': 'application_already_submitted',
                        'message': 'do_nothing',
                        'application_number': application_number,
                        'customer': customer,
                    }
                )
                return
        application = serializer.save(
            customer=customer, device=device, app_version=app_version, web_version=web_version
        )
        send_deprecated_apps_push_notif.delay(application.id, app_version)
        logger.info(
            {
                'message': 'Form success created',
                'status': 'form_created',
                'application': application,
                'customer': customer,
                'device': device,
            }
        )

        # Set mantri id if referral code is a mantri id
        referral_code = self.request.data.get('referral_code', None)
        if referral_code:
            referral_code = referral_code.replace(' ', '')
            mantri_obj = Mantri.objects.get_or_none(code__iexact=referral_code)
            application.mantri = mantri_obj
            application.save(update_fields=['mantri'])

        # set partner reapply
        link_to_partner_if_exists(application)

        process_application_status_change(
            application.id, ApplicationStatusCodes.FORM_CREATED, change_reason='customer_triggered'
        )

        create_application_checklist_async.delay(application.id)
        self.application = application


class ApplicationUpdate(UpdateAPIView):
    serializer_class = ApplicationUpdateSerializer

    def get_queryset(self):
        return self.request.user.customer.application_set.regular_not_deletes()

    def check_job_and_company_phone(self):
        phone_number = self.request.data.get('company_phone_number', None)
        job_type = self.request.data.get('job_type', None)
        salaried = ['Pegawai swasta', 'Pegawai negeri']
        if job_type in salaried and phone_number[0:2] == '08':
            return False

        return True

    @julo_sentry_client.capture_exceptions
    def check_allowed_onboarding(self, onboarding_id):
        """
        Verify data onboarding_id if exist on payload
        """

        try:
            if onboarding_id:
                onboarding_id = int(onboarding_id)
        except ValueError as error:
            logger.error(str(error))
            raise JuloException(str(error))

        if (
            self.serializer_class.__name__ == 'ApplicationSerializer'
            and onboarding_id != OnboardingIdConst.SHORTFORM_ID
        ):
            return False
        elif (
            self.serializer_class.__name__ == 'ApplicationUpdateSerializerV3'
            and onboarding_id
            not in [
                OnboardingIdConst.LONGFORM_ID,
                OnboardingIdConst.LONGFORM_SHORTENED_ID,
                OnboardingIdConst.LFS_REG_PHONE_ID,
                OnboardingIdConst.LF_REG_PHONE_ID,
                OnboardingIdConst.LFS_SPLIT_EMERGENCY_CONTACT,
            ]
        ):
            return False

        return True

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        # validate OTP
        if not is_otp_validated(instance, serializer.validated_data.get('mobile_phone_1')):
            return general_error_response(ErrorMessage.PHONE_NUMBER_MISMATCH)

        if instance.partner and instance.partner.name == 'klop':
            if serializer.validated_data.get('latitude') and serializer.validated_data.get(
                'longitude'
            ):
                try:
                    address_geolocation = instance.addressgeolocation
                    address_geolocation.update_safely(
                        latitude=serializer.validated_data.get('latitude'),
                        longitude=serializer.validated_data.get('longitude'),
                    )
                except AddressGeolocation.DoesNotExist:
                    address_geolocation = AddressGeolocation.objects.create(
                        application=instance,
                        latitude=serializer.validated_data.get('latitude'),
                        longitude=serializer.validated_data.get('longitude'),
                    )

                generate_address_from_geolocation_async.delay(address_geolocation.id)
                store_device_geolocation(
                    instance.customer,
                    latitude=serializer.validated_data.get('latitude'),
                    longitude=serializer.validated_data.get('longitude'),
                )
            else:
                return Response(
                    status=HTTP_400_BAD_REQUEST,
                    data={'message': 'Latitude and Longitude is required'},
                )

        self.claim_customer(instance, request.data)
        if not self.check_job_and_company_phone():
            job_type = self.request.data.get('job_type', None)
            message = 'Jika pekerjaan ' + job_type + ', nomor telepon kantor tidak boleh GSM'
            error = APIException(format(str(message)))
            error.status_code = 400
            raise error
        self.perform_update(serializer)
        return Response(serializer.data)

    def determine_onboarding(self, application, longform_shortened):
        """
        For define onboarding_id is:
        1 -> LongForm
        2 -> Shortform
        3 -> LongForm Shortened

        This logic, also to handle issue Downgrade APK
        Refer:
        https://juloprojects.atlassian.net/browse/RUS1-1197
        """

        # check and update if onboarding is None after register
        current_onboarding_id = application.onboarding_id

        if application.is_julo_one_ios():
            return current_onboarding_id

        # Condition for onboarding_id 4 and 5
        if current_onboarding_id in [
            OnboardingIdConst.LF_REG_PHONE_ID,
            OnboardingIdConst.LFS_REG_PHONE_ID,
            OnboardingIdConst.JULO_360_EXPERIMENT_ID,
            OnboardingIdConst.LFS_SPLIT_EMERGENCY_CONTACT,
            OnboardingIdConst.JULO_360_J1_ID,
            OnboardingIdConst.JULO_360_TURBO_ID,
        ]:
            logger.warning(
                {
                    "message": "Verify onboarding_id by data submission",
                    "old_onboarding": current_onboarding_id,
                    "new_onboarding": current_onboarding_id,
                    "application": application.id,
                }
            )
            return current_onboarding_id

        # default value for longform
        onboarding_id = 1

        # shortform use ApplicationSerializer
        if self.serializer_class.__name__ == ListOfApplicationSerializers.AppSerializer:
            onboarding_id = 2
        elif (
            self.serializer_class.__name__ in ListOfApplicationSerializers.AllowedSerializerForLFS
            and longform_shortened
        ):
            onboarding_id = 3

        logger.warning(
            {
                "message": "Verify onboarding_id by data submission",
                "old_onboarding": current_onboarding_id,
                "new_onboarding": onboarding_id,
                "application": application.id,
            }
        )

        return onboarding_id

    def perform_update(self, serializer, longform_shortened=False, app_version=None, customer=None):
        mother_maiden_name = self.request.data.get('mother_maiden_name', None)
        is_upgrade = self.request.data.get('is_upgrade', None)
        name_in_bank = self.request.data.get('name_in_bank', None)
        latitude = self.request.data.get('latitude', None)
        longitude = self.request.data.get('longitude', None)
        address_latitude = self.request.data.get('address_latitude', None)
        address_longitude = self.request.data.get('address_longitude', None)
        application = serializer._args[0]
        detokenized_applications = detokenize_for_model_object(
            PiiSource.APPLICATION,
            [
                {
                    'customer_xid': application.customer.customer_xid,
                    'object': application,
                }
            ],
            force_get_local_data=True,
        )
        application = detokenized_applications[0]
        incoming_status = application.status
        onboarding_id = self.determine_onboarding(application, longform_shortened)
        monthly_housing_cost = serializer.validated_data.get('monthly_housing_cost')
        application_serializer = self.serializer_class.__name__

        if incoming_status == ApplicationStatusCodes.FORM_CREATED:
            application_update_data = {'onboarding_id': onboarding_id}
            if app_version:
                application_update_data['app_version'] = app_version
            if 'referral_code' in serializer.initial_data:
                referral_code = serializer.initial_data['referral_code'].replace(' ', '')

                # offline activation booth condition
                # check if have referral code and set path tag
                is_user_offline_activation_booth(referral_code, application.id)

                mantri_obj = Mantri.objects.get_or_none(code__iexact=referral_code)
                if mantri_obj:
                    application_update_data['mantri_id'] = mantri_obj.id
            if not name_in_bank and not is_upgrade:
                fullname = self.request.data.get('fullname')
                application_update_data['name_in_bank'] = (
                    fullname if fullname is not None else application.fullname
                )
            if monthly_housing_cost:
                application_update_data['monthly_housing_cost'] = max(0, int(monthly_housing_cost))

            # For LongForm Shortened field `dependent` is not shown.
            # We need to set None for that field.
            if longform_shortened:
                application_update_data['dependent'] = None

            with transaction.atomic():
                application = serializer.save(**application_update_data)

            customer = customer if customer else self.request.user.customer
            if mother_maiden_name:
                customer.update_safely(mother_maiden_name=mother_maiden_name, refresh=False)

            # modify populate_zipcode to sync since it became intermitent delay
            # between ana server and application table when generate score
            populate_zipcode(application)
            change_reason = (
                'dibantu_agent'
                if application_serializer
                == ListOfApplicationSerializers.AgentAssistedSubmissionSerializer
                else 'customer_triggered'
            )
            process_application_status_change(
                application.id,
                ApplicationStatusCodes.FORM_PARTIAL,
                change_reason=change_reason,
            )
            application.refresh_from_db()
            detokenized_applications = detokenize_for_model_object(
                PiiSource.APPLICATION,
                [
                    {
                        'customer_xid': application.customer.customer_xid,
                        'object': application,
                    }
                ],
                force_get_local_data=True,
            )
            application = detokenized_applications[0]

            # upgrade case account status x431 to x410
            from juloserver.account.services.account_related import process_change_account_status
            from juloserver.account.constants import AccountConstant

            account = application.account
            if (
                is_upgrade
                and account
                and account.status_id == AccountConstant.STATUS_CODE.deactivated
            ):
                process_change_account_status(
                    account,
                    AccountConstant.STATUS_CODE.inactive,
                    change_reason='turbo upgrade to j1',
                )

            # separate function to check and generate location
            # only available on version 4
            if application_serializer == ListOfApplicationSerializers.AppSerializerV4:
                check_and_storing_location(
                    application_id=application.id,
                    latitude=latitude,
                    longitude=longitude,
                    address_latitude=address_latitude,
                    address_longitude=address_longitude,
                )

            suspicious_hotspot_app_fraud_check_task.delay(application.id)
            send_deprecated_apps_push_notif.delay(application.id, application.app_version)
            android_id = fetch_android_id(application.customer)
            is_fraudster = is_blacklist_android(android_id)
            if is_fraudster:
                move_application_to_x133_for_blacklisted_device.apply_async(
                    (application.id,), countdown=86400
                )

            suspicious_domain = is_suspicious_domain(application.email)
            if application.product_line_id == ProductLineCodes.J1 and suspicious_domain:
                countdown = get_countdown_suspicious_domain_from_feature_settings(
                    feature_name='suspicious_domain_delay_time'
                )
                move_application_to_x133_for_suspicious_email.apply_async(
                    (application.id,), countdown=countdown
                )

            other_app = Application.objects.filter(
                application_status=ApplicationStatusCodes.FORM_CREATED,
                customer_id=application.customer,
            ).last()
            if other_app:
                process_application_status_change(
                    other_app.id,
                    ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
                    change_reason='J1_App_Submitted',
                )

        elif incoming_status == ApplicationStatusCodes.FORM_PARTIAL:
            try:
                product_line = determine_product_line_v2(
                    self.request.user.customer,
                    serializer.validated_data['product_line'].product_line_code,
                    serializer.validated_data['loan_duration_request'],
                )
            except KeyError as e:
                error = APIException('{}: this field is required on 110'.format(str(e)))
                error.status_code = 400
                raise error

            application = serializer.save(product_line__product_line_code=product_line)
            detokenized_applications = detokenize_for_model_object(
                PiiSource.APPLICATION,
                [
                    {
                        'customer_xid': application.customer.customer_xid,
                        'object': application,
                    }
                ],
                force_get_local_data=True,
            )
            application = detokenized_applications[0]
            customer = self.request.user.customer
            customer.fullname = application.fullname
            customer.phone = application.mobile_phone_1
            if mother_maiden_name:
                customer.mother_maiden_name = mother_maiden_name
            customer.save()
            if not name_in_bank and not is_upgrade:
                application.name_in_bank = application.fullname

            application.update_safely(onboarding_id=onboarding_id, refresh=False)

            link_to_partner_by_product_line(application)
            if application.product_line.product_line_code != product_line:
                application.product_line = ProductLine.objects.get(pk=product_line)
                application.save()
            populate_zipcode.delay(application.id)

            process_application_status_change(
                application.id,
                ApplicationStatusCodes.FORM_SUBMITTED,
                change_reason='customer_triggered',
            )
            send_deprecated_apps_push_notif.delay(application.id, application.app_version)
            android_id = fetch_android_id(application.customer)
            is_fraudster = is_blacklist_android(android_id)
            if is_fraudster:
                move_application_to_x133_for_blacklisted_device.apply_async(
                    (application.id,), countdown=86400
                )

        else:
            return

    @staticmethod
    def claim_customer(application, request_data):
        """
        When customer goes to change the apk, from old to new one, or from new to old one in the
        middle of registration it will make an trash data. So we must claim the trash data into
        new one.
        """

        from juloserver.application_form.services import ClaimError

        application_customer = application.customer

        try:
            from juloserver.application_form.services.claimer_service import (
                ClaimerService,
            )

            detokenized_customer = detokenize_for_model_object(
                PiiSource.CUSTOMER,
                [
                    {
                        'customer_xid': application_customer.customer_xid,
                        'object': application_customer,
                    }
                ],
                force_get_local_data=True,
            )
            application_customer = detokenized_customer[0]

            ClaimerService(customer=application_customer).claim_using(
                phone=request_data.get('mobile_phone_1')
            ).on_module(sys.modules[__name__])

        except ClaimError as e:
            message = e.message if hasattr(e, 'message') else e
            logging.error(
                {
                    'mark': 'ClaimError',
                    'application_id': application.id,
                    'customer_id': application_customer.id,
                    'message': message,
                }
            )


class BankApplicationCreate(APIView):
    def post(self, request, application_id):
        application = Application.objects.get_or_none(pk=application_id)
        if not application:
            return Response(
                status=HTTP_404_NOT_FOUND, data={'not_found_application': application_id}
            )
        user = self.request.user

        if user.id != application.customer.user_id:
            return Response(
                status=HTTP_403_FORBIDDEN, data={'errors': 'User not allowed', 'user_id': user.id}
            )

        data = request.data.copy()
        data['application'] = application.id
        serializer = BankApplicationSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(status=HTTP_201_CREATED, data=serializer.data)

    def get(self, request, application_id):
        application = Application.objects.get_or_none(pk=application_id)
        if not application:
            return Response(
                status=HTTP_404_NOT_FOUND, data={'not_found_application': application_id}
            )

        user = self.request.user

        if user.id != application.customer.user_id:
            return Response(
                status=HTTP_403_FORBIDDEN, data={'errors': 'User not allowed', 'user_id': user.id}
            )

        bank_application = BankApplication.objects.get_or_none(application=application)
        if not bank_application:
            return Response(
                status=HTTP_404_NOT_FOUND, data={'not_found_bankapplication': application_id}
            )
        kyc_request = KycRequest.objects.get_or_none(application=application)
        data = model_to_dict(bank_application)
        if (
            application.application_status.status_code
            > ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED
        ):
            if kyc_request:
                data['bri_account'] = False
            else:
                data['bri_account'] = True
        else:
            if application.bank_account_number:
                data['bri_account'] = True
            else:
                data['bri_account'] = False
        return Response(status=HTTP_200_OK, data=data)


class CreditScoreView(APIView):
    def get(self, request, application_id):
        user_applications = request.user.customer.application_set.values_list('id', flat=True)
        if int(application_id) not in user_applications:
            return Response(status=HTTP_404_NOT_FOUND, data={'not_found': application_id})
        credit_score = get_credit_score1(application_id)
        if credit_score:
            return Response(CreditScoreSerializer(credit_score).data)
        else:
            data = {'message': 'Unable to calculate score'}
            return Response(status=HTTP_400_BAD_REQUEST, data=data)


class CreditScore2View(APIView):
    def get(self, request, application_id):
        minimum_false_rejection = request.GET.get('minimum_false_rejection', False)
        minimum_false_rejection = minimum_false_rejection == 'true'
        user_applications = request.user.customer.application_set.values_list('id', flat=True)
        if int(application_id) not in user_applications:
            return Response(status=HTTP_404_NOT_FOUND, data={'not_found': application_id})
        app = Application.objects.get(pk=application_id)
        # handle error for paylater application
        if app.customer_credit_limit:
            app = request.user.customer.application_set.regular_not_deletes().last()
        credit_score = get_credit_score3(app, minimum_false_rejection)

        exclude_list = ['inside_premium_area', 'fdc_inquiry_check']
        today = timezone.now().date()
        experiment = Experiment.objects.filter(
            is_active=True,
            date_start__lte=today,
            date_end__gte=today,
            code=ExperimentConst.IS_OWN_PHONE_EXPERIMENT,
        ).last()
        is_own_phone_check = AutoDataCheck.objects.filter(
            application_id=app.id, is_okay=False, data_to_check='own_phone'
        )
        if experiment and is_own_phone_check:
            exclude_list += ['own_phone']
            try:
                ApplicationExperiment.objects.get_or_create(application=app, experiment=experiment)
            except MultipleObjectsReturned:
                ApplicationExperiment.objects.filter(
                    application=app, experiment=experiment
                ).last().delete()
                logger.warning(
                    {
                        "message": "get_credit_score_duplicate_application_experiment",
                        "application_id": app.id,
                    }
                )

        no_failed_binary_check = (
            not AutoDataCheck.objects.filter(application_id=app.id, is_okay=False)
            .exclude(data_to_check__in=exclude_list)
            .exists()
        )

        feature_high_score = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.FORCE_HIGH_SCORE, is_active=True
        ).last()
        # force to A- event binary check failed
        if feature_high_score and app.email in feature_high_score.parameters:
            no_failed_binary_check = True

        if credit_score:
            response = CreditScoreSerializer(credit_score).data
            # to change the wording if the user has not update the app
            # version greater than equal to 3.5.3
            if credit_score.score in ['C', '--']:
                if no_failed_binary_check:
                    response['message'] = messages['C_score_and_passed_binary_check']
                elif response['products']:
                    response['products'].pop()

            response['binary_check'] = no_failed_binary_check
            loc = LineOfCreditService().get_loc_status_by_customer(request.user.customer)

            if (
                not credit_score.inside_premium_area
                or ProductLineCodes.LOC not in response['products']
            ):
                loc['can_apply'] = False

            response['loc'] = loc

            product_lines = get_product_lines(request.user.customer, app, app.web_version)
            response['product_lines'] = ProductLineSerializer(product_lines, many=True).data

            response['mtl_experiment_enable'] = False
            if minimum_false_rejection:
                response = update_response_false_rejection(app, response)

            if check_fraud_model_exp(app):
                response = update_response_fraud_experiment(response)

            response = add_boost_button_and_message(response, application_id, credit_score.score)

            return Response(response)
        else:
            data = {'message': 'Unable to calculate score'}
            return Response(status=HTTP_400_BAD_REQUEST, data=data)


class Privacy(generics.ListAPIView):
    """
    end point for privacy
    """

    permission_classes = []
    authentication_classes = []

    def get(self, request, *args, **kwargs):

        # will be show when link in the bottom "Kebijakan Privasi" clicked
        text = render_to_string('privacy_v2.txt')
        len_text = len(text)

        # will be show in on-load after register
        body = render_to_string('privacy_v3.json')
        len_body = len(body)

        body = json.loads(body)

        # log
        logger.info(
            {
                "message": "Privacy data loaded is OK",
                "len body": len_body,
                "len text": len_text,
                "len_body suspicious": len_body < 3000,
                "len_text suspicious": len_text < 23000,
            },
            request=request,
        )

        return Response(
            {
                'text': text,
                'title': body['title'],
                'preface': body['preface'],
            }
        )


class RegisterUser(APIView):
    """
    simple usertoken endpoint using username, password, email
    """

    permission_classes = []
    authentication_classes = []
    serializer_class = RegisterUserSerializer

    def post(self, request):
        """Handles user registration"""
        self.serializer_class(data=request.data).is_valid(raise_exception=True)
        nik = request.data['username']
        email = request.data['email'].strip().lower()

        if email_blacklisted(email):
            logger.error({"message": "Not google email", "email": email}, request=request)
            return Response(status=HTTP_400_BAD_REQUEST, data={'error': 'Not google email'})

        if not verify_nik(nik):
            logger.error({"message": "Invalid NIK", "nik": nik}, request=request)
            return Response(status=HTTP_400_BAD_REQUEST, data={'error': 'Invalid NIK'})

        user = User(username=nik, email=email)
        user.set_password(request.data['password'])
        try:
            with transaction.atomic():
                user.save()
                customer = Customer.objects.create(user=user, email=email, nik=nik)
                workflow = Workflow.objects.get_or_none(name='SubmittingFormWorkflow')
                application = Application.objects.create(
                    customer=customer,
                    ktp=nik,
                    app_version=get_latest_app_version(),
                    email=email,
                    workflow=workflow,
                )
                update_customer_data(application)

                partner_referral = PartnerReferral.objects.filter(
                    Q(cust_email=email) | Q(cust_nik=nik)
                ).last()
                if partner_referral and ((application.cdate - partner_referral.cdate).days <= 30):
                    partner_referral.customer = customer
                    logger.info(
                        {
                            'message': 'create_link_partner_referral_to_customer',
                            'customer_id': customer.id,
                            'partner_referral_id': partner_referral.id,
                            'email': email,
                        },
                        request=request,
                    )
                    partner_referral.save()
                    application.partner = partner_referral.partner
                    application.save()
                process_application_status_change(
                    application.id,
                    ApplicationStatusCodes.FORM_CREATED,
                    change_reason='customer_triggered',
                )
                # Transaction commit here

            # keep this ident
            create_application_checklist_async.delay(application.id)

            return Response(
                status=HTTP_201_CREATED,
                data={
                    'application_id': application.id,
                    'customer_id': customer.id,
                    'auth_token': str(user.auth_expiry_token),
                },
            )
        except IntegrityError:
            logger.error({"message": "Duplicate user", "email": email}, request=request)
            return Response(status=HTTP_400_BAD_REQUEST, data={'error': "Duplicate user"})


class Login2View(CustomExceptionHandlerMixin, APIView):
    """
    End point to handle login
    2nd implementation which also includes
    device, partner referral and bank application data
    """

    permission_classes = ()
    serializer_class = Login2Serializer

    def post(self, request):
        response_data = {}

        self.serializer_class(data=request.data).is_valid(raise_exception=True)

        try:
            username = request.data['username'].strip()  # remove linebreak
            if re.match(r'\d{16}', username):
                customer = Customer.objects.get(nik=username)
            else:
                customer = Customer.objects.get(email__iexact=username)
        except ObjectDoesNotExist:
            logger.error(
                {
                    "message": "Nomor KTP atau email Anda tidak terdaftar.",
                    "username": username if username else None,
                },
                request=request,
            )
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={'errors': ["Nomor KTP atau email Anda tidak terdaftar."]},
            )

        user = customer.user
        is_password_correct = user.check_password(request.data['password'])
        if not is_password_correct:
            return Response(
                status=HTTP_400_BAD_REQUEST, data={'errors': ["Password Anda masih salah."]}
            )
        response_data['token'] = user.auth_expiry_token.key

        response_data['customer'] = CustomerSerializer(customer).data

        device = customer.device_set.filter(gcm_reg_id=request.data['gcm_reg_id']).last()
        suspicious_login = False
        if not device:
            android_device = customer.device_set.filter(
                android_id=request.data['android_id']
            ).exists()
            device_model_name = get_device_model_name(
                request.data.get('manufacturer'), request.data.get('model')
            )
            device = Device.objects.create(
                customer=customer,
                gcm_reg_id=request.data['gcm_reg_id'],
                imei=request.data['imei'],
                android_id=request.data['android_id'],
                device_model_name=device_model_name,
            )
            if not android_device:
                suspicious_login = True
        response_data['device_id'] = device.id

        application = customer.application_set.regular_not_deletes().last()
        if not application:
            workflow = Workflow.objects.get_or_none(name='SubmittingFormWorkflow')
            application = Application.objects.create(
                customer=customer,
                ktp=customer.nik,
                email=customer.email,
                app_version=get_latest_app_version(),
                device=device,
                application_number=1,
                workflow=workflow,
            )
            update_customer_data(application)
            process_application_status_change(
                application.id,
                ApplicationStatusCodes.FORM_CREATED,
                change_reason='customer_triggered',
            )
            create_application_checklist_async.delay(application.id)
        # assign application to device
        else:
            if application.device:
                if application.device.id != device.id:
                    application.device = device
                    application.save()
            else:
                application.device = device
                application.save()
        response_data['applications'] = ApplicationSerializer(
            customer.application_set.regular_not_deletes(), many=True
        ).data

        if not hasattr(application, 'addressgeolocation'):
            try:
                address_geolocation = AddressGeolocation.objects.create(
                    application=application,
                    latitude=request.data['latitude'],
                    longitude=request.data['longitude'],
                )
                generate_address_from_geolocation_async.delay(address_geolocation.id)
            except IntegrityError:
                logger.error(
                    {
                        'status': 'login2_view',
                        'message': 'create_address_by_geolocation_exist',
                        'application_id': application.id,
                        'customer_id': customer.id,
                    },
                    request=request,
                )

        partner_referral = PartnerReferral.objects.filter(
            customer=customer, partner=application.partner
        ).last()
        response_data['partner'] = PartnerReferralSerializer(partner_referral).data

        response_data['bank_application'] = {}
        if application.referral_code:
            mantri = Mantri.objects.get_or_none(code__iexact=application.referral_code)
            if mantri:
                bank_application = BankApplication.objects.get_or_none(application=application)
                if bank_application:
                    response_data['bank_application'] = model_to_dict(bank_application)
                    if (
                        application.application_status.status_code
                        > ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED
                    ):
                        kyc_request = KycRequest.objects.get_or_none(application=application)
                        bri_account = kyc_request is None
                    else:
                        bri_account = application.bank_account_number is not None
                    response_data['bank_application']['bri_account'] = bri_account

        force_logout_action = CustomerAppAction.objects.get_or_none(
            customer=customer, action='force_logout', is_completed=False
        )
        if force_logout_action:
            force_logout_action.mark_as_completed()
            force_logout_action.save()

        # EtlStatus
        response_data['etl_status'] = {
            'scrape_status': 'initiated',
            'is_gmail_failed': True,
            'is_sd_failed': True,
            'credit_score': None,
        }
        now = timezone.now()
        app_cdate = Application.objects.values_list('cdate', flat=True).get(id=application.id)
        etl_status = EtlStatus.objects.filter(application_id=application.id).last()

        if etl_status:
            if 'dsd_extract_zipfile_task' in etl_status.executed_tasks:
                response_data['etl_status']['is_sd_failed'] = False
            elif 'dsd_extract_zipfile_task' in list(etl_status.errors.keys()):
                response_data['etl_status']['is_sd_failed'] = True

            if 'gmail_scrape_task' in etl_status.executed_tasks:
                response_data['etl_status']['is_gmail_failed'] = False
            elif 'gmail_scrape_task' in list(etl_status.errors.keys()):
                response_data['etl_status']['is_gmail_failed'] = True

            if now > app_cdate + relativedelta(minutes=20):
                if 'dsd_extract_zipfile_task' not in etl_status.executed_tasks:
                    response_data['etl_status']['is_sd_failed'] = True
                if 'gmail_scrape_task' not in etl_status.executed_tasks:
                    response_data['etl_status']['is_gmail_failed'] = True

        if (
            not response_data['etl_status']['is_gmail_failed']
            and not response_data['etl_status']['is_sd_failed']
        ):
            credit_score = CreditScore.objects.get_or_none(application_id=application.id)
            if credit_score:
                response_data['etl_status']['credit_score'] = credit_score.score
            response_data['etl_status']['scrape_status'] = 'done'
        elif (
            response_data['etl_status']['is_gmail_failed']
            or response_data['etl_status']['is_sd_failed']
        ):
            response_data['etl_status']['scrape_status'] = 'failed'

        if suspicious_login:
            alert_suspicious_login_to_user(device)

        return Response(data=response_data)


class Login(APIView):
    """
    End point to handle login

    DEPRECATED: See Login2View
    """

    permission_classes = []
    authentication_classes = []
    serializer_class = LoginSerializer

    def post(self, request):
        self.serializer_class(data=request.data).is_valid(raise_exception=True)
        try:
            username = request.data['username']
            username = username.replace('\\n', '')  # Remove breakline in email
            customer = Customer.objects.get(Q(email=username) | Q(nik=username))
            user = customer.user
        except ObjectDoesNotExist:
            return Response(
                status=HTTP_400_BAD_REQUEST, data={'error': 'Informasi yang Anda masukkan salah'}
            )

        if user.check_password(request.data['password']):
            force_logout_action = CustomerAppAction.objects.get_or_none(
                customer=customer, action='force_logout', is_completed=False
            )

            if force_logout_action:
                force_logout_action.mark_as_completed()
                force_logout_action.save()
            return Response({'token': user.auth_expiry_token.key})
        else:
            return Response(
                status=HTTP_400_BAD_REQUEST, data={'error': 'Informasi yang Anda masukkan salah'}
            )


class DeviceScrapedDataUpload(APIView):
    """
    Endpoint for uploading DSD to anaserver and starting ETL
    """

    def post(self, request):
        if 'application_id' not in request.data:
            logger.warning(message="application_id field is required", request=request)
            return Response(
                status=HTTP_400_BAD_REQUEST, data={'application_id': "This field is required"}
            )

        customer = request.user.customer
        application_id = int(request.data['application_id'])
        if application_id == 0:
            application = customer.application_set.filter().order_by('cdate').last()
            if application:
                application_id = application.id

        logger.info(
            {
                "message": "Function call -> DeviceScrapedDataUpload.post",
                "application_id": application_id,
            },
            request=request,
        )

        if 'upload' not in request.data:
            logger.warning(message="upload field is required", request=request)
            return Response(status=HTTP_400_BAD_REQUEST, data={'upload': "This field is required"})
        if not isinstance(request.data['upload'], InMemoryUploadedFile):
            return Response(
                status=HTTP_400_BAD_REQUEST, data={'upload': "This field must contain file"}
            )

        logger.info(
            {
                "message": "DeviceScrapedDataUpload.post data validated",
                "application_id": application_id,
            },
            request=request,
        )

        user_applications = customer.application_set.values_list('id', flat=True)
        if application_id not in user_applications:
            logger.warning(
                {
                    "message": "DeviceScrapedDataUpload.post application id is not correct",
                    "application_id": application_id,
                },
                request=request,
            )
            return Response(status=HTTP_404_NOT_FOUND, data={'not_found': application_id})

        logger.info(
            {
                "message": "DeviceScrapedDataUpload.post check rescrape customer app action",
                "application_id": application_id,
            },
            request=request,
        )
        try:
            incomplete_rescrape_action = CustomerAppAction.objects.get_or_none(
                customer=customer, action='rescrape', is_completed=False
            )
        except MultipleObjectsReturned:
            # checking total duplicate data, delete the duplicate data and leaving 1 data
            incomplete_rescrape_action = CustomerAppAction.objects.filter(
                customer=customer, action='rescrape', is_completed=False
            )
            total_data = len(incomplete_rescrape_action)
            if total_data > 1:
                for incomplete in range(1, total_data):
                    incomplete_rescrape_action[incomplete].update_safely(is_completed=True)
            incomplete_rescrape_action = CustomerAppAction.objects.get_or_none(
                customer=customer, action='rescrape', is_completed=False
            )
        if incomplete_rescrape_action:
            logger.info(
                {
                    "message": "DeviceScrapedDataUpload.post completed rescrape CAA",
                    "application_id": application_id,
                },
                request=request,
            )
            incomplete_rescrape_action.mark_as_completed()
            incomplete_rescrape_action.save()

        url = request.build_absolute_uri()
        application = customer.application_set.get(pk=application_id)
        ApplicationScrapeAction.objects.create(
            application_id=application.id, url=url, scrape_type='dsd'
        )

        data = {'application_id': application_id, 'customer_id': customer.id}
        files = {'upload': request.data['upload']}

        logger.info(
            {
                "message": "Try redirect post to anaserver",
                "ana_server": "/api/amp/v1/device-scraped-data/",
                "data": data,
            },
            request=request,
        )

        ret = redirect_post_to_anaserver('/api/amp/v1/device-scraped-data/', data=data, files=files)

        dummy_ret = {
            "status": 'initiated',
            "application_id": application_id,
            "data_type": 'dsd',
            "s3_url_report": None,
            "udate": None,
            "dsd_id": 0,
            "cdate": None,
            "s3_url_raw": None,
            "temp_dir": None,
            "error": None,
            "customer_id": None,
            "id": 1,
        }

        logger.info(
            {"message": "Success response for device scraped data", "data": dummy_ret},
            request=request,
        )
        return Response(status=ret.status_code, data=dummy_ret)


class GmailAuthTokenGet(APIView):
    """
    Redirect to google permission page for testing gmail scraping
    """

    authentication_classes = []
    permission_classes = []

    # Also disable deviceIP middleware class

    def get(self, request):
        if not request.GET.get('code', ''):
            flow = oauth2_client.flow_from_clientsecrets(
                settings.GOOGLE_CLIENT_SECRET,
                scope='',
                redirect_uri=settings.BASE_URL + '/api/v1/applications/gmail/authcode',
            )
            flow.params['access_type'] = 'offline'  # offline access
            auth_url = flow.step1_get_authorize_url()
            return redirect(auth_url)
        else:
            return Response(status=200, data={'auth_code': request.GET.get('code', '')})


class GmailAuthToken(APIView):
    """
    Scrape gmail
    """

    def post(self, request):
        data = request.data.copy()
        customer = request.user.customer
        user_applications = customer.application_set.values_list('id', flat=True)
        if 'application_id' not in data:
            return Response(
                status=HTTP_400_BAD_REQUEST, data={'application_id': 'This field is required'}
            )

        application_id = int(data['application_id'])
        if application_id not in user_applications:
            return Response(status=HTTP_404_NOT_FOUND, data={'not_found': data['application_id']})

        url = request.build_absolute_uri()
        application = customer.application_set.get(pk=application_id)
        ApplicationScrapeAction.objects.create(
            application_id=application.id, url=url, scrape_type='gmail'
        )

        data['customer_id'] = request.user.customer.id
        data['data_type'] = 'gmail'
        # temporary revert until gmail scrapping issue fixed
        # if customer.google_access_token and customer.google_refresh_token:
        #     data['google_access_token'] = customer.google_access_token
        #     data['google_refresh_token'] = customer.google_refresh_token
        ret = redirect_post_to_anaserver('/api/amp/v1/gmail/', data)

        dummy_ret = {
            "status": 'initiated',
            "application_id": data['application_id'],
            "data_type": 'gmail',
            "s3_url_report": None,
            "udate": None,
            "dsd_id": None,
            "cdate": None,
            "s3_url_raw": None,
            "temp_dir": None,
            "error": None,
            "customer_id": None,
            "id": 1,
        }
        return Response(status=ret.status_code, data=dummy_ret)


class EtlJobStatusListView(generics.ListAPIView):
    def get(self, request, application_id):
        customer = request.user.customer
        user_applications = customer.application_set.values_list('id', flat=True)
        application_id = int(application_id)
        if application_id not in user_applications:
            return Response(status=HTTP_404_NOT_FOUND, data={'not_found': application_id})
        now = timezone.now()
        action_date = Application.objects.values_list('cdate', flat=True).get(id=application_id)
        application = customer.application_set.get(pk=application_id)
        app_scrape_action = ApplicationScrapeAction.objects.filter(application_id=application.id)
        etl_status = EtlStatus.objects.filter(application_id=application_id).first()
        data = []

        if etl_status:
            # check dsd etl status
            if 'dsd_extract_zipfile_task' in etl_status.executed_tasks:
                data.append({'id': 0, 'status': 'done', 'data_type': 'dsd'})
            else:
                dsd_scrape_action = (
                    app_scrape_action.filter(scrape_type='dsd').order_by('-id').first()
                )
                if dsd_scrape_action:
                    action_date = dsd_scrape_action.cdate
                if now > action_date + relativedelta(minutes=20):
                    data.append({'id': 0, 'status': 'failed', 'data_type': 'dsd'})
                else:
                    data.append({'id': 0, 'status': 'initiated', 'data_type': 'dsd'})

            # check gmail etl status
            if 'gmail_scrape_task' in etl_status.executed_tasks:
                data.append({'id': 0, 'status': 'done', 'data_type': 'gmail'})
            else:
                gmail_scrape_action = (
                    app_scrape_action.filter(scrape_type='gmail').order_by('-id').first()
                )
                if gmail_scrape_action:
                    action_date = gmail_scrape_action.cdate
                if now > action_date + relativedelta(minutes=20):
                    data.append({'id': 0, 'status': 'done', 'data_type': 'gmail'})
                else:
                    data.append({'id': 0, 'status': 'done', 'data_type': 'gmail'})

        elif now > action_date + relativedelta(minutes=20):
            data = [
                {'id': 0, 'status': 'failed', 'data_type': 'dsd'},
                {'id': 0, 'status': 'done', 'data_type': 'gmail'},
            ]
        else:
            data = [
                {'id': 0, 'status': 'initiated', 'data_type': 'dsd'},
                {'id': 0, 'status': 'done', 'data_type': 'gmail'},
            ]
        return Response(status=HTTP_200_OK, data=data)


class RequestOTP(APIView):
    # Request OTP for Forgot password
    permission_classes = []
    authentication_classes = []
    serializer_class = OtpRequestSerializer

    def post(self, request):
        self.serializer_class(data=request.data).is_valid(raise_exception=True)
        phone = request.data['phone']
        # request_id integer value from timestamp
        request_id = request.data['request_id']
        postfix = int(time.time())
        postfixed_request_id = request_id + str(postfix)

        try:
            customer = Customer.objects.filter(phone=phone).earliest('cdate')
        except ObjectDoesNotExist:
            return Response(
                status=HTTP_400_BAD_REQUEST, data={'error': 'Nomor telepon belum terdaftar'}
            )

        existing_otp = (
            OtpRequest.objects.filter(customer=customer, is_used=False).order_by('id').last()
        )
        create_new_otp = False if existing_otp and existing_otp.is_active is True else True

        if create_new_otp:
            hotp = pyotp.HOTP(settings.OTP_SECRET_KEY)
            otp = str(hotp.at(int(postfixed_request_id)))
            otp_obj = OtpRequest.objects.create(
                customer=customer,
                request_id=postfixed_request_id,
                otp_token=otp,
                phone_number=phone,
            )
        else:
            otp = existing_otp.otp_token
            otp_obj = existing_otp

        context = {'otp_token': otp}
        text_message = render_to_string('sms_otp_token.txt', context=context)
        send_sms_otp_token.delay(phone, text_message, customer.id, otp_obj.id)
        return Response({'message': "OTP sudah dikirim"})


class LoginWithOTP(APIView):
    # Login with OTP
    permission_classes = []
    authentication_classes = []
    serializer_class = OtpValidationSerializer

    def post(self, request):
        self.serializer_class(data=request.data).is_valid(raise_exception=True)
        otp_token = request.data['otp_token']
        # request_id integer value from timestamp
        request_id = request.data['request_id']
        try:
            otp_data = OtpRequest.objects.filter(otp_token=otp_token, is_used=False).latest('id')
        except ObjectDoesNotExist:
            return Response(
                status=HTTP_400_BAD_REQUEST, data={'error': 'Informasi yang Anda masukkan salah'}
            )
        if request_id in otp_data.request_id:
            hotp = pyotp.HOTP(settings.OTP_SECRET_KEY)
            valid_token = hotp.verify(otp_token, int(otp_data.request_id))

            if otp_data.is_active and valid_token:
                otp_data.is_used = True
                otp_data.save()
                return Response({'token': otp_data.customer.user.auth_expiry_token.key})
            else:
                return Response(status=HTTP_400_BAD_REQUEST, data={'error': 'OTP tidak valid'})
        else:
            return Response(status=HTTP_400_BAD_REQUEST, data={'error': 'Request tidak valid'})


class ApplicationOtpRequest(APIView):
    serializer_class = OtpRequestSerializer

    def post(self, request):
        """Verifying mobile phone included in the application"""
        self.serializer_class(data=request.data).is_valid(raise_exception=True)
        phone = request.data['phone'].strip()

        mfs = MobileFeatureSetting.objects.get_or_none(feature_name='mobile_phone_1_otp')
        if not mfs.is_active:
            logger.warning(
                {
                    "message": "Verifikasi kode tidak aktif",
                    "active": mfs.is_active,
                    "parameters": mfs.parameters,
                },
                request=request,
            )
            return Response(
                data={
                    "success": True,
                    "content": {
                        "active": mfs.is_active,
                        "parameters": mfs.parameters,
                        "message": "Verifikasi kode tidak aktif",
                    },
                }
            )

        customer = Customer.objects.get_or_none(user=request.user)
        existing_otp_request = (
            OtpRequest.objects.filter(customer=customer, is_used=False, phone_number=phone)
            .order_by('id')
            .last()
        )

        change_sms_provide = False
        curr_time = timezone.localtime(timezone.now())
        otp_wait_seconds = mfs.parameters['wait_time_seconds']
        otp_max_request = mfs.parameters['otp_max_request']
        otp_resend_time = mfs.parameters['otp_resend_time']
        data = {
            "success": True,
            "content": {
                "active": mfs.is_active,
                "parameters": mfs.parameters,
                "message": "sms sent is rejected",
                "expired_time": None,
                "resend_time": None,
                "otp_max_request": otp_max_request,
                "retry_count": 0,
                "current_time": curr_time,
            },
        }
        now = timezone.localtime(timezone.now())
        current_count = (
            SmsHistory.objects.filter(
                customer=customer,
                cdate__gte=now - relativedelta(seconds=otp_wait_seconds),
                is_otp=True,
            )
            .exclude(status='UNDELIV')
            .count()
        )
        retry_count = current_count + 1

        if existing_otp_request and existing_otp_request.is_active:
            sms_history = existing_otp_request.sms_history
            prev_time = sms_history.cdate if sms_history else existing_otp_request.cdate
            expired_time = timezone.localtime(existing_otp_request.cdate) + timedelta(
                seconds=otp_wait_seconds
            )
            resend_time = timezone.localtime(prev_time) + timedelta(seconds=otp_resend_time)

            data['content']['expired_time'] = expired_time
            data['content']['resend_time'] = resend_time
            data['content']['retry_count'] = retry_count
            if sms_history and sms_history.status == 'Rejected':
                data['content']['resend_time'] = expired_time
                logger.warning(
                    {
                        "message": "Sms history is rejected",
                        "resend_time": expired_time,
                        "customer": customer.id,
                    },
                    request=request,
                )
                return Response(data=data)
            if retry_count > otp_max_request:
                data['content']['message'] = "exceeded the max request"
                logger.warning(
                    {"message": data['content']['message'], "customer": customer.id},
                    request=request,
                )
                return Response(data=data)

            if curr_time < resend_time:
                data['content']['message'] = "requested OTP less than resend time"
                logger.warning(
                    {"message": data['content']['message'], "customer": customer.id},
                    request=request,
                )
                return Response(data=data)

            if (
                curr_time > resend_time
                and sms_history
                and sms_history.comms_provider
                and sms_history.comms_provider.provider_name
            ):
                if sms_history.comms_provider.provider_name.lower() == VendorConst.MONTY:
                    change_sms_provide = True

            if not sms_history:
                change_sms_provide = True

            otp_request = existing_otp_request
        else:
            if retry_count > otp_max_request:
                data['content']['message'] = "exceeded the max request"
                return Response(data=data)
            hotp = pyotp.HOTP(settings.OTP_SECRET_KEY)
            postfixed_request_id = str(customer.id) + str(int(time.time()))
            otp = str(hotp.at(int(postfixed_request_id)))

            current_application = (
                Application.objects.regular_not_deletes()
                .filter(customer=customer, application_status=ApplicationStatusCodes.FORM_CREATED)
                .first()
            )
            otp_request = OtpRequest.objects.create(
                customer=customer,
                request_id=postfixed_request_id,
                otp_token=otp,
                application=current_application,
                phone_number=phone,
            )
            data['content']['message'] = "Kode verifikasi sudah dikirim"
            data['content']['expired_time'] = timezone.localtime(otp_request.cdate) + timedelta(
                seconds=otp_wait_seconds
            )
            data['content']['retry_count'] = 1

        text_message = render_to_string(
            'sms_otp_token_application.txt', context={'otp_token': otp_request.otp_token}
        )
        try:
            send_sms_otp_token.delay(
                phone, text_message, customer.id, otp_request.id, change_sms_provide
            )
            data['content']['resend_time'] = timezone.localtime(timezone.now()) + timedelta(
                seconds=otp_resend_time
            )
        except SmsNotSent:
            logger.error(
                {
                    "status": "sms_not_sent",
                    "message": "Kode verifikasi belum dapat dikirim",
                    "customer": customer.id,
                    "phone": phone,
                },
                request=request,
            )
            julo_sentry_client.captureException()
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={
                    "success": False,
                    "content": {},
                    "error_message": "Kode verifikasi belum dapat dikirim",
                },
            )

        return Response(data=data)


class ApplicationOtpValidation(APIView):
    serializer_class = OtpValidationSerializer

    def post(self, request):
        self.serializer_class(data=request.data).is_valid(raise_exception=True)

        mfs = MobileFeatureSetting.objects.get_or_none(feature_name='mobile_phone_1_otp')
        if not mfs.is_active:
            return Response(
                data={
                    "success": True,
                    "content": {
                        "active": mfs.is_active,
                        "parameters": mfs.parameters,
                        "message": "Verifikasi kode tidak aktif",
                    },
                }
            )

        otp_token = request.data['otp_token']

        customer = Customer.objects.get_or_none(user=request.user)
        existing_otp_request = (
            OtpRequest.objects.filter(otp_token=otp_token, customer=customer, is_used=False)
            .order_by('id')
            .last()
        )
        if not existing_otp_request:
            logger.error(
                {
                    "status": "otp_token_not_found",
                    "message": "Kode verifikasi belum terdaftar",
                    "otp_token": otp_token,
                    "customer": customer.id,
                },
                request=request,
            )
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={
                    "success": False,
                    "content": {},
                    "error_message": "Kode verifikasi belum terdaftar",
                },
            )

        if str(customer.id) not in existing_otp_request.request_id:
            logger.error(
                {
                    "status": "request_id_failed",
                    "otp_token": otp_token,
                    "message": "Kode verifikasi tidak valid",
                    "otp_request": existing_otp_request.id,
                    "customer": customer.id,
                },
                request=request,
            )
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={
                    "success": False,
                    "content": {},
                    "error_message": "Kode verifikasi tidak valid",
                },
            )

        hotp = pyotp.HOTP(settings.OTP_SECRET_KEY)
        valid_token = hotp.verify(otp_token, int(existing_otp_request.request_id))
        if not valid_token:
            logger.error(
                {
                    "status": "invalid_token",
                    "otp_token": otp_token,
                    "message": "Kode verifikasi tidak valid",
                    "otp_request": existing_otp_request.id,
                    "customer": customer.id,
                },
                request=request,
            )
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={
                    "success": False,
                    "content": {},
                    "error_message": "Kode verifikasi tidak valid",
                },
            )

        if not existing_otp_request.is_active:
            logger.error(
                {
                    "status": "otp_token_expired",
                    "otp_token": otp_token,
                    "message": "Kode verifikasi kadaluarsa",
                    "otp_request": existing_otp_request.id,
                    "customer": customer.id,
                },
                request=request,
            )
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={
                    "success": False,
                    "content": {},
                    "error_message": "Kode verifikasi kadaluarsa",
                },
            )

        existing_otp_request.is_used = True
        existing_otp_request.save(update_fields=['is_used'])
        logger.info(
            {"message": "Kode verifikasi berhasil diverifikasi", "customer": customer.id},
            request=request,
        )
        return Response(
            data={
                "success": True,
                "content": {
                    "active": mfs.is_active,
                    "parameters": mfs.parameters,
                    "message": "Kode verifikasi berhasil diverifikasi",
                },
            }
        )


class CheckReferral(APIView):
    """
    end point check referral code
    """

    permission_classes = []
    authentication_classes = []

    def get(self, request, application_id, referral_code):
        application = Application.objects.get_or_none(pk=application_id)
        if not application:
            return Response(
                status=HTTP_404_NOT_FOUND, data={'not_found_application': application_id}
            )
        user = self.request.user

        if user.id != application.customer.user_id:
            return Response(
                status=HTTP_403_FORBIDDEN, data={'errors': 'User not allowed', 'user_id': user.id}
            )

        referral_code = referral_code.replace(' ', '')
        mantri = Mantri.objects.get_or_none(code__iexact=referral_code)
        if mantri:
            application.mantri = mantri
            application.referral_code = referral_code
            application.save()
            return Response({'status': True, 'application': model_to_dict(application)})
        else:
            return Response({'status': False, 'application': model_to_dict(application)})


class ActivationEformVoucher(APIView):
    """
    Activation eform voucher
    """

    def get(self, request, application_id):
        application = Application.objects.get_or_none(pk=application_id)
        if not application:
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={'error': 'Activation E-form Voucher Failed, application not found'},
            )

        user = self.request.user

        if user.id != application.customer.user_id:
            return Response(
                status=HTTP_403_FORBIDDEN, data={'errors': 'User not allowed', 'user_id': user.id}
            )

        kyc = (
            KycRequest.objects.filter(application=application, is_processed=False)
            .order_by('id')
            .last()
        )

        if not kyc:
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={'error': 'Activation E-form Voucher Failed, voucher not found'},
            )

        if kyc.is_expired:
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={'error': 'Activation E-form Voucher Failed, voucher expired'},
            )

        julo_bri_client = get_julo_bri_client()
        account_number = julo_bri_client.get_account_info(kyc)

        if not account_number:
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={'error': 'Activation E-form Voucher Failed, KYC not yet processed'},
            )

        with transaction.atomic():
            kyc.is_processed = True
            kyc.save()
            application.name_in_bank = application.fullname
            application.bank_account_number = account_number
            application.save()
            process_application_status_change(
                application.id, ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED, 'KYC Successful'
            )
            return Response({'status': True, 'application_id': application.id})


class getNewEformVoucher(APIView):
    """
    Get new eform voucher
    """

    def get(self, request, application_id):
        application = Application.objects.get_or_none(pk=application_id)
        if not application:
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={'error': 'Get new E-form Voucher Failed, application not found'},
            )
        user = self.request.user

        if user.id != application.customer.user_id:
            return Response(
                status=HTTP_403_FORBIDDEN, data={'errors': 'User not allowed', 'user_id': user.id}
            )

        kyc = (
            KycRequest.objects.filter(application=application, is_processed=False)
            .order_by('id')
            .last()
        )
        if not kyc:
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={'error': 'Get new E-form Voucher Failed, voucher not found'},
            )
        if not kyc.is_expired:
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={'error': 'Get new E-form Voucher Failed, voucher not expired'},
            )

        julo_bri_client = get_julo_bri_client()
        new_kyc = julo_bri_client.send_application_result(True, application)
        kyc.is_processed = True
        kyc.save()
        return Response(
            {
                'status': True,
                'eform_voucher': new_kyc.eform_voucher,
                'expiry_time': new_kyc.expiry_time,
            }
        )


class OtpChangePassword(APIView):
    # Change password after Login with OTP

    serializer_class = ChangePasswordSerializer

    def put(self, request):
        self.serializer_class(data=request.data).is_valid(raise_exception=True)
        new_password = request.data['new_password']

        user = self.request.user
        user.set_password(new_password)
        user.save()
        return Response(
            {'message': 'Password berhasil diubah, gunakan password baru saat login selanjutnya'}
        )


class ScrapingButtonList(APIView):
    """
    API for scraping button list
    """

    def get(self, request):
        scraping_buttons = ScrapingButton.objects.values('name', 'type', 'tag', 'is_shown')
        finfini_targets = [
            'shopee',
            'bri',
            'bukalapak',
            'bni',
            'cimb_niaga',
            'permata',
            'tokopedia',
        ]
        finfini_status = dict(
            FinfiniStatus.objects.filter(name__in=finfini_targets).values_list('name', 'status')
        )
        for button in scraping_buttons:
            if button['name'] in finfini_targets:
                button['is_active'] = finfini_status[button['name']] == 'active'
            else:
                button['is_active'] = True
        return Response(scraping_buttons)


class PaymentSummaryListView(generics.ListAPIView):
    """
    end point view custom payment
    """

    def get(self, request, *args, **kwargs):
        user = request.user
        loan_id = kwargs['loan_id']

        loan = Loan.objects.get_or_none(id=loan_id, customer=user.customer)
        if loan is None:
            raise ResourceNotFound(resource_id=loan_id)

        list_payment = list(Payment.objects.by_loan(loan))
        count_paid_payment = 0
        remaining_debt_amount = 0
        first_date_payment = list_payment[0]
        last_date_payment = list_payment[-1]
        for payment in list_payment:
            if payment.payment_status.status_code in PaymentStatusCodes.paid_status_codes():
                count_paid_payment += 1
            else:
                remaining_debt_amount += payment.due_amount
        application = loan.application
        str_count_paid_payment = '%s %s' % (
            count_paid_payment,
            application.determine_kind_of_installment,
        )
        return Response(
            {
                'first_date_payment': first_date_payment.due_date,
                'last_date_payment': last_date_payment.due_date,
                'count_paid_payment': str_count_paid_payment,
                'remaining_debt_amount': remaining_debt_amount,
            }
        )


class RegisterV2View(CustomExceptionHandlerMixin, APIView):
    """
    End point for registration combined from several old end point
        -DeviceListCreateView
        -AddressGeolocationListCreateView
        -PartnerReferralRetrieveView
        -RegisterUser
        -GmailAuthToken
    """

    permission_classes = []
    authentication_classes = []
    serializer_class = RegisterV2Serializer

    def post(self, request):
        """
        Handles user registration
        """

        if is_active_julo1():
            return Response(status=HTTP_404_NOT_FOUND, data={'errors': ["No longer available"]})

        request_data = self.serializer_class(data=request.data)
        request_data.is_valid(raise_exception=True)
        email = request_data.data['email'].strip().lower()
        nik = request_data.data['username']
        appsflyer_device_id = None
        advertising_id = None
        if 'appsflyer_device_id' in request_data.data:
            appsflyer_device_id_exist = Customer.objects.filter(
                appsflyer_device_id=request_data.data['appsflyer_device_id']
            ).last()
            if not appsflyer_device_id_exist:
                appsflyer_device_id = request_data.data['appsflyer_device_id']
                if 'advertising_id' in request_data.data:
                    advertising_id = request_data.data['advertising_id']
        user = User(username=request_data.data['username'])
        user.set_password(request_data.data['password'])
        try:
            with transaction.atomic():
                user.save()

                customer = Customer.objects.create(
                    user=user,
                    email=email,
                    nik=nik,
                    appsflyer_device_id=appsflyer_device_id,
                    advertising_id=advertising_id,
                    mother_maiden_name=request_data.data.get('mother_maiden_name', None),
                )
                app_version = request_data.data['app_version']
                workflow = Workflow.objects.get_or_none(name='SubmittingFormWorkflow')
                application = Application.objects.create(
                    customer=customer,
                    ktp=nik,
                    app_version=app_version,
                    email=email,
                    workflow=workflow,
                )
                update_customer_data(application)

                self.application = application

                # link to partner attribution rules
                partner_referral = link_to_partner_if_exists(application)

                process_application_status_change(
                    application.id,
                    ApplicationStatusCodes.FORM_CREATED,
                    change_reason='customer_triggered',
                )

                # create Device
                device = Device.objects.create(
                    customer=customer,
                    gcm_reg_id=request.data['gcm_reg_id'],
                    android_id=request.data['android_id'],
                    imei=request.data['imei'],
                )

                # create AddressGeolocation
                address_geolocation = AddressGeolocation.objects.create(
                    application=application,
                    latitude=request.data['latitude'],
                    longitude=request.data['longitude'],
                )

                generate_address_from_geolocation_async.delay(address_geolocation.id)

                # store location to device_geolocation table
                store_device_geolocation(
                    customer, latitude=request.data['latitude'], longitude=request.data['longitude']
                )

                ana_data = {
                    'application_id': application.id,
                    'customer_id': customer.id,
                    'data_type': 'gmail',
                    'credentials': request.data['gmail_auth_token'],
                }
                redirect_post_to_anaserver('/api/amp/v1/gmail/', ana_data)
                # temporary revert until gmail scrapping issue fixed
                # customer.google_access_token = ana_resp.data["access_token"]
                # customer.google_refresh_token = ana_resp.data["refresh_token"]
                # customer.save()

                response_data = {
                    "token": str(user.auth_expiry_token),
                    "customer": CustomerSerializer(customer).data,
                    "applications": [ApplicationSerializer(application).data],
                    "partner": PartnerReferralSerializer(partner_referral).data,
                    "device_id": device.id,
                }

            create_application_checklist_async.delay(application.id)
            return Response(status=HTTP_201_CREATED, data=response_data)
        except IntegrityError:
            return Response(
                status=HTTP_400_BAD_REQUEST, data={'errors': ["Email/NIK anda sudah terdaftar"]}
            )


class SPHPView(generics.ListAPIView):
    """
    end point view sphp by application_id
    """

    permission_classes = []
    authentication_classes = []

    def get(self, request, *args, **kwargs):
        application_id = kwargs['application_id']
        application = Application.objects.get_or_none(pk=application_id)
        if not application:
            raise ResourceNotFound(resource_id=application_id)

        if application.status < ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL:
            raise ResourceWithDetailNotFound(
                message="SPHP pengajuan no {application_xid} belum tersedia".format(
                    application_xid=application.application_xid
                )
            )

        text_sphp = ''

        context = {
            'date_today': '',
            'application': application,
            'dob': format_date(application.dob, 'dd-MM-yyyy', locale='id_ID'),
            'full_address': application.complete_addresses,
        }

        if application.product_line.product_line_code in ProductLineCodes.loc():
            other_context = {
                'limit_amount': display_rupiah(application.line_of_credit.limit),
                'statement_day': str(application.payday),
            }
            sphp_date = timezone.now().date()
            if (
                application.application_status.status_code
                >= ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED
            ):
                sphp_date = (
                    application.applicationhistory_set.filter(
                        status_new=ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED
                    )
                    .last()
                    .cdate.date()
                )
            context['date_today'] = format_date(sphp_date, 'd MMMM yyyy', locale='id_ID')
        else:
            loan = application.loan
            other_context = {
                'loan_amount': display_rupiah(loan.loan_amount),
                'max_total_late_fee_amount': display_rupiah(loan.max_total_late_fee_amount),
                'late_fee_amount': '',
                'doku_flag': False,
                'doku_account': '',
                'julo_bank_name': loan.julo_bank_name,
                'julo_bank_code': '',
                'julo_bank_account_number': loan.julo_bank_account_number,
                'provision_fee_amount': display_rupiah(loan.provision_fee()),
                'interest_rate': '{}%'.format(loan.interest_percent_monthly()),
                'lender_agreement_number': SPHPConst.AGREEMENT_NUMBER,
            }
            if application.product_line.product_line_code not in ProductLineCodes.grabfood():
                other_context['late_fee_amount'] = display_rupiah(loan.late_fee_amount)

            document = Document.objects.filter(
                document_source=application_id,
                document_type__in=("sphp_julo", "sphp_digisign", "sphp_privy"),
            ).last()

            if not document:
                generate_sphp(application.id)

            # set date_today
            if document:
                sphp_date = document.cdate.date()
            elif (
                application.application_status.status_code
                >= ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED
            ):
                sphp_date = loan.sphp_accepted_ts
            else:
                sphp_date = timezone.now().date()
            context['date_today'] = format_date(sphp_date, 'd MMMM yyyy', locale='id_ID')

            # add flag doku account
            if application.partner and application.partner.name in 'doku':
                other_context['doku_flag'] = True
                other_context['doku_account'] = settings.DOKU_ACCOUNT_ID
                # add bank code
            if 'bca' not in loan.julo_bank_name.lower():
                payment_method = PaymentMethod.objects.filter(
                    virtual_account=loan.julo_bank_account_number
                ).first()
                if payment_method:
                    other_context['julo_bank_code'] = '<br>Kode Bank: <b>%s</b>' % (
                        payment_method.bank_code
                    )

        context = dict(list(context.items()) + list(other_context.items()))

        # render template by product_line
        if (
            application.product_line.product_line_code
            in ProductLineCodes.mtl() + ProductLineCodes.bri()
        ):
            payments = loan.payment_set.all().order_by('id')
            for payment in payments:
                payment.due_date = format_date(payment.due_date, 'd MMM yy', locale='id_ID')
                payment.due_amount = display_rupiah(payment.due_amount + payment.paid_amount)
            context['payments'] = payments
            text_sphp = get_sphp_template(application_id, False)
            # text_sphp = render_to_string('sphp_mtl.txt', context=context)
        elif application.product_line.product_line_code in ProductLineCodes.stl():
            first_payment = loan.payment_set.all().order_by('id').first()
            context['installment_amount'] = display_rupiah(loan.installment_amount)
            context['min_due_date'] = format_date(
                first_payment.due_date, 'd MMMM yyyy', locale='id_ID'
            )
            context['first_late_fee_amount'] = display_rupiah(50000)
            text_sphp = get_sphp_template(application_id, False)
            # text_sphp = render_to_string('sphp_stl.txt', context=context)
        elif application.product_line.product_line_code in ProductLineCodes.grab():
            payments = loan.payment_set.all().order_by('id')
            for payment in payments:
                payment.due_date = format_date(payment.due_date, 'd MMM yy', locale='id_ID')
                payment.due_amount = display_rupiah(payment.due_amount + payment.paid_amount)
            context['payments'] = payments
            context['bank_account'] = '%s, #%s' % (
                application.bank_name,
                application.bank_account_number,
            )
            context['origination_fee_amount'] = display_rupiah(
                loan.loan_amount * loan.product.origination_fee_pct
            )
            text_sphp = render_to_string('sphp_grab.txt', context=context)
        elif application.product_line.product_line_code in ProductLineCodes.loc():
            text_sphp = render_to_string('sphp_loc.txt', context=context)
        elif application.product_line.product_line_code in ProductLineCodes.grabfood():
            payments = loan.payment_set.all().order_by('id')
            for payment in payments:
                payment.due_date = format_date(payment.due_date, 'd MMM yy', locale='id_ID')
                payment.due_amount = display_rupiah(payment.due_amount + payment.paid_amount)
            context['payments'] = payments
            text_sphp = render_to_string('sphp_grabfood.txt', context=context)
        logger.info(
            {
                'message': 'SPHPView',
                'application_id': application.id,
                'data': context,
                'date': timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M:%S'),
            }
        )
        return Response(
            {
                'text': text_sphp,
                'data': {
                    'date': context['date_today'],
                    'fullname': application.fullname,
                },
            }
        )


class CheckCustomerActions(APIView):
    """
    endpoint for checking actions based on customer ID or app version
    """

    def get(self, request):
        app_version = request.query_params.get('app_version', None)
        customer = request.user.customer
        actions_json = get_customer_app_actions(customer, app_version)

        return Response(actions_json)


class HomeScreen(generics.ListAPIView):
    """
    end point for home screen page
    """

    def get(self, request, *args, **kwargs):
        cards = []

        customer = request.user.customer
        application_id = self.request.query_params.get('application_id', None)
        try:
            application = Application.objects.get_or_none(pk=application_id)
        except ValueError:
            application = None

        account_summary_cards = render_account_summary_cards(customer, application)
        for account_summary_card in account_summary_cards:
            cards.append(account_summary_card)
        campaign_card = render_campaign_card(customer, application_id)
        if campaign_card is not None:
            cards.append(campaign_card)
        # hide Julo Mini to remove STL product from APP for google rules
        # cards.append(render_julomini_card())
        if render_season_card() is not None:
            cards.append(render_season_card())
        if render_sphp_card(customer, application) is not None:
            cards.append(render_sphp_card(customer, application))

        # output it
        result = []
        for i, v in enumerate(cards):
            displayed_card = {
                'position': i + 1,
                'header': v['header'],
                'topimage': v['topimage'],
                'body': v['body'],
                'bottomimage': v['bottomimage'],
                'buttontext': v['buttontext'],
                'buttonurl': v['buttonurl'],
                'buttonstyle': v['buttonstyle'],
            }
            if v['expired_time']:
                displayed_card.update({'expired_time': v['expired_time']})
            result.append(displayed_card)
        return Response(result)


class CashbackGetBalance(APIView):
    """
    endpoint get balance cashback available
    """

    def get(self, request):
        customer = request.user.customer
        logger.info(
            {
                'message': 'get_balance_cashback_available',
                'balance': customer.wallet_balance_available,
            },
            request=request,
        )

        return Response(
            {
                'balance': customer.wallet_balance_available,
            }
        )


class CashbackTransaction(APIView):
    """
    endpoint get transactions cashback disbursement
    """

    def get(self, request):
        customer = request.user.customer
        cashback_transactions = CustomerWalletHistory.objects.filter(customer=customer).order_by(
            '-id'
        )
        list_cashback_transactions = []
        for trx in cashback_transactions:
            if trx.change_reason == 'sepulsa_purchase':
                sepulsa_transaction = trx.sepulsa_transaction
                product = sepulsa_transaction.product
                dict_sepulsa_transaction = {}
                dict_sepulsa_transaction['cdate'] = timezone.localtime(sepulsa_transaction.cdate)
                dict_sepulsa_transaction['transaction_id'] = sepulsa_transaction.id
                dict_sepulsa_transaction['type_transaction'] = get_type_transaction_sepulsa_product(
                    product
                )
                dict_sepulsa_transaction['phone_number'] = sepulsa_transaction.phone_number
                dict_sepulsa_transaction['product_name'] = product.product_name
                dict_sepulsa_transaction['customer_price'] = product.customer_price
                dict_sepulsa_transaction['nominal_product'] = product.product_nominal
                dict_sepulsa_transaction[
                    'transaction_status'
                ] = sepulsa_transaction.transaction_status
                if product.operator:
                    dict_sepulsa_transaction['operator_name'] = product.operator.name
                elif product.type == 'electricity':
                    dict_sepulsa_transaction['operator_name'] = sepulsa_transaction.account_name

                dict_sepulsa_transaction['serial_number'] = sepulsa_transaction.serial_number
                dict_sepulsa_transaction['meter_number'] = sepulsa_transaction.customer_number
                list_cashback_transactions.append(dict_sepulsa_transaction)
            elif trx.change_reason == CashbackChangeReason.USED_ON_PAYMENT:
                amount = trx.wallet_balance_available_old - trx.wallet_balance_available
                if amount == 0:
                    continue
                payment = trx.payment
                dict_payment_transaction = {}
                dict_payment_transaction['cdate'] = timezone.localtime(trx.cdate)
                dict_payment_transaction['payment_number'] = payment.payment_number
                dict_payment_transaction['amount'] = amount
                dict_payment_transaction['type_transaction'] = 'payment'
                list_cashback_transactions.append(dict_payment_transaction)

            elif trx.change_reason == CashbackChangeReason.USED_TRANSFER:
                pending_status = [
                    CashbackTransferConst.STATUS_REQUESTED,
                    CashbackTransferConst.STATUS_APPROVED,
                    CashbackTransferConst.STATUS_PENDING,
                ]
                failed_status = [
                    CashbackTransferConst.STATUS_FAILED,
                    CashbackTransferConst.STATUS_REJECTED,
                ]
                cashback_transfer_trans = trx.cashback_transfer_transaction
                cashback_transfer_status = cashback_transfer_trans.transfer_status
                dict_transfer_trans = {}
                dict_transfer_trans['cdate'] = timezone.localtime(cashback_transfer_trans.cdate)
                dict_transfer_trans['transfer_id'] = cashback_transfer_trans.transfer_id
                dict_transfer_trans['type_transaction'] = 'transfer'

                if cashback_transfer_status in pending_status:
                    dict_transfer_trans['transfer_status'] = 'pending'
                elif cashback_transfer_status in failed_status:
                    dict_transfer_trans['transfer_status'] = 'failed'
                elif cashback_transfer_status == CashbackTransferConst.STATUS_COMPLETED:
                    dict_transfer_trans['transfer_status'] = 'success'

                dict_transfer_trans['transfer_amount'] = cashback_transfer_trans.transfer_amount
                dict_transfer_trans['bank_name'] = cashback_transfer_trans.bank_name
                dict_transfer_trans['bank_number'] = cashback_transfer_trans.bank_number
                dict_transfer_trans['name_in_bank'] = cashback_transfer_trans.name_in_bank
                list_cashback_transactions.append(dict_transfer_trans)

            elif trx.change_reason == CashbackChangeReason.GOPAY_TRANSFER:
                pending_status = (
                    GopayConst.PAYOUT_STATUS_QUEUED,
                    GopayConst.PAYOUT_STATUS_PROCESSED,
                )
                failed_status = (GopayConst.PAYOUT_STATUS_FAILED, GopayConst.PAYOUT_STATUS_REJECTED)
                try:
                    if not hasattr(trx, 'cashback_transfer_transaction'):
                        raise Exception("gopay transaction is not found")

                    cashback_transfer_trans = trx.cashback_transfer_transaction
                    cashback_transfer_status = cashback_transfer_trans.transfer_status
                    dict_transfer_trans = {}
                    dict_transfer_trans['cdate'] = timezone.localtime(cashback_transfer_trans.cdate)
                    dict_transfer_trans['transfer_id'] = cashback_transfer_trans.transfer_id
                    dict_transfer_trans['transfer_name'] = 'Transfer Gopay'
                    if cashback_transfer_status in pending_status:
                        dict_transfer_trans['transfer_status'] = 'pending'
                    elif cashback_transfer_status in failed_status:
                        dict_transfer_trans['transfer_status'] = 'failed'
                    elif cashback_transfer_status == GopayConst.PAYOUT_STATUS_COMPLETED:
                        dict_transfer_trans['transfer_status'] = 'success'

                    dict_transfer_trans['transfer_amount'] = cashback_transfer_trans.redeem_amount
                    dict_transfer_trans['type_transaction'] = 'gopay'
                    dict_transfer_trans['number_in_gopay'] = cashback_transfer_trans.bank_number
                    dict_transfer_trans['name_in_gopay'] = cashback_transfer_trans.name_in_bank
                    list_cashback_transactions.append(dict_transfer_trans)
                except Exception:
                    sentry_client = get_julo_sentry_client()
                    sentry_client.captureException()

            else:
                amount = trx.wallet_balance_available_old - trx.wallet_balance_available
                if amount == 0:
                    continue
                dict_payment_transaction = {}
                dict_payment_transaction['cdate'] = timezone.localtime(trx.cdate)
                dict_payment_transaction['amount'] = amount

                if trx.change_reason in [
                    CashbackChangeReason.LOAN_PAID_OFF,
                    CashbackChangeReason.PAYMENT_ON_TIME,
                ]:
                    dict_payment_transaction['type_transaction'] = trx.change_reason
                elif trx.change_reason == 'sepulsa_refund':
                    dict_payment_transaction['type_transaction'] = 'Refund'
                elif trx.change_reason == 'cfs_claim_reward':
                    dict_payment_transaction['type_transaction'] = 'Klaim Misi'
                    dict_payment_transaction['transaction_note'] = get_cfs_transaction_note(trx.id)
                else:
                    dict_payment_transaction['type_transaction'] = trx.change_reason.replace(
                        "_", " "
                    ).title()
                list_cashback_transactions.append(dict_payment_transaction)

        logger.info(
            {
                'message': 'get_transaction_cahsback_disbursement',
                'balance': customer.wallet_balance_available,
                'transactions': list_cashback_transactions,
            },
            request=request,
        )
        return Response(
            {
                'balance': customer.wallet_balance_available,
                'transactions': list_cashback_transactions,
            }
        )


class SepulsaProductList(APIView):
    """
    endpoint Sepulsa Product List
    """

    serializer_class = SepulsaProductListSerializer

    def get(self, request):
        serializer = self.serializer_class(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.data
        sepulsa_product = list(
            SepulsaProduct.objects.filter(
                type=data['type'],
                category=data['category'],
                operator_id=data['mobile_operator_id'],
                is_active=True,
            )
            .order_by('product_nominal')
            .values()
        )
        return Response(
            status=HTTP_200_OK, data={'is_success': True, 'sepulsa_products': list(sepulsa_product)}
        )


class CashbackFormInfo(APIView):
    """
    endpoint Cashback to Sepulsa
    """

    def get(self, request):
        customer = request.user.customer
        mobile_operators = MobileOperator.objects.filter(is_active=True)
        list_prefix_operator = []
        for operator in mobile_operators:
            for initial_number in operator.initial_numbers:
                prefix_operator_dict = {}
                prefix_operator_dict['number'] = initial_number
                prefix_operator_dict['id'] = operator.id
                prefix_operator_dict['name'] = operator.name
                list_prefix_operator.append(prefix_operator_dict)
        logger.info(
            {
                'message': 'get_data_cashback_disbursement',
                'prefix_operators': list_prefix_operator,
                'balance': customer.wallet_balance_available,
            }
        )
        return Response(
            {'prefix_operators': list_prefix_operator, 'balance': customer.wallet_balance_available}
        )


class CashbackSepulsa(APIView):
    """
    endpoint Cashback to sepulsa
    """

    serializer_class = CashbackSepulsaSerializer

    def post(self, request):
        cashback_sepulsa_enable = is_cashback_method_active(CashbackMethodName.SEPULSA)
        if not cashback_sepulsa_enable:
            return general_error_response(
                'Pencairan cashback melalui metode ini untuk sementara tidak dapat dilakukan'
            )

        customer = request.user.customer
        if customer.is_cashback_freeze:
            return response_failed(CASHBACK_FROZEN_MESSAGE)
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.data
        try:
            (
                product,
                sepulsa_transaction,
                balance,
            ) = cashback_redemption_service.trigger_partner_purchase(data, customer)
        except JuloException as e:
            return response_failed(str(e))
        return Response(
            {
                'is_success': True,
                'product': model_to_dict(product),
                'transaction': model_to_dict(sepulsa_transaction),
                'balance': balance,
            }
        )


class CashbackPayment(APIView):
    """
    endpoint Cashback to payment
    """

    def post(self, request):
        customer = request.user.customer
        try:
            status = cashback_redemption_service.pay_next_loan_payment(customer)
            if status:
                return Response(
                    {
                        'is_success': True,
                        'message': 'create transaction successfull.',
                        'balance': customer.wallet_balance_available,
                    }
                )
            else:
                return response_failed(ERROR_MESSAGE_TEMPLATE_4)
        except DuplicateCashbackTransaction:
            return response_failed(
                'Terdapat transaksi yang sedang dalam proses, ' 'Coba beberapa saat lagi.'
            )
        except BlockedDeductionCashback:
            return response_failed(
                'Mohon maaf, saat ini cashback tidak bisa digunakan ' 'karena program keringanan'
            )
        except Exception:
            julo_sentry_client.captureException()
            return response_failed(ERROR_MESSAGE_TEMPLATE_1)


class CashbackSepulsaInqueryElectricity(APIView):
    """
    endpoint Sepulsa inquery account electricity.
    """

    serializer_class = SepulsaInqueryElectricitySerializer

    def get(self, request):
        serializer = self.serializer_class(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.data
        try:
            sepulsa_service = SepulsaService()
            response = sepulsa_service.get_account_electricity_info(
                data['meter_number'], data['product_id']
            )
            if response['response_code'] in SepulsaResponseCodes.SUCCESS:
                return Response(status=HTTP_200_OK, data={'is_success': True, 'content': response})

            elif (
                response['response_code']
                in SepulsaResponseCodes.FAILED_VALIDATION_ELECTRICITY_ACCOUNT
            ):
                return response_failed(ERROR_MESSAGE_TEMPLATE_5)
            else:
                logger.info(
                    {
                        "action": "juloserver.apiv2.views.CashbackSepulsaInqueryElectricity",
                        "message": "sepulsa electricity inquiry failed",
                        "response": response,
                    }
                )
                return response_failed(ERROR_MESSAGE_TEMPLATE_1)
        except Exception:
            julo_sentry_client.captureException()
            return response_failed(ERROR_MESSAGE_TEMPLATE_1)


class CashbackTransfer(generics.ListCreateAPIView):
    """
    endpoimt Redeem Cashback
    """

    model_class = CashbackTransferTransaction
    serializer_class = CashbackTransferSerializer

    def post(self, request, *args, **kwargs):
        xendit_enable = is_cashback_method_active(CashbackMethodName.XENDIT)
        if not xendit_enable:
            return general_error_response(
                'Pencairan cashback melalui metode ini untuk sementara tidak dapat dilakukan'
            )

        customer = request.user.customer
        if customer.is_cashback_freeze:
            return response_failed(CASHBACK_FROZEN_MESSAGE)

        # last_application
        application = get_last_application(customer)
        if not application:
            raise ResourceNotFound(resource_id=application.id)

        try:
            with transaction.atomic():
                try:
                    customer = (
                        Customer.objects.select_for_update(nowait=True)
                        .filter(id=customer.id)
                        .first()
                    )
                except DatabaseError:
                    return response_failed(ERROR_MESSAGE_TEMPLATE_3)

                cashback_available = customer.wallet_balance_available
                # check cashback amount
                if cashback_available < CashbackTransferConst.MIN_TRANSFER:
                    return response_failed(ERROR_MESSAGE_TEMPLATE_2)
                current_cashback_transfer = (
                    customer.cashbacktransfertransaction_set.exclude(
                        transfer_status__in=CashbackTransferConst.FINAL_STATUSES
                    )
                    .exclude(bank_code=GopayConst.BANK_CODE)
                    .last()
                )
                if current_cashback_transfer:
                    return response_failed(ERROR_MESSAGE_TEMPLATE_3)
                bank = BankManager.get_by_name_or_none(application.bank_name)
                bank_number = application.bank_account_number
                name_in_bank = application.name_in_bank
                transfer_amount = cashback_available - CashbackTransferConst.ADMIN_FEE
                partner_transfer = CashbackTransferConst.METHOD_XFERS
                if 'bca' in application.bank_name.lower():
                    partner_transfer = CashbackTransferConst.METHOD_BCA

                cashback_transfer = CashbackTransferTransaction.objects.create(
                    customer=customer,
                    application=application,
                    transfer_amount=transfer_amount,
                    redeem_amount=cashback_available,
                    transfer_status=CashbackTransferConst.STATUS_REQUESTED,
                    bank_name=application.bank_name,
                    bank_code=bank.bank_code,
                    bank_number=bank_number,
                    name_in_bank=name_in_bank,
                    partner_transfer=partner_transfer,
                )
                cashback_service = CashbackRedemptionService()
                cashback_service.process_transfer_reduction_wallet_customer(
                    customer, cashback_transfer
                )
                balance = customer.wallet_balance_available

            try:
                if cashback_transfer:
                    cashback_transfer_transaction_id = cashback_transfer.id
                    cashback_transfer = CashbackTransferTransaction.objects.get_or_none(
                        id=cashback_transfer_transaction_id
                    )
                    status = cashback_transfer.transfer_status
                    if status == CashbackTransferConst.STATUS_REQUESTED:
                        with transaction.atomic():
                            # choose transfer method
                            if 'bca' in cashback_transfer.bank_name.lower():
                                cashback_transfer.partner_transfer = (
                                    CashbackTransferConst.METHOD_BCA
                                )
                            else:
                                cashback_transfer.partner_transfer = (
                                    CashbackTransferConst.METHOD_XFERS
                                )

                            cashback_transfer.transfer_status = (
                                CashbackTransferConst.STATUS_APPROVED
                            )
                            cashback_transfer.save()
                            cashback_redemption_service.transfer_cashback(cashback_transfer)

            except Exception:
                julo_sentry_client.captureException()
                return Response(
                    {
                        'is_success': True,
                        'transaction': model_to_dict(cashback_transfer),
                        'balance': balance,
                    }
                )
        except Exception:
            julo_sentry_client.captureException()
            return response_failed(ERROR_MESSAGE_TEMPLATE_1)

        return Response(
            {
                'is_success': True,
                'transaction': model_to_dict(cashback_transfer),
                'balance': balance,
            }
        )

    def list(self, request, *args, **kwargs):
        customer = self.request.user.customer
        queryset = CashbackTransferTransaction.objects.filter(customer=customer)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class CashbackLastBankInfo(APIView):
    """
    endpoint to get customer last bank info
    """

    def get(self, request):
        customer = request.user.customer
        last_application = get_last_application(customer)
        if not last_application:
            return response_failed('customer has no active loan')

        bank = BankManager.get_by_name_or_none(last_application.bank_name)
        data = {
            'bank_name': last_application.bank_name,
            'bank_code': bank.bank_code,
            'name_in_bank': last_application.name_in_bank,
            'bank_account_number': last_application.bank_account_number,
            'min_transfer_amount': CashbackTransferConst.MIN_TRANSFER,
            'admin_fee_amount': CashbackTransferConst.ADMIN_FEE,
        }

        return Response(data)


class StatusLabelView(APIView):
    model_class = StatusLabel

    def get(self, request):
        application_id = request.query_params.get('application_id', None)
        application = Application.objects.get_or_none(pk=application_id)
        if not application:
            return Response(
                status=HTTP_404_NOT_FOUND,
                data={'success': False, 'error_message': 'Application not found'},
            )
        user = self.request.user

        if user.id != application.customer.user_id:
            return Response(
                status=HTTP_403_FORBIDDEN, data={'errors': 'User not allowed', 'user_id': user.id}
            )

        if application.status == ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL:
            status = application.loan.status
        else:
            status = application.status
        status_label = StatusLabel.objects.get_or_none(status=status)
        if status_label:
            return Response(
                {
                    'application_id': application.id,
                    'status_label': status_label.label_name,
                    'status_color': status_label.label_colour,
                    'product_name': (
                        application.product_line.product_line_type
                        if application.product_line
                        else None
                    ),
                    'loan_month_duration': (
                        application.loan.loan_duration if hasattr(application, 'loan') else None
                    ),
                    'apply_date': application.cdate,
                    'is_success': True,
                }
            )

        return Response(
            status=HTTP_404_NOT_FOUND, data={'not_found_status_label': application.status}
        )


class ApplicationReapplyView(APIView):
    model_class = Application
    serializer_class = ReapplySerializer

    def post(self, request):
        user = request.user
        if is_active_julo1():
            return Response(
                status=HTTP_400_BAD_REQUEST, data={'message': 'No longer available for this user'}
            )

        request_data = self.serializer_class(data=request.data)
        request_data.is_valid()
        customer = user.customer
        customer.update_safely(is_review_submitted=False)

        if request_data.data.get('mother_maiden_name', None):
            customer.mother_maiden_name = request_data.data['mother_maiden_name']
            customer.save()
        if not customer.can_reapply:
            logger.warning(
                {
                    'message': 'creating application when can_reapply is false',
                    'customer_id': customer.id,
                },
                request=request,
            )
            return Response(
                failure_template(ErrorCode.CUSTOMER_REAPPLY, ErrorMessage.CUSTOMER_REAPPLY)
            )

        # get device and app_version
        device_id = int(request.data['device_id'])
        device = Device.objects.get_or_none(id=device_id, customer=customer)
        if device is None:
            raise ResourceNotFound(resource_id=device_id)
        app_version = request.data['app_version']

        # get last application
        last_application = customer.application_set.regular_not_deletes().last()
        if not last_application:
            return Response(
                status=HTTP_404_NOT_FOUND, data={'message': 'customer has no application'}
            )
        last_application_number = last_application.application_number
        if not last_application_number:
            last_application_number = 1
        application_number = last_application_number + 1

        data_to_save = {'application_number': application_number}

        # check duration
        today = timezone.now().date()
        date_apply = last_application.cdate.date()
        day_range = (today - date_apply).days
        fields = [
            'marketing_source',
            'is_own_phone',
            'mobile_phone_1',
            'fullname',
            'dob',
            'gender',
            'ktp',
            'email',
            'bbm_pin',
            'twitter_username',
            'instagram_username',
            'marital_status',
            'dependent',
            'spouse_name',
            'spouse_dob',
            'close_kin_name',
            'close_kin_mobile_phone',
            'close_kin_relationship',
            'birth_place',
            'kin_name',
            'kin_dob',
            'kin_gender',
            'kin_mobile_phone',
            'kin_relationship',
            'last_education',
            'college',
            'major',
            'graduation_year',
            'gpa',
            'vehicle_type_1',
            'vehicle_ownership_1',
            'bank_name',
            'bank_branch',
            'bank_account_number',
            'name_in_bank',
            'address_kabupaten',
            'address_kecamatan',
            'address_kelurahan',
            'address_kodepos',
            'address_provinsi',
            'address_street_num',
            'home_status',
            'occupied_since',
            'job_description',
            'job_function',
            'job_industry',
            'job_start',
            'job_type',
            'company_name',
            'company_phone_number',
            'payday',
        ]

        if day_range <= 30:
            fields += [
                'billing_office',
                'company_address',
                'employment_status',
                'has_other_income',
                'has_whatsapp_1',
                'has_whatsapp_2',
                'hrd_name',
                'income_1',
                'income_2',
                'income_3',
                'landlord_mobile_phone',
                'monthly_expenses',
                'monthly_housing_cost',
                'monthly_income',
                'mutation',
                'number_of_employees',
                'other_income_amount',
                'other_income_source',
                'position_employees',
                'spouse_has_whatsapp',
                'spouse_mobile_phone',
                'total_current_debt',
                'work_kodepos',
                'mantri_id',
            ]

        if last_application.mantri_id:
            fields += ['referral_code']

        for field in fields:
            data_to_save[field] = getattr(last_application, field)

        serializer = ApplicationSerializer(data=data_to_save)
        serializer.is_valid(raise_exception=True)

        try:
            with transaction.atomic():
                application = serializer.save(
                    customer=last_application.customer, device=device, app_version=app_version
                )
                images = Image.objects.filter(
                    image_source=last_application.id,
                    image_type__in=('ktp_self', 'selfie', 'crop_selfie'),
                )
                for image in images:
                    Image.objects.create(
                        image_source=application.id,
                        image_type=image.image_type,
                        url=image.url,
                        image_status=image.image_status,
                        thumbnail_url=image.thumbnail_url,
                        service=image.service,
                    )

                logger.info(
                    {
                        'message': 'application reapply',
                        'status': 'form_created',
                        'application': application,
                        'customer': customer,
                        'device': application.device,
                    },
                    request=request,
                )

                if day_range <= 30 and last_application.mantri_id:
                    # Set mantri id if referral code is a mantri id
                    referral_code = data_to_save['referral_code']
                    if referral_code:
                        referral_code = referral_code.replace(' ', '')
                        mantri_obj = Mantri.objects.get_or_none(code__iexact=referral_code)
                        application.mantri = mantri_obj
                        application.save(update_fields=['mantri'])

                link_to_partner_if_exists(application)

                process_application_status_change(
                    application.id,
                    ApplicationStatusCodes.FORM_CREATED,
                    change_reason='customer_triggered',
                )

            create_application_checklist_async.delay(application.id)
            application.refresh_from_db()
            final_respone = serializer.data.copy()
            final_respone['mother_maiden_name'] = customer.mother_maiden_name

            return Response(success_template(final_respone))
        except Exception:
            julo_sentry_client.captureException()
            return Response(failure_template(ErrorCode.CUSTOMER_REAPPLY, ErrorMessage.GENERAL))


class CombinedHomeScreen(generics.ListAPIView):
    """
    end point for home screen page
    """

    def get(self, request, *args, **kwargs):
        cards = []
        # user = request.user
        customer = request.user.customer
        application_id = request.query_params.get('application_id', None)
        include_deleted = request.query_params.get('voice_records_include_deleted', 'false')
        app_version = request.query_params.get('app_version', None)
        partner_name = request.query_params.get('partner_name', None)
        apps = (
            Application.objects.regular_not_deletes().filter(customer=customer).order_by('-id')[:2]
        )
        application = apps[0] if len(apps) > 0 else None
        loan = Loan.objects.get_or_none(application=application.id) if application else None

        account_summary_cards = render_account_summary_cards(customer, application)
        for account_summary_card in account_summary_cards:
            cards.append(account_summary_card)
        # hide Julo Mini to remove STL product from APP for google rules
        # only show JULO mini banner for 105
        # if application.application_status.status_code == ApplicationStatusCodes.FORM_PARTIAL:
        #     cards.append(render_julomini_card())

        sphp_card = render_sphp_card(customer, application)
        if sphp_card is not None:
            cards.append(sphp_card)
        cards = get_android_card_from_database(cards)

        today_date = timezone.localtime(timezone.now()).date()
        promotion_card = create_june2022_promotion_card(loan, today_date)
        if loan is not None and promotion_card is not None:
            cards.insert(1, promotion_card)
        if application:
            if (
                application.status
                == ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING
                and not is_bank_name_validated(application)
            ):
                cards.insert(0, create_bank_validation_card(application=application))

            if application.status == ApplicationStatusCodes.NAME_VALIDATE_FAILED:
                cards.insert(0, create_bank_validation_card(from_status='from_175'))

        # this for sold off loan handler
        if loan and loan.loan_status_id == LoanStatusCodes.SELL_OFF:
            sell_off_card = render_loan_sell_off_card(loan)
            if sell_off_card:
                cards = [sell_off_card]
        # output it
        result_homescreen = []
        for i, v in enumerate(cards):
            if isinstance(v, dict):
                displayed_card = {
                    'position': i + 1,
                    'header': v['header'],
                    'topimage': v['topimage'],
                    'body': v['body'],
                    'bottomimage': v['bottomimage'],
                    'buttontext': v['buttontext'],
                    'buttonurl': v['buttonurl'],
                    'buttonstyle': v['buttonstyle'],
                }
                if v['expired_time']:
                    displayed_card.update({'expired_time': v['expired_time']})
                if v['data']:
                    displayed_card.update({'data': v['data']})
                result_homescreen.append(displayed_card)

        if application:
            # image step
            if application.application_status_id and result_homescreen:
                result = result_homescreen[0]
                status_images_1 = (
                    ApplicationStatusCodes.FORM_PARTIAL,
                    ApplicationStatusCodes.FORM_SUBMITTED,
                )
                status_images_2 = (
                    ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
                    ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
                    ApplicationStatusCodes.DOCUMENTS_VERIFIED,
                    ApplicationStatusCodes.CALL_ASSESSMENT,
                    ApplicationStatusCodes.PRE_REJECTION,
                    ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
                    ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
                    ApplicationStatusCodes.APPLICATION_RESUBMITTED,
                    ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
                    ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING,
                    ApplicationStatusCodes.OFFER_MADE_TO_CUSTOMER,
                    ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
                    ApplicationStatusCodes.NAME_BANK_VALIDATION_FAILED,
                )
                status_images_3 = (
                    ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
                    ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING,
                    ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED,
                    ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED,
                    ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED_AND_DP_PENDING,
                    ApplicationStatusCodes.DOWN_PAYMENT_PAID,
                )
                if application.application_status_id in status_images_1:
                    result['headerimageurl'] = 'https://www.julo.co.id/images/ic_home_1.png'
                elif application.application_status_id in status_images_2:
                    result['headerimageurl'] = 'https://www.julo.co.id/images/ic_home_2.png'
                elif application.application_status_id in status_images_3:
                    result['headerimageurl'] = 'https://www.julo.co.id/images/ic_home_3.png'
                result_homescreen[0] = result
        result = {}
        is_show, referral_content = get_referral_home_content(customer, application, app_version)
        if is_show:
            result_homescreen.append(referral_content)
        result['banner'] = []
        result['homescreen'] = result_homescreen

        # customer action
        actions_json = get_customer_app_actions(customer, app_version)

        # device app actions
        device = customer.device_set.last()
        if device:
            device_app_actions = get_device_app_actions(device, app_version)
            result['device_app_action'] = device_app_actions

        if does_user_have_pin(
            customer.user
        ) and CustomerPinChangeService.check_password_is_out_date(customer.user):
            if actions_json['actions']:
                actions_json['actions'].append('pin_is_outdated')
            else:
                actions_json['actions'] = ['pin_is_outdated']
        result['customer_action'] = actions_json

        # applications
        result['applications'] = ApplicationSerializer(apps, many=True).data

        # customers
        result['customers'] = CustomerSerializer([customer], many=True).data
        for _customer in result['customers']:
            _customer['nik'] = get_customer_nik(customer)

        # cashback balance
        result['cashback_balance'] = customer.wallet_balance_available

        # voice-records
        result['voice_records'] = []
        if application and application_id:
            voice_records = VoiceRecord.objects.filter(application=application.id)
            if include_deleted == 'false':
                voice_records = voice_records.exclude(status=VoiceRecord.DELETED)
            result['voice_records'] = VoiceRecordHyperSerializer(voice_records, many=True).data

        result['product_lines'] = []
        product_lines = get_product_lines(customer, application)
        result['product_lines'] = ProductLineSerializer(product_lines, many=True).data
        login_check, error_message = prevent_web_login_cases_check(customer.user, partner_name)
        result['eligible_access'] = {'is_eligible': login_check, 'error_message': error_message}
        if application:
            result = update_response_false_rejection(application, result)
            if check_fraud_model_exp(application):
                result = update_response_fraud_experiment(result)

        return Response({"success": True, "content": result})


class ProductLineListView(generics.ListAPIView):
    model_class = ProductLine
    serializer_class = ProductLineSerializer
    queryset = ProductLine.objects.all()

    def get_queryset(self):
        application_id = self.request.query_params.get('application_id', None)
        customer = self.request.user.customer

        try:
            application = Application.objects.get_or_none(pk=application_id)
        except ValueError:
            application = None

        return get_product_lines(customer, application)


class CollateralDropDown(APIView):
    """
    endpoint to retrieve dropdown for collateral product
    """

    def get(self, request, *args, **kwargs):
        # user = request.user
        print(CollateralDropdown.DROPDOWN_DATA)
        return Response({"success": True, "content": CollateralDropdown.DROPDOWN_DATA})


class UpdateGmailAuthToken(APIView):
    # Update google auth token

    def post(self, request):
        # temporary revert until gmail scrapping issue fixed
        # if 'gmail_auth_token' not in request.data:
        #     return Response(status=HTTP_400_BAD_REQUEST,
        #                     data={'gmail_auth_token': "This field is required"})
        # gmail_auth_token = request.data.get('gmail_auth_token', '')
        # customer = self.request.user.customer
        # try:
        #     scope = [
        #         'https://www.googleapis.com/auth/gmail.readonly',
        #         'https://www.googleapis.com/auth/contacts.readonly',
        #         'https://www.googleapis.com/auth/calendar'
        #     ]
        #     google_credent = oauth2_client.credentials_from_clientsecrets_and_code(
        #         settings.GOOGLE_CLIENT_SECRET, scope, gmail_auth_token,
        #         redirect_uri=settings.GOOGLE_AUTH_CALLBACK
        #     )
        # except Exception as e:
        #     return Response(status=HTTP_400_BAD_REQUEST,
        #                     data={'gmail_auth_token': e.message})
        #
        # if google_credent.access_token and google_credent.refresh_token :
        #     customer.google_access_token = google_credent.access_token
        #     customer.google_refresh_token = google_credent.refresh_token
        #     customer.save()
        #     print(customer.email)
        return Response({'message': "Oauth2 scope updated"})


class SkiptraceView(APIView):
    """
    end point for Skiptrace
    """

    def get(self, request, *args, **kwargs):
        selected = request.query_params.get('selected', None)
        customer = request.user.customer
        setting = MobileFeatureSetting.objects.get(feature_name="guarantor-contact")
        max = int(setting.parameters['max_phonenumbers'])

        if selected:
            skiptrace_list = customer.skiptrace_set.filter(is_guarantor=True).order_by('id')
            contact = SkipTraceSerializer(skiptrace_list, many=True).data
        else:
            contact = []
            limit = 5 if max > 5 else max
            phonebook = customer.skiptrace_set.filter(contact_source='phonebook')[0:limit]
            contact.append(SkipTraceSerializer(phonebook, many=True).data)
            res = max - len(phonebook)
            if res:
                limit = 5 if res > 5 else res
                call = customer.skiptrace_set.filter(contact_source='call_history')[0:limit]
                res = limit - len(call)
                contact.append(SkipTraceSerializer(call, many=True).data)
                if res:
                    limit = 5 if res > 5 else res
                    sms = customer.skiptrace_set.filter(contact_source='sms')[0:limit]
                    contact.append(SkipTraceSerializer(sms, many=True).data)
            contact = [item for sublist in contact for item in sublist]

        return Response({"success": True, "content": contact})

    def post(self, request):
        user = self.request.user
        customer = user.customer
        # get phonenumber list
        if 'guarantors' not in request.data:
            return Response(
                status=HTTP_400_BAD_REQUEST, data={'guarantors': 'This field is required'}
            )
        guarantors = request.data['guarantors']
        try:
            with transaction.atomic():
                skiptrace_list = customer.skiptrace_set.all()
                skiptrace_list.update(is_guarantor=False)
                for guarantor in guarantors:
                    skiptrace = customer.skiptrace_set.get(phone_number=guarantor)
                    if skiptrace:
                        skiptrace.is_guarantor = True
                        skiptrace.save()
            return Response({"success": True, "message": "Kontak berhasil disimpan"})
        except Exception:
            return Response(
                status=HTTP_404_NOT_FOUND,
                data={'success': False, 'error_message': 'Kontak tidak ditemukan'},
            )


class GuarantorContactSettingView(APIView):
    """
    end point for Skiptrace
    """

    def get(self, request, *args, **kwargs):
        setting = MobileFeatureSetting.objects.get_or_none(feature_name='guarantor-contact')
        params = setting.parameters
        params["waiting_time"] = params["waiting_time_sec"] * 1000
        del params["waiting_time_sec"]
        params.update({"active": setting.is_active})
        return Response({"success": True, "content": params})


class ApplicationOtpSettingView(APIView):
    def get(self, request, *args, **kwargs):
        """
        Indicate whether the OTP verification to verify mobile phone in
        application is turned on or off
        """
        mfs = MobileFeatureSetting.objects.get_or_none(feature_name='mobile_phone_1_otp')
        return Response(
            {"success": True, "content": {"active": mfs.is_active, "parameters": mfs.parameters}}
        )


class ChatBotSetting(APIView):
    """
    end point for enable/disable chat bot on apps
    """

    def get(self, request, format=None):
        setting = MobileFeatureSetting.objects.get_or_none(feature_name='chat-bot')
        params = {"active": setting.is_active}
        return Response({"success": True, "content": params})


class CashbackBar(APIView):
    """
    end point for Cashback Bar
    """

    def get(self, request, *args, **kwargs):
        customer = request.user.customer
        params = {}
        application = customer.application_set.get_or_none(
            pk=int(request.query_params.get('application_id', None))
        )
        not_found = Response(
            status=HTTP_400_BAD_REQUEST,
            data={"success": False, "content": {}, 'error_message': 'Aplikasi tidak ditemukan'},
        )
        if not application:
            return not_found
        if not application.product_line:
            return not_found
        if application.product_line.product_line_code not in ProductLineCodes.mtl():
            return not_found
        if hasattr(application, "loan"):
            loan = application.loan
            if loan.status < LoanStatusCodes.CURRENT:
                return Response(
                    status=HTTP_400_BAD_REQUEST,
                    data={
                        "success": False,
                        "content": {},
                        'error_message': 'Tidak ada pinjaman aktif',
                    },
                )
            params['installment_duration'] = loan.loan_duration
            params['number_of_paid_installment'] = len(
                loan.payment_set.filter(
                    payment_status_id__in=PaymentStatusCodes.paid_status_codes()
                )
            )
            params['number_ontime_installment'] = loan.get_ontime_payment()
            params['cashback'] = loan.payment_set.paid().aggregate(total=Sum('cashback_earned'))[
                'total'
            ]
        else:
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={"success": False, "content": {}, 'error_message': 'Pinjaman tidak ditemukan'},
            )

        return Response({"success": True, "content": params})


class UnpaidPaymentPopupView(APIView):
    """
    endpoint Cashback to Sepulsa
    """

    def get(self, request):
        return Response(status=HTTP_200_OK, data=None)

        # Obsolete MTL API. If need revert, (was previously commented because
        #       MTL API that accidentally still being hit by old J1 apk.
        # )
        # check: https://juloprojects.atlassian.net/browse/RP-482.


class FacebookDataView(APIView):
    """
    API for creating and Update FacebookData.
    """

    def post(self, request, format=None):
        serializer = FacebookDataCreateUpdateSerializer(
            data=request.POST, context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        request_data = serializer.validated_data
        customer = Customer.objects.get(id=request.user.customer.id)
        query = customer.application_set
        application = query.filter(id=request_data.get('application_id')).first()
        if application_have_facebook_data(application):
            facebookdata = update_facebook_data(application, request_data)
            return Response(status=HTTP_200_OK, data=FacebookDataSerializer(facebookdata).data)
        else:
            facebookdata = add_facebook_data(application, request_data)
            return Response(status=HTTP_201_CREATED, data=FacebookDataSerializer(facebookdata).data)


class VersionCheckView(generics.ListAPIView):
    """
    end point for privacy
    """

    permission_classes = []
    authentication_classes = []

    def get(self, request, *args, **kwargs):
        if 'version_name' not in request.query_params:
            return Response(
                status=HTTP_400_BAD_REQUEST, data={'version_name': 'This field is required'}
            )
        app_version = request.query_params.get('version_name', None)
        action = ""
        latest_version = AppVersion.objects.filter(status='latest').last()
        if app_version:
            current_version = AppVersion.objects.get_or_none(app_version=app_version)
            if current_version:
                if current_version.status == 'not_supported':
                    action = 'force_upgrade'
                elif current_version.status == 'deprecated':
                    action = 'warning_upgrade'

                logger.info(
                    {
                        "message": "Version check OK",
                        "action_version": action,
                        "latest_version_id": latest_version.id,
                        "latest_version_name": latest_version.app_version,
                        "current_version_id": current_version.id,
                        "current_version_status": current_version.status,
                    },
                    request=request,
                )
                return Response(
                    {
                        "success": True,
                        "content": {
                            "action": action,
                            "latest_version_id": latest_version.id,
                            "latest_version_name": latest_version.app_version,
                            "current_version_id": current_version.id,
                            "current_version_status": current_version.status,
                        },
                    }
                )
            else:
                logger.warning(message="App version not found", request=request)
                return Response(
                    status=HTTP_400_BAD_REQUEST,
                    data={
                        "success": False,
                        "content": {},
                        'error_message': 'app_version not found',
                    },
                )


class PromoInfoView(APIView):
    permission_classes = (AllowAny,)
    """
    API to record customer who click the banner
    """

    def get(self, request, customer_id):
        if Customer.objects.get_or_none(pk=customer_id) is None:
            return render(request, '404-promo.html')

        last_days_delta = 3

        promo_history = PromoHistory.objects.get_or_none(
            customer_id=customer_id, promo_type=PromoType.RUNNING_PROMO
        )

        if promo_history is not None:
            oldest_payment = promo_history.loan.get_oldest_unpaid_payment()
            if not oldest_payment:
                return render(request, '404-promo.html')
            last_date_payment_promo = oldest_payment.due_date - relativedelta(days=last_days_delta)

            return render(request, promo_history.promo_type, {'due_date': last_date_payment_promo})

        loan = Loan.objects.filter(customer_id=customer_id).last()
        oldest_payment = loan.get_oldest_unpaid_payment()
        if not oldest_payment:
            return render(request, '404-promo.html')
        last_date_payment_promo = oldest_payment.due_date - relativedelta(days=last_days_delta)

        PromoHistory.objects.create(
            customer_id=customer_id,
            loan=loan,
            promo_type=PromoType.RUNNING_PROMO,
            payment=oldest_payment,
        )

        return render(request, PromoType.RUNNING_PROMO, {'due_date': last_date_payment_promo})


class SubmitProduct(APIView):
    """
    API endpoint for product submission
    """

    serializer_class = SubmitProductSerializer

    def put(self, request, application_id):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={"success": False, "content": {}, "error_message": serializer.errors},
            )

        data = serializer.validated_data
        application = check_application(
            application_id
        )  # check if application exist, return 400 if not found
        customer = self.request.user.customer

        if customer.user_id != application.customer.user_id:
            return Response(
                status=HTTP_403_FORBIDDEN,
                data={'errors': 'User not allowed', 'user_id': customer.user_id},
            )

        if application.status not in (
            ApplicationStatusCodes.FORM_PARTIAL,
            ApplicationStatusCodes.FORM_SUBMITTED,
        ):  # 110 or 105:
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={
                    "success": False,
                    "content": {},
                    'error_message': 'app_status %s is not allowed to submit product'
                    % application.status,
                },
            )

        try:
            product_line = determine_product_line_v2(
                customer, data['product_line_code'], data['loan_duration_request']
            )
        except KeyError as e:
            error = APIException('{}: this field is required on product submission'.format(str(e)))
            error.status_code = 400
            raise error

        application.product_line = ProductLine.objects.get(pk=product_line)
        application.loan_duration_request = data['loan_duration_request']
        application.loan_amount_request = data['loan_amount_request']
        application.save()

        # set application workflow by product for application v3
        switch_to_product_default_workflow(application)
        create_application_original_task.delay(application.id)

        customer.fullname = application.fullname
        customer.phone = application.mobile_phone_1
        customer.save()

        link_to_partner_by_product_line(application)
        application.refresh_from_db()
        return Response(
            {
                "success": True,
                "content": {"application": ApplicationUpdateSerializer(application).data},
            }
        )


class SubmitDocumentComplete(UpdateAPIView):
    """
    API endpoint for flag document_submitted change app status to 120
    """

    @parse_device_ios_user
    def put(self, request, *args, **kwargs):
        """
        A post save behavior to update the application status when these fields
        are passed:
        * is_document_submitted
        * is_sphp_signed
        """

        application_id = kwargs.get('application_id')
        device_ios_user = kwargs.get(IdentifierKeyHeaderAPI.KEY_IOS_DECORATORS, {})
        application = check_application(
            application_id
        )  # check if application exist, return 400 if not found
        user = self.request.user

        if user.id != application.customer.user_id:
            return Response(
                status=HTTP_403_FORBIDDEN, data={'errors': 'User not allowed', 'user_id': user.id}
            )

        is_document_submitted_hsfbp = self.request.data.get('is_document_submitted_hsfbp')
        is_hsfbp_verification = HsfbpIncomeVerification.objects.filter(
            application_id=application.id,
        ).exists()
        if (
            is_document_submitted_hsfbp
            and str(is_document_submitted_hsfbp).lower() == 'true'
            and application.is_julo_one()
            and is_hsfbp_verification
        ):
            from juloserver.application_flow.services import check_and_move_status_hsfbp_submit_doc

            check_and_move_status_hsfbp_submit_doc(
                application=application, is_ios_device=True if device_ios_user else False
            )
            logger.info(
                {'message': '[x120_HSFBP] Submit Documents', 'application_id': application_id}
            )
            application.refresh_from_db()
            return Response(
                {
                    "success": True,
                    "content": {"application": ApplicationUpdateSerializer(application).data},
                }
            )

        if (
            is_experiment_application(application.id, 'ExperimentUwOverhaul')
            and application.is_julo_one()
        ):
            mandocs_overhaul_status_code = ApplicationStatusCodes.DOCUMENTS_SUBMITTED
        else:
            mandocs_overhaul_status_code = ApplicationStatusCodes.FORM_PARTIAL

        logger.info(
            {
                "function": "SubmitDocumentComplete.put",
                "application_id": application_id,
                "current_status": application.status,
                "is_underwriting_overhaul": is_experiment_application(
                    application.id, 'ExperimentUwOverhaul'
                ),
            }
        )

        is_document_submitted = self.request.data.get('is_document_submitted')
        if is_document_submitted:
            if application.status in (
                mandocs_overhaul_status_code,
                ApplicationStatusCodes.FORM_SUBMITTED,
                ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
            ):  # 110 or 105/106/120(in_experiment)
                if application.product_line.product_line_code in ProductLineCodes.ctl():
                    process_application_status_change(
                        application.id,
                        ApplicationStatusCodes.PENDING_PARTNER_APPROVAL,  # 129
                        change_reason='customer_triggered',
                    )
                else:
                    send_event_to_ga_task_async.apply_async(
                        kwargs={
                            'customer_id': application.customer.id,
                            'event': GAEvent.APPLICATION_MD,
                        }
                    )
                    if (
                        is_experiment_application(application.id, 'ExperimentUwOverhaul')
                        and application.is_julo_one()
                    ):
                        if application.status == ApplicationStatusCodes.DOCUMENTS_SUBMITTED:
                            # do checking for fraud
                            fraud_bpjs_or_bank_scrape_checking.apply_async(
                                kwargs={'application_id': application_id}
                            )

                        process_application_status_change(
                            application.id,
                            ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,  # 121
                            change_reason='customer_triggered',
                        )
                    else:
                        if application.status == ApplicationStatusCodes.FORM_PARTIAL:
                            # do checking for fraud
                            fraud_bpjs_or_bank_scrape_checking.apply_async(
                                kwargs={'application_id': application_id}
                            )

                        process_application_status_change(
                            application.id,
                            ApplicationStatusCodes.DOCUMENTS_SUBMITTED,  # 120
                            change_reason='customer_triggered',
                        )

            elif (
                application.status == ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED
                or application.status == ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED
            ):  # 131 or # 136
                application = Application.objects.get_or_none(pk=application.id)
                app_history = ApplicationHistory.objects.filter(
                    application=application,
                    status_new=ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
                ).last()
                repeat_face_recognition = [
                    ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
                    ApplicationStatusCodes.FACE_RECOGNITION_AFTER_RESUBMIT,
                    ApplicationStatusCodes.CALL_ASSESSMENT,
                ]
                result_face_recognition = AwsFaceRecogLog.objects.filter(
                    application=application
                ).last()
                face_recognition = FaceRecognition.objects.get_or_none(
                    feature_name='face_recognition', is_active=True
                )
                failed_upload_image_reasons = [
                    'failed upload selfie image',
                    'Passed KTP check & failed upload selfie image',
                ]
                change_reason = 'customer_triggered'
                # check if app_history from 120 or 1311
                if (
                    app_history.status_old in repeat_face_recognition
                    and application.product_line_code in ProductLineCodes.new_lended_by_jtp()
                    and result_face_recognition
                    and not result_face_recognition.is_quality_check_passed
                    and face_recognition
                    or (app_history.change_reason in failed_upload_image_reasons)
                    and face_recognition
                ):
                    application_status_code = ApplicationStatusCodes.FACE_RECOGNITION_AFTER_RESUBMIT
                else:
                    application_status_code = ApplicationStatusCodes.APPLICATION_RESUBMITTED
                    if (
                        app_history.status_old in repeat_face_recognition
                        and application.product_line_code in ProductLineCodes.new_lended_by_jtp()
                        and result_face_recognition
                        and not face_recognition
                        or (app_history.change_reason in failed_upload_image_reasons)
                        and not face_recognition
                    ):
                        application_status_code = ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
                        change_reason = 'Passed KTP Check'
                        customer_service = get_customer_service()
                        result_bypass = customer_service.do_high_score_full_bypass_or_iti_bypass(
                            application_id
                        )
                        if result_bypass:
                            application_status_code = result_bypass['new_status_code']
                            change_reason = result_bypass['change_reason']
                if application.status != ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER:
                    process_application_status_change(
                        application.id, application_status_code, change_reason=change_reason  # 132
                    )
            elif application.status == ApplicationStatusCodes.DIGISIGN_FACE_FAILED:  # 147
                process_application_status_change(
                    application.id,
                    ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING,  # 150
                    change_reason='customer_triggered',
                )
            elif application.status == ApplicationStatusCodes.NAME_VALIDATE_FAILED:
                process_application_status_change(
                    application.id,
                    ApplicationStatusCodes.BANK_NAME_CORRECTED,
                    change_reason='bank_book_uploaded',
                )

        is_sphp_signed = self.request.data.get('is_sphp_signed')
        if is_sphp_signed:
            if application.status in (
                ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
                ApplicationStatusCodes.LEGAL_AGREEMENT_RESUBMISSION_REQUESTED,
            ):
                feature_setting = MobileFeatureSetting.objects.filter(
                    feature_name='digisign_mode', is_active=True
                ).last()
                signature = SignatureMethodHistory.objects.get_or_none(
                    application_id=application.id, is_used=True, signature_method='Digisign'
                )
                change_reason = (
                    'digisign_triggered' if signature and feature_setting else 'customer_triggered'
                )
                process_application_status_change(
                    application.id,
                    ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED,
                    change_reason=change_reason,
                )

        application.refresh_from_db()

        return Response(
            {
                "success": True,
                "content": {"application": ApplicationUpdateSerializer(application).data},
            }
        )


class FAQDataView(ViewSet):
    """
    API for FAQ section.
    """

    serializer_class = FAQSerializer

    def get(self, request, section_id, format=None):
        queryset = FaqItem.objects.get_or_none(
            id=section_id, visible=True, section__is_security_faq=False
        )
        if not queryset:
            return Response(status=HTTP_400_BAD_REQUEST, data={'errors': ['Faq Item not found']})
        serializer = FAQItemsSerializer(queryset, many=False)
        return Response(serializer.data)

    def get_assist(self, request, format=None):
        contact = JuloContactDetail.objects.filter(visible=True).first()
        if contact:
            serializer = JULOContactSerializer(contact, many=False)
            return Response(serializer.data)
        return Response(
            status=HTTP_400_BAD_REQUEST,
            data={'errors': ['Data Not available contact ' 'your administrator to request data']},
        )

    def get_all(self, request, format=None):
        queryset = FaqSection.objects.filter(is_security_faq=False)
        contact = JuloContactDetail.objects.filter(visible=True).first()
        serializer = FAQSerializer(queryset, many=True)
        faqs = serializer.data
        if contact:
            contact_serializer = JULOContactSerializer(contact, many=False)
            contact_data = contact_serializer.data
            for idx, faq in enumerate(faqs):
                if faq['id'] == contact_serializer.data.get('section'):
                    contact_data['isContact'] = True
                    faqs[idx]['faq_items'].append(contact_data)
                    faqs[idx]['faq_items'] = sorted(
                        faqs[idx]['faq_items'], key=itemgetter('order_priority')
                    )
        return Response(faqs)


class MobileFeatureSettingView(APIView):
    """
    end point for Mobile feature settings
    """

    def get(self, request, *args, **kwargs):
        feature_name = request.GET.get('feature_name', '')
        if feature_name == 'failover_digisign':
            feature_name = 'digital_signature_failover'
        if not feature_name:
            logger.warning(
                {"message": "Parameter feature_name is required", "feature_name": feature_name},
                request=request,
            )
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={"success": False, "content": {}, "error_message": "feature_name is required"},
            )

        customer = request.user.customer
        if (
            customer
            and get_ongoing_account_deletion_request(customer)
            and feature_name in disabled_feature_setting_account_deletion
        ):
            return Response(
                {
                    "success": True,
                    "content": {
                        "active": False,
                        "paramater": {},
                    },
                }
            )

        feature_setting = MobileFeatureSetting.objects.get_or_none(feature_name=feature_name)
        if not feature_setting:
            logger.warning(message="Feature not found", request=request)
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={"success": False, "content": {}, "error_message": "feature not found"},
            )

        if feature_name == MobileFeatureNameConst.GOPAY_AUTODEBET_CONSENT:
            account = customer.account
            tnc_content = feature_setting.parameters.get('tnc_content')
            if tnc_content:
                modified_tnc_content = process_tnc_message_with_deduction_day(account, tnc_content)
                if modified_tnc_content:
                    feature_setting.parameters['tnc_content'] = modified_tnc_content

        if feature_name == MobileFeatureNameConst.CASHBACK_FAQS:
            # determine faq if user is cashback claim experiment
            feature_setting = determine_cashback_faq_experiment(customer.account, feature_setting)

        data = {"active": feature_setting.is_active, "paramater": feature_setting.parameters}

        logger.info({"message": "Get data mobile feature settings", "data": data}, request=request)
        return Response({"success": True, "content": data})


class DigisignRegisterView(APIView):
    def post(self, request, *args, **kwargs):
        digisign_client = get_julo_digisign_client()

        application_id = request.data['application_id']
        application = Application.objects.get_or_none(pk=application_id)

        user = self.request.user

        if user.id != application.customer.user_id:
            return Response(
                status=HTTP_403_FORBIDDEN, data={'errors': 'User not allowed', 'user_id': user.id}
            )

        return Response(digisign_client.register(request.data['application_id']))


class DigisignSendDocumentView(APIView):
    def post(self, request, *args, **kwargs):
        digisign_client = get_julo_digisign_client()
        application_id = request.data['application_id']
        application = Application.objects.get_or_none(pk=application_id)
        user = self.request.user

        if user.id != application.customer.user_id:
            return Response(
                status=HTTP_403_FORBIDDEN, data={'errors': 'User not allowed', 'user_id': user.id}
            )

        return Response(
            digisign_client.send_document(
                request.data['document_id'],
                request.data['application_id'],
                request.data['filename'],
            )
        )


class DigisignActivateView(APIView):
    def get(self, request, *args, **kwargs):
        digisign_client = get_julo_digisign_client()
        customer = self.request.user.customer
        application = customer.application_set.regular_not_deletes().last()

        try:
            html_webview = digisign_client.activation(
                customer.email, is_digisign_web_browser(application)
            )
        except JuloException:
            logger.error(
                {
                    "message": "Call api digisign activate failed",
                    "status": "digisign_activate_failed",
                    "customer_email": customer.email,
                }
            )
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={
                    "success": False,
                    "content": {},
                    "error_message": "Call api digisign activate failed",
                },
            )

        return StreamingHttpResponse(html_webview)


class DigisignSignDocumentView(APIView):
    def get(self, request, application_id):
        digisign_client = get_julo_digisign_client()
        customer = self.request.user.customer
        document = Document.objects.get_or_none(
            document_source=application_id, document_type="sphp_digisign"
        )
        application = Application.objects.get(pk=application_id)

        try:
            html_webview = digisign_client.sign_document(
                document.id, customer.email, is_digisign_web_browser(application)
            )
        except JuloException:
            logger.error(
                {
                    "message": "Call api digisign sign document failed",
                    "status": "digisign_sign_document_failed",
                    "document_id": document.id,
                }
            )
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={
                    "success": False,
                    "content": {},
                    "error_message": "Call api digisign sign document failed",
                },
            )

        signature_method_history_task.delay(application_id, 'Digisign')
        return StreamingHttpResponse(html_webview)


class DigisignUserStatusView(APIView):
    def get(self, request, *args, **kwargs):
        response = {
            'is_registered': False,
            'is_activated': False,
            'digisign_mode': False,
            'is_digisign_affected': False,
            'is_digisign_failed': False,
            'is_feature_failover': False,
            'application_status': None,
        }
        customer = self.request.user.customer
        application = customer.application_set.regular_not_deletes().last()
        if not is_digisign_feature_active(application):
            partner = (PartnerConstant.AXIATA_PARTNER, PartnerConstant.PEDE_PARTNER)
            if application.partner and application.partner.name in partner:
                process_application_status_change(
                    application.id,
                    ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED,
                    change_reason="Digisign Inactive",
                )
            return Response(response)

        # get all product selection active
        disisign_configs = DigisignConfiguration.objects.filter(is_active=True).values_list(
            "product_selection", flat=True
        )
        productlines_list = []
        for selection in disisign_configs:
            try:
                pline = getattr(ProductLineCodes, selection.lower())
                productlines_list += pline()
            except Exception:
                pass

        failover_status = True
        feature_mobile = MobileFeatureSetting.objects.filter(
            feature_name='digital_signature_failover'
        ).last()
        if feature_mobile:
            response['is_feature_failover'] = feature_mobile.is_active
            failover_status = feature_mobile.is_active

        digisign_client = get_julo_digisign_client()
        if application.product_line_code in productlines_list:
            response['is_digisign_affected'] = True

        if application.is_digisign_version():
            response['digisign_mode'] = True
        else:
            response['is_digisign_affected'] = False
            return Response(response)

        try:
            user_status_response = digisign_client.user_status(customer.email)
        except JuloException:
            logger.error(
                {
                    "message": "Call api digisign user status failed",
                    "status": "digisign_user_status_failed",
                    "email": customer.email,
                }
            )
            if application.is_digisign_version():
                return Response(
                    status=HTTP_400_BAD_REQUEST,
                    data={
                        "success": False,
                        "content": {},
                        "error_message": "Call api digisign user status failed",
                    },
                )
            else:
                return Response(response)

        user_status_response_json = user_status_response['JSONFile']
        if (
            user_status_response_json['result'] == DigisignResultCode.SUCCESS
            and user_status_response_json['info'] == 'belum aktif'
        ):
            response['is_registered'] = True
            response['is_activated'] = False
        elif (
            user_status_response_json['result'] == DigisignResultCode.SUCCESS
            and user_status_response_json['info'] == 'aktif'
        ):
            response['is_registered'] = True
            response['is_activated'] = True
        elif (
            user_status_response_json['result'] in DigisignResultCode.fail_to_145()
            and application.status != ApplicationStatusCodes.DIGISIGN_FAILED
            and application.status != ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
            and not failover_status
        ):
            note = user_status_response_json['notif']
            process_application_status_change(
                application.id,
                ApplicationStatusCodes.DIGISIGN_FAILED,
                change_reason='digisign send document failed',
                note=note,
            )
        # else:
        #     send_registration_and_document_digisign_task.delay(application.id)

        # chcek digisign failure
        signature_history = SignatureMethodHistory.objects.filter(
            application=application, signature_method='Digisign', is_used=False
        )
        if signature_history:
            response['is_digisign_failed'] = True

        return Response(response)


class DigisignUserActivationView(APIView):
    def put(self, request, *args, **kwargs):
        is_actived = self.request.data.get('is_actived', True)
        customer = self.request.user.customer
        customer.is_digisign_activated = is_actived
        customer.save()
        return Response({'success': True})


class DigisignDocumentStatusView(APIView):
    def get(self, request, application_id):
        user = self.request.user
        application = Application.objects.get_or_none(pk=application_id)
        if not application:
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={
                    "success": False,
                    "content": {},
                    "error_message": "application_id is required",
                },
            )

        if user.id != application.customer.user_id:
            return Response(
                status=HTTP_403_FORBIDDEN, data={'errors': 'User not allowed', 'user_id': user.id}
            )

        response = {
            'is_existed': False,
            'is_signed': False,
            'digisign_mode': False,
            'is_digisign_failed': False,
            'is_feature_failover': False,
            'application_status': application.status,
        }

        # feature_setting = MobileFeatureSetting.objects.filter(
        #     feature_name='digisign_mode', is_active=True).last()
        feature_setting = is_digisign_feature_active(application)
        if not feature_setting:
            return Response(response)

        feature_mobile = MobileFeatureSetting.objects.filter(
            feature_name='digital_signature_failover'
        ).last()
        if feature_mobile:
            response['is_feature_failover'] = feature_mobile.is_active

        digisign_client = get_julo_digisign_client()
        if application.is_digisign_version():
            response['digisign_mode'] = True
        else:
            return Response(response)

        document = Document.objects.get_or_none(
            document_source=application_id, document_type="sphp_digisign"
        )
        if not document:
            upload_sphp_from_digisign_task.delay(application_id)
            return Response(response)

        try:
            document_status_response = digisign_client.document_status(document.id)
        except JuloException:
            logger.error(
                {
                    "message": "Call api digisign user status failed",
                    "status": "digisign_document_status_failed",
                    "application_id": application_id,
                }
            )
            if application.is_digisign_version():
                return Response(
                    status=HTTP_400_BAD_REQUEST,
                    data={
                        "success": False,
                        "content": {},
                        "error_message": "Call api digisign user status failed",
                    },
                )
            else:
                return Response(response)

        document_status_response_json = document_status_response['JSONFile']
        if (
            document_status_response_json['result'] == DigisignResultCode.SUCCESS
            and document_status_response_json['status'] == 'waiting'
        ):
            response['is_existed'] = True
            response['is_signed'] = False
        elif (
            document_status_response_json['result'] == DigisignResultCode.SUCCESS
            and document_status_response_json['status'] == 'complete'
        ):
            response['is_existed'] = True
            response['is_signed'] = True
        else:
            upload_sphp_from_digisign_task.delay(application_id)

        # chcek digisign failure

        signature_history = SignatureMethodHistory.objects.filter(
            application=application, signature_method='Digisign', is_used=False
        )
        if signature_history:
            response['is_digisign_failed'] = True

        return Response(response)


class DigisignFailedActionView(APIView):
    def post(self, request, *args, **kwargs):
        customer = self.request.user.customer
        application = customer.application_set.last()

        # switch from digisign to julo
        signature_method_history_task.delay(application.id, 'JULO')
        return Response({'is_digisign_failed': True})


class CheckPayslipMandatory(APIView):
    """
    end point for check payslip in frontend was mandatory or not
    """

    def get(self, request, application_id):
        user = self.request.user
        is_mandatory = True
        feature_setting = MobileFeatureSetting.objects.filter(
            feature_name='set_payslip_no_required', is_active=True
        ).last()
        if not feature_setting:
            logger.warning(
                {"message": "set_payslip_no_required not found", "application": application_id},
                request=request,
            )
            return Response({'is_mandatory': is_mandatory})

        if not application_id:
            logger.warning(
                {"message": "Application is required", "application": application_id},
                request=request,
            )
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={
                    "success": False,
                    "content": {},
                    "error_message": "application_id is required",
                },
            )

        application = Application.objects.get_or_none(pk=application_id)

        if not application:
            logger.warning(
                {"message": "Application not found", "application": application_id}, request=request
            )
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={"success": False, "content": {}, "error_message": "application not found"},
            )
        if user.id != application.customer.user_id:
            logger.warning(
                {"message": "User not allowed", "application": application_id, "user": user.id},
                request=request,
            )
            return Response(
                status=HTTP_403_FORBIDDEN, data={'errors': 'User not allowed', 'user_id': user.id}
            )

        is_mandatory = check_payslip_mandatory(application_id)
        if is_mandatory is None:
            logger.warning(
                {
                    "message": "Unable to check payslip mandatory",
                    "application": application_id,
                    "user": user.id,
                },
                request=request,
            )
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={
                    "success": False,
                    "content": {},
                    "error_message": "unable to check payslip mandatory",
                },
            )

        logger.info(
            {
                "message": "Success response check payslip mandatory",
                "application": application_id,
                "user": user.id,
                "is_mandatory": is_mandatory,
            },
            request=request,
        )
        return Response({'is_mandatory': is_mandatory})


class AdditionalInfoView(APIView):
    permission_classes = []
    authentication_classes = []

    def get(self, request):
        try:
            addtional_info = FrontendView.objects.all()
            addtional_info_data = AdditionalInfoSerializer(addtional_info, many=True).data

            logger.info(message="Additional info view is OK", request=request)
            return Response({"data": addtional_info_data})
        except ValueError as e:
            logger.error(message="Additional info bad request", request=request)
            error = APIException('{}: last update date should be valid'.format(str(e)))
            error.status_code = 400
            raise error


class LenderSphp(APIView):
    def get(self, request, application_xid):
        application = Application.objects.get_or_none(application_xid=application_xid)
        if not application:
            loan = Loan.objects.get_or_none(loan_xid=application_xid)
            filter_lender_bucket = dict(loan_ids__approved__contains=[loan.id])
        else:
            filter_lender_bucket = dict(application_ids__approved__contains=[application.id])
        lender_bucket = LenderBucket.objects.filter(**filter_lender_bucket).last()
        if not lender_bucket:
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={"success": False, "content": {}, "error_message": "lenderbucket Not Found"},
            )

        document = Document.objects.filter(
            document_source=lender_bucket.id, document_type="summary_lender_sphp"
        ).last()

        if not document:
            generate_summary_lender_loan_agreement(lender_bucket.id)
            document = Document.objects.filter(
                document_source=lender_bucket.id, document_type="summary_lender_sphp"
            ).last()
            if not document:
                loan = application.loan
                lender = loan.lender
                template = LoanAgreementTemplate.objects.get_or_none(
                    lender=lender, is_active=True, agreement_type=LoanAgreementType.SUMMARY
                )
                if not template:
                    return Response(
                        status=HTTP_400_BAD_REQUEST,
                        data={
                            "success": False,
                            "content": {},
                            "error_message": "Template P4K tidak ditemukan",
                        },
                    )

                return Response(
                    status=HTTP_400_BAD_REQUEST,
                    data={"success": False, "content": {}, "error_message": "P4K tidak ditemukan"},
                )

        document_stream = get_file_from_oss(settings.OSS_MEDIA_BUCKET, document.url)
        response = StreamingHttpResponse(
            streaming_content=document_stream, content_type='application/pdf'
        )
        response['Content-Disposition'] = 'filename="' + document.filename + '"'
        return response


class CustomerSphp(APIView):
    def get(self, request, application_xid):
        application = Application.objects.get_or_none(application_xid=application_xid)
        loan = None
        if not application:
            loan = Loan.objects.get_or_none(loan_xid=application_xid)

        if not application and not loan:
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={
                    "success": False,
                    "content": {},
                    "error_message": "Application or loan Not Found",
                },
            )

        user = self.request.user
        customer = application.customer if application else loan.customer
        if user.id != customer.user_id and user.username not in ['jtp', 'jh']:
            return Response(
                status=HTTP_403_FORBIDDEN, data={'errors': 'User not allowed', 'user_id': user.id}
            )

        if application:
            filter_document = dict(
                document_source=application.id,
                document_type__in=("sphp_julo", "sphp_digisign", "sphp_privy"),
            )
        else:
            application = loan.get_application
            filter_document = dict(
                loan_xid=loan.loan_xid,
                document_type__in=(
                    'sphp_privy',
                    'sphp_julo',
                ),
            )

        document = Document.objects.filter(**filter_document).last()
        if not document:
            generate_sphp(application.id)
            document = Document.objects.filter(
                document_source=application.id,
                document_type__in=("sphp_julo", "sphp_digisign", "sphp_privy"),
            ).last()
            if not document:
                return Response(
                    status=HTTP_400_BAD_REQUEST,
                    data={"success": False, "content": {}, "error_message": "SPHP tidak ditemukan"},
                )

        document_stream = get_file_from_oss(settings.OSS_MEDIA_BUCKET, document.url)
        response = StreamingHttpResponse(
            streaming_content=document_stream, content_type='application/pdf'
        )
        response['Content-Disposition'] = 'filename="' + document.filename + '"'
        return response


# class UpdateCenterixPaymentData(APIView):
#     """
#     API endpoint for update ceneterix payment data
#     """
#     permission_classes = []
#     authentication_classes = []
#     def post(self, request):
#         try:
#             cred_user = request.data['JuloCredUser']
#             cred_pass = request.data['JuloCredPassword']
#
#             if cred_user == settings.CENTERIX_JULO_USER_ID and cred_pass
#             == settings.CENTERIX_JULO_PASSWORD:
#                 payment_id = request.data['Datas'][0]['PAYMENT_ID']
#                 customer_id = request.data['Datas'][0]['CUSTOMER_ID']
#                 application_id = request.data['Datas'][0]['APPLICATION_ID']
#                 campaign = request.data['Datas'][0]['CAMPAIGN']
#                 paid_date = request.data['Datas'][0]['PAID_DATE']
#                 paid_amount = request.data['Datas'][0]['PAID_AMOUNT']
#                 outstanding = request.data['Datas'][0]['OUTSTANDING']
#                 if campaign == 'JULO':
#                     payment = Payment.objects.get_or_none(pk=payment_id)
#                     if not payment:
#                         return Response({
#                             "ErrMessage": 'Not found payment - {}' .format(payment_id),
#                             "Result": 'Failure'
#                         })
#                     date = datetime.strptime(paid_date, "%d/%m/%Y").date()
#                     payment.paid_date = date
#                     payment.paid_amount = paid_amount
#                     payment.due_amount = outstanding
#                     payment.save(update_fields=['due_amount',
#                                                 'paid_date',
#                                                 'paid_amount',
#                                                 'udate'])
#                 else:
#                     statement = Statement.objects.get_or_none(pk=payment_id)
#                     if not statement:
#                         return Response({
#                             "ErrMessage": 'Not found payment - {}'.format(payment_id),
#                             "Result": 'Failure'
#                         })
#                     date = datetime.strptime(paid_date, "%d/%m/%Y").date()
#                     statement.statement_paid_date = date
#                     statement.statement_paid_amount = paid_amount
#                     statement.statement_due_amount = outstanding
#                     statement.save(update_fields=['statement_due_amount',
#                                                 'statement_paid_date',
#                                                 'statement_paid_amount',
#                                                 'udate'])
#                 return Response({
#                     "ErrMessage": 'Details updated for payment - {}' .format(payment_id),
#                     "Result": 'Success'
#                 })
#
#             else:
#                 return Response({
#                     "ErrMessage": 'Invalid authentication credentials',
#                     "Result": 'Failure'
#                 })
#
#         except ValueError as e:
#             error = APIException('upload centerix data - {}: '.format(e.message))
#             return Response({
#                 "ErrMessage": 'Something went wrong',
#                 "Result": 'Failure'
#             })
#             raise error


class UpdateCenterixSkiptraceData(APIView):
    """
    API endpoint for update ceneterix skiptrace data
    """

    permission_classes = []
    authentication_classes = []

    def update_centerix_callback(self, error_msg, result, data):
        application_id = data['APPLICATION_ID']
        payment_id = data['PAYMENT_ID']
        centerix_campaign = data['CENTERIXCAMPAIGN']
        skiptrace_date = data['DATE']
        skiptrace_time = data['TIME']
        date = datetime.strptime(skiptrace_date, "%d/%m/%Y").date()
        time = datetime.strptime(skiptrace_time, "%H.%M.%S").time()
        date_time = str(date) + " " + str(time)
        start_time = datetime.strptime(date_time, '%Y-%m-%d %H:%M:%S')
        duration = data['DURATION']
        if not duration:
            duration = 0

        end_time = start_time + relativedelta(seconds=int(duration))
        parameters = json.dumps(data)
        CenterixCallbackResults.objects.create(
            start_ts=start_time,
            end_ts=end_time,
            application_id=application_id,
            payment_id=payment_id,
            error_msg=error_msg,
            result=result,
            campaign_code=centerix_campaign,
            parameters=parameters,
        )

    def post(self, request):
        try:
            cred_user = request.data['JuloCredUser']
            cred_pass = request.data['JuloCredPassword']
            if (
                not cred_user == settings.CENTERIX_JULO_USER_ID
                or not cred_pass == settings.CENTERIX_JULO_PASSWORD
            ):
                result = 'Failure'
                error_msg = 'Invalid authentication credentials'
                CenterixCallbackResults.objects.create(
                    error_msg=error_msg, result=result, parameters=json.dumps(request.data)
                )
                return Response({"ErrMessage": error_msg, "Result": result})

            payment_id = request.data['Datas'][0]['PAYMENT_ID']
            customer_id = request.data['Datas'][0]['CUSTOMER_ID']
            application_id = request.data['Datas'][0]['APPLICATION_ID']
            # loan_id = request.data['Datas'][0]['LOAN_ID']
            skiptrace_phone = request.data['Datas'][0]['PHONE']
            skiptrace_result = request.data['Datas'][0]['RESULT']
            skiptrace_sub_result = request.data['Datas'][0]['SUBRESULT']
            skiptrace_status = request.data['Datas'][0]['STATUSCALL']
            skiptrace_ptp_date = request.data['Datas'][0]['PTPDATE']
            skiptrace_callback_time = (
                request.data['Datas'][0]['CALLBACKTIME']
                if request.data['Datas'][0]['CALLBACKTIME']
                else None
            )
            skiptrace_ptp_amount = request.data['Datas'][0]['PTP']
            if not skiptrace_ptp_amount:
                skiptrace_ptp_amount = 0

            skiptrace_notes = request.data['Datas'][0]['NOTES']
            skiptrace_agent_name = request.data['Datas'][0]['AGENTNAME']
            skiptrace_campaign = request.data['Datas'][0]['CAMPAIGN']
            skiptrace_source = request.data['Datas'][0]['TYPEOF']
            centerix_campaign = request.data['Datas'][0]['CENTERIXCAMPAIGN']
            skiptrace_date = request.data['Datas'][0]['DATE']
            skiptrace_time = request.data['Datas'][0]['TIME']
            date = datetime.strptime(skiptrace_date, "%d/%m/%Y").date()
            time = datetime.strptime(skiptrace_time, "%H.%M.%S").time()
            date_time = str(date) + " " + str(time)
            start_time = datetime.strptime(date_time, '%Y-%m-%d %H:%M:%S')
            duration = request.data['Datas'][0]['DURATION']
            non_payment_reason = request.data['Datas'][0]['NONPAYMENTREASON']
            non_payment_reason_other = request.data['Datas'][0]['NONPAYMENTREASONOTHER']
            if not duration:
                duration = 0
            spoke_with = request.data['Datas'][0]['SPOKEWITH']

            end_time = start_time + relativedelta(seconds=int(duration))
            if skiptrace_sub_result == 'RPC - PTP' and (
                int(skiptrace_ptp_amount) == 0
                or not skiptrace_ptp_date
                or skiptrace_ptp_date == "01/01/0001"
            ):
                result = 'Failure'
                error_msg = 'Invalid PTP Amount/Date'
                self.update_centerix_callback(error_msg, result, request.data['Datas'][0])
                return Response({"ErrMessage": error_msg, "Result": result})

            if not skiptrace_campaign == 'JULO':
                result = 'Failure'
                error_msg = 'Invalid campaign {}'.format(skiptrace_campaign)
                self.update_centerix_callback(error_msg, result, request.data['Datas'][0])
                return Response({"ErrMessage": error_msg, "Result": result})

            payment = Payment.objects.get_or_none(pk=payment_id)

            if not payment:
                result = 'Failure'
                error_msg = 'Not found payment for application - {}'.format(application_id)
                self.update_centerix_callback(error_msg, result, request.data['Datas'][0])
                return Response({"ErrMessage": error_msg, "Result": result})

            if not customer_id:
                result = 'Failure'
                error_msg = 'Invalid customer details - {}'.format(customer_id)
                self.update_centerix_callback(error_msg, result, request.data['Datas'][0])
                return Response({"ErrMessage": error_msg, "Result": result})

            cust_obj = Customer.objects.get_or_none(pk=customer_id)
            if cust_obj is None:
                result = 'Failure'
                error_msg = 'Invalid customer details - {}'.format(customer_id)
                self.update_centerix_callback(error_msg, result, request.data['Datas'][0])
                return Response({"ErrMessage": error_msg, "Result": result})

            user_obj = User.objects.filter(username=skiptrace_agent_name.lower()).last()
            if user_obj is None:
                result = 'Failure'
                error_msg = 'Invalid agent details - {}'.format(skiptrace_agent_name)
                self.update_centerix_callback(error_msg, result, request.data['Datas'][0])
                return Response({"ErrMessage": error_msg, "Result": result})

            if skiptrace_result and skiptrace_sub_result:
                skip_result_choices = skiptrace_sub_result
                result_error = 'SUBRESULT'
            else:
                skip_result_choices = skiptrace_result
                result_error = 'RESULT'

            skip_result_choice = SkiptraceResultChoice.objects.filter(
                name=skip_result_choices
            ).last()
            if not skip_result_choice:
                result = 'Failure'
                error_msg = 'Invalid {} - {}'.format(result_error, skip_result_choices)
                self.update_centerix_callback(error_msg, result, request.data['Datas'][0])
                return Response({"ErrMessage": error_msg, "Result": result})

            CuserMiddleware.set_user(user_obj)
            skiptrace_obj = Skiptrace.objects.filter(
                phone_number=format_e164_indo_phone_number(skiptrace_phone), customer_id=customer_id
            ).last()
            if not skiptrace_obj:
                skiptrace = Skiptrace.objects.create(
                    contact_source=skiptrace_source,
                    phone_number=format_e164_indo_phone_number(skiptrace_phone),
                    customer_id=customer_id,
                )
                skiptrace_ids = skiptrace.id
            else:
                skiptrace_ids = skiptrace_obj.id

            if not skiptrace_ids:
                result = 'Failure'
                error_msg = 'Invalid Skiptrace ID'
                self.update_centerix_callback(error_msg, result, request.data['Datas'][0])
                return Response({"ErrMessage": error_msg, "Result": result})

            if skiptrace_sub_result == 'RPC - PTP':
                ptp_amount = [x for x in skiptrace_ptp_amount if x.isdigit()]
                ptp_date = datetime.strptime(skiptrace_ptp_date, "%d/%m/%Y").date()

                with transaction.atomic():
                    # Create PTP
                    ptp = PTP.objects.filter(payment=payment).last()
                    paid_ptp_status = ['Paid', 'Paid after ptp date']

                    if payment.payment_status_id in PaymentStatusCodes.paid_status_codes:
                        error_msg = 'This payment already paid off'
                        result = 'failure'
                        return Response(
                            status=HTTP_404_NOT_FOUND,
                            data={"error_message": error_msg, "Result": result},
                        )

                    if ptp:
                        if ptp.ptp_status and ptp.ptp_status in paid_ptp_status:
                            error_msg = 'can not add PTP, this payment already paid off'
                            result = 'failure'

                            return Response(
                                status=HTTP_404_NOT_FOUND,
                                data={"error_message": error_msg, "Result": result},
                            )

                    ptp_create(payment, ptp_date, ptp_amount, user_obj)

                    payment.update_safely(ptp_date=ptp_date, ptp_amount=ptp_amount)

                    ptp_notes = "Promise to Pay %s -- %s " % (ptp_amount, ptp_date)
                    PaymentNote.objects.create(note_text=ptp_notes, payment=payment)

            skiptrace_result_id = skip_result_choice.id
            if skiptrace_notes:
                PaymentNote.objects.create(
                    note_text=skiptrace_notes, payment=payment, added_by_id=user_obj
                )

            if non_payment_reason_other and non_payment_reason == 'Other':
                non_payment_reason = '{} - {}'.format(non_payment_reason, non_payment_reason_other)

            SkiptraceHistory.objects.create(
                start_ts=start_time,
                end_ts=end_time,
                application_id=payment.loan.application.id,
                loan_id=payment.loan.id,
                agent_name=user_obj.username,
                call_result_id=skiptrace_result_id,
                agent_id=user_obj,
                skiptrace_id=skiptrace_ids,
                payment_id=payment.id,
                notes=skip_result_choices,
                callback_time=skiptrace_callback_time,
                loan_status=payment.loan.loan_status.status_code,
                payment_status=payment.payment_status.status_code,
                application_status=payment.loan.application.status,
                non_payment_reason=non_payment_reason,
                spoke_with=spoke_with,
            )
            SkiptraceHistoryCentereix.objects.create(
                start_ts=start_time,
                end_ts=end_time,
                application_id=payment.loan.application.id,
                loan_id=payment.loan.id,
                loan_status=payment.loan.loan_status.status_code,
                payment_status=payment.payment_status.status_code,
                application_status=payment.loan.application.status,
                agent_name=user_obj.username,
                contact_source=skiptrace_source,
                payment_id=payment.id,
                comments=skiptrace_notes,
                campaign_name=centerix_campaign,
                phone_number=format_e164_indo_phone_number(skiptrace_phone),
                status_group=skiptrace_status,
                status=skip_result_choices,
                callback_time=skiptrace_callback_time,
                non_payment_reason=non_payment_reason,
                spoke_with=spoke_with,
            )

            if payment and user_obj and skip_result_choice:
                trigger_insert_col_history(payment.id, user_obj.id, skip_result_choice.id)
            result = 'Success'
            error_msg = 'Details updated for application - {}'.format(application_id)
            self.update_centerix_callback(error_msg, result, request.data['Datas'][0])
            return Response({"ErrMessage": error_msg, "Result": result})

        except Exception as e:
            APIException('upload centerix data - {}: '.format(str(e)))
            result = 'Failure'
            error_msg = 'Something went wrong -{}'.format(str(e))
            CenterixCallbackResults.objects.create(
                error_msg=error_msg, result=result, parameters=json.dumps(request.data)
            )
            return Response({"ErrMessage": error_msg, "Result": result})


class TutorialSphpPopupView(APIView):
    def get(self, request):
        return render(request, 'digisign/tutorial_digisign_sphp.html')


class ReferralHome(APIView):
    def get(self, request, customer_id):
        customer = Customer.objects.get_or_none(pk=customer_id)
        application = customer.application_set.last()
        if not show_referral_code(customer):
            return Response(
                {
                    "success": True,
                    "content": {
                        "active": False,
                        "message": "Mohon maaf, fitur ini sedang tidak aktif.",
                    },
                }
            )
        user = self.request.user

        if user.id != customer.user_id:
            return Response(
                status=HTTP_403_FORBIDDEN, data={'errors': 'User not allowed', 'user_id': user.id}
            )

        referral_system = ReferralSystem.objects.filter(
            name='PromoReferral', is_active=True
        ).first()
        if not referral_system:
            return Response(
                {
                    "success": True,
                    "content": {
                        "active": False,
                        "message": "Mohon maaf, fitur ini sedang tidak aktif.",
                    },
                }
            )

        (
            total_referral_invited,
            total_referral_benefits,
        ) = get_total_referral_invited_and_total_referral_benefits(customer)

        content = referral_system.extra_data['content']
        if application.is_julo_one_product():
            _, tier = get_customer_tier_info(application)
            referral_bonus = tier.referral_bonus
        else:
            referral_bonus = referral_system.caskback_amount
        cashback_currency = display_rupiah(referral_bonus)
        cashback_referee_currency = display_rupiah(referral_system.referee_cashback_amount)
        return success_response(
            {
                "header": content['header'],
                "image": referral_system.banner_static_url,
                "body": content['body'].format(cashback_currency, cashback_referee_currency),
                "footer": content['footer'],
                "referral_code": customer.self_referral_code,
                'message': content['message'].format(
                    cashback_referee_currency, customer.self_referral_code
                ),
                'terms': content['terms'].format(cashback_currency),
                'total_referral_invited': total_referral_invited,
                'total_referral_benefits': total_referral_benefits,
                'referee_cashback_amount': referral_system.referee_cashback_amount,
            }
        )


class UserFeedback(APIView):
    def post(self, request):
        user = self.request.user
        application_id = request.data.get('application_id')
        application = Application.objects.get_or_none(pk=application_id)
        if not application:
            error_msg = 'application not found'
            result = 'failure'
            return Response(
                status=HTTP_404_NOT_FOUND, data={"error_message": error_msg, "Result": result}
            )

        if user.id != application.customer.user_id:
            return Response(
                status=HTTP_403_FORBIDDEN, data={'errors': 'User not allowed', 'user_id': user.id}
            )

        if not request.data.get('feedback', None):
            error_msg = 'Feedback field require'
            result = 'failure'
            return Response(
                status=HTTP_400_BAD_REQUEST, data={"error_message": error_msg, "Result": result}
            )
        if not request.data.get('rating', None):
            error_msg = 'Rating field require'
            result = 'failure'
            return Response(
                status=HTTP_400_BAD_REQUEST, data={"error_message": error_msg, "Result": result}
            )
        data = request.data.copy()
        data['application'] = application.id
        user_feedback = UserFeedbackModel.objects.filter(application=application).last()
        if not user_feedback:
            serializer = UserFeedbackSerializer(data=data)
            serializer.is_valid()
            serializer.save()
            customer = application.customer
            customer.update_safely(is_review_submitted=True)
        else:
            error_msg = 'application has already given feedback'
            result = 'failure'
            return Response(
                status=HTTP_400_BAD_REQUEST, data={"error_message": error_msg, "Result": result}
            )

        return Response(status=HTTP_201_CREATED, data={'result': serializer.data})


class AppScrapedChecking(StandardizedExceptionHandlerMixin, APIView):
    """
    Checking worthy to scrape data or not
    """

    def get(self, request, application_id):
        customer = request.user.customer
        user_applications = customer.application_set.values_list('id', flat=True)
        application_id = int(application_id)
        if application_id not in user_applications:
            return Response(status=HTTP_404_NOT_FOUND, data={'not_found': application_id})
        scheduled_days = 14
        clcs_scheduled = FeatureSetting.objects.get_or_none(
            feature_name=FeatureNameConst.CLCS_SCRAPED_SCHEDULE, is_active=True
        )
        if clcs_scheduled:
            scheduled_days = clcs_scheduled.parameters.get('days') or scheduled_days

            # mock to return worthy = False until etl revamped properly
            return Response(status=200, data={'worthy': True, 'scheduled_days': scheduled_days})

        return Response(status=200, data={'worthy': False, 'scheduled_days': scheduled_days})


class AppScrapedDataOnlyUpload(StandardizedExceptionHandlerMixin, APIView):
    """
    Endpoint for uploading DSD to anaserver and starting ETL for installed apps only
    """

    def post(self, request):
        if 'application_id' not in request.data:
            return Response(
                status=HTTP_400_BAD_REQUEST, data={'application_id': "This field is required"}
            )
        if 'upload' not in request.data:
            return Response(status=HTTP_400_BAD_REQUEST, data={'upload': "This field is required"})
        if not isinstance(request.data['upload'], InMemoryUploadedFile):
            return Response(
                status=HTTP_400_BAD_REQUEST, data={'upload': "This field must contain file"}
            )

        application_id = int(request.data['application_id'])
        customer = request.user.customer

        user_applications = customer.application_set.values_list('id', flat=True)
        if application_id not in user_applications:
            return Response(status=HTTP_404_NOT_FOUND, data={'not_found': application_id})

        url = request.build_absolute_uri()

        ApplicationScrapeAction.objects.create(
            application_id=application_id, url=url, scrape_type='dsd-clcs'
        )

        etl_repeat_status = EtlRepeatStatus.objects.filter(application_id=application_id).last()
        etl_repeat_number = etl_repeat_status.repeat_number if etl_repeat_status else 0

        data = {
            'application_id': application_id,
            'customer_id': customer.id,
            'repeat_number': int(etl_repeat_number) + 1,
        }
        files = {'upload': request.data['upload']}

        # don't pass data to ANA until etl revamped properly
        # Call to ana server for repeat CLCS
        ret = redirect_post_to_anaserver(
            '/api/amp/v1/device-scraped-data-clcs/', data=data, files=files
        )

        return Response(status=ret.status_code, data=ret.data)


class ChangeEmailView(APIView):
    serializer_class = ChangeEmailSerializer

    def post(self, request):
        serializer = ChangeEmailSerializer(data=request.data)

        if serializer.is_valid():
            password = serializer.validated_data['password']
            email = serializer.validated_data['email']

            try:
                customer = Customer.objects.get(user=self.request.user)

                if does_user_have_pin(customer.user):
                    data = {'message': 'You cannot use this process'}
                    return Response(data, status=HTTP_200_OK)

                user = authenticate(username=self.request.user.username, password=password)

                if self.request.user != user:
                    data = {'message': 'Masukkan kata sandi yang valid'}

                    return Response(data, status=HTTP_400_BAD_REQUEST)

                old_email = customer.email

                if old_email == email:
                    data = {"message": "Enter a different email"}

                    return Response(data, status=HTTP_400_BAD_REQUEST)

                customer_with_existing_email = Customer.objects.filter(email=email).last()
                application_with_existing_email = Application.objects.filter(email=email).last()

                if customer_with_existing_email is None and application_with_existing_email is None:
                    with transaction.atomic():
                        customer.email = email
                        customer.save()

                        user = User.objects.get(pk=request.user.id)
                        user.email = email
                        user.save()

                        application = Application.objects.filter(customer=customer).latest('id')
                        application.email = email
                        application.save()

                        CustomerFieldChange.objects.create(
                            customer=customer,
                            field_name='email',
                            old_value=old_email,
                            new_value=email,
                            application=application,
                            changed_by=user,
                        )

                    data = {"message": "success"}

                    return Response(data, status=HTTP_200_OK)
                else:
                    data = {"message": "Email is already registered."}

                    return Response(data, status=HTTP_400_BAD_REQUEST)

            except (ObjectDoesNotExist, TypeError) as e:
                data = {"error": str(e)}

                return Response(data, status=HTTP_400_BAD_REQUEST)

        return Response(serializer.errors, status=HTTP_400_BAD_REQUEST)


class SecurityFaqApiview(ViewSet):
    def get_all(self, request, format=None):
        query = FaqSection.objects.filter(is_security_faq=True)
        serializers = FAQSerializer(query, many=True)
        return Response(serializers.data)

    def get(self, request, section_id, format=None):
        queryset = FaqItem.objects.filter(
            section__id=section_id, visible=True, section__is_security_faq=True
        )
        if not queryset:
            return Response(
                status=HTTP_400_BAD_REQUEST, data={'errors': ['Security Faq items not found']}
            )
        serializer = FAQItemsSerializer(queryset, many=True)
        return Response(serializer.data)


class PaymentInfoRetrieveViewV2(APIView):
    permission_classes = []
    authentication_classes = []

    def get(self, request, payment_id):
        encryptor = encrypt()
        decoded_payment_id = encryptor.decode_string(payment_id)
        account_payment = AccountPayment.objects.get_or_none(pk=decoded_payment_id)
        if not account_payment:
            return Response(status=HTTP_404_NOT_FOUND, data="resource not found")

        account = account_payment.account
        customer = account.customer
        apps_installed_status = get_uninstall_indicator_from_moengage_by_customer_id(customer.id)
        active_loans = account_payment.account.get_all_active_loan()

        if not active_loans:
            return Response(status=HTTP_404_NOT_FOUND, data="resource not found")

        warning_letter_id = request.query_params.get('physical_warning_letter', None)
        if warning_letter_id:
            decoded_warning_letter_id = encryptor.decode_string(warning_letter_id)
            warning_letter_history = WarningLetterHistory.objects.filter(
                id=decoded_warning_letter_id
            ).last()
            if warning_letter_history:
                PaymentDetailUrlLog.objects.create(
                    source='physical_warning_letter',
                    warning_letter_history_id=decoded_warning_letter_id,
                )

        response_data = {
            "customer": {
                "fullname": "",
                'title_long': None,
            },
            "payment": {
                "payment_number": None,
                "due_amount": "",
                "due_date": "",
                "month_and_year_due_date": "",
                "maturity_date": None,
                "payment_cashback_amount": "",
                "payment_methods": {},
                "payment_cashback_percentage": 0,
                "is_due_pay_date": False,
            },
            "settings": {},
            "product": {"type": ""},
            "apps_installed_status": apps_installed_status,
        }

        curr_account_payment = account_payment
        url = settings.PROJECT_URL + request.get_full_path()

        # Record payment detail page access count
        record_payment_detail_page_access_history.delay(account.id, url)

        oldest_unpaid_account_payment = account.get_oldest_unpaid_account_payment()
        if oldest_unpaid_account_payment:
            curr_account_payment = oldest_unpaid_account_payment

        curr_due_amount = curr_account_payment.due_amount
        if curr_account_payment.dpd > 0:
            curr_due_amount = 0
            curr_late_fee_amount = 0
            unpaid_account_payments = account.accountpayment_set.not_paid_active()
            for el in unpaid_account_payments:
                curr_due_amount += el.due_amount
                curr_late_fee_amount += el.late_fee_amount
            response_data["payment"]["late_fee_amount"] = display_rupiah(curr_late_fee_amount)
            response_data["payment"]["is_due_pay_date"] = True

        acc_payment_due_date = curr_account_payment.due_date

        active_loans = account.loan_set.filter(
            loan_status__gte=LoanStatusCodes.CURRENT,
            loan_status__lt=LoanStatusCodes.PAID_OFF,
        )

        cashback_multiplier = curr_account_payment.cashback_multiplier
        curr_payment_cashback_amount = get_potential_cashback_for_crm(account_payment)

        payment_method_qs = customer.paymentmethod_set.filter(is_shown=True)
        payment_method_qs = filter_payment_methods_by_lender(payment_method_qs, customer)
        payment_methods = payment_method_qs.order_by('sequence',).values(
            'payment_method_code',
            'payment_method_name',
            'virtual_account',
            'bank_code',
            'is_primary',
        )

        payment_methods_name = [e['payment_method_name'] for e in payment_methods]
        payment_methods_lookup = PaymentMethodLookup.objects.filter(
            name__in=payment_methods_name
        ).values('name', 'image_logo_url')

        bank_name_logo_map = {
            method['name']: method['image_logo_url'] for method in payment_methods_lookup
        }

        pm_virtual_account = []
        pm_e_wallet = []
        pm_another_method = []
        pm_autodebet = []
        pm_retail = []
        pm_primary = []
        pm_new_channel = []
        order_payment_methods_feature = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.ORDER_PAYMENT_METHODS_BY_GROUPS,
        ).last()
        today_date = timezone.localtime(timezone.now()).date()
        end_date = order_payment_methods_feature.parameters.get('new_repayment_channel_group').get(
            'end_date'
        )
        if end_date:
            end_date = datetime.strptime(end_date, '%d-%m-%Y').date()
        parameters = order_payment_methods_feature.parameters
        for payment_method in payment_methods:
            payment_method_name = payment_method["payment_method_name"]

            pm_data = {
                "payment_method_code": payment_method["payment_method_code"],
                "payment_method_name": payment_method_name,
                "account_number": payment_method["virtual_account"],
                "account_code": payment_method["bank_code"],
                "logo": settings.STATIC_URL + "placeholder_payment_logo.svg",
            }

            if payment_method_name in bank_name_logo_map:
                pm_data["logo"] = bank_name_logo_map[payment_method_name]

            if payment_method['is_primary']:
                pm_primary.append(pm_data)
            elif (
                end_date
                and today_date <= end_date
                and payment_method['payment_method_name'].lower()
                in parameters.get('new_repayment_channel_group').get('new_repayment_channel')
            ):
                pm_new_channel.append(pm_data)
            elif payment_method['payment_method_name'].lower() in parameters.get('autodebet_group'):
                pm_autodebet.append(pm_data)
            elif payment_method['payment_method_name'].lower() in parameters.get('bank_va_group'):
                pm_virtual_account.append(pm_data)
            elif payment_method['payment_method_name'].lower() in parameters.get('retail_group'):
                pm_retail.append(pm_data)
            elif payment_method['payment_method_name'].lower() in parameters.get('e_wallet_group'):
                pm_e_wallet.append(pm_data)
            else:
                pm_another_method.append(pm_data)

        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.IN_APP_PTP_SETTING, is_active=True
        ).last()

        # Assign Cashback responses data
        cashback_dpd_threshold, cashback_percentage_mapping = get_paramters_cashback_new_scheme()
        cashback_counter = account.cashback_counter_for_customer
        response_data["payment"][
            "is_cashback_streak_user"
        ] = account.is_eligible_for_cashback_new_scheme
        response_data["payment"]["cashback_streak_counter"] = cashback_counter
        response_data["payment"]["cashback_dpd_threshold"] = cashback_dpd_threshold
        response_data["payment"]["cashback_percentage"] = cashback_percentage_mapping.get(
            str(cashback_counter)
        )

        # Assign response data customer.
        gender_title = {'Pria': 'Bapak', 'Wanita': 'Ibu'}
        response_data["customer"]["fullname"] = mask_fullname_each_word(customer.fullname)
        response_data["customer"]["title_long"] = gender_title.get(customer.gender, 'Bapak/Ibu')

        # Assign response data payment.
        response_data["payment"]["due_amount"] = display_rupiah(curr_due_amount)
        response_data["payment"]["due_date"] = format_date(
            acc_payment_due_date, 'd MMMM yyyy', locale='id_ID'
        )
        response_data["payment"]["month_and_year_due_date"] = date.strftime(
            acc_payment_due_date, '%m/%Y'
        )
        response_data["payment"]["payment_cashback_amount"] = curr_payment_cashback_amount
        response_data["payment"]["payment_methods"] = {
            "recommendation": pm_primary,
            "new_channel": pm_new_channel,
            "virtual_account": pm_virtual_account,
            "e_wallet": pm_e_wallet,
            "retail": pm_retail,
            "another_method": pm_another_method,
            "autodebet": pm_autodebet,
        }
        response_data["payment"]["payment_cashback_percentage"] = cashback_multiplier
        response_data["payment"]["encrypted_payment_id"] = payment_id
        response_data["payment"]["dpd_number"] = curr_account_payment.dpd
        response_data["payment"]["short_due_date"] = (
            acc_payment_due_date - timedelta(days=2)
        ).strftime('%d/%m/%Y')

        response_data["settings"]["in_app_ptp"] = True if feature_setting else False

        # Assing response data product.
        response_data["product"]["type"] = 'J1'

        return Response(data=response_data)


class HelpCenterView(ViewSet):
    permission_classes = []
    authentication_classes = []

    def get_all(self, request, format=None):
        query = HelpCenterSection.objects.filter(visible=True).order_by('id')
        serializers = HelpCenterSerializer(query, many=True)
        return success_response(serializers.data)

    def get(self, request, slug, format=None):
        queryset = HelpCenterItem.objects.filter(section__slug=slug, visible=True).order_by('id')
        if not queryset:
            return general_error_response('items not found')
        serializer = HelpCenterItemsSerializer(queryset, many=True)

        app_version_code = int(request.META.get('HTTP_X_VERSION_CODE') or 0)
        android_id = request.META.get('HTTP_X_ANDROID_ID')

        data = modify_change_phone_number_related_response(
            datas=serializer.data,
            android_id=android_id,
            app_version_code=app_version_code,
        )

        return success_response(data)


class DropDownApi(APIView, StandardizedExceptionHandlerMixinV2):
    def get(self, request, product_line_code):
        result, response = generate_dropdown_data(
            int(product_line_code), request, url=request.get_full_path(), api_version='v2'
        )
        if result == DropdownResponseCode.PRODUCT_NOT_FOUND:
            return not_found_response(response)

        if result == DropdownResponseCode.UP_TO_DATE:
            return success_response(response)

        if result == DropdownResponseCode.NEW_DATA:
            return response


class FormAlertMessageView(APIView):
    permission_classes = []
    authentication_classes = []
    serialier = FormAlertMessageSerializer

    def get(self, request, format=None):
        """
        Return creation form alert messages for x100 form
        """
        alert_configs = FormAlertMessageConfig.objects.all()
        serializer = self.serialier(alert_configs, many=True)

        return success_response(serializer.data)
