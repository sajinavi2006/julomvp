# Register your models here.
import logging

from django.contrib import admin
from future import standard_library

from juloserver.julo.admin import JuloModelAdmin

from .models import CityLookup, DistrictLookup, ProvinceLookup, SubDistrictLookup

standard_library.install_aliases()

# Register your models here.

logger = logging.getLogger(__name__)


class ProvinceLookupAdmin(JuloModelAdmin):
    pass


class CityLookupAdmin(JuloModelAdmin):
    pass


class DistrictLookupAdmin(JuloModelAdmin):
    pass


class SubDistrictLookupAdmin(JuloModelAdmin):
    pass


admin.site.register(ProvinceLookup, ProvinceLookupAdmin)
admin.site.register(CityLookup, CityLookupAdmin)
admin.site.register(DistrictLookup, DistrictLookupAdmin)
admin.site.register(SubDistrictLookup, SubDistrictLookupAdmin)
