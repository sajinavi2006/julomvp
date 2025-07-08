from __future__ import absolute_import
from builtins import str
from builtins import range
import logging
import random
import string
import csv

from datetime import date
from datetime import timedelta  # noqa

from django.db import transaction
from django.db.utils import IntegrityError
from django.core.exceptions import ObjectDoesNotExist
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.contrib.auth.models import User

from juloserver.api_token.authentication import ExpiryTokenAuthentication
from rest_framework import exceptions
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework import generics
from rest_framework.decorators import parser_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.status import HTTP_200_OK
from rest_framework.status import HTTP_201_CREATED
from rest_framework.status import HTTP_404_NOT_FOUND
from rest_framework.status import HTTP_406_NOT_ACCEPTABLE
from rest_framework.status import HTTP_400_BAD_REQUEST
from rest_framework.status import HTTP_403_FORBIDDEN
from rest_framework.status import HTTP_500_INTERNAL_SERVER_ERROR
from juloserver.julo.product_lines import ProductLineCodes
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework import serializers

from pyexcel_xls import get_data

from ..julo.models import AddressGeolocation
from ..julo.models import Application
from ..julo.models import ApplicationScrapeAction
from ..julo.models import Customer
from ..julo.models import CustomerAppAction
from ..julo.models import Device
from ..julo.models import Loan
from ..julo.models import LoanPurpose
from ..julo.models import Image
from ..julo.models import PartnerPurchaseItem
from ..julo.models import PartnerReferral
from ..julo.models import Payment
from ..julo.models import ProductLine
from ..julo.models import Offer
from ..julo.models import Workflow
from juloserver.julo.partners import PartnerConstant
from ..julo.models import Partner

from ..apiv1.exceptions import ResourceNotFound
from rest_framework.exceptions import APIException

from .serializers import RegisterSerializer
from .serializers import CustomerSerializer
from .serializers import LoanSerializer
from .serializers import ApplicationSerializer
from .serializers import ApplicationStatusSerializer
from .serializers import ApplicationPartnerUpdateSerializer
from .serializers import CreditScoreSerializer
from .serializers import ImageSerializer
from .serializers import PaymentMethodSerializer
from .serializers import OfferSerializer
from .serializers import PartnerPurchaseItemSerializer
from .serializers import AcceptActivationSerializer
from .serializers import SdkLogSerializer

from .constants import LIST_PARTNER, EXPIRED_STATUS
from .constants import CreditMatrixPartner

from ..apiv1.filters import LoanFilter

from ..julo.services import process_application_status_change
from ..julo.services2.payment_method import get_payment_methods

from ..julo.statuses import ApplicationStatusCodes
from ..julo.tasks import create_application_checklist_async, upload_image
from ..julo.utils import redirect_post_to_anaserver

from ..apiv2.tasks import generate_address_from_geolocation_async

from ..sdk.services import get_credit_score_partner
from ..sdk.services import get_laku6_sphp, get_partner_product_sphp
from ..sdk.services import get_partner_productline
from ..sdk.services import get_partner_offer
from ..sdk.services import get_pede_product_lines
from ..sdk.tasks import send_retry_callback
from ..apiv1.data.addresses import get_full_addresses_dropdown_data
from ..apiv1.data import DropDownData
from juloserver.apiv1.serializers import ProductLineSerializer
from juloserver.julo.services import get_partner_application_status_exp_date
from juloserver.julo.product_lines import ProductLineManager
from django.http import HttpResponseNotAllowed
from .models import SdkLog
from ..julo.models import PartnerSignatureMode
from juloserver.sdk.services import register_digisign_pede
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.julo.services2.digisign import is_digisign_feature_active
from juloserver.julo.services import update_customer_data
from django.shortcuts import render
from django.conf import settings
import pyexcel_xls  # noqa

# Create your views here.
logger = logging.getLogger(__name__)


class ClientAuthentication(ExpiryTokenAuthentication):
    def authenticate(self, request):
        authentic = super(ClientAuthentication, self).authenticate(request)
        partner_list = LIST_PARTNER
        if authentic is None:
            raise exceptions.AuthenticationFailed('Authentication credentials were not provided.')
        try:
            user, auth = authentic
            partner = user.partner
        except ObjectDoesNotExist:
            raise exceptions.AuthenticationFailed('Forbidden request, user is not partner julo')

        if partner.name not in partner_list:
            raise exceptions.AuthenticationFailed('Forbidden request')

        return (user, auth)


