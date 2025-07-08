from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from juloserver.fraud_portal.models.constants import (
    DEFAULT_PAGE_SIZE,
    MAXIMUM_PAGE_SIZE,
)


class CustomPaginator(PageNumberPagination):
    page_query_param = "page"
    page_size = DEFAULT_PAGE_SIZE
    page_size_query_param = "page_size"
    max_page_size = MAXIMUM_PAGE_SIZE

    def get_paginated_response(self, data):
        return Response(
            {
                'count': self.page.paginator.count,
                'pages': self.page.paginator.num_pages,
                'next': self.page.next_page_number() if self.page.has_next() else None,
                'prev': self.page.previous_page_number() if self.page.has_previous() else None,
                'data': data,
            }
        )

    def get_paginated_data(self, data):
        return {
            'count': self.page.paginator.count,
            'pages': self.page.paginator.num_pages,
            'next': self.page.next_page_number() if self.page.has_next() else None,
            'prev': self.page.previous_page_number() if self.page.has_previous() else None,
            'data': data,
        }


class CustomPaginatorApp():
    def __init__(self, request, total_count, data):
        self.request = request
        self.total_count = total_count
        self.data = data
        self.items_per_page = DEFAULT_PAGE_SIZE

    def get_paginated_response(self):
        page_number = int(self.request.GET.get('page', 1))
        total_pages = (self.total_count + self.items_per_page - 1) // self.items_per_page
        next_page = page_number + 1 if page_number < total_pages else None
        prev_page = page_number - 1 if page_number > 1 else None
        return Response({
            'count': self.total_count,
            'pages': total_pages,
            'next': next_page,
            'prev': prev_page,
            'data': self.data,
        })
