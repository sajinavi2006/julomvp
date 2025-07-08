from unittest import TestCase

from juloserver.loan.services.loan_formula import LoanAmountFormulaService
from juloserver.loan.tests.factories import TransactionMethodFactory
from juloserver.payment_point.constants import TransactionMethodCode


class TestLoanAmountFormulaService(TestCase):
    def setUp(self):
        self.self_method = TransactionMethodCode.SELF.code
        self.qris_1_method = TransactionMethodCode.QRIS_1.code
        self.kirim_method = TransactionMethodCode.OTHER.code

    def test_properties_tarik_dana(self):
        transaction_method = self.self_method
        requested_amount = 3_000_000
        provision_rate = 0.08
        tax_rate = 0.11
        insurance_amount = 3_000
        delay_disbursement_fee = 233
        total_digisign_fee = 445

        service = LoanAmountFormulaService(
            method_code=transaction_method,
            requested_amount=requested_amount,
            tax_rate=tax_rate,
            provision_rate=provision_rate,
            insurance_amount=insurance_amount,
            total_digisign_fee=total_digisign_fee,
            delay_disburesment_fee=delay_disbursement_fee,
        )

        self.assertEqual(service.adjusted_amount, 3_000_000)
        self.assertEqual(service.tax_amount, 26_805)
        self.assertEqual(service.final_amount, 3_000_000)
        self.assertEqual(service.disbursement_amount, 2_729_517)
        self.assertEqual(service.provision_fee, 243_233)
        self.assertEqual(service.insurance_rate, 0.001)
        self.assertEqual(service.taxable_amount, 243_678)

    def test_properties_kirim_dana(self):
        transaction_method = self.kirim_method
        requested_amount = 3_000_000
        provision_rate = 0.08
        tax_rate = 0.11
        insurance_amount = 3_000  # shoult rendered zero since it's its for tarik only
        delay_disbursement_fee = 233
        total_digisign_fee = 445

        service = LoanAmountFormulaService(
            method_code=transaction_method,
            requested_amount=requested_amount,
            tax_rate=tax_rate,
            provision_rate=provision_rate,
            insurance_amount=insurance_amount,
            total_digisign_fee=total_digisign_fee,
            delay_disburesment_fee=delay_disbursement_fee,
        )

        self.assertEqual(service.adjusted_amount, 3_261_123)
        self.assertEqual(service.tax_amount, 28_772)
        self.assertEqual(service.final_amount, 3_290_340)
        self.assertEqual(service.disbursement_amount, 3_000_000)
        self.assertEqual(service.provision_fee, 261_123)
        self.assertEqual(service.insurance_rate, 0)  # because nonself method
        self.assertEqual(service.insurance_amount, 0)  # because nonself method
        self.assertEqual(service.taxable_amount, 261_568)

    def test_properties_qris_1(self):
        transaction_method = self.qris_1_method
        requested_amount = 3_000_000
        provision_rate = 0.08
        tax_rate = 0.11
        insurance_amount = 3000

        service = LoanAmountFormulaService(
            method_code=transaction_method,
            requested_amount=requested_amount,
            tax_rate=tax_rate,
            provision_rate=provision_rate,
            insurance_amount=insurance_amount,
        )

        self.assertEqual(service.adjusted_amount, 3_260_870)
        self.assertEqual(service.tax_amount, 28_696)
        self.assertEqual(service.final_amount, 3_289_566)
        self.assertEqual(service.disbursement_amount, 3_000_000)
        self.assertEqual(service.provision_fee, 260_870)
        self.assertEqual(service.insurance_rate, 0)
        self.assertEqual(service.insurance_amount, 0)

    def test_requested_amount_from_final_amount(self):

        # tarik
        available_limit = 3_000_000
        provision_rate = 0.08
        tax_rate = 0.11
        total_digisign_fee = 445
        insurance_amount = 3000
        delay_disbursement_fee = 233

        service = LoanAmountFormulaService(
            method_code=TransactionMethodCode.SELF.code,
            requested_amount=available_limit,
            provision_rate=provision_rate,
            tax_rate=tax_rate,
            total_digisign_fee=total_digisign_fee,
            insurance_amount=insurance_amount,
            delay_disburesment_fee=delay_disbursement_fee,
        )

        new_final_amount = 3_290_340
        requested_amount = service.compute_requested_amount_from_final_amount(
            final_amount=new_final_amount,
        )

        self.assertEqual(requested_amount, new_final_amount)

        # kirim
        available_limit = 3_000_000
        provision_rate = 0.08
        tax_rate = 0.11
        total_digisign_fee = 445
        insurance_amount = 3000
        delay_disbursement_fee = 233

        service = LoanAmountFormulaService(
            method_code=TransactionMethodCode.OTHER.code,
            requested_amount=available_limit,
            provision_rate=provision_rate,
            tax_rate=tax_rate,
            total_digisign_fee=total_digisign_fee,
            insurance_amount=insurance_amount,
            delay_disburesment_fee=delay_disbursement_fee,
        )

        new_final_amount = 3_290_340
        requested_amount = service.compute_requested_amount_from_final_amount(
            final_amount=new_final_amount,
        )

        self.assertEqual(
            requested_amount,
            available_limit,
        )
