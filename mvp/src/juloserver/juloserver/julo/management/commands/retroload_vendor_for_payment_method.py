from django.core.management.base import BaseCommand

from django.conf import settings
from django.db import transaction

from juloserver.julo.models import PaymentMethod


class Command(BaseCommand):
    def handle(self, *args, **options):
        batch_size = 1000

        payment_groups = [
            {
                'name': 'DOKU',
                'codes': [
                    settings.PREFIX_MANDIRI_DOKU,
                    settings.PREFIX_BRI_DOKU,
                    settings.PREFIX_PERMATA_DOKU,
                ],
            },
            {
                'name': 'FASPAY',
                'codes': [
                    settings.FASPAY_PREFIX_MANDIRI,
                    settings.FASPAY_PREFIX_BRI,
                    settings.FASPAY_PREFIX_PERMATA,
                ],
            },
        ]

        with transaction.atomic():
            for group in payment_groups:
                self.stdout.write(f"\nProcessing {group['name']} payments...")

                all_ids = PaymentMethod.objects.filter(
                    payment_method_code__in=group['codes']
                ).values_list('id', flat=True)

                total = len(all_ids)
                if not total:
                    self.stdout.write(f"No {group['name']} payments found")
                    continue

                for i in range(0, total, batch_size):
                    batch_ids = all_ids[i : i + batch_size]

                    PaymentMethod.objects.filter(id__in=batch_ids).update(vendor=group['name'])

                    self.stdout.write(
                        f"Processed {min(i + batch_size, total)}/{total} {group['name']} payments...",
                        ending='\r',
                    )

                self.stdout.write(f"\nUpdated {total} {group['name']} payments")

        self.stdout.write("\nAll updates completed successfully!")
