from __future__ import unicode_literals

import os
from builtins import object, str
from datetime import date, datetime, timedelta

import requests
from django.conf import settings
from django.contrib.auth import authenticate

# from django.contrib.auth.models import User
from juloserver.julo.models import AuthUser as User
from django.db import transaction
from django.db.models import Sum
from django.db.utils import IntegrityError
from django.forms.models import model_to_dict
from django.http import JsonResponse
from django.http.response import HttpResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.utils import timezone
from rest_framework import filters, generics, parsers, serializers
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.decorators import parser_classes
from rest_framework.exceptions import (
    APIException,
)
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.renderers import TemplateHTMLRenderer
from rest_framework.response import Response
from rest_framework.status import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
)
from rest_framework.views import APIView
from rest_framework.serializers import ValidationError

from juloserver.account_payment.models import AccountPayment
from juloserver.api_token.models import ExpiryToken as Token
from juloserver.apiv2.services import store_device_geolocation
from juloserver.cfs.constants import EtlJobType
from juloserver.julo.clients import get_julo_email_client
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.pin.services import does_user_have_pin
from juloserver.julolog.julolog import JuloLog
from ..account_payment.services.earning_cashback import get_cashback_experiment
from juloserver.apiv2.utils import mask_fullname_each_word

from ..julo.banks import BankCodes, BankManager
from ..julo.clients import get_julo_sentry_client
from ..julo.constants import FeatureNameConst
from ..julo.models import (
    AddressGeolocation,
    Application,
    ApplicationHistory,
    AppVersionHistory,
    AwsFaceRecogLog,
    Collateral,
    Customer,
    CustomerAppAction,
    Device,
    DeviceGeolocation,
    DeviceScrapedData,
    FacebookData,
    GlobalPaymentMethod,
    Image,
    Loan,
    MobileFeatureSetting,
    Offer,
    PartnerLoan,
    PartnerReferral,
    Payment,
    PaymentMethod,
    PaymentMethodLookup,
    ProductLine,
    SignatureMethodHistory,
    SiteMapJuloWeb,
    VoiceRecord,
    FeatureSetting,
)
from ..julo.partners import PartnerConstant
from ..julo.product_lines import ProductLineCodes
from ..julo.services import (
    link_to_partner_by_product_line,
    process_application_status_change,
)
from ..julo.services2 import encrypt
from ..julo.services2.payment_method import aggregate_payment_methods
from ..julo.statuses import ApplicationStatusCodes
from ..julo.tasks import (
    create_application_checklist_async,
    send_data_to_collateral_partner_async,
    upload_image,
    upload_voice_record,
)
from ..julo.tasks2.application_tasks import send_deprecated_apps_push_notif
from ..julo.utils import (
    check_email,
    display_rupiah,
    generate_email_key,
    post_anaserver,
    push_file_to_s3,
    splitAt,
)
from .data import DropDownData, get_all_versions, get_dropdown_versions_by_product_line
from .data.addresses import get_addresses_dropdown_by_product_line
from .data.loan_purposes import get_loan_purpose_dropdown_by_product_line
from .exceptions import EmailNotVerified, ResourceNotFound
from .filters import (
    ApplicationFilter,
    DeviceFilter,
    DeviceGeolocationFilter,
    ImageFilter,
    LoanFilter,
    OfferFilter,
    PaymentFilter,
)
from .serializers import (
    AddressGeolocationSerializer,
    ApplicationSerializer,
    AppVersionHistorySerializer,
    BankScrapingStartSerializer,
    CollateralSerializer,
    CustomerSerializer,
    DeviceGeolocationSerializer,
    DeviceSerializer,
    EmailSerializer,
    FacebookDataSerializer,
    FacebookUserTokenSerializer,
    ImageSerializer,
    LoanSerializer,
    LoginSerializer,
    OfferSerializer,
    PartnerReferralSerializer,
    PaymentSerializer,
    ProductLineSerializer,
    ScrapedDataSerializer,
    SiteMapArticleSerializer,
    ImageListCreateViewV1Serializer,
    UserTokenSerializer,
    VoiceRecordHyperSerializer,
    VoiceRecordSerializer,
)

# hide Julo Mini to remove STL product from APP for google rules
# from .services import render_julomini_card
from .services import (
    determine_product_line,
    get_voice_record_script,
    render_account_summary_cards,
    render_campaign_card,
    render_season_card,
    render_sphp_card,
)
from .tasks import (
    send_customer_feedback_email,
    send_email_verification_email,
    send_reset_password_email,
)
from juloserver.apiv1.services import generate_dropdown_zip
from juloserver.pii_vault.services import detokenize_for_model_object
from juloserver.pii_vault.constants import PiiSource
from juloserver.julo.services2.payment_method import filter_payment_methods_by_lender
from juloserver.apiv1.services import is_allowed_to_upload_photo

logger = JuloLog(__name__)
MAX_LENGTH_USERNAME = 30
MAX_LENGTH_EMAIL_USERNAME = MAX_LENGTH_USERNAME - 1


class BankScrapingStart(APIView):
    serializer_class = BankScrapingStartSerializer

    def post(self, request):
        headers = {'Authorization': 'Token %s' % settings.SCRAPER_TOKEN}
        data = request.data
        data['customer_id'] = request.user.customer.id
        page_type = request.data.get('page_type')
        data['job_type'] = EtlJobType.NORMAL if not page_type else page_type

        result = requests.post(
            settings.SCRAPER_BASE_URL + '/api/etl/v1/scrape_jobs/', json=data, headers=headers
        )

        return Response(status=result.status_code, data=result.json())


class BankScrapingGet(APIView):
    def get(self, request, job_id):
        headers = {'Authorization': 'Token %s' % settings.SCRAPER_TOKEN}
        result = requests.get(
            settings.SCRAPER_BASE_URL + '/api/etl/v1/scrape_jobs/{}/'.format(job_id),
            data=request.data,
            headers=headers,
        )
        return Response(status=result.status_code, data=result.json())


class ObtainJuloToken(ObtainAuthToken):
    """
    API endpoint that allows exchange between facebook's user token with
    julo's API token.
    """

    # TODO: this view will be deprecated, we don't use it anymore
    parser_classes = (parsers.FormParser,)
    serializer_class = FacebookUserTokenSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        token, created = Token.objects.get_or_create(user=user)
        return Response({'token': token.key})


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


class UserOwnedRetrieveUpdateView(GetUserOwnedQuerySetMixin, generics.RetrieveUpdateAPIView):
    # To be set by the child class
    model_class = None

    def perform_update(self, serializer):
        user = self.request.user
        serializer.save(customer=user.customer)


class UserOwnedListView(GetUserOwnedQuerySetMixin, generics.ListAPIView):
    # To be set by the child class
    model_class = None


class UserOwnedRetrieveView(GetUserOwnedQuerySetMixin, generics.RetrieveAPIView):
    # To be set by the child class
    model_class = None


class ApplicationListCreateView(UserOwnedListCreateView):
    """
    API endpoint that allows current user's applications to be submitted and
    listed.
    """

    model_class = Application
    serializer_class = ApplicationSerializer
    filter_class = ApplicationFilter

    def perform_create(self, serializer):

        user = self.request.user

        if not user.customer.can_reapply:
            logger.warning(
                {
                    'msg': 'creating application when can_reapply is false',
                    'customer_id': user.customer.id,
                }
            )

        if not user.customer.is_email_verified:
            raise EmailNotVerified(email=user.customer.email)

        device_id = self.request.data.get('device_id')
        device = Device.objects.get_or_none(id=device_id, customer=user.customer)
        if device is None:
            raise ResourceNotFound(resource_id=device_id)

        # BACKWARD: existing apps will not pass this parameter and applications
        # submitted from those apps will have default product line
        if 'product_line_code' not in self.request.data:
            product_line = ProductLine.objects.get(product_line_code=ProductLineCodes.MTL1)
        else:
            product_line_code = self.request.data.get('product_line_code')
            product_line = ProductLine.objects.get_or_none(product_line_code=product_line_code)
            if not product_line:
                raise ResourceNotFound(resource_id=product_line_code)

        if 'application_number' in self.request.data:
            application_number = self.request.data.get('application_number')
            submitted_application = (
                Application.objects.regular_not_deletes()
                .filter(customer=user.customer, application_number=application_number)
                .first()
            )
            if submitted_application is not None:
                logger.warn(
                    {
                        'status': 'application_already_submitted',
                        'action': 'do_nothing',
                        'application_number': application_number,
                        'customer': user.customer,
                    }
                )
                return
        product_line = determine_product_line(user.customer, self.request.data)
        application = serializer.save(
            customer=user.customer, device=device, product_line=product_line
        )

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

        send_deprecated_apps_push_notif.delay(application.id, application.app_version)
        process_application_status_change(
            application.id,
            ApplicationStatusCodes.FORM_SUBMITTED,
            change_reason='customer_triggered',
        )
        logger.info(
            {
                'status': 'form_submitted',
                'application': application,
                'customer': user.customer,
                'device': device,
            }
        )

        application = Application.objects.get(id=application.id)
        link_to_partner_by_product_line(application)
        create_application_checklist_async.delay(application.id)


