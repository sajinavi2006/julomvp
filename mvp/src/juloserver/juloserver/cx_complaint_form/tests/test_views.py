import uuid
from unittest.mock import patch

from rest_framework.test import APIClient, APITestCase

from juloserver.account.constants import AccountConstant
from juloserver.account.tests.factories import AccountFactory
from juloserver.cx_complaint_form.const import SuggestedAnswerConst
from juloserver.cx_complaint_form.models import ComplaintSubmissionLog, SuggestedAnswer
from juloserver.cx_complaint_form.tests.factories import (
    ComplaintSubTopicFactory,
    ComplaintTopicFactory,
)
from juloserver.cx_complaint_form.views.api_v1 import (
    GetSuggestedAnswers,
    SubmitFeedbackSuggestedAnswers,
)
from juloserver.inapp_survey.tests.factories import (
    InAppSurveyQuestionFactory,
    InAppSurveyUserAnswerFactory,
)
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    StatusLookupFactory,
)
from juloserver.standardized_api_response.utils import (
    not_found_response,
)


class TestGetComplaintTopics(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active),
        )
        self.token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)

    def hit_api(self):
        return self.client.get('/api/cx-complaint/v1/topics/')

    def test_no_topics(self):
        response = self.hit_api()
        self.assertIsNotNone(response.json()["data"])
        self.assertEqual(len(response.json()["data"]), 0)

    def test_with_topics(self):
        for i in range(10):
            topic_name = 'Topic {}'.format(i + 1)
            ComplaintTopicFactory(
                topic_name=topic_name,
                image_url='complaint-form/topics/{}.svg'.format(topic_name),
            )

        response = self.hit_api()
        self.assertIsNotNone(response.json()["data"])
        self.assertEqual(len(response.json()["data"]), 10)


class TestGetComplaintSubTopics(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active),
        )
        self.token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)

        self.topic = ComplaintTopicFactory(
            topic_name='Pelaporan Penipuan',
            image_url='complaint-form/topics/pelaporan-penipuan.svg',
        )
        # seed random topic to ensure result is filtered by topic slug
        ComplaintSubTopicFactory()

    def hit_api(self, topic_slug):
        return self.client.get('/api/cx-complaint/v1/topics/{}/sub-topics/'.format(topic_slug))

    def test_no_data(self):
        response = self.hit_api(self.topic.slug)
        self.assertIsNotNone(response.json()["data"])
        self.assertEqual(len(response.json()["data"]), 0)

    def test_without_confirmation_dialog(self):
        ComplaintSubTopicFactory(
            topic=self.topic,
        )

        response = self.hit_api(self.topic.slug)
        self.assertIsNotNone(response.json()["data"])
        self.assertEqual(len(response.json()["data"]), 1)
        self.assertEqual(response.json().get('data')[0].get('confirmation_dialog'), None)

    def test_with_confirmation_dialog(self):
        ComplaintSubTopicFactory(
            topic=self.topic,
            confirmation_dialog_title='Perhatian',
            confirmation_dialog_banner='complaint-form/subtopics/pelaporan-penipuan.jpg',
            confirmation_dialog_content='Silahkan lampirkan bukti penipuan atau percobaan penipuan.',
            confirmation_dialog_info_text='Akan di respon 1x24 jam',
            confirmation_dialog_button_text='Buka Aplikasi Email',
        )

        response = self.hit_api(self.topic.slug)
        self.assertIsNotNone(response.json()["data"])
        self.assertEqual(len(response.json()["data"]), 1)

        self.assertEqual(
            response.json().get('data')[0].get('confirmation_dialog').get('title'),
            'Perhatian',
        )
        self.assertIn(
            'complaint-form%2Fsubtopics%2Fpelaporan-penipuan.jpg',
            response.json().get('data')[0].get('confirmation_dialog').get('image_url'),
        )
        self.assertEqual(
            response.json().get('data')[0].get('confirmation_dialog').get('content'),
            'Silahkan lampirkan bukti penipuan atau percobaan penipuan.',
        )
        self.assertEqual(
            response.json().get('data')[0].get('confirmation_dialog').get('info'),
            'Akan di respon 1x24 jam',
        )
        self.assertEqual(
            response.json().get('data')[0].get('confirmation_dialog').get('button_text'),
            'Buka Aplikasi Email',
        )

    def test_without_action_value(self):
        ComplaintSubTopicFactory(
            topic=self.topic,
            action_type='email',
        )

        response = self.hit_api(self.topic.slug)
        self.assertIsNotNone(response.json()["data"])
        self.assertEqual(len(response.json()["data"]), 1)
        self.assertEqual(response.json().get('data')[0].get('action_type'), 'email')
        self.assertIsNone(response.json().get('data')[0].get('action_value'))

    def test_with_action_value(self):
        ComplaintSubTopicFactory(
            topic=self.topic,
            action_type='deeplink',
            action_value='juloapp:homepage',
        )

        response = self.hit_api(self.topic.slug)
        self.assertIsNotNone(response.json()["data"])
        self.assertEqual(len(response.json()["data"]), 1)
        self.assertEqual(response.json().get('data')[0].get('action_type'), 'deeplink')
        self.assertEqual(response.json().get('data')[0].get('action_value'), 'juloapp:homepage')

    def test_multiple(self):
        for i in range(5):
            ComplaintSubTopicFactory(
                topic=self.topic,
                title='Sub Topic {}'.format(i + 1),
            )

        response = self.hit_api(self.topic.slug)
        self.assertIsNotNone(response.json()["data"])
        self.assertEqual(len(response.json()["data"]), 5)


