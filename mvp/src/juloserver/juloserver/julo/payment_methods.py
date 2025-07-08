import logging
from builtins import object
from collections import namedtuple
from typing import (
    List,
    Set,
)

from django.conf import settings

from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting
from juloserver.utilities.services import gen_probability

from .banks import BankCodes

logger = logging.getLogger(__name__)


class PaymentMethodCodes(BankCodes):

    ALFAMART = settings.FASPAY_PREFIX_ALFAMART
    BCA = settings.PREFIX_BCA
    BRI = settings.FASPAY_PREFIX_BRI
    DOKU = '1001'
    INDOMARET = settings.FASPAY_PREFIX_INDOMARET
    MANDIRI = settings.FASPAY_PREFIX_MANDIRI
    PERMATA = settings.FASPAY_PREFIX_PERMATA
    PERMATA1 = settings.FASPAY_PREFIX_OLD_PERMATA
    MAYBANK = settings.FASPAY_PREFIX_MAYBANK
    BNI = settings.FASPAY_PREFIX_BNI
    BNI_V2 = settings.FASPAY_PREFIX_BNI_V2
    GOPAY = '1002'
    OLD_INDOMARET = '319237'
    OVO = '1003'
    OVO_TOKENIZATION = '1006'
    GOPAY_TOKENIZATION = '1004'
    DANA = '1005'
    DANA_BILLER = '880'
    CIMB_NIAGA = settings.PREFIX_CIMB_NIAGA
    ONEKLIK_BCA = settings.PREFIX_ONEKLIK_BCA
    NOT_SUPPORT_REFINANCING_OR_WAIVER = (
        ALFAMART, INDOMARET, OLD_INDOMARET, BNI, GOPAY, OVO, GOPAY_TOKENIZATION, DANA)
    MANDIRI_DOKU = settings.PREFIX_MANDIRI_DOKU
    BRI_DOKU = settings.PREFIX_BRI_DOKU
    PERMATA_DOKU = settings.PREFIX_PERMATA_DOKU


class PartnerServiceIds:
    MANDIRI_DOKU = settings.PARTNER_SERVICE_ID_MANDIRI_DOKU
    BRI_DOKU = settings.PARTNER_SERVICE_ID_BRI_DOKU
    PERMATA_DOKU = settings.PARTNER_SERVICE_ID_PERMATA_DOKU


class PartnerServiceIds:
    MANDIRI_DOKU = settings.PARTNER_SERVICE_ID_MANDIRI_DOKU
    BRI_DOKU = settings.PARTNER_SERVICE_ID_BRI_DOKU
    PERMATA_DOKU = settings.PARTNER_SERVICE_ID_PERMATA_DOKU


AxiataIcarePaymentMethod = (
    BankCodes.BCA,
    BankCodes.PERMATA,
    BankCodes.MAYBANK,
    PaymentMethodCodes.ALFAMART,
    PaymentMethodCodes.INDOMARET
    )

SecondaryMethodName = [
    "ALFAMART",
    "INDOMARET",
    "Gopay",
    "OVO",
    "OVO Tokenization",
    "GoPay Tokenization",
    "DANA",
    "DANA Biller",
    "OneKlik BCA",
]

mf_excluded_payment_method_codes = {BankCodes.CIMB_NIAGA,
                                    BankCodes.MANDIRI,
                                    BankCodes.BNI,
                                    BankCodes.BTN,
                                    BankCodes.MEGA,
                                    802,
                                    settings.FASPAY_PREFIX_OLD_INDOMARET,
                                    BankCodes.SYARIAH_MANDIRI,
                                    BankCodes.SINARMAS}

PaymentMethod = namedtuple(
    'PaymentMethod', ['code', 'name', 'faspay_payment_code', 'payment_code', 'type', 'vendor']
)

active_payment_method_name_list = [
    "Bank BCA",
    "Bank BRI",
    "Bank MAYBANK",
    "Bank BNI",
    "Bank MANDIRI",
    "PERMATA Bank",
    "Bank CIMB Niaga",
    "ALFAMART",
    "INDOMARET",
    "OVO",
    "OVO Tokenization",
    "Gopay",
    "GoPay Tokenization",
    "DANA",
    "DANA Biller",
    "Autodebet BCA",
    "Autodebet BRI",
    "Autodebet BNI",
    "Autodebet GOPAY",
    "Autodebet MANDIRI",
    "Autodebet DANA",
    "OneKlik BCA",
]

FaspayPaymentMethod = [
    PaymentMethodCodes.MANDIRI,
    PaymentMethodCodes.BRI,
    PaymentMethodCodes.PERMATA,
]

DokuPaymentMethod = [
    PaymentMethodCodes.MANDIRI_DOKU,
    PaymentMethodCodes.BRI_DOKU,
    PaymentMethodCodes.PERMATA_DOKU,
]

OVOTokenizationPaymentMethod = PaymentMethod(
    code=PaymentMethodCodes.OVO_TOKENIZATION,
    name="OVO Tokenization",
    faspay_payment_code=PaymentMethodCodes.OVO_TOKENIZATION,
    payment_code=PaymentMethodCodes.OVO_TOKENIZATION,
    type='non_bank',
    vendor=None,
)

