import datetime
from factory import Iterator

from unittest.mock import patch

from django.test import TestCase

from juloserver.account.tests.factories import AccountFactory, AccountPropertyFactory
from juloserver.disbursement.services.daily_disbursement_limit import (
    check_daily_limit,
    check_daily_disbursement_limit_by_transaction_method,
    check_customer_disbursement_whitelist,
    process_daily_disbursement_limit_whitelist,
)
from juloserver.disbursement.models import (
    DailyDisbursementLimitWhitelist,
    DailyDisbursementLimitWhitelistHistory
)
from juloserver.julo.tests.factories import (
    FeatureSettingFactory,
    DailyDisbursementScoreLimitFactory,
    PdBscoreModelResultFactory,
)
from juloserver.disbursement.tests.factories import (
    DailyDisbursementLimitWhitelistFactory,
    DailyDisbursementLimitWhitelistHistoryFactory,
)
from juloserver.julo.tests.factories import (
    AuthUserFactory,
)

SUB_FOLDER = "juloserver.disbursement.services.daily_disbursement_limit"


class TestDailyDisbursementLimit(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.account = AccountFactory()
        self.daily_disbursement_score_limit = DailyDisbursementScoreLimitFactory()
        self.fs = FeatureSettingFactory(
            feature_name='daily_disbursement_limit',
            is_active=True,
            parameters={"pgood": 0.88, "amount": 50000000000, "bscore": 0.6,
                        "message": "Saat ini belum ada Pemberi Dana yang dapat mendanai pinjaman ini. Sebagai platform yang menghubungkan Pemberi Dana dan Penerima Dana, kami akan terus mencarikan kesediaan dana untukmu.<br/>Terima kasih atas pengertiannya. Nantikan informasi terbaru di aplikasi JULO ya.",
                        "pgood_amount": 2000000, "bscore_amount": 2000000, "non_repeat_bscore_amount": 0,
                        "transaction_method": [1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15, 16, 17, 18, 19]}
        )
        self.whitelist_fs = FeatureSettingFactory(
            feature_name='daily_disbursement_limit_whitelist',
            is_active=False,
            parameters={}
        )
        self.bscore = PdBscoreModelResultFactory(
            customer_id=1234,
        )

    def test_check_daily_limit(self):
        # Bscore
        res = check_daily_limit('bscore', self.fs.parameters['bscore_amount'])
        self.assertEqual(res, True)

        self.fs.parameters = {"pgood_amount": 2000000, "bscore_amount": 100000}
        self.fs.save()
        res = check_daily_limit('bscore', self.fs.parameters['bscore_amount'])
        self.assertEqual(res, False)


        # Pgood
        res = check_daily_limit('pgood', self.fs.parameters['pgood_amount'])
        self.assertEqual(res, True)

        self.fs.parameters = {"pgood_amount": 100000, "bscore_amount": 100000}
        self.fs.save()
        self.daily_disbursement_score_limit.score_type = 'pgood'
        self.daily_disbursement_score_limit.save()
        res = check_daily_limit('pgood', self.fs.parameters['pgood_amount'])
        self.assertEqual(res, False)

        # Non-repeat Bscore
        self.fs.parameters = {"non_repeat_bscore_amount": 0}
        self.fs.save()
        res = check_daily_limit('non_repeat_bscore', self.fs.parameters['non_repeat_bscore_amount'])
        self.assertEqual(res, False)

    @patch(f'{SUB_FOLDER}.check_daily_limit')
    @patch(f'{SUB_FOLDER}.is_bscore')
    @patch(f'{SUB_FOLDER}.get_account_property_by_account')
    def test_store_daily_disbursement_score_limit_amount(self,
                                                         mock_get_account_property_by_account,
                                                         mock_is_bscore,
                                                         mock_check_daily_limit):
        mock_get_account_property_by_account.return_value = AccountPropertyFactory(
            account=self.account
        )
        mock_is_bscore.return_value = None
        mock_check_daily_limit.retun_value = True
        res, _, _ = check_daily_disbursement_limit_by_transaction_method(self.account, 1)
        self.assertEqual(res, False)
        # Second case pgood:  0.2, should return True
        mock_get_account_property_by_account.return_value = AccountPropertyFactory(
            account=self.account,
            pgood=0.2
        )
        mock_is_bscore.return_value = None
        mock_check_daily_limit.retun_value = True
        res, _, _ = check_daily_disbursement_limit_by_transaction_method(self.account, 1)
        self.assertEqual(res, True)

        # First case bscore:  0.9, should return True
        mock_get_account_property_by_account.return_value = AccountPropertyFactory(
            account=self.account
        )
        mock_is_bscore.return_value = PdBscoreModelResultFactory(
            id=12,
            pgood=0.9
        )
        mock_check_daily_limit.retun_value = True
        res, _, _ = check_daily_disbursement_limit_by_transaction_method(self.account, 1)
        self.assertEqual(res, False)

        # Second case bscore:  0.5, should return True
        mock_is_bscore.return_value = PdBscoreModelResultFactory(id=123, pgood=0.5)
        mock_check_daily_limit.return_value = True  # Fixed typo here

        res, _, _ = check_daily_disbursement_limit_by_transaction_method(self.account, 1)
        self.assertEqual(res, True)

    @patch(f'{SUB_FOLDER}.check_daily_limit')
    @patch(f'{SUB_FOLDER}.is_bscore')
    @patch(f'{SUB_FOLDER}.get_account_property_by_account')
    @patch(f'{SUB_FOLDER}.check_customer_disbursement_whitelist')
    def test_check_daily_disbursement_limit_whitelist(self,
        mock_whitelist_disbursement, mock_get_account_property_by_account,
        mock_is_bscore, mock_check_daily_limit
    ):
        self.whitelist_fs.update_safely(is_active=True)

        # Customer found in whitelist
        # P-good
        mock_whitelist_disbursement.return_value = True
        mock_get_account_property_by_account.return_value = AccountPropertyFactory(
            account=self.account,
            pgood=0.2
        )
        mock_is_bscore.return_value = None
        mock_check_daily_limit.retun_value = True
        res, _, _ = check_daily_disbursement_limit_by_transaction_method(self.account, 1)
        self.assertFalse(res)

        # B-score
        mock_whitelist_disbursement.return_value = True
        mock_is_bscore.return_value = PdBscoreModelResultFactory(pgood=0.5)
        mock_check_daily_limit.return_value = True

        res, _, _ = check_daily_disbursement_limit_by_transaction_method(self.account, 1)
        self.assertFalse(res)

        # Customer not found in whitelist
        mock_whitelist_disbursement.return_value = False
        mock_is_bscore.return_value = PdBscoreModelResultFactory(pgood=0.5)
        mock_check_daily_limit.return_value = True

        res, _, _ = check_daily_disbursement_limit_by_transaction_method(self.account, 1)
        self.assertTrue(res)

    def test_check_customer_disbursement_whitelist(self):
        is_whitelisted_customer = check_customer_disbursement_whitelist(customer_id=1000000001)
        self.assertFalse(is_whitelisted_customer)

        self.whitelist_fs.update_safely(is_active=True)
        is_whitelisted_customer = check_customer_disbursement_whitelist(customer_id=1000000001)
        self.assertFalse(is_whitelisted_customer)

        DailyDisbursementLimitWhitelistFactory(
            customer_id=1000000001, source='test', user_id=1234
        )
        is_whitelisted_customer = check_customer_disbursement_whitelist(customer_id=1000000001)
        self.assertTrue(is_whitelisted_customer)


class TestDailyDisbursementLimitWhitelistUpload(TestCase):
    def setUp(self):
        self.url = "tmp/disbursement/daily_disbursement_limit_whitelist.csv"
        self.user = AuthUserFactory()
        self.user_2 = AuthUserFactory()
        self.whitelist = DailyDisbursementLimitWhitelistFactory.create_batch(
            2,
            customer_id=Iterator([1000000011, 1000000012]),
            source="test",
            user_id=self.user_2.id
        )
        self.whitelist_history = DailyDisbursementLimitWhitelistHistoryFactory.create_batch(
            2,
            customer_id=Iterator([1000000011, 1000000012]),
            source="test",
            user_id=self.user_2.id,
            start_date=datetime.date(2025, 4, 10)
        )

    def oss_data_generator(self):
        yield [
            {"customer_id": 1000000001, "source": "test"},
            {"customer_id": 1000000002, "source": "test"}
        ]

        yield [
            {"customer_id": 1000000003, "source": "test"},
            {"customer_id": 1000000004, "source": "test"}
        ]

    @patch(f"{SUB_FOLDER}.load_data_from_presigned_url_oss")
    def test_success_process_whitelist(self, mock_load_file):
        mock_load_file.return_value = self.oss_data_generator()
        process_daily_disbursement_limit_whitelist(self.url, self.user.id)

        whitelist = DailyDisbursementLimitWhitelist.objects.all()
        whitelist_history = DailyDisbursementLimitWhitelistHistory.objects.all()
        self.assertEqual(whitelist.count(), 4)
        self.assertEqual(whitelist_history.count(), 4)

        deleted_whitelist = \
            DailyDisbursementLimitWhitelist.objects.filter(customer_id=1000000010).last()
        inserted_whitelist = \
            DailyDisbursementLimitWhitelist.objects.filter(customer_id=1000000001).last()

        self.assertIsNone(deleted_whitelist)
        self.assertIsNotNone(inserted_whitelist)

        inserted_whitelist_history = DailyDisbursementLimitWhitelistHistory.objects.last()
        self.assertEqual(inserted_whitelist_history.start_date, self.whitelist[0].cdate.date())

    @patch('django.db.transaction.atomic')
    @patch(f"{SUB_FOLDER}.load_data_from_presigned_url_oss")
    def test_unsuccess_process_whitelist(self, mock_load_file, mock_atomic):
        mock_atomic.side_effect = Exception()
        mock_load_file.return_value = self.oss_data_generator()
        with self.assertRaises(Exception):
            process_daily_disbursement_limit_whitelist(self.url, self.user.id)

            whitelist = DailyDisbursementLimitWhitelist.objects.all()
            whitelist_history = DailyDisbursementLimitWhitelistHistory.objects.all()
            self.assertEqual(whitelist.count(), 2)
            self.assertEqual(whitelist_history.count(), 2)

            deleted_whitelist = \
                DailyDisbursementLimitWhitelist.objects.filter(customer_id=1000000010).last()
            inserted_whitelist = \
                DailyDisbursementLimitWhitelist.objects.filter(customer_id=1000000001).last()

            self.assertIsNotNone(deleted_whitelist)  # Not deleted yet
            self.assertIsNone(inserted_whitelist)    # Not inserted yet
