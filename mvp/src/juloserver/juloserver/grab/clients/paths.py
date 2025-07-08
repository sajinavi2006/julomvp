from builtins import str
from builtins import object
import uuid

from django.conf import settings


class GrabPaths(object):
    # grab paths
    LINK_GRAB_ACCOUNT = "/lendingPartner/external/v1/authenticate"
    LOAN_OFFER = "/lendingPartner/external/v1/loanOffer"
    REPAYMENT_PLAN = "/lendingPartner/external/v1/repaymentPlans"
    APPLICATION_CREATION = "/lendingPartner/external/v1/applicationData"
    LEGACY_APPLICATION_CREATION = ("/lendingPartner/external/v1/applicationData/lendingPartner/external/v1"
                                   "/applicationData")
    APPLICATION_UPDATION = "/lendingPartner/external/v1/applicationStatus"
    LOAN_CREATION = "/lendingPartner/external/v1/auth"
    PRE_DISBURSAL_CHECK = "/lendingPartner/external/v1/preDisbursalCheck"
    DISBURSAL_CREATION = "/lendingPartner/external/v1/capture"
    CANCEL_LOAN = "/lendingPartner/external/v1/cancel"
    PUSH_NOTIFICATION = "/lendingPartner/external/v1/notify"
    DEDUCTION_API = "/lendingPartner/external/v1/julo-deduction"
    LOAN_SYNC_API = "/lendingPartner/external/v1/loan-sync-api"

    # LINK_GRAB_ACCOUNT = "/v1/authenticate"
    # LOAN_OFFER = "/v1/loanOffer"
    # REPAYMENT_PLAN = "/v1/repaymentPlans"
    # APPLICATION_CREATION = "/v1/applicationData"
    # LOAN_CREATION = "/v1/auth"
    # PRE_DISBURSAL_CHECK = "/v1/preDisbursalCheck"
    # DISBURSAL_CREATION = "/v1/capture"

    @staticmethod
    def build_url(path, http_method, additional_params=""):
        msg_id = GrabPaths.create_msg_id()

        url = settings.GRAB_API_URL + path + (msg_id + additional_params if http_method == "GET" else "")
        uri_path = path + (msg_id + additional_params if http_method == "GET" else "")

        return url, uri_path

    @staticmethod
    def create_msg_id():
        return "?msg_id=" + str(uuid.uuid4().hex)
