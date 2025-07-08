import logging
from abc import ABCMeta, abstractmethod
from builtins import str

import semver
from six import with_metaclass
from django.utils import timezone

from juloserver.apiv2.services import false_reject_min_exp
from juloserver.application_flow.services import is_experiment_application
from juloserver.boost.services import check_scrapped_bank
from juloserver.disbursement.constants import NameBankValidationStatus
from juloserver.julo.constants import (
    FeatureNameConst,
    HighScoreFullByPassConstant,
    WorkflowConst,
)
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import (
    Application,
    CreditScore,
    FaceRecognition,
    FeatureSetting,
    MobileFeatureSetting,
)
from juloserver.julo.partners import PartnerConstant
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.utils import post_anaserver
from juloserver.julo.workflows import WorkflowAction
from juloserver.julo.workflows2.schemas.cash_loan import CashLoanSchema
from juloserver.sdk.constants import LIST_PARTNER, PARTNER_LAKU6, PARTNER_PEDE
from juloserver.fdc.services import check_fdc_is_ready_to_refresh

from ..constants import WorkflowConst
from ..models import StatusLookup, WorkflowStatusNode, FDCInquiry
from ..product_lines import ProductLineCodes
from ..statuses import ApplicationStatusCodes
from ..workflows import WorkflowAction


logger = logging.getLogger(__name__)