PaymentMethods = (

    PaymentMethod(
        code=BankCodes.BCA,
        name="Bank BCA",
        faspay_payment_code=PaymentMethodCodes.BCA,
        payment_code=PaymentMethodCodes.BCA,
        type='bank',
        vendor=None,
    ),
    PaymentMethod(
        code=BankCodes.CIMB_NIAGA,
        name="Bank CIMB Niaga",
        faspay_payment_code=PaymentMethodCodes.CIMB_NIAGA,
        payment_code=PaymentMethodCodes.CIMB_NIAGA,
        type='bank',
        vendor=None,
    ),
    PaymentMethod(
        code=BankCodes.MANDIRI,
        name="Bank MANDIRI",
        faspay_payment_code=PaymentMethodCodes.MANDIRI,
        payment_code=PaymentMethodCodes.MANDIRI,
        type='bank',
        vendor='FASPAY',
    ),
    PaymentMethod(
        code=BankCodes.MANDIRI,
        name="Bank MANDIRI",
        faspay_payment_code=PaymentMethodCodes.MANDIRI_DOKU,
        payment_code=PaymentMethodCodes.MANDIRI_DOKU,
        type='bank',
        vendor='DOKU',
    ),
    PaymentMethod(
        code=BankCodes.BNI,
        name="Bank BNI",
        faspay_payment_code=PaymentMethodCodes.BNI,
        payment_code=PaymentMethodCodes.BNI,
        type='bank',
        vendor=None,
    ),
    PaymentMethod(
        code=BankCodes.BRI,
        name="Bank BRI",
        faspay_payment_code=PaymentMethodCodes.BRI,
        payment_code=PaymentMethodCodes.BRI,
        type='bank',
        vendor='FASPAY',
    ),
    PaymentMethod(
        code=BankCodes.BRI,
        name="Bank BRI",
        faspay_payment_code=PaymentMethodCodes.BRI_DOKU,
        payment_code=PaymentMethodCodes.BRI_DOKU,
        type='bank',
        vendor='DOKU',
    ),
    PaymentMethod(
        code=BankCodes.BTN,
        name="Bank Tabungan Negara",
        faspay_payment_code=None,
        payment_code=None,
        type='bank',
        vendor=None,
    ),
    PaymentMethod(
        code=BankCodes.PERMATA,
        name="PERMATA Bank",
        faspay_payment_code=PaymentMethodCodes.PERMATA,
        payment_code=PaymentMethodCodes.PERMATA,
        type='bank',
        vendor='FASPAY',
    ),
    PaymentMethod(
        code=BankCodes.PERMATA,
        name="PERMATA Bank",
        faspay_payment_code=PaymentMethodCodes.PERMATA_DOKU,
        payment_code=PaymentMethodCodes.PERMATA_DOKU,
        type='bank',
        vendor='DOKU',
    ),
    PaymentMethod(
        code=BankCodes.MEGA,
        name="Bank MEGA",
        faspay_payment_code=None,
        payment_code=None,
        type='bank',
        vendor=None,
    ),
    PaymentMethod(
        code=BankCodes.SYARIAH_MANDIRI,
        name="Bank SYARIAH MANDIRI",
        faspay_payment_code=None,
        payment_code=None,
        type='bank',
        vendor=None,
    ),
    PaymentMethod(
        code=BankCodes.SINARMAS,
        name="Bank SINARMAS",
        faspay_payment_code=None,
        payment_code=None,
        type='bank',
        vendor=None,
    ),
    PaymentMethod(
        code=BankCodes.MAYBANK,
        name="Bank MAYBANK",
        faspay_payment_code=PaymentMethodCodes.MAYBANK,
        payment_code=PaymentMethodCodes.MAYBANK,
        type='bank',
        vendor=None,
    ),
    PaymentMethod(
        code=PaymentMethodCodes.DOKU,
        name="Doku",
        faspay_payment_code=PaymentMethodCodes.DOKU,
        payment_code=PaymentMethodCodes.DOKU,
        type='non_bank',
        vendor=None,
    ),
    PaymentMethod(
        code=PaymentMethodCodes.INDOMARET,
        name="INDOMARET",
        faspay_payment_code=PaymentMethodCodes.INDOMARET,
        payment_code=PaymentMethodCodes.INDOMARET,
        type='non_bank',
        vendor=None,
    ),
    PaymentMethod(
        code=PaymentMethodCodes.ALFAMART,
        name="ALFAMART",
        faspay_payment_code=PaymentMethodCodes.ALFAMART,
        payment_code=PaymentMethodCodes.ALFAMART,
        type='non_bank',
        vendor=None,
    ),
    PaymentMethod(
        code=PaymentMethodCodes.GOPAY,
        name="Gopay",
        faspay_payment_code=PaymentMethodCodes.GOPAY,
        payment_code=PaymentMethodCodes.GOPAY,
        type='non_bank',
        vendor=None,
    ),
    PaymentMethod(
        code=PaymentMethodCodes.OVO,
        name="OVO",
        faspay_payment_code=PaymentMethodCodes.OVO,
        payment_code=PaymentMethodCodes.OVO,
        type='non_bank',
        vendor=None,
    ),
    OVOTokenizationPaymentMethod,
    PaymentMethod(
        code=PaymentMethodCodes.DANA,
        name="DANA",
        faspay_payment_code=PaymentMethodCodes.DANA,
        payment_code=PaymentMethodCodes.DANA,
        type='non_bank',
        vendor=None,
    ),
    PaymentMethod(
        code=PaymentMethodCodes.DANA_BILLER,
        name="DANA Biller",
        faspay_payment_code=PaymentMethodCodes.DANA_BILLER,
        payment_code=PaymentMethodCodes.DANA_BILLER,
        type='non_bank',
        vendor=None,
    ),
    PaymentMethod(
        code=PaymentMethodCodes.ONEKLIK_BCA,
        name="OneKlik BCA",
        faspay_payment_code=PaymentMethodCodes.ONEKLIK_BCA,
        payment_code=PaymentMethodCodes.ONEKLIK_BCA,
        type='bank',
        vendor=None,
    ),
)


