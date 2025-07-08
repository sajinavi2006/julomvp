# src/juloserver/juloserver/apiv1/dropdown/companies.py

import json

from django.core.management.base import BaseCommand
from django.db import transaction

from juloserver.application_form.models import CompanyLookup
from juloserver.apiv1.dropdown.companies import CompanyDropDown


class Command(BaseCommand):
    help = 'Retroload Company Lookup data'

    def run(self):
        batch_size = 1000
        company_lookup = []

        self.stdout.write(self.style.SUCCESS('[PROCESS] transaction active & start loop data'))
        with transaction.atomic():
            for company_name in CompanyDropDown.DATA:
                company_lookup.append(
                    CompanyLookup(
                        company_name=company_name,
                        company_address=None,
                        latitude=None,
                        longitude=None,
                        company_phone_number=None,
                    )
                )

            self.stdout.write(self.style.SUCCESS('[PROCESS] bulk_create processing...'))
            CompanyLookup.objects.bulk_create(company_lookup, batch_size=batch_size)

    def handle(self, *args, **options):

        self.stdout.write(self.style.SUCCESS('[START] process.'))
        self.run()
        self.stdout.write(self.style.SUCCESS('[DONE] data successfully inserted.'))