def execute_action(application, old_status_code, new_status_code, change_reason, note, workflow, action_type='pre'):
    dest_node = WorkflowStatusNode.objects.filter(
        status_node=new_status_code, workflow=workflow
    ).cache().last()
    dest_node_handler = dest_node.handler if dest_node else None
    status_before_handler = None
    status_handler = None
    if application.is_julo_one() and dest_node_handler:
        from juloserver.application_flow.handlers import (  # noqa
            JuloOne105Handler,
            JuloOne115Handler,
            JuloOne120Handler,
            JuloOne121Handler,
            JuloOne122Handler,
            JuloOne124Handler,
            JuloOne127Handler,
            JuloOne128Handler,
            JuloOne130Handler,
            JuloOne131Handler,
            JuloOne132Handler,
            JuloOne133Handler,
            JuloOne135Handler,
            JuloOne136Handler,
            JuloOne137Handler,
            JuloOne138Handler,
            JuloOne139Handler,
            JuloOne140Handler,
            JuloOne141Handler,
            JuloOne142Handler,
            JuloOne150Handler,
            JuloOne155Handler,
            JuloOne162Handler,
            JuloOne172Handler,
            JuloOne179Handler,
            JuloOne183Handler,
            JuloOne184Handler,
            JuloOne185Handler,
            JuloOne186Handler,
            JuloOne188Handler,
            JuloOne190Handler,
        )
    elif application.is_julo_one_ios() and dest_node_handler:
        from juloserver.ios.handlers import (  # noqa
            JuloOneIOSWorkflowHandler,
            JuloOneIOS105Handler,
            JuloOneIOS115Handler,
            JuloOneIOS120Handler,
            JuloOneIOS121Handler,
            JuloOneIOS124Handler,
            JuloOneIOS127Handler,
            JuloOneIOS130Handler,
            JuloOneIOS131Handler,
            JuloOneIOS132Handler,
            JuloOneIOS133Handler,
            JuloOneIOS135Handler,
            JuloOneIOS136Handler,
            JuloOneIOS137Handler,
            JuloOneIOS140Handler,
            JuloOneIOS141Handler,
            JuloOneIOS142Handler,
            JuloOneIOS150Handler,
            JuloOneIOS175Handler,
            JuloOneIOS179Handler,
            JuloOneIOS183Handler,
            JuloOneIOS184Handler,
            JuloOneIOS190Handler,
        )
    elif application.is_merchant_flow():
        from juloserver.application_flow.handlers import (  # noqa
            MerchantFinancing100Handler,
            MerchantFinancing105Handler,
            MerchantFinancing120Handler,
            MerchantFinancingWorkflowHandler,
        )
        from juloserver.merchant_financing.handlers import (  # noqa
            MerchantFinancing130Handler,
            MerchantFinancing135Handler,
            MerchantFinancing160Handler,
            MerchantFinancing190Handler,
            MerchantFinancingWorkflowHandler,
        )
    elif application.is_grab() and dest_node_handler:
        from juloserver.grab.handlers import (  # noqa
            Grab105Handler,
            Grab106Handler,
            Grab124Handler,
            Grab130Handler,
            Grab131Handler,
            Grab141Handler,
            Grab150Handler,
            Grab185Handler,
            Grab186Handler,
            Grab180Handler,
            Grab190Handler,
            GrabActionHandler,
            GrabWorkflowAction,
        )
    elif application.is_julover() and dest_node_handler:
        from juloserver.julovers.handlers import (  # noqa
            Julover105Handler,
            Julover130Handler,
            Julover141Handler,
            Julover190Handler,
            JuloverWorkflowHandler,
        )
    elif application.is_dana_flow() and dest_node_handler:
        from juloserver.dana.handlers import (  # noqa
            Dana105Handler,
            Dana130Handler,
            Dana133Handler,
            Dana135Handler,
            Dana190Handler,
            DanaWorkflowHandler,
        )
    elif application.is_julo_starter() and dest_node_handler:
        from juloserver.julo_starter.handlers import (  # noqa
            JuloStarter105Handler,
            JuloStarter106Handler,
            JuloStarter107Handler,
            JuloStarter108Handler,
            JuloStarter109Handler,
            JuloStarter115Handler,
            JuloStarter121Handler,
            JuloStarter133Handler,
            JuloStarter135Handler,
            JuloStarter137Handler,
            JuloStarter153Handler,
            JuloStarterWorkflowHandler,
            JuloStarter183Handler,
            JuloStarter184Handler,
            JuloStarter185Handler,
            JuloStarter186Handler,
            JuloStarter190Handler,
            JuloStarter191Handler,
            JuloStarter192Handler,
        )
    elif application.is_mf_web_app_flow() and dest_node_handler:
        from juloserver.merchant_financing.web_app.handlers import(
            PartnershipMfWebAppWorkflowHandler,
            PartnershipMF100Handler,
            PartnershipMF105Handler,
            PartnershipMF130Handler,
            PartnershipMF141Handler,
            PartnershipMF131Handler,
            PartnershipMF132Handler,
            PartnershipMF133Handler,
            PartnershipMF135Handler,
            PartnershipMF190Handler,
        )
    else:
        if action_type == 'after':
            status_before = StatusLookup.objects.get_or_none(status_code=old_status_code)
            status_before_handler = status_before.handler if status_before else None
        else:
            status_destination = StatusLookup.objects.get_or_none(status_code=new_status_code)
            status_handler = status_destination.handler if status_destination else None

    workflow_handler = workflow.handler
    product_handler = application.product_line.handler if application.product_line else None
    global_handler = 'GlobalHandler'

    handlers = [
        status_before_handler, dest_node_handler,
        status_handler, workflow_handler, product_handler, global_handler
    ]

    if handlers:
        for handler_class in handlers:
            if handler_class:
                handler = eval(handler_class)
                handler = handler(application, old_status_code, new_status_code, change_reason, note)
                eval("handler.%s()" % action_type)
    return True


class ActionHandlerAbstract(with_metaclass(ABCMeta, object)):
    def __init__(self, application, old_status_code, new_status_code, change_reason, note):
        self.application = application
        self.new_status_code = new_status_code
        self.change_reason = change_reason
        self.note = note
        self.old_status_code = old_status_code
        self.action = WorkflowAction(self.application, self.new_status_code,
                                     self.change_reason, self.note, self.old_status_code)
        super(ActionHandlerAbstract, self).__init__()

    @abstractmethod
    def pre(self):
        pass

    @abstractmethod
    def async_task(self):
        pass

    @abstractmethod
    def post(self):
        pass

    @abstractmethod
    def after(self):
        pass


