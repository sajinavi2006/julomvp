import semver

from functools import wraps
from juloserver.standardized_api_response.utils import general_error_response
from juloserver.pin.utils import transform_error_msg
from juloserver.application_form.constants import AdditionalMessagesSubmitApp
from juloserver.julo.models import FeatureSetting
from juloserver.julo.constants import FeatureNameConst


def parse_param(serializer_class):
    def _parse_param(function):
        @wraps(function)
        def wrapper(view, request, *args, **kwargs):
            app_version = request.META.get('HTTP_X_APP_VERSION')
            if not app_version:
                return general_error_response('Invalid params')

            serializer = serializer_class(data=request.data)
            if not serializer.is_valid():
                return general_error_response(
                    transform_error_msg(serializer.errors, exclude_key=True)[0]
                )
            validated_data = serializer.validated_data
            validated_data['app_version'] = app_version

            return function(view, request, *args, validated_data=validated_data, **kwargs)

        return wrapper

    return _parse_param


def build_additional_message(app_version, title=None, message=None, button_text=None):

    if not app_version:
        return None

    if not semver.match(app_version, '>=9.1.0'):
        return None

    banner_url = get_setting_additional_msg()
    if not banner_url:
        return None

    default_structure = {
        AdditionalMessagesSubmitApp.KEY_ADDITIONAL_MESSAGE: {
            'title': title,
            'message': message,
            'banner_url': banner_url,
            'button_text': button_text,
        }
    }
    return default_structure


def get_setting_additional_msg():

    setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.ADDITIONAL_MESSAGE_SUBMIT_APP
    ).last()
    if not setting or not setting.is_active:
        return None

    return setting.parameters.get(AdditionalMessagesSubmitApp.KEY_BANNER_URL)
