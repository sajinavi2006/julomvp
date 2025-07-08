from django.core.management.base import BaseCommand

from juloserver.account.models import Account
from juloserver.julo.constants import AddressPostalCodeConst


class Command(BaseCommand):
    help = "Retroload account user timezone"

    def handle(self, *args, **options):
        data = {
            'WITA': [
                [77111, 77574],
                [75111, 77381],
                [70111, 72276],
                [80111, 82262],
                [83115, 84459],
                [85111, 87284],
                [91311, 91591],
                [94111, 94981],
                [90111, 91273],
                [91611, 92985],
                [93111, 93963],
                [95111, 95999],
                [96111, 96574],
            ],
            'WIT': [
                [97114, 97669],
                [97711, 97869],
                [98511, 99976],
                [98011, 98495],
            ],
        }
        for timezone_key, range_postal_codes in data.items():
            self.stdout.write('Start Retroloading {}'.format(timezone_key))
            for postal_code in range_postal_codes:
                self.stdout.write(
                    'Start Retroloading {} {} - {}'.format(
                        timezone_key, postal_code[0], postal_code[-1]
                    )
                )
                if not Account.objects.filter(
                    application__address_kodepos__range=postal_code
                ).exists():
                    self.stdout.write(
                        self.style.WARNING(
                            'Warning Retroloading {} {} - {}'.format(
                                timezone_key, postal_code[0], postal_code[-1]
                            )
                        )
                    )
                    continue
                Account.objects.filter(application__address_kodepos__range=postal_code).update(
                    user_timezone=AddressPostalCodeConst.PYTZ_TIME_ZONE_ID[timezone_key]
                )
                self.stdout.write(
                    'Finish Retroloading {} {} - {}'.format(
                        timezone_key, postal_code[0], postal_code[-1]
                    )
                )
            self.stdout.write(self.style.SUCCESS('finish Retroloading {}'.format(timezone_key)))
        if not Account.objects.filter(user_timezone__isnull=True).exists():
            self.stdout.write(self.style.SUCCESS('finish Retroloading WIB because not exists'))
            return
        Account.objects.filter(user_timezone__isnull=True).update(
            user_timezone=AddressPostalCodeConst.PYTZ_TIME_ZONE_ID['WIB']
        )
        self.stdout.write(self.style.SUCCESS('finish Retroloading WIB'))