class BaseActionHandler(ActionHandlerAbstract):
    def pre(self):
        pass

    def async_task(self):
        pass

    def post(self):
        pass

    def after(self):
        pass


# global Handler
class GlobalHandler(BaseActionHandler):
    def pre(self):
        pass


# MTL1
class ProductMTL1Handler(BaseActionHandler):
    pass

# example ## for default Legacy Workflow


# status 120
class LegacyWorkflowNode120Handler(BaseActionHandler):
    pass


# Workflow handler
class LegacyWorkflowHandler(BaseActionHandler):
    pass


class SubmittingFormWorkflowHandler(BaseActionHandler):
    pass


class CashLoanWorkflowHandler(BaseActionHandler):
    pass


class LineOfCreditWorkflowHandler(BaseActionHandler):
    pass


class GrabFoodWorkflowHandler(BaseActionHandler):
    pass


class PartnerWorkflowHandler(BaseActionHandler):
    pass


class JuloOneWorkflowHandler(BaseActionHandler):
    pass


class JuloOneIOSWorkflowHandler(BaseActionHandler):
    pass


class GrabWorkflowHandler(BaseActionHandler):
    pass


class JuloStarterWorkflowHandler(BaseActionHandler):
    pass


# handlers for default status
# default status handler naming convention
# Status<status_code>Handler
# example Status100Handler

# 100
class Status100Handler(BaseActionHandler):
    def post(self):
        if not self.application.partner:
            self.action.update_status_apps_flyer()
        if self.application.ktp:
            if check_fdc_is_ready_to_refresh(application_id=self.application.id):
                self.action.run_fdc_task()


# 105
class Status105Handler(BaseActionHandler):
    def post(self):
        if self.old_status_code is ApplicationStatusCodes.FORM_CREATED:
            if self.application.is_new_version() or\
                    (self.application.partner and self.application.partner.name in LIST_PARTNER):
                self.action.update_customer_data()
                self.action.trigger_anaserver_status105()
            elif self.application.is_merchant_flow() or self.application.company != None:
                self.action.trigger_anaserver_status105()
            else:
                # handle transition from application v2 to v3
                self.action.switch_back_to_100_and_update_app_version()


# 106
class Status106Handler(BaseActionHandler):
    def async_task(self):
        if not self.application.partner:
            self.action.update_status_apps_flyer()

    def post(self):
        self.action.process_application_reapply_status_action()
        self.action.trigger_anaserver_short_form_timeout()


# 111
class Status111Handler(BaseActionHandler):
    def async_task(self):
        self.action.send_email_status_change()

    def post(self):
        self.action.process_customer_may_reapply_action()


