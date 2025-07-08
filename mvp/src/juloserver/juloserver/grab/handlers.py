"""contain handler"""

from juloserver.julo.workflows2.handlers import BaseActionHandler
from .workflows import GrabWorkflowAction
from juloserver.grab.services.services import (
    verify_grab_loan_offer,
    EmergencyContactService,
    get_redis_client
)
from juloserver.grab.tasks import trigger_action_handler_124_to_190_grab
from juloserver.julo.models import ApplicationStatusCodes, Application
from django.db.models import Q


class GrabActionHandler(BaseActionHandler):
    def __init__(self, *arg, **karg):
        super(GrabActionHandler, self).__init__(*arg, **karg)
        self.action = GrabWorkflowAction(self.application, self.new_status_code,
                                         self.change_reason, self.note, self.old_status_code)


class Grab105Handler(GrabActionHandler):
    def post(self):
        self.action.update_customer_data()
        self.action.trigger_anaserver_status105()


class Grab106Handler(GrabActionHandler):
    def post(self):
        pass


class Grab124Handler(GrabActionHandler):
    def get_previous_application(self):
        app = Application.objects.filter(
            customer=self.application.customer,
            kin_mobile_phone=self.application.kin_mobile_phone
        ).filter(Q(is_kin_approved=1) | Q(is_kin_approved=2)).exclude(id=self.application.id)
        return app.last()

    def post(self):
        ec_service = EmergencyContactService(
            redis_client=get_redis_client(),
            sms_client=None
        )

        if ec_service.get_feature_settings_parameters():
            previous_app = self.get_previous_application()
            if previous_app:
                self.application.is_kin_approved = previous_app.is_kin_approved
                self.application.save()
            else:
                ec_service.save_application_id_to_redis(self.application.id)

        trigger_action_handler_124_to_190_grab.apply_async(
            (self.application.id,), queue='application_high')


class Grab150Handler(GrabActionHandler):
    def change_status_to_180(self):
        self.action.change_status_150_to_180()

    def change_status_to_190(self):
        self.action.register_or_update_customer_to_privy()

    def request_fdc_data(self):
        self.action.request_fdc_data()

    def post(self):
        result = self.action.is_max_creditors_reached()
        is_pending = result.get("is_pending")
        is_out_date = result.get("is_out_date")
        is_fdc_exists = result.get("is_fdc_exists")
        if True in {is_pending, is_out_date} or not is_fdc_exists:
            self.request_fdc_data()
            return

        if result.get("is_max_creditors_reached"):
            self.change_status_to_180()
            return

        self.change_status_to_190()


class Grab190Handler(GrabActionHandler):
    def post(self):
        self.action.process_grab_at_190()
        self.action.populate_bank_account_destination()
        self.action.create_grab_loan()

    def async_task(self):
        self.action.update_status_apps_flyer()
        self.action.trigger_ayoconnect_beneficiary()


class Grab130Handler(GrabActionHandler):

    def post(self):
        # self.action.process_affordability_calculation()
        self.action.verify_loan_offer()
        loan_offer_flag = verify_grab_loan_offer(self.application)
        if loan_offer_flag:
            self.action.process_credit_limit_generation()
            self.action.update_grab_limit()
            self.action.generate_grab_credit_score()
        # self.action.change_status_130_to_141()


class Grab141Handler(GrabActionHandler):
    def post(self):
        self.action.generate_payment_method()
        self.action.change_status_141_to_150()

class Grab185Handler(GrabActionHandler):
    pass

class Grab186Handler(GrabActionHandler):
    pass


class Grab131Handler(GrabActionHandler):
    def async_task(self):
        if self.application.is_grab():
            self.action.send_grab_sms_status_change_131()
            self.action.send_grab_email_status_change_131()

    def post(self):
        self.action.process_documents_resubmission_action()
        if self.old_status_code is not ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR:
            self.action.process_documents_resubmission_action()


class Grab180Handler(GrabActionHandler):
    def post(self):
        pass
