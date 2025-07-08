from builtins import str
from builtins import object
import logging
from juloserver.julo.models import (
    Customer,
    VendorDataHistory,
)
from juloserver.julo.constants import ReminderTypeConst
from ..helpers.reminders import parse_template_reminders
from ..product_lines import ProductLineCodes

logger = logging.getLogger(__name__)


class Reminder(object):
    def create_reminder_history(self, payment=None, customer=None, template=None,
                                vendor=None, reminder_type=None):
        """
            To create data that contain reminder
            information that use vendor to send reminder to customer
        """

        if vendor is None:
            logger.warn({
                'error': 'Vendor is empty'
            })

            return

        reminder = {}

        if payment is not None:
            reminder['loan'] = payment.loan
            reminder['loan_status_code'] = payment.loan.loan_status.status_code
            reminder['payment'] = payment
            reminder['payment_status_code'] = payment.payment_status.status_code

            if payment.is_ptp_robocall_active is None and not template:
                product_type = str(payment.loan.application.product_line.product_line_type)[:-1]

                if reminder_type == ReminderTypeConst.ROBOCALL_TYPE_REMINDER:
                    if payment.loan.application.product_line_id in ProductLineCodes.pede():
                        product_type = 'STL'

                    template = parse_template_reminders(payment.due_date, product_type, True)

        reminder['vendor'] = vendor
        reminder['template_code'] = template
        reminder['customer_id'] = customer.id if isinstance(customer, Customer) else customer
        reminder['reminder_type'] = reminder_type

        vendor_data_history = VendorDataHistory(**reminder)
        vendor_data_history.save()

    @staticmethod
    def create_j1_reminder_history(
        account_payment=None, customer=None, template=None, vendor=None, reminder_type=None
    ):
        """
            To create data that contain reminder
            information that use vendor to send reminder to customer
        """

        if vendor is None:
            logger.warn({
                'error': 'Vendor is empty'
            })

            return

        reminder = {}

        if account_payment is not None:
            reminder['account_id'] = account_payment.account_id
            reminder['account_payment_id'] = account_payment.id
            reminder['account_payment_status_code'] = account_payment.status_id

        reminder['vendor'] = vendor
        reminder['template_code'] = template
        reminder['customer_id'] = customer.id if isinstance(customer, Customer) else customer
        reminder['reminder_type'] = reminder_type

        vendor_data_history = VendorDataHistory(**reminder)
        vendor_data_history.save()
