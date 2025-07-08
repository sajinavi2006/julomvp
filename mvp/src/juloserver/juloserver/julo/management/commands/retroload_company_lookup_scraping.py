import json
import csv
import zipfile
import pandas as pd

from io import BytesIO
from django.core.management.base import BaseCommand
from django.db import transaction

from juloserver.application_form.models.general_models import CompanyLookup
from juloserver.apiv1.dropdown.companies import CompanyDropDown
from bulk_update.helper import bulk_update


class Command(BaseCommand):
    help = 'Retroload Company Lookup data Scraping'

    def reformat_company_name(self, value):
        return value.replace('PT ', 'PT. ')

    def get_origin_company_name(self, value, new_company_full_data):

        for new_item in new_company_full_data:
            if value.lower() == new_item['reformat_company_name'].lower():
                return new_item['origin_company_name']

        return None

    def run(self):
        batch_size = 1000
        insert_data = []
        update_data = []
        count_skip_company = 0
        source_data = 'misc_files/csv/company_lookup/company_lookup_2025_05_28.zip'

        with zipfile.ZipFile(source_data, 'r') as zip_file:
            for filename in zip_file.namelist():

                if filename != 'company_lookup.csv':
                    continue

                with zip_file.open(filename) as csv_file:

                    data = pd.read_csv(csv_file, encoding='latin1')
                    # List company name
                    new_company_name = [
                        self.reformat_company_name(row.company_name) for row in data.itertuples()
                    ]
                    new_company_full_data = []
                    for row in data.itertuples():
                        new_company_full_data.append(
                            {
                                'reformat_company_name': self.reformat_company_name(
                                    row.company_name
                                ),
                                'origin_company_name': row.company_name,
                            }
                        )

                    # Reformat company name in existing
                    existing_data = CompanyLookup.objects.extra(
                        select={'reformat_company_name': "REPLACE(company_name, 'PT ', 'PT. ')"}
                    ).values('reformat_company_name', 'id')

                    list_company_name_update = []
                    for item in existing_data.iterator():
                        if item['reformat_company_name'] in new_company_name:
                            origin_company_name = self.get_origin_company_name(
                                item['reformat_company_name'], new_company_full_data
                            )

                            if not origin_company_name:
                                continue

                            list_company_name_update.append(origin_company_name)

                    print('Total data in csv file: ', len(data))
                    print('Total found data need to update ', len(list_company_name_update))
                    for row in data.itertuples():
                        try:

                            # skip if this is header
                            origin_company_name = row.company_name
                            company_name = self.reformat_company_name(origin_company_name)
                            if company_name == 'company_name' or not company_name:
                                count_skip_company = count_skip_company + 1
                                continue

                            company_address = None
                            if row.company_address and not pd.isna(row.company_address):
                                company_address = row.company_address

                            company_phone_number = None
                            if row.company_phone_number and not pd.isna(row.company_phone_number):
                                company_phone_number = row.company_phone_number

                            if origin_company_name in list_company_name_update:
                                obj = CompanyLookup.objects.filter(
                                    company_name__iexact=company_name
                                ).last()
                                if not obj:
                                    print('company_name is not exists: {}'.format(company_name))
                                    continue
                                obj.company_address = company_address
                                obj.company_phone_number = company_phone_number

                                update_data.append(obj)
                            else:
                                insert_data.append(
                                    CompanyLookup(
                                        company_name=company_name,
                                        company_address=company_address,
                                        company_phone_number=company_phone_number,
                                        latitude=None,
                                        longitude=None,
                                    )
                                )

                        except Exception as error:
                            count_skip_company = count_skip_company + 1
                            print(str(error))
                            continue

        with transaction.atomic():
            if update_data:
                CompanyLookup.objects.bulk_update(
                    update_data,
                    update_fields=['company_address', 'company_phone_number', 'udate'],
                    batch_size=1000,
                )
            CompanyLookup.objects.bulk_create(insert_data, batch_size=batch_size)
        print('[Summary] Total data inserted: ', len(insert_data))
        print('[Summary] Total data updated: ', len(update_data))
        print('[Summary] Total data is skip process: ', count_skip_company)


    def handle(self, *args, **options):

        self.stdout.write(self.style.SUCCESS('[START] process.'))
        self.run()
        self.stdout.write(self.style.SUCCESS('[DONE] data successfully'))