# 120 TODO: check this
class Status120Handler(BaseActionHandler):
    def pre(self):
        if self.old_status_code in {ApplicationStatusCodes.FORM_SUBMITTED, ApplicationStatusCodes.FORM_PARTIAL}:
            if self.application.partner and self.application.partner.name in LIST_PARTNER:
                pass
            else:
                self.action.assigning_optional_field()
                self.action.auto_populate_expenses()

    def async_task(self):
        logger.info(
            {"application_id": self.application.id, "message": "Status120Handler.async_task"}
        )
        if self.application.partner and not self.application.workflow.name == WorkflowConst.GRAB:
            if getattr(self.application, 'creditscore', None):
                self.action.run_advance_ai_task()
        else:
            self.action.update_status_apps_flyer()
        self.action.remove_application_from_fraud_application_bucket()  # will make is_active false for app status from x115

    def post(self):
        logger.info({"application_id": self.application.id, "message": "Status120Handler.post"})
        if check_scrapped_bank(self.application):
            url = '/api/amp/v1/bank-scrape-model'
            try:
                post_anaserver(url, json={'application_id': self.application.id})
            except JuloException as e:
                logger.error('error predict bank scrap data, error=%s' % str(e))

        # process BPJS for waitlist bucket
        from juloserver.bpjs.services.bpjs_direct import bypass_bpjs_waitlist
        if self.old_status_code == ApplicationStatusCodes.WAITING_LIST:
            bpjs_bypass = bypass_bpjs_waitlist(self.application)

            if bpjs_bypass:
                return

        if self.old_status_code in {ApplicationStatusCodes.FORM_SUBMITTED, ApplicationStatusCodes.FORM_PARTIAL}:
            self.action.process_verify_ktp()
            if self.application.is_julo_one() and \
                    not is_experiment_application(self.application.id, 'ExperimentUwOverhaul'):
                self.action.check_face_similarity()
                self.action.face_matching_task()

            if self.application.partner and self.application.partner.name == PARTNER_LAKU6:
                self.action.process_name_bank_validate_earlier()

            if self.application.partner and self.application.partner.name in LIST_PARTNER:
                self.action.trigger_anaserver_status120()
            else:
                self.action.process_customer_may_not_reapply_action()
                if not self.application.is_new_version():
                    self.action.trigger_anaserver_status120()

    def after(self):
        pass


# 122
class Status122Handler(BaseActionHandler):
    def pre(self):
        self.action.check_is_credit_score_ready()

    def async_task(self):
        if self.old_status_code is not ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR:
            self.action.process_documents_verified_action()
        # delete proccess OBP by request data engineer: https://juloprojects.atlassian.net/browse/ON-439
        # self.action.trigger_anaserver_status122()
    def post(self):
        self.action.send_lead_data_to_primo()
        #customer first apply(MTL1)
        if self.old_status_code == ApplicationStatusCodes.SCRAPED_DATA_VERIFIED and \
            not false_reject_min_exp(self.application):
            self.action.process_experiment_bypass()
            self.action.process_experiment_iti_low_threshold()
        # check for new parallel high score bypass experiment
        # customer reapply (MTL2)
        elif self.old_status_code == ApplicationStatusCodes.DOCUMENTS_SUBMITTED and \
            not false_reject_min_exp(self.application):
            self.action.process_experiment_repeat_high_score_ITI_bypass()

        if self.application.partner and self.application.partner.name in LIST_PARTNER:
            self.action.handle_line_partner_document_verified_post_action()

    def after(self):
        self.action.delete_lead_data_from_primo()
        self.action.app122queue_set_called()


#124
class Status124Handler(BaseActionHandler):
    def post(self):
        self.action.send_lead_data_to_primo()

    def after(self):
        self.action.delete_lead_data_from_primo()

#125
class Status125Handler(BaseActionHandler):
    def post(self):
        if self.application.partner and self.application.partner.name in LIST_PARTNER:
            pass
        else:
            self.action.process_experiment_bypass_iti_125()

# 130
class Status130Handler(BaseActionHandler):
    def async_task(self):
        if not self.application.partner:
            self.action.update_status_apps_flyer()

    def post(self):
        self.action.adjust_monthly_income_by_iti_score()
        self.action.process_offer_experiment_iti_low_threshold()
        if self.application.partner and self.application.partner.name == PARTNER_PEDE:
            self.action.change_status_130_to_172()


# 131
class Status131Handler(BaseActionHandler):
    def async_task(self):
        if (self.old_status_code is ApplicationStatusCodes.SCRAPED_DATA_VERIFIED and
                not self.application.is_grab()):
            self.action.send_sms_status_change_131()
        if (self.old_status_code is ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR and
                not self.application.is_grab()):
            self.action.send_email_status_change()

    def post(self):
        if self.old_status_code is not ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR:
            self.action.process_documents_resubmission_action()


# 132
class Status132Handler(BaseActionHandler):
    def post(self):
        self.action.process_documents_resubmitted_action()


