from builtins import str
from django.core.management.base import BaseCommand
from django.db import transaction
from juloserver.julo.models import Disbursement, Loan
from juloserver.disbursement.models import Disbursement as Disbursement2
from juloserver.disbursement.models import NameBankValidation


class Command(BaseCommand):
    help = 'retroactively load new disbursement flow for disbursed loan'

    def handle(self, *args, **options):
        old_disbursements = Disbursement.objects.all()
        total_disbursed = old_disbursements.count()
        success = []
        failed = []
        self.stdout.write(self.style.SUCCESS(
            '================= retroload disbursed loan to disbursement begin %s '
            '=========================' % (total_disbursed)
        ))
        name_bank_validations = []
        new_disbursements = []
        for old_disbursement in old_disbursements:
            try:
                with transaction.atomic():
                    # create new name bank validation
                    loan = Loan.objects.select_for_update().get(pk=old_disbursement.loan_id)
                    is_loaded = loan.name_bank_validation_id is not None and \
                                loan.disbursement_id is not None
                    if is_loaded:
                        self.stdout.write(self.style.WARNING(
                            'new disbursement for loan %s already loaded' % (loan.id)
                        ))
                        continue

                    new_name_bank_validation_fields = ['bank_code', 'account_number' ,
                                                       'name_in_bank', 'method',
                                                       'validation_id', 'validation_status',
                                                       'validated_name', 'mobile_phone', 'reason']
                    name_bank_validation = NameBankValidation.objects.create(
                        bank_code=old_disbursement.bank_code,
                        account_number=old_disbursement.bank_number,
                        name_in_bank=old_disbursement.loan.application.name_in_bank,
                        validated_name=old_disbursement.validated_name,
                        validation_id=old_disbursement.validation_id,
                        validation_status=old_disbursement.validation_status,
                        method='Instamoney',
                        reason='retroload')
                    name_bank_validation.create_history(
                        'retroload', new_name_bank_validation_fields)
                    # create new disbursement
                    new_disbursement_fields = ['name_bank_validation_id', 'external_id', 'amount',
                                               'method', 'disburse_id', 'disburse_status',
                                               'retry_times', 'reason']
                    disburse_amount = old_disbursement.disburse_amount
                    if disburse_amount is None:
                        disburse_amount = loan.loan_disbursement_amount
                    new_disbursement = Disbursement2.objects.create(
                        name_bank_validation=name_bank_validation,
                        external_id=old_disbursement.external_id,
                        amount=disburse_amount,
                        method='Instamoney',
                        disburse_id=old_disbursement.disburse_id,
                        disburse_status=old_disbursement.disburse_status,
                        retry_times=old_disbursement.retry_times,
                        reason='retroload')
                    new_disbursement.create_history('retroload', new_disbursement_fields)
                    # assign loan 
                    loan.name_bank_validation_id = name_bank_validation.id
                    loan.disbursement_id = new_disbursement.id
                    loan.save()
                success.append(old_disbursement.loan_id)
            except Exception as e:
                failed.append(old_disbursement.loan_id)
                self.stdout.write(self.style.ERROR(str(e)))

        self.stdout.write(self.style.SUCCESS(
            'Success retroload %s disbursed_loan %s' % (
                len(success), success)
            ))
        if len(failed) > 0:
            self.stdout.write(self.style.ERROR(
                'Failed retroload %s disbursed_loan %s' % (
                    len(failed), failed)
                ))
