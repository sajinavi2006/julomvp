from .strategy import *
from .base import *


class RamadanPromoCampaign(PromoCampaign):
    def __init__(self):
        super(RamadanPromoCampaign, self).__init__(
            ramadan_email, ramadan_pn, ramadan_sms)

ramadan_email = RamadanEmailStrategy()
ramadan_sms = RamadanSmsStrategy()
ramadan_pn = RamadanPnStrategy()
RamadanPromo = RamadanPromoCampaign()
