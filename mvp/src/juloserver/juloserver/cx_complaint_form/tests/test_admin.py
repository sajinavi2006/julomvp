from django.core.urlresolvers import reverse
from django.test import TestCase
from juloserver.julo.tests.factories import (
    AuthUserFactory,
)

from django.core.exceptions import ValidationError
from juloserver.cx_complaint_form.tests.factories import (
    SuggestedAnswerFactory,
    ComplaintSubTopicFactory,
)

from juloserver.inapp_survey.tests.factories import (
    InAppSurveyAnswerFactory,
)
from juloserver.cx_complaint_form.admin import SuggestedAnswerForm
from juloserver.cx_complaint_form.tests.factories import (
    SuggestedAnswerFactory,
)


class TestSuggestedAnswerFormAdmin(TestCase):
    def setUp(self):
        self.auth_user = AuthUserFactory(username='usertest', is_superuser=True, is_staff=True)
        self.client.force_login(self.auth_user)

    def test_get_list(self):
        SuggestedAnswerFactory.create_batch(10)
        url = reverse('admin:cx_complaint_form_suggestedanswer_changelist')
        res = self.client.get(url)

        self.assertEqual(res.status_code, 200)

    def test_get_create(self):
        url = reverse('admin:cx_complaint_form_suggestedanswer_add')
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)

    def test_get_update(self):
        suggested_answer = SuggestedAnswerFactory()
        url = reverse('admin:cx_complaint_form_suggestedanswer_change', args=[suggested_answer.pk])
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)

    def test_post_create(self):
        url = reverse('admin:cx_complaint_form_suggestedanswer_add')
        data = {
            'survey_answer_ids': "['1', '2', '3']",
            'suggested_answer': "<p><strong>Lorem Ipsum</strong>&nbsp;is simply dummy text of the printing and typesetting industry. Lorem Ipsum has been the industry&#39;s standard dummy text ever since the 1500s, when an unknown printer took a galley of type and scrambled it to</p><ul><li><strong>Lorem Ipsum</strong>&nbsp;is simply dummy text of the printing and typesetting industry. Lorem Ipsum has been the industry&#39;s standard dummy text ever since the 1500s, when an unknown printer took a galley of type and scrambled it to</li><li><strong>Lorem Ipsum</strong>&nbsp;is simply dummy text of the printing and typesetting industry. Lorem Ipsum has been the industry&#39;s standard dummy text ever since the 1500s, when an unknown printer took a galley of type and scrambled it to</li><li><strong>Lorem Ipsum</strong>&nbsp;is simply dummy text of the printing and typesetting industry. Lorem Ipsum has been the industry&#39;s standard dummy text ever since the 1500s, when an unknown printer took a galley of type and scrambled it to</li></ul>",
            'topic': 1,
            'subtopic': 1,
        }
        res = self.client.post(url, data)
        self.assertEqual(res.status_code, 200)

    def test_search_functionality(self):
        suggested_answer = SuggestedAnswerFactory()
        url = reverse('admin:cx_complaint_form_suggestedanswer_changelist') + '?q=simply'
        response = self.client.get(url)
        self.assertContains(response, suggested_answer)


class TestSuggestedAnswerForm(TestCase):
    def setUp(self):
        self.subtopic = ComplaintSubTopicFactory(title="Test Subtopic", survey_usage="test_usage")
        self.answer1 = InAppSurveyAnswerFactory(
            answer="Answer 1",
            question__survey_usage="test_usage",
            question__survey_type="complaint-form",
        )
        self.answer2 = InAppSurveyAnswerFactory(
            answer="Answer 2",
            question__survey_usage="test_usage",
            question__survey_type="complaint-form",
        )
        self.answer3 = InAppSurveyAnswerFactory(
            answer="Answer 3",
            question__survey_usage="different_usage",
            question__survey_type="complaint-form",
        )

    def test_form_initialization_with_instance(self):
        instance = SuggestedAnswerFactory(
            suggested_answer="Test answer", survey_answer_ids="1,2", subtopic=self.subtopic
        )
        form = SuggestedAnswerForm(instance=instance)
        self.assertEqual(form.initial['survey_answer_ids'], ['1', '2'])

    def test_clean_survey_answer_ids_valid(self):
        form = SuggestedAnswerForm(
            data={
                'survey_answer_ids': [str(self.answer1.pk), str(self.answer2.pk)],
                'suggested_answer': 'Test answer',
            }
        )

        self.assertTrue(form.is_valid())
        cleaned_ids = form.clean_survey_answer_ids()
        self.assertEqual(cleaned_ids, [str(self.answer1.pk), str(self.answer2.pk)])
        self.assertEqual(form._validated_subtopic_info['id'], self.subtopic.id)

    def test_clean_survey_answer_ids_empty(self):
        form = SuggestedAnswerForm(
            data={'survey_answer_ids': [], 'suggested_answer': 'Test answer'}
        )
        self.assertFalse(form.is_valid())

    def test_clean_survey_answer_ids_mixed_subtopics(self):
        form = SuggestedAnswerForm(
            data={
                'survey_answer_ids': [str(self.answer1.pk), str(self.answer3.pk)],
                'suggested_answer': 'Test answer',
            }
        )

        is_valid = form.is_valid()
        self.assertFalse(is_valid)

        self.assertIn('survey_answer_ids', form.errors)

    def test_clean_suggested_answer(self):
        form = SuggestedAnswerForm(
            data={
                'survey_answer_ids': [str(self.answer1.pk)],
                'suggested_answer': '  Test answer with whitespace  ',
            }
        )
        self.assertTrue(form.is_valid())
        cleaned_answer = form.clean_suggested_answer()
        self.assertEqual(cleaned_answer, "Test answer with whitespace")

    def test_save_method(self):
        form = SuggestedAnswerForm(
            data={'survey_answer_ids': [str(self.answer1.pk)], 'suggested_answer': 'Test answer'}
        )
        self.assertTrue(form.is_valid())
        instance = form.save()
        self.assertEqual(instance.survey_answer_ids, str(self.answer1.pk))
        self.assertEqual(instance.subtopic_id, self.subtopic.id)
