import json

from cacheops import cached
from rest_framework.authentication import SessionAuthentication
from rest_framework.views import APIView

from juloserver.apiv1.dropdown import (
    BirthplaceDropDown,
    CompanyDropDown,
    JobDropDownV2,
)
from juloserver.apiv3.views import AddressLookupView
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixinV2
from juloserver.standardized_api_response.utils import success_response


class DropdownApi(StandardizedExceptionHandlerMixinV2, APIView):
    """
    This class is used to get the dropdown data for the CRM.
    This class is supporting the DropDownBase Class in `apiv1.dropdown`
    """
    authentication_classes = [SessionAuthentication]
    http_method_names = ['get']
    dropdown_map = {
        'job': JobDropDownV2,
        'companies': CompanyDropDown,
        'birthplace': BirthplaceDropDown,
    }
    default_product_line_code = 10

    @cached(timeout=60 * 60 * 24, extra='juloserver.new_crm_views.dropdown_views.DropdownApi')
    def _get_data(self, dropdown_type, filter_levels=None, search=None):
        dropdown_class = self.dropdown_map.get(dropdown_type)
        if not dropdown_class:
            return {}

        dropdown = dropdown_class()
        json_str = dropdown._get_data(self.default_product_line_code)
        raw_data = json.loads(json_str)['data']

        parsed_data = {}
        for row in raw_data:
            levels = row.split(',')
            current_level = parsed_data
            for level in levels:
                if level not in current_level:
                    current_level[level] = {}
                current_level = current_level[level]

        if isinstance(filter_levels, list):
            for key in filter_levels:
                parsed_data = parsed_data.get(key, {})

        filter_data = list(parsed_data.keys())
        if search:
            filter_data = [value for value in filter_data if search.lower() in value.lower()]
        return filter_data

    def get(self, request, dropdown_type, *args, **kwargs):
        level = request.GET.get('level')
        search = request.GET.get('search')
        levels = level.split(',') if level else []
        dropdown_data = self._get_data(dropdown_type, levels, search)
        return success_response(dropdown_data)


class DropdownAddressApi(AddressLookupView):
    """
    Address Dropdown API this is similar to `api/v3/address/*` endpoints but this is only for CRM.
    """
    authentication_classes = [SessionAuthentication]
    http_method_names = ['get']

    def _get_request_data(self):
        return self.request.GET

    def get(self, request, *args, **kwargs):
        if 'zipcode' in request.GET:
            return self.get_info(request)
        elif 'district' in request.GET:
            return self.get_subdistricts(request)
        elif 'city' in request.GET:
            return self.get_districts(request)
        elif 'province' in request.GET:
            return self.get_cities(request)

        return self.get_provinces(request)
