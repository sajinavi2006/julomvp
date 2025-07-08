from builtins import object
from ..clients import get_julo_advanceai_client

class AdvanceAiService(object):

    def run_blacklist_check(self, application):
        advance_ai_client = get_julo_advanceai_client()
        response = advance_ai_client.blacklist_check(
            application.ktp, application.fullname, application.mobile_phone_1, application.id)

        return response

    def run_id_check(self, application):
        advance_ai_client = get_julo_advanceai_client()
        response = advance_ai_client.id_check(application.ktp, application.fullname)

        return response
