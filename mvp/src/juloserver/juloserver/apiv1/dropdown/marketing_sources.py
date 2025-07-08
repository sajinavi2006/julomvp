from __future__ import unicode_literals

from .base import DropDownBase


class MarketingSourceDropDown(DropDownBase):
    dropdown = "marketing_sources"
    version = 2
    file_name = "marketing_sources.json"

    # Please Always Upgrade Version if there is changes on data
    DATA = [
        "Teman / saudara",
        "Facebook",
        "Artikel online",
        "Flyer",
        "Tokopedia",
        "Iklan online",
        "Google Play Store",
        "Doku",
        "Grab",
    ]
