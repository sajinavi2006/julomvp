import logging
from django.db.models import signals
from django.dispatch import receiver

from juloserver.integapiv1.tasks import update_va_bni_transaction
from juloserver.loan_refinancing.constants import CovidRefinancingConst
from juloserver.loan_refinancing.models import LoanRefinancingRequest
from juloserver.julo.models import Application
from juloserver.moengage.tasks import async_update_moengage_for_refinancing_request_status_change
from django.conf import settings

logger = logging.getLogger(__name__)


@receiver(signals.post_init, sender=LoanRefinancingRequest)
def get_data_before_loan_refinancing_request_updation(sender, instance=None, **kwargs):
    instance.__stored_status = instance.status


@receiver(signals.post_save, sender=LoanRefinancingRequest)
def get_data_after_loan_refinancing_request_updation(sender,
                                                     instance=None, created=False, **kwargs):
    loan_refinancing_request = instance
    if not loan_refinancing_request._state.adding:
        if loan_refinancing_request.__stored_status != loan_refinancing_request.status:
            loan = loan_refinancing_request.loan
            if loan and loan.application_id:
                application = Application.objects.get(pk=loan.application_id)
                if not application.is_julo_one():
                    async_update_moengage_for_refinancing_request_status_change.apply_async(
                        (loan_refinancing_request.id,),
                        countdown=settings.DELAY_FOR_MOENGAGE_API_CALL)


@receiver(signals.post_save, sender=LoanRefinancingRequest)
def post_data_bni_va(sender, created, instance=None, **kwargs):
    if instance:
        if instance.account:
            if created and instance.status == CovidRefinancingConst.STATUSES.approved:
                update_va_bni_transaction.delay(
                    instance.account.id,
                    'loan_refinancing.signals.post_data_bni_va',
                    instance.prerequisite_amount
                )
                return

            if not kwargs.get('update_fields'):
                return

            if 'status' in kwargs.get('update_fields'):
                if instance.status == CovidRefinancingConst.STATUSES.approved:
                    update_va_bni_transaction.delay(
                        instance.account.id,
                        'loan_refinancing.signals.post_data_bni_va',
                        instance.prerequisite_amount
                    )
                elif instance.status == CovidRefinancingConst.STATUSES.expired:
                    update_va_bni_transaction.delay(
                        instance.account.id,
                        'loan_refinancing.signals.post_data_bni_va',
                    )
