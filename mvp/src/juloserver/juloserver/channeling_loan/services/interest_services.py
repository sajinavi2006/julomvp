import math
from django.utils import timezone
from juloserver.julocore.python2.utils import py2round
from juloserver.channeling_loan.constants import (
    FeatureNameConst,
)
from juloserver.channeling_loan.constants.bni_constants import (
    BNI_DEFAULT_INTEREST,
)
from juloserver.julo.models import FeatureSetting
from juloserver.channeling_loan.models import ChannelingLoanPayment


class ChannelingInterest:
    def __init__(self, loan, channeling_type, total_annual_interest, days_in_year, payments=None):
        self.loan = loan
        self.channeling_type = channeling_type
        self.payments = payments

        if not self.payments:
            self.payments = loan.payment_set.order_by('payment_number')

        self.total_annual_interest = total_annual_interest
        self.days_in_year = days_in_year

        self.loan_amount = self.loan.loan_amount

    def pmt_channeling_payment_interest(self):
        duration = self.loan.loan_duration
        calculate_interest = self.total_annual_interest / 12

        installment = (
            self.loan_amount
            * calculate_interest
            / (1 - pow((1 + calculate_interest), (-1 * duration)))
        )
        channeling_loan_payments = []
        interest_dict = {}
        # no need to pass duration here, since we use len(payment)
        channeling_loan_payments, interest_dict = self.pmt_monthly_interest(
            installment,
        )

        if channeling_loan_payments:
            ChannelingLoanPayment.objects.bulk_create(channeling_loan_payments)

        return interest_dict

    def pmt_monthly_interest(
        self,
        installment,
    ):
        """
        calculate PMT for daily interest
        also have to make sure loan not exceed daily limit rate rule
        using PMT formula :
        PMT = (amount x percent) / (1 - (1 + percent)^-duration)
        """
        os_principal = self.loan_amount
        channeling_loan_payments = []
        interest_dict = {}
        total_installment = 0
        total_interest = 0
        total_principal = 0
        for payment in self.payments:
            interest_fee = py2round(self.total_annual_interest * os_principal / 12)
            principal = py2round(installment - interest_fee)
            os_principal = py2round(os_principal - principal)
            interest_dict[payment.id] = interest_fee

            total_installment += py2round(installment)
            total_interest += interest_fee
            total_principal += principal
            # calculate daily interest
            channeling_loan_payments.append(
                ChannelingLoanPayment(
                    payment=payment,
                    due_date=payment.due_date,
                    due_amount=py2round(installment),
                    principal_amount=principal,
                    interest_amount=interest_fee,
                    channeling_type=self.channeling_type,
                    actual_daily_interest=0,
                )
            )

        start_date = timezone.localtime(self.loan.fund_transfer_ts).date()
        diff_date = (self.payments[0].due_date - start_date).days + 1
        daily_interest_fee = py2round(
            diff_date * self.total_annual_interest / self.days_in_year * self.loan_amount
        )
        channeling_loan_payments[0].actual_daily_interest = daily_interest_fee

        last_channeling_loan_payment = channeling_loan_payments[-1]
        if total_principal != self.loan_amount:
            # Edit last channeling_loan_payments (have to match loan_amount)
            principal_diff = total_principal - self.loan_amount
            last_channeling_loan_payment.principal_amount -= principal_diff
            total_principal -= principal_diff

        if total_interest != total_installment - total_principal:
            interest_diff = total_interest - (total_installment - total_principal)
            last_channeling_loan_payment.interest_amount -= interest_diff
            last_payment_id = last_channeling_loan_payment.payment.id
            interest_dict[last_payment_id] = last_channeling_loan_payment.interest_amount

        return channeling_loan_payments, interest_dict