class TestSubmitComplaint(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active),
        )
        self.token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)

        self.topic = ComplaintTopicFactory(
            topic_name='Pelaporan Penipuan',
            image_url='complaint-form/topics/pelaporan-penipuan.svg',
        )
        self.subtopic = ComplaintSubTopicFactory(
            topic=self.topic,
            title='Penipuan via Email',
        )

        self.survey_submission_uid = uuid.uuid4()
        InAppSurveyUserAnswerFactory(
            customer_id=self.customer.id,
            submission_uid=self.survey_submission_uid,
            question='Pertanyaan survey pertama',
            answer='Jawaban survey pertama',
        )
        InAppSurveyUserAnswerFactory(
            customer_id=self.customer.id,
            submission_uid=self.survey_submission_uid,
            question='Pertanyaan survey kedua',
            answer='Jawaban survey kedua',
        )
        self.question = InAppSurveyQuestionFactory()
        self.inapp_survey_user_answer = InAppSurveyUserAnswerFactory(
            customer_id=self.customer.id, question=self.question.question
        )

    def hit_api(self, data):
        url = '/api/cx-complaint/v1/submit/'
        return self.client.post(url, data, format='json')

    def test_empty_sub_topic_id(self):
        data = {
            'survey_submission_uid': self.survey_submission_uid,
        }
        response = self.hit_api(data)
        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.json().get('success'))
        self.assertIsNone(response.json().get('data'))

    def test_with_no_answers(self):
        data = {
            'survey_submission_uid': uuid.uuid4(),
            'complaint_sub_topic_id': self.subtopic.id,
        }
        response = self.hit_api(data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json().get('success'))
        self.assertEqual(response.json()['data']['customer_name'], self.customer.fullname)
        self.assertEqual(response.json()['data']['nik'], self.customer.get_nik)
        self.assertEqual(response.json()['data']['survey_answers'], [])

    def test_email_action_type(self):
        data = {
            'survey_submission_uid': self.inapp_survey_user_answer.submission_uid,
            'complaint_sub_topic_id': self.subtopic.id,
        }
        response = self.hit_api(data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json().get('success'))
        self.assertEqual(response.json()['data']['customer_name'], self.customer.fullname)
        self.assertEqual(response.json()['data']['nik'], self.customer.get_nik)
        self.assertEqual(len(response.json()['data']['survey_answers']), 1)

        logs = ComplaintSubmissionLog.objects.filter(
            survey_submission_uid=self.inapp_survey_user_answer.submission_uid,
        )
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs.first().customer_id, self.customer.id)
        self.assertEqual(logs.first().subtopic.id, self.subtopic.id)
        self.assertEqual(logs.first().submission_action_type, 'email')
        self.assertEqual(logs.first().submission_action_value, self.customer.get_email)

    def test_deeplink_action_type(self):
        subtopic = ComplaintSubTopicFactory(
            topic=self.topic,
            title='Penipuan via Email',
            action_type='deeplink',
            action_value='julo:/deeplinkvalue',
        )
        data = {
            'survey_submission_uid': self.inapp_survey_user_answer.submission_uid,
            'complaint_sub_topic_id': subtopic.id,
        }
        response = self.hit_api(data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json().get('success'))
        self.assertEqual(response.json()['data']['customer_name'], self.customer.fullname)
        self.assertEqual(response.json()['data']['nik'], self.customer.get_nik)
        self.assertEqual(len(response.json()['data']['survey_answers']), 1)

        logs = ComplaintSubmissionLog.objects.filter(
            survey_submission_uid=self.inapp_survey_user_answer.submission_uid,
        )
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs.first().customer_id, self.customer.id)
        self.assertEqual(logs.first().subtopic.id, subtopic.id)
        self.assertEqual(logs.first().submission_action_type, 'deeplink')
        self.assertEqual(logs.first().submission_action_value, 'julo:/deeplinkvalue')


