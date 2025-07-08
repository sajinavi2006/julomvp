import csv
from typing import Dict, Any

from rest_framework.authentication import SessionAuthentication
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ViewSet

from juloserver.fraud_portal.models.enums import (
    Filter,
)
from juloserver.fraud_portal.serializers.homepage_serializer import (
    ApplicationListResponse,
    StatusCodeListResponse,
    ProductLineListResponse,
    SuspiciousCustomerListRequest,
    SuspiciousCustomerListResponse,
    SuspiciousAppListRequest,
    SuspiciousAppListResponse,
    BlacklistedGeohash5ListRequest,
    BlacklistedGeohash5ListResponse,
    BlacklistedPostalCodeListRequest,
    BlacklistedPostalCodeListResponse,
    BlacklistedCustomerListRequest,
    BlacklistedCustomerListResponse,
    BlacklistedEmailDomainListRequest,
    BlacklistedEmailDomainListResponse,
    BlacklistedCompanyListRequest,
    BlacklistedCompanyListResponse,
    SuspiciousAsnListRequest,
    SuspiciousAsnListResponse,
)
from juloserver.fraud_portal.serializers.paginator import (
    CustomPaginator,
    CustomPaginatorApp,
)
from juloserver.fraud_portal.services.applications import (
    get_applications_qs,
    get_applications_raw_qs,
    get_cache_key_applications,
    detokenize_and_convert_to_dict,
)
from juloserver.fraud_portal.services.blacklisted_companies import (
    get_blacklisted_companies_qs,
    get_search_blacklisted_companies_results,
    add_bulk_blacklisted_companies,
    add_blacklisted_company,
    delete_blacklisted_company,
)
from juloserver.fraud_portal.services.blacklisted_customers import (
    get_blacklisted_customers_qs,
    get_search_blacklisted_customers_results,
    add_bulk_blacklisted_customers,
    add_blacklisted_customer,
    delete_blacklisted_customer,
    detokenize_blacklisted_customer_from_ids,
)
from juloserver.fraud_portal.services.blacklisted_email_domains import (
    get_blacklisted_email_domains_qs,
    get_search_blacklisted_email_domains_results,
    add_bulk_blacklisted_email_domains,
    add_blacklisted_email_domain,
    delete_blacklisted_email_domain,
)
from juloserver.fraud_portal.services.blacklisted_geohash5s import (
    get_blacklisted_geohash5s_qs,
    get_search_blacklisted_geohash5s_results,
    add_bulk_blacklisted_geohash5s,
    add_blacklisted_geohash5,
    delete_blacklisted_geohash5,
)
from juloserver.fraud_portal.services.blacklisted_postal_codes import (
    get_blacklisted_postal_codes_qs,
    get_search_blacklisted_postal_codes_results,
    add_bulk_blacklisted_postal_codes,
    add_blacklisted_postal_code,
    delete_blacklisted_postal_code,
)
from juloserver.fraud_portal.services.product_lines import (
    get_product_lines_qs,
)
from juloserver.fraud_portal.services.status_codes import (
    get_status_codes_qs,
)
from juloserver.fraud_portal.services.suspicious_apps import (
    get_suspicious_apps_qs,
    get_search_suspicious_apps_results,
    add_suspicious_app,
    add_bulk_suspicious_apps,
    delete_suspicious_app,
)
from juloserver.fraud_portal.services.suspicious_asns import (
    get_suspicious_asns_qs,
    get_search_suspicious_asns_results,
    add_bulk_suspicious_asns,
    add_suspicious_asn,
    delete_suspicious_asn,
)
from juloserver.fraud_portal.services.suspicious_customers import (
    get_suspicious_customers_qs,
    get_search_results,
    delete_suspicious_customer,
    add_bulk_suspicious_customers,
    add_suspicious_customer,
)
from juloserver.fraud_portal.utils import cvs_rows_exceeded_limit, is_csv_extension
from juloserver.julocore.cache_client import get_redis_cache
from juloserver.new_crm.utils import crm_permission
from juloserver.portal.object.dashboard.constants import JuloUserRoles
from juloserver.standardized_api_response.utils import (
    success_response,
    general_error_response,
    not_found_response,
)

