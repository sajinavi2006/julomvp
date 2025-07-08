from builtins import str
from builtins import object
import logging
import requests
from datetime import datetime
from decimal import Decimal


from django.conf import settings
from suds.client import Client

from juloserver.application_flow.constants import PartnerNameConstant

from .exceptions import JuloException
from .models import Collateral, Partner, FeatureSetting
from .utils import generate_guid, generate_hmac
from juloserver.merchant_financing.constants import MFFeatureSetting

logger = logging.getLogger(__name__)


def get_doku_client():
    partner = Partner.objects.get(name=PartnerConstant.DOKU_PARTNER)
    token = partner.token
    systrace = partner.systrace
    return DokuClient(
        settings.DOKU_BASE_URL,
        settings.DOKU_CLIENT_ID,
        settings.DOKU_CLIENT_SECRET,
        settings.DOKU_ACCOUNT_ID,
        settings.DOKU_SHARED_KEY,
        token,
        systrace)


def get_bfi_client():
    return BfiClient(
        settings.BFI_BASE_URL,
        settings.BFI_CLIENT_ID)


def get_partners_for_partner_sms():
    sms_partner_list = [PartnerNameConstant.CERMATI, PartnerConstant.RENTEE,
            PartnerNameConstant.OLX, PartnerNameConstant.CEKAJA,
            PartnerNameConstant.USAHAKU99, PartnerNameConstant.J1]
    partner_ids = Partner.objects.filter(name__in=sms_partner_list)\
        .values_list('id', flat=True)
    return partner_ids


class DokuAccountType(object):
    NORMAL = 1000000
    PREMIUM = 10000000
    LIMIT_DOKU = 100000


class PartnerConstant(object):
    DOKU_PARTNER = "doku"
    TOKOPEDIA_PARTNER = "tokopedia"
    BFI_PARTNER = "bfi"
    GRAB_PARTNER = "grab"
    BRI_PARTNER = "bri"
    JTP_PARTNER = "jtp"
    SEPULSA_PARTNER = "sepulsa"
    GRAB_FOOD_PARTNER = "grabfood"
    ATURDUIT_PARTNER = "aturduit"
    LAKU6_PARTNER = "laku6"
    PEDE_PARTNER = "pede"
    ICARE_PARTNER = "icare"
    AXIATA_PARTNER = "axiata"
    BCA_PARTNER = "bca"
    RENTEE = 'rentee'
    IPRICE = 'iprice'
    JULOVERS = 'julovers'  # not a real partner
    LINKAJA_PARTNER = "linkaja"
    KLOP_PARTNER = "klop"
    JULOSHOP = 'juloshop'
    AXIATA_PARTNER_IF = "skrtp_axiata_if"
    AXIATA_PARTNER_SCF = "skrtp_axiata_scf"
    GOSEL = "gojektsel"
    DANA = "dana"

    @classmethod
    def all(cls):
        return [cls.DOKU_PARTNER, cls.TOKOPEDIA_PARTNER,
                cls.BFI_PARTNER, cls.GRAB_PARTNER,
                cls.BRI_PARTNER,  cls.JTP_PARTNER,
                cls.ATURDUIT_PARTNER]

    @classmethod
    def collateral_partners(cls):
        return [cls.BFI_PARTNER]
    @classmethod
    def lender_partners(cls):
        return [cls.BRI_PARTNER, cls.JTP_PARTNER, cls.GRAB_PARTNER]
    @classmethod
    def lender_exclusive_by_product(cls):
        return [cls.GRAB_PARTNER, cls.BRI_PARTNER]

    @classmethod
    def form_partner(cls):
        return [cls.ICARE_PARTNER, cls.AXIATA_PARTNER]

    @classmethod
    def referral_partner(cls):
        return [cls.TOKOPEDIA_PARTNER]

    @classmethod
    def excluded_for_crm(cls):
        return [cls.ICARE_PARTNER, cls.AXIATA_PARTNER, cls.GRAB_PARTNER]

    @classmethod
    def excluded_partner_intelix(cls):
        return [cls.AXIATA_PARTNER]

    @classmethod
    def excluded_for_crm_intelix(cls):
        return [cls.AXIATA_PARTNER, cls.GRAB_PARTNER]

    @classmethod
    def loan_halt_or_resume(cls):
        return [cls.GRAB_PARTNER]

    @classmethod
    def list_partner_merchant_financing_standard(cls):
        feature_setting = FeatureSetting.objects.filter(
            feature_name=MFFeatureSetting.STANDARD_PRODUCT_API_CONTROL,
            is_active=True,
        ).last()
        list_partnership_mf_std = []
        if feature_setting and feature_setting.parameters:
            list_partnership_mf_std = feature_setting.parameters.get('api_v2')

        return list_partnership_mf_std


