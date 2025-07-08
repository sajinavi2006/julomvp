import itertools
import logging
from datetime import timedelta

from celery import task
from django.conf import settings
from django.db.models import F
from django.utils import timezone

from juloserver.julo.statuses import (
    ApplicationStatusCodes,
    LoanStatusCodes,
    PaymentStatusCodes,
)
from juloserver.julocore.utils import get_minimum_model_id
from juloserver.pusdafil.services import (
    get_pusdafil_service,
    validate_pusdafil_customer_data,
)
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import (
    Application,
    FeatureSetting,
    Loan,
    Payment,
)

logger = logging.getLogger(__name__)


@task(name='task_report_new_user_registration', bind=True, queue='application_pusdafil')
def task_report_new_user_registration(self, user_id, force=False):
    service = get_pusdafil_service()

    if not service:
        return
    service.report_new_user_registration(user_id, force)


@task(name='task_report_new_lender_registration', bind=True, queue='application_pusdafil')
def task_report_new_lender_registration(self, lender_id):
    service = get_pusdafil_service()

    if not service:
        return
    service.report_new_lender_registration(lender_id)


@task(name='task_report_new_borrower_registration', bind=True, queue='application_pusdafil')
def task_report_new_borrower_registration(self, customer_id, force=False):
    service = get_pusdafil_service()

    if not service:
        return
    service.report_new_borrower_registration(customer_id, force)


@task(name='task_report_new_application_registration', bind=True, queue='application_pusdafil')
def task_report_new_application_registration(self, application_id, force=False):
    service = get_pusdafil_service()

    if not service:
        return
    service.report_new_application_registration(application_id, force)


@task(name='task_report_new_loan_registration', bind=True, queue='application_pusdafil')
def task_report_new_loan_registration(self, loan_id, force=False):
    service = get_pusdafil_service()

    if not service:
        return
    service.report_new_loan_registration(loan_id, force)


@task(name='task_report_new_loan_approved', bind=True, queue='application_pusdafil')
def task_report_new_loan_approved(self, loan_id, force=False):
    service = get_pusdafil_service()

    if not service:
        return
    service.report_new_loan_approved(loan_id, force)


@task(name='task_report_new_loan_payment_creation', bind=True, queue='application_pusdafil')
def task_report_new_loan_payment_creation(self, payment_id):
    service = get_pusdafil_service()

    if not service:
        return
    service.report_new_loan_payment_creation(payment_id)


@task(queue='application_pusdafil')
def task_daily_deactivate_pusdafil():
    feature_setting = FeatureSetting.objects.get(feature_name=FeatureNameConst.PUSDAFIL)
    feature_setting.is_active = False
    feature_setting.save()


@task(queue='application_pusdafil')
def task_daily_activate_pusdafil():
    feature_setting = FeatureSetting.objects.get(feature_name=FeatureNameConst.PUSDAFIL)
    feature_setting.is_active = True
    feature_setting.save()

    if settings.ENVIRONMENT != 'prod':
        return

    task_daily_sync_pusdafil_loan.delay(7)
    task_daily_sync_pusdafil_payment.delay(7)


@task(queue='application_pusdafil')
def task_daily_sync_pusdafil_loan(timedelta_day=0):
    check_datetime = timezone.localtime(timezone.now()) - timedelta(days=timedelta_day)
    check_datetime = check_datetime.replace(hour=0, minute=0, second=0, microsecond=0)

    # 200000 is the estimation data growth of loan data in 7 days
    min_loan_id = get_minimum_model_id(Loan, check_datetime, 200000)

    app_status = [
        ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
        ApplicationStatusCodes.LOC_APPROVED,
    ]
    loan_qs = (
        Loan.objects.filter(
            loan_status__in=LoanStatusCodes.pusdafil_loan_status(),
            id__gte=min_loan_id,
            cdate__gte=check_datetime,
        )
        .annotate(
            user_id=F('customer__user_id'),
        )
        .order_by('-id')
        .distinct('id')
    )

    # Application-based Loan
    application_based_loan_ids = (
        loan_qs.filter(
            application__application_status_id__in=app_status,
            account__isnull=True,
        )
        .annotate(real_application_id=F('application_id'))
        .values('id', 'customer_id', 'user_id', 'real_application_id')
    )

    # Account-based loan
    account_based_loan_ids = (
        loan_qs.filter(
            account__application__application_status_id__in=app_status,
            application__isnull=True,
        )
        .annotate(real_application_id=F('account__application__id'))
        .values('id', 'customer_id', 'user_id', 'real_application_id')
    )

    loan_ids = itertools.chain(
        account_based_loan_ids.iterator(),
        application_based_loan_ids.iterator(),
    )
    for data in loan_ids:
        bunch_of_loan_creation_tasks.delay(
            user_id=data.get('user_id'),
            customer_id=data.get('customer_id'),
            application_id=data.get('real_application_id'),
            loan_id=data.get('loan_id'),
        )


@task(queue='application_pusdafil')
def task_daily_sync_pusdafil_payment(timedelta_day=0):
    check_datetime = timezone.localtime(timezone.now()) - timedelta(days=timedelta_day)
    check_datetime = check_datetime.replace(hour=0, minute=0, second=0, microsecond=0)

    payment_ids = Payment.objects.filter(
        payment_status_id__in=PaymentStatusCodes.paid_status_codes(),
        due_amount=0,
        udate__gte=check_datetime,
    ).values_list('id', flat=True)
    for payment_id in payment_ids.iterator():
        task_report_new_loan_payment_creation.delay(payment_id)


@task(queue='application_pusdafil')
def bunch_of_loan_creation_tasks(user_id, customer_id, application_id, loan_id, force=False):
    applications = Application.objects.filter(id=application_id)

    # Do not send data to pusdafil if the data is not complete or not mapable
    # only for Dana Application
    if applications and applications.last().is_dana_flow():
        # Check fund_transfer_ts on loan
        fund_transfer_ts = Loan.objects.filter(pk=loan_id).values('fund_transfer_ts').last()
        if validate_pusdafil_customer_data(applications) and fund_transfer_ts:
            task_report_new_user_registration(user_id, force)
            task_report_new_borrower_registration(customer_id, force)

            task_report_new_application_registration(application_id, force)
            task_report_new_loan_registration(loan_id, force)
            task_report_new_loan_approved(loan_id, force)
        else:
            logger.info(
                {
                    'action': 'dana_validate_pusdafil_customer_data',
                    'message': 'application data not complete, data not sent to pusdafil',
                    'error': 'fund_transfer_ts is null, loan_id is {}'.format(loan_id),
                }
            )
            return
    else:
        # only report once making the first loan
        task_report_new_user_registration(user_id, force)
        task_report_new_borrower_registration(customer_id, force)

        task_report_new_application_registration(application_id, force)
        task_report_new_loan_registration(loan_id, force)
        task_report_new_loan_approved(loan_id, force)