# 133
class Status133Handler(BaseActionHandler):
    def async_task(self):
        if self.old_status_code not in (ApplicationStatusCodes.APPLICATION_DENIED,
                                        ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                                        ApplicationStatusCodes.PRE_REJECTION):
            self.action.send_email_status_change()

    def post(self):
        self.action.process_customer_may_not_reapply_action()
        if self.old_status_code in ApplicationStatusCodes.reset_lender_counters():
            self.action.revert_lender_counter()


# 134
class Status134Handler(BaseActionHandler):
    def async_task(self):
        if self.old_status_code is ApplicationStatusCodes.SCRAPED_DATA_VERIFIED:
            self.action.send_email_status_change()

    def post(self):
        if self.old_status_code in ApplicationStatusCodes.reset_lender_counters():
            self.action.revert_lender_counter()
        if self.old_status_code in (ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
                                    ApplicationStatusCodes.FORM_SUBMISSION_ABANDONED,
                                    ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED,
                                    ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
                                    ApplicationStatusCodes.OFFER_EXPIRED,
                                    ApplicationStatusCodes.LEGAL_AGREEMENT_EXPIRED):
            self.action.process_customer_may_not_reapply_action()


# 135
class Status135Handler(BaseActionHandler):
    def async_task(self):
        if not self.application.partner:
            self.action.update_status_apps_flyer()

    def post(self):
        self.action.process_application_reapply_status_action()
        if self.old_status_code in ApplicationStatusCodes.reset_lender_counters():
            self.action.revert_lender_counter()
        if self.application.partner and self.application.partner.name in LIST_PARTNER:
            self.action.callback_to_partner()


# 136
class Status136Handler(BaseActionHandler):
    def async_task(self):
        self.action.send_email_status_change()
        self.action.update_status_apps_flyer()

    def post(self):
        if not self.application.is_julo_one():
            # Because julo one has its own post handler, and it has different
            # behaviour for reapply, just we give if condition here.
            self.action.process_customer_may_reapply_action()


# 137
class Status137Handler(BaseActionHandler):
    def async_task(self):
        self.action.update_status_apps_flyer()
        if self.old_status_code not in (ApplicationStatusCodes.FORM_SUBMITTED,
                                        ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
                                        ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
                                        ApplicationStatusCodes.PRE_REJECTION,
                                        ApplicationStatusCodes.PENDING_PARTNER_APPROVAL,
                                        ApplicationStatusCodes.APPLICATION_DENIED,
                                        ApplicationStatusCodes.DOCUMENTS_VERIFIED,
                                        ApplicationStatusCodes.FORM_PARTIAL):
            self.action.send_email_status_change()

    def post(self):
        self.action.process_customer_may_reapply_action()
        if self.old_status_code in ApplicationStatusCodes.reset_lender_counters():
            self.action.revert_lender_counter()
        if self.old_status_code is ApplicationStatusCodes.FORM_PARTIAL:
            self.action.trigger_anaserver_short_form_timeout()


# 138
class Status138Handler(BaseActionHandler):
    def async_task(self):
        self.action.send_email_status_change()


# 139
class Status139Handler(BaseActionHandler):
    def async_task(self):
        self.action.update_status_apps_flyer()
        if self.old_status_code is ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING:
            self.action.send_email_status_change()

    def post(self):
        self.action.process_customer_may_reapply_action()
        if self.old_status_code in ApplicationStatusCodes.reset_lender_counters():
            self.action.revert_lender_counter()


# 140
class Status140Handler(BaseActionHandler):
    def pre(self):
        if self.application.offer_set.exists():
            self.action.show_offers()

    def post(self):
        self.action.send_lead_data_to_primo()

    def after(self):
        self.action.delete_lead_data_from_primo()


