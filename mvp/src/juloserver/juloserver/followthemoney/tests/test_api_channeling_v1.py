from __future__ import print_function

import mock
from mock import patch
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    LoanFactory,
    PartnerFactory,
    ProductLineFactory,
    ProductLookupFactory,
    StatusLookupFactory,
    FeatureSettingFactory,
    WorkflowFactory,
)
from juloserver.channeling_loan.constants import ChannelingStatusConst
from juloserver.channeling_loan.tests.factories import (
    ChannelingLoanStatusFactory,
    ChannelingEligibilityStatusFactory,
)
from juloserver.followthemoney.factories import (
    LenderCurrentFactory,
    LenderBucketFactory,
)
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLookupFactory,
)
from juloserver.channeling_loan.constants import (
    FeatureNameConst as ChannelingFeatureNameConst,
)
from juloserver.channeling_loan.constants import (
    ChannelingConst,
)
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.services2.redis_helper import MockRedisHelper


class TestListApplicationChanneling(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.client.credentials(
            HTTP_AUTHORIZATION="Token " + self.user.auth_expiry_token.key
        )
        self.account = AccountFactory()
        self.application = ApplicationFactory(
            customer=self.customer, fullname="testname"
        )
        self.partner = PartnerFactory(user=self.user)
        self.lender = LenderCurrentFactory(user=self.user, lender_name='bss_channeling')
        self.product_line = ProductLineFactory(product_line_code=12345)
        self.product_look_up = ProductLookupFactory(product_line=self.product_line)
        self.loan = LoanFactory(
            application=self.application,
            lender=self.lender,
            product=self.product_look_up,
        )
        self.hide_partner_loan_fs = FeatureSettingFactory(
            feature_name="hide_partner_loan", category="followthemoney", is_active=False
        )
        self.channeling_loan_status = ChannelingLoanStatusFactory(
            channeling_eligibility_status=ChannelingEligibilityStatusFactory(
                application=self.application
            ),
            loan=self.loan,
            channeling_type="BSS",
            channeling_status="process",
        )
        self.feature_setting = FeatureSettingFactory(
            feature_name=ChannelingFeatureNameConst.CHANNELING_LOAN_CONFIG,
            is_active=True,
            parameters={
                ChannelingConst.BSS: {
                    "is_active": True,
                    "general": {
                        "LENDER_NAME": "bss_channeling",
                        "BUYBACK_LENDER_NAME": "jh",
                        "EXCLUDE_LENDER_NAME": ["ska", "gfin", "helicap", "ska2"],
                        "INTEREST_PERCENTAGE": 15,
                        "DAYS_IN_YEAR": 360,
                        "CHANNELING_TYPE": ChannelingConst.API_CHANNELING_TYPE,
                    },
                    "rac": {
                        "TENOR": "Monthly",
                        "MAX_AGE": 59,
                        "MIN_AGE": 21,
                        "JOB_TYPE": ["Pegawai swasta", "Pegawai negeri", "Pengusaha"],
                        "MAX_LOAN": 15000000,
                        "MIN_LOAN": 500000,
                        "MAX_RATIO": 0.3,
                        "MAX_TENOR": 9,
                        "MIN_TENOR": 1,
                        "MIN_INCOME": 2000000,
                        "MIN_WORKTIME": 3,
                        "TRANSACTION_METHOD": ['1', '2', '3', '4', '5', '6', '7', '12', '11', '16'],
                        "INCOME_PROVE": True,
                        "HAS_KTP_OR_SELFIE": True,
                        "MOTHER_MAIDEN_NAME": True,
                        "VERSION": 2,
                    },
                    "cutoff": {
                        "is_active": False,
                        "OPENING_TIME": {"hour": 7, "minute": 0, "second": 0},
                        "CUTOFF_TIME": {"hour": 19, "minute": 0, "second": 0},
                        "INACTIVE_DATE": [],
                        "INACTIVE_DAY": [],
                        "LIMIT": None,
                    },
                    "force_update": {
                        "is_active": True,
                        "VERSION": 2,
                    },
                    "due_date": {"is_active": False, "ESCLUSION_DAY": [25, 26]},
                    "credit_score": {"is_active": False, "SCORE": ["A", "B-"]},
                    "b_score": {"is_active": False, "MAX_B_SCORE": None, "MIN_B_SCORE": None},
                    "whitelist": {"is_active": False, "APPLICATIONS": []},
                },
                ChannelingConst.FAMA: {
                    "is_active": True,
                    "general": {
                        "LENDER_NAME": "fama_channeling",
                        "BUYBACK_LENDER_NAME": "jh",
                        "EXCLUDE_LENDER_NAME": ["ska", "gfin", "helicap", "ska2"],
                        "INTEREST_PERCENTAGE": 14,
                        "DAYS_IN_YEAR": 360,
                        "CHANNELING_TYPE": ChannelingConst.MANUAL_CHANNELING_TYPE,
                    },
                    "rac": {
                        "TENOR": "Monthly",
                        "MAX_AGE": None,
                        "MIN_AGE": None,
                        "JOB_TYPE": [],
                        "MAX_LOAN": 20000000,
                        "MIN_LOAN": 1000000,
                        "MAX_RATIO": None,
                        "MAX_TENOR": None,
                        "MIN_TENOR": None,
                        "MIN_INCOME": None,
                        "MIN_WORKTIME": 24,
                        "TRANSACTION_METHOD": ['1', '2', '3', '4', '5', '6', '7', '12', '11', '16'],
                        "INCOME_PROVE": True,
                        "HAS_KTP_OR_SELFIE": True,
                        "MOTHER_MAIDEN_NAME": True,
                        "VERSION": 2,
                    },
                    "cutoff": {
                        "is_active": True,
                        "OPENING_TIME": {"hour": 1, "minute": 0, "second": 0},
                        "CUTOFF_TIME": {"hour": 9, "minute": 0, "second": 0},
                        "INACTIVE_DATE": [],
                        "INACTIVE_DAY": ["Saturday", "Sunday"],
                        "LIMIT": 1,
                    },
                    "due_date": {"is_active": False, "ESCLUSION_DAY": [25, 26]},
                    "credit_score": {"is_active": False, "SCORE": ["A", "B-"]},
                    "b_score": {"is_active": False, "MAX_B_SCORE": None, "MIN_B_SCORE": None},
                    "force_update": {
                        "is_active": True,
                        "VERSION": 2,
                    },
                    "whitelist": {"is_active": False, "APPLICATIONS": []},
                },
            },
        )

    def test_list_application(self):
        self.loan.loan_status = StatusLookupFactory(status_code=LoanStatusCodes.CURRENT)
        self.loan.save()

        # current lender is BSS but try to access FAMA
        response = self.client.get("/api/followthemoney/v1/channeling/list_application/FAMA/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # filter by product_line_code
        response = self.client.get(
            "/api/followthemoney/v1/channeling/list_application/BSS/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["data"]), 1)

        # different
        self.lender.lender_name = 'fama_channeling'
        self.lender.save()
        response = self.client.get(
            "/api/followthemoney/v1/channeling/list_application/FAMA/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["data"]), 0)

        self.lender.lender_name = 'bss_channeling'
        self.lender.save()

        # test fullname updated based on application
        self.loan.account = self.account
        self.loan.save()
        response = self.client.get(
            "/api/followthemoney/v1/channeling/list_application/BSS/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["data"]), 1)
        self.assertNotEqual(response.data["data"][0]["fullname"], "")

        # disable hide_partner_loan fs
        self.hide_partner_loan_fs.is_active = False
        self.hide_partner_loan_fs.save()
        response = self.client.get(
            "/api/followthemoney/v1/channeling/list_application/BSS/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["data"]), 1)

        # test lender_bucket previous already added
        lender_bucket = LenderBucketFactory(partner=self.partner, is_active=True)
        lender_bucket.loan_ids = {"approved": [self.loan.id], "rejected": []}
        lender_bucket.save()
        response = self.client.get(
            "/api/followthemoney/v1/channeling/list_application/BSS/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["data"]), 0)

        # enable hide_partner_loan fs but hidden_product_line_codes does not contain 12345
        self.hide_partner_loan_fs.is_active = True
        self.hide_partner_loan_fs.parameters = {"hidden_product_line_codes": [999]}
        self.hide_partner_loan_fs.save()
        response = self.client.get(
            "/api/followthemoney/v1/channeling/list_application/BSS/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["data"]), 1)

        # enable hide_partner_loan fs and hidden_product_line_codes contain 12345
        self.hide_partner_loan_fs.parameters = {
            "hidden_product_line_codes": [999, self.product_line.product_line_code]
        }
        self.hide_partner_loan_fs.save()
        response = self.client.get(
            "/api/followthemoney/v1/channeling/list_application/BSS/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["data"]), 0)


class TestChannelingLenderBucketCreationFlow(APITestCase):
    def setUp(self) -> None:
        self.url = '/api/followthemoney/v1/channeling/channeling_lender_approval/BSS/'
        self.user = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user, name='bss')
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(
            customer=self.customer
        )
        self.client = APIClient()
        self.client.force_login(self.user)
        self.client.credentials(
            HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.application = ApplicationFactory(customer=self.customer)
        self.loan = LoanFactory(
            customer=self.customer,
            loan_amount=9000000,
            loan_disbursement_amount=8000000,
            loan_duration=180,
            account=self.account,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT)
        )
        self.lender_bucket = LenderBucketFactory(
            loan_ids={"approved": [self.loan.pk], "rejected": []},
            lender_bucket_xid="1232321321321"
        )
        self.hide_partner_loan_fs = FeatureSettingFactory(
            feature_name='hide_partner_loan',
            category='followthemoney',
            is_active=False
        )
        self.channeling_loan_status = ChannelingLoanStatusFactory(
            channeling_eligibility_status=ChannelingEligibilityStatusFactory(
                application=self.application
            ),
            loan=self.loan,
            channeling_type="BSS",
            channeling_status=ChannelingStatusConst.PENDING,
        )
        self.feature_setting = FeatureSettingFactory(
            feature_name=ChannelingFeatureNameConst.CHANNELING_LOAN_CONFIG,
            is_active=True,
            parameters={
                ChannelingConst.BSS: {
                    "is_active": True,
                    "general": {
                        "LENDER_NAME": "bss_channeling",
                        "BUYBACK_LENDER_NAME": "jh",
                        "EXCLUDE_LENDER_NAME": ["ska", "gfin", "helicap", "ska2"],
                        "INTEREST_PERCENTAGE": 15,
                        "DAYS_IN_YEAR": 360,
                        "CHANNELING_TYPE": ChannelingConst.API_CHANNELING_TYPE,
                    },
                    "rac": {
                        "TENOR": "Monthly",
                        "MAX_AGE": 59,
                        "MIN_AGE": 21,
                        "JOB_TYPE": ["Pegawai swasta", "Pegawai negeri", "Pengusaha"],
                        "MAX_LOAN": 15000000,
                        "MIN_LOAN": 500000,
                        "MAX_RATIO": 0.3,
                        "MAX_TENOR": 9,
                        "MIN_TENOR": 1,
                        "MIN_INCOME": 2000000,
                        "MIN_WORKTIME": 3,
                        "TRANSACTION_METHOD": ['1', '2', '3', '4', '5', '6', '7', '12', '11', '16'],
                        "INCOME_PROVE": True,
                        "HAS_KTP_OR_SELFIE": True,
                        "MOTHER_MAIDEN_NAME": True,
                        "VERSION": 2,
                    },
                    "cutoff": {
                        "is_active": False,
                        "OPENING_TIME": {"hour": 7, "minute": 0, "second": 0},
                        "CUTOFF_TIME": {"hour": 19, "minute": 0, "second": 0},
                        "INACTIVE_DATE": [],
                        "INACTIVE_DAY": [],
                        "LIMIT": None,
                    },
                    "force_update": {
                        "is_active": True,
                        "VERSION": 2,
                    },
                    "due_date": {"is_active": False, "ESCLUSION_DAY": [25, 26]},
                    "credit_score": {"is_active": False, "SCORE": ["A", "B-"]},
                    "b_score": {"is_active": False, "MAX_B_SCORE": None, "MIN_B_SCORE": None},
                    "whitelist": {"is_active": False, "APPLICATIONS": []},
                    "lender_dashboard": {"is_active": True},
                },
                ChannelingConst.FAMA: {
                    "is_active": True,
                    "general": {
                        "LENDER_NAME": "fama_channeling",
                        "BUYBACK_LENDER_NAME": "jh",
                        "EXCLUDE_LENDER_NAME": ["ska", "gfin", "helicap", "ska2"],
                        "INTEREST_PERCENTAGE": 14,
                        "DAYS_IN_YEAR": 360,
                        "CHANNELING_TYPE": ChannelingConst.MANUAL_CHANNELING_TYPE,
                    },
                    "rac": {
                        "TENOR": "Monthly",
                        "MAX_AGE": None,
                        "MIN_AGE": None,
                        "JOB_TYPE": [],
                        "MAX_LOAN": 20000000,
                        "MIN_LOAN": 1000000,
                        "MAX_RATIO": None,
                        "MAX_TENOR": None,
                        "MIN_TENOR": None,
                        "MIN_INCOME": None,
                        "MIN_WORKTIME": 24,
                        "TRANSACTION_METHOD": ['1', '2', '3', '4', '5', '6', '7', '12', '11', '16'],
                        "INCOME_PROVE": True,
                        "HAS_KTP_OR_SELFIE": True,
                        "MOTHER_MAIDEN_NAME": True,
                        "VERSION": 2,
                    },
                    "cutoff": {
                        "is_active": True,
                        "OPENING_TIME": {"hour": 1, "minute": 0, "second": 0},
                        "CUTOFF_TIME": {"hour": 9, "minute": 0, "second": 0},
                        "INACTIVE_DATE": [],
                        "INACTIVE_DAY": ["Saturday", "Sunday"],
                        "LIMIT": 1,
                    },
                    "force_update": {
                        "is_active": True,
                        "VERSION": 2,
                    },
                    "due_date": {"is_active": False, "ESCLUSION_DAY": [25, 26]},
                    "credit_score": {"is_active": False, "SCORE": ["A", "B-"]},
                    "b_score": {"is_active": False, "MAX_B_SCORE": None, "MIN_B_SCORE": None},
                    "whitelist": {"is_active": False, "APPLICATIONS": []},
                    "lender_dashboard": {"is_active": True},
                },
            },
        )


    @patch('juloserver.followthemoney.services.get_redis_client')
    def test_api_view(self, _mock_get_redis_client):
        _mock_get_redis_client.return_value = MockRedisHelper()

        data = {
            "application_ids": {
                "approved": [self.loan.id],
                "rejected": []
            }
        }
        #test approved
        response = self.client.post(self.url, data=data, format='json')
        self.assertEqual(response.status_code, 200)

        # test already approved
        data = {
            "application_ids": {
                "approved": [self.loan.id],
                "rejected": []
            }
        }
        response = self.client.post(self.url, data=data, format='json')
        self.assertEqual(response.status_code, 400)

        # uniq loan id
        self.channeling_loan_status.channeling_status = ChannelingStatusConst.PENDING
        self.channeling_loan_status.save()
        data = {
            "application_ids": {
                "approved": [self.loan.id],
                "rejected": [self.loan.id],
            }
        }
        response = self.client.post(self.url, data=data, format='json')
        self.assertEqual(response.status_code, 400)

        data = {
            "application_ids": {
                "approved": [],
                "rejected": [self.loan.id, 123222],
            }
        }

        #test loan reject not found / same
        response = self.client.post(self.url, data=data, format='json')
        self.assertEqual(response.status_code, 400)

        data = {
            "application_ids": {
                "approved": [],
                "rejected": [self.loan.id],
            }
        }
        #test loan reject success
        response = self.client.post(self.url, data=data, format='json')
        self.assertEqual(response.status_code, 200)

    @patch('juloserver.followthemoney.services.get_redis_client')
    def test_api_lender_dashboard_inactive(self, _mock_get_redis_client):
        # if lender dashboard is inactive, no need to resend data to bss
        _mock_get_redis_client.return_value = MockRedisHelper()
        self.feature_setting.parameters[ChannelingConst.BSS]['lender_dashboard'][
            'is_active'
        ] = False
        self.feature_setting.save()
        data = {"application_ids": {"approved": [self.loan.id], "rejected": []}}
        response = self.client.post(self.url, data=data, format='json')
        self.assertEqual(response.status_code, 403)

    @patch('juloserver.followthemoney.views.channeling_views.execute_after_transaction_safely')
    @patch('juloserver.followthemoney.services.get_redis_client')
    def test_api_lender_dashboard_active(
        self, _mock_get_redis_client, mock_execute_after_transaction_safely
    ):
        # if lender dashboard active, need to send data to bss
        # also cover for rejected loan (rejected loan are not send)
        loan = LoanFactory(
            customer=self.customer,
            loan_amount=9000000,
            loan_disbursement_amount=8000000,
            loan_duration=180,
            account=self.account,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
        )
        ChannelingLoanStatusFactory(
            channeling_eligibility_status=ChannelingEligibilityStatusFactory(
                application=self.application
            ),
            loan=loan,
            channeling_type="BSS",
            channeling_status=ChannelingStatusConst.PENDING,
        )
        _mock_get_redis_client.return_value = MockRedisHelper()

        data = {"application_ids": {"approved": [self.loan.id], "rejected": [loan.id]}}
        response = self.client.post(self.url, data=data, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_execute_after_transaction_safely.call_count, 1)
