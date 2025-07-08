from __future__ import absolute_import

import json
from builtins import str
import logging
from typing import Any
import uuid
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.shortcuts import render
from django.shortcuts import redirect
from django.utils import timezone
from django.template import RequestContext, loader
from django.http import HttpResponse, JsonResponse
from django.core.urlresolvers import reverse
from django.http.response import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from rest_framework.response import Response
from rest_framework import viewsets
from rest_framework.views import APIView
from rest_framework.status import (
    HTTP_200_OK, HTTP_201_CREATED,
    HTTP_400_BAD_REQUEST,
    HTTP_500_INTERNAL_SERVER_ERROR,
    HTTP_401_UNAUTHORIZED,
    HTTP_409_CONFLICT,
    HTTP_404_NOT_FOUND,
)
from rest_framework.permissions import AllowAny
from rest_framework.request import Request

from juloserver.account.services.repayment import get_account_from_payment_method
from juloserver.account_payment.services.gopay import (
    process_gopay_initial_for_account,
    process_gopay_repayment_for_account
)

from juloserver.julo.utils import display_rupiah
from juloserver.julo.services2.payment_method import get_active_loan
from juloserver.julo.utils import generate_sha512
from juloserver.julo.models import (
    PaybackTransaction,
    FeatureSetting,
    PaymentMethod,
    Payment,
)
from juloserver.julo.services import (
    get_oldest_payment_due,
)

from juloserver.payback.serializers import (
    CimbSnapAccessTokenSerializer,
    GopayAccountLinkNotificationSerializer,
    OuterRequestSerializer,
    SnapAccessTokenSerializer,
    DOKUPaymentNotificationSerializer,
)

from juloserver.payback.models import (
    CashbackPromo,
    GopayRepaymentTransaction,
    DanaBillerInquiry,
    DanaBillerStatus,
    DanaBillerOrder,
)
from juloserver.payback.services.gopay import (
    GopayServices,
    is_eligible_change_url_gopay,
)
from juloserver.payback.serializers import (
    PaybackTransactionSerializer,
    GopayNotificationSerializer,
    InitTransactionSerializer,
    GopayInitTransactionSerializer,
    DanaBillerInquirySerializer,
    DanaGetOrderSerializer,
    CIMBPaymentNotificationSerializer,
)
from juloserver.payback.status import GoPayTransStatus

from .forms import CashbackPromoTemplateForm
from .services.cashback_promo import save_cashback_promo_file
from .services.dana_biller import create_order, verify_signature
from .utils.cashback_promo import generate_token
from .tasks.cashback_promo_tasks import (sent_cashback_promo_approval,
                                         inject_cashback_task,
                                         sent_cashback_promo_notification_to_requester)
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import general_error_response, success_response
from juloserver.payback.services.payback import (
    record_transaction_data_for_autodebet_gopay,
    check_payment_method_vendor,
)
from juloserver.payback.services.dana_biller import (
    verify_signature,
    generate_signature,
    get_dana_biller_payment_method,
)
from juloserver.julo.banks import BankCodes
from juloserver.payback.constants import (
    DanaBillerStatusCodeConst,
    FeatureSettingNameConst,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.account_payment.constants import CheckoutRequestCons
from juloserver.account_payment.models import AccountPayment, CheckoutRequest
from juloserver.integapiv1.constants import (
    SnapVendorChoices,
    EXPIRY_TIME_TOKEN_CIMB_SNAP,
    EXPIRY_TIME_TOKEN_DOKU_SNAP,
    SnapInquiryResponseCodeAndMessage,
    SnapReasonMultilanguage,
    SnapStatus,
    ErrorDetail,
    SnapTokenResponseCodeAndMessage,
    SnapPaymentNotificationResponseCodeAndMessage,
)
from juloserver.integapiv1.serializers import SnapInquiryBillsSerializer
from juloserver.integapiv1.services import (
    generate_snap_expiry_token,
    get_snap_expiry_token,
    is_expired_snap_token,
    authenticate_snap_request,
)
from juloserver.integapiv1.utils import verify_asymmetric_signature
from juloserver.julo.services2 import get_redis_client
from juloserver.payback.tasks.doku_tasks import send_slack_alert_doku_payment_notification
from juloserver.payback.constants import (
    CIMBSnapPaymentResponseCodeAndMessage,
    CimbVAConst,
)
from juloserver.payback.services.cimb_va import process_cimb_repayment
from juloserver.integapiv1.tasks2.cimb_tasks import send_slack_alert_cimb_payment_notification
from juloserver.autodebet.utils import detokenize_sync_primary_object_model
from juloserver.pii_vault.constants import PiiSource

from juloserver.account_payment.services.payment_flow import process_repayment_trx
from juloserver.refinancing.services import j1_refinancing_activation
from juloserver.waiver.services.waiver_related import process_j1_waiver_before_payment
from juloserver.moengage.tasks import update_moengage_for_payment_received_task
from juloserver.pii_vault.repayment.services import pii_lookup
from juloserver.payback.tasks.payback_tasks import store_payback_callback_log

logger = logging.getLogger(__name__)
sentry = get_julo_sentry_client()


class TransactionView(APIView):
    def get(self, request, format=None):
        transactions = PaybackTransaction.objects.filter(customer=request.user.customer)
        serializer = PaybackTransactionSerializer(transactions, many=True)
        return Response(data=serializer.data)


class GopayView(viewsets.ViewSet):
    def init(self, request, format=None):
        ''' This function inits the transaction for Gopay '''

        def process_init_for_mtl():
            loan = get_active_loan(payment_method)
            if not loan:
                logger.error({
                    'action': 'Init gopay transaction',
                    'error': 'Loan not found'
                })
                return Response(status=HTTP_400_BAD_REQUEST, data={'error': 'No active loan found'})

            user_applications = request.user.customer.application_set.values_list('id', flat=True)
            if loan.application_id not in user_applications:
                logger.error({
                    'action': 'Init gopay transaction',
                    'error': 'User not application owner, invalid application_id: %s' % loan.application_id
                })
                return Response(status=HTTP_400_BAD_REQUEST,
                                data={'error': 'User is not application owner'})

            payment = get_oldest_payment_due(loan)
            # Initiate the transaction
            if payment:
                data = gopay_services.init_transaction(
                    payment=payment,
                    payment_method=payment_method,
                    amount=amount)
                serializer = PaybackTransactionSerializer(data['transaction'])
                res_data = serializer.data
                res_data['gopay'] = data['gopay']

                return Response(status=HTTP_201_CREATED, data=res_data)

            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={'error': 'Invalid Request'})

        serializer = InitTransactionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        gopay_services = GopayServices()

        payment_method = serializer.validated_data['payment_method']
        amount = serializer.validated_data['amount']

        logger.info(
            {
                'action': 'Init gopay transaction',
                'action_group': 'payment_api_requests',
                'data': request.data,
            }
        )

        account = get_account_from_payment_method(payment_method)
        if account:
            return process_gopay_initial_for_account(request, amount, account, payment_method)
        else:
            return process_init_for_mtl()

    def current_status(self, request, transaction_id, format=None):
        transaction = PaybackTransaction.objects.get_or_none(transaction_id=transaction_id)
        if not transaction:
            return Response(
                data={'error': 'Matching transaction not found'},
                status=HTTP_400_BAD_REQUEST)

        serializer = PaybackTransactionSerializer(transaction)

        return Response(data=serializer.data)


class GopayCallbackView(APIView):
    permission_classes = (AllowAny, )

    def post(self, request):
        data = GopayNotificationSerializer(request.data).data
        status_code = data['status_code']
        order_id = data['order_id']
        gross_amount = data['gross_amount']
        signature = data['signature_key']
        transaction_status = data['transaction_status']

        # Validate signature
        signature_keystring = '{}{}{}{}'.format(
            order_id,
            status_code,
            gross_amount,
            settings.GOPAY_SERVER_KEY)
        gen_signature = generate_sha512(signature_keystring)

        logger.info(
            {
                'action': 'Gopay callback handler',
                'action_group': 'payment_api_requests',
                'data': data,
            }
        )

        if gen_signature != str(signature):
            logger.error({
                'action': 'Gopay callback handler',
                'error': 'authentication is failed, %s' % gen_signature,
            })
            return Response(
                data={'error': 'invalid signature'},
                status=HTTP_400_BAD_REQUEST
            )

        if 'subscription_id' not in data:
            #update the gopay repayment transaction detail
            gopay_repayment_transaction = GopayRepaymentTransaction.objects.filter(
                transaction_id=order_id).last()
            if gopay_repayment_transaction:
                gopay_repayment_transaction.update_safely(
                    status=transaction_status,
                    status_code=status_code,
                    status_message=data['status_message'],
                    external_transaction_id=data['transaction_id'],
                )
            # Get the transaction
            transaction = PaybackTransaction.objects.get_or_none(
                transaction_id=order_id)
        else:
            transaction = record_transaction_data_for_autodebet_gopay(data)
            if transaction is None:
                logger.error({
                    'action': 'Gopay callback handler',
                    'error': 'Transaction not found for the gopay autodebet, order_id: %s' % order_id,
                })
                return Response(
                    status=HTTP_200_OK,
                    data={'msg': 'Status Updated'}
                )

        if transaction is None:
            logger.error({
                'action': 'Gopay callback handler',
                'error': 'Transaction not found, order_id: %s' % order_id,
            })
            return Response(
                data={'error': 'invalid transaction'},
                status=HTTP_400_BAD_REQUEST
            )
        elif transaction.is_processed:
            logger.warning({
                'action': 'Gopay callback handler',
                'error': 'Transaction has been processed, order_id: %s' % order_id,
            })
            return Response(status=HTTP_200_OK, data={'msg': 'Transaction has been processed'})

        # Update status
        if GoPayTransStatus.is_success(transaction_status, status_code):
            if transaction.account:
                account_payment = transaction.account.get_oldest_unpaid_account_payment()
                if not account_payment:
                    logger.error({
                        'action': 'Gopay callback handler',
                        'error': 'Customer has no unpaid account payment',
                        'account_id': transaction.account.id
                    })
                    return Response(
                        data={'error': 'customer has no unpaid account payment'},
                        status=HTTP_400_BAD_REQUEST)
                if process_gopay_repayment_for_account(transaction, data):
                    return Response(status=HTTP_200_OK, data={'msg': 'Status Updated'})
            else:
                loan = transaction.loan
                payment = get_oldest_payment_due(loan)
                if not payment:
                    logger.error({
                        'action': 'Gopay callback handler',
                        'error': 'Customer has no unpaid payment, loan_id: %s' % loan.id,
                    })
                    return Response(
                        data={'error': 'customer has no unpaid payment'},
                        status=HTTP_400_BAD_REQUEST)
                if GopayServices.process_loan(loan, payment, transaction, data):
                    return Response(status=HTTP_200_OK, data={'msg': 'Status Updated'})
        else:
            GopayServices.update_transaction_status(transaction, data)
            return Response(status=HTTP_200_OK, data={'msg': 'Status Updated'})


def cashback_promo_add(request):
    cashback_promo_form = CashbackPromoTemplateForm(request.POST or None)
    template = loader.get_template('custom_admin/cashback_promo_template_form.html')
    data = {}
    if request.POST and cashback_promo_form.is_valid():
        cashback_promo_saved = cashback_promo_form.save()
        excel_file = request.FILES.get('input_file')
        cashback_promo_saved.requester = request.user
        if excel_file:
            number_of_customer, total_money =  save_cashback_promo_file(
                cashback_promo_saved, excel_file, request)
            cashback_promo_saved.number_of_customers = number_of_customer
            cashback_promo_saved.total_money = total_money
        cashback_promo_saved.approval_token = generate_token(
            cashback_promo_saved.pic_email,
            cashback_promo_saved.id,
            cashback_promo_saved.udate)
        cashback_promo_saved.save()
        redirect_url = reverse('cashback_promo_admin:cashback_promo_review',
                             kwargs={'cashback_promo_id': cashback_promo_saved.pk})
        return redirect(redirect_url)
    context = RequestContext(request, {
        "cashback_promo_form": cashback_promo_form,
        "data": data,
        "form_status": "add"
    })
    return HttpResponse(template.render(context))

