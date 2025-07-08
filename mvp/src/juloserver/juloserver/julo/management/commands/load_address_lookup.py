import logging
import sys
import csv

from django.core.management.base import BaseCommand
from juloserver.apiv3.models import (ProvinceLookup,
                                     CityLookup,
                                     DistrictLookup,
                                     SubDistrictLookup
                                     )
logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))

PROVINCE = 'Province'
CITY = 'Kabupaten'
DISTRICT = 'Kecamatan'
SUBDISTRICT = 'Kelurahan'
ZIP = 'zipcode'

class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument('-f', '--file', type=str, help='Define file name')

    def handle(self, **options):
        path = options['file']
        try:
            with open(path, 'r') as csvfile:
                csv_rows = csv.DictReader(csvfile, delimiter=',')
                rows = [r for r in csv_rows]

            # parse unique province
            self.stdout.write(self.style.SUCCESS("==========provinces import============"))
            provinces = set([x['Province'] for x in rows])
            exist_province = list(ProvinceLookup.objects.all().values_list('province', flat=True))
            for province in provinces:
                if province not in exist_province:
                    ProvinceLookup.objects.create(
                        province=province
                    )
                    exist_province.append(province)

            # parse city
            self.stdout.write(self.style.SUCCESS("==========city import============"))
            for row in rows:
                province = ProvinceLookup.objects.get(province=row[PROVINCE])
                exist_city = CityLookup.objects.get_or_none(
                    province=province,
                    city=row[CITY]
                )
                if not exist_city:
                    CityLookup.objects.create(
                        province=province,
                        city=row[CITY]
                    )

            # parse district
            self.stdout.write(self.style.SUCCESS("==========district import============"))
            for row in rows:
                province = ProvinceLookup.objects.get(province=row[PROVINCE])
                city = CityLookup.objects.get(
                    province=province,
                    city=row[CITY]
                )
                exist_district = DistrictLookup.objects.get_or_none(
                    city__province=province,
                    city=city,
                    district=row[DISTRICT]
                )
                if not exist_district:
                    DistrictLookup.objects.create(
                        city=city,
                        district=row[DISTRICT]
                    )

            # parse sub district
            self.stdout.write(self.style.SUCCESS("==========sub district import============"))
            for row in rows:
                province = ProvinceLookup.objects.get(province=row[PROVINCE])
                city = CityLookup.objects.get(
                    province=province,
                    city=row[CITY]
                )
                district = DistrictLookup.objects.get(
                    city__province=province,
                    city=city,
                    district=row[DISTRICT]
                )
                exist_subdistrict = SubDistrictLookup.objects.get_or_none(
                    district__city__province=province,
                    district__city=city,
                    district=district,
                    sub_district=row[SUBDISTRICT]
                )

                if not exist_subdistrict:
                    SubDistrictLookup.objects.create(
                        district=district,
                        sub_district=row[SUBDISTRICT],
                        zipcode=row[ZIP]
                    )

        except IOError:
            logger.error("could not open given file " + path)
            return