class ApplicationRetrieveUpdateView(UserOwnedRetrieveUpdateView):
    """
    API endpoint that allows current user's applications to be retrieved and
    updated.
    """

    model_class = Application
    serializer_class = ApplicationSerializer
    lookup_url_kwarg = 'application_id'

    def perform_update(self, serializer):
        """
        A post save behavior to update the application status when these fields
        are passed:
        * is_document_submitted
        * is_sphp_signed

        Note: validations are done in the serializer
        """
        application = serializer.save()
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

        send_deprecated_apps_push_notif.delay(application.id, application.app_version)
        is_document_submitted = self.request.data.get('is_document_submitted')
        if is_document_submitted is not None:
            if application.status == ApplicationStatusCodes.FORM_SUBMITTED:  # 110
                if application.product_line.product_line_code in ProductLineCodes.ctl():
                    send_data_to_collateral_partner_async.delay(application.id)
                    process_application_status_change(
                        application.id,
                        ApplicationStatusCodes.PENDING_PARTNER_APPROVAL,  # 129
                        change_reason='customer_triggered',
                    )
                else:
                    process_application_status_change(
                        application.id,
                        ApplicationStatusCodes.DOCUMENTS_SUBMITTED,  # 120
                        change_reason='customer_triggered',
                    )

            elif (
                application.status == ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED
            ):  # 131
                application = Application.objects.get_or_none(pk=application.id)
                app_history = ApplicationHistory.objects.filter(
                    application=application,
                    status_new=ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
                    status_old__in=[
                        ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
                        ApplicationStatusCodes.FACE_RECOGNITION_AFTER_RESUBMIT,
                    ],
                ).last()
                passed_face_recog = AwsFaceRecogLog.objects.filter(
                    application=application, is_quality_check_passed=True
                ).last()
                # check if app_history from 120 or 1311
                if app_history and not passed_face_recog:
                    application_status_code = ApplicationStatusCodes.FACE_RECOGNITION_AFTER_RESUBMIT
                else:
                    application_status_code = ApplicationStatusCodes.APPLICATION_RESUBMITTED
                process_application_status_change(
                    application.id,
                    application_status_code,  # 132
                    change_reason='customer_triggered',
                )
            elif application.status == ApplicationStatusCodes.DIGISIGN_FACE_FAILED:  # 147
                process_application_status_change(
                    application.id,
                    ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING,  # 150
                    change_reason='customer_triggered',
                )

        is_sphp_signed = self.request.data.get('is_sphp_signed')
        if is_sphp_signed is not None:
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


class CustomerRetrieveView(generics.ListAPIView):
    """
    API endpoint that allows current user's retrieve his/her profile data.
    """

    model_class = Customer
    serializer_class = CustomerSerializer

    def get_queryset(self):
        user = self.request.user
        return self.__class__.model_class.objects.filter(user=user)

    def put(self, request):
        user = self.request.user
        customer = user.customer
        if 'is_review_submitted' in request.data:
            is_review_submitted = self.request.data.get('is_review_submitted')
            if is_review_submitted in ('False', 'false', 'f', '0'):
                customer.is_review_submitted = False
            elif is_review_submitted in ('True', 'true', 't', '1'):
                customer.is_review_submitted = True
            elif is_review_submitted in ('Null', 'None', ''):
                customer.is_review_submitted = None

            customer.save()

        logger.info(
            {
                'status': 'mark is_review_submitted',
                'customer_id': customer.id,
                'is_review_submitted': self.request.data.get('is_review_submitted'),
            }
        )

        return Response([customer.id, customer.is_review_submitted])


class CustomerAgreementRetrieveView(APIView):
    permission_classes = []
    authentication_classes = []

    def get(self, request, customer_id):
        encrypter = encrypt()
        decoded_customer_id = encrypter.decode_string(customer_id)
        if not decoded_customer_id:
            return Response(status=HTTP_400_BAD_REQUEST, data="invalid token")
        # warning_method = request.GET.get("type", "1")
        customer = Customer.objects.get_or_none(pk=decoded_customer_id)
        # if not WarningUrl.objects.filter(customer=customer, warning_method=warning_method,
        # is_enabled=True).exists():
        #     return Response(status=HTTP_400_BAD_REQUEST, data="invalid page")
        loan = Loan.objects.filter(customer=customer, loan_status__lt=250).order_by('cdate').last()
        if not loan or not customer:
            return Response(status=HTTP_404_NOT_FOUND, data="resource not found")
        application = loan.application

        payment_method = PaymentMethod.objects.filter(loan=loan, payment_method_code=319322).first()

        due_payment = (
            Payment.objects.by_loan(loan=loan)
            .filter(payment_status__lte=327, payment_status__gte=320)
            .order_by('due_date')
        )

        all_payments = Payment.objects.by_loan(loan).values(
            "pk", "due_date", 'payment_number', 'due_amount'
        )

        if due_payment:
            not_payed_start = due_payment.first().due_date
            not_payed_end = due_payment.last().due_date
            principal_sum = due_payment.aggregate(Sum('installment_principal'))[
                'installment_principal__sum'
            ]
            late_fee_applied_sum = due_payment.aggregate(Sum('late_fee_amount'))[
                'late_fee_amount__sum'
            ]
            installment_interest = due_payment.aggregate(Sum('installment_interest'))[
                'installment_interest__sum'
            ]
            paid_sum = due_payment.aggregate(Sum('paid_amount'))['paid_amount__sum']
            change_due_date_interest = due_payment.aggregate(Sum('change_due_date_interest'))[
                'change_due_date_interest__sum'
            ]

            # due_sum = principal_sum + late_fee_applied_sum + installment_interest
            while paid_sum > 0:
                if principal_sum > 0:
                    if paid_sum > principal_sum:
                        paid_sum -= principal_sum
                        principal_sum = 0
                    else:
                        principal_sum -= paid_sum
                        paid_sum = 0
                elif installment_interest > 0:
                    if paid_sum > installment_interest:
                        paid_sum -= installment_interest
                        installment_interest = 0
                    else:
                        installment_interest -= paid_sum
                        paid_sum = 0
                elif late_fee_applied_sum > 0:
                    if paid_sum > late_fee_applied_sum:
                        paid_sum -= late_fee_applied_sum
                        late_fee_applied_sum = 0
                    else:
                        late_fee_applied_sum -= paid_sum
                        paid_sum = 0

                elif change_due_date_interest > 0:
                    if paid_sum > change_due_date_interest:
                        paid_sum -= change_due_date_interest
                        change_due_date_interest = 0
                    else:
                        change_due_date_interest -= paid_sum
                        paid_sum = 0
            total_sum = (
                principal_sum
                + late_fee_applied_sum
                + installment_interest
                + change_due_date_interest
            )
        else:
            not_payed_start = ""
            not_payed_end = ""
            principal_sum = ""
            late_fee_applied_sum = ""
            installment_interest = ""
            total_sum = ""

        payment_method_lookup = PaymentMethodLookup.objects.filter(name=loan.julo_bank_name).first()
        if payment_method_lookup:
            bank_code = payment_method_lookup.code
        else:
            bank_code = ""

        data = {
            "customer": {
                "email": customer.email,
                "fullname": customer.fullname,
                "phone": customer.phone,
            },
            "loan": {
                "amount": loan.loan_amount,
                "loan_duration": loan.loan_duration,
                "provision_fee": loan.provision_fee(),
                "interest_percent_monthly": loan.interest_percent_monthly(),
                "late_fee_amount": loan.late_fee_amount,
                "va_number": loan.payment_virtual_accounts,
                "sphp_accepted_ts": loan.sphp_accepted_ts,
                "installment_amount": loan.installment_amount,
                "first_installment_amount": loan.first_installment_amount,
                "julo_bank_account_number": loan.julo_bank_account_number,
                "not_payed_start": not_payed_start,
                "not_payed_end": not_payed_end,
                "due_amount_sum": principal_sum,
                "installment_interest": installment_interest,
                "late_fee_applied_sum": late_fee_applied_sum,
                "total_sum": total_sum,
                "julo_bank_name": loan.julo_bank_name,
                "now": timezone.now().date(),
                "bank_code": bank_code,
            },
            "application": {
                "application_xid": application.application_xid,
                "ktp": application.ktp,
                "dob": application.dob,
                "full_address": application.complete_addresses,
                "bank_name": application.bank_name,
                "bank_branch": application.bank_branch,
                "gender": application.gender,
                "full_name": application.fullname_with_title,
            },
            "product": {
                "product_name": loan.product.product_name,
                "product_code": loan.product.product_code,
                "product_line_code": loan.product.product_line.product_line_code,
                "product_line_type": loan.product.product_line.product_line_type,
            },
            "payemnts": all_payments,
        }

        if payment_method:
            data['loan']['payment_method_name'] = payment_method.payment_method_name
            data['loan']['virtual_account'] = payment_method.virtual_account
        else:
            data['loan']['payment_method_name'] = ""
            data['loan']['virtual_account'] = ""
        return Response(data=data)


