from django.core.management.base import BaseCommand

from django.conf import settings

from juloserver.julo.banks import BankCodes
from juloserver.julo.models import BankVirtualAccount
from juloserver.julo.models import Loan, PaymentMethod
from juloserver.julo.models import PaymentMethodLookup
from juloserver.julo.models import VirtualAccountSuffix
from juloserver.julo.partners import PartnerConstant
from juloserver.julo.payment_methods import PaymentMethodCodes, PaymentMethodManager
from juloserver.julo.statuses import LoanStatusCodes
from django.utils import timezone


class Command(BaseCommand):
    help = 'retroactively create payment method for existing loan'

    def handle(self, *args, **options):
        query = Loan.objects.filter(
            loan_status__status_code__lt=LoanStatusCodes.PAID_OFF).exclude(
            loan_status__status_code=LoanStatusCodes.INACTIVE)
        for loan in query:
            payment_methods = PaymentMethod.objects.filter(loan=loan)
            if len(payment_methods) > 0:
                continue
            else:
                va_suffix_obj = VirtualAccountSuffix.objects.filter(loan=None, account=None).first()
                if va_suffix_obj is None:
                    logger.error({
                        'application_id': loan.application.id,
                        'application_status': loan.application.application_status.status,
                        'status': 'no more bank virtual account availabe'
                    })
                    raise JuloException('no more bank virtual account availabe!!!!')

                va_suffix = va_suffix_obj.virtual_account_suffix

                default_payment_methods = [
                    PaymentMethodManager.get_or_none(PaymentMethodCodes.ALFAMART),
                    PaymentMethodManager.get_or_none(PaymentMethodCodes.INDOMARET)
                ]

                if loan.application.partner is not None:
                    if loan.application.partner.name == PartnerConstant.DOKU_PARTNER:
                        default_payment_methods.append(
                            PaymentMethodManager.get_or_none(PaymentMethodCodes.DOKU))

                bva = BankVirtualAccount.objects.filter(
                    loan=loan).first()
                if bva is not None:
                    bank_virtual_account= bva.virtual_account_number
                    bank_obj = bva.bank_code
                    bank_code = bank_obj.code
                    payment_method_name = PaymentMethodManager.get_or_none(bank_code)

                    PaymentMethod.objects.create(
                        payment_method_code=bank_code,
                        payment_method_name=bank_obj.name,
                        bank_code=bank_code,
                        loan=loan,
                        virtual_account=bank_virtual_account
                    )

                customer_bank_name = loan.application.bank_name
                if customer_bank_name is not None:
                    """currently we only use PERMATA AND MANDIRI if BCA and BRI already activate we need to add more condition here"""
                    if "BANK PERMATA" in customer_bank_name:
                        bank_code = BankCodes.PERMATA

                    else:
                        bank_code = BankCodes.MANDIRI

                    default_payment_methods.append(PaymentMethodManager.get_or_none(bank_code))

            for payment_method in default_payment_methods:
                if 'Doku' in payment_method.name:
                    virtual_account = settings.DOKU_ACCOUNT_ID
                    payment_method_code = PaymentMethodCodes.DOKU
                if 'Doku' not in payment_method.name:
                    virtual_account = payment_method.faspay_payment_code + va_suffix
                    payment_method_code = payment_method.faspay_payment_code
                if payment_method.type == 'non_bank':
                    pm_bank_code = None
                else:
                    pm_bank_code = payment_method.code

                PaymentMethod.objects.create(
                    payment_method_code=payment_method_code,
                    payment_method_name=payment_method.name,
                    bank_code=pm_bank_code,
                    loan=loan,
                    virtual_account=virtual_account
                )

            va_suffix_obj.loan = loan
            va_suffix_obj.save()


        self.stdout.write(self.style.SUCCESS('Successfully created retroactive payment methods'))
