from __future__ import absolute_import

import json
import pytest
import os
import mock

from datetime import datetime

from juloserver.julo.checkers import does_applicant_meet_age_requirements
from juloserver.julo.checkers import true_owned_phone
from juloserver.julo.checkers import does_salary_meet_requirements
from juloserver.julo.checkers import ktp_vs_areacode
from juloserver.julo.checkers import ktp_vs_dob
from juloserver.julo.checkers import company_not_blacklist
from juloserver.julo.checkers import job_not_blacklist
from juloserver.julo.checkers import fb_friends_gt_50
from juloserver.julo.checkers import dob_match_fb_form
from juloserver.julo.checkers import gender_match_fb_form
from juloserver.julo.checkers import email_match_fb_form
from juloserver.julo.checkers import home_address_vs_gps

from juloserver.julo.models import StatusLookup

from .factories import ApplicationFactory, FacebookDataFactory, AddressGeolocationFactory
from django.test.testcases import TestCase

current_dir = os.getcwd()

@pytest.mark.django_db
class TestCheckers(TestCase):

    def test_json_data(self):
        file_names = ['blacklist_company.json', 'chinatrust_blacklist.json', 'kode_wilayah.json']

        for file_name in file_names:
            filepath = os.path.join(current_dir, 'juloserver', 'julo', 'helpers', file_name)

            with open(filepath, 'r') as f:
                json.loads(f.read())

    def test_does_applicant_meet_age_requirements(self):
        test_cases = [
            ('1966-02-12', False),
            ('1990-02-24', True),
            ('2008-01-23', False)
        ]
        for str_date, expected_value in test_cases:
            date_dt = datetime.strptime(str_date, '%Y-%m-%d')
            date = datetime.date(date_dt)
            assert does_applicant_meet_age_requirements(date) == expected_value

    def test_true_owned_phone(self):
        status = StatusLookup.objects.get(status_code=110)
        application = ApplicationFactory(application_status=status)

        assert true_owned_phone(application) == True

    def test_does_salary_meet_requirements(self):
        test_cases = [
            (1000000, False),
            (3000000, True),
            (5000000, True)
        ]

        for salary, expected_value in test_cases:
            assert does_salary_meet_requirements(salary) == expected_value

    def test_ktp_vs_areacode(self):
        test_cases = [
            ('3271065902890002', True),
            ('1234567890123433', False)
        ]
        for ktp, expected_value in test_cases:
            assert ktp_vs_areacode(ktp) == expected_value

    def test_ktp_vs_dob(self):
        status = StatusLookup.objects.get(status_code=110)

        application = ApplicationFactory(application_status=status)
        application.dob = '1990-02-01'
        application.gender = 'Pria'
        application.save()

        assert ktp_vs_dob(application) is False

        application2 = ApplicationFactory()
        application2.dob = '1989-02-19'
        application2.gender = 'Wanita'
        application2.ktp = '3271065902890002'
        application2.save()

        assert ktp_vs_dob(application2) is True

    def test_company_not_blacklist(self):
        test_cases = [
            ('PT. Kilang Gemilang', True),
            ('PT. TUNGGALIDAMANABADI', False),
            ('PT. VULGO FINANCE', False),
            ('CV. SKYLINK', True)
        ]
        for company, expected_value in test_cases:
            assert company_not_blacklist(company) == expected_value


def mock_geocode(*args):
    geo = lambda: 0
    geo.latitude = -6.263224
    geo.longitude = 106.843852
    return geo


class TestCheckers2(TestCase):
    def setUp(self):
        status = StatusLookup.objects.get(status_code=110)
        self.application = ApplicationFactory(application_status=status)
        self.fb_data = FacebookDataFactory()
        self.application.facebook_data = self.fb_data
        self.application.customer.save()
        self.application.addressgeolocation = AddressGeolocationFactory()
        self.application.save()

    def test_job_not_blacklist(self):
        self.application.job_type = "Not Banned"
        self.application.save()
        self.assertEqual(job_not_blacklist(self.application), True)

        # Two banned types
        self.application.job_type = "Tidak bekerja"
        self.application.save()
        self.assertEqual(job_not_blacklist(self.application), False)

        self.application.job_type = "Not Banned"
        self.application.job_industry = "Transportasi"
        self.application.job_description = "Supir / Ojek"
        self.application.save()
        self.assertEqual(job_not_blacklist(self.application), False)

    def test_fb_friends_gt_50(self):
        self.application.facebook_data.friend_count = 70
        self.application.facebook_data.save()
        self.assertEqual(fb_friends_gt_50(self.application), True)

        self.application.facebook_data.friend_count = 30
        self.application.facebook_data.save()
        self.assertEqual(fb_friends_gt_50(self.application), False)

    def test_fb_data_matches_form(self):
        # Date of birth
        self.application.facebook_data.dob = self.application.dob
        self.application.facebook_data.save()
        self.assertEqual(dob_match_fb_form(self.application), True)

        self.application.facebook_data.dob = "2099-01-01"
        self.application.facebook_data.save()
        self.assertEqual(dob_match_fb_form(self.application), False)

        # Gender
        test_cases = [
            ('male', 'Wanita', False),
            ('female', 'Wanita', True),
            ('Bi-fluid snowflake', 'Pria', None)
        ]
        for fb_gender, application_gender, expected_result in test_cases:
            self.application.facebook_data.gender = fb_gender
            self.application.facebook_data.save()
            self.application.gender = application_gender
            self.application.save()
            self.assertEqual(gender_match_fb_form(self.application), expected_result)

        # Email
        self.application.facebook_data.email = self.application.email
        self.application.facebook_data.save()
        self.assertEqual(email_match_fb_form(self.application), True)

        self.application.facebook_data.email = "none@none.no"
        self.application.facebook_data.save()
        self.assertEqual(email_match_fb_form(self.application), False)

    @mock.patch('geopy.geocoders.GoogleV3.geocode', mock_geocode)
    def test_home_address_vs_gps(self):
        self.application.addressgeolocation.latitude = -6.263224
        self.application.addressgeolocation.longitude = 106.843852
        self.application.addressgeolocation.save()
        self.application.address_street_num = "Jalan Raya Pasar Minggu KM. 18, RT. 01 / RW. 01"
        self.application.address_kelurahan = "Ps. Minggu"
        self.application.address_kecamatan = "Jakarta"
        self.application.address_kabupaten = ""
        self.application.address_provinsi = ""
        self.application.address_kodepos = "12510"
        self.application.save()
        self.assertEqual(home_address_vs_gps(self.application), True)

        self.application.addressgeolocation.latitude = -6.2690988
        self.application.addressgeolocation.longitude = 106.846597
        self.application.addressgeolocation.save()
        self.assertEqual(home_address_vs_gps(self.application), False)