class FacebookDataListCreateView(APIView):
    """
    API for creating FacebookData.
    """

    def post(self, s):
        application_id = self.request.POST.get('application', '')
        serializer = FacebookDataSerializer(data=self.request.POST)
        if application_id == '':
            # Backwards compatibility
            customer = Customer.objects.get(id=self.request.user.customer.id)
            query = customer.application_set
            query = query.filter(
                application_status__gte=ApplicationStatusCodes.FORM_SUBMITTED,
                facebook_data__isnull=True,
            )
            if not query.count():
                return Response(
                    status=HTTP_201_CREATED, data={'error': 'No applications without FBData'}
                )
            for application in query.all():
                serializer.initial_data['application'] = application.id
                serializer.id = None
                serializer.is_valid(raise_exception=True)
                serializer.save()
        else:
            # here skip the saving to db if already exists.
            if application_id and int(application_id) > 0:
                fb_data_qs = FacebookData.objects.filter(application=application_id)
                if fb_data_qs.exists():
                    fb_data = fb_data_qs.first()
                    return Response(status=HTTP_200_OK, data=model_to_dict(fb_data))

            serializer.is_valid(raise_exception=True)
            serializer.save()
        return Response(status=HTTP_201_CREATED, data=serializer.data)


class FacebookDataRetrieveUpdateView(UserOwnedRetrieveUpdateView):
    """
    API endpoint that allows current user's facebookdata to be retrieved and
    updated.
    """

    model_class = FacebookData
    serializer_class = FacebookDataSerializer
    lookup_url_kwarg = 'facebook_data_id'


class DeviceListCreateView(UserOwnedListCreateView):
    """
    API endpoint that allows current user's devices to be added and listed.
    """

    model_class = Device
    serializer_class = DeviceSerializer
    filter_class = DeviceFilter


class DeviceRetrieveUpdateView(UserOwnedRetrieveUpdateView):
    """
    API endpoint that allows current user's devices to be retrieved and
    updated.
    """

    model_class = Device
    serializer_class = DeviceSerializer
    lookup_url_kwarg = 'device_id'


class OfferListView(generics.ListAPIView):
    """
    API endpoint that allows current user's approved application offers to be
    listed.
    """

    serializer_class = OfferSerializer
    filter_class = OfferFilter

    def get_queryset(self):
        user = self.request.user
        application_id = self.kwargs['application_id']

        application = Application.objects.get_or_none(id=application_id, customer=user.customer)
        if application is None:
            raise ResourceNotFound(resource_id=application_id)

        return Offer.objects.shown_for_application(application)


class OfferRetrieveUpdateView(generics.RetrieveUpdateAPIView):
    """
    API endpoint that allows current user's approved application offers to be
    retrieved and updated (accepted).
    """

    serializer_class = OfferSerializer
    lookup_url_kwarg = 'offer_id'

    def perform_update(self, serializer):

        user = self.request.user
        application_id = self.kwargs['application_id']
        offer_id = self.kwargs['offer_id']

        if not self.request.data.get('is_accepted'):
            logger.warn("Attempt to un-accept offer_id=%s" % offer_id)
            raise serializers.ValidationError("Action not allowed")

        application = Application.objects.get_or_none(id=application_id, customer=user.customer)
        if application is None:
            raise ResourceNotFound(resource_id=application_id)

        offer = Offer.objects.get_or_none(id=offer_id, application=application)
        if offer is None:
            raise ResourceNotFound(resource_id=offer_id)
        if offer.is_accepted:
            logger.warn("The offer=%s was already accepted before, ignore..." % offer)
            raise serializers.ValidationError("Offer already accepted")
        with transaction.atomic():
            serializer.save()
            process_application_status_change(
                application.id,
                ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
                change_reason='customer_triggered',
            )

    def get_queryset(self):

        user = self.request.user
        application_id = self.kwargs['application_id']

        application = Application.objects.get_or_none(id=application_id, customer=user.customer)
        if application is None:
            raise ResourceNotFound(resource_id=application_id)

        return Offer.objects.shown_for_application(application)


class ImageListCreateView(APIView):
    """
    This end point handles used for upload new image (image_source needs to be given).

    TODO: This endpoint SHOULD implement file type verification,
        currently doing this by wrapping it on ImageListCreateViewV1 to prevent breaking changes
    """

    # upload image providing image binary and the image_source
    @parser_classes(
        (
            FormParser,
            MultiPartParser,
        )
    )
    def post(self, request, *args, **kwargs):
        if 'upload' not in request.data:
            return Response(status=HTTP_400_BAD_REQUEST)

        image = Image()
        image_type = request.data['image_type']
        image_source = request.data['image_source']

        if image_type is not None:
            image.image_type = image_type
        if image_source is None:
            return Response(status=HTTP_400_BAD_REQUEST, data='Invalid image_source')

        image.image_source = int(image_source)
        customer = self.request.user.customer
        if 1000000000 < int(image.image_source) < 1999999999:
            if customer.id != image.image_source:
                return Response(
                    status=HTTP_404_NOT_FOUND, data="Customer id=%s not found" % image.image_source
                )
        if 2000000000 < int(image.image_source) < 2999999999:
            if not customer.application_set.filter(id=image_source).exists():
                return Response(
                    status=HTTP_404_NOT_FOUND,
                    data="Application id=%s not found" % image.image_source,
                )
        elif 3000000000 < int(image.image_source) < 3999999999:
            if not customer.application_set.filter(loan=3000000001).exists():
                return Response(
                    status=HTTP_404_NOT_FOUND, data="Loan id=%s not found" % image.image_source
                )
        image.save()
        upload = request.data['upload']
        image.image.save(image.full_image_name(upload.name), upload)

        upload_image.apply_async((image.id,), countdown=3)

        return Response(status=HTTP_201_CREATED, data={'id': str(image.id)})


class ImageListCreateViewV1(ImageListCreateView):
    def post(self, request, *args, **kwargs):
        try:
            serializer = ImageListCreateViewV1Serializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            validated_data = serializer.validated_data
            is_allowed = is_allowed_to_upload_photo(validated_data)
            if not is_allowed:
                return Response(status=HTTP_400_BAD_REQUEST, data='request is not allowed')

        except ValidationError as e:
            logger.error({'action': 'apiv1_image_list_create_view_v1', 'errors': str(e)})
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={
                    'success': False,
                    'data': None,
                    'errors': e.detail.get('upload')[0] if e.detail.get('upload') else str(e),
                },
            )
        return super().post(request, args, kwargs)


class SiteMapArticleView(APIView):
    """
    API endpoint that allows current user's approved application offers to be
    listed.

    """

    """
    API endpoint that allows sitemap to be listed.

    """
    permission_classes = []
    authentication_classes = []
    serializer_class = SiteMapArticleSerializer

    def get(self, request):

        site_map_content = SiteMapJuloWeb.objects.all().values('label_url', 'label_name')
        if site_map_content:
            data = {'data': site_map_content}
            return Response(status=HTTP_200_OK, data=data)
        else:
            return Response(status=HTTP_200_OK, data={'data': []})


class ImageListView(generics.ListAPIView):

    serializer_class = ImageSerializer
    filter_class = ImageFilter

    def get_queryset(self):

        user = self.request.user
        application_id = self.kwargs['application_id']
        include_deleted = self.request.query_params.get('include_deleted', 'false')
        application = (
            Application.objects.select_related('customer').filter(id=application_id).last()
        )

        if application.customer.user_id != user.id:
            logger.warning(
                {"message": "Resource not found", "application_id": application_id},
                request=self.request,
            )
            raise ResourceNotFound(resource_id=application_id)

        images = Image.objects.filter(image_source=application_id)

        if include_deleted == 'false':
            images = images.exclude(image_status=Image.DELETED)

        if not images:
            logger.warning(
                {"message": "Resource not found", "application_id": application_id},
                request=self.request,
            )
            raise ResourceNotFound(resource_id=application_id)

        logger.info(
            {"message": "Resource is found", "application_id": application_id}, request=self.request
        )
        return images


