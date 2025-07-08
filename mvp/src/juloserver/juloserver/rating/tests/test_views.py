from unittest import mock
from juloserver.julo.tests.factories import AuthUserFactory, CustomerFactory
from juloserver.rating.tests.factories import RatingFactory
from rest_framework.test import APIClient, APITestCase
from juloserver.rating.models import RatingFormTypeEnum, RatingSourceEnum
from juloserver.loan.models import Loan


class TestRatingDeciderAPI(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)

    @mock.patch('juloserver.rating.views.requests.get')
    def test_failed(self, mock_response):
        mock_response.return_value = mock.Mock(
            status_code=401,
            json=lambda: {
                "data": None,
                "error": "Problem with user request. Please make sure the information you send is correct.",
                "success": False,
            },
        )
        response = self.client.get('/api/rating/v1/show-popup')
        self.assertEqual(
            response.json(),
            {'success': False, 'data': None, 'errors': ['Terjadi kesalahan pada server.']},
        )

    @mock.patch('juloserver.rating.views.requests.get')
    def test_true(self, mock_response):
        mock_response.return_value = mock.Mock(
            status_code=200,
            json=lambda: {
                "data": {"show_popup": True, "rating_form": 2},
                "error": None,
                "success": True,
            },
        )
        response = self.client.get('/api/rating/v1/show-popup')
        self.assertEqual(response.json()['data'], {'show_rating_popup': True})

    @mock.patch('juloserver.rating.views.requests.get')
    def test_false(self, mock_response):
        mock_response.return_value = mock.Mock(
            status_code=200,
            json=lambda: {
                "data": {"show_popup": False, "rating_form": 2},
                "error": None,
                "success": True,
            },
        )
        response = self.client.get('/api/rating/v1/show-popup')
        self.assertEqual(response.json()['data'], {'show_rating_popup': False})


class TestSubmitRatingAPI(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)

    @mock.patch('juloserver.rating.views.submit_rating_task')
    def test_submit_success(
        self,
        mock_submit_rating_task,
    ):
        data = {
            'rating': 2,
            'description': 'tidak mantap',
        }
        response = self.client.post('/api/rating/v1/submit', data, format='json')
        self.assertTrue(response.json()['success'])
        self.assertEqual(response.status_code, 200)

    @mock.patch('juloserver.rating.views.submit_rating_task.apply_async')
    def test_submit_internal_server_error(
        self,
        mock_submit_rating_task,
    ):
        mock_submit_rating_task.side_effect = Exception('Submit rating tidak berhasil')
        data = {
            'rating': 5,
            'description': 'tidak mantap',
        }
        response = self.client.post('/api/rating/v1/submit', data, format='json')
        self.assertFalse(response.json()['success'])
        self.assertEqual(response.status_code, 500)

    def test_insufficient_data(self):
        data = {
            'description': 'tidak mantap',
            'source': RatingSourceEnum.loan_success.value,
            'form_type': RatingFormTypeEnum.type_b.value,
        }
        response = self.client.post('/api/rating/v1/submit', data, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['success'])

    def test_wrong_data(self):
        data = {
            'rating': 0,
            'description': 'tidak mantap',
            'source': RatingSourceEnum.loan_success.value,
            'form_type': RatingFormTypeEnum.type_b.value,
        }
        response = self.client.post('/api/rating/v1/submit', data, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['success'])


class TestSuccessLoanRatingAPI(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)

    @mock.patch('juloserver.rating.views.requests.get')
    def test_failed(self, mock_response):
        mock_response.return_value = mock.Mock(
            status_code=401,
            json=lambda: {
                "data": None,
                "error": "Problem with user request. Please make sure the information you send is correct.",
                "success": False,
            },
        )
        response = self.client.get('/api/rating/v1/loan/show-success-popup')
        self.assertEqual(
            response.json(),
            {'success': False, 'data': None, 'errors': ['Terjadi kesalahan pada server.']},
        )

    @mock.patch('juloserver.rating.views.requests.get')
    def test_true(self, mock_response):
        mock_response.return_value = mock.Mock(
            status_code=200,
            json=lambda: {
                "data": {
                    "show_popup": True,
                    "rating_form": 1,
                    "source": 2,
                },
                "error": None,
                "success": True,
            },
        )
        response = self.client.get('/api/rating/v1/loan/show-success-popup')
        expected_response = {"show_popup": True, "rating_form": 1, 'source': 2}
        self.assertEqual(response.json()['data'], expected_response)

    @mock.patch('juloserver.rating.views.requests.get')
    def test_true_without_source(self, mock_response):
        mock_response.return_value = mock.Mock(
            status_code=200,
            json=lambda: {
                "data": {
                    "show_popup": True,
                    "rating_form": 2,
                },
                "error": None,
                "success": True,
            },
        )
        response = self.client.get('/api/rating/v1/loan/show-success-popup')
        expected_response = {
            "show_popup": True,
            "rating_form": 2,
        }
        self.assertEqual(response.json()['data'], expected_response)

    @mock.patch('juloserver.rating.views.requests.get')
    def test_false(self, mock_response):
        mock_response.return_value = mock.Mock(
            status_code=200,
            json=lambda: {
                "data": {
                    "show_popup": False,
                    "rating_form": 1,
                    "source": 2,
                },
                "error": None,
                "success": True,
            },
        )
        response = self.client.get('/api/rating/v1/loan/show-success-popup')
        expected_response = {
            "show_popup": False,
            "rating_form": 1,
            "source": 2,
        }
        self.assertEqual(response.json()['data'], expected_response)

    @mock.patch('juloserver.rating.views.requests.get')
    def test_false_without_response(self, mock_response):
        mock_response.return_value = mock.Mock(
            status_code=200,
            json=lambda: {
                "data": {
                    "show_popup": False,
                    "rating_form": 1,
                },
                "error": None,
                "success": True,
            },
        )
        response = self.client.get('/api/rating/v1/loan/show-success-popup')
        expected_response = {
            "show_popup": False,
            "rating_form": 1,
        }
        self.assertEqual(response.json()['data'], expected_response)