def cashback_promo_edit(request, cashback_promo_id):
    temp_cash_back = CashbackPromo.objects.get(pk=cashback_promo_id)
    data = {
        'promo_name': temp_cash_back.promo_name,
        'department': temp_cash_back.department,
        'pic_email': temp_cash_back.pic_email,
        'number_of_customers': temp_cash_back.number_of_customers,
        'total_money': temp_cash_back.total_money,
    }
    cashback_promo_form = CashbackPromoTemplateForm(request.POST or None, initial=data, instance=temp_cash_back)
    template = loader.get_template('custom_admin/cashback_promo_template_form.html')
    if request.POST and cashback_promo_form.is_valid():
        cashback_promo_saved = cashback_promo_form.save()
        excel_file = request.FILES.get('input_file')
        cashback_promo_saved.requester = request.user
        if excel_file:
            number_of_customer, total_money = save_cashback_promo_file(
                cashback_promo_saved, excel_file, request)
            cashback_promo_saved.number_of_customers = number_of_customer
            cashback_promo_saved.total_money = total_money
        cashback_promo_saved.approval_token = generate_token(
            cashback_promo_saved.pic_email,
            cashback_promo_saved.id,
            cashback_promo_saved.udate)
        cashback_promo_saved.save()
        redirect_url = reverse('cashback_promo_admin:cashback_promo_review',
                             kwargs={'cashback_promo_id': cashback_promo_saved.pk})
        return redirect(redirect_url)

    context = RequestContext(request, {
        "cashback_promo_form": cashback_promo_form,
        "form_status": "update"
    })
    return HttpResponse(template.render(context))

def cashback_promo_review(request, cashback_promo_id):
    template = loader.get_template('custom_admin/cashback_promo_template_review.html')
    message = None
    cash_back = CashbackPromo.objects.get(pk=cashback_promo_id)
    review_data = {
        'promo_name': cash_back.promo_name,
        'departement': cash_back.department,
        'pic_email': cash_back.pic_email,
        'number_of_customers': cash_back.number_of_customers,
        'total_money': display_rupiah(cash_back.total_money),
        'decision': cash_back.decision
    }
    context = RequestContext(request, {
        "message": message,
        "data": review_data,
        "edit_link": reverse('cashback_promo_admin:cashback_promo_edit',
                            kwargs={'cashback_promo_id': cashback_promo_id}),
        "request_link": reverse('cashback_promo_admin:cashback_promo_proceed',
                            kwargs={'cashback_promo_id': cashback_promo_id}),
    })

    messages.warning(request, 'Please make sure all detail are correct')
    return HttpResponse(template.render(context))

def cashback_promo_proceed(request, cashback_promo_id):
    sent_cashback_promo_approval.delay(cashback_promo_id)
    messages.success(request, 'Cashback Promo request succeed, please wait for approval.')
    return redirect(reverse('cashback_promo_admin:payback_cashbackpromo_changelist'))


def cashback_promo_decision(request, approval_token):
    template_name = 'cashback_promo/error.html'
    if request.method == 'GET':
        cashback_promo = CashbackPromo.objects.get_or_none(
            approval_token=approval_token, decision__isnull=True)
        approver = request.GET.get('approver', None)
        decision = request.GET.get('decision', None)
        if cashback_promo and approver and decision:
            if decision == 'approved':
                template_name = 'cashback_promo/approved.html'
            elif decision == 'rejected':
                template_name = 'cashback_promo/rejected.html'
            if decision in ('approved', 'rejected'):
                cashback_promo.update_safely(
                    decided_by=approver, decision=decision, decision_ts=timezone.now())
                sent_cashback_promo_notification_to_requester.delay(cashback_promo.id)
            if decision == 'approved':
                #we set execution time to almost midnight to prevent performance issue
                later = timezone.localtime(timezone.now()).replace(hour=23, minute=30)
                inject_cashback_task.apply_async([cashback_promo.id], eta=later)
    return render(request, template_name)


class GopayOnboardingPageView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        response, error = GopayServices.get_gopay_onboarding_data()

        if error:
            return general_error_response(error)

        return success_response(response)


class GopayCreatePayAccountView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        gopay_services = GopayServices()
        customer = request.user.customer
        response, error = gopay_services.create_pay_account(customer)

        if is_eligible_change_url_gopay(request.path):
            if isinstance(response, dict) and 'web_linking' in response:
                response['web_linking'] = response['web_linking'].replace(
                    'gopay.co.id/app', 'gojek.link/gopay'
                )

        if error:
            return general_error_response(error)

        return success_response(response)


class GopayGetPayAccountDetailsView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        gopay_services = GopayServices()
        account = request.user.customer.account
        response, error = gopay_services.get_pay_account(account)

        if error:
            return general_error_response(error)

        return success_response(response)


class GopayPayAccountLinkNotificationView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = (AllowAny,)
    def post(self, request):
        gopay_services = GopayServices()
        serializer = GopayAccountLinkNotificationSerializer(request.data)
        data = serializer.data
        pay_account_id = data['account_id']
        signature_key = data['signature_key']
        status_code = data['status_code']
        account_status = data['account_status']
        response, error = gopay_services.pay_account_link_notification(
            pay_account_id,
            signature_key,
            status_code,
            account_status
        )

        if error:
            return general_error_response(error)

        return success_response(response)


class GopayPayAccountUnbind(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request):
        gopay_services = GopayServices()
        account = request.user.customer.account
        response, error = gopay_services.unbind_gopay_account_linking(account)

        if error:
            return general_error_response(error)

        return success_response(response)


class GopayAccountRepaymentView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = (AllowAny,)
    def post(self, request):
        account = request.user.customer.account
        serializer = GopayInitTransactionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment_method = serializer.validated_data['payment_method']
        amount = serializer.validated_data['amount']

        logger.info({
            'action': 'Init gopay tokenization transaction',
            'data': request.data
        })

        return process_gopay_initial_for_account(request, amount, account, payment_method, is_gopay_tokenization=True)


class BaseDanaBillerView(APIView):
    permission_classes = (AllowAny,)

    def dispatch(self, request, *args, **kwargs):
        raw_body = request.body
        response = super().dispatch(request, *args, **kwargs)
        try:
            data = json.loads(response.content)
            signature = generate_signature(data.get('response'), settings.DANA_BILLER_PRIVATE_KEY)
            data["signature"] = signature
            self.log_request(raw_body, request, response, data)

            return JsonResponse(
                data, status=response.status_code, json_dumps_params={'separators': (',', ':')}
            )
        except Exception as e:
            sentry.captureException()
            return response

    def log_request(self, request_body, request, response, response_data):
        data_to_log = {
            "action": "dana_biller_api",
            "request_body": request_body.decode('utf-8'),
            "endpoint": request.get_full_path(),
            "method": request.method,
            "response_code": response.status_code,
            "response_data": response_data,
            "error_message": self.kwargs.get('error_message')
        }

        log_method = logger.warning if 400 <= response.status_code <= 499 else (
            logger.error if 500 <= response.status_code <= 599 else logger.info
        )
        log_method(data_to_log)
        return


    def get_request_data(self, request):
        try:
            data = json.loads(request.body)
        except Exception:
            data = {}
        self.kwargs['request_data'] = data.get('request', {})
        self.kwargs['head_request_data'] = self.kwargs['request_data'].get('head', {})
        copy_head_request_data = self.kwargs['head_request_data'].copy()
        try:
            del copy_head_request_data['reqTime']
        except KeyError:
            pass
        self.kwargs['head_response_data'] = {
            "respTime": timezone.localtime(timezone.now()).replace(microsecond=0).isoformat(),
            **copy_head_request_data
        }
        self.kwargs['body_data'] = self.kwargs['request_data'].get('body', {})
        self.kwargs['destination_info_data'] = self.kwargs['body_data'].get('destinationInfos',
                                                                            [{}])
        self.kwargs['primary_param'] = self.kwargs['destination_info_data'][0].get(
            'primaryParam'
        )


class DanaBillerProductView(BaseDanaBillerView):
    def post(self, request):
        self.get_request_data(request)
        response_data = {
            "response": {
                "head": self.kwargs['head_response_data'],
                "body": {"products": []}
            },
            "signature": None
        }
        try:
            public_key = settings.DANA_BILLER_PUBLIC_KEY
            feature_setting = FeatureSetting.objects.filter(
                feature_name=FeatureSettingNameConst.CHANGE_PUBLIC_KEY_DANA_BILLER,
                is_active=True
            ).last()

            if settings.ENVIRONMENT != 'prod' and feature_setting:
                public_key = feature_setting.parameters.get('public_key', public_key)

            if not verify_signature(request.data, public_key):
                return JsonResponse(data=response_data, status=HTTP_401_UNAUTHORIZED)

            feature_setting_exists = FeatureSetting.objects.filter(
                feature_name=FeatureSettingNameConst.DANA_BILLER_PRODUCT,
                is_active=True,
            ).exists()
            product = {"productId": BankCodes.DANA_BILLER, "type": "INSTALLMENT", "provider": "julo",
                       "price": {"value": "0", "currency": "IDR"},
                       "availability": feature_setting_exists}
            response_data['response']['body']['products'] = [product]

            return JsonResponse(
                data=response_data, status=HTTP_200_OK, json_dumps_params={'separators': (',', ':')}
            )
        except Exception as e:
            sentry.captureException()
            self.kwargs['error_message'] = str(e)
            # for error case dana want the http status code is 200
            return JsonResponse(
                data=response_data, status=HTTP_200_OK, json_dumps_params={'separators': (',', ':')}
            )