class PaymentMethodManager(object):

    @classmethod
    def get_or_none(cls, code):
        for payment_method in PaymentMethods:
            if payment_method.code == code:
                logger.debug({
                    'payment_method': 'found',
                    'code': payment_method.code
                })
                return payment_method
        logger.warn({
            'payment_method': 'not_found',
            'code': code
        })
        return None

    @classmethod
    def get_faspay_bank_list(cls, type):
        payment_methods = []
        for payment_method in PaymentMethods:
            if payment_method.faspay_payment_code is not None and payment_method.type == type:
                payment_methods.append(payment_method)

        return payment_methods

    @classmethod
    def get_available_payment_method(cls, primary_bank_code):
        available_list = []
        for payment_method in PaymentMethods:
            if payment_method and payment_method.faspay_payment_code is not None:
                bank_code = payment_method.code
                if primary_bank_code == BankCodes.BCA and bank_code == BankCodes.PERMATA:
                    continue
                elif primary_bank_code == BankCodes.PERMATA and bank_code == BankCodes.BCA:
                    continue
                elif primary_bank_code != BankCodes.BNI and bank_code == BankCodes.BNI:
                    continue
                if bank_code == primary_bank_code:
                    available_list.insert(0, payment_method)
                else:
                    available_list.append(payment_method)
        return available_list

    @classmethod
    def get_available_axiata_icare_payment_method(cls):
        available_list = []
        for payment_method in PaymentMethods:
            if payment_method and payment_method.faspay_payment_code is not None:
                if payment_method.code in AxiataIcarePaymentMethod:
                    available_list.append(payment_method)
        return available_list

    @classmethod
    def get_experiment_payment_method(cls, customer_type):
        """return payment method is satisfied in repayment traffic setting"""
        traffic_setting = (
            FeatureSetting.objects.filter(feature_name=FeatureNameConst.REPAYMENT_TRAFFIC_SETTING)
            .cache(timeout=60 * 60 * 24)
            .first()
        )

        available_list = []
        if not (traffic_setting and traffic_setting.is_active and traffic_setting.parameters):
            return available_list

        traffic_setting = traffic_setting.parameters
        traffic = traffic_setting.get(customer_type) or traffic_setting.get('other')

        if not traffic:
            return available_list

        # Generate the probability-based selection from the traffic settings
        data = {bank_code: val['prob'] for bank_code, val in traffic['settings'].items()}
        method = gen_probability(data)
        backup_methods = traffic['settings'][method]['selected']

        primary_bank_code = None
        backup_bank_codes = []

        for payment_method in PaymentMethods:
            if payment_method.payment_code == method:
                primary_bank_code = payment_method.code
            elif payment_method.payment_code in backup_methods:
                backup_bank_codes.append(payment_method.code)
            elif payment_method.name not in SecondaryMethodName:
                continue
            available_list.append(payment_method)

        return primary_bank_code, backup_bank_codes, available_list

    @classmethod
    def get_payment_code_for_payment_method(cls, code):
        for payment_method in PaymentMethods:
            if code in {settings.FASPAY_PREFIX_OLD_ALFAMART,
                        PaymentMethodCodes.OLD_INDOMARET,
                        PaymentMethodCodes.MAYBANK
                        }:
                return True
            elif code == payment_method.code and payment_method.faspay_payment_code is not None:
                return True

        return False

    @classmethod
    def get_all_payment_methods(cls):
        available_list = []
        for payment_method in PaymentMethods:
            if payment_method and payment_method.faspay_payment_code is not None:
                if payment_method.code == BankCodes.BNI:
                    continue
                available_list.append(payment_method)

        return available_list

    @classmethod
    def filter_payment_methods_by_payment_code(cls, payment_codes: Set[str]) -> List[PaymentMethod]:
        payment_methods = []
        for payment_method in PaymentMethods:
            if payment_method.payment_code in payment_codes:
                payment_methods.append(payment_method)

        return payment_methods
