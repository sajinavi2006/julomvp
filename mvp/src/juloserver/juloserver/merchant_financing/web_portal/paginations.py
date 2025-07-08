from rest_framework import pagination
from rest_framework.response import Response
from juloserver.merchant_financing.web_app.constants import WebAppErrorMessage


class WebPortalPagination(pagination.PageNumberPagination):
    page_size = 50
    page_query_param = 'page'
    page_size_query_param = 'limit'
    invalid_page_message = WebAppErrorMessage.PAGE_NOT_FOUND

    def get_paginated_response(self, data):
        return Response({
            'data': data,
            'meta': {
                'last_page': self.page.paginator.num_pages,
                'total': self.page.paginator.count,
            }
        })