class DanaBillerInquiryView(BaseDanaBillerView):
    def dispatch(self, request, *args, **kwargs):
        raw_body = request.body
        response = super().dispatch(request, *args, **kwargs)
        try:
            data = json.loads(response.content)
            signature = generate_signature(data.get('response'), settings.DANA_BILLER_PRIVATE_KEY)
            data["signature"] = signature
            self.log_request(raw_body, request, response, data)
            self.create_and_save_inquiry()

            return JsonResponse(
                data, status=response.status_code, json_dumps_params={'separators': (',', ':')}
            )
        except Exception as e:
            sentry.captureException()
            return response

    def create_and_save_inquiry(self):
        if self.kwargs.get('primary_param'):
            DanaBillerInquiry.objects.create(
                inquiry_id=self.kwargs.get('inquiry_id'),
                primary_param=self.kwargs.get('primary_param'),
                account_payment_id=self.kwargs.get('account_payment_id'),
                account_id=self.kwargs.get('account_id'),
                amount=self.kwargs.get('amount'),
                dana_biller_status=self.kwargs.get('dana_biller_status'),
            )

    def post(self, request):
        self._pre_log_request(request)
        self.get_request_data(request)
        self.kwargs['inquiry_id'] = uuid.uuid4().hex
        self.get_dana_biller_status(DanaBillerStatusCodeConst.SUCCESS)
        inquiry_result = {
            "inquiryId": self.kwargs['inquiry_id'],
            "inquiryStatus": {
                "code": self.kwargs['dana_biller_status'].code,
                "status": "SUCCESS",
                "message": self.kwargs['dana_biller_status'].message
            },
            "destinationInfo": self.kwargs['destination_info_data'][0],
            "type": "INSTALLMENT",
            "totalAmount": {"value": "0", "currency": "IDR"},
            "baseAmount": {"value": "0", "currency": "IDR"},
            "customerName": "",
        }
        response_data = {
            "response": {
                "head": self.kwargs['head_response_data'],
                "body": {"inquiryResults": [inquiry_result]}
            },
            "signature": None
        }
        try:
            public_key = settings.DANA_BILLER_PUBLIC_KEY
            feature_setting = FeatureSetting.objects.filter(
                feature_name=FeatureSettingNameConst.CHANGE_PUBLIC_KEY_DANA_BILLER,
                is_active=True
            ).last()

            if settings.ENVIRONMENT != 'prod' and feature_setting:
                public_key = feature_setting.parameters.get('public_key', public_key)

            if not verify_signature(request.data, public_key):
                self.get_dana_biller_status(DanaBillerStatusCodeConst.GENERAL_ERROR)
                self.update_inquiry_data_failed_case(response_data, "signature invalid")
                return JsonResponse(data=response_data, status=HTTP_401_UNAUTHORIZED)
            serializer = DanaBillerInquirySerializer(data=request.data)
            if not serializer.is_valid():
                self.get_dana_biller_status(DanaBillerStatusCodeConst.GENERAL_ERROR)
                self.update_inquiry_data_failed_case(response_data, "invalid payload")
                return JsonResponse(data=response_data, status=HTTP_400_BAD_REQUEST)
            data = serializer.validated_data
            status_code = self.process_inquiry_results(response_data, inquiry_result, request, data)

            return JsonResponse(
                data=response_data, status=status_code, json_dumps_params={'separators': (',', ':')}
            )
        except Exception as e:
            sentry.captureException()
            self.get_dana_biller_status(DanaBillerStatusCodeConst.TRANSACTION_FAILED)
            self.update_inquiry_data_failed_case(response_data, str(e))
            # for transaction failed dana want the http status code is 200
            return JsonResponse(
                data=response_data, status=HTTP_200_OK, json_dumps_params={'separators': (',', ':')}
            )

    def _pre_log_request(
        self,
        request: Request,
    ) -> None:
        body = request.data.get('request', {}).get('body', {})
        logger.info(
            {
                "action": "DanaBillerInquiryView",
                "action_group": "payment_api_requests",
                "endpoint": request.get_full_path(),
                "method": request.method,
                "virtual_account": body.get('destinationInfos', [{}]),
                "transaction_id": body.get('requestId', ''),
            }
        )

    def get_dana_biller_status(self, code):
        self.kwargs['dana_biller_status'] = DanaBillerStatus.objects.get_or_none(
            code=code
        )

    def update_inquiry_data_failed_case(self, response_data, error_message):
        inquiry_result = response_data["response"]["body"]["inquiryResults"][0]
        inquiry_result['inquiryStatus']['code'] = self.kwargs['dana_biller_status'].code
        inquiry_result['inquiryStatus']['status'] = "FAILED"
        inquiry_result['inquiryStatus']['message'] = self.kwargs['dana_biller_status'].message
        response_data["response"]["body"]["inquiryResults"] = [inquiry_result]
        self.kwargs['error_message'] = error_message

    def process_inquiry_results(self, response_data, inquiry_result, request, data):
        payment_method = PaymentMethod.objects.filter(
            payment_method_code=BankCodes.DANA_BILLER,
            virtual_account=self.kwargs['primary_param']
        ).last()

        if not payment_method:
            self.get_dana_biller_status(DanaBillerStatusCodeConst.INVALID_DESTINATION)
            self.update_inquiry_data_failed_case(response_data, "payment method not found")
            return HTTP_200_OK

        detokenized_customer = detokenize_sync_primary_object_model(
            PiiSource.CUSTOMER,
            payment_method.customer,
            payment_method.customer.customer_xid,
            ['fullname'],
        )
        inquiry_result['customerName'] = detokenized_customer.fullname

        account = payment_method.customer.account_set.last()
        self.kwargs['account_id'] = account.id
        account_payments = account.accountpayment_set.status_overdue().order_by('due_date').only(
            'id', 'due_date', 'due_amount'
        )
        periods = []
        detail_amount = []
        for account_payment in account_payments:
            due_date = timezone.localtime(
                datetime.combine(account_payment.due_date, datetime.min.time())
            ).isoformat()
            periods.append(due_date)
            detail_amount.append(
                {
                    "amount": {
                        "value": str(account_payment.due_amount) + "00",
                        "currency": "IDR"
                    },
                    "period": due_date
                }
            )
        account_payment = account_payments.order_by('-due_date').first()
        amount = account.get_total_overdue_amount()

        if not account_payment:
            account_payment = account.get_oldest_unpaid_account_payment()
            if account_payment:
                amount = account_payment.due_amount
                due_date = timezone.localtime(
                    datetime.combine(account_payment.due_date, datetime.min.time())
                ).isoformat()
                periods.append(due_date)
                detail_amount.append(
                    {
                        "amount": {
                            "value": str(amount) + "00",
                            "currency": "IDR"
                        },
                        "period": due_date
                    }
                )

        if not account_payment:
            self.get_dana_biller_status(DanaBillerStatusCodeConst.BILL_NOT_AVAILABLE)
            self.update_inquiry_data_failed_case(response_data, "bill not available")
            return HTTP_200_OK

        self.kwargs['account_payment_id'] = account_payment.id
        self.kwargs['amount'] = amount
        amount = {"value": str(amount) + "00", "currency": "IDR"}
        zero_amount = {"value": "0", "currency": "IDR"}
        inquiry_result['totalAmount'] = amount
        inquiry_result['baseAmount'] = amount
        inquiry_result['adminFee'] = zero_amount
        inquiry_result['fineAmount'] = zero_amount
        inquiry_result['period'] = periods
        inquiry_result['detailAmount'] = detail_amount
        inquiry_result['paymentCount'] = Payment.objects.paid().filter(
            loan_id__in=account.get_all_active_loan().values_list('pk', flat=True),
        ).values_list('account_payment_id', flat=True).distinct('account_payment_id').count()
        inquiry_result['dueDate'] = timezone.localtime(
            datetime.combine(account_payment.due_date, datetime.min.time())
        ).isoformat()
        response_data["response"]["body"]["inquiryResults"] = [inquiry_result]

        return HTTP_200_OK


class DanaBillerCreateOrderView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = (AllowAny,)

    def post(self, request):
        self._pre_log_request(request)
        serializer = OuterRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data, status = create_order(serializer.validated_data)

        if data == 'unauthorized':
            return JsonResponse(
                status=HTTP_401_UNAUTHORIZED, data={'message': 'Signature not match'}
            )

        if not status:
            return JsonResponse(
                data, status=HTTP_400_BAD_REQUEST, json_dumps_params={'separators': (',', ':')}
            )

        return JsonResponse(
            data, status=HTTP_201_CREATED, json_dumps_params={'separators': (',', ':')}
        )

    def _pre_log_request(
        self,
        request: Request,
    ) -> None:
        body = request.data.get('request', {}).get('body', {})
        logger.info(
            {
                "action": "DanaBillerCreateOrderView",
                "action_group": "payment_api_requests",
                "endpoint": request.get_full_path(),
                "method": request.method,
                "virtual_account": body.get('destinationInfo', {}),
                "transaction_id": body.get('requestId', ''),
            }
        )


class DanaGetOrderDetailView(BaseDanaBillerView):
    def post(self, request):
        self.get_request_data(request)
        response_data = {
            "response": {"head": self.kwargs['head_response_data'], "body": {"orders": []}},
            "signature": None,
        }
        try:
            public_key = settings.DANA_BILLER_PUBLIC_KEY
            if not verify_signature(request.data, public_key):
                return JsonResponse(data=response_data, status=HTTP_401_UNAUTHORIZED)

            serializer = DanaGetOrderSerializer(data=request.data)
            if not serializer.is_valid():
                return JsonResponse(data=response_data, status=HTTP_400_BAD_REQUEST)

            orders = []
            order_list = serializer.validated_data['request']['body']['orderIdentifiers']
            for order in order_list:
                request_id = order['requestId']
                order_id = order['orderId']
                amount = "0"
                primary_param = ''
                dana_biller_order = DanaBillerOrder.objects.filter(
                    request_id=request_id,
                ).last()
                if dana_biller_order:
                    created_time = timezone.localtime(dana_biller_order.cdate)
                    modified_time = timezone.localtime(dana_biller_order.udate)
                    formated_created_time = (
                        created_time.isoformat().split('.')[0]
                        + '+'
                        + created_time.isoformat().split('+')[1]
                    )
                    formated_modified_time = (
                        modified_time.isoformat().split('.')[0]
                        + '+'
                        + modified_time.isoformat().split('+')[1]
                    )
                    if not order_id:
                        order_id = dana_biller_order.order_id
                    dana_biller_status = dana_biller_order.dana_biller_status
                    code = dana_biller_status.code
                    status = "SUCCESS" if dana_biller_status.is_success else "FAILED"
                    message = dana_biller_status.message
                    dana_biller_inquiry = dana_biller_order.dana_biller_inquiry
                    if dana_biller_inquiry:
                        if dana_biller_inquiry.account:
                            payment_method = get_dana_biller_payment_method(
                                dana_biller_inquiry.account
                            )
                            detokenized_payment_method = detokenize_sync_primary_object_model(
                                PiiSource.PAYMENT_METHOD,
                                payment_method,
                                required_fields=['virtual_account'],
                            )
                            primary_param = detokenized_payment_method.virtual_account
                        if dana_biller_inquiry.amount:
                            amount = (
                                str(dana_biller_inquiry.amount) + "00"
                                if dana_biller_status.is_success
                                else "0"
                            )
                else:
                    formated_created_time = ''
                    formated_modified_time = ''
                    code = DanaBillerStatusCodeConst.ORDER_NOT_FOUND
                    status = 'EMPTY'
                    message = 'Order Not Found'

                feature_setting_exists = FeatureSetting.objects.filter(
                    feature_name=FeatureSettingNameConst.DANA_BILLER_PRODUCT,
                    is_active=True,
                ).exists()

                orders.append(
                    {
                        "requestId": request_id,
                        "orderId": order_id,
                        "createdTime": formated_created_time,
                        "modifiedTime": formated_modified_time,
                        "destinationInfo": {
                            "primaryParam": primary_param,
                        },
                        "orderStatus": {
                            "code": code,
                            "status": status,
                            "message": message,
                        },
                        "product": {
                            "productId": BankCodes.DANA_BILLER,
                            "type": "INSTALLMENT",
                            "provider": "julo",
                            "price": {
                                "value": amount,
                                "currency": "IDR",
                            },
                            "availability": feature_setting_exists,
                        },
                    }
                )

            if not orders:
                return JsonResponse(data=response_data, status=HTTP_404_NOT_FOUND)

            response_data['response']['body']['orders'] = orders

            return JsonResponse(data=response_data, status=HTTP_200_OK)
        except Exception as e:
            sentry.captureException()
            self.kwargs['error_message'] = str(e)
            return JsonResponse(data=response_data, status=HTTP_500_INTERNAL_SERVER_ERROR)


class BaseSnapCimbView(APIView):
    permission_classes = (AllowAny,)

    @csrf_exempt
    def dispatch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raw_body = request.body
        response = super().dispatch(request, *args, **kwargs)
        self._log_request(raw_body, request, response)
        if hasattr(response, 'render'):
            response.render()
        if hasattr(response, 'content'):
            redis_client = get_redis_client()
            response_data = json.loads(response.content)
            external_id = request.META.get('HTTP_X_EXTERNAL_ID', None)
            key = 'cimb_snap:external_id:{}'.format(external_id)
            external_id_redis = redis_client.get(key)
            if external_id and not external_id_redis:
                today_datetime = timezone.localtime(timezone.now())
                tomorrow_datetime = today_datetime + relativedelta(
                    days=1, hour=0, minute=0, second=0
                )
                redis_client.set(key, json.dumps(response_data), tomorrow_datetime - today_datetime)

        return response

    def _pre_log_request(
        self,
        request: Request,
    ) -> None:
        logger.info(
            {
                "action": "BaseSnapCimbView",
                "action_group": "payment_api_requests",
                "endpoint": request.get_full_path(),
                "method": request.method,
                "virtual_account": request.data.get('virtualAccountNo', ''),
                "transaction_id": request.data.get('inquiryRequestId', '')
                or request.data.get('paymentRequestId', ''),
            }
        )

    def _log_request(
        self,
        request_body: bytes,
        request: Request,
        response: Response,
    ) -> None:
        timestamp = request.META.get('HTTP_X_TIMESTAMP', None)
        signature = request.META.get('HTTP_X_SIGNATURE', None)
        partner_id = request.META.get('HTTP_X_PARTNER_ID', None)
        external_id = request.META.get('HTTP_X_EXTERNAL_ID', None)
        channel_id = request.META.get('HTTP_CHANNEL_ID', None)

        headers = {
            'HTTP_X_TIMESTAMP': timestamp,
            'HTTP_X_SIGNATURE': signature,
            'HTTP_X_PARTNER_ID': partner_id,
            'HTTP_X_EXTERNAL_ID': external_id,
            'HTTP_CHANNEL_ID': channel_id,
        }
        data_to_log = {
            "action": "snap_cimb_api_view_logs",
            "headers": headers,
            "request_body": request_body.decode('utf-8'),
            "endpoint": request.get_full_path(),
            "method": request.method,
            "response_code": response.status_code,
            "response_data": response.__dict__,
        }
        if 400 <= response.status_code <= 499:
            logger.warning(data_to_log)
        elif 500 <= response.status_code <= 599:
            logger.error(data_to_log)
        else:
            logger.info(data_to_log)


