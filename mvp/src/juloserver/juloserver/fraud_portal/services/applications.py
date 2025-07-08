from typing import List, Dict, Any, Optional, Union
from hashlib import md5

from django.db.models import Q
from django.db import connection

from juloserver.antifraud.services.pii_vault import detokenize_pii_antifraud_data
from juloserver.fraud_portal.models.enums import Filter
from juloserver.fraud_portal.models.constants import DEFAULT_PAGE_SIZE
from juloserver.fraud_portal.utils import (
    is_valid_application_id,
    is_valid_customer_id,
    is_valid_email,
    is_valid_phone,
    is_1xx_status,
    is_2xx_status,
    is_3xx_status,
    is_4xx_status,
)
from juloserver.julo.models import (
    Application,
    ApplicationQuerySet,
)
from juloserver.pii_vault.constants import PiiSource


def get_applications_qs(
    filters: dict,
) -> List[Dict[str, Any]]:
    queries = get_application_query_from_filters(filters)

    applications = get_application_by_status_filter(filters[Filter.status])
    applications = get_application_sort(applications, filters[Filter.sort_by])
    applications = applications.select_related('account')
    applications = applications.filter(queries)

    return applications


def get_applications_raw_qs(
    page_number: int,
    filters: dict,
) -> Union[List[Dict[str, Any]], int]:
    """
    Retrieves a paginated list of applications based on raw SQL queries.

    Args:
    - page_number (int): The page number for pagination.
    - filters (dict): A dictionary containing filtering criteria such as sorting and product line.

    Returns:
    - Tuple[List[Dict[str, Any]], int]: A list of applications and the total count of applications.
    """
    # Extract sorting and filtering options from filters
    order_by = filters[Filter.sort_by]
    product_line_code = filters[Filter.product_line]

    # Define pagination parameters
    items_per_page = DEFAULT_PAGE_SIZE  # Number of items per page
    offset = (page_number - 1) * items_per_page  # Calculate offset for SQL query

    # Construct raw SQL queries (for fetching applications and total count)
    base_query, params_base_query, count_query, params_count_query = construct_raw_query(
        items_per_page, offset, order_by, product_line_code
    )

    with connection.cursor() as cursor:
        cursor.execute(base_query, params_base_query)
        result = cursor.fetchall()  # Fetch all rows from the query result

        # Extract application IDs from the result
        application_ids = [row[0] for row in result]

        # Fetch applications from the ORM using the retrieved ids
        applications = Application.objects.filter(id__in=application_ids).select_related('account')

        # Keeping the order according to application_ids
        applications = sorted(applications, key=lambda app: application_ids.index(app.id))

        # Execute the count query to get the total number of applications
        cursor.execute(count_query, params_count_query)
        total_count = cursor.fetchone()[0]  # Retrieve the total count from the result

    return applications, total_count


def get_cache_key_applications(
    page_number: int,
    filters: dict,
) -> str:
    """
    Generates a cache key for storing and retrieving application lists.

    Args:
    - page_number (int): The current page number for pagination.
    - filters (dict): A dictionary containing filter parameters.

    Returns:
    - str: A unique cache key based on the page number and filters.
    """
    filters_hash = md5(str(filters).encode()).hexdigest()
    cache_key = 'homepage_application_list::{0}_{1}'.format(
        page_number,
        filters_hash
    )
    return cache_key


