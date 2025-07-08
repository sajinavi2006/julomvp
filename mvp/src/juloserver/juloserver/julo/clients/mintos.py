from future import standard_library
standard_library.install_aliases()
from builtins import str
from builtins import object
import json
import logging
import requests
import urllib.request, urllib.parse, urllib.error
import os

from decimal import Decimal
from io import StringIO
from datetime import datetime, date
from dateutil import relativedelta
from django.db import models
from django.utils import timezone

from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import Loan

from juloserver.julocore.python2.utils import py2round

from juloserver.lenderinvestment.services import (mintos_response_logger,
                                                idr_to_eur,
                                                mintos_interest_rate,
                                                convert_all_to_uer,
                                                recalculate_rounding)
from juloserver.lenderinvestment.models import (SbMintosPaymentList,
                                                ExchangeRate,
                                                SbLenderLoanLedger,
                                                MintosPaymentSendin,
                                                MintosLoanListStatus)
from juloserver.lenderinvestment.constants import MintosExchangeScrape as scrape_const


logger = logging.getLogger(__name__)


class JuloMintosClient(object):
    """  Mintos Integration API """

    def __init__(self, base_url, token):
        self.base_url = base_url
        self.token = token

    def get_mintos_request_data(self, loan):
        application = loan.application
        payments = loan.payment_set
        last_payment = payments.last()
        lender_loan_ledgers = SbLenderLoanLedger.objects.filter(loan=loan).first()

        exchange_rate = ExchangeRate.objects.filter(currency=scrape_const.CURRENCY).last()
        interest_rate_percent = mintos_interest_rate()
        request_data = dict()
        today = timezone.now().date()
        age = relativedelta.relativedelta(today, application.dob).years

        # set payment data
        sb_payments = SbMintosPaymentList.objects.filter(loan_id=loan.id).values(
            'principal_amount', 'payment_schedule_number', 'due_date'
        )

        paid_count = payments.count() - sb_payments.count()
        schedule_type  = 'full'

        loan_amount = idr_to_eur(loan.loan_amount, exchange_rate)
        loan_disburse = idr_to_eur(loan.loan_disbursement_amount, exchange_rate)
        loan_assign_mintos = idr_to_eur(lender_loan_ledgers.osp, exchange_rate)
        request_data['loan'] = {
            'lender_id': application.application_xid,
            'country': 'ID',
            'lender_issue_date': loan.fund_transfer_ts.strftime('%Y-%m-%d'),
            'mintos_issue_date': today.strftime('%Y-%m-%d'),
            'final_payment_date': last_payment.due_date.strftime('%Y-%m-%d'),
            'prepaid_schedule_payments': paid_count,
            'loan_amount': loan_amount,
            'loan_amount_assigned_to_mintos': loan_assign_mintos,
            'undiscounted_principal': None,
            'interest_rate_percent': interest_rate_percent,
            'schedule_type': schedule_type,
            'purpose': None,
            'buyback': True,
            'advance_rate': None,
            'cession_contract_template': 'default',
            'currency': scrape_const.CURRENCY,
            'currency_exchange_rate': str(Decimal(exchange_rate.rate)),
            'assigned_origination_fee_share': None,
            'extendable': True
        }

        split_name = application.fullname.split(' ')

        request_data['client'] = {
            'id': application.application_xid,
            'name': ' '.join(split_name[:1]),
            'surname': ' '.join(split_name[1:]),
            'email': application.email,
            'gender': application.gender_mintos,
            'age': age,
            'liability': None,
            'dependents': application.dependent,
            'occupation': None,
            'legal_type': 1,
            'phone_number': application.mobile_phone_1,
            'address_street_actual': application.complete_addresses,
            'personal_identification': application.ktp
        }

        request_data['pledge'] = {
            'type': 'unsecured'
        }

        request_data['apr_calculation_data'] = {
            'net_issued_amount': loan_disburse,
            'first_agreement_date': loan.sphp_accepted_ts.strftime('%Y-%m-%d'),
            'actual_payment_schedule': list(),
        }

        request_data['documents'] = list()

        # convert all payment to eur
        payments_converted = convert_all_to_uer(sb_payments, ['principal_amount'], exchange_rate)

        # recalculate installment
        payments_recalculated = recalculate_rounding(loan_assign_mintos, payments_converted)

        payment_schedules = list()
        remaining_principal = loan_assign_mintos
        for sb_payment in payments_recalculated:
            interest_amount = sb_payment['principal_amount'] * (float(interest_rate_percent) / 100)
            payment_data = {
                'number': sb_payment['payment_schedule_number'],
                'date': sb_payment['due_date'].strftime('%Y-%m-%d'),
                'principal_amount': sb_payment['principal_amount'],
                'interest_amount': py2round(interest_amount, 2),
                'sum': py2round(sb_payment['principal_amount'] + interest_amount, 2),
                'total_remaining_principal': py2round(remaining_principal, 2)
            }
            remaining_principal -= sb_payment['principal_amount']

            payment_schedules.append(payment_data)

        request_data['payment_schedule']  = sorted(payment_schedules, key = lambda i: i['number'])

        actual_payments = list()
        for actual_payment in payments.all():
            payment_actual = {
                'date': actual_payment.due_date.strftime('%Y-%m-%d'),
                'amount': idr_to_eur(actual_payment.installment_principal + actual_payment.installment_interest, exchange_rate),
            }

            actual_payments.append(payment_actual)
        request_data['apr_calculation_data']['actual_payment_schedule'] = sorted(actual_payments, key = lambda i: i['date'])

        if loan.payment_set.count() == 1:
            request_data['pledge'] = {
                'type': 'payday'
            }

        return {'data': request_data}

    def get_mintos_request_payment_data(self, mintos_loan_id, sb_payment_sendin):
        sendin_data = {}
        request_data = {}

        mintos_loan = MintosLoanListStatus.objects.get_or_none(mintos_loan_id=mintos_loan_id)
        if not mintos_loan:
            logger.info({
                'action': 'payment_sendin_tasks',
                'loan_id': mintos_loan_id,
                'message': "couldn't find mintos loan"
            })
            return request_data, sendin_data

        mintos_data = self.get_loans(mintos_loan_id)
        if mintos_data and 'data' in mintos_data:
            payment_summary = mintos_data['data']['payment_summary']
            payment_schedule = mintos_data['data']['payment_schedule']
            penalty_amount = float(payment_summary['next_payment_delayed_interest']) + float(payment_summary['next_payment_late_payment_fee'])
            loan = mintos_data['data']['loan']
            if loan['status'] == 'finished':
                return request_data, sendin_data

            for schedule in payment_schedule:
                if schedule['number'] == sb_payment_sendin.payment_schedule_number:
                    sb_principal = idr_to_eur(sb_payment_sendin.principal_amount, mintos_loan.exchange_rate)
                    schedule_principal = float(schedule['principal_amount'])
                    remain_principal = schedule_principal - sb_principal
                    principal_amount = sb_principal if remain_principal >= 1 else schedule_principal

                    # check for partial payment
                    is_partial_payment = MintosPaymentSendin.objects.filter(
                        loan_id=sb_payment_sendin.loan_id,
                        payment_schedule_number=sb_payment_sendin.payment_schedule_number)

                    if is_partial_payment:
                        schedule['interest_amount'] = "{:.2f}".format(0) + 14 * '0'
                        payment_list = is_partial_payment.values_list('principal_amount', flat=True)
                        payment_paid = sum([float(i) for i in payment_list])
                        total_paid = payment_paid + sb_principal
                        diff_paid = schedule_principal - total_paid
                        principal_amount = py2round(sb_principal + diff_paid, 2) if diff_paid < 1 else sb_principal

                    sendin_data = {
                        "application_xid": sb_payment_sendin.application_xid,
                        "loan_id": sb_payment_sendin.loan_id,
                        "payment_id": sb_payment_sendin.payment_id,
                        "payment_date": sb_payment_sendin.payment_date,
                        "payment_schedule_number": sb_payment_sendin.payment_schedule_number,
                        "principal_amount": "{:.2f}".format(principal_amount) + 14 * '0',
                        "interest_amount": schedule['interest_amount'],
                        "total_amount": schedule['sum'],
                        "remaining_principal": schedule['total_remaining_principal'],
                        "penalty_amount": "{:.2f}".format(penalty_amount) + 14 * '0',
                    }

                    request_data = {
                        'data': {
                            'number': sendin_data['payment_schedule_number'],
                            'date': sendin_data['payment_date'].strftime('%Y-%m-%d'),
                            'principal_amount': sendin_data['principal_amount'],
                            'interest_amount': sendin_data['interest_amount'],
                            'total_remaining_principal': sendin_data['remaining_principal'],
                            'penalty_amount': sendin_data['penalty_amount']
                        }
                    }
                    break

            return request_data, sendin_data

    def send_request(self, request_path, request_type, data=None, params=None, application=None):
        """
        Send API request to Mintos Client
        :param request_path: mintos's route url
        :param  request_type: request type [get, post]
        :param data: Dictionary contains data using for requests body usually using by [POST]
        :param params: Dictionary contains data using for requests query params usually using by [GET]
        :return: object response.json
        """
        sentry_client = get_julo_sentry_client()

        api_type = "{}-{}".format(request_type, request_path)

        request_params = dict(
            url=self.base_url + self.token + '/' + request_path,
            headers={'Content-Type': 'application/json'}
        )

        for key in ('data', 'params',):
            if eval(key):
                request_params[key] = json.dumps(eval(key)) if key == 'data' else eval(key)

        try:
            requests_ = eval('requests.%s' % request_type)
            response = requests_(**request_params)
            response.raise_for_status()
            return_response = response.json()
            error = None
        except Exception as error:
            sentry_client.captureException()
            response = error.response
            return_response = response.json() if hasattr(response , 'json') else None

        mintos_response_logger(api_type, request_params, response, error, application)

        return return_response

    def loan_sendin(self, loan_obj):
        request_type = 'post'
        path = 'loans'
        request_data = self.get_mintos_request_data(loan_obj)

        response = self.send_request(
            path, request_type, request_data, application=loan_obj.application
        )

        return response

    def loan_sendin_bulk(self, loans_obj):
        request_type = 'post'
        path = 'loans'
        request_data = list()

        for loan in loans_obj:
            data = self.get_mintos_request_data(loan)
            request_data.append(data)

        response = self.send_request(
            path, request_type, request_data
        )

        return response

    def get_loans(self, mintos_loan_id):
        request_type = 'get'
        path = 'loans'

        if mintos_loan_id:
            path += '/{}'.format(mintos_loan_id)

        response = self.send_request(
            path, request_type
        )

        return response

    def payment_sendin(self, mintos_loan_id, sb_payment_sendin, loan_obj):
        response = {}
        request_type = 'post'
        path = 'loans/{}/payments'.format(mintos_loan_id)

        request_data, sendin_data = self.get_mintos_request_payment_data(mintos_loan_id, sb_payment_sendin)

        if request_data:
            response = self.send_request(
                path, request_type, request_data, application=loan_obj.application
            )

        return response, sendin_data

    def rebuy_loan(self, mintos_loan_id, purpose, loan_obj):
        request_type = 'post'
        path = 'rebuy/{}'.format(mintos_loan_id)

        request_data = {
            'data': {
                'purpose': purpose
            }
        }

        response = self.send_request(
            path, request_type, request_data, application=loan_obj.application
        )

        return response