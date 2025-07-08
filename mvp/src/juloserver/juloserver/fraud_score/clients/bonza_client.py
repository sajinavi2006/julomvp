from builtins import object

from django.db import transaction
from django.utils import timezone
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.account.constants import AccountConstant
from juloserver.fraud_score.constants import BonzaConstants
import logging
from juloserver.fraud_score.models import (
    BonzaScoringResult, BonzaStoringResult, TransactionFraudModelAccount)

from rest_framework.renderers import JSONRenderer
import requests
from juloserver.loan.services.loan_related import update_loan_status_and_loan_history
from juloserver.account.services.account_related import process_change_account_status
from juloserver.fraud_score.serializers import (
    BonzaApplicationAPISerializer,
    BonzaLoanPaymentAPISerializer,
    BonzaLoanTransactionAPISerializer,
    BonzaLoanTransactionScoringAPISerializer,
    BonzaInhousePredictionAPISerializer)

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


class BonzaClient(object):
    """Client SDK for interacting with Bonza"""

    def __init__(self, api_key, api_urls, timeout_params=None):
        self.api_key = api_key
        self.api_urls = api_urls
        self.headers = {
            'Content-Type': 'application/json',
            'X-API-Key': self.api_key}
        self.inhouse_headers = {
            'Content-Type': 'application/json',
            'x-access-token': self.api_key}
        self.stored_scoring_result = None
        self.timeout_params = timeout_params if timeout_params else BonzaConstants.API_TIMEOUTS
        self.reject_reason = None
        self.transaction_fraud_model_account = None

    def log_bonza_api_calls(self, method, model_obj, status=None, response=None, exception=None,
                            storing=True):
        logger.info({
            'bonza_method': method,
            'status': str(status),
            'exception': str(exception),
            'object_id': str(model_obj.id)})
        if storing:
            BonzaStoringResult.objects.create(
                method_name=method,
                object_id=model_obj.id,
                status=status,
                api_response=exception if exception else response)

    def store_scoring_results(self, loan, status, response=None, timeout_on=True):
        data = {
            'loan_id': loan.id,
            'customer_id': loan.customer.id,
            'status': str(status) + '-async-rehit' if not timeout_on else str(status)
        }
        if response and status == 200:
            data['score'] = response.get('score')
            data['request_id'] = response.get('request_id')
        if response and status in (400, 422):
            data['api_response'] = response.get('error')
        self.stored_scoring_result = BonzaScoringResult.objects.create(**data)

    def store_scoring_results_inhouse(self, loan, status, response=None, timeout_on=True):
        data = {
            'loan_id': loan.id,
            'customer_id': loan.customer.id,
            'status': str(status) + '-async-rehit' if not timeout_on else str(status)
        }
        now = timezone.localtime(timezone.now())
        self.transaction_fraud_model_account = TransactionFraudModelAccount.objects.filter(
            account=loan.account, start_expire_date__lt=now, end_expire_date__gte=now).last()
        if self.transaction_fraud_model_account:
            data['transaction_fraud_model_account_id'] = self.transaction_fraud_model_account.id
            data['on_reverified_period'] = True
        if response and status == 200:
            data['score'] = response.get('score')
            data['version'] = response.get('version')
        if loan.account.loan_set.count() == 1:
            data['is_first_loan'] = True
        self.stored_scoring_result = BonzaScoringResult.objects.create(**data)

    def get_api_response(self, api_name, data, timeout_on=True):
        url = self.api_urls.get(api_name, None)
        json_data = JSONRenderer().render(data).decode('ascii')
        if not url:
            return None, None
        timeout = None
        if timeout_on is True:
            timeout = BonzaConstants.API_TIMEOUTS.get(api_name, 5)
        try:
            for retry in range(3):
                response = requests.post(url, data=json_data, headers=self.headers,
                                         timeout=timeout)
                if response.status_code in (200, 400, 422):
                    break
            if response.status_code != 200 and api_name != 'loan_scoring':
                return None, response.status_code
            results = response.json()
            return results, response.status_code
        except requests.exceptions.Timeout:
            return None, 'API timeout'

    def get_api_response_inhouse(self, data, timeout_on=True, storing=False):
        url = self.api_urls.get('inhouse_loan_scoring', None)
        if storing:
            url = url.replace('predict', 'storing')
        json_data = JSONRenderer().render(data).decode('ascii')
        if not url:
            return None, None
        timeout = None
        if timeout_on is True:
            if storing:
                timeout = self.timeout_params.get(
                    'inhouse_loan_storing',
                    BonzaConstants.API_TIMEOUTS.get('inhouse_loan_storing'))
            else:
                timeout = self.timeout_params.get(
                    'inhouse_loan_scoring',
                    BonzaConstants.API_TIMEOUTS.get('inhouse_loan_scoring'))
        try:
            for retry in range(3):
                response = requests.post(url, data=json_data, headers=self.inhouse_headers,
                                         timeout=timeout)
                if response.status_code == 200:
                    break
            if response.status_code != 200:
                return None, response.status_code
            results = response.json()
            return results, response.status_code
        except requests.exceptions.Timeout:
            return None, 'API timeout'

    def post_application_data(self, application):
        try:
            request_constructor = BonzaRequestConstructor(application=application)
            data = request_constructor.construct_application_request_data()
            response, status = self.get_api_response('application', data=data)
            self.log_bonza_api_calls('post_application_data', application, status=status,
                                     response=response)
            return response
        except Exception as exc:
            self.log_bonza_api_calls('post_application_data', application, exception=exc)

    def post_loan_transaction_data(self, loan):
        try:
            request_constructor = BonzaRequestConstructor(loan=loan)
            data = request_constructor.construct_loan_transaction_request_data()
            response, status = self.get_api_response('loan_transaction', data=data)
            self.log_bonza_api_calls('post_loan_transaction_data', loan, status=status,
                                     response=response)
            return response
        except Exception as exc:
            self.log_bonza_api_calls('post_loan_transaction_data', loan, exception=exc)

    def post_loan_payment_data(self, payment):
        try:
            request_constructor = BonzaRequestConstructor(payment=payment)
            data = request_constructor.construct_loan_payment_request_data()
            response, status = self.get_api_response('loan_payment', data=data)
            self.log_bonza_api_calls('post_loan_payment_data', payment, status=status,
                                     response=response)
            return response
        except Exception as exc:
            self.log_bonza_api_calls('post_loan_payment_data', payment, exception=exc)

    def get_loan_transaction_scoring(self, loan, timeout_on=True):
        from juloserver.fraud_score.tasks import hit_bonza_loan_scoring_asynchronous
        try:
            request_constructor = BonzaRequestConstructor(loan=loan)
            data = request_constructor.construct_loan_transaction_scoring_request_data()
            response, status = self.get_api_response(
                'loan_scoring', data=data, timeout_on=timeout_on)
            if response or status:
                self.store_scoring_results(loan, status, response, timeout_on=timeout_on)
            self.log_bonza_api_calls('get_loan_transaction_scoring', loan, status=status,
                                     storing=False)
            if status == 'API timeout' and timeout_on is True:
                hit_bonza_loan_scoring_asynchronous.apply_async((loan.id,), countdown=30)
            return response if status == 200 else None
        except Exception as exc:
            self.log_bonza_api_calls('get_loan_transaction_scoring', loan, exception=exc,
                                     storing=False)

    def get_loan_transaction_scoring_inhouse(self, loan, timeout_on=True):
        from juloserver.fraud_score.tasks import hit_bonza_loan_scoring_asynchronous
        try:
            application = None
            if loan.account:
                application = loan.account.last_application
            if not application:
                application = loan.customer.application_set.last()
            request_constructor = BonzaRequestConstructor(loan=loan)
            data = request_constructor.construct_loan_inhouse_prediction_request_data()
            response, status = self.get_api_response_inhouse(
                data=data, timeout_on=timeout_on)
            if response or status:
                self.store_scoring_results_inhouse(loan, status, response, timeout_on=timeout_on)
            self.log_bonza_api_calls('get_loan_transaction_scoring_inhouse', loan, status=status,
                                     storing=False)
            if status == 'API timeout' and timeout_on is True:
                hit_bonza_loan_scoring_asynchronous.apply_async((loan.id, True), countdown=30)
            return response if status == 200 else None
        except Exception as exc:
            sentry_client.captureException()
            self.log_bonza_api_calls('get_loan_transaction_scoring_inhouse', loan, exception=exc,
                                     storing=False)

    def hit_inhouse_storing_api(self, loan):
        try:
            data = {"loan_id": str(loan.id)}
            response, status = self.get_api_response_inhouse(data=data, storing=True)
            self.log_bonza_api_calls('hit_inhouse_storing_api', loan, status=status,
                                     response=response)
            return response
        except Exception as exc:
            sentry_client.captureException()
            self.log_bonza_api_calls('hit_inhouse_storing_api', loan, exception=exc)

    def validate_loan(self, loan, hard_reject_threshold, soft_reject_threshold):
        eligible_score = True
        scoring_response = self.get_loan_transaction_scoring_inhouse(loan)

        # BONZA REVERSE EXPERIMENT
        from juloserver.fraud_score.services import account_under_bonza_experiment_old
        if account_under_bonza_experiment_old(loan.account_id) is True:
            if self.stored_scoring_result:
                self.stored_scoring_result.update_safely(holdout=True)
            return True

        if self.transaction_fraud_model_account:
            return True

        if self.stored_scoring_result and self.stored_scoring_result.is_first_loan:
            return True

        if scoring_response:
            score = scoring_response.get('score')
            if score >= hard_reject_threshold:
                self.reject_reason, eligible_score = BonzaConstants.HARD_REJECT_REASON, False
            elif score >= soft_reject_threshold and score < hard_reject_threshold:
                self.reject_reason, eligible_score = BonzaConstants.SOFT_REJECT_REASON, False
        if eligible_score is False:
            with transaction.atomic():
                if self.reject_reason == BonzaConstants.HARD_REJECT_REASON:
                    update_loan_status_and_loan_history(
                        loan_id=loan.id,
                        new_status_code=LoanStatusCodes.GRAB_AUTH_FAILED,
                        change_reason="Transaction Gotham Hard Reject")
                    process_change_account_status(
                        loan.account,
                        new_status_code=AccountConstant.STATUS_CODE.terminated,
                        change_reason="Transaction Gotham Hard Reject")
                elif self.reject_reason == BonzaConstants.SOFT_REJECT_REASON:
                    update_loan_status_and_loan_history(
                        loan_id=loan.id,
                        new_status_code=LoanStatusCodes.GRAB_AUTH_FAILED,
                        change_reason="Transaction Gotham Soft Reject")
                    process_change_account_status(
                        loan.account,
                        new_status_code=AccountConstant.STATUS_CODE.fraud_soft_reject,
                        change_reason="Transaction Gotham Soft Reject")
        return eligible_score


class BonzaRequestConstructor(object):
    def __init__(self, application=None, loan=None, payment=None):
        self.application = application
        self.loan = loan
        self.payment = payment

    def construct_application_request_data(self):
        serializer = BonzaApplicationAPISerializer(self.application)
        return serializer.data

    def construct_loan_transaction_request_data(self):
        serializer = BonzaLoanTransactionAPISerializer(self.loan)
        return serializer.data

    def construct_loan_payment_request_data(self):
        serializer = BonzaLoanPaymentAPISerializer(self.payment)
        return serializer.data

    def construct_loan_transaction_scoring_request_data(self):
        serializer = BonzaLoanTransactionScoringAPISerializer(self.loan)
        return serializer.data

    def construct_loan_inhouse_prediction_request_data(self):
        serializer = BonzaInhousePredictionAPISerializer(self.loan)
        return serializer.data
