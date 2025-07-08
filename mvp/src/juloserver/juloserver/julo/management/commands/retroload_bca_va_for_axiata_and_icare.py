import base64
import csv
import os

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.db import transaction
from django.utils import timezone

from juloserver.julo.banks import BankCodes
from juloserver.julo.payment_methods import PaymentMethodCodes
from juloserver.julo.models import PaymentMethod, Loan, Application
from juloserver.julo.partners import PartnerConstant
from juloserver.julo.utils import format_mobile_phone
from juloserver.julo.services2.payment_method import get_application_primary_phone, active_va

class Command(BaseCommand):
    help = 'retroload_bca_va_for_axiata_and_icare'


    def handle(self, *args, **options):
        applications = Application.objects.filter(
            partner__name__in=(PartnerConstant.ICARE_PARTNER, PartnerConstant.AXIATA_PARTNER))

        for application in applications:
            if hasattr(application, 'loan'):
                loan = application.loan
                mobile_phone_1 = get_application_primary_phone(application)
                if mobile_phone_1:
                    mobile_phone_1 = format_mobile_phone(mobile_phone_1)

                    with transaction.atomic():
                        payment_methods = PaymentMethod.objects.filter(loan=loan)

                        if payment_methods:
                            payment_method = PaymentMethod.objects.filter(loan_id=loan.id,
                                payment_method_code=PaymentMethodCodes.BCA)

                            if not payment_method:
                                virtual_account = "".join([
                                    PaymentMethodCodes.BCA,
                                    mobile_phone_1
                                ])
                                PaymentMethod.objects.create(
                                    payment_method_code=PaymentMethodCodes.BCA,
                                    payment_method_name="Bank BCA",
                                    bank_code=BankCodes.BCA,
                                    customer=application.customer,
                                    is_shown=True,
                                    is_primary=False,
                                    loan=loan,
                                    virtual_account=virtual_account,
                                    sequence=None)

                                self.stdout.write(
                                    self.style.SUCCESS(
                                        'successfully add BCA VA for loan_id {} with VA number {}'.format(
                                            loan.id, virtual_account)
                                        ))

                            else:
                                self.stdout.write(
                                    self.style.WARNING(
                                        'failed add BCA VA for loan_id {} Payment Method Found'.format(
                                            loan.id)
                                        ))

                        else:
                            self.stdout.write(
                                self.style.WARNING(
                                    'failed add BCA VA for loan_id {} Payment Method Not Found'.format(
                                        loan.id)
                                    ))
                else:
                    self.stdout.write(
                        self.style.WARNING(
                            'failed add BCA VA for application_id {} Phone Number Not Found'.format(
                                application.id)
                            ))
            else:
                self.stdout.write(
                    self.style.WARNING(
                        'failed add BCA VA for application_id {} Loan Not Generated'.format(
                            application.id)
                        ))

        self.stdout.write(self.style.SUCCESS('Successfully retro load existing data'))