from django.test import TestCase

from juloserver.payment_point.constants import (
    FeatureNameConst as PaymentPointFeatureConst,
    TransactionMethodCode,
)
from juloserver.julo.tests.factories import FeatureSettingFactory
from juloserver.payment_point.services.ewallet_related import (
    is_applied_ayc_switching_flow,
    is_applied_xfers_switching_flow,
)


class TestEwalletRelatedServices(TestCase):
    def setUp(self):
        pass

    def test_is_applied_ayc_switching_flow(self):
        # set data
        customer_id = 123
        params = {'is_active_prod_testing': True, 'prod_testing_customer_ids': []}
        fs = FeatureSettingFactory(
            feature_name=PaymentPointFeatureConst.SEPULSA_AYOCONNECT_EWALLET_SWITCH,
            is_active=False,
            parameters=params,
        )

        # wrong transaction code
        result = is_applied_ayc_switching_flow(
            customer_id=customer_id,
            transaction_method=-1,
        )
        self.assertFalse(result)

        # fs not active
        result = is_applied_ayc_switching_flow(
            customer_id=customer_id,
            transaction_method=TransactionMethodCode.DOMPET_DIGITAL.code,
        )
        self.assertFalse(result)

        # fs active and prod-test is active but no customer ids in setting
        fs.is_active = True
        fs.save()

        result = is_applied_ayc_switching_flow(
            customer_id=customer_id,
            transaction_method=TransactionMethodCode.DOMPET_DIGITAL.code,
        )
        self.assertFalse(result)

        # fs active and prod-test is active with customer ids set
        fs.parameters['prod_testing_customer_ids'] = [customer_id]
        fs.save()

        result = is_applied_ayc_switching_flow(
            customer_id=customer_id,
            transaction_method=TransactionMethodCode.DOMPET_DIGITAL.code,
        )
        self.assertTrue(result)

        # also works with str customer id
        fs.parameters['prod_testing_customer_ids'] = ['123']
        fs.save()

        result = is_applied_ayc_switching_flow(
            customer_id=customer_id,
            transaction_method=TransactionMethodCode.DOMPET_DIGITAL.code,
        )
        self.assertTrue(result)

        # fs active and prod-test is inactive
        fs.parameters['is_active_prod_testing'] = False
        fs.save()

        result = is_applied_ayc_switching_flow(
            customer_id=customer_id,
            transaction_method=TransactionMethodCode.DOMPET_DIGITAL.code,
        )
        self.assertTrue(result)

        result = is_applied_ayc_switching_flow(
            customer_id=999999,
            transaction_method=TransactionMethodCode.DOMPET_DIGITAL.code,
        )
        self.assertTrue(result)

    def test_is_applied_xfers_switching_flow(self):
        # set data
        customer_id = 123
        params = {'is_whitelist_active': True, 'whitelist_customer_ids': []}
        fs = FeatureSettingFactory(
            feature_name=PaymentPointFeatureConst.SEPULSA_XFERS_EWALLET_SWITCH,
            is_active=False,
            parameters=params,
        )

        # wrong transaction code
        result = is_applied_xfers_switching_flow(
            customer_id=customer_id,
            transaction_method=-1,
        )
        self.assertFalse(result)

        # fs not active
        result = is_applied_xfers_switching_flow(
            customer_id=customer_id,
            transaction_method=TransactionMethodCode.DOMPET_DIGITAL.code,
        )
        self.assertFalse(result)

        # fs active and prod-test is active but no customer ids in setting
        fs.is_active = True
        fs.save()

        result = is_applied_xfers_switching_flow(
            customer_id=customer_id,
            transaction_method=TransactionMethodCode.DOMPET_DIGITAL.code,
        )
        self.assertFalse(result)

        # fs active and prod-test is active with customer ids set
        fs.parameters['whitelist_customer_ids'] = [customer_id]
        fs.save()

        result = is_applied_xfers_switching_flow(
            customer_id=customer_id,
            transaction_method=TransactionMethodCode.DOMPET_DIGITAL.code,
        )
        self.assertTrue(result)

        # also works with str customer id
        fs.parameters['whitelist_customer_ids'] = ['123']
        fs.save()

        result = is_applied_xfers_switching_flow(
            customer_id=customer_id,
            transaction_method=TransactionMethodCode.DOMPET_DIGITAL.code,
        )
        self.assertTrue(result)

        # fs active and prod-test is inactive
        fs.parameters['is_whitelist_active'] = False
        fs.save()

        result = is_applied_xfers_switching_flow(
            customer_id=customer_id,
            transaction_method=TransactionMethodCode.DOMPET_DIGITAL.code,
        )
        self.assertTrue(result)

        result = is_applied_xfers_switching_flow(
            customer_id=999999,
            transaction_method=TransactionMethodCode.DOMPET_DIGITAL.code,
        )
        self.assertTrue(result)