class CimbSnapAccessTokenView(BaseSnapCimbView):
    def post(self, request, *args, **kwargs):
        client_id = request.META.get('HTTP_X_CLIENT_KEY')
        signature = request.META.get('HTTP_X_SIGNATURE')
        timestamp = request.META.get('HTTP_X_TIMESTAMP')

        serializer = CimbSnapAccessTokenSerializer(data=request.data)
        if not serializer.is_valid():
            key = list(serializer.errors.items())[0][0]
            errors = list(serializer.errors.items())[0][1]
            response_code = SnapTokenResponseCodeAndMessage.INVALID_FIELD_FORMAT.code
            response_message = "{} {}".format(
                SnapTokenResponseCodeAndMessage.INVALID_FIELD_FORMAT.message, key
            )
            if 'This field is required.' in errors:
                response_code = SnapTokenResponseCodeAndMessage.INVALID_MANDATORY_FIELD.code
                response_message = "{} {}".format(
                    SnapTokenResponseCodeAndMessage.INVALID_MANDATORY_FIELD.message,
                    key,
                )

            return JsonResponse(
                status=HTTP_400_BAD_REQUEST,
                data={
                    "responseCode": response_code,
                    "responseMessage": response_message,
                    "accessToken": "",
                    "tokenType": "",
                    "expiresIn": "",
                },
            )
        if client_id != settings.CIMB_SNAP_CLIENT_ID_INBOUND:
            return JsonResponse(
                status=HTTP_401_UNAUTHORIZED,
                data={
                    "responseCode": SnapTokenResponseCodeAndMessage.UNAUTHORIZED_CLIENT.code,
                    "responseMessage": (
                        SnapTokenResponseCodeAndMessage.UNAUTHORIZED_CLIENT.message
                    ),
                },
            )
        string_to_sign = '{}|{}'.format(client_id, timestamp)
        public_key = settings.CIMB_SNAP_PUBLIC_KEY_INBOUND
        cimb_credential_fs = FeatureSetting.objects.filter(
            feature_name=FeatureSettingNameConst.CHANGE_CIMB_VA_CREDENTIALS, is_active=True
        ).last()

        if cimb_credential_fs:
            public_key = cimb_credential_fs.parameters['public_key']

        try:
            is_valid_signature = verify_asymmetric_signature(public_key, signature, string_to_sign)
        except Exception:
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
            is_valid_signature = False
        if not is_valid_signature:
            return JsonResponse(
                status=HTTP_401_UNAUTHORIZED,
                data={
                    "responseCode": SnapTokenResponseCodeAndMessage.UNAUTHORIZED_SIGNATURE.code,
                    "responseMessage": (
                        SnapTokenResponseCodeAndMessage.UNAUTHORIZED_SIGNATURE.message
                    ),
                },
            )

        expiry_token = generate_snap_expiry_token(SnapVendorChoices.CIMB)

        return JsonResponse(
            data={
                "responseCode": SnapTokenResponseCodeAndMessage.SUCCESS.code,
                "responseMessage": SnapTokenResponseCodeAndMessage.SUCCESS.message,
                "accessToken": expiry_token.key,
                "tokenType": "bearer",
                "expiresIn": "{}".format(EXPIRY_TIME_TOKEN_CIMB_SNAP),
            }
        )


class CimbSnapInquiryBillsView(BaseSnapCimbView):
    def post(self, request):
        cimb_bill = {
            "responseCode": "",
            "responseMessage": "",
            "virtualAccountData": {
                "inquiryStatus": "",
                "inquiryReason": {"english": "", "indonesia": ""},
                "partnerServiceId": request.data.get('partnerServiceId', ''),
                "customerNo": request.data.get('customerNo', ''),
                "virtualAccountNo": request.data.get('virtualAccountNo', ''),
                "virtualAccountName": "",
                "inquiryRequestId": request.data.get('inquiryRequestId', ''),
                "totalAmount": {"value": "", "currency": ""},
                "virtualAccountTrxType": "O",
            },
            "additionalInfo": {},
        }
        try:
            self._pre_log_request(request)
            # check token
            access_token = request.META.get('HTTP_AUTHORIZATION', '').split(' ')[-1]
            snap_expiry_token = get_snap_expiry_token(access_token, SnapVendorChoices.CIMB)

            if not snap_expiry_token or is_expired_snap_token(
                snap_expiry_token, EXPIRY_TIME_TOKEN_CIMB_SNAP
            ):
                response_data = {
                    'responseCode': SnapInquiryResponseCodeAndMessage.INVALID_TOKEN.code,
                    'responseMessage': SnapInquiryResponseCodeAndMessage.INVALID_TOKEN.message,
                }

                return JsonResponse(status=HTTP_401_UNAUTHORIZED, data=response_data)

            data = request.data
            relative_url = request.get_full_path()
            headers = {
                "access_token": access_token,
                "content_type": request.META.get('CONTENT_TYPE'),
                "origin": request.META.get('HTTP_ORIGIN'),
                "x_key": request.META.get('HTTP_X_TIMESTAMP'),
                "x_timestamp": request.META.get('HTTP_X_TIMESTAMP'),
                "x_signature": request.META.get('HTTP_X_SIGNATURE'),
            }
            is_authenticated = authenticate_snap_request(
                headers,
                data,
                request.method,
                settings.CIMB_SNAP_CLIENT_SECRET_INBOUND,
                relative_url,
            )
            if not is_authenticated:
                response_data = {
                    'responseCode': (SnapInquiryResponseCodeAndMessage.UNAUTHORIZED_SIGNATURE.code),
                    'responseMessage': (
                        SnapInquiryResponseCodeAndMessage.UNAUTHORIZED_SIGNATURE.message
                    ),
                }
                return JsonResponse(status=HTTP_401_UNAUTHORIZED, data=response_data)

            serializer = SnapInquiryBillsSerializer(data=request.data)
            if not serializer.is_valid():
                key = list(serializer.errors.items())[0][0]
                errors = list(serializer.errors.items())[0][1][0]
                cimb_bill['virtualAccountData']['inquiryStatus'] = SnapStatus.FAILED
                if errors in ErrorDetail.mandatory_field_errors():
                    cimb_bill[
                        'responseCode'
                    ] = SnapInquiryResponseCodeAndMessage.INVALID_MANDATORY_FIELD.code
                    cimb_bill['responseMessage'] = "{} {}".format(
                        SnapInquiryResponseCodeAndMessage.INVALID_MANDATORY_FIELD.message,
                        key,
                    )
                    cimb_bill['virtualAccountData']['inquiryReason'] = {
                        "english": (
                            SnapReasonMultilanguage.INVALID_MANDATORY_FIELD.english.format(key)
                        ),
                        "indonesia": (
                            SnapReasonMultilanguage.INVALID_MANDATORY_FIELD.indonesia.format(key)
                        ),
                    }
                else:
                    cimb_bill[
                        'responseCode'
                    ] = SnapInquiryResponseCodeAndMessage.INVALID_FIELD_FORMAT.code
                    cimb_bill['responseMessage'] = "{} {}".format(
                        SnapInquiryResponseCodeAndMessage.INVALID_FIELD_FORMAT.message,
                        key,
                    )
                    cimb_bill['virtualAccountData']['inquiryReason'] = {
                        "english": (
                            SnapReasonMultilanguage.INVALID_FIELD_FORMAT.english.format(key)
                        ),
                        "indonesia": (
                            SnapReasonMultilanguage.INVALID_FIELD_FORMAT.indonesia.format(key)
                        ),
                    }
                return JsonResponse(status=HTTP_400_BAD_REQUEST, data=cimb_bill)

            external_id = request.META.get('HTTP_X_EXTERNAL_ID')
            if not external_id:
                cimb_bill[
                    'responseCode'
                ] = SnapInquiryResponseCodeAndMessage.INVALID_MANDATORY_FIELD.code
                cimb_bill['responseMessage'] = "{} X-EXTERNAL-ID".format(
                    SnapInquiryResponseCodeAndMessage.INVALID_MANDATORY_FIELD.message
                )
                cimb_bill['virtualAccountData']['inquiryStatus'] = SnapStatus.FAILED
                cimb_bill['virtualAccountData']['inquiryReason'] = {
                    "english": SnapReasonMultilanguage.NULL_EXTERNAL_ID.english,
                    "indonesia": SnapReasonMultilanguage.NULL_EXTERNAL_ID.indonesia,
                }
                return JsonResponse(status=HTTP_409_CONFLICT, data=cimb_bill)
            key = 'cimb_snap:external_id:{}'.format(external_id)
            redis_client = get_redis_client()
            external_id_redis = redis_client.get(key)
            if external_id_redis:
                cimb_bill[
                    'responseCode'
                ] = SnapInquiryResponseCodeAndMessage.EXTERNAL_ID_CONFLICT.code
                cimb_bill[
                    'responseMessage'
                ] = SnapInquiryResponseCodeAndMessage.EXTERNAL_ID_CONFLICT.message
                cimb_bill['virtualAccountData']['inquiryStatus'] = SnapStatus.FAILED
                cimb_bill['virtualAccountData']['inquiryReason'] = {
                    "english": SnapReasonMultilanguage.DUPLICATE_EXTERNAL_ID.english,
                    "indonesia": SnapReasonMultilanguage.DUPLICATE_EXTERNAL_ID.indonesia,
                }
                return JsonResponse(status=HTTP_409_CONFLICT, data=cimb_bill)

            payback_transaction = PaybackTransaction.objects.filter(
                transaction_id=data['inquiryRequestId']
            ).exists()
            if payback_transaction and payback_transaction.is_processed:
                cimb_bill['responseCode'] = SnapInquiryResponseCodeAndMessage.PAID_BILL.code
                cimb_bill['responseMessage'] = SnapInquiryResponseCodeAndMessage.PAID_BILL.message
                cimb_bill['virtualAccountData']['inquiryStatus'] = SnapStatus.FAILED
                cimb_bill['virtualAccountData']['inquiryReason'] = {
                    "english": SnapReasonMultilanguage.PAID_BILL.english,
                    "indonesia": SnapReasonMultilanguage.PAID_BILL.indonesia,
                }
                return JsonResponse(status=HTTP_409_CONFLICT, data=cimb_bill)
            virtual_account = data.get('virtualAccountNo').strip()
            query_filter = {'virtual_account': virtual_account}
            response_pii_lookup = pii_lookup(virtual_account)
            if response_pii_lookup:
                query_filter = {'virtual_account_tokenized__in': response_pii_lookup}
            payment_method = PaymentMethod.objects.filter(**query_filter).last()

            if not payment_method:
                cimb_bill[
                    'responseCode'
                ] = SnapInquiryResponseCodeAndMessage.BILL_OR_VA_NOT_FOUND.code
                cimb_bill[
                    'responseMessage'
                ] = SnapInquiryResponseCodeAndMessage.BILL_OR_VA_NOT_FOUND.message
                cimb_bill['virtualAccountData']['inquiryStatus'] = SnapStatus.FAILED
                cimb_bill['virtualAccountData']['inquiryReason'] = {
                    "english": SnapReasonMultilanguage.VA_NOT_FOUND.english,
                    "indonesia": SnapReasonMultilanguage.VA_NOT_FOUND.indonesia,
                }
                cimb_bill['virtualAccountData']['totalAmount']['value'] = '0.00'
                return JsonResponse(status=HTTP_400_BAD_REQUEST, data=cimb_bill)

            loan = get_active_loan(payment_method)

            if not loan:
                cimb_bill['responseCode'] = SnapInquiryResponseCodeAndMessage.PAID_BILL.code
                cimb_bill['responseMessage'] = SnapInquiryResponseCodeAndMessage.PAID_BILL.message
                cimb_bill['virtualAccountData']['inquiryStatus'] = SnapStatus.FAILED
                cimb_bill['virtualAccountData']['inquiryReason'] = {
                    "english": SnapReasonMultilanguage.VA_NOT_HAVE_BILL.english,
                    "indonesia": SnapReasonMultilanguage.VA_NOT_HAVE_BILL.indonesia,
                }
                cimb_bill['virtualAccountData']['totalAmount']['value'] = '0.00'
                return JsonResponse(status=HTTP_400_BAD_REQUEST, data=cimb_bill)

            due_amount = 0
            account = payment_method.customer.account_set.last()
            checkout_request = CheckoutRequest.objects.filter(
                account_id=account, status=CheckoutRequestCons.ACTIVE
            ).last()

            cimb_bill['responseCode'] = SnapInquiryResponseCodeAndMessage.SUCCESS.code
            cimb_bill['responseMessage'] = SnapInquiryResponseCodeAndMessage.SUCCESSFUL.message
            cimb_bill['virtualAccountData']['inquiryStatus'] = SnapStatus.SUCCESS
            cimb_bill['virtualAccountData']['inquiryReason'] = {
                "english": SnapReasonMultilanguage.SUCCESSFUL.english,
                "indonesia": SnapReasonMultilanguage.SUCCESSFUL.indonesia,
            }
            cimb_bill['virtualAccountData']['totalAmount']['currency'] = 'IDR'
            detokenized_customer = detokenize_sync_primary_object_model(
                PiiSource.CUSTOMER,
                account.customer,
                account.customer.customer_xid,
                ['fullname'],
            )
            cimb_bill['virtualAccountData']['virtualAccountName'] = detokenized_customer.fullname
            if checkout_request:
                due_amount = checkout_request.total_payments
            else:
                account_payments = (
                    AccountPayment.objects.not_paid_active()
                    .filter(account=account)
                    .order_by('due_date')
                )
                if not account_payments:
                    cimb_bill['responseCode'] = SnapInquiryResponseCodeAndMessage.PAID_BILL.code
                    cimb_bill[
                        'responseMessage'
                    ] = SnapInquiryResponseCodeAndMessage.PAID_BILL.message
                    cimb_bill['virtualAccountData']['inquiryStatus'] = SnapStatus.FAILED
                    cimb_bill['virtualAccountData']['inquiryReason'] = {
                        "english": SnapReasonMultilanguage.PAID_BILL.english,
                        "indonesia": SnapReasonMultilanguage.PAID_BILL.indonesia,
                    }
                    cimb_bill['virtualAccountData']['totalAmount']['value'] = '0.00'
                    return JsonResponse(data=cimb_bill)

                for account_payment in account_payments.iterator():
                    account_payment_dpd = account_payment.due_late_days
                    if account_payment_dpd >= 0:
                        due_amount += account_payment.due_amount
                    elif due_amount == 0:
                        due_amount += account_payment.due_amount
                        break

            additional_info = request.data.get('additionalInfo', '')
            if additional_info and 'isPayment' in additional_info:
                if additional_info['isPayment'] == 'Y':
                    if not payback_transaction:
                        PaybackTransaction.objects.create(
                            transaction_id=data['inquiryRequestId'],
                            is_processed=False,
                            virtual_account=payment_method.virtual_account,
                            customer=account.customer,
                            payment_method=payment_method,
                            payback_service='cimb',
                            account=account,
                            amount=due_amount,
                        )
            cimb_bill['virtualAccountData']['totalAmount']['value'] = '{}.00'.format(
                str(due_amount)
            )

            return JsonResponse(data=cimb_bill)
        except Exception:
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
            cimb_bill['responseCode'] = SnapInquiryResponseCodeAndMessage.GENERAL_ERROR.code
            cimb_bill['responseMessage'] = SnapInquiryResponseCodeAndMessage.GENERAL_ERROR.message
            cimb_bill['virtualAccountData']['inquiryStatus'] = ''
            cimb_bill['virtualAccountData']['inquiryReason'] = {
                "english": "",
                "indonesia": "",
            }
            return JsonResponse(status=HTTP_500_INTERNAL_SERVER_ERROR, data=cimb_bill)


