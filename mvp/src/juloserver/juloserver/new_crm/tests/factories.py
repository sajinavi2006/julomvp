from builtins import object

from factory import SubFactory
from factory.django import DjangoModelFactory

from juloserver.application_flow.models import ApplicationPathTag
from juloserver.julo.models import ApplicationCheckListComment
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
)


class ApplicationCheckListCommentFactory(DjangoModelFactory):
    class Meta(object):
        model = ApplicationCheckListComment

    application = 0
    field_name = 'loan_purpose'
    group = 'sd'
    comment = 'This is a sd group comment'
    agent = SubFactory(AuthUserFactory)


class ApplicationPathTagFactory(DjangoModelFactory):
    class Meta(object):
        model = ApplicationPathTag