cache = get_redis_cache()
CACHE_DURATION = 60 * 5  # 5 Minutes


class ApplicationList(ListAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [
        crm_permission(
            [
                JuloUserRoles.ADMIN_FULL,
                JuloUserRoles.FRAUD_OPS,
                JuloUserRoles.PRODUCT_MANAGER,
            ]
        )
    ]
    pagination_class = CustomPaginator
    serializer_class = ApplicationListResponse

    def get_queryset(self):
        filters = self._get_filters(self.request)
        return get_applications_qs(filters)

    def list(self, request, *args, **kwargs):
        page_number_query = request.GET.get('page', 1)
        if page_number_query == '':
            return not_found_response("Invalid page.")
        page_number = int(page_number_query)
        filters = self._get_filters(self.request)
        cache_key = get_cache_key_applications(page_number, filters)
        cache_data = cache.get(cache_key)
        if cache_data:
            return success_response(cache_data)

        if filters[Filter.status] \
                or filters[Filter.search] \
                or filters[Filter.sort_by] in ['account__status_id', '-account__status_id']:
            queryset = self.filter_queryset(self.get_queryset())
            page = self.paginate_queryset(queryset)
            if page is not None:
                detokenize_data = detokenize_and_convert_to_dict(page)
                serializer = self.get_serializer(detokenize_data, many=True)
                response = self.get_paginated_response(serializer.data)
            else:
                serializer = self.get_serializer(page, many=True)
                response = Response(serializer.data)
        else:
            items_data, total_count = get_applications_raw_qs(page_number, filters)
            detokenize_data = detokenize_and_convert_to_dict(items_data)
            serializer = self.get_serializer(detokenize_data, many=True)
            paginator = CustomPaginatorApp(request, total_count, serializer.data)
            response = paginator.get_paginated_response()

        cache.set(cache_key, response.data, CACHE_DURATION)
        return success_response(response.data)

    def _get_filters(
        self,
        request,
    ) -> Dict[Filter, Any]:

        filters = {
            Filter.search: request.GET.get(
                Filter.search.value, request.data.get(Filter.search.value, "")
            ),
            Filter.status: request.GET.get(Filter.status.value, ""),
            Filter.product_line: request.GET.get(Filter.product_line.value, ""),
            Filter.sort_by: self.serializer_class.get_original_field_name(
                request.GET.get(Filter.sort_by.value, ""),
            ),
        }

        return filters


class StatusCodeList(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [
        crm_permission(
            [
                JuloUserRoles.ADMIN_FULL,
                JuloUserRoles.FRAUD_OPS,
                JuloUserRoles.PRODUCT_MANAGER,
            ]
        )
    ]
    serializer_class = StatusCodeListResponse

    def get(self, request, *args, **kwargs):
        status_codes = get_status_codes_qs()
        if not status_codes:
            return success_response([])

        return success_response(self.serializer_class(status_codes, many=True).data)


class ProductLineList(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [
        crm_permission(
            [
                JuloUserRoles.ADMIN_FULL,
                JuloUserRoles.FRAUD_OPS,
                JuloUserRoles.PRODUCT_MANAGER,
            ]
        )
    ]
    serializer_class = ProductLineListResponse

    def get(self, request, *args, **kwargs):
        product_lines = get_product_lines_qs()
        if not product_lines:
            return success_response([])

        return success_response(self.serializer_class(product_lines, many=True).data)


class SuspiciousCustomerList(ViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [
        crm_permission(
            [
                JuloUserRoles.ADMIN_FULL,
                JuloUserRoles.FRAUD_OPS,
                JuloUserRoles.PRODUCT_MANAGER,
            ]
        )
    ]
    serializer_class = SuspiciousCustomerListResponse

    def get(self, request):
        search_query = request.GET.get('search', '')
        if search_query:
            suspicious_customers = get_search_results(search_query)
        else:
            suspicious_customers = get_suspicious_customers_qs()
        if not suspicious_customers:
            return success_response([])
        paginator = CustomPaginator()
        paginate_qs = paginator.paginate_queryset(suspicious_customers, request)
        serializer = self.serializer_class(paginate_qs, many=True)
        return success_response(paginator.get_paginated_data(serializer.data))

    def post(self, request):
        serializer = SuspiciousCustomerListRequest(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        user_id = request.user.id
        result = add_bulk_suspicious_customers(serializer.data, user_id)
        return success_response(self.serializer_class(result, many=True).data)

    def delete(self, request):
        pk = int(request.GET.get('id'))
        type = int(request.GET.get('type'))
        result = delete_suspicious_customer(pk, type)
        if not result:
            return not_found_response("suspicious_customer_id not found")
        return success_response("success")

    def upload(self, request):
        csv_file = request.FILES.get('file')
        if not csv_file:
            return general_error_response('No file uploaded')
        if not is_csv_extension(csv_file):
            return general_error_response('Invalid file format, please upload a CSV file')

        decoded_file = csv_file.read().decode('utf-8').splitlines()
        if cvs_rows_exceeded_limit(decoded_file):
            return general_error_response("Amount of data exceeds the maximum 200")

        user_id = request.user.id
        csv_reader = csv.DictReader(decoded_file)
        for row in csv_reader:
            serializer = SuspiciousCustomerListRequest(data=row)
            serializer.is_valid(raise_exception=True)
            add_suspicious_customer(serializer.data, user_id)

        return success_response("File uploaded successfully")


class SuspiciousAppsList(ViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [
        crm_permission(
            [
                JuloUserRoles.ADMIN_FULL,
                JuloUserRoles.FRAUD_OPS,
                JuloUserRoles.PRODUCT_MANAGER,
            ]
        )
    ]
    serializer_class = SuspiciousAppListResponse
    pagination_class = CustomPaginator

    def get(self, request):
        search_query = request.GET.get('package_name', '')
        if search_query:
            suspicious_apps = get_search_suspicious_apps_results(search_query)
        else:
            suspicious_apps = get_suspicious_apps_qs()
        if not suspicious_apps:
            return success_response([])
        paginator = CustomPaginator()
        paginate_qs = paginator.paginate_queryset(suspicious_apps, request)
        serializer = self.serializer_class(paginate_qs, many=True)
        return success_response(paginator.get_paginated_data(serializer.data))

    def post(self, request):
        serializer = SuspiciousAppListRequest(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        user_id = request.user.id
        result = add_bulk_suspicious_apps(serializer.data, user_id)
        return success_response(self.serializer_class(result, many=True).data)

    def delete(self, request, pk):
        result = delete_suspicious_app(pk)
        if not result:
            return not_found_response("suspicious_fraud_app_id not found")
        return success_response("success")

    def upload(self, request):
        csv_file = request.FILES.get('file')
        if not csv_file:
            return general_error_response('No file uploaded')
        if not is_csv_extension(csv_file):
            return general_error_response('Invalid file format, please upload a CSV file')

        decoded_file = csv_file.read().decode('utf-8').splitlines()
        if cvs_rows_exceeded_limit(decoded_file):
            return general_error_response("Amount of data exceeds the maximum 200")

        user_id = request.user.id
        csv_reader = csv.DictReader(decoded_file)
        for row in csv_reader:
            serializer = SuspiciousAppListRequest(data=row)
            serializer.is_valid(raise_exception=True)
            add_suspicious_app(serializer.data, user_id)

        return success_response("File uploaded successfully")


class BlacklistedGeohash5List(ViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [
        crm_permission(
            [
                JuloUserRoles.ADMIN_FULL,
                JuloUserRoles.FRAUD_OPS,
                JuloUserRoles.PRODUCT_MANAGER,
            ]
        )
    ]
    serializer_class = BlacklistedGeohash5ListResponse
    pagination_class = CustomPaginator

    def get(self, request, *args, **kwargs):
        search_query = request.GET.get('geohash5', '')
        if search_query:
            blacklisted_geohash5s = get_search_blacklisted_geohash5s_results(search_query)
        else:
            blacklisted_geohash5s = get_blacklisted_geohash5s_qs()
        if not blacklisted_geohash5s:
            return success_response([])
        paginator = CustomPaginator()
        paginate_qs = paginator.paginate_queryset(blacklisted_geohash5s, request)
        serializer = self.serializer_class(paginate_qs, many=True)
        return success_response(paginator.get_paginated_data(serializer.data))

    def post(self, request):
        serializer = BlacklistedGeohash5ListRequest(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        user_id = request.user.id
        result = add_bulk_blacklisted_geohash5s(serializer.data, user_id)
        return success_response(self.serializer_class(result, many=True).data)

    def delete(self, request, pk):
        result = delete_blacklisted_geohash5(pk)
        if not result:
            return not_found_response("fraud_blacklisted_geohash5_id not found")
        return success_response("success")

    def upload(self, request):
        csv_file = request.FILES.get('file')
        if not csv_file:
            return general_error_response('No file uploaded')
        if not is_csv_extension(csv_file):
            return general_error_response('Invalid file format, please upload a CSV file')

        decoded_file = csv_file.read().decode('utf-8').splitlines()
        if cvs_rows_exceeded_limit(decoded_file):
            return general_error_response("Amount of data exceeds the maximum 200")

        user_id = request.user.id
        csv_reader = csv.DictReader(decoded_file)
        for row in csv_reader:
            serializer = BlacklistedGeohash5ListRequest(data=row)
            serializer.is_valid(raise_exception=True)
            add_blacklisted_geohash5(serializer.data, user_id)

        return success_response("File uploaded successfully")


class BlacklistedPostalCodeList(ViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [
        crm_permission(
            [
                JuloUserRoles.ADMIN_FULL,
                JuloUserRoles.FRAUD_OPS,
                JuloUserRoles.PRODUCT_MANAGER,
            ]
        )
    ]
    serializer_class = BlacklistedPostalCodeListResponse
    pagination_class = CustomPaginator

    def get(self, request, *args, **kwargs):
        search_query = request.GET.get('postal_code', '')
        if search_query:
            blacklisted_postal_codes = get_search_blacklisted_postal_codes_results(search_query)
        else:
            blacklisted_postal_codes = get_blacklisted_postal_codes_qs()
        if not blacklisted_postal_codes:
            return success_response([])
        paginator = CustomPaginator()
        paginate_qs = paginator.paginate_queryset(blacklisted_postal_codes, request)
        serializer = self.serializer_class(paginate_qs, many=True)
        return success_response(paginator.get_paginated_data(serializer.data))

    def post(self, request):
        serializer = BlacklistedPostalCodeListRequest(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        user_id = request.user.id
        result = add_bulk_blacklisted_postal_codes(serializer.data, user_id)
        return success_response(self.serializer_class(result, many=True).data)

    def delete(self, request, pk):
        result = delete_blacklisted_postal_code(pk)
        if not result:
            return not_found_response("fraud_blacklisted_postal_code_id not found")
        return success_response("success")

    def upload(self, request):
        csv_file = request.FILES.get('file')
        if not csv_file:
            return general_error_response('No file uploaded')
        if not is_csv_extension(csv_file):
            return general_error_response('Invalid file format, please upload a CSV file')

        decoded_file = csv_file.read().decode('utf-8').splitlines()
        if cvs_rows_exceeded_limit(decoded_file):
            return general_error_response("Amount of data exceeds the maximum 200")

        user_id = request.user.id
        csv_reader = csv.DictReader(decoded_file)
        for row in csv_reader:
            serializer = BlacklistedPostalCodeListRequest(data=row)
            serializer.is_valid(raise_exception=True)
            add_blacklisted_postal_code(serializer.data, user_id)

        return success_response("File uploaded successfully")


class BlacklistedCustomerList(ViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [
        crm_permission(
            [
                JuloUserRoles.ADMIN_FULL,
                JuloUserRoles.FRAUD_OPS,
                JuloUserRoles.PRODUCT_MANAGER,
            ]
        )
    ]
    serializer_class = BlacklistedCustomerListResponse
    pagination_class = CustomPaginator

    def get_queryset(self, request):
        search_query = request.GET.get('fullname', '')
        if search_query:
            return get_search_blacklisted_customers_results(search_query, is_detokenize=False)

        return get_blacklisted_customers_qs(is_detokenize=False)

    def get(self, request, *args, **kwargs):
        blacklisted_customers = self.get_queryset(request).only('id')
        if not blacklisted_customers.exists():
            return success_response([])

        paginator = CustomPaginator()
        paginate_qs = paginator.paginate_queryset(blacklisted_customers, request)
        serializer = self.serializer_class(
            detokenize_blacklisted_customer_from_ids([p.id for p in paginate_qs]), many=True
        )
        return success_response(paginator.get_paginated_data(serializer.data))

    def post(self, request):
        serializer = BlacklistedCustomerListRequest(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        user_id = request.user.id
        result = add_bulk_blacklisted_customers(serializer.data, user_id)
        return success_response(self.serializer_class(result, many=True).data)

    def delete(self, request, pk):
        result = delete_blacklisted_customer(pk)
        if not result:
            return not_found_response("blacklist_customer_id not found")
        return success_response("success")

    def upload(self, request):
        csv_file = request.FILES.get('file')
        if not csv_file:
            return general_error_response('No file uploaded')
        if not is_csv_extension(csv_file):
            return general_error_response('Invalid file format, please upload a CSV file')

        decoded_file = csv_file.read().decode('utf-8').splitlines()
        if cvs_rows_exceeded_limit(decoded_file):
            return general_error_response("Amount of data exceeds the maximum 200")

        user_id = request.user.id
        csv_reader = csv.DictReader(decoded_file)
        for row in csv_reader:
            serializer = BlacklistedCustomerListRequest(data=row)
            serializer.is_valid(raise_exception=True)
            add_blacklisted_customer(serializer.data, user_id)

        return success_response("File uploaded successfully")


class BlacklistedEmailDomainList(ViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [
        crm_permission(
            [
                JuloUserRoles.ADMIN_FULL,
                JuloUserRoles.FRAUD_OPS,
                JuloUserRoles.PRODUCT_MANAGER,
            ]
        )
    ]
    serializer_class = BlacklistedEmailDomainListResponse
    pagination_class = CustomPaginator

    def get(self, request, *args, **kwargs):
        search_query = request.GET.get('email_domain', '')
        if search_query:
            blacklisted_email_domains = get_search_blacklisted_email_domains_results(search_query)
        else:
            blacklisted_email_domains = get_blacklisted_email_domains_qs()
        if not blacklisted_email_domains:
            return success_response([])
        paginator = CustomPaginator()
        paginate_qs = paginator.paginate_queryset(blacklisted_email_domains, request)
        serializer = self.serializer_class(paginate_qs, many=True)
        return success_response(paginator.get_paginated_data(serializer.data))

    def post(self, request):
        serializer = BlacklistedEmailDomainListRequest(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        user_id = request.user.id
        result = add_bulk_blacklisted_email_domains(serializer.data, user_id)
        return success_response(self.serializer_class(result, many=True).data)

    def delete(self, request, pk):
        result = delete_blacklisted_email_domain(pk)
        if not result:
            return not_found_response("suspicious_domain_id not found")
        return success_response("success")

    def upload(self, request):
        csv_file = request.FILES.get('file')
        if not csv_file:
            return general_error_response('No file uploaded')
        if not is_csv_extension(csv_file):
            return general_error_response('Invalid file format, please upload a CSV file')

        decoded_file = csv_file.read().decode('utf-8').splitlines()
        if cvs_rows_exceeded_limit(decoded_file):
            return general_error_response("Amount of data exceeds the maximum 200")

        user_id = request.user.id
        csv_reader = csv.DictReader(decoded_file)
        for row in csv_reader:
            serializer = BlacklistedEmailDomainListRequest(data=row)
            serializer.is_valid(raise_exception=True)
            add_blacklisted_email_domain(serializer.data, user_id)

        return success_response("File uploaded successfully")


class BlacklistedCompanyList(ViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [
        crm_permission(
            [
                JuloUserRoles.ADMIN_FULL,
                JuloUserRoles.FRAUD_OPS,
                JuloUserRoles.PRODUCT_MANAGER,
            ]
        )
    ]
    serializer_class = BlacklistedCompanyListResponse
    pagination_class = CustomPaginator

    def get(self, request, *args, **kwargs):
        search_query = request.GET.get('company_name', '')
        if search_query:
            blacklisted_companies = get_search_blacklisted_companies_results(search_query)
        else:
            blacklisted_companies = get_blacklisted_companies_qs()
        if not blacklisted_companies:
            return success_response([])
        paginator = CustomPaginator()
        paginate_qs = paginator.paginate_queryset(blacklisted_companies, request)
        serializer = self.serializer_class(paginate_qs, many=True)
        return success_response(paginator.get_paginated_data(serializer.data))

    def post(self, request):
        serializer = BlacklistedCompanyListRequest(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        user_id = request.user.id
        result = add_bulk_blacklisted_companies(serializer.data, user_id)
        return success_response(self.serializer_class(result, many=True).data)

    def delete(self, request, pk):
        result = delete_blacklisted_company(pk)
        if not result:
            return not_found_response("fraud_blacklisted_company_id not found")
        return success_response("success")

    def upload(self, request):
        csv_file = request.FILES.get('file')
        if not csv_file:
            return general_error_response('No file uploaded')
        if not is_csv_extension(csv_file):
            return general_error_response('Invalid file format, please upload a CSV file')

        decoded_file = csv_file.read().decode('utf-8').splitlines()
        if cvs_rows_exceeded_limit(decoded_file):
            return general_error_response("Amount of data exceeds the maximum 200")

        user_id = request.user.id
        csv_reader = csv.DictReader(decoded_file)
        for row in csv_reader:
            serializer = BlacklistedCompanyListRequest(data=row)
            serializer.is_valid(raise_exception=True)
            add_blacklisted_company(serializer.data, user_id)

        return success_response("File uploaded successfully")


class SuspiciousAsnList(ViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [
        crm_permission(
            [
                JuloUserRoles.ADMIN_FULL,
                JuloUserRoles.FRAUD_OPS,
                JuloUserRoles.PRODUCT_MANAGER,
            ]
        )
    ]
    serializer_class = SuspiciousAsnListResponse
    pagination_class = CustomPaginator

    def get(self, request, *args, **kwargs):
        search_query = request.GET.get('name', '')
        if search_query:
            suspicious_asns = get_search_suspicious_asns_results(search_query)
        else:
            suspicious_asns = get_suspicious_asns_qs()
        if not suspicious_asns:
            return success_response([])
        paginator = CustomPaginator()
        paginate_qs = paginator.paginate_queryset(suspicious_asns, request)
        serializer = self.serializer_class(paginate_qs, many=True)
        return success_response(paginator.get_paginated_data(serializer.data))

    def post(self, request):
        serializer = SuspiciousAsnListRequest(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        user_id = request.user.id
        result = add_bulk_suspicious_asns(serializer.data, user_id)
        return success_response(self.serializer_class(result, many=True).data)

    def delete(self, request):
        id = request.GET.get('id', '')
        name = request.GET.get('name', '')
        result = delete_suspicious_asn(int(id), name)
        if not result:
            return not_found_response("fraud_high_risk_asn_id or name not found")
        return success_response("success")

    def upload(self, request):
        csv_file = request.FILES.get('file')
        if not csv_file:
            return general_error_response('No file uploaded')
        if not is_csv_extension(csv_file):
            return general_error_response('Invalid file format, please upload a CSV file')

        decoded_file = csv_file.read().decode('utf-8').splitlines()
        if cvs_rows_exceeded_limit(decoded_file):
            return general_error_response("Amount of data exceeds the maximum 200")

        user_id = request.user.id
        csv_reader = csv.DictReader(decoded_file)
        for row in csv_reader:
            serializer = SuspiciousAsnListRequest(data=row)
            serializer.is_valid(raise_exception=True)
            add_suspicious_asn(serializer.data, user_id)

        return success_response("File uploaded successfully")