def construct_raw_query(
    items_per_page: int,
    offset: int,
    order_by: Optional[str] = None,
    product_line_code: Optional[str] = None,
) -> Union[str, List[str]]:
    """
    Constructs raw SQL queries for fetching application ids and counting total applications.

    Args:
    - items_per_page (int): Number of records to fetch per page.
    - offset (int): Number of records to skip before starting to fetch.
    - order_by (Optional[str]): Column name for sorting, prefixed with "-" for descending order.
    - product_line_code (Optional[str]): Product line filter.

    Returns:
    - Tuple containing:
      - base_query (str): SQL query to fetch application ids.
      - params_base_query (List[str]): Parameters for base query.
      - count_query (str): SQL query to count total applications.
      - params_count_query (List[str]): Parameters for count query.
    """
    base_query = "SELECT application_id FROM ops.application"
    count_query = "SELECT COUNT(*) FROM ops.application"

    params_base_query = []
    params_count_query = []
    filters = []

    if not order_by:
        order_by = '-cdate'

    order_mapping = {
        'id': 'application_id',
        '-id': '-application_id',
        'application_status_id': 'application_status_code',
        '-application_status_id': '-application_status_code'
    }
    order_by = order_mapping.get(order_by, order_by)

    # Add filter if product_line_code is provided
    if product_line_code:
        filters.append("product_line_code = %s")
        params_base_query.append(product_line_code)
        params_count_query.append(product_line_code)

    # Append WHERE clause if filters exist
    if filters:
        base_query += " WHERE " + " AND ".join(filters)
        count_query += " WHERE " + " AND ".join(filters)

    # Apply ORDER BY clause
    order_column = order_by.lstrip("-")  # Remove "-" to get column name
    order_direction = "DESC" if order_by.startswith("-") else "ASC"
    base_query += " ORDER BY {} {}".format(order_column, order_direction)

    # Apply LIMIT and OFFSET for pagination
    base_query += " LIMIT %s OFFSET %s"
    params_base_query.extend([items_per_page, offset])

    return base_query, params_base_query, count_query, params_count_query


def detokenize_and_convert_to_dict(pageData):
    applications = [app for app in pageData]
    detokenized_applications = detokenize_pii_antifraud_data(PiiSource.APPLICATION, applications)
    return [
        {
            'cdate': app.cdate,
            'id': app.id,
            'fullname': app.fullname,
            'email': app.email,
            'mobile_phone_1': app.mobile_phone_1,
            'application_status_id': app.application_status.status_code
            if app.application_status
            else None,
            'product_line_id': app.product_line.product_line_code if app.product_line else None,
            'account_id': app.account_id,
            'customer_id': app.customer_id,
            'account__status_id': app.account.status.status_code if app.account else None,
        }
        for app in detokenized_applications
    ]


def get_application_query_from_filters(
    filters: dict,
) -> Q:
    query = Q()

    for key, value in filters.items():
        if key == Filter.search and value:
            search_query = get_search_query(value)
            query &= search_query
        elif key == Filter.status and is_1xx_status(value):
            query &= Q(application_status_id=value)
        elif key == Filter.product_line and value:
            query &= Q(product_line_id=value)

    return query


def get_search_query(
    search_value: str,
) -> Q:
    query = Q()
    search_values = search_value.split(', ')

    for value in search_values:
        if is_valid_application_id(value):
            query |= Q(id=value)
        elif is_valid_phone(value):
            query |= Q(mobile_phone_1__iexact=value)
        elif is_valid_email(value):
            query |= Q(email__iexact=value)
        elif is_valid_customer_id(value):
            query |= Q(customer_id=value)
        else:
            query |= Q(fullname__iexact=value)

    return query


def get_application_by_status_filter(
    status_value: str,
) -> List[Application]:
    if is_1xx_status(status_value):
        return Application.objects.filter(application_status_id=status_value)
    elif is_2xx_status(status_value):
        return Application.objects.filter(account__loan_loan_status_id=status_value)
    elif is_3xx_status(status_value):
        return Application.objects.filter(account__account_payment_status_id=status_value)
    elif is_4xx_status(status_value):
        return Application.objects.filter(account__status_id=status_value)

    return Application.objects.all()


def get_application_sort(
    queryset: ApplicationQuerySet,
    sort_by: str,
) -> ApplicationQuerySet:
    if not sort_by:
        sort_by = '-cdate'
    queryset = queryset.order_by(sort_by)

    return queryset