class CimbPaymentNotificationView(BaseSnapCimbView):
    def dispatch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        response = super().dispatch(request, *args, **kwargs)
        if response.status_code != 200:
            if not self.kwargs.get('error_message'):
                self.kwargs['error_message'] = response.data
            send_slack_alert_cimb_payment_notification.delay(
                self.kwargs.get('error_message'),
                self.kwargs.get('payment_request_id'),
            )

        return response

    def post(self, request):
        response_data = {
            "responseCode": "",
            "responseMessage": "",
            "virtualAccountData": {
                "paymentFlagStatus": SnapStatus.FAILED,
                "paymentFlagReason": {
                    "indonesia": ""
                },
                "partnerServiceId": request.data.get('partnerServiceId', ''),
                "customerNo": request.data.get('customerNo', ''),
                "virtualAccountNo": request.data.get('virtualAccountNo', ''),
                "virtualAccountName": request.data.get('virtualAccountName', ''),
                "paymentRequestId": request.data.get('paymentRequestId', ''),
                "referenceNo": request.data.get('referenceNo', ''),
                "paidAmount": {
                    "value": "",
                    "currency": ""
                },
                "totalAmount": {
                    "value": "",
                    "currency": ""
                },
            },
            "additionalInfo": {},
        }
        try:
            self._pre_log_request(request)
            self.kwargs['payment_request_id'] = request.data.get('paymentRequestId')
            access_token = request.META.get('HTTP_AUTHORIZATION', '').split(' ')[-1]
            snap_expiry_token = get_snap_expiry_token(access_token, SnapVendorChoices.CIMB)

            if not snap_expiry_token or is_expired_snap_token(
                    snap_expiry_token, EXPIRY_TIME_TOKEN_CIMB_SNAP
            ):
                response_data = {
                    'responseCode': SnapInquiryResponseCodeAndMessage.INVALID_TOKEN.code,
                    'responseMessage': SnapInquiryResponseCodeAndMessage.INVALID_TOKEN.message,
                }
                self.kwargs['error_message'] = 'invalid token'
                return JsonResponse(status=HTTP_401_UNAUTHORIZED, data=response_data)

            data = request.data
            relative_url = request.get_full_path()
            headers = {
                "access_token": access_token,
                "content_type": request.META.get('CONTENT_TYPE'),
                "origin": request.META.get('HTTP_ORIGIN'),
                "x_key": request.META.get('HTTP_X_TIMESTAMP'),
                "x_timestamp": request.META.get('HTTP_X_TIMESTAMP'),
                "x_signature": request.META.get('HTTP_X_SIGNATURE'),
            }
            is_authenticated = authenticate_snap_request(
                headers, data, request.method, settings.CIMB_SNAP_CLIENT_SECRET_INBOUND,
                relative_url
            )
            if not is_authenticated:
                response_data = {
                    'responseCode': (
                        SnapInquiryResponseCodeAndMessage.UNAUTHORIZED_SIGNATURE.code
                    ),
                    'responseMessage': (
                        SnapInquiryResponseCodeAndMessage.UNAUTHORIZED_SIGNATURE.message
                    ),
                }
                self.kwargs['error_message'] = response_data['responseMessage']
                return JsonResponse(status=HTTP_401_UNAUTHORIZED, data=response_data)
            serializer = CIMBPaymentNotificationSerializer(data=request.data)
            if not serializer.is_valid():
                key = list(serializer.errors.items())[0][0]
                errors = list(serializer.errors.items())[0][1][0]
                if errors in ErrorDetail.mandatory_field_errors():
                    response_data['responseCode'] = CIMBSnapPaymentResponseCodeAndMessage. \
                        INVALID_MANDATORY_FIELD.code
                    response_data['responseMessage'] = "{} {}".format(
                        CIMBSnapPaymentResponseCodeAndMessage.INVALID_MANDATORY_FIELD.message,
                        key,
                    )
                    response_data['virtualAccountData']['paymentFlagReason'] = {
                        "indonesia": (SnapReasonMultilanguage.
                                      INVALID_MANDATORY_FIELD.indonesia.format(key)),
                    }
                else:
                    response_data['responseCode'] = CIMBSnapPaymentResponseCodeAndMessage. \
                        INVALID_FIELD_FORMAT.code
                    response_data['responseMessage'] = "{} {}".format(
                        CIMBSnapPaymentResponseCodeAndMessage.INVALID_FIELD_FORMAT.message,
                        key,
                    )
                    if key == 'paidAmount' and errors == 'Amount':
                        response_data['responseMessage'] = (CIMBSnapPaymentResponseCodeAndMessage.
                                                            INVALID_AMOUNT.message)
                        response_data['responseCode'] = (CIMBSnapPaymentResponseCodeAndMessage.
                                                         INVALID_AMOUNT.code)
                    response_data['virtualAccountData']['paymentFlagReason'] = {
                        "indonesia": (SnapReasonMultilanguage.
                                      INVALID_FIELD_FORMAT.indonesia.format(key)),
                    }
                self.kwargs['error_message'] = response_data['responseMessage']
                return JsonResponse(status=HTTP_400_BAD_REQUEST, data=response_data)
            if float(data['paidAmount']['value']) < float(CimbVAConst.MINIMUM_TRANSFER_AMOUNT):
                self.kwargs['error_message'] = 'paid amount {} below the minimum amount {}'.format(
                    float(data['paidAmount']['value']),
                    float(CimbVAConst.MINIMUM_TRANSFER_AMOUNT)
                )
                response_data[
                    'responseCode'] = CIMBSnapPaymentResponseCodeAndMessage.INVALID_AMOUNT.code
                response_data['responseMessage'] = CIMBSnapPaymentResponseCodeAndMessage. \
                    INVALID_AMOUNT.message
                response_data['virtualAccountData']['paymentFlagStatus'] = SnapStatus.FAILED
                response_data['virtualAccountData']['paymentFlagReason'] = {
                    "english": SnapReasonMultilanguage.INVALID_AMOUNT.english,
                    "indonesia": SnapReasonMultilanguage.INVALID_AMOUNT.indonesia,
                }

                return JsonResponse(status=HTTP_400_BAD_REQUEST, data=response_data)
            external_id = request.META.get('HTTP_X_EXTERNAL_ID')
            if not external_id:
                response_data['responseCode'] = CIMBSnapPaymentResponseCodeAndMessage. \
                    INVALID_MANDATORY_FIELD.code
                response_data['responseMessage'] = "{} X-EXTERNAL-ID".format(
                    CIMBSnapPaymentResponseCodeAndMessage.INVALID_MANDATORY_FIELD.message
                )
                response_data['virtualAccountData']['paymentFlagStatus'] = SnapStatus.FAILED
                response_data['virtualAccountData']['paymentFlagReason'] = {
                    "english": SnapReasonMultilanguage.NULL_EXTERNAL_ID.english,
                    "indonesia": SnapReasonMultilanguage.NULL_EXTERNAL_ID.indonesia,
                }
                return JsonResponse(
                    status=HTTP_400_BAD_REQUEST, data=response_data
                )
            key = 'cimb_snap:external_id:{}'.format(external_id)
            redis_client = get_redis_client()
            raw_value = redis_client.get(key)
            if raw_value:
                response_data['responseCode'] = CIMBSnapPaymentResponseCodeAndMessage. \
                    EXTERNAL_ID_CONFLICT.code
                response_data['responseMessage'] = CIMBSnapPaymentResponseCodeAndMessage. \
                    EXTERNAL_ID_CONFLICT.message
                response_data['virtualAccountData']['paymentFlagStatus'] = SnapStatus.FAILED
                response_data['virtualAccountData']['paymentFlagReason'] = {
                    "english": SnapReasonMultilanguage.DUPLICATE_EXTERNAL_ID.english,
                    "indonesia": SnapReasonMultilanguage.DUPLICATE_EXTERNAL_ID.indonesia,
                }
            virtual_account = data.get('virtualAccountNo', '').strip()
            query_filter = {'virtual_account': virtual_account}
            response_pii_lookup = pii_lookup(virtual_account)
            if response_pii_lookup:
                query_filter = {'virtual_account_tokenized__in': response_pii_lookup}
            payment_method = PaymentMethod.objects.filter(**query_filter).last()
            if not payment_method:
                self.kwargs['error_message'] = 'virtual account {} not found'.format(
                    virtual_account
                )
                response_data[
                    'responseCode'] = CIMBSnapPaymentResponseCodeAndMessage.VA_NOT_FOUND.code
                response_data['responseMessage'] = CIMBSnapPaymentResponseCodeAndMessage. \
                    VA_NOT_FOUND.message
                response_data['virtualAccountData']['paymentFlagReason'] = {
                    "english": SnapReasonMultilanguage.VA_NOT_FOUND.english,
                    "indonesia": SnapReasonMultilanguage.VA_NOT_FOUND.indonesia,
                }
                return JsonResponse(status=HTTP_404_NOT_FOUND, data=response_data)

            account = payment_method.customer.account_set.last()
            if account:
                account_payment = account.get_oldest_unpaid_account_payment()
                if not account_payment:
                    self.kwargs['error_message'] = 'virtual account doesnt have the bill'
                    response_data[
                        'responseCode'] = CIMBSnapPaymentResponseCodeAndMessage.PAID_BILL.code
                    response_data['responseMessage'] = CIMBSnapPaymentResponseCodeAndMessage. \
                        PAID_BILL.message
                    response_data['virtualAccountData']['paymentFlagReason'] = {
                        "english": SnapReasonMultilanguage.VA_NOT_HAVE_BILL.english,
                        "indonesia": SnapReasonMultilanguage.VA_NOT_HAVE_BILL.indonesia,
                    }
                    return JsonResponse(status=HTTP_404_NOT_FOUND, data=response_data)
            payment_request_id = data.get('paymentRequestId', '')
            payback_transaction = PaybackTransaction.objects.filter(
                payment_method=payment_method,
                transaction_id=payment_request_id).last()

            if not payback_transaction:
                self.kwargs['error_message'] = 'payback transaction not found'
                response_data[
                    'responseCode'] = CIMBSnapPaymentResponseCodeAndMessage.VA_NOT_FOUND.code
                response_data['responseMessage'] = CIMBSnapPaymentResponseCodeAndMessage. \
                    VA_NOT_FOUND.message
                response_data['virtualAccountData']['paymentFlagReason'] = {
                    "indonesia": SnapReasonMultilanguage.BILL_NOT_FOUND.indonesia,
                }

                return JsonResponse(status=HTTP_404_NOT_FOUND, data=response_data)
            elif payback_transaction.is_processed:
                self.kwargs['error_message'] = 'payback transaction has already been processed'
                response_data['responseCode'] = CIMBSnapPaymentResponseCodeAndMessage.PAID_BILL.code
                response_data['responseMessage'] = CIMBSnapPaymentResponseCodeAndMessage. \
                    PAID_BILL.message
                response_data['virtualAccountData']['paymentFlagStatus'] = SnapStatus.FAILED
                response_data['virtualAccountData']['paymentFlagReason'] = {
                    "indonesia": SnapReasonMultilanguage.PAID_BILL.indonesia,
                }

                return JsonResponse(status=HTTP_404_NOT_FOUND, data=response_data)

            process_cimb_repayment(
                payback_transaction.id,
                datetime.strptime(data['trxDateTime'], "%Y-%m-%dT%H:%M:%S%z"),
                float(data['paidAmount']['value'])
            )
            response_data['virtualAccountData']['paymentFlagStatus'] = SnapStatus.SUCCESS
            response_data['virtualAccountData']['paymentFlagReason'] = {
                "indonesia": "Sukses"
            }
            response_data['virtualAccountData']['paidAmount'] = data["paidAmount"]
            response_data['virtualAccountData']['totalAmount'] = data["totalAmount"]
            response_data['virtualAccountData']['paymentFlagStatus'] = SnapStatus.SUCCESS
            response_data['responseCode'] = CIMBSnapPaymentResponseCodeAndMessage.SUCCESS.code
            response_data['responseMessage'] = CIMBSnapPaymentResponseCodeAndMessage.SUCCESS.message

            return JsonResponse(status=HTTP_200_OK, data=response_data)
        except Exception as e:
            sentry.captureException()
            self.kwargs['error_message'] = str(e)
            return JsonResponse(status=HTTP_500_INTERNAL_SERVER_ERROR, data=response_data)