class PartnerScrapedDataViewSet(APIView):
    """
        This end point handles the query for device scraped data
        upload new data file.
        """
    permission_classes = []
    authentication_classes = (ClientAuthentication,)

    # upload file providing file path and the application_id
    def post(self, request):
        application = Application.objects.get_or_none(application_xid=request.data['application_xid'])
        if application:
            request.data['application_id'] = application.id

        if 'application_id' not in request.data:
            return Response(status=HTTP_400_BAD_REQUEST,
                            data={'application_id': "This field is required"})
        if 'upload' not in request.data:
            return Response(status=HTTP_400_BAD_REQUEST,
                            data={'upload': "This field is required"})
        if not isinstance(request.data['upload'], InMemoryUploadedFile):
            return Response(status=HTTP_400_BAD_REQUEST,
                            data={'upload': "This field must contain file"})

        application_id = int(request.data['application_id'])
        customer = application.customer
        # override request for include data customer to DeviceIpMiddleware
        request.user.customer = customer

        user_applications = customer.application_set.values_list('id', flat=True)
        if application_id not in user_applications:
            return Response(status=HTTP_404_NOT_FOUND,
                            data={'not_found': application_id})

        incomplete_rescrape_action = CustomerAppAction.objects.get_or_none(
            customer=customer, action='rescrape', is_completed=False)
        if incomplete_rescrape_action:
            incomplete_rescrape_action.mark_as_completed()
            incomplete_rescrape_action.save()

        url = request.build_absolute_uri()
        application = customer.application_set.get(pk=application_id)
        ApplicationScrapeAction.objects.create(
            application_id=application.id, url=url, scrape_type='dsd'
        )

        data = {'application_id': application_id,
                'customer_id': customer.id}
        files = {'upload': request.data['upload']}
        ret = redirect_post_to_anaserver(
            '/api/amp/v1/device-scraped-data/', data=data, files=files)

        dummy_ret = {
            "status": 'initiated',
            "application_xid": application.application_xid,
            "data_type": 'dsd',
            "customer_nik": customer.nik,
        }

        return Response(status=ret.status_code, data=dummy_ret)


