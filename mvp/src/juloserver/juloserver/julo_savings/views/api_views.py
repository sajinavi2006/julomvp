from rest_framework.views import APIView
from rest_framework.status import (
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
)

from juloserver.standardized_api_response.utils import (
    success_response,
    response_template,
)
from juloserver.julo_savings.models import (
    JuloSavingsWhitelistApplication,
    JuloSavingsMobileContentSetting,
)
from juloserver.julo_savings.constants import ContentNameConst, DescriptionConst


class GetWhitelistStatus(APIView):
    def get(self, request, application_id):
        application = JuloSavingsWhitelistApplication.objects.get_or_none(
            application_id=application_id
        )
        if not application:
            data = {'whitelist_status': False}
            return response_template(data=data, message=['Application are not whitelisted'])

        user = self.request.user
        if user.id != application.application.customer.user_id:
            return response_template(
                status=HTTP_403_FORBIDDEN, success=False, message=['User are not allowed']
            )

        data = {'whitelist_status': True}
        return success_response(data)


class GetBenefitWelcomeContent(APIView):
    def get(self, request):
        contents = JuloSavingsMobileContentSetting.objects.filter(
            content_name=ContentNameConst.BENEFIT_SCREEN, is_active=True
        ).order_by('id')
        if not contents:
            return response_template(
                status=HTTP_404_NOT_FOUND, success=False, message=['Data are not found']
            )
        # there should be only 1 json data for one content_name
        json_content = None
        # there could be more than 1 html content for one content_name
        html_content = []
        for content in contents:
            if content.description == DescriptionConst.JSON_CONTENT:
                json_content = content.parameters
            else:
                if content not in html_content:
                    html_content.append(content)
        if not json_content:
            return response_template(
                status=HTTP_404_NOT_FOUND, success=False, message=['Data are not found']
            )
        benefits_data = json_content['benefits']['benefits_data']
        for benefit in benefits_data:
            for content_obj in html_content:
                if benefit['title'] == content_obj.description:
                    benefit['description'] = content_obj.content

        return success_response(json_content)
