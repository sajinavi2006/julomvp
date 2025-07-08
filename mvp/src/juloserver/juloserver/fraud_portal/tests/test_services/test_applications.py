from django.test import TestCase
from hashlib import md5

from juloserver.fraud_portal.models.enums import Filter
from juloserver.fraud_portal.services.applications import (
    get_cache_key_applications,
    construct_raw_query,
)

class TestApplicationsService(TestCase):

    def test_get_cache_key_applications(self):
        filters = {Filter.sort_by: 'cdate', Filter.product_line: '1'}
        page_number = 1
        expected_hash = md5(str(filters).encode()).hexdigest()
        expected_cache_key = f'homepage_application_list::{page_number}_{expected_hash}'
        
        cache_key = get_cache_key_applications(page_number, filters)
        self.assertEqual(cache_key, expected_cache_key)
    
    def test_get_cache_key_applications_with_empty_filters(self):
        filters = {}
        page_number = 5
        expected_hash = md5(str(filters).encode()).hexdigest()
        expected_cache_key = f'homepage_application_list::{page_number}_{expected_hash}'
        
        cache_key = get_cache_key_applications(page_number, filters)
        self.assertEqual(cache_key, expected_cache_key)
    
    def test_get_cache_key_applications_with_different_page_numbers(self):
        filters = {Filter.sort_by: 'cdate', Filter.product_line: '1'}
        cache_key_page_1 = get_cache_key_applications(1, filters)
        cache_key_page_2 = get_cache_key_applications(2, filters)

        self.assertNotEqual(cache_key_page_1, cache_key_page_2)

    def test_get_cache_key_applications_with_different_filters(self):
        filters_1 = {Filter.sort_by: 'cdate', Filter.product_line: '1'}
        filters_2 = {Filter.search: '1234', Filter.status: '100'}
        page_number = 10
        cache_key_filters_1 = get_cache_key_applications(page_number, filters_1)
        cache_key_filters_2 = get_cache_key_applications(page_number, filters_2)

        self.assertNotEqual(cache_key_filters_1, cache_key_filters_2)

    def test_construct_raw_query_basic(self):
        items_per_page = 10
        offset = 0
        query, params, count_query, count_params = construct_raw_query(items_per_page, offset)
        self.assertEqual(query, "SELECT application_id FROM ops.application ORDER BY cdate DESC LIMIT %s OFFSET %s")
        self.assertEqual(params, [10, 0])
        self.assertEqual(count_query, "SELECT COUNT(*) FROM ops.application")
        self.assertEqual(count_params, [])

    def test_construct_raw_query_with_product_line(self):
        items_per_page = 10
        offset = 0
        product_line_code = '1'
        query, params, count_query, count_params = construct_raw_query(items_per_page, offset, product_line_code=product_line_code)
        self.assertEqual(query, "SELECT application_id FROM ops.application WHERE product_line_code = %s ORDER BY cdate DESC LIMIT %s OFFSET %s")
        self.assertEqual(params, ['1', 10, 0])
        self.assertEqual(count_query, "SELECT COUNT(*) FROM ops.application WHERE product_line_code = %s")
        self.assertEqual(count_params, ['1'])

    def test_construct_raw_query_with_with_order_by_cdate_asc(self):
        items_per_page = 10
        offset = 0
        order_by = 'cdate'
        query, params, count_query, count_params = construct_raw_query(items_per_page, offset, order_by=order_by)
        self.assertEqual(query, "SELECT application_id FROM ops.application ORDER BY cdate ASC LIMIT %s OFFSET %s")
        self.assertEqual(params, [10, 0])
        self.assertEqual(count_query, "SELECT COUNT(*) FROM ops.application")
        self.assertEqual(count_params, [])

    def test_construct_raw_query_with_with_order_by_cdate_desc(self):
        items_per_page = 10
        offset = 0
        order_by = '-cdate'
        query, params, count_query, count_params = construct_raw_query(items_per_page, offset, order_by=order_by)
        self.assertEqual(query, "SELECT application_id FROM ops.application ORDER BY cdate DESC LIMIT %s OFFSET %s")
        self.assertEqual(params, [10, 0])
        self.assertEqual(count_query, "SELECT COUNT(*) FROM ops.application")
        self.assertEqual(count_params, [])

    def test_construct_raw_query_with_with_order_by_application_id_asc(self):
        items_per_page = 10
        offset = 0
        order_by = 'application_id'
        query, params, count_query, count_params = construct_raw_query(items_per_page, offset, order_by=order_by)
        self.assertEqual(query, "SELECT application_id FROM ops.application ORDER BY application_id ASC LIMIT %s OFFSET %s")
        self.assertEqual(params, [10, 0])
        self.assertEqual(count_query, "SELECT COUNT(*) FROM ops.application")
        self.assertEqual(count_params, [])

    def test_construct_raw_query_with_with_order_by_application_id_desc(self):
        items_per_page = 10
        offset = 0
        order_by = '-application_id'
        query, params, count_query, count_params = construct_raw_query(items_per_page, offset, order_by=order_by)
        self.assertEqual(query, "SELECT application_id FROM ops.application ORDER BY application_id DESC LIMIT %s OFFSET %s")
        self.assertEqual(params, [10, 0])
        self.assertEqual(count_query, "SELECT COUNT(*) FROM ops.application")
        self.assertEqual(count_params, [])
    
    def test_construct_raw_query_with_with_order_by_application_status_asc(self):
        items_per_page = 10
        offset = 0
        order_by = 'application_status_id'
        query, params, count_query, count_params = construct_raw_query(items_per_page, offset, order_by=order_by)
        self.assertEqual(query, "SELECT application_id FROM ops.application ORDER BY application_status_code ASC LIMIT %s OFFSET %s")
        self.assertEqual(params, [10, 0])
        self.assertEqual(count_query, "SELECT COUNT(*) FROM ops.application")
        self.assertEqual(count_params, [])

    def test_construct_raw_query_with_with_order_by_application_status_desc(self):
        items_per_page = 10
        offset = 0
        order_by = '-application_status_id'
        query, params, count_query, count_params = construct_raw_query(items_per_page, offset, order_by=order_by)
        self.assertEqual(query, "SELECT application_id FROM ops.application ORDER BY application_status_code DESC LIMIT %s OFFSET %s")
        self.assertEqual(params, [10, 0])
        self.assertEqual(count_query, "SELECT COUNT(*) FROM ops.application")
        self.assertEqual(count_params, [])

    def test_construct_raw_query_with_with_order_by_email_asc(self):
        items_per_page = 10
        offset = 0
        order_by = 'email'
        query, params, count_query, count_params = construct_raw_query(items_per_page, offset, order_by=order_by)
        self.assertEqual(query, "SELECT application_id FROM ops.application ORDER BY email ASC LIMIT %s OFFSET %s")
        self.assertEqual(params, [10, 0])
        self.assertEqual(count_query, "SELECT COUNT(*) FROM ops.application")
        self.assertEqual(count_params, [])

    def test_construct_raw_query_with_with_order_by_email_desc(self):
        items_per_page = 10
        offset = 0
        order_by = '-email'
        query, params, count_query, count_params = construct_raw_query(items_per_page, offset, order_by=order_by)
        self.assertEqual(query, "SELECT application_id FROM ops.application ORDER BY email DESC LIMIT %s OFFSET %s")
        self.assertEqual(params, [10, 0])
        self.assertEqual(count_query, "SELECT COUNT(*) FROM ops.application")
        self.assertEqual(count_params, [])

    def test_construct_raw_query_with_all_filters(self):
        items_per_page = 10
        offset = 5
        order_by = '-cdate'
        product_line_code = '1'
        query, params, count_query, count_params = construct_raw_query(
            items_per_page, offset, order_by=order_by, product_line_code=product_line_code
        )
        self.assertEqual(query, "SELECT application_id FROM ops.application WHERE product_line_code = %s ORDER BY cdate DESC LIMIT %s OFFSET %s")
        self.assertEqual(params, ['1', 10, 5])
        self.assertEqual(count_query, "SELECT COUNT(*) FROM ops.application WHERE product_line_code = %s")
        self.assertEqual(count_params, ['1'])
