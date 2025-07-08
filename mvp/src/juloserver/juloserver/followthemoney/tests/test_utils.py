from django.test.testcases import TestCase
from juloserver.followthemoney.utils import (
    mapping_loan_and_application_status_code,
)

from juloserver.julo.statuses import (
    LoanStatusCodes,
    ApplicationStatusCodes,
)


class TestFlollowTheMoneyServices(TestCase):
    def test_mapping_loan_and_application_status_code(self):
        self.assertEqual(
            mapping_loan_and_application_status_code(LoanStatusCodes.LENDER_APPROVAL),
            ApplicationStatusCodes.LENDER_APPROVAL
        )

        self.assertEqual(
            mapping_loan_and_application_status_code(LoanStatusCodes.FUND_DISBURSAL_ONGOING),
            ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED
        )

        self.assertEqual(
            mapping_loan_and_application_status_code(LoanStatusCodes.FUND_DISBURSAL_FAILED),
            ApplicationStatusCodes.FUND_DISBURSAL_FAILED
        )

        self.assertEqual(
            mapping_loan_and_application_status_code(LoanStatusCodes.LENDER_REJECT),
            ApplicationStatusCodes.APPLICATION_DENIED
        )

        self.assertEqual(
            mapping_loan_and_application_status_code(LoanStatusCodes.CURRENT),
            ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
        )

        self.assertEqual(
            mapping_loan_and_application_status_code(LoanStatusCodes.INACTIVE),
            LoanStatusCodes.INACTIVE
        )