class DokuClient(object):
    def __init__(
            self, base_url, client_id, client_secret, account_id,
            shared_key, token, systrace):
        self.base_url = base_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.account_id = account_id
        self.shared_key = shared_key
        self.token = self.get_fresh_token() if token is None or token == '' else token
        self.systrace = systrace

    def post_request(self, url, data=None, json=None, **kwargs):
        """Wrapper for requests.post, matching its parameters"""
        try:
            r = requests.post(url, data=data, json=json, **kwargs)
            if not (200 <= r.status_code <= 299):
                raise JuloException(r.text)
            response = r.json()
        except Exception as e:
            raise JuloException(e)
        return response

    def get_fresh_token(self):
        url = self.base_url + 'signon'
        systrace = generate_guid()
        keystring = '{}{}{}'.format(self.client_id, self.shared_key, systrace)
        words = generate_hmac(keystring, self.client_secret)
        data = {
            "clientId": self.client_id,
            "clientSecret": self.client_secret,
            "sharedKey": self.shared_key,
            "systrace": systrace,
            "words": words,
            "version": 1.0,
            "responseType": "JSON"
        }
        logger.debug(data)
        response = self.post_request(url, data=data)

        if response['responseCode'] != "0000":
            error_message = response['responseMessage']['en']
            raise JuloException(error_message, response['responseCode'])

        partner = Partner.objects.get(name=PartnerConstant.DOKU_PARTNER)
        partner.token = response['accessToken']
        partner.systrace = systrace
        partner.save()

        return response['accessToken']

    def get_customer_info(self, account_id):
        url = self.base_url + "custinquiry"
        keystring = '{}{}{}{}'.format(self.client_id, self.systrace, self.shared_key, account_id)
        words = generate_hmac(keystring, self.client_secret)

        data = {
            "clientId": self.client_id,
            "accessToken": self.token,
            "accountId": account_id,
            "words": words,
        }
        response = self.post_request(url, data=data)

        if response['responseCode'] == "3010":
            refresh_token = self.get_fresh_token()
            if refresh_token:
                return self.get_customer_info(account_id)

        if response['responseCode'] != '0000':
            del data["clientId"]
            del data["accessToken"]
            data['url'] = url
            logger.error(data)
            raise JuloException(response['responseMessage']['en'], response['responseCode'])

        return response

    def check_balance(self, account_id):
        url = self.base_url + "custsourceoffunds"
        keystring = '{}{}{}{}'.format(
                    self.client_id, self.systrace,
                    self.shared_key, account_id)
        words = generate_hmac(keystring, self.client_secret)
        data = {
            "clientId": self.client_id,
            "accessToken": self.token,
            "accountId": account_id,
            "words": words
        }
        response = self.post_request(url, data=data)

        if response['responseCode'] == "3010":
            refresh_token = self.get_fresh_token()
            if refresh_token:
                return self.check_balance(account_id)

        if response['responseCode'] != "0000":
            error_message = response['responseMessage']['en']
            del data["clientId"]
            del data["accessToken"]
            data['url'] = url
            logger.error(data)
            raise JuloException(error_message, response['responseCode'])

        return response

    def check_julo_balance(self):
        url = self.base_url + "custsourceoffunds"
        keystring = '{}{}{}{}'.format(
                    self.client_id, self.systrace,
                    self.shared_key, self.account_id)
        words = generate_hmac(keystring, self.client_secret)
        data = {
            "clientId": self.client_id,
            "accessToken": self.token,
            "accountId": self.account_id,
            "words": words
        }
        response = self.post_request(url, data=data)

        if response['responseCode'] == "3010":
            refresh_token = self.get_fresh_token()
            if refresh_token:
                return self.check_julo_balance(self.account_id)

        if response['responseCode'] != "0000":
            error_message = response['responseMessage']['en']
            del data["clientId"]
            del data["accessToken"]
            data['url'] = url
            logger.error(data)
            raise JuloException(error_message, response['responseCode'])

        return response

    def disbursement(self, cust_account_id, transaction_id, amount):
        amount = '{:.2f}'.format(Decimal(amount))
        url = self.base_url + "cashback"
        keystring = '{}{}{}{}{}'.format(
                    self.client_id, transaction_id,
                    self.systrace, self.shared_key, amount)
        words = generate_hmac(keystring, self.client_secret)
        data = {
            "clientId": self.client_id,
            "accessToken": self.token,
            "accountId": cust_account_id,
            "words": words,
            "amount": amount,
            "transactionId": transaction_id
        }
        response = self.post_request(url, data=data)

        if response['responseCode'] != "0000":
            error_message = response['responseMessage']['en']
            del data["clientId"]
            del data["accessToken"]
            data['url'] = url
            logger.error(data)
            raise JuloException(str(error_message), response['responseCode'])

        return response

    def transfer(self, cust_account_id, transaction_id, amount):
        amount = '{:.2f}'.format(Decimal(amount))
        url = self.base_url + "sendmoney/init"
        keystring = '{}{}{}{}{}{}{}'.format(
                    cust_account_id, self.client_id,
                    transaction_id, self.systrace,
                    self.shared_key, self.account_id, amount)
        words = generate_hmac(keystring, self.client_secret)
        data = {
            "clientId": self.client_id,
            "accessToken": self.token,
            "senderAccountId": cust_account_id,
            "receiverAccountId": self.account_id,
            "transactionId": transaction_id,
            "amount": amount,
            "words": words
        }
        response = self.post_request(url, data=data)

        if response['responseCode'] != "0000":
            error_message = response['responseMessage']['en']
            del data["clientId"]
            del data["accessToken"]
            data['url'] = url
            logger.error(data)
            raise JuloException(str(error_message), response['responseCode'])

        return response

    def confirm_transfer(self, tracking_id):
        url = self.base_url + "sendmoney/pay"
        keystring = '{}{}{}{}'.format(tracking_id, self.client_id, self.systrace, self.shared_key)
        words = generate_hmac(keystring, self.client_secret)
        data = {
            "clientId": self.client_id,
            "accessToken": self.token,
            "words": words,
            "trackingId": tracking_id
        }
        response = self.post_request(url, data=data)

        if response['responseCode'] != "0000":
            error_message = response['responseMessage']['en']
            del data["clientId"]
            del data["accessToken"]
            data['url'] = url
            logger.error(data)
            raise JuloException(str(error_message), response['responseCode'])

        return response

    def check_activities(self, last_ref_id=None, start_date=None, end_date=None):
        url = self.base_url + "custactivities"
        keystring = '{}{}{}{}'.format(
                    self.client_id, self.systrace,
                    self.shared_key, self.account_id)
        words = generate_hmac(keystring, self.client_secret)
        data = {
            "clientId": self.client_id,
            "accessToken": self.token,
            "accountId": self.account_id,
            "words": words,
            "lastRefId": last_ref_id,
            "criteriaStartDate": start_date,
            "criteriaEndDate": end_date,
        }
        response = self.post_request(url, data=data)

        if response['responseCode'] == "3010":
            refresh_token = self.get_fresh_token()
            if refresh_token:
                return self.check_activities()
        if response['responseCode'] != "0000":
            error_message = response['responseMessage']['en']
            del data["clientId"]
            del data["accessToken"]
            data['url'] = url
            logger.error(data)
            raise JuloException(str(error_message), response['responseCode'])

        return response


