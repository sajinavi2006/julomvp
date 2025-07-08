from django.core.management.base import BaseCommand

from django.db import transaction

from juloserver.julo.models import HighScoreFullBypass

from pyexcel_xls import get_data

def change_types(category):
    if category.lower() == 'first time':
        return 'julo'
    elif category.lower() == 'repeat':
        return 'julo_repeat'

    return None

def change_salaried(category):
    if category.lower() == 'salaried':
        return True

    return False

def change_premium_area(location):
    if location.lower() == 'jabodetabek':
        return True

    return False


class Command(BaseCommand):
    help = 'bulk_create_highscore_full_bypass_threshold'

    def handle(self, *args, **options):
        data = get_data('misc_files/excel/highscore_full_bypass.xls')

        hs_list = data['High Score Threshold']
        hs_entries = []

        with transaction.atomic():
            for idx, hs in enumerate(hs_list):
                if idx == 0:
                    continue

                hs_type = change_types(hs[1])
                if not hs_type:
                    continue

                existing = HighScoreFullBypass.objects.filter(
                    cm_version=hs[0],
                    is_premium_area=change_premium_area(hs[3]),
                    is_salaried=change_salaried(hs[2]),
                    customer_category=hs_type,
                )

                if existing:
                    self.stdout.write(
                        self.style.WARNING(
                            'Version {}, Customer {}, Salary {}, Location {} already exists!'.format(
                                hs[0], hs[1], hs[2], hs[3]
                            )
                        )
                    )
                    continue

                hs_data = HighScoreFullBypass(
                    cm_version=hs[0],
                    threshold=float(hs[4]),
                    is_premium_area=change_premium_area(hs[3]),
                    is_salaried=change_salaried(hs[2]),
                    customer_category=hs_type,
                )
                hs_entries.append(hs_data)
                self.stdout.write(
                    self.style.SUCCESS(
                        'Version {}, Customer {}, Salary {}, Location {}, Threshold {} added!'.format(
                            hs[0], hs[1], hs[2], hs[3], hs[4]
                        )
                    )
                )

            hs_save = HighScoreFullBypass.objects.bulk_create(hs_entries)
            self.stdout.write(self.style.SUCCESS('Successfully bulk create High Score Full Bypass to database'))