class VoiceRecordScriptView(APIView):
    def get(self, request, application_id):
        user = self.request.user
        application = get_object_or_404(Application, id=application_id)

        if user.id != application.customer.user_id:
            return Response(
                status=HTTP_403_FORBIDDEN, data={'errors': 'User not allowed', 'user_id': user.id}
            )

        return Response({'script': get_voice_record_script(application)})


class VoiceRecordCreateView(generics.CreateAPIView):
    serializer_class = VoiceRecordSerializer

    def perform_create(self, serializer):
        if 'upload' not in self.request.POST:
            exception = APIException('Field "upload" is required')
            exception.status_code = 400
            raise exception
        applications = [str(x.id) for x in self.request.user.customer.application_set.all()]
        if self.request.data.get('application', 1) not in applications:
            exception = APIException("Not allowed")
            exception.status_code = 403
            raise exception
        voice_record = serializer.save()
        voice_file = self.request.data['upload']
        voice_record.tmp_path.save(voice_file.name, voice_file)
        upload_voice_record.delay(voice_record.id)


class VoiceRecordListView(generics.ListAPIView):
    serializer_class = VoiceRecordHyperSerializer

    def get_queryset(self):
        application_id = self.kwargs['application_id']
        include_deleted = self.request.query_params.get('include_deleted', 'false')
        qs = VoiceRecord.objects.filter(application=application_id)
        if include_deleted == 'false':
            qs = qs.exclude(status=VoiceRecord.DELETED)
        return qs


class ScrapedDataViewSet(generics.ListCreateAPIView):
    """
    This end point handles the query for device scraped data
    upload new data file.
    """

    serializer_class = ScrapedDataSerializer

    def __init__(self, *args, **kwargs):
        super(ScrapedDataViewSet, self).__init__(*args, **kwargs)

    # filter by application_id
    def get_queryset(self):
        application_id = self.request.query_params.get('application_id', None)
        user = self.request.user
        application = Application.objects.get_or_none(id=application_id, customer=user.customer)
        if application is None:
            raise ResourceNotFound(resource_id=application_id)

        queryset = DeviceScrapedData.objects.by_application(application)

        return queryset

    # upload file providing file path and the application_id
    @parser_classes(
        (
            FormParser,
            MultiPartParser,
        )
    )
    def post(self, request, *args, **kwargs):
        if 'upload' in request.data:

            application_id = request.data['application_id']
            user = self.request.user

            if 'file_type' in request.data:
                file_type = request.data['file_type']
            else:
                file_type = None

            application = Application.objects.get_or_none(id=application_id, customer=user.customer)
            if application is None:
                raise ResourceNotFound(resource_id=application_id)

            dsd = DeviceScrapedData()
            dsd.application = application
            dsd.file_type = file_type
            dsd.save()
            upload = request.data['upload']
            dsd.file.save(upload.name, upload)

            # build folder structure in s3
            s3_key_path = construct_s3_key_scraped_data(self.request.user.customer.id, dsd)

            # upload to s3 and getting s3 URL
            s3url = push_file_to_s3(
                settings.S3_DATA_BUCKET, settings.MEDIA_ROOT + '/' + dsd.file.name, s3_key_path
            )

            # set url field to s3 url
            dsd.url = s3url
            dsd.save(update_fields=["url"])
            dsd_path = dsd.file.path
            if os.path.isfile(dsd_path):
                logger.info({'action': 'deleting_local_file', 'dsd_path': dsd_path})
                dsd.file.delete()

            # Start parsing on anaserver
            ana_data = {
                'application_id': application_id,
                'customer_id': application.customer_id,
                'dsd_id': dsd.id,
                "s3_url_raw": s3url,
                "data_type": "dsd",
            }
            post_anaserver('/api/etl/v1/etl_create/', data=ana_data)

            # Mark rescrape action completed if not already marked
            customer = application.customer
            incomplete_rescrape_action = CustomerAppAction.objects.get_or_none(
                customer=customer, action='rescrape', is_completed=False
            )
            if incomplete_rescrape_action:
                incomplete_rescrape_action.mark_as_completed()
                incomplete_rescrape_action.save()

            # return image_id as requested by Vishal
            return Response(status=HTTP_201_CREATED, data={'id': str(dsd.id)})
        else:
            return Response(status=HTTP_400_BAD_REQUEST)


def construct_s3_key_scraped_data(customer_id, dsd):
    """
    Using some input constructing
    folder structure in s3
    """
    # getting userid as folder name
    _, file_extension = os.path.splitext(dsd.file.name)
    filename = 'scrapdata' + '_' + str(dsd.id) + file_extension
    s3_key_path = '/'.join(
        ['cust_' + str(customer_id), 'application_' + str(dsd.application.id), filename]
    )
    logger.info({'dsd': dsd.id, 's3_key_path': s3_key_path})
    return s3_key_path


class ScrapedDataMultiPartParserViewSet(generics.RetrieveUpdateAPIView):
    """
    this end point handles the query for existing image by id and updating the image binary
    """

    queryset = DeviceScrapedData.objects.all()
    serializer_class = ScrapedDataSerializer

    def __init__(self, *args, **kwargs):
        super(ScrapedDataMultiPartParserViewSet, self).__init__(*args, **kwargs)

    @parser_classes((MultiPartParser,))
    def put(self, request, *args, **kwargs):
        if 'upload' in request.data:
            dsd = self.get_object()
            dsd.file.delete()
            upload = request.data['upload']
            dsd.file.save(upload.name, upload)

            # build folder structure in s3
            dest_name = construct_s3_key_scraped_data(self.request.user.customer.id, dsd)

            # upload to s3 and getting s3 URL
            s3url = push_file_to_s3(
                settings.S3_DATA_BUCKET, settings.MEDIA_ROOT + '/' + dsd.file.name, dest_name
            )

            # set url field to s3 url
            dsd.url = s3url
            dsd.save(update_fields=["url"])

        # image_id as requested by Vishal
        return Response(status=HTTP_201_CREATED, data={'id': str(dsd.id)})


class ObtainUsertoken(ObtainAuthToken):
    """
    simple usertoken endpoint using username, password, email
    """

    serializer_class = UserTokenSerializer

    def __init__(self, *args, **kwargs):
        super(ObtainUsertoken, self).__init__(*args, **kwargs)

    def post(self, request, *args, **kwargs):
        """Handles user registration"""

        email = request.data['email'].strip().lower()

        password1 = request.data['password1']
        password2 = request.data['password2']
        if password1 != password2:
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={"Passwords don't match. Carefully re-enter password."},
            )

        with transaction.atomic():
            customer = Customer.objects.get_or_none(email=email)
            if customer:
                logger.warn("Registration failed, email=%s already exists", request=request)
                return Response(
                    status=HTTP_400_BAD_REQUEST,
                    data={"Email already exists. Please use another email."},
                )

            if len(email) > MAX_LENGTH_EMAIL_USERNAME:
                username_to_search = email[:MAX_LENGTH_EMAIL_USERNAME]
            else:
                username_to_search = email
            logger.debug(
                "Searching for username that starts with " + username_to_search, request=request
            )

            username_prefix_count = User.objects.filter(
                username__startswith=username_to_search
            ).count()
            if username_prefix_count > 0:
                # E.g. if there are 3 matches, this would be the forth one. Append
                # number 3 to the username.
                username = username_to_search + str(username_prefix_count)
            else:
                username = username_to_search

            if len(username) > MAX_LENGTH_USERNAME:
                # NOTE: This should not happen unless user count is big. Basically,
                # this happens when registering <username_duplicate>10.
                logger.warn("Unable to register username=%s too long" % username, request=request)
                return Response(
                    status=HTTP_400_BAD_REQUEST,
                    data={"Email not allowed. Please user another email."},
                )

            logger.debug("Registering new user with username=%s" % username)
            email_valid = check_email(email)

            if email_valid is True:
                try:
                    user = User.objects.create_user(
                        username=username, password=password1, email=email
                    )
                except IntegrityError:
                    logger.warn("Registration failed, email=%s already exists", request=request)
                    return Response(
                        status=HTTP_400_BAD_REQUEST,
                        data={"Email already exists. Please use another email."},
                    )
                logger.info("Sucessfully created user=%s" % user, request=request)

                ver_key = generate_email_key(email)
                exp_date = datetime.now() + timedelta(days=7)

                customer = Customer.objects.create(
                    user=user,
                    email=email,
                    email_verification_key=ver_key,
                    email_key_exp_date=exp_date,
                )

                partner_referral = PartnerReferral.objects.filter(cust_email=email).last()
                if partner_referral:
                    partner_referral.customer = customer
                    logger.info(
                        {
                            'action': 'create_link_partner_referral_to_customer',
                            'customer_id': customer.id,
                            'partner_referral_id': partner_referral.id,
                            'email': email,
                        },
                        request=request,
                    )
                    partner_referral.save()

                send_email_verification_email.delay(email, ver_key)
                logger.info("Customer with customerid=%d registered" % customer.id, request=request)

                token, created = Token.objects.get_or_create(user=user)
                logger.info("Returning token for customer=%s" % customer, request=request)

                return Response({'token': token.key})
            else:
                logger.error({"message": "Email is not valid", "email": email}, request=request)
                return Response(status=HTTP_400_BAD_REQUEST, data={"Email is not valid."})


