from factory import SubFactory
from factory.django import DjangoModelFactory
from factory.faker import Faker
from juloserver.cx_complaint_form.models import ComplaintSubTopic, ComplaintTopic, SuggestedAnswer


class ComplaintTopicFactory(DjangoModelFactory):
    class Meta(object):
        model = ComplaintTopic

    topic_name = 'Topic 1'
    image_url = 'complaint-form/topics/topic-1.svg'


class ComplaintSubTopicFactory(DjangoModelFactory):
    class Meta(object):
        model = ComplaintSubTopic

    topic = SubFactory(ComplaintTopicFactory)
    title = 'Sub Topic 1'
    action_type = 'email'
    action_value = None
    confirmation_dialog_title = None
    confirmation_dialog_banner = None
    confirmation_dialog_content = None
    confirmation_dialog_info_text = None
    confirmation_dialog_button_text = None


class SuggestedAnswerFactory(DjangoModelFactory):
    class Meta:
        model = SuggestedAnswer

    survey_answer_ids = "['1', '2', '3']"
    suggested_answer = "<p><strong>Lorem Ipsum</strong>&nbsp;is simply dummy text of the printing and typesetting industry. Lorem Ipsum has been the industry&#39;s standard dummy text ever since the 1500s, when an unknown printer took a galley of type and scrambled it to</p><ul><li><strong>Lorem Ipsum</strong>&nbsp;is simply dummy text of the printing and typesetting industry. Lorem Ipsum has been the industry&#39;s standard dummy text ever since the 1500s, when an unknown printer took a galley of type and scrambled it to</li><li><strong>Lorem Ipsum</strong>&nbsp;is simply dummy text of the printing and typesetting industry. Lorem Ipsum has been the industry&#39;s standard dummy text ever since the 1500s, when an unknown printer took a galley of type and scrambled it to</li><li><strong>Lorem Ipsum</strong>&nbsp;is simply dummy text of the printing and typesetting industry. Lorem Ipsum has been the industry&#39;s standard dummy text ever since the 1500s, when an unknown printer took a galley of type and scrambled it to</li></ul>"
    topic = SubFactory(ComplaintTopicFactory)
    subtopic = SubFactory(ComplaintSubTopicFactory)
