from django.utils.dateparse import parse_datetime


class DanaLenderSettlementFileSerializer:
    def __init__(self, data):
        self.data = data
        self.errors = set()

    def validate(self):
        self.validate_customer_id()
        self.validate_partner_id()
        self.validate_lender_product_id()
        self.validate_partner_reference_no()
        self.validate_txn_type()
        self.validate_amount()
        self.validate_bill_id()
        self.validate_due_date()
        self.validate_period_no()
        self.validate_credit_usage_mutation()
        self.validate_principal_amount()
        self.validate_interest_fee_amount()
        self.validate_late_fee_amount()
        self.validate_total_amount()
        self.validate_trans_time()
        self.validate_status()
        self.validate_original_order_amount()
        self.validate_original_partner_reference_no()
        self.validate_paid_principal_amount()
        self.validate_paid_interest_fee_amount()
        self.validate_paid_late_fee_amount()
        self.validate_total_paid_amount()
        self.validate_is_partial_refund()
        self.waived_principal_amount()
        self.waived_interest_fee_amount()
        self.waived_late_fee_amount()
        self.total_waived_amount()

        return self.errors

    def validate_customer_id(self):
        customer_id = self.data.get('customerId')
        if not customer_id:
            self.errors.add("customerId is required")

    def validate_partner_id(self):
        partner_id = self.data.get('partnerId')
        if not partner_id:
            self.errors.add("partnerId is required")

    def validate_lender_product_id(self):
        lender_product_id = self.data.get('lenderProductId')
        if not lender_product_id:
            self.errors.add("lenderProductId is required")

    def validate_partner_reference_no(self):
        partner_reference_no = self.data.get('partnerReferenceNo')
        if not partner_reference_no:
            self.errors.add("partnerReferenceNo is required")

    def validate_txn_type(self):
        txn_type = self.data.get('txnType')
        if not txn_type:
            self.errors.add("txnType is required")

    def validate_amount(self):
        amount = self.data.get('amount')
        if not amount:
            self.errors.add("amount is required")
        else:
            try:
                float(amount)
            except ValueError:
                self.errors.add("amount is not a number")

    def validate_bill_id(self):
        bill_id = self.data.get('billId')
        if not bill_id:
            self.errors.add("billId is required")

    def validate_due_date(self):
        due_date = self.data.get('dueDate')
        if not due_date:
            self.errors.add("dueDate is required")
        if due_date:
            parsed_datetime = parse_datetime(due_date)
            if not parsed_datetime:
                self.errors.add("dueDate Format is not valid")

    def validate_period_no(self):
        period_no = self.data.get('periodNo')
        if not period_no:
            self.errors.add("periodNo is required")
        else:
            try:
                float(period_no)
            except ValueError:
                self.errors.add("periodNo is not a number")

    def validate_credit_usage_mutation(self):
        credit_usage_mutation = self.data.get('creditUsageMutation')
        if not credit_usage_mutation:
            self.errors.add("creditUsageMutation is required")
        else:
            try:
                float(credit_usage_mutation)
            except ValueError:
                self.errors.add("creditUsageMutation is not a number")

    def validate_principal_amount(self):
        principal_amount = self.data.get('principalAmount')
        if not principal_amount:
            self.errors.add("principalAmount is required")
        else:
            try:
                float(principal_amount)
            except ValueError:
                self.errors.add("principalAmount is not a number")

    def validate_interest_fee_amount(self):
        interest_fee_amount = self.data.get('interestFeeAmount')
        if not interest_fee_amount:
            self.errors.add("interestFeeAmount is required")
        else:
            try:
                float(interest_fee_amount)
            except ValueError:
                self.errors.add("interestFeeAmount is not a number")

    def validate_late_fee_amount(self):
        late_fee_amount = self.data.get('lateFeeAmount')
        if not late_fee_amount:
            self.errors.add("lateFeeAmount is required")
        else:
            try:
                float(late_fee_amount)
            except ValueError:
                self.errors.add("lateFeeAmount is not a number")

    def validate_total_amount(self):
        total_amount = self.data.get('totalAmount')
        if not total_amount:
            self.errors.add("totalAmount is required")
        else:
            try:
                float(total_amount)
            except ValueError:
                self.errors.add("totalAmount is not a number")

    def validate_trans_time(self):
        trans_time = self.data.get('transTime')
        if not trans_time:
            self.errors.add("transTime is required")
        else:
            parsed_datetime = parse_datetime(trans_time)
            if not parsed_datetime:
                self.errors.add("transTime Format is not valid")

    def validate_status(self):
        status = self.data.get('status')
        if not status:
            self.errors.add("status is required")

    def validate_original_order_amount(self):
        original_order_amount = self.data.get('originalOrderAmount')
        if not original_order_amount:
            self.errors.add("originalOrderAmount is required")
        else:
            try:
                float(original_order_amount)
            except ValueError:
                self.errors.add("originalOrderAmount is not a number")

    def validate_original_partner_reference_no(self):
        original_partner_reference_no = self.data.get('originalPartnerReferenceNo')
        if not original_partner_reference_no:
            self.errors.add("originalPartnerReferenceNo is required")

    def validate_paid_principal_amount(self):
        paid_principal_amount = self.data.get('paidPrincipalAmount')
        if paid_principal_amount:
            try:
                float(paid_principal_amount)
            except ValueError:
                self.errors.add("paidPrincipalAmount is not a number")

    def validate_paid_interest_fee_amount(self):
        paid_interest_fee_amount = self.data.get('paidInterestFeeAmount')
        if paid_interest_fee_amount:
            try:
                float(paid_interest_fee_amount)
            except ValueError:
                self.errors.add("paidInterestFeeAmount is not a number")

    def validate_paid_late_fee_amount(self):
        paid_late_fee_amount = self.data.get('paidLateFeeAmount')
        if paid_late_fee_amount:
            try:
                float(paid_late_fee_amount)
            except ValueError:
                self.errors.add("paidLateFeeAmount is not a number")

    def validate_total_paid_amount(self):
        total_paid_amount = self.data.get('totalPaidAmount')
        if not total_paid_amount:
            self.errors.add("totalPaidAmount is required")
        else:
            try:
                float(total_paid_amount)
            except ValueError:
                self.errors.add("totalPaidAmount is not a number")

    def validate_is_partial_refund(self):
        is_partial_refund = self.data.get('isPartialRefund')
        if isinstance(is_partial_refund, str):
            lowered = is_partial_refund.strip().lower()
            if lowered in ['true', '1']:
                is_partial_refund = True
            elif lowered in ['false', '0']:
                is_partial_refund = False
            else:
                self.errors.add("isPartialRefund must be a boolean")
                return
            self.data['isPartialRefund'] = is_partial_refund

        if not isinstance(is_partial_refund, bool):
            self.errors.add("isPartialRefund must be a boolean")

    def waived_principal_amount(self):
        waived_principal_amount = self.data.get('waivedPrincipalAmount')
        if waived_principal_amount:
            try:
                float(waived_principal_amount)
            except ValueError:
                self.errors.add("waivedPrincipalAmount is not a number")

    def waived_interest_fee_amount(self):
        waived_interest_fee_amount = self.data.get('waivedInterestFeeAmount')
        if waived_interest_fee_amount:
            try:
                float(waived_interest_fee_amount)
            except ValueError:
                self.errors.add("waivedInterestFeeAmount is not a number")

    def waived_late_fee_amount(self):
        waived_late_fee_amount = self.data.get('waivedLateFeeAmount')
        if waived_late_fee_amount:
            try:
                float(waived_late_fee_amount)
            except ValueError:
                self.errors.add("waivedLateFeeAmount is not a number")

    def total_waived_amount(self):
        total_waived_amount = self.data.get('totalWaivedAmount')
        if total_waived_amount:
            try:
                float(total_waived_amount)
            except ValueError:
                self.errors.add("totalWaivedAmount is not a number")
