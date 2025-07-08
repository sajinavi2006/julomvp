from __future__ import print_function
from builtins import str
import logging
import sys
import csv

from django.core.management.base import BaseCommand
from juloserver.julo.models import Customer
from django.contrib.auth.models import User
from juloserver.julo.models import Skiptrace, SkiptraceHistory, SkiptraceResultChoice, SkiptraceHistoryCentereix
from juloserver.julo.utils import format_e164_indo_phone_number
import datetime
from cuser.middleware import CuserMiddleware
logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))

class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument('-f', '--file', type=str, help='Define file name')

    def handle(self, **options):
        path = options['file']
        try:
            with open(path, 'r') as csvfile:
                csv_rows = csv.DictReader(csvfile, delimiter=',')
                rows = [r for r in csv_rows]
                row_num = 1
            for row in rows:
                skiptrace_agent_name = row['agent_name']
                skiptrace_agent_id = row['agent_id']
                application_id = row['application_id']
                loan_id = row['loan_id']
                skiptrace_notes = row['Notes']
                start_ts_date = row['start_ts']
                start_ts =  datetime.datetime.strptime(start_ts_date, '%Y-%m-%d %H:%M:%S.%f')
                start_ts = start_ts.strftime("%Y-%m-%d %H:%M:%S")
                end_ts = start_ts
                skiptrace_result_id = row['skiptrace_result_choice_id']
                skiptrace_result_name = row['skiptrace_result_name']
                skiptrace_phone = row['phone_number']
                customer_id = row['customer_id']
                udates = row['udate']
                udate = datetime.datetime.strptime(udates, '%Y-%m-%d %H:%M:%S.%f')
                udate = udate.strftime("%Y-%m-%d")

                row_num = row_num + 1
                if customer_id:
                    skip_history = SkiptraceHistory.objects.filter(udate__date=udate, loan_id= loan_id).last()
                    if skip_history:
                        print('skiptrace details already exists for loan -'+str(loan_id)+' on the date '+str(udate)+', row no:'+str(row_num))
                        continue
                    cust_obj = Customer.objects.get_or_none(pk=customer_id)
                    if cust_obj is None:
                        logger.error({
                            "ErrMessage": 'Invalid customer details - {}, row no: {}'.format(customer_id, row_num),
                            "Result": 'Failure'
                        })
                        continue
                    user_obj = User.objects.filter(id=skiptrace_agent_id).last()
                    if user_obj is None:
                        logger.error({
                            "ErrMessage": 'Invalid agent details - {}, row no: {}'.format(skiptrace_agent_id, row_num),
                            "Result": 'Failure'
                        })
                        continue
                    skip_result_choice = SkiptraceResultChoice.objects.filter(id=skiptrace_result_id).last()
                    if not skip_result_choice:
                        logger.error({
                            "ErrMessage": 'Invalid status call  - {}, row no: {}'.format(skiptrace_result_id, row_num),
                            "Result": 'Failure'
                        })
                        continue
                    CuserMiddleware.set_user(user_obj)
                    skiptrace_obj = Skiptrace.objects.filter(
                        phone_number=format_e164_indo_phone_number(skiptrace_phone),
                        customer_id=customer_id).last()
                    if not skiptrace_obj:
                        skiptrace = Skiptrace.objects.create(phone_number=format_e164_indo_phone_number(skiptrace_phone),
                                                             customer_id=customer_id)
                        skiptrace_id = skiptrace.id
                    else:
                        skiptrace_id = skiptrace_obj.id
                    if skiptrace_id:
                        skiptrace_history = SkiptraceHistory.objects.create(start_ts=start_ts, end_ts=end_ts,
                                                                            application_id=application_id,
                                                                            loan_id=loan_id,
                                                                            agent_name=user_obj.username,
                                                                            call_result_id=skiptrace_result_id,
                                                                            agent_id=skiptrace_agent_id,
                                                                            skiptrace_id=skiptrace_id,
                                                                            notes=skiptrace_notes)
                        skip_status_mappings = {'RPC - Regular': 'CONTACTED',
                                                'RPC - PTP': 'CONTACTED',
                                                'PTPR': 'CONTACTED',
                                                'RPC - HTP': 'CONTACTED',
                                                'RPC - Broken Promise': 'CONTACTED',
                                                'Broken Promise': 'CONTACTED',
                                                'RPC - Call Back': 'CONTACTED',
                                                'Call Back': 'CONTACTED',
                                                'WPC - Regular': 'CONTACTED',
                                                'WPC - Left Message': 'CONTACTED',
                                                'Answering Machine': 'NO CONTACTED',
                                                'Busy Tone': 'NO CONTACTED',
                                                'Ringing': 'NO CONTACTED',
                                                'Rejected/Busy': 'NO CONTACTED',
                                                'No Answer': 'NO CONTACTED',
                                                'Dead Call': 'NO CONTACTED',
                                                'Ringing no pick up / Busy': 'NO CONTACTED',
                                                'Whatsapp - Text': 'WHATSAPP',
                                                'WPC': 'CONTACTED',
                                                'RPC': 'CONTACTED',
                                                'PTPR': 'CONTACTED',
                                                'Short Call': 'CONTACTED',
                                                'cancel': 'NO CONTACTED',
                                                'HANG UP': 'NO CONTACTED',
                                                }
                        skip_group_mappings = {'Not Connected': 'NO CONTACTED',
                                               'Connected': 'CONTACTED',
                                               'NO CONTACTED': 'NO CONTACTED'
                                               }

                        skip_result_status = skip_status_mappings.get(skiptrace_result_name)
                        skip_result_group = skip_group_mappings.get(skiptrace_result_name)
                        if skip_result_status:
                            status_group = skip_result_status
                            status = skiptrace_result_name
                        elif skip_result_group:
                            status_group = skip_result_group
                            status = ''
                        elif skiptrace_result_name == 'Hard To Pay':
                            status_group = 'CONTACTED'
                            status = 'RPC - HTP'
                        else:
                            status_group = skiptrace_result_name
                            status = ''
                        skiptrace_history_centerix = SkiptraceHistoryCentereix.objects.create(start_ts=start_ts,
                                                                                              end_ts=end_ts,
                                                                                              application_id=application_id,
                                                                                              loan_id=loan_id,
                                                                                              agent_name=user_obj.username,
                                                                                              comments=skiptrace_notes,
                                                                                              phone_number=format_e164_indo_phone_number(
                                                                                                  skiptrace_phone),
                                                                                              status_group=status_group,
                                                                                              status=status,
                                                                                              campaign_name='JULO'
                                                                                              )


            print('data upoaded successfully')
        except IOError:
            logger.error("could not open given file " + path)
            return