class TestSuggestedAnswer(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active),
        )
        self.token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)

    def test_get_suggested_answer_not_found(self):
        """
        Test case for _get_suggested_answer when no matching suggested answer is found.
        This tests the edge case where the method returns None when no SuggestedAnswer
        matches the given subtopic_id and answer_ids.
        """
        view = GetSuggestedAnswers()
        subtopic_id = 999  # Assuming this ID doesn't exist
        answer_ids = "1,2,3"

        result = view._get_suggested_answer(subtopic_id, answer_ids)

        self.assertIsNone(result)

    def test_get_suggested_answer_returns_matching_suggested_answer(self):
        """
        Test that _get_suggested_answer returns the correct SuggestedAnswer object
        when given a valid subtopic_id and answer_ids string.
        """

        topic_id = 1
        subtopic_id = 1
        answer_ids = "1,2,3"
        expected_answer = "This is a suggested answer"
        SuggestedAnswer.objects.create(
            topic_id=topic_id,
            subtopic_id=subtopic_id,
            survey_answer_ids=answer_ids,
            suggested_answer=expected_answer,
        )
        get_suggested_answers = GetSuggestedAnswers()

        result = get_suggested_answers._get_suggested_answer(subtopic_id, answer_ids)

        self.assertIsNotNone(result)
        self.assertEqual(result.suggested_answer, expected_answer)

    def test_prepare_answer_ids_1(self):
        """
        Test that _prepare_answer_ids correctly converts a list of answer IDs to a sorted,
        comma-separated string.
        """
        get_suggested_answers = GetSuggestedAnswers()
        survey_answer_ids = [3, 1, 4, 1, 5, 9, 2, 6, 5, 3, 5]
        result = get_suggested_answers._prepare_answer_ids(survey_answer_ids)
        expected = "1,1,2,3,3,4,5,5,5,6,9"
        self.assertEqual(result, expected)

    def test_prepare_answer_ids_with_empty_list(self):
        """
        Test the _prepare_answer_ids method with an empty list input.
        This tests the edge case of handling an empty list of survey answer IDs.
        """
        get_suggested_answers = GetSuggestedAnswers()
        result = get_suggested_answers._prepare_answer_ids([])
        self.assertEqual(result, '')

    def test__prepare_answer_ids_with_unsorted_list(self):
        """
        Test the _prepare_answer_ids method with an unsorted list of integers.
        This verifies that the method correctly sorts the input list before joining.
        """
        get_suggested_answers = GetSuggestedAnswers()
        result = get_suggested_answers._prepare_answer_ids([3, 1, 4, 2])
        self.assertEqual(result, '1,2,3,4')

    def test_post_exception_handling(self):
        """
        Test the post method's exception handling.
        This test checks if the method correctly handles unexpected exceptions
        by returning a not_found_response with the exception message.
        """

        with patch.object(
            GetSuggestedAnswers, '_prepare_answer_ids', side_effect=Exception('Test exception')
        ):
            data = {
                'survey_answer_ids': [1, 2, 3],
                'complaint_sub_topic_id': 1,
            }

            response = self.client.post(
                "/api/cx-complaint/v1/suggested-answers/", data, format='json'
            )

        self.assertEqual(response.status_code, 404)

    def test_post_missing_parameters(self):
        """
        Test that the post method returns a not_found_response when required parameters are missing.
        This test covers the case where either survey_answer_ids or complaint_sub_topic_id is not provided.
        """
        data = {}

        response = self.client.post("/api/cx-complaint/v1/suggested-answers/", data, format='json')

        self.assertEqual(response.status_code, 404)

    def test_post_missing_required_parameters(self):
        """
        Test the post method with missing required parameters.
        This test checks if the method correctly handles the case when
        survey_answer_ids or complaint_sub_topic_id are not provided.
        """

        # Test with empty data
        data = {}

        response = self.client.post("/api/cx-complaint/v1/suggested-answers/", data, format='json')

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data, not_found_response('Field wajid diisi semua').data)

        # Test with only survey_answer_ids
        data = {'survey_answer_ids': [1, 2, 3]}

        response = self.client.post("/api/cx-complaint/v1/suggested-answers/", data, format='json')

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data, not_found_response('Field wajid diisi semua').data)

        # Test with only complaint_sub_topic_id
        data = {
            'complaint_sub_topic_id': 1,
        }

        response = self.client.post("/api/cx-complaint/v1/suggested-answers/", data, format='json')

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data, not_found_response('Field wajid diisi semua').data)

    def test_post_suggested_answer_not_found(self):
        """
        Test the post method when no suggested answer is found.
        This test checks if the method correctly handles the case when
        the _get_suggested_answer method returns None.
        """

        with patch.object(GetSuggestedAnswers, '_get_suggested_answer', return_value=None):
            data = {
                'survey_answer_ids': [1, 2, 3],
                'complaint_sub_topic_id': 1,
            }

            response = self.client.post(
                "/api/cx-complaint/v1/suggested-answers/", data, format='json'
            )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data, not_found_response('Jawaban tidak ditemukan').data)


