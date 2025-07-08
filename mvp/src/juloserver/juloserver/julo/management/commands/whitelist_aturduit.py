import base64
import csv
import os

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from ...clients import get_julo_email_client
from ...clients import get_julo_sms_client
from ...exceptions import EmailNotSent, SmsNotSent
from ...models import Customer
from ...models import Partner
from ...models import PartnerReferral
from ...partners import PartnerConstant
from ...utils import format_e164_indo_phone_number


def set_pre_exist(email, nik):
    customer = Customer.objects.filter(Q(email__icontains=email) | Q(nik=nik))
    partner_referral = PartnerReferral.objects.filter(Q(cust_email__icontains=email) |
                                                      Q(cust_nik=nik))
    if customer or partner_referral:
        return True

    return False


class Command(BaseCommand):
    help = 'whitelist customer from aturduit <path/to/csv_file.csv'

    def add_arguments(self, parser):
        parser.add_argument('whitelist_csv', nargs='+', type=str)

    def handle(self, *args, **options):
        path = None
        for option in options['whitelist_csv']:
            path = option

        with open(path, 'r') as csvfile:
            partner = Partner.objects.get(name=PartnerConstant.ATURDUIT_PARTNER)
            report_list = []
            r = csv.DictReader(csvfile)
            num = 1
            for row in r:
                if row['Email Address'] == '' and row['Identification No'] == '':
                    continue

                data = {}
                data['partner'] = partner
                data['pre_exist'] = set_pre_exist(row['Email Address'], row['Identification No'])
                data['partner_account_id'] = row['Submission Id']
                data['cust_fullname'] = row['Name']
                data['cust_email'] = row['Email Address']
                data['mobile_phone_1'] = row['Phone Number']
                data['cust_nik'] = row['Identification No']
                data['monthly_income'] = row['Monthly Salary']
                data['job_type'] = row['Employed Status']
                data['job_function'] = row['Work Position']

                # check for redundant data
                existed_whitelist = PartnerReferral.objects.filter(
                    (Q(cust_email__icontains=row['Email Address']) |
                     Q(cust_nik=row['Identification No'])) & Q(partner=partner)).exists()
                if existed_whitelist:
                    self.stdout.write(self.style.WARNING(
                        'whitelist %s from partner %s already exist' % (row['Email Address'],
                                                                        partner)
                    ))
                    continue

                else:
                    # save partner referral
                    whitelisted_cust = PartnerReferral(**data)
                    try:
                        whitelisted_cust.save()
                        row['status'] = 'Success'
                        if data['pre_exist']:
                            row['status'] = 'Pre-Exist'
                        self.stdout.write(self.style.SUCCESS(
                            'Successfully whitelist customer %s' % (whitelisted_cust.cust_email)))
                    except Exception as e:
                        row['status'] = 'Failed'
                        self.stdout.write(self.style.ERROR(e))

                    if not data['pre_exist'] and row['status'] == 'Success':
                        sms_client = get_julo_sms_client()
                        message = 'Selamat! Solusi Pinjaman Tanpa Jaminan MUDAH & MURAH smp dgn 8 JUTA lewat HP Anda. Unduh aplikasi JULO disini bit.ly/juloapp dan ajukan sekarang! Salam Sukses!'
                        mobile_number = format_e164_indo_phone_number(data['mobile_phone_1'])

                        try:
                            message, response = sms_client.send_sms(mobile_number, message)
                            row['sms_sent_status'] = response['status']
                            if response['status'] == '0':
                                row['sms_sent_status'] = 'Sent'

                        except SmsNotSent as e:
                            row['sms_sent_status'] = 'Not Sent'
                            self.stdout.write(self.style.WARNING(e))

                row['No'] = num
                del row['Formating']
                del row['File']
                report_list.append(row)
                num += 1

            self.stdout.write(self.style.SUCCESS(
                'Successfully load whitelist %s to db' % (partner.name)))

            list_email_to = ['yogi@julo.co.id']
            now = timezone.now()
            filedate = now.date().__str__().replace('-', '')
            # folder = '../../whitelisted/'
            filename = 'whitelist_{}{}.csv'.format(partner.name, filedate)
            fields = ['No', 'Submission Id', 'Name', 'Email Address', 'Phone Number',
                      'Identification No', 'City', 'Address', 'Age', 'Monthly Salary',
                      'Employed Status', 'Work Position', 'status', 'sms_sent_status']
            with open(filename, 'wb') as csvfile2:
                w = csv.DictWriter(csvfile2, fields)
                w.writeheader()
                w.writerows(report_list)

            # prepare attachment
            with open(filename, 'rb') as rf:
                result_string = rf.read()

            b64content = base64.b64encode(result_string)
            attachment = {
                'content': b64content.encode('utf-8'),
                'filename': filename,
                'type': 'csv'
            }
            email_client = get_julo_email_client()
            email_to = (',').join(list_email_to)
            subject = 'AturDuit Whitelist Report'
            message = 'aturduit whitelist report on %s' % now

            try:
                status, body, headers = email_client.send_email(subject,
                                                                message,
                                                                email_to,
                                                                attachment_dict=attachment)
            except EmailNotSent as e:
                self.stdout.write(self.style.WARNING(e))

            if status == 202:
                os.remove(filename)
                self.stdout.write(self.style.SUCCESS(
                    'Successfully send report to %s' % (email_to)))
            else:
                self.stdout.write(self.style.WARNING(
                    'Send email report response status %s') % (status))
