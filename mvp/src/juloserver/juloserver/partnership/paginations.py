from django.conf import settings

from rest_framework import pagination
from rest_framework.response import Response
from rest_framework.utils.urls import remove_query_param, replace_query_param


class CustomPagination(pagination.PageNumberPagination):
    page_size = 50
    page_query_param = 'page'
    page_size_query_param = 'limit'
    invalid_page_message = 'Page tidak valid'

    def get_paginated_response(self, data):
        return Response({
            'success': True,
            'next': self.get_next_link(),
            'previous': self.get_previous_link(),
            'data': data,
            'errors': []
        })

    def get_next_link(self):
        if not self.page.has_next():
            return None
        url = settings.BASE_URL + self.request.get_full_path()
        page_number = self.page.next_page_number()
        return replace_query_param(url, self.page_query_param, page_number)

    def get_previous_link(self):
        if not self.page.has_previous():
            return None
        url = settings.BASE_URL + self.request.get_full_path()
        page_number = self.page.previous_page_number()
        if page_number == 1:
            return remove_query_param(url, self.page_query_param)
        return replace_query_param(url, self.page_query_param, page_number)