class GetCustomerTotalApplication(generics.ListCreateAPIView):
    """
    end point for obtaining user's total application
    """

    def get(self, request, *args, **kwargs):
        user = request.user
        customer = user.customer
        application_count = (
            Application.objects.regular_not_deletes().filter(customer_id=customer.id).count()
        )
        logger.info(message="Total application=%s" % application_count, request=request)
        return Response({'count': application_count})


class SendEmailToDev(generics.ListCreateAPIView):
    """
    end point for send email to dev when app errors
    """

    def post(self, request, *args, **kwargs):
        user_email = request.data['email'].strip().lower()
        stack_trace = request.data['stack_trace']
        julo_email_client = get_julo_email_client()
        julo_email_client.send_email(
            settings.EMAIL_SUBJECT_APP_ERROR,
            user_email + ' - ' + stack_trace,
            settings.EMAIL_DEV,
            settings.EMAIL_FROM,
        )
        return Response({'success': "E-mail has been sent."})


class SendFeedbackToCS(generics.ListCreateAPIView):
    """
    end point for send email to julo
    """

    def post(self, request, *args, **kwargs):
        sentry_client = get_julo_sentry_client()

        try:
            user_email = request.data['email'].strip().lower()
            full_name = request.data['full_name'].strip()
            feedback = request.data['feedback'].strip()
            email_subject = request.data['email_subject'].strip()
            application_id = request.data['application_id'].strip()
        except Exception:
            sentry_client.captureException()
            return Response(status=HTTP_404_NOT_FOUND, data={'failed': "Invalid parameters"})

        try:
            send_customer_feedback_email.delay(
                user_email, full_name, email_subject, application_id, feedback
            )
        except Exception:
            sentry_client.captureException()
            return Response(status=HTTP_404_NOT_FOUND, data={'failed': "Failed sending E-mail"})

        return Response({'success': "E-mail has been sent."})


class ResendEmail(generics.ListCreateAPIView):
    """
    end point for resend email confirmation
    """

    serializer_class = EmailSerializer

    def post(self, request, *args, **kwargs):
        email = request.data['email'].strip().lower()
        user = request.user
        if user.email != email:
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={"The email doesn't match the one we currently have in our database"},
            )

        customer = user.customer
        ver_key = generate_email_key(email)
        exp_date = datetime.now() + timedelta(days=7)
        customer.email_verification_key = ver_key
        customer.email_key_exp_date = exp_date
        customer.save()

        send_email_verification_email.delay(email, ver_key)

        return Response({'success': "E-mail has been sent."})


class VerifyEmail(ObtainAuthToken):
    """
    end point for email verification
    """

    renderer_classes = [TemplateHTMLRenderer]

    def get(self, request, *args, **kwargs):
        verification_key = self.kwargs['verification_key']
        customer = Customer.objects.get_or_none(email_verification_key=verification_key)
        if customer is None:
            logger.error("Can\'t verify email. Link is not valid.")
            return Response(template_name='verification_response_invalid.html')
        # verify if verification key hasn't expired
        if customer.has_emailkey_expired():
            logger.error("Email verification key expired.")
            return Response(template_name='verification_response_expired.html')
        # everything is fine here
        customer.is_email_verified = True
        customer.save(update_fields=["is_email_verified"])

        return Response(template_name='verification_response.html')


class EmailStatus(generics.ListAPIView):  # ListAPIView
    """
    end point for email status
    """

    serializer_class = EmailSerializer

    def get(self, request, *args, **kwargs):
        email = self.request.query_params.get('email', None)
        if email:
            email = email.strip().lower()
        user = request.user

        if user.email != email:
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={"The email doesn't match the one we currently have in our database"},
            )

        customer = user.customer

        if customer.is_email_verified:
            response = Response({'verified': "1"})
        else:
            response = Response({'verified': "0"})
        return response


class Login(ObtainAuthToken):
    """
    end point to handle login
    """

    serializer_class = LoginSerializer

    def post(self, request, *args, **kwargs):

        email = request.data['email'].strip().lower()
        password = request.data['password']

        customer = Customer.objects.get_or_none(email=email)
        if not customer:
            logger.error("User with email=%s doesn't exist" % email)
            return Response({'message': "Sorry, Julo doesn't recognize this email."})

        logger.debug("Authenticating with django username=%r" % customer.user.username)
        user = authenticate(username=customer.user.username, password=password)

        if not user:
            logger.error("User with email=%r doesn't exist" % email)
            return Response({'message': 'Either password or email is incorrect'})

        if not customer.is_email_verified:
            logger.error("This email=%s hasn't been confirmed" % email)
            return Response({'message': "Email hasn't been confirmed"})

        if not user.is_active:
            logger.error("Account for email=%s is not active!" % email)
            return Response({'message': 'The account is valid but has been disabled!'})

        logger.info("User with email=%s is valid, active and authenticated" % email)
        token, created = Token.objects.get_or_create(user=user)
        return Response({'token': token.key})


class LoginWithUnverifiedEmailView(Login):
    def post(self, request, *args, **kwargs):

        email = request.data['email'].strip().lower()
        password = request.data['password']

        customer = Customer.objects.get_or_none(email=email)
        if not customer:
            logger.error("User with email=%s doesn't exist" % email)
            return Response(
                status=HTTP_401_UNAUTHORIZED,
                data={'message': "Sorry, Julo doesn't recognize this email."},
            )

        logger.debug("Authenticating with django username=%r" % customer.user.username)
        user = authenticate(username=customer.user.username, password=password)

        if not user:
            logger.error("User with email=%r doesn't exist" % email)
            return Response(
                status=HTTP_401_UNAUTHORIZED,
                data={'message': 'Either password or email is incorrect'},
            )

        if not user.is_active:
            logger.error("Account for email=%s is not active!" % email)
            return Response(
                status=HTTP_401_UNAUTHORIZED,
                data={'message': 'The account is valid but has been disabled!'},
            )

        logger.info("User with email=%s is valid, active and authenticated" % email)
        token, created = Token.objects.get_or_create(user=user)

        # We want to return False even if it's None
        is_email_verified = customer.is_email_verified is True

        return Response({'token': token.key, 'is_email_verified': is_email_verified})


class ResetPassword(ObtainAuthToken):
    serializer_class = EmailSerializer

    def post(self, request, *args, **kwargs):
        """
        Handle user's request to send an email for resetting their password.
        """
        email = request.data['email'].strip().lower()

        email_valid = check_email(email)
        if not email_valid:
            logger.warn({'status': 'email_invalid', 'email': email})
            return Response(
                status=HTTP_200_OK,
                data={'message': "A password reset email will be sent if the email is registered"},
            )

        customer = Customer.objects.get_or_none(email__iexact=email)
        if customer is None or does_user_have_pin(customer.user):
            logger.warn({'status': 'email_not_in_database', 'email': email})
            return Response(
                status=HTTP_200_OK,
                data={'message': "A password reset email will be sent if the email is registered"},
            )

        new_key_needed = False
        if customer.reset_password_exp_date is None:
            new_key_needed = True
        else:
            if customer.has_resetkey_expired():
                new_key_needed = True

        if new_key_needed:
            reset_password_key = generate_email_key(email)
            customer.reset_password_key = reset_password_key
            reset_password_exp_date = datetime.now() + timedelta(days=7)
            customer.reset_password_exp_date = reset_password_exp_date
            customer.save()
            logger.info(
                {
                    'status': 'just_generated_reset_password',
                    'email': email,
                    'customer': customer,
                    'reset_password_key': reset_password_key,
                    'reset_password_exp_date': reset_password_exp_date,
                }
            )
        else:
            reset_password_key = customer.reset_password_key
            logger.info(
                {
                    'status': 'reset_password_key_already_generated',
                    'email': email,
                    'customer': customer,
                    'reset_password_key': reset_password_key,
                }
            )

        send_reset_password_email.delay(email, reset_password_key)

        return Response(
            {"message": "A password reset email will be sent if the email is registered"}
        )