# 141
class Status141Handler(BaseActionHandler):
    def pre(self):
        if self.application.partner_name == PARTNER_PEDE:
            self.action.process_validate_bank()
        if self.application.status is ApplicationStatusCodes.OFFER_MADE_TO_CUSTOMER:
            self.action.accept_selected_offer()
        elif self.application.status in HighScoreFullByPassConstant.application_status():
            if (
                self.application.product_line and
                self.application.product_line.product_line_code in ProductLineCodes.grabfood()
            ):
                self.action.grab_food_generate_loan_and_payment()
            else:
                if self.application.partner and self.application.partner.name in LIST_PARTNER:
                    # LIST_PARTNER offers created in 163 status change
                    # self.action.accept_partner_offer()
                    pass
                else:
                    self.action.accept_default_offer()

        if (
            self.application.product_line and
            self.application.product_line.product_line_code not in ProductLineCodes.grab() + ProductLineCodes.loc()
        ):
            if self.application.partner and self.application.partner.name in LIST_PARTNER:
                pass
            else:
                self.action.assign_loan_to_virtual_account()

    def post(self):
        self.action.send_lead_data_to_primo()
        self.action.assign_lender_in_loan()

        #always call this method last to prevent race condition
        if self.application.partner_name != PARTNER_PEDE:
            self.action.ac_bypass_experiment()


    def after(self):
        self.action.delete_lead_data_from_primo()


# 142
class Status142Handler(BaseActionHandler):
    def async_task(self):
        self.action.send_email_status_change()

    def post(self):
        self.action.process_customer_may_reapply_action()


# 143
class Status143Handler(BaseActionHandler):
    def async_task(self):
        self.action.send_email_status_change()
        self.action.update_status_apps_flyer()

    def post(self):
        self.action.process_customer_may_reapply_action()

# 150
class Status150Handler(BaseActionHandler):
    def post(self):
        if self.application.partner_name == PARTNER_PEDE:
            self.action.validate_bank_name_in_160()


#150 only implemented on cashloan workflow
class CashLoanNode150Handler(BaseActionHandler):
    def post(self):
        self.action.validate_bank_name_in_160()

    def async_task(self):
        from juloserver.julo_privyid.services import get_privy_feature
        if get_privy_feature():
            self.action.register_or_update_customer_to_privy()

# 160
class Status160Handler(BaseActionHandler):
    def pre(self):
        product_line_internal = ProductLineCodes.mtl() + ProductLineCodes.stl()
        if (self.application.status in NameBankValidationStatus.APPLICATION_STATUSES
            and self.application.product_line_code in product_line_internal):
            self.action.process_validate_bank()
        self.action.show_legal_document()

    def async_task(self):
        from juloserver.julo.workflows2.tasks import signature_method_history_task
        from juloserver.julo_privyid.services.common import get_privy_feature
        from juloserver.julo_privyid.services.privy_integrate import (
            is_privy_custumer_valid,
        )
        from juloserver.julo_privyid.tasks import send_reminder_sign_sphp
        feature_setting = MobileFeatureSetting.objects.filter(
            feature_name='digisign_mode', is_active=True).last()

        if get_privy_feature():
            signature_method_history_task.delay(self.application.id, 'Privy')
            send_reminder_sign_sphp.delay(self.action.application.id)
        if not feature_setting and not get_privy_feature() and not is_privy_custumer_valid(self.application):
            self.action.create_sphp()
            return None
        if feature_setting and self.application.is_digisign_version() and not (self.application.partner_name == PARTNER_PEDE):
            self.action.send_registration_and_document_digisign()
        else:
            if not get_privy_feature() and not is_privy_custumer_valid(self.application):
                self.action.create_sphp()


    def post(self):
        self.action.send_lead_data_to_primo()
        self.action.ac_bypass_experiment()

    def after(self):
        self.action.delete_lead_data_from_primo()


# 161
class Status161Handler(BaseActionHandler):
    def async_task(self):
        self.action.send_email_status_change()

    def post(self):
        self.action.process_customer_may_reapply_action()