class BfiClient(object):
    def __init__(self, base_url, partner_id):
        self.base_url = base_url
        self.partner_id = partner_id

    def send_data_application(self, application):
        client = Client(self.base_url)

        partner_id = self.partner_id
        address = '{} {} {} {} {}'.format(
            application.address_street_num,
            application.address_provinsi,
            application.address_kabupaten,
            application.address_kecamatan,
            application.address_kelurahan,
            application.address_kodepos)

        collateral = Collateral.objects.get_or_none(application=application)
        if collateral is None:
            raise JuloException('collateral is None')

        dc = client.factory.create('DataCustomer')
        dc.PartnerID = partner_id
        dc.Datetime = datetime.now()
        dc.Funding = application.loan_amount_request
        dc.CustDateOfBirth = datetime.combine(application.dob, datetime.min.time())
        dc.MonthlyIncome = application.monthly_income
        dc.Tenor = application.loan_duration_request
        dc.Installment = 0
        dc.CustomerName = application.fullname
        dc.EmailCustomer = application.email
        dc.CustomerAddress = address
        dc.CustomerNumber1 = application.mobile_phone_1
        dc.CustomerNumber2 = application.mobile_phone_2
        dc.SubmissionID = application.application_xid
        dc.ListingID = ''
        dc.SellerName = ''
        dc.SellerNumber = ''
        dc.EmailSeller = ''
        dc.SellerAddress = ''
        dc.Product = collateral.collateral_type
        dc.VehicleType = collateral.collateral_model_name
        dc.Year = collateral.collateral_model_year
        dc.LinkIklan = ''
        dc.ZipCode = ''
        dc.City = ''
        dc.Kelurahan = ''
        dc.Kecamatan = ''

        result = client.service.RegisterApplication(dc)
        logger.info({
            'status': 'send data to partner bfi',
            'application': application.id,
        })

        return result
