from __future__ import print_function
from builtins import str
import logging
import re

from datetime import datetime

from django.core.management.base import BaseCommand
from django.db import connection

from ...models import Application
from ...models import Payment
from ...models import DeviceIpHistory
from ...models import Loan


class Command(BaseCommand):
    help = 'parse nginx_access log file to database'

    def add_arguments(self, parser):
        parser.add_argument('log_files', nargs='+', type=str)

    def handle(self, *args, **options):
        path = None
        for option in options['log_files']:
            path = option

        self.parse_log_to_json(path)

        self.stdout.write(self.style.SUCCESS('Successfully parse log'))

    def update_cdate(self, cdate, device_ip_history_id):
        """
        Update c_date device_ip_history with SQL since in django it is auto set
        """
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE device_ip_history SET cdate = %s WHERE device_ip_history_id = %s",
                [cdate, device_ip_history_id]
            )

        print('updated', device_ip_history_id, cdate)

    def insert_to_table(self, datas):
        """to insert parser data into DeviceIpHistory table"""
        for data in datas:
            parent = None
            refer_id = data['refer_id']
            cdate = data['cdate'].replace('/', '-')
            # process insert to table by application id
            if data['refer_id'].startswith("2"):
                application = Application.objects.get_or_none(id=int(refer_id))
                print(application)
                if application is not None:
                    customer_id = application.customer_id
                    device_id = application.device_id
                    inserted = DeviceIpHistory.objects.create(
                        ip_address=data['ip'],
                        customer_id=customer_id,
                        count=1,
                        device_id=device_id
                    )
                    print(customer_id, device_id, data[
                        'ip'], cdate, application.id)
                    if inserted:
                        converted_cdate = datetime.strptime(cdate[0:19],
                                                            '%d-%b-%Y:%H:%M:%S')
                        self.update_cdate(converted_cdate, inserted.id)

            # process insert to table by loan id
            elif data['refer_id'].startswith("3"):
                loan = Loan.objects.get_or_none(id=int(refer_id))
                print(loan)
                if loan is not None:
                    customer_id = loan.customer_id
                    device_id = loan.application.device_id
                    inserted = DeviceIpHistory.objects.create(
                        ip_address=data['ip'],
                        customer_id=customer_id,
                        count=1,
                        device_id=device_id
                    )
                    print(customer_id, device_id, data['ip'], data[
                        'cdate'], loan.id)
                    if inserted:
                        converted_cdate = datetime.strptime(cdate[0:19],
                                                            '%d-%b-%Y:%H:%M:%S')
                        self.update_cdate(converted_cdate, inserted.id)

            # process insert to table by paymnet id
            elif data['refer_id'].startswith("4"):
                payment = Payment.objects.get(id=int(refer_id))
                print(payment)
                if payment is not None:
                    customer_id = payment.loan.customer_id
                    device_id = payment.loan.application.device_id
                    inserted = DeviceIpHistory.objects.create(
                        ip_address=data['ip'],
                        customer_id=customer_id,
                        count=1,
                        device_id=device_id
                    )
                    print(customer_id, device_id, data['ip'], data[
                        'cdate'], payment.id)
                    if inserted:
                        converted_cdate = datetime.strptime(cdate[0:19],
                                                            '%d-%b-%Y:%H:%M:%S')
                        self.update_cdate(converted_cdate, inserted.id)

    def parse_log_to_json(self, files):
        """to parser log file into string and put in the list"""
        with open(files, 'r') as raw:
            log_file = raw.readlines()

        lines = list(log_file)

        ip_re = re.compile(
            r'(\d+.\d+.\d+.\d+)\s-\s-\s'  # IP address
        )
        id_re = re.compile(
            r'([0-9]{10})'  # application id, payment id, loan id
        )
        cdate_re = re.compile(
            r'\[(.+)\]\s'  # datetime
        )

        has_id = ['application', 'loan', 'payment']
        keymatch = re.compile("|".join(has_id), flags=re.I | re.X)
        targeted_url = 'api/v1/'

        datas = []

        for line in lines:
            match = keymatch.findall(str(line))
            # print match
            idv = re.findall(id_re, str(line))
            if len(match) > 0 and targeted_url in line:
                if idv:
                    ip_addr = re.findall(ip_re, str(line))
                    access_time = re.findall(cdate_re, str(line))

                    data = {
                        'refer_id': idv[0],
                        'ip': ip_addr[0],
                        'cdate': access_time[0],
                    }

                    datas.append(data)
        self.insert_to_table(datas)
