from datetime import timedelta
from mock import patch

from django.test import override_settings
from django.test.testcases import TestCase
from django.utils import timezone

from juloserver.employee_financing.models import EmFinancingWFAccessToken
from juloserver.julo.tests.factories import PartnerFactory
from juloserver.employee_financing.tests.factories import CompanyFactory
from juloserver.employee_financing.utils import (
    create_or_update_token,
    encode_jwt_token,
    decode_jwt_token
)


class TestJWTAccessToken(TestCase):

    @override_settings(WEB_FORM_JWT_SECRET_KEY='secret-key')
    def setUp(self) -> None:
        self.name = 'user name'
        self.email = 'user1company@email.com'
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
        self.form_type = 'application'
        self.expired_at = timezone.localtime(timezone.now()) + timedelta(days=30)
        self.payload = {
            'email': self.email,
            'name': self.name,
            'form_type': self.form_type,
            'company_id': self.company.id,
            'exp': self.expired_at
        }

    @override_settings(WEB_FORM_JWT_SECRET_KEY='secret-key')
    def test_encode_decode_jwt_token(self) -> None:
        jwt_token = encode_jwt_token(self.payload)
        self.assertIsNotNone(jwt_token)

        failed_result_token = decode_jwt_token(jwt_token + '111')
        self.assertEqual(failed_result_token, False)

        success_result_token = decode_jwt_token(jwt_token)
        self.assertEqual(success_result_token, self.payload)

    @override_settings(WEB_FORM_JWT_SECRET_KEY='secret-key')
    def test_create_or_update_token(self) -> None:
        create_token = create_or_update_token(email=self.email, company=self.company,
                                              expired_at=self.expired_at, form_type=self.form_type,
                                              name=self.name)

        self.payload['exp'] = self.expired_at
        expected_token = encode_jwt_token(self.payload)
        self.assertEqual(create_token.token, expected_token)
        self.assertEqual(create_token.limit_token_creation, 3)

        create_token = create_or_update_token(email=self.email, company=self.company,
                                              expired_at=self.expired_at, form_type=self.form_type,
                                              name=self.name)
        # Token not expired still using old token
        self.assertEqual(create_token.token, expected_token)
        self.assertEqual(create_token.limit_token_creation, 3)

        # update token token is expired
        with patch('juloserver.employee_financing.utils.decode_jwt_token', return_value=False):
            self.expired_at = timezone.localtime(timezone.now()) + timedelta(days=25)
            create_token = create_or_update_token(email=self.email, company=self.company,
                                                  expired_at=self.expired_at, form_type=self.form_type,
                                                  name=self.name)
            # should not same with old token
            old_token = expected_token
            create_token.refresh_from_db()
            self.assertEqual(create_token.limit_token_creation, 2)
            self.assertNotEqual(create_token.token, old_token)
            self.assertEqual(EmFinancingWFAccessToken.objects.count(), 1)