class ResetPasswordConfirm(ObtainAuthToken):
    """
    end point for reset password page
    """

    renderer_classes = [TemplateHTMLRenderer]

    def get(self, request, *args, **kwargs):
        """
        Called when user clicks link in the reset password email.
        """
        reset_key = self.kwargs['reset_key']

        customer = Customer.objects.get_or_none(reset_password_key=reset_key)
        if customer is None or does_user_have_pin(customer.user):
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={'message': "reset key sudah tidak valid"},
                template_name='reset_password_failed.html',
            )

        if customer.has_resetkey_expired():
            customer.reset_password_key = None
            customer.reset_password_exp_date = None
            customer.save()
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={'message': "Reset key sudah expired."},
                template_name='reset_password_failed.html',
            )

        action = settings.RESET_PASSWORD_FORM_ACTION + reset_key + '/'
        return Response(
            {'email': customer.user.email, 'action': action}, template_name='reset_password.html'
        )

    def post(self, request, *args, **kwargs):
        """
        Called when user submits the reset password html form.
        """
        password1 = request.data['password1']
        password2 = request.data['password2']

        reset_key = self.kwargs['reset_key']

        if password1 is None or password2 is None or reset_key is None:
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={'message': 'Password kosong'},
                template_name='reset_password_failed.html',
            )

        if password1 != password2:
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={'message': "Password tidak sama."},
                template_name='reset_password_failed.html',
            )

        customer = Customer.objects.get_or_none(reset_password_key=reset_key)
        if customer is None or does_user_have_pin(customer.user):
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={'message': "Reset key tidak lagi valid."},
                template_name='reset_password_failed.html',
            )

        if customer.has_resetkey_expired():
            customer.reset_password_key = None
            customer.reset_password_exp_date = None
            customer.save()
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={'message': "Reset key sudah expired."},
                template_name='reset_password_failed.html',
            )

        with transaction.atomic():
            user = customer.user
            user.set_password(password1)
            user.save()
            customer.reset_password_key = None
            customer.reset_password_exp_date = None
            customer.save()

        return Response(template_name='reset_password_success.html')


class LoanListView(generics.ListAPIView):
    """
    API endpoint that allows current user's loans to be listed.
    """

    # model_class = Loan
    serializer_class = LoanSerializer
    filter_class = LoanFilter

    def get_queryset(self):
        customer = self.request.user.customer

        # monkey patch for case J1 account get blank on tagihan result
        if customer.account:
            queryset = customer.account.loan_set.order_by('-id')[:1]
        else:
            queryset = customer.loan_set.all()
        return queryset


class LoanRetrieveUpdateView(UserOwnedRetrieveUpdateView):
    """
    API endpoint that allows a current user's loan to be retrieved.
    """

    model_class = Loan
    serializer_class = LoanSerializer
    lookup_url_kwarg = 'loan_id'

    def get_queryset(self):
        return super(LoanRetrieveUpdateView, self).get_queryset()

    def perform_update(self, serializer):

        user = self.request.user
        loan_id = self.kwargs['loan_id']

        loan = Loan.objects.get_or_none(id=loan_id, customer=user.customer)
        if loan is None:
            raise ResourceNotFound(resource_id=loan_id)

        loan = serializer.save()

        if 'cycle_day_requested' in serializer.validated_data:
            loan.cycle_day_requested_date = date.today()
            loan.save()


class PaymentListView(generics.ListAPIView):
    """
    API endpoint that allows current user's activated loan payments to be
    listed.
    """

    serializer_class = PaymentSerializer
    filter_class = PaymentFilter
    pagination_class = None

    def get_queryset(self):
        user = self.request.user
        loan_id = self.kwargs['loan_id']

        loan = Loan.objects.get_or_none(id=loan_id, customer=user.customer)
        if loan is None:
            raise ResourceNotFound(resource_id=loan_id)

        return Payment.objects.by_loan(loan)


class PaymentRetrieveView(generics.RetrieveAPIView):
    """
    API endpoint that allows a current user's activated loan payment to be
    retrieved.
    """

    serializer_class = PaymentSerializer
    lookup_url_kwarg = 'payment_id'
    pagination_class = None

    def get_queryset(self):
        user = self.request.user
        loan_id = self.kwargs['loan_id']

        loan = Loan.objects.get_or_none(id=loan_id, customer=user.customer)
        if loan is None:
            raise ResourceNotFound(resource_id=loan_id)

        return Payment.objects.by_loan(loan)


class AddressGeolocationListCreateView(APIView):
    """
    API endpoint that allows current application's geolocation to be added and listed.
    """

    def get(self, request, *args, **kwargs):
        user = self.request.user
        application_id = self.kwargs['application_id']

        application = Application.objects.get_or_none(id=application_id, customer=user.customer)
        if application is None:
            raise ResourceNotFound(resource_id=application_id)

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

        response_data = {}
        address_geolocs = []
        address_geoloc_qs = AddressGeolocation.objects.by_application(application)
        if address_geoloc_qs.exists():
            address_geoloc = address_geoloc_qs.first()
            if address_geoloc:
                address_geolocs.append(model_to_dict(address_geoloc))
        response_data['results'] = address_geolocs  # front end expecting "results" element.

        return Response(status=HTTP_200_OK, data=response_data)

    def post(self, request, *args, **kwargs):

        # here skip the saving to db if already exists.
        application_id = request.data.get('application')
        customer = self.request.user.customer
        if application_id and int(application_id) > 0:
            address_geoloc_qs = AddressGeolocation.objects.by_application(application_id)
            if address_geoloc_qs.exists():
                address_geoloc = address_geoloc_qs.first()
                return Response(status=HTTP_200_OK, data=model_to_dict(address_geoloc))

        serializer = AddressGeolocationSerializer(data=self.request.POST)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        # store location to device_geolocation table
        store_device_geolocation(
            customer, latitude=serializer.data['latitude'], longitude=serializer.data['longitude']
        )
        return Response(status=HTTP_201_CREATED, data=serializer.data)


class DeviceGeolocationListCreateView(generics.ListCreateAPIView):
    """
    API endpoint that allows current device's geolocation to be added and listed.
    """

    serializer_class = DeviceGeolocationSerializer
    filter_class = DeviceGeolocationFilter

    def get_queryset(self):
        device_id = self.kwargs['device_id']

        device = Device.objects.get_or_none(id=device_id)
        if device is None:
            raise ResourceNotFound(resource_id=device_id)

        return DeviceGeolocation.objects.by_device(device)


class AddressGeolocationRetrieveUpdateView(generics.RetrieveUpdateAPIView):
    """
    API endpoint that allows application's geolocation to be retrieved and
    updated.
    """

    serializer_class = AddressGeolocationSerializer
    lookup_url_kwarg = 'address_geolocation_id'

    def perform_update(self, serializer):

        user = self.request.user
        application_id = self.kwargs['application_id']
        address_geolocation_id = self.kwargs['address_geolocation_id']

        application = Application.objects.get_or_none(id=application_id, customer=user.customer)
        if application is None:
            raise ResourceNotFound(resource_id=application_id)

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

        address_geolocation = AddressGeolocation.objects.get_or_none(
            id=address_geolocation_id, application=application
        )
        if address_geolocation is None:
            raise ResourceNotFound(resource_id=address_geolocation_id)

        serializer.save(application=application)

    def get_queryset(self):
        user = self.request.user
        application_id = self.kwargs['application_id']

        application = Application.objects.get_or_none(id=application_id, customer=user.customer)
        if application is None:
            raise ResourceNotFound(resource_id=application_id)

        return AddressGeolocation.objects.by_application(application)


class Privacy(generics.ListAPIView):
    """
    end point for privacy
    """

    def get(self, request, *args, **kwargs):
        text = render_to_string('privacy.txt')
        return Response({'text': text})


class Terms(generics.ListAPIView):
    """
    end point for terms and conditions (Syarat & Ketentuan)
    """

    def get(self, request, *args, **kwargs):
        text = render_to_string('terms.html')
        return Response({'text': text})


class HomeScreen(generics.ListAPIView):
    """
    end point for home screen page
    """

    def get(self, request, *args, **kwargs):

        cards = []

        customer = request.user.customer
        application_id = self.request.query_params.get('application_id', None)
        # app_version = self.request.query_params.get('app_version', None)

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

        _sphp_card_result = render_sphp_card(customer, application)
        if _sphp_card_result is not None:
            cards.append(_sphp_card_result)

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


