import csv
import re
from django.db import transaction
from django.core.management.base import BaseCommand

from juloserver.apiv3.models import (
    ProvinceLookup,
    CityLookup,
    DistrictLookup,
    SubDistrictLookup,
)


class Command(BaseCommand):
    help = 'Retroload new address for zipcode'

    def remove_double_space(self, value):
        return re.sub(' +', ' ', value)

    def remove_to_clean_string(self, value):

        if not value:
            return value

        value = self.remove_double_space(value)
        final_value = "".join(value.rstrip())

        return final_value

    def handle(self, *args, **options):

        csv_file_name = 'misc_files/csv/20250217_0943_export_json_result.csv'
        count = 0
        with open(csv_file_name, 'r') as csvfile:
            csv_rows = csv.DictReader(csvfile, delimiter=',')
            for row in csv_rows:

                kode_pos = row['Kode POS']
                provinsi = self.remove_to_clean_string(row['Provinsi'])
                kota_kabupaten = row['DT2'] + ' {}'.format(row['Kota/Kabupaten'])
                if row['DT2'] == 'Kabupaten':
                    kota_kabupaten = 'Kab. {}'.format(row['Kota/Kabupaten'])

                kota_kabupaten = self.remove_to_clean_string(kota_kabupaten)
                kecamatan = self.remove_to_clean_string(row['Kecamatan/Distrik'])
                kelurahan = self.remove_to_clean_string(row['Desa/Kelurahan'])

                if (
                    not provinsi
                    or not kode_pos
                    or not kota_kabupaten
                    or not kecamatan
                    or not kelurahan
                ):
                    self.stdout.write(
                        self.style.WARNING(
                            '[SKIP] retroload data for zipcode {} - {} - {} - {} - {} '.format(
                                provinsi, kota_kabupaten, kecamatan, kelurahan, kode_pos
                            )
                        )
                    )
                    continue

                with transaction.atomic():
                    # insert province
                    province_lookup = ProvinceLookup.objects.filter(
                        province__iexact=provinsi, is_active=True
                    ).last()
                    if not province_lookup:
                        province_lookup = ProvinceLookup.objects.create(
                            province=provinsi, is_active=True
                        )
                        self.stdout.write(
                            self.style.SUCCESS('[INSERTED] Province: {}'.format(provinsi))
                        )

                    # City Lookup
                    city_lookup = CityLookup.objects.filter(
                        province=province_lookup, city__iexact=kota_kabupaten, is_active=True
                    ).last()
                    if not city_lookup:
                        city_lookup = CityLookup.objects.create(
                            city=kota_kabupaten, province=province_lookup, is_active=True
                        )
                        self.stdout.write(
                            self.style.SUCCESS('[INSERTED] City: {}'.format(kota_kabupaten))
                        )

                    # Kecamatan
                    district_lookup = DistrictLookup.objects.filter(
                        city=city_lookup,
                        district__iexact=kecamatan,
                        is_active=True,
                    ).last()
                    if not district_lookup:
                        district_lookup = DistrictLookup.objects.create(
                            city=city_lookup, district=kecamatan, is_active=True
                        )
                        self.stdout.write(
                            self.style.SUCCESS('[INSERTED] District: {}'.format(kecamatan))
                        )

                    # Kelurahan
                    sub_district_lookup = SubDistrictLookup.objects.filter(
                        district=district_lookup,
                        sub_district__iexact=kelurahan,
                        is_active=True,
                    ).last()
                    if not sub_district_lookup:
                        sub_district_lookup = SubDistrictLookup.objects.create(
                            sub_district=kelurahan,
                            district=district_lookup,
                            zipcode=kode_pos,
                            is_active=True,
                        )
                        self.stdout.write(
                            self.style.SUCCESS('[INSERTED] Sub-district: {}'.format(kelurahan))
                        )

                    count += 1

        self.stdout.write(
            self.style.SUCCESS('[DONE] retroload total data for zipcode: {}'.format(count))
        )