class BaseSnapView(APIView):
    permission_classes = (AllowAny,)

    vendor = ''

    def dispatch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raw_body = request.body
        response = super().dispatch(request, *args, **kwargs)
        self._log_request(raw_body, request, response)
        if hasattr(response, 'render'):
            response.render()
        if hasattr(response, 'content'):
            redis_client = get_redis_client()
            response_data = json.loads(response.content)
            external_id = request.META.get('HTTP_X_EXTERNAL_ID', None)
            key = '{}_snap:external_id:{}'.format(self.vendor, external_id)
            external_id_redis = redis_client.get(key)
            if external_id and not external_id_redis:
                today_datetime = timezone.localtime(timezone.now())
                tomorrow_datetime = today_datetime + relativedelta(
                    days=1, hour=0, minute=0, second=0
                )
                redis_client.set(key, json.dumps(response_data), tomorrow_datetime - today_datetime)

        return response

    def _pre_log_request(
        self,
        request: Request,
    ) -> None:
        logger.info(
            {
                "action": "{}BaseSnapView".format(self.vendor),
                "action_group": "payment_api_requests",
                "endpoint": request.get_full_path(),
                "method": request.method,
                "virtual_account": request.data.get('virtualAccountNo', ''),
                "transaction_id": request.data.get('inquiryRequestId', '')
                or request.data.get('paymentRequestId', ''),
            }
        )

    def _log_request(
        self,
        request_body: bytes,
        request: Request,
        response: Response,
    ) -> None:
        timestamp = request.META.get('HTTP_X_TIMESTAMP', None)
        signature = request.META.get('HTTP_X_SIGNATURE', None)
        partner_id = request.META.get('HTTP_X_PARTNER_ID', None)
        external_id = request.META.get('HTTP_X_EXTERNAL_ID', None)
        channel_id = request.META.get('HTTP_CHANNEL_ID', None)

        headers = {
            'HTTP_X_TIMESTAMP': timestamp,
            'HTTP_X_SIGNATURE': signature,
            'HTTP_X_PARTNER_ID': partner_id,
            'HTTP_X_EXTERNAL_ID': external_id,
            'HTTP_CHANNEL_ID': channel_id,
        }
        data_to_log = {
            "action": "{}_snap_api_view_log".format(self.vendor),
            "headers": headers,
            "request_body": request_body.decode('utf-8'),
            "endpoint": request.get_full_path(),
            "method": request.method,
            "response_code": response.status_code,
            "response_data": response.__dict__,
        }
        store_payback_callback_log.delay(
            request_data=request_body,
            response_data=response.content,
            http_status_code=response.status_code,
            url='[POST] {}'.format(request.get_full_path()),
            vendor=SnapVendorChoices.DOKU,
            customer_id=self.kwargs.get('customer_id', None),
            loan_id=self.kwargs.get('loan_id', None),
            account_payment_id=self.kwargs.get('account_payment_id', None),
            payback_transaction_id=self.kwargs.get('payback_transaction_id', None),
            error_message=self.kwargs.get('error_message', None),
            header=headers,
        )
        if 400 <= response.status_code <= 499:
            logger.warning(data_to_log)
        elif 500 <= response.status_code <= 599:
            logger.error(data_to_log)
        else:
            logger.info(data_to_log)


class BaseSnapAccessTokenView(BaseSnapView):

    # BaseSnapAccessTokenView is the common SNAP access token view that can be inherited to vendor views
    # please use this view for all SNAP integration in future
    # please do add some modifications in flows optionally so it can still be used by other vendors

    # CONFIGURATION
    client_id = ''
    public_key = ''
    token_expiry_time = 0

    def post(self, request, *args, **kwargs):
        client_id = request.META.get('HTTP_X_CLIENT_KEY')
        signature = request.META.get('HTTP_X_SIGNATURE')
        timestamp = request.META.get('HTTP_X_TIMESTAMP')

        serializer = SnapAccessTokenSerializer(data=request.data)
        if not serializer.is_valid():
            key = list(serializer.errors.items())[0][0]
            errors = list(serializer.errors.items())[0][1]
            response_code = SnapTokenResponseCodeAndMessage.INVALID_FIELD_FORMAT.code
            response_message = "{} [clientId/clientSecret/grantType]".format(
                SnapTokenResponseCodeAndMessage.INVALID_FIELD_FORMAT.message
            )
            if 'This field is required.' in errors:
                response_code = SnapTokenResponseCodeAndMessage.INVALID_MANDATORY_FIELD.code
                response_message = "{} {}".format(
                    SnapTokenResponseCodeAndMessage.INVALID_MANDATORY_FIELD.message,
                    key,
                )

            return JsonResponse(
                status=HTTP_400_BAD_REQUEST,
                data={
                    "responseCode": response_code,
                    "responseMessage": response_message,
                },
            )
        # VALIDATE TIMESTAMP
        try:
            format_timestamp = timezone.localtime(
                datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S+07:00')
            )
            now = timezone.localtime(timezone.now())
            start = now - timedelta(minutes=10)

            if format_timestamp < start or format_timestamp > now:
                raise Exception
        except Exception:
            response_code = SnapTokenResponseCodeAndMessage.INVALID_FIELD_FORMAT.code
            response_message = "{} X-TIMESTAMP".format(
                SnapTokenResponseCodeAndMessage.INVALID_FIELD_FORMAT.message
            )
            return JsonResponse(
                status=HTTP_400_BAD_REQUEST,
                data={
                    "responseCode": response_code,
                    "responseMessage": response_message,
                },
            )
        if client_id != self.client_id:
            return JsonResponse(
                status=HTTP_401_UNAUTHORIZED,
                data={
                    "responseCode": SnapTokenResponseCodeAndMessage.UNAUTHORIZED_CLIENT.code,
                    "responseMessage": (
                        SnapTokenResponseCodeAndMessage.UNAUTHORIZED_CLIENT.message
                    ),
                },
            )
        string_to_sign = '{}|{}'.format(client_id, timestamp)
        public_key = self.public_key

        try:
            is_valid_signature = verify_asymmetric_signature(public_key, signature, string_to_sign)
        except Exception:
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
            is_valid_signature = False
        if not is_valid_signature:
            return JsonResponse(
                status=HTTP_401_UNAUTHORIZED,
                data={
                    "responseCode": SnapTokenResponseCodeAndMessage.UNAUTHORIZED_SIGNATURE.code,
                    "responseMessage": (
                        SnapTokenResponseCodeAndMessage.UNAUTHORIZED_SIGNATURE.message
                    ),
                },
            )

        expiry_token = generate_snap_expiry_token(self.vendor)

        return JsonResponse(
            data={
                "responseCode": SnapTokenResponseCodeAndMessage.SUCCESSFUL.code,
                "responseMessage": SnapTokenResponseCodeAndMessage.SUCCESSFUL.message,
                "accessToken": expiry_token.key,
                "tokenType": "bearer",
                "expiresIn": "{}".format(self.token_expiry_time),
            }
        )


