from builtins import object
class PromoCampaign(object):
    def __init__(self, email_strategy=None,
                 pn_strategy=None,
                 sms_strategy=None):
        self._email_strategy = email_strategy
        self._pn_strategy = pn_strategy
        self._sms_strategy = sms_strategy

    def send_email(self):
        self._email_strategy.send()

    def send_pn(self):
        self._pn_strategy.send()

    def send_sms(self):
        self._sms_strategy.send()