# 162
class Status162Handler(BaseActionHandler):
    def pre(self):
        self.action.process_sphp_resubmission_action()

    def async_task(self):
        self.action.send_sms_status_change()


# 163
class Status163Handler(BaseActionHandler):
    def pre(self):
        if self.application.status is ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL:
            if self.application.partner and self.application.partner.name == PARTNER_LAKU6:
                self.action.create_loan_payment_partner()
                self.action.assign_loan_to_virtual_account()

            self.action.process_sphp_signed_action()

        elif self.application.status is ApplicationStatusCodes.LEGAL_AGREEMENT_RESUBMISSION_REQUESTED:
            self.action.process_sphp_resubmitted_action()

        self.action.update_status_apps_flyer()

    def async_task(self):
        feature_setting = MobileFeatureSetting.objects.filter(
            feature_name='digisign_mode', is_active=True).last()
        if not feature_setting:
            return None

        is_new_app_version = True
        if self.application.app_version:
            is_new_app_version = semver.match(self.application.app_version, ">=3.0.0")

        if is_new_app_version:
            self.action.download_sphp_from_digisign()


#163 cash loan workflow only
class CashLoanWorkflowNode163Handler(BaseActionHandler):
    def pre(self):
        if self.application.loan and not self.application.loan.lender:
            self.action.assign_lender_to_loan()


# 164
class Status164Handler(BaseActionHandler):
    def post(self):
        if self.application.partner and self.application.partner.name == PARTNER_LAKU6:
            self.action.process_partner_bank_validate()
        else:
            self.action.process_name_bank_validate()

# 165
class Status165Handler(BaseActionHandler):
    def async_task(self):
        self.action.create_lender_sphp()
        self.action.lender_auto_approval()
        self.action.lender_auto_expired()

    def after(self):
        self.action.assign_lender_signature()


# 170
class Status170Handler(BaseActionHandler):
    def pre(self):
        if self.application.partner and self.application.partner.name == PARTNER_LAKU6:
            pass
        else:
            self.action.disbursement_validate_bank()

    def post(self):
        if self.old_status_code is not ApplicationStatusCodes.KYC_IN_PROGRESS:
            if self.application.partner and self.application.partner.name == PARTNER_LAKU6:
                self.action.process_partner_disbursement()
            else:
                self.action.process_disbursement()


# 171
class Status171Handler(BaseActionHandler):
    def async_task(self):
        self.action.send_email_status_change()
        self.action.update_status_apps_flyer()

    def post(self):
        if self.old_status_code is ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL:
            self.action.process_customer_may_reapply_action()
        if self.old_status_code in ApplicationStatusCodes.reset_lender_counters():
            self.action.revert_lender_counter()


# 172
class Status172Handler(BaseActionHandler):
    def post(self):
        self.action.send_lead_data_to_primo()
        if self.application.partner and self.application.partner.name == PARTNER_PEDE:
            self.action.send_sms_status_change_172()
            self.action.create_loan_payment_partner()
            self.action.assign_loan_to_virtual_account()
        self.action.ac_bypass_experiment()

    def after(self):
        self.action.delete_lead_data_from_primo()


# 174
class Status174Handler(BaseActionHandler):
    def post(self):
        if self.old_status_code in ApplicationStatusCodes.reset_lender_counters():
            self.action.revert_lender_counter()


# 175
class Status175Handler(BaseActionHandler):
    def async_task(self):
        self.action.automate_sending_reconfirmation_email_175()

    def post(self):
        # shadow score CDE
        from juloserver.application_flow.services2.cde import CDEClient
        CDEClient(self.application).hit_cde()


# Comment out because it will double commited amount
# 177
# class Status177Handler(BaseActionHandler):
#     def post(self):
#         self.action.trigger_update_lender_balance_current_for_disbursement()


# 178
class PartnerNode178Handler(BaseActionHandler):
    def pre(self):
        self.action.bulk_disbursement_assignment()


