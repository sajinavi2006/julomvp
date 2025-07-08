import os
import time
import datetime
import requests
import urllib3
import json

from juloserver.julo.models import(
    Application,
    FeatureSetting,
    UnderwritingRunner,
    CreditScore,
    AddressGeolocation,
)
from juloserver.julo.constants import FeatureNameConst
from juloserver.julolog.julolog import JuloLog

from juloserver.julo.clients import get_julo_sentry_client

logger = JuloLog(__name__)


class CDEError(Exception):
    pass


class CDEClient:

    CDE_ENDPOINT = os.getenv("CDE_ENDPOINT")
    CDE_AUTH = os.getenv("CDE_AUTH")

    def __init__(self, application: Application):
        self.application = application

    def get_cde_setting(self):
        return FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.CREDIT_DECISION_ENGINE_CDE
        ).last()

    def post(self, path, headers, data):
        url = '{}{}'.format(self.CDE_ENDPOINT, path)

        response = requests.post(url, json=data, headers=headers)

        return response

    def hit_cde(self):
        if (
            not self.application.is_julo_one_product()
            or self.application.partner
        ):
            return

        setting = self.get_cde_setting()

        if not setting or not setting.is_active:
            return

        credit_score = CreditScore.objects.filter(application=self.application).last()
        if not credit_score:
            return

        und_runner = UnderwritingRunner.objects.filter(
            application_xid=self.application.application_xid
        ).last()
        if und_runner and und_runner.http_status_code in (200,201):
            return

        try:
            url = '/v1/cde/applications/{}/init'.format(self.application.id)
            headers = {
                "Content-Type": "application/json",
                "Authorization": self.CDE_AUTH,
            }

            customer = self.application.customer
            device = customer.device_set.last()

            address_geolocation = AddressGeolocation.objects.filter(
                application_id=self.application.id
            ).last()
            address_payload = {
                'latitude': None,
                'longitude': None,
                'kabupaten': None,
                'kecamatan': None,
                'kelurahan': None,
                'provinsi': None,
                'kode_pos': None,
            }
            if address_geolocation:
                address_payload = {
                    'latitude': address_geolocation.latitude,
                    'longitude': address_geolocation.longitude,
                    'kabupaten': address_geolocation.kabupaten,
                    'kecamatan': address_geolocation.kecamatan,
                    'kelurahan': address_geolocation.kelurahan,
                    'provinsi': address_geolocation.provinsi,
                    'kode_pos': address_geolocation.kodepos,
                }

            job_start = None
            if self.application.job_start:
                job_start = self.application.job_start.strftime('%d-%m-%Y')

            payload = {
                'fullname': self.application.fullname,
                'dob': self.application.dob.strftime('%d-%m-%Y'),
                'birth_place': self.application.birth_place,
                'email': self.application.email,
                'gender': self.application.gender,
                'address': {
                    'street_num': self.application.address_street_num,
                    'provinsi': self.application.address_provinsi,
                    'kabupaten': self.application.address_kabupaten,
                    'kecamatan': self.application.address_kecamatan,
                    'kelurahan': self.application.address_kelurahan,
                    'kode_pos': self.application.address_kodepos,
                },
                'address_geolocation': address_payload,
                'marital_status': self.application.marital_status,
                'android_id': device.android_id,
                'mobile_phone_1': self.application.mobile_phone_1,
                'mobile_phone_2': self.application.mobile_phone_2,
                'spouse_name': self.application.spouse_name,
                'spouse_mobile_phone': self.application.spouse_mobile_phone,
                'mother_maiden_name': customer.mother_maiden_name,
                'kin_name': self.application.kin_name,
                'kin_mobile_phone': self.application.kin_mobile_phone,
                'kin_relationship': self.application.kin_relationship,
                'close_kin_name': self.application.close_kin_name,
                'close_kin_mobile_phone': self.application.close_kin_mobile_phone,
                'job_type': self.application.job_type,
                'job_industry': self.application.job_industry,
                'job_description': self.application.job_description,
                'partner_name': 'default',
                'company_name': self.application.company_name,
                'company_phone_no': self.application.company_phone_number,
                'job_start': job_start,
                'payday': self.application.payday,
                'last_education': self.application.last_education,
                'monthly_income': self.application.monthly_income,
                'monthly_expenses': self.application.monthly_expenses,
                'total_current_debt': self.application.total_current_debt,
                'bank_name': self.application.bank_name,
                'bank_account_no': self.application.bank_account_number,
                'loan_purpose': self.application.loan_purpose,
            }

            response = self.post(url, headers, payload).json()

            if response['error']:
                logger.info(
                    {
                        'action': 'CDE - Hit Error',
                        'data': {
                            'application_id': self.application.id,
                            'erorr': response['error'],
                        },
                    }
                )
                raise CDEError("Failed to hit CDE")

            logger.info(
                {
                    'action': 'CDE - Hit',
                    'data': {
                        'application_id': self.application.id,
                        'application_status': self.application.application_status_id,
                    },
                }
            )
        except (
            CDEError,
            urllib3.exceptions.ReadTimeoutError,
            requests.exceptions.ConnectionError,
            requests.exceptions.ConnectTimeout,
        ) as e:
            logger.info(
                {
                    'action': 'CDE - Hit Error',
                    'data': {'application_id': self.application.id, 'message': str(e)},
                }
            )
            get_julo_sentry_client().captureException()