class PartnerReferralListView(generics.ListAPIView):
    """
    API endpoint to get a list of e-commerce referrals by searching email
    """

    model_class = PartnerReferral
    serializer_class = PartnerReferralSerializer
    filter_backends = (filters.OrderingFilter, filters.SearchFilter)
    search_fields = ('cust_email',)

    def get_queryset(self):
        # Is ordered last one first since the last is probably the most relevent
        return self.__class__.model_class.objects.order_by('-cdate')


class AppVersionHistoryListView(generics.ListAPIView):
    """
    API endpoint to get a list of app version history
    """

    model_class = AppVersionHistory
    serializer_class = AppVersionHistorySerializer

    def get(self, request, *args, **kwargs):
        app_version_history = AppVersionHistory.objects.order_by('-id').first()

        if app_version_history is None:
            return JsonResponse({})

        response = JsonResponse(model_to_dict(app_version_history))
        return response


class DropDownApi(APIView):
    def get(self, request, product_line_code):
        if int(product_line_code) not in ProductLineCodes.all():
            if int(product_line_code) not in ProductLineCodes.julo_one():
                return Response(status=HTTP_404_NOT_FOUND, data={'Not found': 'Product line code'})
        in_memory, file_size = generate_dropdown_zip(request, product_line_code)
        if file_size > 22:  # A zip file binary header is 22 bytes
            in_memory.seek(0)
            response = HttpResponse(content=in_memory.read(), content_type="application/zip")
            response["Content-Disposition"] = "attachment; filename=dropdowns.zip"
            response['Content-Length'] = file_size
            return response
        else:
            return Response(data={'OK': 'up to date'})


class DropDownVersion(generics.ListAPIView):
    """
    A view that can accept GET requests for Jobs Version with JSON content.

    DEPRECATED: See DropDownVersionListView
    """

    parser_classes = (JSONParser,)

    def get(self, request, *args, **kwargs):
        data = get_all_versions()
        logger.info("GET: ALL Dropdowns version: %s" % data)
        return Response(data)


class DropDownJobs(generics.ListAPIView):
    """
    A view that can accept GET requests for Jobs List with JSON content.
    """

    parser_classes = (JSONParser,)

    def get(self, request, *args, **kwargs):
        data = DropDownData(DropDownData.JOB)
        logger.info("GET: JOB list endpoint, with length: %d" % data.count())
        return Response(data.get_data_dict())


class DropDownCollege(generics.ListAPIView):
    """
    A view that can accept GET requests COLLAGE with JSON content.
    """

    parser_classes = (JSONParser,)

    def get(self, request, *args, **kwargs):
        data = DropDownData(DropDownData.COLLEGE)
        logger.info("GET: college list endpoint, with length: %d" % data.count())
        return Response(data.get_data_dict())


class DropDownBank(generics.ListAPIView):
    """
    A view that can accept GET requests BANK with JSON content.
    """

    parser_classes = (JSONParser,)

    def get(self, request, *args, **kwargs):
        data = DropDownData(DropDownData.BANK)
        logger.info("GET: Bank list endpoint, with length: %d" % data.count())
        return Response(data.get_data_dict())


class DropDownMajor(generics.ListAPIView):
    """
    A view that can accept GET requests COLLEGE with JSON content.
    """

    parser_classes = (JSONParser,)

    def get(self, request, *args, **kwargs):
        data = DropDownData(DropDownData.MAJOR)
        logger.info("GET: MAJOR list endpoint, with length: %d" % data.count())
        return Response(data.get_data_dict())


class DropDownAddress(generics.ListAPIView):
    """
    A view that can accept GET requests for Indonesia Postal Code with JSON content.
    """

    parser_classes = (JSONParser,)

    def get(self, request, *args, **kwargs):
        product_line_code = int(self.kwargs['product_line_code'])
        addresses = get_addresses_dropdown_by_product_line(product_line_code)
        if addresses is None:
            return Response(
                status=HTTP_404_NOT_FOUND,
                data={"product_line_code=%s not found." % product_line_code},
            )
        return Response(addresses)


class DropDownMarketingSource(generics.ListAPIView):
    """
    A view that can accept GET requests for Marketing Source Dropdown with JSON content.
    """

    parser_classes = (JSONParser,)

    def get(self, request, *args, **kwargs):
        data = DropDownData(DropDownData.MARKETING_SOURCE)
        logger.info("GET: MARKETING_SOURCE list endpoint, with length: %d" % data.count())
        return Response(data.get_data_dict())


class DropDownLoanPurpose(generics.ListAPIView):
    """
    A view that can accept GET requests for LOAN PURPOSE Dropdown with JSON content.
    depend on product_line_id
    """

    parser_classes = (JSONParser,)

    def get(self, request, *args, **kwargs):
        product_line_code = int(self.kwargs['product_line_code'])
        loan_purposes = get_loan_purpose_dropdown_by_product_line(product_line_code)
        if loan_purposes is None:
            return Response(
                status=HTTP_404_NOT_FOUND,
                data={"product_line_code=%s not found." % product_line_code},
            )
        return Response(loan_purposes)


class DropDownCompany(generics.ListAPIView):
    """
    A view that can accept GET requests for Marketing Source Dropdown with JSON content.
    """

    parser_classes = (JSONParser,)

    def get(self, request, *args, **kwargs):
        data = DropDownData(DropDownData.COMPANY)
        logger.info("GET: COMPANY list endpoint, with length: %d" % data.count())
        return Response(data.get_data_dict())


class DropDownVersionListView(generics.ListAPIView):
    """
    A view to get the versions of all the form dropdowns
    """

    parser_classes = (JSONParser,)

    def get(self, request, *args, **kwargs):
        product_line_code = int(self.kwargs['product_line_code'])
        dropdown_versions = get_dropdown_versions_by_product_line(product_line_code)
        return Response(dropdown_versions)


class ProductLineListView(generics.ListAPIView):
    model_class = ProductLine
    serializer_class = ProductLineSerializer
    queryset = ProductLine.objects.all()

    def get_queryset(self):
        customer = self.request.user.customer
        loan = Loan.objects.filter(customer=customer).paid_off().first()
        if loan is None:
            return self.queryset.first_time_lines()
        else:
            return self.queryset.repeat_lines()


class FirstProductlineListView(ProductLineListView):
    permission_classes = (AllowAny,)

    def get_queryset(self):
        return self.queryset.first_time_lines()


class BankCredentialListCreateView(APIView):
    """
    API for creating FacebookData.
    """

    def post(self, request, *args, **kwargs):
        application_id = self.kwargs['application_id']
        bank_code = self.request.POST.get('bank_code')
        username = self.request.POST.get('username')
        password = self.request.POST.get('password')

        if application_id == '':
            # Backwards compatibility
            return Response(
                status=HTTP_404_NOT_FOUND, data={"application=%s not found." % application_id}
            )
        else:
            application = Application.objects.get_or_none(id=application_id)
            if not application:
                return Response(
                    status=HTTP_404_NOT_FOUND, data={"application=%s not found." % application_id}
                )

            if bank_code == '':
                return Response(status=HTTP_404_NOT_FOUND, data={"bank_code could not be empty."})

            if username == '':
                return Response(status=HTTP_404_NOT_FOUND, data={"username could not be empty."})

            if password == '':
                return Response(status=HTTP_404_NOT_FOUND, data={"password could not be empty."})

            bank = BankManager.get_or_none(int(bank_code))
            if not bank:
                return Response(
                    status=HTTP_404_NOT_FOUND, data={"bank_code=%s not found." % application_id}
                )

            data = {
                'application_id': application_id,
                'bank_code': bank_code,
                'bank_name': bank.bank_name,
                'username': username,
                'password': password,
            }
        return Response(status=HTTP_201_CREATED, data=data)


class PartnerReferralRetrieveView(generics.RetrieveAPIView):
    queryset = PartnerReferral.objects.all()
    # add your serializer
    serializer_class = PartnerReferralSerializer

    def get_object(self, *args, **kwargs):
        user = self.request.user
        email = user.customer.email
        referral_by_email = (
            self.queryset.filter(cust_email__iexact=email).order_by('-cdate').first()
        )
        if referral_by_email:
            return referral_by_email
        nik = user.customer.nik
        if not nik:
            return None
        referral_by_nik = self.queryset.filter(cust_nik=nik).order_by('-cdate').first()
        if referral_by_nik:
            return referral_by_nik
        else:
            return None


