from __future__ import print_function
from pyexcel_xls import get_data

from django.core.management.base import BaseCommand

from ...models import PartnerReferral
from ...models import Partner
from ...models import ProductLookup
from ...product_lines import ProductLineCodes

def load_grab_app_to_refferal(files):

    data = get_data(files)
    batch1 = data['batch1']
    batch2 = data['batch2']
    partner = Partner.objects.get(name='grab')
    ProductLookup1 = ProductLookup.objects.get(product_name='I.000-O.060-L.000-C1.000-C2.000-M')
    ProductLookup2 = ProductLookup.objects.get(product_name='I.000-O.100-L.000-C1.000-C2.000-M')


    for a in batch1:
        if batch1.index(a) > 0:
            try:
                PartnerReferral.objects.create(
                    cust_fullname=a[0],
                    cust_nik=a[1],
                    cust_dob=a[2],
                    gender=a[3],
                    partner=partner,
                    product=ProductLookup1
                )
            except:
                print(a[0])

    for b in batch2:
        if batch2.index(b) > 0:
            try:
                PartnerReferral.objects.create(
                    cust_fullname=a[0],
                    cust_nik=a[1],
                    cust_dob=a[2],
                    gender=a[3],
                    partner=partner,
                    product=ProductLookup2
                )
            except:
                print(b[0])


class Command(BaseCommand):
    help = 'load_grab_app_to_refferal <path/to/excel_file.xlxs'

    def add_arguments(self, parser):
        parser.add_argument('va_excel', nargs='+', type=str)

    def handle(self, *args, **options):
        path = None
        for option in options['grab_excel']:
            path = option

        load_grab_app_to_refferal(path)

        self.stdout.write(self.style.SUCCESS('Successfully load grab to database'))
