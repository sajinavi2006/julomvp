from __future__ import print_function
from django.core.management.base import BaseCommand
from juloserver.julo.models import Application, Loan, PaymentMethod
from juloserver.julo.banks import BankCodes, BankManager
from django.utils import timezone


class Comand(BaseCommand):
    help = 'disabled payment method VA MAYBANK for customer with SINARMAS registered bank'

    def handle(self, *args, **options):
        sinarmas_bank = BankManager.get_by_code_or_none(BankCodes.SINARMAS)
        loans = Loan.objects.filter(application__bank_name=sinarmas_bank.bank_name)

        for loan in loans:
            pm_obj_list = loan.paymentmethod_set.all()
            pm_code_list = [pm.bank_code for pm in pm_obj_list]
            pm_maybank = pm_obj_list.filter(bank_code=BankCodes.MAYBANK, is_shown=True).first()

            if BankCodes.CIMB_NIAGA not in pm_code_list:
                bva = BankVirtualAccount.objects.filter(loan=None,
                    bank_code__code=BankCodes.CIMB_NIAGA).first()

                PaymentMethod.objects.create(
                    payment_method_code=bva.bank_code.code,
                    payment_method_name=bva.bank_code.name,
                    bank_code=bva.bank_code.code,
                    loan=loan,
                    virtual_account=bva.virtual_account_number)

                print('successfully create Niaga Payment method for loan %s' % loan.id)

                bva.loan = loan
                bva.save()

            if pm_maybank is not None:
                pm_maybank.is_shown = False
                pm_maybank.save()

        self.stdout.write(self.style.SUCCESS('Successfully assign niaga as payment method and diasable maybank'))