class PartnerRegisterUser(StandardizedExceptionHandlerMixin, APIView):
    """
        End point for registration combined from several old end point
            -DeviceListCreateView
            -AddressGeolocationListCreateView
            -PartnerReferralRetrieveView
            -RegisterUser
        """
    permission_classes = []
    authentication_classes = (ClientAuthentication, )
    serializer_class = RegisterSerializer

    def post(self, request):
        """
        Handles user registration
        """

        request_data = self.serializer_class(data=request.data)
        request_data.is_valid(raise_exception=True)
        partner = request.user.partner

        email = None
        appsflyer_device_id = None
        advertising_id = None

        if 'email' in request_data.data:
            email = request_data.data['email'].lower()

        if 'appsflyer_device_id' in request_data.data:
            appsflyer_device_id_exist = Customer.objects.filter(
                appsflyer_device_id=request_data.data['appsflyer_device_id']
            ).last()
            if not appsflyer_device_id_exist:
                appsflyer_device_id = request_data.data['appsflyer_device_id']
                if 'advertising_id' in request_data.data:
                    advertising_id = request_data.data['advertising_id']

        # Set auth user with blank password
        nik = request_data.data['ktp']
        customer = Customer.objects.get_or_none(nik=nik)
        app_number = 1
        if customer:
            last_application = customer.application_set.last()
            if last_application and last_application.is_active():
                last_loan = Loan.objects.filter(application_id=last_application.id).last()
                if last_loan and last_loan.is_active:
                    if partner.name != last_application.partner_name:
                        return Response(status=HTTP_403_FORBIDDEN,
                                        data={'errors': ["NIK has active loan"]})
                    else:
                        response_data = {
                            "customer": CustomerSerializer(customer).data,
                            "applications": [ApplicationSerializer(last_application).data]
                        }
                        # override request for include data customer to DeviceIpMiddleware
                        request.user.customer = customer

                        return Response(status=HTTP_200_OK, data=response_data)
                else:
                    if last_application.status == ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL:
                        pass
                    elif partner.name != last_application.partner_name:
                        return Response(status=HTTP_403_FORBIDDEN,
                                        data={'errors': ["NIK has application on going"]})
                    else:
                        response_data = {
                            "customer": CustomerSerializer(customer).data,
                            "applications": [ApplicationSerializer(last_application).data]
                        }
                        # override request for include data customer to DeviceIpMiddleware
                        request.user.customer = customer

                        return Response(status=HTTP_200_OK, data=response_data)
            else:
                if not customer.can_reapply:
                    response_data = {
                        "customer": CustomerSerializer(customer).data,
                        "applications": [ApplicationSerializer(last_application).data]
                    }
                    # override request for include data customer to DeviceIpMiddleware
                    request.user.customer = customer

                    return Response(status=HTTP_200_OK, data=response_data)

            if last_application:
                last_application_number = last_application.application_number if last_application.application_number \
                    else customer.application_set.all().count()
                app_number = last_application_number + 1
        else:
            try:
                user = User.objects.get(username=nik)
            except ObjectDoesNotExist:
                user = User(username=nik)
                password = ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(8))
                user.set_password(password)
                user.save()

            customer = Customer.objects.create(user=user, email=email, nik=nik,
                                               appsflyer_device_id=appsflyer_device_id, advertising_id=advertising_id)

        try:
            with transaction.atomic():
                app_version = request_data.data['app_version']
                workflow = Workflow.objects.get_or_none(name='SubmittingFormWorkflow')
                application = Application.objects.create(customer=customer, ktp=nik, app_version=app_version,
                                                         email=email, application_number=app_number,workflow=workflow)
                update_customer_data(application)

                application.partner = partner
                # create Device
                device = Device.objects.create(customer=customer, gcm_reg_id=request.data['gcm_reg_id'],
                                               android_id=request.data['android_id'], imei=request.data['imei'])
                application.device = device
                application.save()

                # create partner_referral
                partner_referral = PartnerReferral(cust_nik=nik)
                partner_referral.partner = partner
                partner_referral.customer = customer
                logger.info({
                    'action': 'create_link_partner_referral_to_customer',
                    'customer_id': customer.id,
                    'partner_id': partner_referral.partner,
                    'nik': nik
                })
                partner_referral.save()

                process_application_status_change(application.id, ApplicationStatusCodes.FORM_CREATED,
                                                  change_reason='customer_triggered')

                # create AddressGeolocation
                address_geolocation = AddressGeolocation.objects.create(
                    application=application,
                    latitude=request.data['latitude'],
                    longitude=request.data['longitude'])

                generate_address_from_geolocation_async.delay(address_geolocation.id)

                application.refresh_from_db()
                response_data = {
                    "customer": CustomerSerializer(customer).data,
                    "applications": [ApplicationSerializer(application).data]
                }

                # override request for include data customer to DeviceIpMiddleware
                request.user.customer = customer

            create_application_checklist_async.delay(application.id)
            return Response(status=HTTP_201_CREATED, data=response_data)
        except IntegrityError:
            return Response(status=HTTP_500_INTERNAL_SERVER_ERROR,
                            data={'errors': ["Server Error"]})
            raise IntegrityError


class PartnerLoanRetrieveUpdateView(RetrieveUpdateAPIView):
    """
        API endpoint that allows a current user's loan to be retrieved.
        """
    model_class = Loan
    serializer_class = LoanSerializer
    authentication_classes = (ClientAuthentication,)
    permission_classes = []
    lookup_field = 'application_xid'

    def get_queryset(self):
        return self.__class__.model_class.objects.filter(application_xid=self.kwargs['application_xid'])

    def perform_update(self, serializer):
        application_xid = self.kwargs['application_xid']
        application = Application.objects.get_or_none(application_xid=application_xid)

        if application is None:
            raise ResourceNotFound(resource_id=self.kwargs['application_xid'])

        # override request for include data customer to DeviceIpMiddleware
        self.request.user.customer = application.customer

        loan = Loan.objects.get_or_none(application=application)
        if loan is None:
            raise ResourceNotFound(resource_id=loan.id)

        loan = serializer.save()

        if 'cycle_day_requested' in serializer.validated_data:
            loan.cycle_day_requested_date = date.today()
            loan.save()


class PartnerLoanListView(APIView):
    """
       API endpoint that allows current user's loans to be listed.
       """
    model_class = Loan
    serializer_class = LoanSerializer
    filter_class = LoanFilter
    authentication_classes = (ClientAuthentication,)
    permission_classes = []
    lookup_url_kwarg = 'nik'
    lookup_field = 'application_xid'

    def get_queryset(self):
        nik = self.kwargs['nik']
        customer = Customer.objects.get_or_none(nik=nik)
        # override request for include data customer to DeviceIpMiddleware
        self.request.user.customer = customer

        return self.__class__.model_class.objects.filter(customer=customer)