class BaseSnapInquiryBillsView(BaseSnapView):

    # BaseSnapInquiryBillsView is the common SNAP inquiry view that can be inherited to vendor views
    # please use this view for all SNAP integration in future
    # please do add some modifications in flows optionally so it can still be used by other vendors

    # CONFIGURATION
    client_secret = ''
    token_expiry_time = 0
    is_validate_token = True
    inquiry_type = "O"
    request_header_map = {
        "content_type": 'CONTENT_TYPE',  # mandatory for signature validation
        "x_timestamp": 'HTTP_X_TIMESTAMP',  # mandatory for signature validation
        "x_signature": 'HTTP_X_SIGNATURE',  # mandatory for signature validation
        "origin": 'HTTP_ORIGIN',
        "x_key": 'HTTP_X_TIMESTAMP',
    }
    additional_info_default = {}

    def reconstruct_return_response(self, status=None, data=None):
        return data

    def return_response(self, status=None, data=None):
        reconstructed_data = self.reconstruct_return_response(status=status, data=data)

        return JsonResponse(status=status, data=reconstructed_data)

    def post(self, request):
        snap_bill = {
            "responseCode": "",
            "responseMessage": "",
            "virtualAccountData": {
                "inquiryStatus": "",
                "inquiryReason": {"english": "", "indonesia": ""},
                "partnerServiceId": request.data.get('partnerServiceId', ''),
                "customerNo": request.data.get('customerNo', ''),
                "virtualAccountNo": request.data.get('virtualAccountNo', ''),
                "virtualAccountName": "",
                "inquiryRequestId": request.data.get('inquiryRequestId', ''),
                "totalAmount": {"value": "", "currency": ""},
                "virtualAccountTrxType": "O",
            },
            "additionalInfo": self.additional_info_default,
        }
        try:
            # check token
            self._pre_log_request(request)
            is_vendor_match = check_payment_method_vendor(
                request.data.get('virtualAccountNo').strip()
            )

            if not is_vendor_match:
                snap_bill[
                    'responseCode'
                ] = SnapInquiryResponseCodeAndMessage.BILL_OR_VA_NOT_FOUND.code
                snap_bill[
                    'responseMessage'
                ] = SnapInquiryResponseCodeAndMessage.BILL_OR_VA_NOT_FOUND.message
                snap_bill['virtualAccountData']['inquiryStatus'] = SnapStatus.FAILED
                snap_bill['virtualAccountData']['inquiryReason'] = {
                    "english": SnapReasonMultilanguage.VA_NOT_FOUND.english,
                    "indonesia": SnapReasonMultilanguage.VA_NOT_FOUND.indonesia,
                }
                snap_bill['virtualAccountData']['totalAmount']['value'] = '0.00'
                return self.return_response(status=HTTP_404_NOT_FOUND, data=snap_bill)

            access_token = request.META.get('HTTP_AUTHORIZATION', '').split(' ')[-1]
            if self.is_validate_token:
                snap_expiry_token = get_snap_expiry_token(access_token, self.vendor)

                if not snap_expiry_token or is_expired_snap_token(
                    snap_expiry_token, self.token_expiry_time
                ):
                    response_data = {
                        'responseCode': SnapInquiryResponseCodeAndMessage.INVALID_TOKEN.code,
                        'responseMessage': SnapInquiryResponseCodeAndMessage.INVALID_TOKEN.message,
                    }
                    self.kwargs['error_message'] = response_data.get('responseMessage')

                    return self.return_response(status=HTTP_401_UNAUTHORIZED, data=response_data)

            data = request.data
            relative_url = request.get_full_path()
            headers = {
                "access_token": access_token,
            }
            for key, header_name in self.request_header_map.items():
                headers[key] = request.META.get(header_name)

            is_authenticated = authenticate_snap_request(
                headers,
                data,
                request.method,
                self.client_secret,
                relative_url,
            )
            if not is_authenticated:
                response_data = {
                    'responseCode': (SnapInquiryResponseCodeAndMessage.UNAUTHORIZED_SIGNATURE.code),
                    'responseMessage': (
                        SnapInquiryResponseCodeAndMessage.UNAUTHORIZED_SIGNATURE.message
                    ),
                }
                self.kwargs['error_message'] = response_data.get('responseMessage')
                return self.return_response(status=HTTP_401_UNAUTHORIZED, data=response_data)

            serializer = SnapInquiryBillsSerializer(data=request.data)
            if not serializer.is_valid():
                key = list(serializer.errors.items())[0][0]
                errors = list(serializer.errors.items())[0][1][0]
                snap_bill['virtualAccountData']['inquiryStatus'] = SnapStatus.FAILED
                if errors in ErrorDetail.mandatory_field_errors():
                    snap_bill[
                        'responseCode'
                    ] = SnapInquiryResponseCodeAndMessage.INVALID_MANDATORY_FIELD.code
                    snap_bill['responseMessage'] = "{} {}".format(
                        SnapInquiryResponseCodeAndMessage.INVALID_MANDATORY_FIELD.message,
                        key,
                    )
                    snap_bill['virtualAccountData']['inquiryReason'] = {
                        "english": (
                            SnapReasonMultilanguage.INVALID_MANDATORY_FIELD.english.format(key)
                        ),
                        "indonesia": (
                            SnapReasonMultilanguage.INVALID_MANDATORY_FIELD.indonesia.format(key)
                        ),
                    }
                else:
                    snap_bill[
                        'responseCode'
                    ] = SnapInquiryResponseCodeAndMessage.INVALID_FIELD_FORMAT.code
                    snap_bill['responseMessage'] = "{} {}".format(
                        SnapInquiryResponseCodeAndMessage.INVALID_FIELD_FORMAT.message,
                        key,
                    )
                    snap_bill['virtualAccountData']['inquiryReason'] = {
                        "english": (
                            SnapReasonMultilanguage.INVALID_FIELD_FORMAT.english.format(key)
                        ),
                        "indonesia": (
                            SnapReasonMultilanguage.INVALID_FIELD_FORMAT.indonesia.format(key)
                        ),
                    }
                self.kwargs['error_message'] = snap_bill.get('responseMessage')
                return self.return_response(status=HTTP_400_BAD_REQUEST, data=snap_bill)

            external_id = request.META.get('HTTP_X_EXTERNAL_ID')
            if not external_id:
                snap_bill[
                    'responseCode'
                ] = SnapInquiryResponseCodeAndMessage.INVALID_MANDATORY_FIELD.code
                snap_bill['responseMessage'] = "{} X-EXTERNAL-ID".format(
                    SnapInquiryResponseCodeAndMessage.INVALID_MANDATORY_FIELD.message
                )
                snap_bill['virtualAccountData']['inquiryStatus'] = SnapStatus.FAILED
                snap_bill['virtualAccountData']['inquiryReason'] = {
                    "english": SnapReasonMultilanguage.NULL_EXTERNAL_ID.english,
                    "indonesia": SnapReasonMultilanguage.NULL_EXTERNAL_ID.indonesia,
                }
                self.kwargs['error_message'] = snap_bill.get('responseMessage')
                return self.return_response(status=HTTP_409_CONFLICT, data=snap_bill)
            key = '{}_snap:external_id:{}'.format(self.vendor, external_id)
            redis_client = get_redis_client()
            external_id_redis = redis_client.get(key)
            if external_id_redis:
                snap_bill[
                    'responseCode'
                ] = SnapInquiryResponseCodeAndMessage.EXTERNAL_ID_CONFLICT.code
                snap_bill[
                    'responseMessage'
                ] = SnapInquiryResponseCodeAndMessage.EXTERNAL_ID_CONFLICT.message
                snap_bill['virtualAccountData']['inquiryStatus'] = SnapStatus.FAILED
                snap_bill['virtualAccountData']['inquiryReason'] = {
                    "english": SnapReasonMultilanguage.DUPLICATE_EXTERNAL_ID.english,
                    "indonesia": SnapReasonMultilanguage.DUPLICATE_EXTERNAL_ID.indonesia,
                }
                self.kwargs['error_message'] = snap_bill.get('responseMessage')
                return self.return_response(status=HTTP_409_CONFLICT, data=snap_bill)

            payback_transaction = PaybackTransaction.objects.filter(
                transaction_id=data['inquiryRequestId']
            ).last()
            if payback_transaction and payback_transaction.is_processed:
                snap_bill['responseCode'] = SnapInquiryResponseCodeAndMessage.PAID_BILL.code
                snap_bill['responseMessage'] = SnapInquiryResponseCodeAndMessage.PAID_BILL.message
                snap_bill['virtualAccountData']['inquiryStatus'] = SnapStatus.FAILED
                snap_bill['virtualAccountData']['inquiryReason'] = {
                    "english": SnapReasonMultilanguage.PAID_BILL.english,
                    "indonesia": SnapReasonMultilanguage.PAID_BILL.indonesia,
                }
                return self.return_response(status=HTTP_409_CONFLICT, data=snap_bill)

            virtual_account = data.get('virtualAccountNo').strip()
            query_filter = {'virtual_account': virtual_account}
            response_pii_lookup = pii_lookup(virtual_account)
            if response_pii_lookup:
                query_filter = {'virtual_account_tokenized__in': response_pii_lookup}
            payment_method = PaymentMethod.objects.filter(**query_filter).last()

            if not payment_method:
                snap_bill[
                    'responseCode'
                ] = SnapInquiryResponseCodeAndMessage.BILL_OR_VA_NOT_FOUND.code
                snap_bill[
                    'responseMessage'
                ] = SnapInquiryResponseCodeAndMessage.BILL_OR_VA_NOT_FOUND.message
                snap_bill['virtualAccountData']['inquiryStatus'] = SnapStatus.FAILED
                snap_bill['virtualAccountData']['inquiryReason'] = {
                    "english": SnapReasonMultilanguage.VA_NOT_FOUND.english,
                    "indonesia": SnapReasonMultilanguage.VA_NOT_FOUND.indonesia,
                }
                snap_bill['virtualAccountData']['totalAmount']['value'] = '0.00'
                self.kwargs['error_message'] = snap_bill.get('responseMessage')
                return self.return_response(status=HTTP_404_NOT_FOUND, data=snap_bill)

            loan = get_active_loan(payment_method)

            if not loan:
                snap_bill['responseCode'] = SnapInquiryResponseCodeAndMessage.PAID_BILL.code
                snap_bill['responseMessage'] = SnapInquiryResponseCodeAndMessage.PAID_BILL.message
                snap_bill['virtualAccountData']['inquiryStatus'] = SnapStatus.FAILED
                snap_bill['virtualAccountData']['inquiryReason'] = {
                    "english": SnapReasonMultilanguage.VA_NOT_HAVE_BILL.english,
                    "indonesia": SnapReasonMultilanguage.VA_NOT_HAVE_BILL.indonesia,
                }
                snap_bill['virtualAccountData']['totalAmount']['value'] = '0.00'
                self.kwargs['error_message'] = snap_bill.get('responseMessage')
                return self.return_response(status=HTTP_404_NOT_FOUND, data=snap_bill)

            due_amount = 0
            account = payment_method.customer.account_set.last()
            checkout_request = CheckoutRequest.objects.filter(
                account_id=account, status=CheckoutRequestCons.ACTIVE
            ).last()

            snap_bill['responseCode'] = SnapInquiryResponseCodeAndMessage.SUCCESS.code
            snap_bill['responseMessage'] = SnapInquiryResponseCodeAndMessage.SUCCESSFUL.message
            snap_bill['virtualAccountData']['inquiryStatus'] = SnapStatus.SUCCESS
            snap_bill['virtualAccountData']['inquiryReason'] = {
                "english": SnapReasonMultilanguage.SUCCESSFUL.english,
                "indonesia": SnapReasonMultilanguage.SUCCESSFUL.indonesia,
            }
            snap_bill['virtualAccountData']['totalAmount']['currency'] = 'IDR'
            detokenized_customer = detokenize_sync_primary_object_model(
                PiiSource.CUSTOMER,
                account.customer,
                account.customer.customer_xid,
                ['fullname'],
            )
            snap_bill['virtualAccountData']['virtualAccountName'] = detokenized_customer.fullname
            if checkout_request:
                due_amount = checkout_request.total_payments
            else:
                account_payments = (
                    AccountPayment.objects.not_paid_active()
                    .filter(account=account)
                    .order_by('due_date')
                )
                if not account_payments:
                    snap_bill['responseCode'] = SnapInquiryResponseCodeAndMessage.PAID_BILL.code
                    snap_bill[
                        'responseMessage'
                    ] = SnapInquiryResponseCodeAndMessage.PAID_BILL.message
                    snap_bill['virtualAccountData']['inquiryStatus'] = SnapStatus.FAILED
                    snap_bill['virtualAccountData']['inquiryReason'] = {
                        "english": SnapReasonMultilanguage.PAID_BILL.english,
                        "indonesia": SnapReasonMultilanguage.PAID_BILL.indonesia,
                    }
                    snap_bill['virtualAccountData']['totalAmount']['value'] = '0.00'
                    self.kwargs['error_message'] = snap_bill.get('responseMessage')
                    return self.return_response(status=HTTP_404_NOT_FOUND, data=snap_bill)

                for account_payment in account_payments.iterator():
                    account_payment_dpd = account_payment.due_late_days
                    if account_payment_dpd >= 0:
                        due_amount += account_payment.due_amount
                    elif due_amount == 0:
                        due_amount += account_payment.due_amount
                        break

            if not payback_transaction:
                payback_transaction = PaybackTransaction.objects.create(
                    transaction_id=data['inquiryRequestId'],
                    is_processed=False,
                    virtual_account=payment_method.virtual_account,
                    customer=account.customer,
                    payment_method=payment_method,
                    payback_service=self.vendor,
                    account=account,
                    amount=due_amount,
                )

            self.kwargs['customer_id'] = (
                payback_transaction.customer.id if payback_transaction.customer else None
            )
            self.kwargs['loan_id'] = (
                payback_transaction.loan.id if payback_transaction.loan else None
            )
            self.kwargs['payback_transaction_id'] = payback_transaction.id

            if self.inquiry_type == "O":
                snap_bill['virtualAccountData']['totalAmount']['value'] = '0.00'
            else:
                snap_bill['virtualAccountData']['totalAmount']['value'] = '{}.00'.format(
                    str(due_amount)
                )

            snap_bill['additionalInfo']['channel'] = data.get('additionalInfo', {}).get(
                'channel', ""
            )
            snap_bill['additionalInfo']['trxId'] = "JULO-" + str(payback_transaction.id)
            return self.return_response(status=HTTP_200_OK, data=snap_bill)

        except Exception as e:
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
            snap_bill['responseCode'] = SnapInquiryResponseCodeAndMessage.GENERAL_ERROR.code
            snap_bill['responseMessage'] = SnapInquiryResponseCodeAndMessage.GENERAL_ERROR.message
            snap_bill['virtualAccountData']['inquiryStatus'] = ''
            snap_bill['virtualAccountData']['inquiryReason'] = {
                "english": "",
                "indonesia": "",
            }
            self.kwargs['error_message'] = str(e)
            return self.return_response(status=HTTP_500_INTERNAL_SERVER_ERROR, data=snap_bill)


class DokuSnapAccessTokenView(BaseSnapAccessTokenView):
    # doku access token inherit from common snap access token
    def initial(self, request, *args, **kwargs):
        self.client_id = settings.DOKU_SNAP_CLIENT_ID_INBOUND
        self.public_key = settings.DOKU_SNAP_PUBLIC_KEY_INBOUND
        if settings.ENVIRONMENT != 'prod':
            doku_feature_setting = FeatureSetting.objects.filter(
                feature_name=FeatureSettingNameConst.CHANGE_DOKU_SNAP_CREDENTIALS,
                is_active=True,
            ).last()
            if doku_feature_setting:
                public_key = doku_feature_setting.parameters.get("public_key")
                if public_key and public_key != '':
                    self.public_key = public_key
        self.vendor = SnapVendorChoices.DOKU
        self.token_expiry_time = EXPIRY_TIME_TOKEN_DOKU_SNAP
        super().initial(request, *args, **kwargs)


