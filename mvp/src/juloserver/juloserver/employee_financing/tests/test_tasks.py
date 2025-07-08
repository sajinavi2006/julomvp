from datetime import timedelta
from mock import patch

from django.test import override_settings
from django.test.testcases import TestCase
from django.utils import timezone
from unittest.mock import MagicMock

from juloserver.employee_financing.models import EmFinancingWFAccessToken
from juloserver.employee_financing.tasks.email_task import (
    run_resend_email_web_form_application,
    run_resend_email_web_form_disbursement
)
from juloserver.employee_financing.tests.factories import (
    EmFinancingWFAccessTokenFactory,
    CompanyFactory
)
from juloserver.julo.tests.factories import PartnerFactory
from juloserver.partnership.constants import EFWebFormType


class TestResendEmailWebForm(TestCase):

    def setUp(self) -> None:
        self.partner = PartnerFactory()
        self.company = CompanyFactory(
            partner=self.partner,
            name='pt abc',
            email='ptabc@email.com',
            phone_number='089899998888',
            address='abc',
            company_profitable='Yes',
            centralised_deduction='Yes'
        )
        self.application_form_type = EFWebFormType.APPLICATION
        self.disbursement_form_type = EFWebFormType.DISBURSEMENT

    @override_settings(WEB_FORM_JWT_SECRET_KEY='secret-key')
    def test_resend_email_web_form_application(self) -> None:
        form_mock_name = 'juloserver.employee_financing.tasks.email_task.send_email_web_form_application.delay'
        datetime_now = timezone.localtime(timezone.now()).replace(hour=23, minute=59, second=59)

        # valid
        token1 = EmFinancingWFAccessTokenFactory(
            email='user1@email.com',
            name='user1',
            token='abc',
            company=self.company,
            expired_at=datetime_now,
            form_type=self.application_form_type,
            limit_token_creation=3,
            is_used=False
        )

        # valid
        token2 = EmFinancingWFAccessTokenFactory(
            email='user2@email.com',
            name='user2',
            token='cde',
            company=self.company,
            expired_at=datetime_now,
            form_type=self.application_form_type,
            limit_token_creation=2,
            is_used=False
        )

        # valid
        token3 = EmFinancingWFAccessTokenFactory(
            email='user3@email.com',
            name='user3',
            token='def',
            company=self.company,
            expired_at=datetime_now,
            form_type=self.application_form_type,
            limit_token_creation=1,
            is_used=False
        )

        # Invalid: is used true
        token4 = EmFinancingWFAccessTokenFactory(
            email='user4@email.com',
            name='user4',
            token='fgh',
            company=self.company,
            expired_at=datetime_now,
            form_type=self.application_form_type,
            limit_token_creation=2,
            is_used=True
        )

        # Invalid: form type is disbursement
        token5 = EmFinancingWFAccessTokenFactory(
            email='user5@email.com',
            name='user5',
            token='fgh',
            company=self.company,
            expired_at=datetime_now,
            form_type=self.disbursement_form_type,
            limit_token_creation=2,
            is_used=False
        )

        # Invalid: limit token creation 0
        token6 = EmFinancingWFAccessTokenFactory(
            email='user6@email.com',
            name='user6',
            token='jkl',
            company=self.company,
            expired_at=datetime_now,
            form_type=self.application_form_type,
            limit_token_creation=0,
            is_used=False
        )

        target_date = datetime_now + timedelta(days=1, hours=1)
        with patch('django.utils.timezone.localtime') as mocked_time, \
                patch(form_mock_name) as send_email_mock:
            mocked_time.side_effect = [
                target_date,
                target_date,
                target_date,
                target_date,
                target_date,
                target_date,
                target_date,
                target_date,
                target_date,
            ]
            run_resend_email_web_form_application()
            # Send email 3 times, because is valid token only 3
            self.assertEqual(send_email_mock.call_count, 3)
            old_token_1 = token1.token
            old_token_2 = token2.token
            old_token_3 = token3.token
            old_token_4 = token4.token
            old_token_5 = token5.token
            old_token_6 = token6.token

            token1.refresh_from_db()
            token2.refresh_from_db()
            token3.refresh_from_db()
            token4.refresh_from_db()
            token5.refresh_from_db()
            token6.refresh_from_db()

            # token 1 - 3 will have new token
            self.assertNotEqual(token1.token, old_token_1)
            self.assertNotEqual(token2.token, old_token_2)
            self.assertNotEqual(token3.token, old_token_3)

            # token 4 - 6 will have same token (invalid)
            self.assertEqual(token4.token, old_token_4)
            self.assertEqual(token5.token, old_token_5)
            self.assertEqual(token6.token, old_token_6)

    @override_settings(WEB_FORM_JWT_SECRET_KEY='secret-key')
    def test_resend_email_web_form_disbursement(self) -> None:
        form_mock_name = 'juloserver.employee_financing.tasks.email_task.send_email_web_form_disbursement.delay'
        datetime_now = timezone.localtime(timezone.now()).replace(hour=23, minute=59, second=59)

        # valid
        token1 = EmFinancingWFAccessTokenFactory(
            email='user1@email.com',
            name='user1',
            token='abc',
            company=self.company,
            expired_at=datetime_now,
            form_type=self.disbursement_form_type,
            limit_token_creation=3,
            is_used=False
        )

        # valid
        token2 = EmFinancingWFAccessTokenFactory(
            email='user2@email.com',
            name='user2',
            token='cde',
            company=self.company,
            expired_at=datetime_now,
            form_type=self.disbursement_form_type,
            limit_token_creation=2,
            is_used=False
        )

        # valid
        token3 = EmFinancingWFAccessTokenFactory(
            email='user3@email.com',
            name='user3',
            token='def',
            company=self.company,
            expired_at=datetime_now,
            form_type=self.disbursement_form_type,
            limit_token_creation=1,
            is_used=False
        )

        # Invalid: is used true
        token4 = EmFinancingWFAccessTokenFactory(
            email='user4@email.com',
            name='user4',
            token='fgh',
            company=self.company,
            expired_at=datetime_now,
            form_type=self.disbursement_form_type,
            limit_token_creation=2,
            is_used=True
        )

        # Invalid: form type is application
        token5 = EmFinancingWFAccessTokenFactory(
            email='user7@email.com',
            name='user7',
            token='fgh',
            company=self.company,
            expired_at=datetime_now,
            form_type=self.application_form_type,
            limit_token_creation=2,
            is_used=False
        )

        # Invalid: limit token creation 0
        token6 = EmFinancingWFAccessTokenFactory(
            email='user6@email.com',
            name='user6',
            token='jkl',
            company=self.company,
            expired_at=datetime_now,
            form_type=self.disbursement_form_type,
            limit_token_creation=0,
            is_used=False
        )

        target_date = datetime_now + timedelta(days=1, hours=1)
        with patch('django.utils.timezone.localtime') as mocked_time, \
                patch(form_mock_name) as send_email_mock:
            mocked_time.side_effect = [
                target_date,
                target_date,
                target_date,
                target_date,
                target_date,
                target_date,
                target_date,
                target_date,
                target_date,
            ]
            run_resend_email_web_form_disbursement()
            # Send email 3 times, because is valid token only 3
            self.assertEqual(send_email_mock.call_count, 3)
            old_token_1 = token1.token
            old_token_2 = token2.token
            old_token_3 = token3.token
            old_token_4 = token4.token
            old_token_5 = token5.token
            old_token_6 = token6.token

            token1.refresh_from_db()
            token2.refresh_from_db()
            token3.refresh_from_db()
            token4.refresh_from_db()
            token5.refresh_from_db()
            token6.refresh_from_db()

            # token 1 - 3 will have new token
            self.assertNotEqual(token1.token, old_token_1)
            self.assertNotEqual(token2.token, old_token_2)
            self.assertNotEqual(token3.token, old_token_3)

            # token 4 - 6 will have same token (invalid)
            self.assertEqual(token4.token, old_token_4)
            self.assertEqual(token5.token, old_token_5)
            self.assertEqual(token6.token, old_token_6)