class PartnerApplicationView(generics.RetrieveUpdateAPIView):

    model_class = Application
    authentication_classes = (ClientAuthentication,)
    serializer_class = ApplicationPartnerUpdateSerializer
    permission_classes = []
    lookup_field = 'application_xid'

    def get_queryset(self):
        application = self.__class__.model_class.objects.filter(application_xid=self.kwargs['application_xid'])

        return application

    def perform_update(self, serializer):
        email = self.request.data.get('email', None)
        gpa = self.request.data.get('gpa', None)
        bank_name = self.request.data.get('bank_name',None)
        bank_account_number = self.request.data.get('bank_account_number',None)
        name_in_bank = self.request.data.get('name_in_bank',None)


        if not email:
            raise serializers.ValidationError({'errors': ['Email is required!']})
        else:
            email = email.lower()

        if not bank_name:
            raise serializers.ValidationError({'error': ['Bank Name is required!']})

        if not bank_account_number:
            raise serializers.ValidationError({'error': ['Bank Account Number is required!']})

        if not name_in_bank:
            raise serializers.ValidationError({'error': ['Name in Bank is required!']})

        if gpa and (float(gpa) < 0 or float(gpa) > 4):
            raise serializers.ValidationError({'errors': ['Enter valid gpa']})

        application = Application.objects.get_or_none(application_xid=self.kwargs['application_xid'])
        customer = Customer.objects.get_or_none(email__iexact=email)

        if application is None:
            raise serializers.ValidationError(
                {'errors': ['Application with application_xid %s not found' % self.kwargs['application_xid']]})

        if customer:
            if not application.customer.email == customer.email:
                raise serializers.ValidationError({'errors': ['please use your registered email!!']})

        # override request for include data customer to DeviceIpMiddleware
        self.request.user.customer = application.customer

        try:
            with transaction.atomic():
                application = serializer.save()
                incoming_status = application.status

                workflow = Workflow.objects.get(name='PartnerWorkflow')
                application.workflow = workflow
                application.save()
                # update data customer
                customer = application.customer
                customer.fullname = application.fullname
                customer.email = application.email
                customer.phone = application.mobile_phone_1
                customer.save()

                if incoming_status == ApplicationStatusCodes.FORM_CREATED:    # 100
                    process_application_status_change(application.id, ApplicationStatusCodes.FORM_PARTIAL,
                                                      change_reason='customer_triggered_form_partnerAPI')

        except IntegrityError:
            raise APIException("Server Error")


class ActivationView(APIView):

    authentication_classes = (ClientAuthentication,)
    permission_classes = []

    def get(self, request, application_xid):
        application = Application.objects.get_or_none(application_xid=application_xid)

        if application is None:
            raise ResourceNotFound(resource_id=application_xid)

        if application.status < ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL:
            return Response(status=HTTP_403_FORBIDDEN,
                            data={'errors': ["you must validate your credit limit first"]})

        if application.status in EXPIRED_STATUS:
            return Response(status=HTTP_406_NOT_ACCEPTABLE,
                            data={'errors': ["your application expired"]})

        # override request for include data customer to DeviceIpMiddleware
        self.request.user.customer = application.customer

        offer = Offer.objects.filter(application=application).first()

        if not offer:
            return Response(status=HTTP_403_FORBIDDEN,
                            data={'errors': ["you must validate your credit limit first"]})

        offer.is_accepted = True
        offer.save()

        agreement, url, status, reason, digisign = None, None, None, None, None
        try:
            if application.partner_name == PartnerConstant.PEDE_PARTNER:
                agreement = get_partner_product_sphp(application.id, application.customer)

                digisign = PartnerSignatureMode.objects.filter(
                    partner__name=PartnerConstant.PEDE_PARTNER, is_active=True)
                feature_setting = is_digisign_feature_active(application)
                if digisign and feature_setting:
                    # function to call the digisign
                    url, status, reason = register_digisign_pede(application)
            else:
                agreement = get_laku6_sphp(application.id, application.customer)
        except Exception as e:
            logger.error('Error partner SPHP: {}'.format(e))
        expire_date = get_partner_application_status_exp_date(application)

        if not url and digisign:
            expire_date = None

        return Response(data={
            "sphp": agreement,
            "url": url,
            "expiration_date": expire_date,
            "status": status,
            "reason": reason})