class BNIInterest(ChannelingInterest):
    @staticmethod
    def _get_bni_interest():
        """
        get interest from config / use default interest value
        bni have different interest based on the loan duration length (tenor)
        """
        bni_interest_config = FeatureSetting.objects.get_or_none(
            feature_name=FeatureNameConst.BNI_INTEREST_CONFIG,
            is_active=True,
        )
        bni_interest = BNI_DEFAULT_INTEREST
        if bni_interest_config:
            bni_interest = bni_interest_config.parameters.get("interest", {})

        return bni_interest

    def channeling_payment_interest(self):
        """
        generate Channeling Loan Payment for BNI
        BNI have rule, if first payment is less than equal 30 days,
        it will be considered as 1 month
        but if first payment is more than 30 days, need to calculate per days
        """
        loan_amount = self.loan.loan_amount
        duration = self.loan.loan_duration
        total_interest = self.calculate_total_interest(loan_amount, duration)

        interest_dict = {}
        channeling_loan_payments = []
        monthly_interest_amount = py2round(total_interest / duration)
        monthly_principal_amount = py2round(loan_amount / duration)
        for payment in self.payments:
            interest_dict[payment.id] = monthly_interest_amount
            channeling_loan_payments.append(
                ChannelingLoanPayment(
                    payment=payment,
                    due_date=payment.due_date,
                    due_amount=monthly_principal_amount + monthly_interest_amount,
                    principal_amount=monthly_principal_amount,
                    interest_amount=monthly_interest_amount,
                    channeling_type=self.channeling_type,
                    actual_daily_interest=0,
                )
            )

        if channeling_loan_payments:
            ChannelingLoanPayment.objects.bulk_create(channeling_loan_payments)

        return interest_dict

    def calculate_total_interest(self, loan_amount, duration):
        first_payment = self.payments[0]
        diff_date = (first_payment.due_date - self.loan.fund_transfer_ts.date()).days

        # get bni interest
        bni_interest = self._get_bni_interest()
        yearly_interest = bni_interest.get(str(duration), 0) / 100 + self.total_annual_interest
        monthly_interest = py2round(yearly_interest / 12, 4)

        total_days = duration * 30
        total_interest = monthly_interest * duration * loan_amount
        if diff_date > 30:
            # first payment more than 30 days
            total_days += diff_date - 30
            total_interest = (monthly_interest / 30) * loan_amount * total_days

        return total_interest


class DBSInterest(ChannelingInterest):
    def pmt_monthly_interest(
        self,
        installment,
    ):
        """
        calculate PMT for daily interest
        also have to make sure loan not exceed daily limit rate rule
        using PMT formula :
        PMT = (amount x percent) / (1 - (1 + percent)^-duration)
        for DBS roundup (math.ceil) instead using py2round (normal rounding)
        """
        os_principal = self.loan_amount
        channeling_loan_payments = []
        interest_dict = {}
        total_installment = 0
        total_interest = 0
        total_principal = 0
        for payment in self.payments:
            interest_fee = math.ceil(self.total_annual_interest * os_principal / 12)
            principal = math.ceil(installment - interest_fee)
            os_principal = math.ceil(os_principal - principal)
            interest_dict[payment.id] = interest_fee

            total_installment += math.ceil(installment)
            total_interest += interest_fee
            total_principal += principal
            # calculate daily interest
            channeling_loan_payments.append(
                ChannelingLoanPayment(
                    payment=payment,
                    due_date=payment.due_date,
                    due_amount=math.ceil(installment),
                    principal_amount=principal,
                    interest_amount=interest_fee,
                    channeling_type=self.channeling_type,
                    actual_daily_interest=0,
                )
            )

        start_date = timezone.localtime(self.loan.fund_transfer_ts_or_cdate).date()
        diff_date = (self.payments[0].due_date - start_date).days + 1
        daily_interest_fee = math.ceil(
            diff_date * self.total_annual_interest / self.days_in_year * self.loan_amount
        )
        channeling_loan_payments[0].actual_daily_interest = daily_interest_fee

        last_channeling_loan_payment = channeling_loan_payments[-1]
        if total_principal != self.loan_amount:
            # Edit last channeling_loan_payments (have to match loan_amount)
            principal_diff = total_principal - self.loan_amount
            last_channeling_loan_payment.principal_amount -= principal_diff
            total_principal -= principal_diff

        if total_interest != total_installment - total_principal:
            interest_diff = total_interest - (total_installment - total_principal)
            last_channeling_loan_payment.interest_amount -= interest_diff
            last_payment_id = last_channeling_loan_payment.payment.id
            interest_dict[last_payment_id] = last_channeling_loan_payment.interest_amount

        return channeling_loan_payments, interest_dict