# 180
class Status180Handler(BaseActionHandler):
    def async_task(self):
        if not self.application.partner:
            self.action.update_status_apps_flyer()
        # block notify to ICare client
        if self.application.customer.can_notify:
            self.action.send_email_status_change()

        if self.application.partner and self.application.partner.name == PARTNER_PEDE:
            self.action.score_partner_notify()
        # temporary revert until gmail scrapping issue fixed
        #self.action.set_google_calender()

    def post(self):
        self.action.process_customer_may_not_reapply_action()
        self.action.start_loan()
        if self.application.partner_name == PartnerConstant.TOKOPEDIA_PARTNER:
            self.action.eligibe_check_tokopedia_october_campaign()
            self.action.check_tokopedia_eligibe_january_campaign()
        # send push notification for play store rating
        self.action.send_pn_playstore_rating()

        # check customer is used any promo code
        if self.application.referral_code is not None:
            self.action.check_customer_promo()


# 181
class Status181Handler(BaseActionHandler):
    def async_task(self):
        self.action.send_back_to_170_for_disbursement_auto_retry()

# 189
class Status189Handler(BaseActionHandler):
    def async_task(self):
        if not self.application.partner:
            self.action.update_status_apps_flyer()

#for application < v3
class SubmittingFormWorkflowNode110Handler(BaseActionHandler):
    def post(self):
        self.action.switch_to_product_default_workflow()

    def async_task(self):
        self.action.create_application_original()
        self.action.update_status_apps_flyer()

# for app v3
class SubmittingFormWorkflowNode105Handler(BaseActionHandler):
    def async_task(self):
        self.action.update_status_apps_flyer()


class LineOfCreditWorkflowNode120Handler(BaseActionHandler):
    def pre(self):
        self.action.create_and_assign_loc()


class LineOfCreditWorkflowNode190Handler(BaseActionHandler):
    def pre(self):
        self.action.activate_loc()
        self.action.process_customer_may_reapply_action()

    def async_task(self):
        self.action.update_status_apps_flyer()


class Status1001Handler(BaseActionHandler):
    def async_task(self):
        self.action.update_status_apps_flyer()


class Status1201Handler(BaseActionHandler):
    def async_task(self):
        if self.old_status_code == ApplicationStatusCodes.FORM_CREATED_PARTNER:
            self.action.send_pn_reminder_six_hour_later()

    def post(self):
        if self.old_status_code == ApplicationStatusCodes.FORM_CREATED_PARTNER:
            application_obj = Application.objects.filter(pk = self.action.application.id)[0]
            CreditScore.objects.create(application=application_obj,score="b-")
            # self.action.trigger_anaserver_status105()

class PartnerNode105Handler(BaseActionHandler):
    def async_task(self):
        self.action.create_application_original()
        #self.action.update_status_apps_flyer()


class PartnerNode148Handler(BaseActionHandler):
    def async_task(self):
        self.action.create_application_original()
        #self.action.update_status_apps_flyer()

    def post(self):
        self.action.create_icare_axiata_offer()
        self.action.accept_default_offer()
        self.action.assign_loan_to_virtual_account()


#145 digisign failed
class Status145Handler(BaseActionHandler):
    def post(self):
        self.action.assign_to_legal_expired()


#147 digisign face failed
class Status147Handler(BaseActionHandler):
    def after(self):
        self.action.run_index_faces()


# 1311 for face recognition after resubmit
class Status1311Handler(BaseActionHandler):
    def async_task(self):
        self.action.run_index_faces()


class JuloOne105Handler(BaseActionHandler):
    def post(self):
        self.action.trigger_anaserver_status105()


class JuloOne122Handler(BaseActionHandler):
    def post(self):
        if not is_experiment_application(self.application.id, 'ExperimentUwOverhaul'):
            self.action.process_experiment_iti_low_threshold()