class AcceptActivationView(APIView):

    authentication_classes = (ClientAuthentication,)
    serializer_class = AcceptActivationSerializer
    permission_classes = []

    def post(self, request, application_xid):
        application = Application.objects.get_or_none(application_xid=application_xid)

        if application is None:
            raise ResourceNotFound(resource_id=application_xid)

        if application.status < ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL:
            return Response(status=HTTP_403_FORBIDDEN,
                            data={'errors': ["sphp has not created"]})

        if application.status in EXPIRED_STATUS:
            return Response(status=HTTP_406_NOT_ACCEPTABLE,
                            data={'errors': ["your application expired"]})

        if application.status >= ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED:
            return Response(data={"is_sphp_signed": application.is_sphp_signed})

        # override request for include data customer to DeviceIpMiddleware
        request.user.customer = application.customer

        try:
            with transaction.atomic():

                request_data = self.serializer_class(data=request.data)
                request_data.is_valid(raise_exception=True)
                is_accepted = request_data.data['is_sphp_signed']

                application.is_sphp_signed = is_accepted
                application.save()

                if application.status == ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL:
                    if is_accepted:
                        process_application_status_change(application.id,
                                                          ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED,
                                                          change_reason='customer_triggered_form_partnerAPI')
                    else:
                        process_application_status_change(application.id,
                                                          ApplicationStatusCodes.APPLICATION_DENIED,
                                                          change_reason='customer_triggered_form_partnerAPI')

        except Exception as e:
            logger.info({
                "action": "AcceptActivationView",
                "error": e
            })
            return Response(status=HTTP_500_INTERNAL_SERVER_ERROR,
                            data={'errors': ["ups! something went wrong Please try again."]})

        return Response(data={"is_sphp_signed": application.is_sphp_signed})


class CreditScoreView(APIView):

    authentication_classes = (ClientAuthentication,)
    permission_classes = []

    def get(self, request, application_xid):
        # partner data
        partner = request.user.partner

        application = Application.objects.get_or_none(application_xid=application_xid)
        if application is None:
            raise ResourceNotFound(resource_id=application_xid)

        if application.status < ApplicationStatusCodes.DOCUMENTS_VERIFIED:
            return Response(status=HTTP_403_FORBIDDEN,
                            data={'errors': ["your application not verify yet"]})

        if application.status in EXPIRED_STATUS:
            return Response(status=HTTP_406_NOT_ACCEPTABLE,
                            data={'errors': ["your application expired"]})

        if application.status < ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER:
            return Response(status=HTTP_403_FORBIDDEN,
                            data={'errors': ["your application form submission not completed"]})

        # override request for include data customer to DeviceIpMiddleware
        request.user.customer = application.customer

        credit_score = get_credit_score_partner(application.id)
        response = dict()
        if credit_score:
            if partner.name == PartnerConstant.PEDE_PARTNER:
                if not application.product_line:
                    if application.loan_duration_request > 1:
                        product_codes = ProductLineCodes.pedemtl()
                    else:
                        product_codes = ProductLineCodes.pedestl()
                else:
                    product_codes = [application.product_line.product_line_code]

                product_lines = get_pede_product_lines(
                        request.user.customer, application.id, line_ids=product_codes)

                response['product_lines'] = ProductLineSerializer(product_lines, many=True).data
                if product_lines:
                    response['message'] = "Products generated for application"
                else:
                    response['message'] = "No product available for your application"

                rate = 0
                product_line_obj = product_lines.first()
                if product_line_obj:
                    if product_line_obj.product_line_code in ProductLineCodes.pedemtl():
                        rate = CreditMatrixPartner.PEDE_INTEREST_BY_SCORE[credit_score.score]
                    else:
                        product_line = ProductLineManager.get_or_none(product_line_obj.product_line_code)
                        rate = product_line.max_interest_rate
                interest_rate = "{}%".format(float(rate) * 100)

                response['score'] = CreditScoreSerializer(credit_score).data
                response['score'].pop('credit_limit')
                response['score']['interest_rate'] = interest_rate
            else:
                rate = CreditMatrixPartner.INTEREST_BY_SCORE[credit_score.score]
                interest_rate = "{}%".format(float(rate) * 100)

                response['score'] = CreditScoreSerializer(credit_score).data
                response['score']['interest_rate'] = interest_rate

            response['expiration_date'] = get_partner_application_status_exp_date(application)

            return Response(response)
        else:
            data = {'message': 'Unable to calculate score'}
            return Response(status=HTTP_500_INTERNAL_SERVER_ERROR, data=data)


