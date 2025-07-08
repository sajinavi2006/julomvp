from django.core.management.base import BaseCommand

from django.db import transaction

from juloserver.loan_refinancing.models import WaiverRecommendation

from pyexcel_xls import get_data


def percent_to_float(percentage_str):
    return float(percentage_str.strip('%')) / 100


def string_to_boolean(boolean_str):
    if boolean_str.lower() == "yes":
        return True

    return False


class Command(BaseCommand):
    help = 'bulk_create_waiver_recommendation'

    def handle(self, *args, **options):
        data = get_data('misc_files/excel/waiver_recommendation.xls')

        reco_list = data['Sheet1']
        reco_entries = []

        with transaction.atomic():
            for idx, reco in enumerate(reco_list):
                if idx == 0:
                    continue

                self.stdout.write(
                    'Program {}, Bucket {}, Covid Risky {}, Product {}'.format(
                        reco[0], reco[1], reco[2], reco[3]))

                filter_data = dict(
                    program_name=reco[0],
                    bucket_name=reco[1],
                    is_covid_risky=string_to_boolean(reco[2]),
                    partner_product=reco[3].lower(),
                )

                existing = WaiverRecommendation.objects.filter(**filter_data)

                if existing:
                    self.stdout.write(self.style.WARNING("already exists!"))
                    continue

                waiver_reco_data = WaiverRecommendation(
                    late_fee_waiver_percentage=percent_to_float(reco[4]),
                    interest_waiver_percentage=percent_to_float(reco[5]),
                    principal_waiver_percentage=percent_to_float(reco[6]),
                    **filter_data
                )
                reco_entries.append(waiver_reco_data)
                self.stdout.write(self.style.SUCCESS(
                    ('Added! with Late Fee amount {}, Interest amount {}, '
                     'Principal amount {}').format(reco[4], reco[5], reco[6])))

            WaiverRecommendation.objects.bulk_create(reco_entries)
            self.stdout.write(
                self.style.SUCCESS('Successfully bulk create Waiver Recommendation to database'))