class DokuSnapInquiryBillsView(BaseSnapInquiryBillsView):
    # doku inquiry inherit from common snap inquiry view
    def reconstruct_return_response(self, status, data):
        if "virtualAccountData" in data:
            data["virtualAccountData"]["additionalInfo"] = {
                "channel": data.get('additionalInfo', {}).get('channel', ""),
                "trxId": data.get('additionalInfo', {}).get('trxId', ""),
                "virtualAccountConfig": {
                    "minAmount": "10000.00",
                    "maxAmount": "300000000.00",
                },
            }
        data.pop("additionalInfo", None)

        return data

    def initial(self, request, *args, **kwargs):
        self.client_secret = settings.DOKU_SNAP_CLIENT_SECRET_INBOUND
        self.vendor = SnapVendorChoices.DOKU
        self.token_expiry_time = EXPIRY_TIME_TOKEN_DOKU_SNAP
        self.inquiry_type = "O"
        self.additional_info_default = {
            "channel": "",
            "trxId": "",
        }
        if settings.ENVIRONMENT != 'prod':
            doku_feature_setting = FeatureSetting.objects.filter(
                feature_name=FeatureSettingNameConst.CHANGE_DOKU_SNAP_CREDENTIALS,
                is_active=True,
            ).last()
            if doku_feature_setting:
                is_bypass = doku_feature_setting.parameters.get("is_bypass_access_token")
                self.is_validate_token = is_bypass != "true"
        super().initial(request, *args, **kwargs)


class DokuSnapPaymentNotificationView(BaseSnapView):
    def initial(self, request, *args, **kwargs):
        self.vendor = SnapVendorChoices.DOKU

    def dispatch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        response = super().dispatch(request, *args, **kwargs)
        if response.status_code != 200:
            self.kwargs['error_message'] = json.loads(response.content)['responseMessage']
            send_slack_alert_doku_payment_notification.delay(
                self.kwargs.get('error_message'),
                self.kwargs.get('payment_request_id'),
            )

        return response

    def post(self, request):
        response_data = {
            "responseCode": "",
            "responseMessage": "",
            "virtualAccountData": {
                "partnerServiceId": request.data.get('partnerServiceId', ''),
                "customerNo": request.data.get('customerNo', ''),
                "virtualAccountNo": request.data.get('virtualAccountNo', ''),
                "virtualAccountName": request.data.get('virtualAccountName', ''),
                "paymentRequestId": "",
                "paidAmount": {"value": "", "currency": "IDR"},
                "virtualAccountTrxType": "O",
                "additionalInfo": {
                    "channel": request.data.get('additionalInfo', {}).get('channel', ''),
                    "virtualAccountConfig": {
                        "minAmount": "10000.00",
                        "maxAmount": "300000000.00",
                    },
                },
            },
        }
        try:
            self._pre_log_request(request)
            self.kwargs['payment_request_id'] = request.data.get('paymentRequestId')
            access_token = request.META.get('HTTP_AUTHORIZATION', '').split(' ')[-1]
            snap_expiry_token = get_snap_expiry_token(access_token, SnapVendorChoices.DOKU)

            if not snap_expiry_token or is_expired_snap_token(
                snap_expiry_token, EXPIRY_TIME_TOKEN_DOKU_SNAP
            ):
                response_data = {
                    'responseCode': SnapPaymentNotificationResponseCodeAndMessage.INVALID_TOKEN.code,
                    'responseMessage': SnapPaymentNotificationResponseCodeAndMessage.INVALID_TOKEN.message,
                }
                self.kwargs['error_message'] = response_data.get('responseMessage')
                return JsonResponse(status=HTTP_401_UNAUTHORIZED, data=response_data)

            data = request.data
            relative_url = request.get_full_path()
            headers = {
                "access_token": access_token,
                "x_timestamp": request.META.get('HTTP_X_TIMESTAMP'),
                "x_signature": request.META.get('HTTP_X_SIGNATURE'),
            }
            is_authenticated = authenticate_snap_request(
                headers,
                data,
                request.method,
                settings.DOKU_SNAP_CLIENT_SECRET_INBOUND,
                relative_url,
            )
            if not is_authenticated:
                response_data = {
                    'responseCode': SnapPaymentNotificationResponseCodeAndMessage.UNAUTHORIZED_SIGNATURE.code,
                    'responseMessage': (
                        SnapPaymentNotificationResponseCodeAndMessage.UNAUTHORIZED_SIGNATURE.message
                    ),
                }
                self.kwargs['error_message'] = response_data['responseMessage']
                return JsonResponse(status=HTTP_401_UNAUTHORIZED, data=response_data)

            serializer = DOKUPaymentNotificationSerializer(data=request.data)
            if not serializer.is_valid():
                key = list(serializer.errors.items())[0][0]
                errors = list(serializer.errors.items())[0][1][0]
                if errors in ErrorDetail.mandatory_field_errors():
                    response_data[
                        'responseCode'
                    ] = SnapPaymentNotificationResponseCodeAndMessage.INVALID_MANDATORY_FIELD.code
                    response_data['responseMessage'] = "{} {}".format(
                        SnapPaymentNotificationResponseCodeAndMessage.INVALID_MANDATORY_FIELD.message,
                        key,
                    )
                else:
                    response_data[
                        'responseCode'
                    ] = SnapPaymentNotificationResponseCodeAndMessage.INVALID_FIELD_FORMAT.code
                    response_data['responseMessage'] = "{} {}".format(
                        SnapPaymentNotificationResponseCodeAndMessage.INVALID_FIELD_FORMAT.message,
                        key,
                    )
                    if key == 'paidAmount' and errors == 'Amount':
                        response_data[
                            'responseMessage'
                        ] = SnapPaymentNotificationResponseCodeAndMessage.INVALID_AMOUNT.message
                        response_data[
                            'responseCode'
                        ] = SnapPaymentNotificationResponseCodeAndMessage.INVALID_AMOUNT.code
                self.kwargs['error_message'] = response_data['responseMessage']
                return JsonResponse(status=HTTP_400_BAD_REQUEST, data=response_data)
            external_id = request.META.get('HTTP_X_EXTERNAL_ID')

            if not external_id:
                response_data[
                    'responseCode'
                ] = SnapPaymentNotificationResponseCodeAndMessage.INVALID_MANDATORY_FIELD.code
                response_data['responseMessage'] = "{} X-EXTERNAL-ID".format(
                    SnapPaymentNotificationResponseCodeAndMessage.INVALID_MANDATORY_FIELD.message
                )
                self.kwargs['error_message'] = response_data.get('responseMessage')
                return JsonResponse(status=HTTP_400_BAD_REQUEST, data=response_data)
            key = '{}_snap:external_id:{}'.format(SnapVendorChoices.DOKU, external_id)
            redis_client = get_redis_client()
            raw_value = redis_client.get(key)
            if raw_value:
                response_data[
                    'responseCode'
                ] = SnapPaymentNotificationResponseCodeAndMessage.EXTERNAL_ID_CONFLICT.code
                response_data[
                    'responseMessage'
                ] = SnapPaymentNotificationResponseCodeAndMessage.EXTERNAL_ID_CONFLICT.message
                self.kwargs['error_message'] = response_data.get('responseMessage')
                return JsonResponse(status=HTTP_409_CONFLICT, data=response_data)
            virtual_account = data.get('virtualAccountNo', '').strip()
            query_filter = {'virtual_account': virtual_account}
            response_pii_lookup = pii_lookup(virtual_account)
            if response_pii_lookup:
                query_filter = {'virtual_account_tokenized__in': response_pii_lookup}
            payment_method = PaymentMethod.objects.filter(**query_filter).last()

            if not payment_method:
                self.kwargs['error_message'] = 'virtual account {} not found'.format(
                    virtual_account
                )
                response_data[
                    'responseCode'
                ] = SnapPaymentNotificationResponseCodeAndMessage.VA_NOT_FOUND.code
                response_data[
                    'responseMessage'
                ] = SnapPaymentNotificationResponseCodeAndMessage.VA_NOT_FOUND.message
                return JsonResponse(status=HTTP_404_NOT_FOUND, data=response_data)

            account = payment_method.customer.account_set.last()
            account_payment = None
            if account:
                account_payment = account.get_oldest_unpaid_account_payment()
                if not account_payment:
                    self.kwargs['error_message'] = 'virtual account doesnt have the bill'
                    response_data[
                        'responseCode'
                    ] = SnapPaymentNotificationResponseCodeAndMessage.PAID_BILL.code
                    response_data[
                        'responseMessage'
                    ] = SnapPaymentNotificationResponseCodeAndMessage.PAID_BILL.message
                    return JsonResponse(status=HTTP_404_NOT_FOUND, data=response_data)
            payment_request_id = data.get('paymentRequestId', '')
            payback_transaction = PaybackTransaction.objects.filter(
                payment_method=payment_method, transaction_id=payment_request_id
            ).last()

            if not payback_transaction:
                self.kwargs['error_message'] = 'payback transaction not found'
                response_data[
                    'responseCode'
                ] = SnapPaymentNotificationResponseCodeAndMessage.VA_NOT_FOUND.code
                response_data[
                    'responseMessage'
                ] = SnapPaymentNotificationResponseCodeAndMessage.VA_NOT_FOUND.message
                return JsonResponse(status=HTTP_404_NOT_FOUND, data=response_data)
            elif payback_transaction.is_processed:
                self.kwargs['error_message'] = 'payback transaction has already been processed'
                response_data[
                    'responseCode'
                ] = SnapPaymentNotificationResponseCodeAndMessage.PAID_BILL.code
                response_data[
                    'responseMessage'
                ] = SnapPaymentNotificationResponseCodeAndMessage.PAID_BILL.message
                return JsonResponse(status=HTTP_404_NOT_FOUND, data=response_data)

            self.kwargs['customer_id'] = (
                payback_transaction.customer.id if payback_transaction.customer else None
            )
            self.kwargs['loan_id'] = (
                payback_transaction.loan.id if payback_transaction.loan else None
            )
            self.kwargs['payback_transaction_id'] = payback_transaction.id
            self.kwargs['account_payment_id'] = account_payment.id if account_payment else None

            with transaction.atomic():
                payback_transaction = PaybackTransaction.objects.select_for_update().get(
                    pk=payback_transaction.id
                )
                loan = get_active_loan(payback_transaction.payment_method)
                payment = get_oldest_payment_due(loan)
                note = 'payment with doku'
                transaction_date = data.get('trxDateTime')

                if transaction_date:
                    transaction_date = datetime.strptime(transaction_date, '%Y-%m-%dT%H:%M:%S%z')
                else:
                    transaction_date = timezone.localtime(timezone.now())

                payback_transaction.update_safely(
                    amount=float(data['paidAmount']['value']),
                    transaction_date=transaction_date,
                    payment=payment,
                    loan=loan,
                )
                response_data['virtualAccountData']['paidAmount'] = data['paidAmount']
                response_data['virtualAccountData']['paymentRequestId'] = data['paymentRequestId']
                response_data[
                    'responseCode'
                ] = SnapPaymentNotificationResponseCodeAndMessage.SUCCESS.code
                response_data[
                    'responseMessage'
                ] = SnapPaymentNotificationResponseCodeAndMessage.SUCCESS.message
                account_payment = payback_transaction.account.get_oldest_unpaid_account_payment()
                j1_refinancing_activation(
                    payback_transaction, account_payment, payback_transaction.transaction_date
                )
                process_j1_waiver_before_payment(
                    account_payment, payback_transaction.amount, transaction_date
                )
                payment_processed = process_repayment_trx(payback_transaction, note=note)

            if payment_processed:
                update_moengage_for_payment_received_task.delay(payment_processed.id)
                return JsonResponse(status=HTTP_200_OK, data=response_data)
        except Exception as e:
            sentry.captureException()
            self.kwargs['error_message'] = str(e)
            response_data[
                'responseCode'
            ] = SnapPaymentNotificationResponseCodeAndMessage.GENERAL_ERROR.code
            response_data[
                'responseMessage'
            ] = SnapPaymentNotificationResponseCodeAndMessage.GENERAL_ERROR.message
            return JsonResponse(status=HTTP_500_INTERNAL_SERVER_ERROR, data=response_data)
