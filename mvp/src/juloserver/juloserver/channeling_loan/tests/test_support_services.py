from django.test.testcases import TestCase
from django.utils import timezone

from datetime import date

from juloserver.account.tests.factories import AccountFactory
from juloserver.channeling_loan.services.support_services import (
    retroload_address,
    update_application_dob_by_channeling_loan_status_cdate,
    update_application_marital_spouse_name_by_channeling_loan_status_cdate,
)
from juloserver.channeling_loan.constants import (
    ChannelingConst,
    MartialStatusConst,
)
from juloserver.disbursement.tests.factories import DisbursementFactory
from juloserver.followthemoney.factories import LenderCurrentFactory
from juloserver.julo.tests.factories import (
    LoanFactory,
    ApplicationFactory,
)

from juloserver.channeling_loan.tests.factories import (
    ChannelingLoanStatusFactory,
    ChannelingEligibilityStatusFactory,
)

from juloserver.portal.object.bulk_upload.constants import GENDER

class TestSupportServices(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.disbursement = DisbursementFactory()
        cls.lender = LenderCurrentFactory(xfers_token="xfers_tokenforlender")
        cls.account = AccountFactory()
        cls.loan = LoanFactory(
            application=None,
            account=cls.account,
            lender=cls.lender,
            disbursement_id=cls.disbursement.id,
            fund_transfer_ts=timezone.localtime(timezone.now()),
        )
        cls.application = ApplicationFactory(
            account=cls.account,
            marital_status=MartialStatusConst.MENIKAH,
            last_education="SD",
            address_kabupaten="Kab. Bekasi",
            ktp="1234560101913456",
            dob=date(1991, 1, 1),
            gender=GENDER['male'],
            spouse_name=None,
        )

    def test_retroload_address(self):
        assert ({}, []) == retroload_address(1, None, 25, None, "BSS")
        application = ApplicationFactory(id=2, bss_eligible=True, address_kelurahan='Andir')
        application.update_safely(
            cdate=timezone.localtime(timezone.now()).replace(year=2022, month=2, day=24)
        )
        self.assertIsNotNone(retroload_address(1, None, 25, None, "BSS"))


    def test_update_application_dob(self):
        ChannelingLoanStatusFactory(
            channeling_eligibility_status=ChannelingEligibilityStatusFactory(
                application=self.application,
            ),
            channeling_type=ChannelingConst.FAMA,
            loan=self.loan,
            cdate=timezone.localtime(timezone.now()),
        )

        update_application_dob_by_channeling_loan_status_cdate(None, None)
        self.application.refresh_from_db()
        self.assertEqual(self.application.ktp, '1234560101913456')

        self.application.gender = GENDER['female']
        self.application.save()
        update_application_dob_by_channeling_loan_status_cdate(None, None)
        self.application.refresh_from_db()
        self.assertEqual(self.application.ktp, '1234564101913456')


    def test_update_application_marital_spouse_name(self):
        ChannelingLoanStatusFactory(
            channeling_eligibility_status=ChannelingEligibilityStatusFactory(
                application=self.application,
            ),
            channeling_type=ChannelingConst.FAMA,
            loan=self.loan,
            cdate=timezone.localtime(timezone.now()),
        )

        update_application_marital_spouse_name_by_channeling_loan_status_cdate(None, None)
        self.application.refresh_from_db()
        self.assertEqual(self.application.spouse_name, 'Lorem Ipsum')

        self.application.spouse_name = 'Kevin'
        self.application.save()
        update_application_marital_spouse_name_by_channeling_loan_status_cdate(None, None)
        self.application.refresh_from_db()
        self.assertEqual(self.application.spouse_name, 'Kevin')
