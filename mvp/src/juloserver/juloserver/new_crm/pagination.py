from django.conf import settings
from rest_framework import pagination
from rest_framework.response import Response
from rest_framework.utils.urls import remove_query_param, replace_query_param
from rest_framework.status import (
    HTTP_200_OK,
    HTTP_404_NOT_FOUND)

class StreamlinedCommunicationSegmentPagination(pagination.PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 10

    def get_paginated_response(self, data):
        page_increment = (self.page.number - 1) * self.max_page_size
        for index, _ in enumerate(data.get('data')):
            data['data'][index]['no'] = index + page_increment + 1

        return Response({
            'success': True,
            'total_count': data.get('total_count'),
            'next': self.get_next_link(),
            'previous': self.get_previous_link(),
            'data': data.get('data'),
            'errors': []
        }, status=HTTP_200_OK if data else HTTP_404_NOT_FOUND)

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
