# keep this service formulas related only.
# do not import Models here.


from juloserver.payment_point.constants import TransactionMethodCode


class LoanAmountFormulaService:
    """
    For loan amount formula (not repayment/payment)
    All loan formulas in one service

    Google Sheet:
    https://docs.google.com/spreadsheets/d/1glHC8M_fDtvBBjyN6B115umLLYFGDckltQ0bI3R8ECY

    """

    def __init__(
        self,
        method_code: int,
        requested_amount: int,
        tax_rate: float,
        provision_rate: float,
        insurance_amount: int = 0,
        total_digisign_fee: int = 0,
        delay_disburesment_fee: int = 0,
    ) -> None:
        self.transaction_method = method_code
        self.requested_amount = requested_amount
        self.tax_rate = tax_rate
        self.provision_rate = provision_rate
        self.insurance_amount = (
            insurance_amount if self.transaction_method == TransactionMethodCode.SELF.code else 0
        )
        self.total_digisign_fee = total_digisign_fee
        self.delay_disbursement_fee = delay_disburesment_fee

    @property
    def tax_amount(self) -> int:
        return self.get_tax_amount(
            taxable_amount=self.taxable_amount,
            tax_rate=self.tax_rate,
        )

    @staticmethod
    def get_tax_amount(taxable_amount: float, tax_rate: float) -> int:
        return round(taxable_amount * tax_rate)

    @property
    def final_amount(self) -> int:
        return self.get_final_amount(
            transaction_method_code=self.transaction_method,
            adjusted_amount=self.adjusted_amount,
            tax_amount=self.tax_amount,
            total_digisign_fee=self.total_digisign_fee,
        )

    @staticmethod
    def get_final_amount(
        transaction_method_code: int,
        adjusted_amount: int,
        tax_amount: int,
        total_digisign_fee: int,
    ) -> int:
        if transaction_method_code == TransactionMethodCode.SELF.code:
            return adjusted_amount

        return adjusted_amount + tax_amount + total_digisign_fee

    @property
    def adjusted_amount(self) -> int:
        return self.get_adjusted_amount(
            requested_amount=self.requested_amount,
            provision_rate=self.provision_rate,
            transaction_method_code=self.transaction_method,
            delay_disburesment_fee=self.delay_disbursement_fee,
        )

    @staticmethod
    def get_adjusted_amount(
        requested_amount: int,
        provision_rate: float,
        transaction_method_code: int,
        delay_disburesment_fee: int = 0,
    ) -> int:
        """
        Adjusted from original amount because of transaction method
        Sending to other account adds extra fee
        """
        if transaction_method_code == TransactionMethodCode.SELF.code:
            return requested_amount

        # add delay_disburesment fee on top of requested amount
        requested_amount_and_delay = requested_amount + delay_disburesment_fee

        adjusted_amount = round(requested_amount_and_delay / (1 - provision_rate))
        return adjusted_amount

    @property
    def insurance_rate(self) -> float:
        return self.get_insurance_rate(
            insurance_amount=self.insurance_amount,
            adjusted_amount=self.adjusted_amount,
        )

    @staticmethod
    def get_insurance_rate(insurance_amount: int, adjusted_amount: int) -> float:
        return float(insurance_amount / adjusted_amount)

    @property
    def provision_fee(self) -> int:
        """
        includes many fees from our side:

        insurance fee, delay disburesment, etc.
        """
        return self.get_provision_fee(
            adjusted_amount=self.adjusted_amount,
            provision_rate=self.provision_rate,
            insurance_amount=self.insurance_amount,
            delay_disbursement_fee=self.delay_disbursement_fee,
        )

    @staticmethod
    def get_provision_fee(
        adjusted_amount: int,
        provision_rate: float,
        insurance_amount: int,
        delay_disbursement_fee,
    ) -> int:
        return round(adjusted_amount * provision_rate) + insurance_amount + delay_disbursement_fee

    @property
    def disbursement_amount(self) -> int:
        return self.get_disbursement_amount(
            final_amount=self.final_amount,
            provision_fee=self.provision_fee,
            tax_amount=self.tax_amount,
            total_digisign_fee=self.total_digisign_fee,
        )

    @staticmethod
    def get_disbursement_amount(
        final_amount: int,
        provision_fee: float,
        tax_amount: int,
        total_digisign_fee: int,
    ) -> int:
        return final_amount - provision_fee - tax_amount - total_digisign_fee

    @property
    def taxable_amount(self) -> int:
        """
        Total amount that can be taxed
        (to keep track of taxed amount)
        """
        return self.get_taxable_amount(
            provision_fee=self.provision_fee,
            total_digisign_fee=self.total_digisign_fee,
        )

    @staticmethod
    def get_taxable_amount(
        provision_fee: int,
        total_digisign_fee: int,
    ) -> int:
        """
        Total fees that are taxable
        - provisition fee
        - digisign fee
        - digisign registration fee
        """
        return provision_fee + total_digisign_fee

    def compute_requested_amount_from_final_amount(
        self,
        final_amount: int,
    ) -> int:
        """
        Reverse engineer a requested amount, based on final amount given
        """

        return self.get_requested_amount_from_final_amount(
            final_amount=final_amount,
            transaction_method_code=self.transaction_method,
            provision_rate=self.provision_rate,
            tax_amount=self.tax_amount,
            total_digisign_fee=self.total_digisign_fee,
            delay_disbursement_fee=self.delay_disbursement_fee,
        )

    @staticmethod
    def get_requested_amount_from_final_amount(
        final_amount: int,
        transaction_method_code: int,
        provision_rate: float,
        tax_amount: float,
        total_digisign_fee: int,
        delay_disbursement_fee: int,
    ) -> int:
        """
        Reverse engineer from final amount to requested amount
        Should change this too if other final_amount/adjusted loan amount FORMULA changes
        """
        if transaction_method_code == TransactionMethodCode.SELF.code:
            return final_amount

        adjusted_amount = final_amount - tax_amount - total_digisign_fee

        requested_amount = int(adjusted_amount * (1 - provision_rate) - delay_disbursement_fee)
        return requested_amount


class LoanRepaymentFormulaService:
    """
    All loan-repayment formula logic in one service
    """

    def __init__(
        self,
        amount_formula_service: LoanAmountFormulaService,
        tenure: int,
        monthly_interest_rate: float,
    ) -> None:
        """
        Not implemented yet
        """
        pass