class TestSubmitFeedbackSuggestedAnswer(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active),
        )
        self.token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)

    def test_get_cache_key(self):
        """
        Test that _get_cache_key method returns the correct cache key string.

        This test verifies that the _get_cache_key method of SubmitFeedbackSuggestedAnswers
        correctly concatenates the CACHE_PREFIX with the customer_id and suggested_answer_id
        to form the expected cache key string.
        """
        submit_feedback = SubmitFeedbackSuggestedAnswers()
        customer_id = "12345"
        suggested_answer_id = "67890"
        expected_cache_key = (
            SuggestedAnswerConst.CACHE_PREFIX + "_" + customer_id + "_" + suggested_answer_id
        )

        result = submit_feedback._get_cache_key(customer_id, suggested_answer_id)

        assert result == expected_cache_key, (
            "Expected " + expected_cache_key + ", but got " + result
        )

    def test_get_cache_key_with_empty_strings(self):
        """
        Test _get_cache_key method with empty strings as input.
        This tests the edge case of providing empty strings for both customer_id and suggested_answer_id.
        The method should still concatenate these empty strings with the prefix and separators.
        """
        submit_feedback = SubmitFeedbackSuggestedAnswers()
        result = submit_feedback._get_cache_key("", "")
        expected = SuggestedAnswerConst.CACHE_PREFIX + "__"
        self.assertEqual(result, expected)

    def test_get_cache_key_with_special_characters(self):
        """
        Test _get_cache_key method with special characters in the input.
        This tests the edge case of providing strings containing special characters,
        which should be handled without any issues by the string concatenation.
        """
        submit_feedback = SubmitFeedbackSuggestedAnswers()
        result = submit_feedback._get_cache_key("customer@123", "answer#456")
        expected = SuggestedAnswerConst.CACHE_PREFIX + "_customer@123_answer#456"
        self.assertEqual(result, expected)

    @patch('juloserver.cx_complaint_form.views.api_v1.get_redis_client')
    def test_check_and_increment_rate_limit(self, mock_get_redis_client):
        """
        Test that check_and_increment_rate_limit returns False when there are no previous attempts.

        This test verifies that when the Redis cache doesn't have any previous attempts for the given
        customer and suggested answer, the method returns False (indicating not rate limited) and sets
        the initial attempt count to 1 with the correct expiration time.
        """
        mock_get_redis_client.return_value.get.return_value = None
        mock_get_redis_client.return_value.set.return_value = None
        submit_feedback = SubmitFeedbackSuggestedAnswers()
        customer = CustomerFactory()
        suggested_answer_id = "123"

        result = submit_feedback.check_and_increment_rate_limit(
            str(customer.id), suggested_answer_id
        )

        self.assertEqual(result, False)
        mock_get_redis_client.return_value.get.assert_called_once_with(
            submit_feedback._get_cache_key(str(customer.id), "123")
        )
        mock_get_redis_client.return_value.set.assert_called_once_with(
            submit_feedback._get_cache_key(str(customer.id), "123"),
            1,
            SuggestedAnswerConst.RATE_LIMIT_PERIOD,
        )

    def test_submit_feedback(self):
        """
        Test successful submission of feedback for suggested answers.

        This test case verifies that when valid parameters are provided,
        and the give_feedback_suggested_answers method doesn't return a result,
        the post method returns a success response with the message
        'Feedback berhasil disimpan'.
        """

        # Create necessary objects
        ComplaintSubTopicFactory()
        topic = ComplaintTopicFactory()
        subtopic = ComplaintSubTopicFactory(topic=topic)
        survey_answer_ids = [1, 2, 3]
        SuggestedAnswer.objects.create(
            id=1,
            topic=topic,
            subtopic=subtopic,
            survey_answer_ids=survey_answer_ids,
            suggested_answer="test",
        )

        # Prepare request data
        data = {
            'suggested_answer_id': 1,
            'subtopic_id': 1,
            'is_helpful': True,
            'survey_answer_ids': survey_answer_ids,
        }

        # Mock the give_feedback_suggested_answers method to return None
        with patch.object(
            SubmitFeedbackSuggestedAnswers, 'give_feedback_suggested_answers', return_value=None
        ):
            response = self.client.post(
                '/api/cx-complaint/v1/suggested-answers/feedback/', data, format="json"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data'], 'Feedback berhasil disimpan')


class TestWebSuggestedAnswer(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active),
        )
        self.client.credentials(HTTP_X_API_KEY='token ' + SuggestedAnswerConst.API_KEY)

    def test_post_exception_handling(self):
        """
        Test the post method's exception handling.
        This test checks if the method correctly handles unexpected exceptions
        by returning a not_found_response with the exception message.
        """

        with patch.object(
            GetSuggestedAnswers, '_prepare_answer_ids', side_effect=Exception('Test exception')
        ):
            data = {
                'survey_answer_ids': [1, 2, 3],
                'complaint_sub_topic_id': 1,
            }

            response = self.client.post(
                "/api/cx-complaint/web/v1/suggested-answers/", data, format='json'
            )

        self.assertEqual(response.status_code, 404)

    def test_post_missing_parameters(self):
        """
        Test that the post method returns a not_found_response when required parameters are missing.
        This test covers the case where either survey_answer_ids or complaint_sub_topic_id is not provided.
        """
        data = {}

        response = self.client.post(
            "/api/cx-complaint/web/v1/suggested-answers/", data, format='json'
        )

        self.assertEqual(response.status_code, 404)

    def test_post_missing_required_parameters(self):
        """
        Test the post method with missing required parameters.
        This test checks if the method correctly handles the case when
        survey_answer_ids or complaint_sub_topic_id are not provided.
        """

        # Test with empty data
        data = {}

        response = self.client.post(
            "/api/cx-complaint/web/v1/suggested-answers/", data, format='json'
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data, not_found_response('Field wajid diisi semua').data)

        # Test with only survey_answer_ids
        data = {'survey_answer_ids': [1, 2, 3]}

        response = self.client.post(
            "/api/cx-complaint/web/v1/suggested-answers/", data, format='json'
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data, not_found_response('Field wajid diisi semua').data)

        # Test with only complaint_sub_topic_id
        data = {
            'complaint_sub_topic_id': 1,
        }

        response = self.client.post(
            "/api/cx-complaint/web/v1/suggested-answers/", data, format='json'
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data, not_found_response('Field wajid diisi semua').data)

    def test_post_suggested_answer_not_found(self):
        """
        Test the post method when no suggested answer is found.
        This test checks if the method correctly handles the case when
        the _get_suggested_answer method returns None.
        """

        with patch.object(GetSuggestedAnswers, '_get_suggested_answer', return_value=None):
            data = {
                'survey_answer_ids': [1, 2, 3],
                'complaint_sub_topic_id': 1,
            }

            response = self.client.post(
                "/api/cx-complaint/web/v1/suggested-answers/", data, format='json'
            )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data, not_found_response('Jawaban tidak ditemukan').data)