class ValidateView(APIView):

    authentication_classes = (ClientAuthentication,)
    permission_classes = []
    serializer_class = PartnerPurchaseItemSerializer

    def post(self, request, application_xid):
        partner = request.user.partner
        request.data['partner'] = partner.id
        request.data['application_xid'] = application_xid
        loan_amount_request = request.data.get('device_price', None)
        package_name = request.data.get('package_name', None)
        product_code = None

        loan_duration_request = request.data.get('loan_duration_request', 12)

        application = Application.objects.get_or_none(application_xid=application_xid)

        if application is None:
            raise ResourceNotFound(resource_id=application_xid)

        if partner.name in [PartnerConstant.PEDE_PARTNER]:
            loan_amount_request = application.loan_amount_request
            loan_duration_request = application.loan_duration_request
            product_code = request.data.get('product_code', None)

            if not loan_amount_request:
                return Response(status=HTTP_403_FORBIDDEN,
                            data={'errors': ["Update loan_amount_request in Application"]})

            if not loan_duration_request:
                return Response(status=HTTP_403_FORBIDDEN,
                            data={'errors': ["Update loan_duration_request in Application"]})

            if not product_code:
                return Response(status=HTTP_400_BAD_REQUEST,
                            data={'errors': ["Provide a valid product_code"]})

        if application.status < ApplicationStatusCodes.DOCUMENTS_VERIFIED:
            return Response(status=HTTP_403_FORBIDDEN,
                            data={'errors': ["your application not verify yet"]})

        if application.status == ApplicationStatusCodes.CALL_ASSESSMENT:
            return Response(status=HTTP_403_FORBIDDEN,
                            data={'errors': ["ktp invalid"]})

        if application.status == ApplicationStatusCodes.APPLICATION_DENIED:
            return Response(status=HTTP_403_FORBIDDEN,
                            data={'errors': ["Application Denied"]})

        if application.is_sphp_signed:
            return Response(status=HTTP_403_FORBIDDEN,
                            data={'errors': ["the status is not correct to hit the API"]})

        product_line = get_partner_productline(application, application.partner, product_code=product_code).first()
        credit_score = get_credit_score_partner(application.id)

        if not product_line:
            return Response(status=HTTP_400_BAD_REQUEST,
                            data={'errors': ["product line can't be empty"]})

        if int(loan_amount_request) > int(credit_score.credit_limit) and partner.name == PartnerConstant.LAKU6_PARTNER:
            return Response(status=HTTP_403_FORBIDDEN,
                            data={'errors': ["you reach your credit limit"]})

        if application.status in EXPIRED_STATUS:
            return Response(status=HTTP_406_NOT_ACCEPTABLE,
                            data={'errors': ["your application expired"]})

        try:
            with transaction.atomic():
                # override request for include data customer to DeviceIpMiddleware
                request.user.customer = application.customer

                if partner.name == PartnerConstant.LAKU6_PARTNER:
                    application.loan_amount_request = loan_amount_request
                    application.loan_duration_request = loan_duration_request
                    application.product_line = product_line
                    application.save()

                    offer_data = get_partner_offer(application, package_name)
                    if not offer_data:
                        return Response(status=HTTP_403_FORBIDDEN,
                                        data={'errors': ["No offer available for your application"]})

                    offer = Offer.objects.filter(application=application)
                    if not offer.first():
                        offer = Offer.objects.create(**offer_data)
                    else:
                        offer = offer.first()
                        offer.update_safely(**offer_data)

                    # store data partner item to
                    partner_purchase = PartnerPurchaseItem.objects.filter(partner=partner,
                                                                          application_xid=application_xid).first()

                    purchase_data = self.serializer_class(partner_purchase, data=request.data)
                    purchase_data.is_valid(raise_exception=True)
                    purchase_data.save()

                elif partner.name == PartnerConstant.PEDE_PARTNER:
                    offer = Offer.objects.filter(application=application).first()

                if application.status == ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER:
                    process_application_status_change(application.id, ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
                                                      change_reason='customer_triggered_form_partnerAPI')

                return Response(status=HTTP_201_CREATED, data=OfferSerializer(offer).data)
        except Exception as e:
            logger.info({
                "action": "AcceptActivationView",
                "error": e
            })
            return Response(status=HTTP_500_INTERNAL_SERVER_ERROR,
                            data={'errors': ["ups! something went wrong Please try again."]})


