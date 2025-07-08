import copy
from builtins import str
from builtins import object
import logging

from ..models import Application
from ..models import Loan
from ..product_lines import ProductLineCodes
from ..statuses import LoanStatusCodes, PaymentStatusCodes
from ..workflows2.tasks import appsflyer_update_status_task
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.models import Workflow
from juloserver.julo.constants import WorkflowConst
from juloserver.julo_starter.services.services import check_is_j1_upgraded

logger = logging.getLogger(__name__)


class AppsFlyerService(object):

    def __init__(self):
        self.all_status = [100, 105, 106, 110, 120, 130, 135, 136, 137, 139, 143, 163, 171, 180, 189, 190]
        self.normal_status = [100, 105, 106, 120, 130, 135, 136, 137, 139, 143, 163, 171, 180]
        self.mtl_status = [110, 120, 180]
        self.stl_status = [110, 120, 180]
        self.ctl_status = [110, 120, 189]
        self.loc_status = [110, 120, 190]
        self.j1_status = [190]
        self.j1_addition_status = [121]
        self.j1_loan_status = [220, 250]
        self.account_status = [420, 421, 430]
        self.can_reapply_status = [135]
        self.grace_period_earlier_status = [330, 331]
        self.overdue_status = [332]
        self.can_reapply_3mth_reason = [
            'monthly_income_gt_3_million',
            'monthly_income',
            'sms_grace_period_3_months',
            'sms_grace_period_24_months',
            'job type blacklisted'
        ]
        self.can_reapply_12mth_reason = [
            'negative data in sd',
            'sms_delinquency_24_months',
            'email_delinquency_24_months',
            'negative payment history with julo'
        ]
        self.eligible_product = [
            ProductLineCodes.MTL1,
            ProductLineCodes.MTL2,
            ProductLineCodes.STL1,
            ProductLineCodes.STL2,
            ProductLineCodes.CTL1,
            ProductLineCodes.CTL2,
            ProductLineCodes.LOC,
        ]
        self.julo_starter_addition_status = [
            ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
            ApplicationStatusCodes.LOC_APPROVED,
        ]
        self.julo_starter_status = [
            ApplicationStatusCodes.FORM_CREATED,
            ApplicationStatusCodes.FORM_PARTIAL,
            ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
            ApplicationStatusCodes.LOC_APPROVED,
        ]
        self.duplicate_event_j1_jstarter_status = copy.copy(self.julo_starter_status)

    def appflyer_id(self, application):
        return application.customer.appsflyer_device_id

    def get_name_product_by_code(self, product_code):
        if product_code in ProductLineCodes.mtl():
            return 'MTL'
        elif product_code in ProductLineCodes.stl():
            return 'STL'
        elif product_code in ProductLineCodes.ctl():
            return 'CTL'
        elif product_code == ProductLineCodes.LOC:
            return 'LOC'
        else:
            return ''

    def info_eligible_product(self, application, products):
        if not self.appflyer_id(application):
            return
        for product in products:
            if product not in self.eligible_product:
                continue
            event_name = '105_ELIGIBLE_'
            event_name += self.get_name_product_by_code(product)
            appsflyer_update_status_task.delay(application.id, event_name)

    def info_application_status(self, application_id, status, status_old=None, status_new=None):
        application = Application.objects.get_or_none(pk=application_id)
        application_status_updated = True
        if application:
            valid_status = (
                status in self.all_status
                or application.is_julo_one_product() and status == ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
                or application.is_julo_starter() and status in self.julo_starter_addition_status
            )
            if valid_status and self.appflyer_id(application):
                history_exist = application.applicationhistory_set.filter(status_new=status,
                                                                          is_skip_workflow_action=False)
                if history_exist and len(history_exist) == 1:
                    history_exist = history_exist.first()
                    self.update_application_status(status, application, history_exist.change_reason,
                                                   status_old, status_new)
                    application_status_updated = False
                if ((status == ApplicationStatusCodes.FORM_PARTIAL) or
                    (status == ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED)) and application_status_updated:
                    appsflyer_update_status_task.delay(
                        application.id,
                        self.get_event_name(application, status),
                        status_old=status_old,
                        status_new=status_new
                    )
                    j1_ios_android_starter = application.is_julo_one_or_starter() or application.is_julo_one_ios()
                    if (
                        j1_ios_android_starter
                        and status in self.duplicate_event_j1_jstarter_status
                        and not check_is_j1_upgraded(application)
                    ):
                        appsflyer_update_status_task.delay(
                            application.id,
                            str(status),
                            status_old=status_old,
                            status_new=status_new
                        )

                last_application = Application.objects.filter(customer=application.customer).exclude(id=application.id).order_by('id').last()
                if last_application and status==ApplicationStatusCodes.FORM_CREATED:
                    if last_application.status == ApplicationStatusCodes.FORM_PARTIAL_EXPIRED:
                        appsflyer_update_status_task.delay(
                            application.id,
                            self.get_event_name(application, status, name='100_re'),
                            status_old=status_old,
                            status_new=status_new
                        )

    def get_event_name(self, application, status, name=None):
        if application.is_julo_starter() and status in self.julo_starter_status:
            return '{}_Turbo'.format(name or status)
        if application.is_julo_one() or application.is_julo_one_ios():
            return '{}_J1'.format(name or status)

        return str(name or status)

    def info_loan_status(self, loan_id):
        loan = Loan.objects.get_or_none(pk=loan_id)
        if not loan and loan.loan_status.status_code != LoanStatusCodes.PAID_OFF:
            return
        if not self.appflyer_id(loan.application):
            return
        self.update_loan_status(loan)

    def info_j1_loan_status(self, loan, loan_status, extra_params={}):
        loan.refresh_from_db()
        application = loan.get_application
        if loan_status in self.j1_loan_status and self.appflyer_id(application):
            if loan.loanhistory_set.filter(status_new=loan_status).exists():
                appsflyer_update_status_task.delay(application.id, str(loan_status), extra_params=extra_params)

    def update_application_status(self, status, application, change_reason,
                                  status_old=None, status_new=None):
        # for example name event = 100
        if status in self.normal_status:
            appsflyer_update_status_task.delay(
                application.id,
                self.get_event_name(application, status),
                status_old=status_old,
                status_new=status_new,
            )
            if (application.is_julo_one_or_starter()
                    and status in self.duplicate_event_j1_jstarter_status):
                if not check_is_j1_upgraded(application):
                    appsflyer_update_status_task.delay(
                        application.id,
                        str(status),
                        status_old=status_old,
                        status_new=status_new,
                    )

        # for example name event = 100_MTL
        if application.product_line:
            if status in self.mtl_status and application.product_line_code in ProductLineCodes.mtl():
                appsflyer_update_status_task.delay(application.id, str(status)+'_MTL',
                                                   status_old=status_old, status_new=status_new)
            elif status in self.stl_status and application.product_line_code in ProductLineCodes.stl():
                appsflyer_update_status_task.delay(application.id, str(status)+'_STL',
                                                   status_old=status_old, status_new=status_new)
            elif status in self.ctl_status and application.product_line_code in ProductLineCodes.ctl():
                appsflyer_update_status_task.delay(application.id, str(status)+'_CTL',
                                                   status_old=status_old, status_new=status_new)
            elif status in self.loc_status and application.product_line_code == ProductLineCodes.LOC:
                appsflyer_update_status_task.delay(application.id, str(status)+'_LOC',
                                                   status_old=status_old, status_new=status_new)
            elif status in [*self.j1_status, *self.j1_addition_status] and application.product_line_code == ProductLineCodes.J1:
                appsflyer_update_status_task.delay(
                    application.id, self.get_event_name(application, status),
                    status_old=status_old, status_new=status_new)
                if status in self.duplicate_event_j1_jstarter_status and not check_is_j1_upgraded(application):
                    appsflyer_update_status_task.delay(application.id, str(status),
                                                       status_old=status_old, status_new=status_new)

            elif (status in self.julo_starter_addition_status
                  and application.product_line_code == ProductLineCodes.JULO_STARTER):
                appsflyer_update_status_task.delay(application.id, '{}_Turbo'.format(status),
                                                   status_old=status_old, status_new=status_new)
                if status in self.duplicate_event_j1_jstarter_status:
                    appsflyer_update_status_task.delay(
                        application.id, str(status),
                        status_old=status_old, status_new=status_new)

        # for example name event = 135_CAN_REAPPLY_3MTH_[reason]
        if status in self.can_reapply_status and change_reason in self.can_reapply_3mth_reason:
            appsflyer_update_status_task.delay(application.id, '135_CAN_REAPPLY_3MTH',
                                               status_old=status_old, status_new=status_new)
        elif status in self.can_reapply_status and change_reason in self.can_reapply_12mth_reason:
            appsflyer_update_status_task.delay(application.id, '135_CAN_REAPPLY_12MTH',
                                               status_old=status_old, status_new=status_new)

    def update_loan_status(self, loan):
        # init data
        have_payment_late = False
        application = loan.application
        product_line_code = application.product_line_code
        payments = loan.payment_set.all().order_by('id')
        for payment in payments:
            if payment.payment_status.status_code == PaymentStatusCodes.PAID_LATE:
                have_payment_late = True

        if have_payment_late:
            appsflyer_update_status_task.delay(application.id, '250_LATE')
        if not have_payment_late and product_line_code in ProductLineCodes.mtl():
            appsflyer_update_status_task.delay(application.id, '250_MTL')
        elif not have_payment_late and product_line_code in ProductLineCodes.stl():
            appsflyer_update_status_task.delay(application.id, '250_STL')

    def info_account_status(self, account, account_status):
        account.refresh_from_db()
        application = account.application_set.last()
        if account_status in self.account_status and self.appflyer_id(application):
            if account.accountstatushistory_set.filter(status_new_id=account_status).exists():
                event_name = str(account_status)
                logger.info({
                    'event': 'info_account_status',
                    'msg': 'run appsflyer_update_status_task',
                    'data': {'application_id': application.id, 'event_name': event_name}
                })
                appsflyer_update_status_task.delay(application.id, event_name)