class CollateralListCreateView(generics.ListCreateAPIView):
    """
    This end point handles the query for collateral by application_id and
    create new collateral when submit application (application_id needs to be given).
    """

    serializer_class = CollateralSerializer

    def __init__(self, *args, **kwargs):
        super(CollateralListCreateView, self).__init__(*args, **kwargs)

    # filter by application_id, user_id, etc.)
    def get_queryset(self):
        queryset = Collateral.objects.all()
        application_id = self.request.query_params.get('application_id', None)

        if application_id is not None:
            application = Application.objects.get_or_none(pk=application_id)
            if application is not None:
                queryset = queryset.filter(application=application)
        return queryset

    # create collateral after submit application
    @parser_classes(
        (
            FormParser,
            MultiPartParser,
        )
    )
    def post(self, request, *args, **kwargs):
        application_id = self.request.data['application_id']
        collateral_type = self.request.data['collateral_type']
        collateral_name = self.request.data['collateral_name']
        collateral_year = self.request.data['collateral_year']

        if application_id is None:
            return Response(status=HTTP_404_NOT_FOUND, data={"application id could not be empty"})

        application = Application.objects.get_or_none(pk=application_id)
        if application is None:
            return Response(
                status=HTTP_404_NOT_FOUND, data={"application=%s not found." % application_id}
            )

        user = self.request.user

        if user.id != application.customer.user_id:
            return Response(
                status=HTTP_403_FORBIDDEN, data={'errors': 'User not allowed', 'user_id': user.id}
            )

        if application.partner.name not in PartnerConstant.collateral_partners():
            return Response(
                status=HTTP_404_NOT_FOUND, data={"application has no collateral partner"}
            )

        collateral = Collateral.objects.filter(application=application).last()
        if not collateral:
            collateral = Collateral.objects.create(
                application=application,
                partner=application.partner,
                collateral_type=collateral_type,
                collateral_model_name=collateral_name,
                collateral_model_year=collateral_year,
            )

            PartnerLoan.objects.create(
                application=application, partner=application.partner, approval_status='created'
            )
        send_data_to_collateral_partner_async.delay(application.id)

        return Response(status=HTTP_201_CREATED, data={'id': str(collateral.id)})


class PaymentMethodRetrieveView(APIView):
    def get(self, request, *args, **kwargs):
        loan_id = self.request.query_params.get('loan_id', None)
        user = self.request.user

        if not loan_id:
            raise ResourceNotFound(resource_id=loan_id)
        loan = Loan.objects.get_or_none(id=loan_id)
        if not loan:
            raise ResourceNotFound(resource_id=loan_id)

        if user.id != loan.customer.user_id:
            return Response(
                status=HTTP_403_FORBIDDEN, data={'errors': 'User not allowed', 'user_id': user.id}
            )

        payment_methods = PaymentMethod.objects.filter(loan=loan).order_by('id')
        if (
            loan.application.application_status_id
            >= ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
        ):
            global_payment_methods = GlobalPaymentMethod.objects.all()
        else:
            global_payment_methods = []
        # handle payment method for axiata
        if not payment_methods and loan.customer:
            payment_methods = PaymentMethod.objects.filter(customer=loan.customer).order_by('id')

        list_method_lookups = aggregate_payment_methods(
            payment_methods, global_payment_methods, loan.application.bank_name
        )

        return Response(status=HTTP_200_OK, data={'results': list_method_lookups})


class PaymentInfoRetrieveView(APIView):
    permission_classes = []
    authentication_classes = []

    def get(self, request, payment_id):
        encrypter = encrypt()
        decoded_payment_id = encrypter.decode_string(payment_id)
        payment = Payment.objects.get_or_none(pk=decoded_payment_id)
        if not payment:
            account_payment = AccountPayment.objects.get_or_none(pk=decoded_payment_id)
        # product_line_code = payment.loan.application.product_line.product_line_code
        if payment:
            loan = payment.loan
            application = payment.loan.application
            fullname = application.fullname_with_title
            payment_number = payment.payment_number
            due_amount = payment.due_amount
            due_date = date.strftime(payment.notification_due_date, '%d %B %Y')
            month_and_year_due_date = date.strftime(payment.notification_due_date, '%m/%Y')
            bank_name = payment.loan.julo_bank_name
            account_number = " ".join(splitAt(payment.loan.julo_bank_account_number, 4))
            payment_cashback_amount = (0.01 / loan.loan_duration) * loan.loan_amount
            bank_code = PaymentMethodLookup.objects.filter(name=payment.loan.julo_bank_name).first()
            payment_details = (
                loan.paymentmethod_set.filter(is_shown=True)
                .values(
                    'payment_method_code', 'payment_method_name', 'virtual_account', 'bank_code'
                )
                .order_by('-id')
            )
            maturity_date = payment.notification_due_date + timedelta(days=4)
            mature_date = date.strftime(maturity_date, '%d %B %Y')
            if bank_code and bank_code.code != BankCodes.BCA:
                code = bank_code.code
                bank_code_text = "(Kode Bank: " + code + ")"
            else:
                code = ""
                bank_code_text = ""

            payment_methods = []

            # set primary payment method in the first order
            for payment_detail in payment_details.exclude(bank_code=bank_code):
                payment_methods.append(payment_detail)

            primary_pmt_method = payment_details.filter(bank_code=bank_code).last()
            payment_methods.append(primary_pmt_method)
            cashback_counter = loan.account.cashback_counter_for_customer
            is_account_cashback_experiment = get_cashback_experiment(loan.account.id)
            short_due_date = (payment.notification_due_date - timedelta(days=2)).strftime(
                '%d/%m/%Y'
            )
        elif account_payment:
            account = account_payment.account
            oldest_unpaid_account_payment = account.get_oldest_unpaid_account_payment()
            customer = account.customer
            fullname = customer.fullname

            if oldest_unpaid_account_payment:
                account_payment = oldest_unpaid_account_payment

            due_amount = account_payment.due_amount

            if account_payment.dpd > 0:
                due_amount = 0
                unpaid_account_payments = account.accountpayment_set.not_paid_active()
                for each in unpaid_account_payments:
                    due_amount += each.due_amount

            account_payment_due_date = account_payment.due_date

            due_date = date.strftime(account_payment_due_date, '%d %B %Y')
            month_and_year_due_date = date.strftime(account_payment_due_date, '%m/%Y')

            active_loans = account.loan_set.filter(
                loan_status__gte=LoanStatusCodes.CURRENT, loan_status__lt=LoanStatusCodes.PAID_OFF
            )
            payment_cashback_amount = 0
            for loan in active_loans:
                payment_cashback_amount += (0.01 / loan.loan_duration) * loan.loan_amount

            payment_methods = []
            payment_method_qs = customer.paymentmethod_set.filter(is_shown=True)
            payment_method_qs = filter_payment_methods_by_lender(payment_method_qs, customer)
            payment_details = payment_method_qs.values(
                'payment_method_code', 'payment_method_name', 'virtual_account', 'bank_code'
            ).order_by('-id')
            for payment_detail in payment_details:
                payment_methods.append(payment_detail)

            oldest_unpaid_payment = (
                account_payment.payment_set.not_paid_active().order_by('payment_number').first()
            )
            oldest_payment = account_payment.payment_set.order_by('payment_number').last()

            if oldest_unpaid_payment:
                cashback_multiplier = oldest_unpaid_payment.cashback_multiplier
            else:
                cashback_multiplier = oldest_payment.cashback_multiplier

            cashback_counter = account.cashback_counter_for_customer
            is_account_cashback_experiment = get_cashback_experiment(account.id)
            short_due_date = (account_payment_due_date - timedelta(days=2)).strftime('%d/%m/%Y')
        else:
            return Response(status=HTTP_404_NOT_FOUND, data="resource not found")

        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.IN_APP_PTP_SETTING, is_active=True
        ).last()

        gender_title = {'Pria': 'Bapak', 'Wanita': 'Ibu'}
        data = {
            "customer": {
                'fullname': mask_fullname_each_word(fullname),
                'title_long': None if payment else gender_title.get(customer.gender, 'Bapak/Ibu'),
            },
            "payment": {
                'payment_number': payment_number if payment else None,
                'due_amount': display_rupiah(due_amount),
                'due_date': due_date,
                'month_and_year_due_date': month_and_year_due_date,
                'maturity_date': mature_date if payment else None,
                'payment_cashback_amount': display_rupiah(int(payment_cashback_amount)),
                'payment_details': payment_methods,
                'is_cashback_streak_user': is_account_cashback_experiment,
                'cashback_streak_counter': cashback_counter,
                'short_due_date': short_due_date,
            },
            "settings": {
                "in_app_ptp": True if feature_setting else False,
            },
            "bank": {
                'bank_name': bank_name if payment else None,
                'account_number': account_number if payment else None,
                'cashback_multiplier': payment.cashback_multiplier
                if payment
                else cashback_multiplier,
                'bank_code': code if payment else None,
                'bank_code_text': bank_code_text if payment else None,
            },
            "product": {'type': application.product_line.product_line_type if payment else 'J1'},
        }

        return Response(data=data)