class ImageListCreateView(generics.ListCreateAPIView):
    """
    This end point handles the query for images by image_source and
    upload new image (image_source needs to be given).
    """
    authentication_classes = (ClientAuthentication,)
    permission_classes = []
    serializer_class = ImageSerializer
    lookup_url_kwarg = 'application_xid'

    def __init__(self, *args, **kwargs):
        super(ImageListCreateView, self).__init__(*args, **kwargs)

    # filter by image_source application_id, user_id, etc.)
    def get_queryset(self):
        queryset = Image.objects.all()
        # image_source = self.request.query_params.get('image_source', None)
        application = Application.objects.get_or_none(application_xid=self.kwargs['application_xid'])
        image_source = application.id
        if image_source is not None:
            queryset = queryset.filter(image_source=image_source)
        return queryset

    # upload image providing image binary and the image_source
    @parser_classes((FormParser, MultiPartParser,))
    def post(self, request, *args, **kwargs):
        application = Application.objects.get_or_none(application_xid=self.kwargs['application_xid'])

        if application is None:
            raise ResourceNotFound(resource_id=self.kwargs['application_xid'])

        if 'upload' not in request.data:
            return Response(status=HTTP_400_BAD_REQUEST)

        # override request for include data customer to DeviceIpMiddleware
        self.request.user.customer = application.customer

        image = Image()
        image_type = request.data['image_type']
        image_source = application.id
        if image_type is not None:
            image.image_type = image_type
            if request.user.partner.name == PartnerConstant.PEDE_PARTNER:
                if image_type.lower() == 'selfie':
                    image.image_type = 'crop_selfie'
                elif image_type.lower() == 'ktp':
                    image.image_type = 'ktp_self'
        if image_source is None:
            return Response(status=HTTP_400_BAD_REQUEST, data='Invalid image_source')

        image.image_source = int(image_source)
        customer = application.customer
        if 2000000000 < int(image.image_source) < 2999999999:
            if not customer.application_set.filter(id=image_source).exists():
                return Response(status=HTTP_404_NOT_FOUND,
                                data="Application id=%s not found" % image.image_source)
        elif 3000000000 < int(image.image_source) < 3999999999:
            if not customer.application_set.filter(loan=3000000001).exists():
                return Response(status=HTTP_404_NOT_FOUND,
                                data="Loan id=%s not found" % image.image_source)
        image.save()
        upload = request.data['upload']
        image.image.save(image.full_image_name(upload.name), upload)

        upload_image.apply_async((image.id,), countdown=3)
        if application.status == ApplicationStatusCodes.FORM_PARTIAL:  # 105
            process_application_status_change(application.id, ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
                                              change_reason='customer_triggered_form_partnerAPI')

        if application.partner_name == PartnerConstant.LAKU6_PARTNER:
            send_retry_callback.apply_async((application.id, ), countdown=600)

        return Response(status=HTTP_201_CREATED, data={'id': str(image.id)})


class PartnerLoanPaymentView(APIView):

    authentication_classes = (ClientAuthentication,)
    permission_classes = []

    def get(self, request, application_xid):
        application = Application.objects.get_or_none(application_xid=application_xid)

        if application is None:
            raise ResourceNotFound(resource_id=self.kwargs['application_xid'])
        try:
            loan = application.loan
            payments = list(Payment.objects.by_loan(loan))
            payment_method = get_payment_methods(loan)
            list_payment = []

            for payment in payments:
                list_payment.append({
                    'payment_number': payment.payment_number,
                    'payment_amount': payment.due_amount,
                    'payment_due': payment.due_date,
                    'payment_status': payment.payment_status.status,
                    'payment_status_code': payment.payment_status.status_code,
                    'paymet_paid_amount': payment.paid_amount,
                    'payment_paid_date': payment.paid_date
                })

            data = {
                'loan': LoanSerializer(loan).data,
                'payment': list_payment,
                'payment_method': PaymentMethodSerializer(payment_method, many=True).data,
                'how_to_pay': "https://www.julo.co.id/cara-membayar.html"
            }

            return Response(status=HTTP_200_OK, data=data)
        except ObjectDoesNotExist:
            return Response(status=HTTP_404_NOT_FOUND, data="Loan not found")


