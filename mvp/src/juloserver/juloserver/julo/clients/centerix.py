from builtins import str
from builtins import object
import json
import logging

import requests
from django.utils import timezone

from datetime import datetime, timedelta
from dateutil.parser import parse
from juloserver.julo.models import (Payment,
                                    Skiptrace,
                                    SkiptraceResultChoice,
                                    PaymentMethod)
from juloserver.paylater.models import Statement
from juloserver.julo.models import (Customer,
                                    CenterixCallbackResults,
                                    SkiptraceHistory,
                                    SkiptraceHistoryCentereix,
                                    PaymentNote,
                                    Application,
                                    AgentProductivity)
from juloserver.julo.utils import format_e164_indo_phone_number
from juloserver.julo.exceptions import JuloException
from juloserver.minisquad.constants import CenterixCallResult
from django.contrib.auth.models import User
from cuser.middleware import CuserMiddleware
from django.db import transaction

logger = logging.getLogger(__name__)


class JuloCenterixClient(object):
    def __init__(self, user_id, pwd, base_url):
        self.user_id = user_id
        self.pwd = pwd
        self.base_url = base_url

    def upload_centerix_data(self, campaign_code, payment_params):
        params = {
            'CampaignCode': campaign_code,
            'CredUser': self.user_id,
            'CredPassword': self.pwd,
            'Datas': payment_params
        }

        url = self.base_url + '/createdataupload'
        logger.info({
            "campaign_code": campaign_code,
            "total_count": len(payment_params),
            "url": url,
            "status": "uploading"
        })
        response = requests.post(url, json=params)
        response_data = response.json()
        if response_data['Result'] != 'Success':
            exception_message = {
                "error_message": response_data['ErrMessage'],
                "campaign_code": params["CampaignCode"],
                "url": url
            }
            raise JuloException(exception_message)

        return "Successfully sent data to Centerix for campaign_code: %s" % campaign_code

    def upload_centerix_payment_data(self, payment_id, payment_method_id):

        payment = Payment.objects.get_or_none(pk=payment_id)
        if not payment:
            raise JuloException("payment doesn't exist: %s" % payment_id)

        date = datetime.strftime(payment.paid_date, "%Y-%m-%d")
        loan = payment.loan
        application = loan.application
        time = ' 00:00:00'
        payment_method = PaymentMethod.objects.get_or_none(pk=payment_method_id)

        if payment_method:
            pay_method = payment_method.payment_method_name
        else:
            pay_method = ''

        params = {
            "CredUser": self.user_id,
            "CredPassword": self.pwd,
            "Payments": [{
                "CUSTOMER_ID": payment.loan.application.customer.id,
                "APPLICATION_ID": application.id,
                "PAYMENT_AMOUNT": payment.paid_amount,
                "PAYMENT_DATE": date + str(time),
                "PAYMENT_METHOD": pay_method,
                "PAYMENT_ID": payment_id,
                "OUTSTANDING_AMOUNT": payment.due_amount
            }]
        }
        url = self.base_url + '/updatepayments'
        logger.info({
            "payment_id": payment_id,
            "url": url,
            "status": "uploading"
        })
        response = requests.post(url, json=params)
        response_data = response.json()
        if response_data['Result'] != 'Success':
            exception_message = {
                "error_message": response_data['ErrMessage'],
                "url": url
            }
            raise JuloException(exception_message)

        return "Successfully updated to Centerix payment_id: %s" % payment_id

    def upload_centerix_payment_bl_data(self, statement_id, payment_method):
        statement = Statement.objects.get_or_none(pk=statement_id)
        if not statement:
            raise JuloException("statement doesn't exist: %s" % statement_id)

        date = datetime.strftime(statement.statement_paid_date, "%Y-%m-%d")
        time = ' 00:00:00'
        pay_method = ''
        params = {
            "CredUser": self.user_id,
            "CredPassword": self.pwd,
            "Payments": [{
                "CUSTOMER_ID": statement.customer_credit_limit.customer.id,
                "APPLICATION_ID": '',
                "PAYMENT_AMOUNT": statement.statement_paid_amount,
                "PAYMENT_DATE": date + str(time),
                "PAYMENT_METHOD": pay_method,
                "PAYMENT_ID": statement_id,
                "OTSTANDING_AMOUNT": statement.statement_due_amount
            }]
        }
        url = self.base_url + '/updatepayments'
        logger.info({
            "statement_id": statement_id,
            "url": url,
            "status": "uploading"
        })

        response = requests.post(url, json=params)
        response_data = response.json()
        if response_data['Result'] != 'Success':
            exception_message = {
                "error_message": response_data['ErrMessage'],
                "url": url
            }
            raise JuloException(exception_message)

        return "Successfully updated to Centerix BL statement: %s" % statement_id

    def upload_skiptrace_data(self, data, call_result, customer_id, is_payment):
        """
        upload data to centerix for the skiptrace from crm
        """
        if data['start_ts']:
            start_ts = data['start_ts'].strftime("%m/%d/%Y")
            time_ts = data['start_ts'].strftime("%H:%M:%S")
        else:
            start_ts = ''
            time_ts = ''

        payment_id = '' if is_payment == 0 else data['payment']
        if data['skip_ptp_date']:
            date_obj = datetime.strptime(data['skip_ptp_date'], '%d-%m-%Y').date()
            skip_ptp_date = datetime.strftime(date_obj, '%m/%d/%Y')
        else:
            skip_ptp_date = ''

        skiptrace = Skiptrace.objects.get_or_none(id=data['skiptrace'])
        if not skiptrace:
            raise JuloException("skiptrace doesn't exist: %s" % data['skiptrace'])

        params = {
            "CredUser": self.user_id,
            "CredPassword": self.pwd,
            "Datas": [{
                "CUSTOMER_ID": customer_id,
                "APPLICATION_ID": data['application'],
                "PAYMENT_ID": payment_id,
                "NOTES": data['skip_note'],
                "PHONE": skiptrace.phone_number.national_number,
                "RESULT": data['level2'],
                "SUBRESULT": data['level3'],
                "STATUSCALL": data['level1'],
                "PTPDATE": skip_ptp_date,
                "PTP": data['skip_ptp_amount'],
                "CALLBACKTIME":data['skip_time'],
                "AGENTNAME": data['agent_name'],
                "CAMPAIGN": "JULO",
                "DATE": start_ts,
                "TIME": time_ts,
                "TYPEOF": skiptrace.contact_source,
                "BL_CREDITLIMIT": "0"
            }]
        }

        url = self.base_url + '/inserthistorycall'
        response = requests.post(url, json=params)
        response_data = response.json()
        if response_data['Result'] != 'Success':
            exception_message = {
                "error_message": response_data['ErrMessage'],
                "url": url
            }
            raise JuloException(exception_message)

        return "Successfully updated to Centerix BL skiptrace data: %s" % data['skiptrace']

    def update_centerix_callback_log(self, error_msg, response, data):
        application_id = data['Application_ID']
        payment_id = data['Payment_ID']
        centerix_campaign = data['Centerix_Campaign']
        call_time = data['CallTime']
        start_time = datetime.strptime(call_time, '%m/%d/%Y %H:%M:%S')
        disconnect_time = data['DisconnectTime']
        end_time = datetime.strptime(disconnect_time, '%m/%d/%Y %H:%M:%S')
        parameters = json.dumps(data)
        CenterixCallbackResults.objects.create(start_ts=start_time,
                                               end_ts=end_time,
                                               application_id=application_id,
                                               payment_id=payment_id,
                                               error_msg=error_msg,
                                               result=response,
                                               campaign_code=centerix_campaign,
                                               parameters=parameters)

    def update_centerix_callback_log_system_call_result(
            self, error_msg, response, data, application, start_ts, payment_id):
        CenterixCallbackResults.objects.create(
            start_ts=start_ts,
            application_id=application.id, payment_id=payment_id,
            error_msg=error_msg,
            result=response,
            campaign_code=data.get('campaign_name'),
            parameters=json.dumps(data)
        )

    def get_call_status_details_from_centerix(self, start_date, end_date):
        url = self.base_url + '/gethistorycall'
        start_date = datetime.strftime(start_date, '%Y/%m/%d')
        end_date = datetime.strftime(end_date, '%Y/%m/%d')
        params = {
            "CredUser": self.user_id,
            "CredPassword": self.pwd,
            "From": start_date,
            "To": end_date
        }
        response = requests.post(url, json=params)
        response_data = response.json()
        if not response_data['Result']:
            logger.warning({
                'status': 'no_data',
                'start_date': start_date,
                'end_date': end_date,
                'url': url
            })
            return

        for result in response_data['Result']:
            application_id = result['Application_ID']
            payment_id = result['Payment_ID']
            customer_id = result['Customer_ID']
            phone = result['ContactPhone']
            centerix_campaign = result['Centerix_Campaign']
            call_time = result['CallTime']
            start_time = datetime.strptime(call_time, '%m/%d/%Y %H:%M:%S')
            disconnect_time = result['DisconnectTime']
            end_time = datetime.strptime(disconnect_time, '%m/%d/%Y %H:%M:%S')
            source = result['TYPEOF']
            call_status = result['CallStatus']
            call_sub_status = result['CallSubStatus']
            agent_name = result['AgentCode']
            if result['CallStatus'] is None or not result['CallStatus']:
                call_status = 'NULL'

            if result['CallSubStatus'] is None or not result['CallSubStatus']:
                call_substatus = ''
                call_sub_status = 'NULL'
            else:
                call_substatus = call_sub_status.lower().strip()

            notes = result['Notes']
            if call_substatus not in CenterixCallResult.SYSTEM_GENERATED_SUB_STATUS or \
                    (call_substatus == CenterixCallResult.SUB_STATUS_AM_OLD_NAME and agent_name):
                response = 'Failure'
                error_msg = 'Invalid SUBRESULT - {}'.format(result['CallSubStatus'])
                self.update_centerix_callback_log(error_msg, response, result)
                continue

            if call_substatus == CenterixCallResult.SUB_STATUS_AM_OLD_NAME:
                call_substatus = CenterixCallResult.SUB_STATUS_AM_NEW_NAME.lower()
                call_sub_status = CenterixCallResult.SUB_STATUS_AM_NEW_NAME

            if call_substatus in CenterixCallResult.SYSTEM_GENERATED_NC_STATUS:
                call_status = CenterixCallResult.NC_STATUS_GROUP

            if call_substatus in CenterixCallResult.SYSTEM_GENERATED_NULL_STATUS:
                call_status = CenterixCallResult.NULL_STATUS_GROUP

            if call_substatus in CenterixCallResult.SYSTEM_GENERATED_DEFAULT_STATUS:
                call_status = CenterixCallResult.DEFAULT_STATUS_GROUP

            skip_result_choice = SkiptraceResultChoice.objects.filter(name__iexact=call_sub_status).last()
            if not skip_result_choice:
                response = 'Failure'
                error_msg = 'Invalid SUBRESULT - {}'.format(call_substatus)
                self.update_centerix_callback_log(error_msg, response, result)
                continue

            payment = Payment.objects.get_or_none(pk=payment_id)
            if not payment:
                response = 'Failure'
                error_msg = 'Not found payment for application - {}'.format(application_id)
                self.update_centerix_callback_log(error_msg, response, result)
                continue

            if not customer_id:
                response = 'Failure'
                error_msg = 'Invalid customer details - {}'.format(customer_id)
                self.update_centerix_callback_log(error_msg, response, result)
                continue

            cust_obj = Customer.objects.get_or_none(pk=customer_id)
            if cust_obj is None:
                response = 'Failure'
                error_msg = 'Invalid customer details - {}'.format(customer_id)
                self.update_centerix_callback_log(error_msg, response, result)
                continue

            if agent_name:
                user_obj = User.objects.filter(username=agent_name.lower()).last()
                if user_obj is None:
                    response = 'Failure'
                    error_msg = 'Invalid agent details - {}'.format(agent_name)
                    self.update_centerix_callback_log(error_msg, response, result)
                    continue

                agent_name = user_obj.username
                CuserMiddleware.set_user(user_obj)
            else:
                user_obj = None

            skiptrace_result_id = skip_result_choice.id
            skip_history = SkiptraceHistory.objects.filter(
                payment_id=payment.id,
                loan_id=payment.loan.id,
                application_id=payment.loan.application.id,
                start_ts=start_time,
                call_result_id=skiptrace_result_id).last()
            if skip_history:
                continue

            skiptrace_obj = Skiptrace.objects.filter(
                phone_number=format_e164_indo_phone_number(phone),
                customer_id=customer_id).last()
            if not skiptrace_obj:
                skiptrace = Skiptrace.objects.create(
                    contact_source=source,
                    phone_number=format_e164_indo_phone_number(phone),
                    customer_id=customer_id)
                skiptrace_ids = skiptrace.id
            else:
                skiptrace_ids = skiptrace_obj.id

            if not skiptrace_ids:
                result = 'Failure'
                error_msg = 'Invalid Skiptrace ID'
                self.update_centerix_callback_log(error_msg, response, result)
                continue

            if notes:
                PaymentNote.objects.create(
                    note_text=notes,
                    payment=payment,
                    added_by_id=user_obj
                )

            SkiptraceHistory.objects.create(
                start_ts=start_time,
                end_ts=end_time,
                application_id=payment.loan.application.id,
                loan_id=payment.loan.id,
                agent_name=agent_name,
                agent_id=user_obj,
                call_result_id=skiptrace_result_id,
                skiptrace_id=skiptrace_ids,
                payment_id=payment.id,
                notes=call_sub_status,
                loan_status=payment.loan.loan_status.status_code,
                payment_status=payment.payment_status.status_code,
                application_status=payment.loan.application.status)
            SkiptraceHistoryCentereix.objects.create(
                start_ts=start_time,
                end_ts=end_time,
                application_id=payment.loan.application.id,
                loan_id=payment.loan.id,
                loan_status=payment.loan.loan_status.status_code,
                payment_status=payment.payment_status.status_code,
                agent_name=agent_name,
                application_status=payment.loan.application.status,
                contact_source=source,
                payment_id=payment.id,
                comments=notes,
                campaign_name=centerix_campaign,
                phone_number=format_e164_indo_phone_number(phone),
                status_group=call_status,
                status=call_sub_status)

            response = 'Success'
            error_msg = 'Details updated for application - {}'.format(application_id)
            self.update_centerix_callback_log(error_msg, response, result)

    def get_agent_productiviy_details_from_centerix(self, start_date, end_date):
        url = self.base_url + '/getProductivitySummary'
        start_date = datetime.strftime(start_date, '%Y/%m/%d')
        end_date = datetime.strftime(end_date, '%Y/%m/%d')
        params = {
            "CredUser": self.user_id,
            "CredPassword": self.pwd,
            "From": start_date,
            "To": end_date
        }
        results = requests.post(url, json=params)
        if not results:
            raise JuloException('Failed to retrieve data from centerix for agent productivity')

        results_data = results.json()
        if not results_data['Result']:
            logger.info({
                'status': (
                    'No data received from centrix regarding agent productivity '
                    'for the duration {} - {}'.format(start_date, end_date)
                )
            })
            return []

        return results_data['Result']


    def get_all_system_call_result_from_centerix(self):

        url = self.base_url + '/systemCallResult'

        now = timezone.localtime(timezone.now())
        centerix_callback_result = CenterixCallbackResults.objects.filter(result='Success').last()
        from_date = centerix_callback_result.cdate - timedelta(minutes=30)

        params = {
            'From': datetime.strftime(from_date, '%Y-%m-%d %H:%M:%S'),
            'To': datetime.strftime(now, '%Y-%m-%d %H:%M:%S'),
            'CredUser': self.user_id,
            'CredPassword': self.pwd
        }
        logger.info({
            'url': url,
            'from': params["From"],
            'to': params["To"],
            'status': "getting"
        })
        response = requests.post(url, json=params)
        if response.status_code != requests.codes.ok:
            response_body = response.text
            raise JuloException(
                "Failed hitting: %s status: %s" % (url, response.status_code))

        response_body = response.json()
        if response_body.get("ErrMessage"):
            raise JuloException(
                "Centerix API error: %s" % response_body.get("ErrMessage"))

        skip_traces = response_body.get('Result')
        logger.info({
            'url': url,
            'from': params["From"],
            'to': params["To"],
            'status': "received",
            'result_count': 0 if skip_traces is None else len(skip_traces)
        })

        for skip_trace in skip_traces:
            application = Application.objects.get(id=skip_trace.get('application_id'))
            try:
                loan = application.loan
                loan_status = loan.status
            except:
                loan = None
                loan_status = None

            start_ts = parse(skip_trace.get('interaction_time'))

            skip_result_choice = SkiptraceResultChoice.objects.filter(
                name__iexact=skip_trace.get('result_call')).last()

            payment_id = None
            if skip_trace.get('payment_id'):
                payment_id = skip_trace.get('payment_id')

            if not skip_result_choice:
                result_message = 'Failure'
                error_msg = 'Invalid Result Call - {}'.format(skip_trace.get('result_call'))
                self.update_centerix_callback_log_system_call_result(
                    error_msg, result_message, skip_trace, application, start_ts, payment_id
                )
                continue

            skip_history = SkiptraceHistory.objects.filter(
                payment_id=payment_id,
                loan=loan,
                application=application,
                start_ts=start_ts,
                call_result=skip_result_choice)
            if skip_history:
                continue

            phone = skip_trace.get('address')
            skiptrace = Skiptrace.objects.filter(
                phone_number=format_e164_indo_phone_number(phone),
                customer=application.customer).last()

            with transaction.atomic():

                if not skiptrace:
                    skiptrace = Skiptrace.objects.create(
                        phone_number=format_e164_indo_phone_number(phone),
                        customer=application.customer,
                        application=application)

                SkiptraceHistory.objects.create(
                    start_ts=start_ts,
                    application=application,
                    application_status=application.status,
                    loan=loan,
                    loan_status=loan_status,
                    payment_id=payment_id,
                    skiptrace=skiptrace,
                    call_result=skip_result_choice
                )

                call_status = None

                call_substatus = skip_trace.get('result_call')

                if call_substatus:
                    call_substatus = call_substatus.lower()

                if call_substatus in CenterixCallResult.SYSTEM_GENERATED_NC_STATUS:
                    call_status = CenterixCallResult.NC_STATUS_GROUP

                if call_substatus in CenterixCallResult.SYSTEM_GENERATED_NULL_STATUS:
                    call_status = CenterixCallResult.NULL_STATUS_GROUP

                if call_substatus in CenterixCallResult.SYSTEM_GENERATED_DEFAULT_STATUS:
                    call_status = CenterixCallResult.DEFAULT_STATUS_GROUP

                SkiptraceHistoryCentereix.objects.create(
                    start_ts=start_ts,
                    application=application,
                    loan=loan,
                    loan_status=loan_status,
                    application_status=application.status,
                    payment_id=payment_id,
                    campaign_name=skip_trace.get('campaign_name'),
                    phone_number=format_e164_indo_phone_number(phone),
                    status_group=call_status,
                    status=skip_trace.get('result_call')
                )

                result_message = 'Success'
                error_msg = 'Details updated for application - {}'.format(application.id)
                self.update_centerix_callback_log_system_call_result(
                    error_msg, result_message, skip_trace, application, start_ts, payment_id
                )

    def get_agent_hourly_data_from_centerix(self):
        """
        get agent hourly data from centerix
        """
        url = self.base_url + '/agentCallHourly'
        today = timezone.localtime(timezone.now()).date()
        params = {
            "CredUser": self.user_id,
            "CredPassword": self.pwd,
            "DateFrom": datetime.strftime(today, '%Y-%m-%d'),
            "DateTo": datetime.strftime(today, '%Y-%m-%d')
        }
        response = requests.post(url, json=params)
        if response.status_code != requests.codes.ok:
            response_body = response.text
            raise JuloException(
                "Failed hitting: %s status: %s" % (url, response.status_code))

        response_body = response.json()
        if response_body.get("ErrMessage"):
            raise JuloException(
                "Centerix API error: %s" % response_body.get("ErrMessage"))

        for result in response_body['Result']:
            agent_productivity = AgentProductivity.objects.filter(
                agent_name=result.get('agent_name'), hourly_interval=result.get('interval'),
                calling_date=parse(result.get('summary_date')))

            if not agent_productivity:
                AgentProductivity.objects.create(agent_name=result.get('agent_name'),
                    hourly_interval=result.get('interval'),
                    calling_date=parse(result.get('summary_date')),
                    inbound_calls_offered=result.get('inbound_calls_offered'),
                    inbound_calls_answered=result.get('inbound_calls_answered'),
                    inbound_calls_not_answered=result.get('inbound_calls_not_answered'),
                    outbound_calls_initiated=result.get('outbound_calls_initiated'),
                    outbound_calls_connected=result.get('outbound_calls_connected'),
                    outbound_calls_not_connected=result.get('outbound_calls_not_connected'),
                    outbound_calls_offered=result.get('outbound_calls_offered'),
                    outbound_calls_answered=result.get('outbound_calls_answered'),
                    outbound_calls_not_answered=result.get('outbound_calls_not_answered'),
                    manual_in_calls_offered=result.get('manual_in__calls_offered'),
                    manual_in_calls_answered=result.get('manual_in__calls_answered'),
                    manual_in_calls_not_answered=result.get('manual_in__calls_not_answered'),
                    manual_out_calls_initiated=result.get('manual_out_calls_initiated'),
                    manual_out_calls_connected=result.get('manual_out_calls_connected'),
                    manual_out_calls_not_connected=result.get('manual_out__calls_not_connected'),
                    internal_in_calls_offered=result.get('internal_in__calls_offered'),
                    internal_in_calls_answered=result.get('internal_in__calls_answered'),
                    internal_in_calls_not_answered=result.get('internal_in__calls_not_answered'),
                    internal_out_calls_initiated=result.get('internal_out_calls_initiated'),
                    internal_out_calls_connected=result.get('internal_out_calls_connected'),
                    internal_out_calls_not_connected=result.get('internal_out__calls_not_connected'),
                    inbound_talk_time=result.get('inbound_talk_time'),
                    inbound_hold_time=result.get('inbound_hold_time'),
                    inbound_acw_time=result.get('inbound_acw_time'),
                    inbound_handling_time=result.get('inbound_handling_time'),
                    outbound_talk_time=result.get('outbound_talk_time'),
                    outbound_hold_time=result.get('outbound_hold_time'),
                    outbound_acw_time=result.get('outbound_acw_time'),
                    outbound_handling_time=result.get('outbound_handling_time'),
                    manual_out_call_time=result.get('manual_out_call_time'),
                    manual_in_call_time=result.get('manual_in_call_time'),
                    internal_out_call_time=result.get('internal_out_call_time'),
                    internal_in_call_time=result.get('internal_in_call_time'),
                    logged_in_time=result.get('logged_in_time'),
                    available_time=result.get('available_time'),
                    aux_time=result.get('aux_time'),
                    busy_time=result.get('busy_time'))