class DropDownApi(APIView):

    def get(self, request):
        from .data.addresses import INDONESIA_AD
        data = {
            "addresses": INDONESIA_AD,
            "banks": DropDownData(DropDownData.BANK)._select_data(),
            "college": DropDownData(DropDownData.COLLEGE)._select_data(),
            "companies": DropDownData(DropDownData.COMPANY)._select_data(),
            "job": DropDownData(DropDownData.JOB)._select_data(),
            "majors": DropDownData(DropDownData.MAJOR)._select_data(),
            "marketing_sources": DropDownData(DropDownData.MARKETING_SOURCE)._select_data(),
            "loan_purposes": LoanPurpose.objects.all().values_list('purpose', flat=True),
            "dialects": [x[0] for x in Application().DIALECT_CHOICES],
            "home_statuses": [x[0] for x in Application().HOME_STATUS_CHOICES],
            "job_types": [x[0] for x in Application().JOB_TYPE_CHOICES],
            "kin_relationships": [x[0] for x in Application().KIN_RELATIONSHIP_CHOICES],
            "last_educations": [x[0] for x in Application().LAST_EDUCATION_CHOICES],
            "marital_statuses": [x[0] for x in Application().MARITAL_STATUS_CHOICES],
            "vehicle_types": [x[0] for x in Application().VEHICLE_TYPE_CHOICES],
            "vehicle_ownerships": [x[0] for x in Application().VEHICLE_OWNERSHIP_CHOICES],
        }
        return Response(data=data)


class SendInvociesView(APIView):

    authentication_classes = (ClientAuthentication,)
    permission_classes = []
    serializer_class = PartnerPurchaseItemSerializer

    def post(self, request, application_xid):
        application = Application.objects.get_or_none(application_xid=application_xid)
        partner = request.user.partner
        request.data['partner'] = partner.id
        request.data['application_xid'] = application_xid

        if application is None:
            raise ResourceNotFound(resource_id=application_xid)

        # store data partner item to
        partner_purchase = PartnerPurchaseItem.objects.filter(partner=partner,
                                                              application_xid=application_xid).first()

        purchase_data = self.serializer_class(partner_purchase, data=request.data)
        purchase_data.is_valid(raise_exception=True)
        purchase_data.save()

        return Response(status=HTTP_201_CREATED, data=purchase_data.data)


class PartnerApplicationStatusView(APIView):
    authentication_classes = (ClientAuthentication,)
    permission_classes = []

    def get(self, request, application_xid, format=None):
        application = Application.objects.filter(application_xid=application_xid).last()
        if application is None:
            raise ResourceNotFound(resource_id=application_xid)

        data = ApplicationStatusSerializer(application).data
        return Response(status=HTTP_200_OK, data=data)


class SDKLogApi(APIView):
    def post(self, request):
        if request.method != 'POST':
            logger.info({
                'action': 'sdk_log_api_post',
                'message': 'failed upload log to db',
                'reason': 'wrong method request type'
            })

            return HttpResponseNotAllowed(["POST"])

        if 'sdk_log' in request.FILES and 'csv' in request.FILES['sdk_log'].name:
            paramFile = request.FILES['sdk_log']

            csv_reader = csv.DictReader(paramFile.read().decode().splitlines())

            sdk_log = []

            for row in csv_reader :
                serializer = SdkLogSerializer(data=row)

                if serializer.is_valid():
                    sdk_log.append(SdkLog(**serializer.data))
                else:
                    continue

            SdkLog.objects.bulk_create(sdk_log)

            logger.info({
                'action': 'sdk_log_api_post',
                'status': 'success upload log to db'
            })

            return Response(status=HTTP_201_CREATED,
                            data=({'Status': 'log saved to db'}))
        else:
            logger.info({
                'action': 'sdk_log_api_post',
                'status': 'failed upload log to db',
                'reason': 'file is not csv format'
            })

            return Response(status=HTTP_400_BAD_REQUEST,
                            data=({'Bad Request': 'File format is not csv'}))


class DigisignPedeWebView(APIView):

    authentication_classes = []
    permission_classes = []

    def get(self, request, application_xid):
        # call back api digisign pede
        application = Application.objects.get_or_none(
            application_xid=application_xid
        )
        if not application:
            return render(request, 'sdk/application_not_found.html')

        data = {
            "user_token": application.customer.user.auth_expiry_token.key,
            "application_id": application.id,
            "base_url": settings.BASE_URL + "/"
        }

        return render(request, 'digisign/digisign_pede.html', data)
