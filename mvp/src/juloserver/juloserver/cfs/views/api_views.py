import logging
from django.utils import timezone

from rest_framework.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
    HTTP_417_EXPECTATION_FAILED,
)
from rest_framework.views import APIView

from juloserver.cfs.exceptions import (
    CfsActionAssignmentInvalidStatus,
    CfsActionAssignmentNotFound,
    CfsActionNotFound,
    CfsFeatureNotEligible,
    CfsFeatureNotFound,
    CfsTierNotFound,
    DoMissionFailed,
    InvalidImage,
    UserForbidden,
    InvalidStatusChange,
)
from juloserver.account.constants import AccountConstant
from juloserver.cfs.constants import (
    CfsActionId,
    GoogleAnalyticsActionTracking,
)
from juloserver.cfs.constants import CfsProgressStatus
from juloserver.cfs.serializers import (
    CfsActionType,
    CfsAssignmentConnectBank,
    CfsAssignmentPhoneRelated,
    CfsAssignmentShareSocialMedia,
    CfsAssignmentVerifyAddress,
    CfsAssignmentVerifyPhoneNumberViaOTP,
    CfsUploadDocument,
    ClaimCfsRewardsSerializer, CfsMonthHistoryDetails,
)
from juloserver.cfs.services.core_services import (
    claim_cfs_rewards,
    create_cfs_action_assignment_connect_bpjs,
    create_cfs_action_assignment_phone_related,
    create_cfs_action_assignment_share_social_media,
    create_cfs_action_assignment_upload_document,
    create_cfs_action_assignment_verify_address,
    create_cfs_action_assignment_verify_phone_via_otp,
    get_cfs_missions,
    get_cfs_status,
    get_customer_j_score_histories,
    get_customer_tier_info,
    get_faqs,
    get_mission_enable_state,
    get_tiers_dict,
    send_cfs_ga_event,
    get_j_score_history_details,
    get_cfs_mission_web_url
)
from juloserver.cfs.services.easy_income_services import (
    get_data_for_easy_income_eligible_and_status,
    get_perfios_url
)
from juloserver.standardized_api_response.utils import (
    success_response,
    response_template
)
from juloserver.otp.constants import SessionTokenAction
from juloserver.otp.services import verify_otp_session
from juloserver.pin.decorators import blocked_session
from juloserver.entry_limit.services import is_entry_level_type
from juloserver.loan.models import LoanDbrLog
from juloserver.loan.services.dbr_ratio import LoanDbrSetting


logger = logging.getLogger(__name__)


class GetCfsFAQs(APIView):
    def get(self, request):
        try:
            faqs = get_faqs()
        except CfsFeatureNotFound:
            return response_template(
                status=HTTP_400_BAD_REQUEST,
                success=False,
                message=['CFS feature setting not found']
            )

        return success_response({
            "header": faqs['header'],
            "topics": faqs['topics'],
        })


class GetCfsStatus(APIView):
    def get(self, request, application_id):
        customer = request.user.customer
        application = customer.account.get_active_application()
        if not application:
            return response_template(
                status=HTTP_404_NOT_FOUND,
                success=False,
                message=['Application not found']
            )

        user = self.request.user
        if user.id != application.customer.user_id:
            return response_template(
                status=HTTP_403_FORBIDDEN,
                success=False,
                message=['User not allowed']
            )

        try:
            cfs_status = get_cfs_status(application)
        except CfsTierNotFound:
            return response_template(
                status=HTTP_404_NOT_FOUND,
                success=False, message=['Tier not found']
            )
        except CfsFeatureNotEligible:
            logger.error({
                'reason': 'CfsFeatureNotEligible',
                'application_id': application.id,
                'partner': bool(application.partner),
            })
            return response_template(
                status=HTTP_403_FORBIDDEN,
                success=False, message=['Not eligible for CFS']
            )
        return success_response(cfs_status)


class GetCfsMissions(APIView):
    def get(self, request, application_id):
        customer = request.user.customer
        application = customer.account.get_active_application()
        if not application:
            return response_template(
                status=HTTP_404_NOT_FOUND,
                success=False,
                message=['Application not found']
            )

        user = self.request.user
        if user.id != application.customer.user_id:
            return response_template(
                status=HTTP_403_FORBIDDEN,
                success=False,
                message=['User not allowed']
            )

        account = application.account
        if account.status_id == AccountConstant.STATUS_CODE.suspended:
            return response_template(
                status=HTTP_417_EXPECTATION_FAILED,
                success=False,
                message=['Maaf saat ini Anda belum bisa melakukan misi. Yuk segera bayar tagihan '
                         'Anda agar bisa melakukan misi dan mendapakan cashback.']
            )

        special_missions, on_going_missions, completed_missions = get_cfs_missions(application)

        return success_response({
            "on_going_missions": on_going_missions,
            "completed_missions": completed_missions,
            "special_missions": special_missions,
        })


class ClaimCfsRewards(APIView):
    serializer_class = ClaimCfsRewardsSerializer

    def post(self, request, application_id):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer = request.user.customer
        application = customer.account.get_active_application()
        if not application:
            return response_template(
                status=HTTP_404_NOT_FOUND,
                success=False,
                message=['Application not found']
            )

        user = self.request.user
        if user.id != application.customer.user_id:
            return response_template(
                status=HTTP_403_FORBIDDEN,
                success=False,
                message=['User not allowed']
            )

        customer = request.user.customer
        action_assignment_id = request.data['action_assignment_id']
        try:
            is_success, cashback_amount = claim_cfs_rewards(
                action_assignment_id, customer
            )
            reward_point = cashback_amount
        except CfsActionAssignmentNotFound:
            return response_template(
                status=HTTP_404_NOT_FOUND,
                success=False, message=['Assignment not found']
            )

        except CfsActionAssignmentInvalidStatus:
            return response_template(
                status=HTTP_400_BAD_REQUEST,
                success=False, message=['Invalid assignment status']
            )

        except UserForbidden:
            return response_template(
                status=HTTP_403_FORBIDDEN, success=False,
                message=['User not allowed'])

        if is_success:
            return success_response({
                "reward_point": reward_point,
                "cashback_amount": cashback_amount,
                "customer_name": customer.fullname,
            })

        else:
            return response_template(
                status=HTTP_400_BAD_REQUEST, success=False,
                message=['Can not claim reward'])


class CfsAssignmentActionUpLoadDocument(APIView):
    serializer_class = CfsUploadDocument

    def post(self, request, application_id):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer = request.user.customer
        application = customer.account.get_active_application()
        if not application:
            return response_template(
                status=HTTP_404_NOT_FOUND,
                success=False,
                message=['Application not found']
            )

        user = self.request.user
        if user.id != application.customer.user_id:
            return response_template(
                status=HTTP_403_FORBIDDEN,
                success=False,
                message=['User not allowed']
            )

        image_id = request.data['image_id']
        try:
            action_assignment = create_cfs_action_assignment_upload_document(application, image_id)

        except CfsActionNotFound:
            return response_template(
                status=HTTP_404_NOT_FOUND,
                success=False,
                message=['Action not found']
            )

        except (DoMissionFailed, InvalidStatusChange, InvalidImage) as err:
            return response_template(
                status=HTTP_400_BAD_REQUEST,
                success=False,
                message=[err.message]
            )

        return success_response({
            "action_assignment_id": action_assignment.id,
            "progress_status": action_assignment.progress_status,
        })


class CfsAssignmentActionVerifyAddress(APIView):
    serializer_class = CfsAssignmentVerifyAddress

    def post(self, request, application_id):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer = request.user.customer
        application = customer.account.get_active_application()
        if not application:
            return response_template(
                status=HTTP_404_NOT_FOUND,
                success=False,
                message=['Application not found']
            )

        user = self.request.user
        if user.id != application.customer.user_id:
            return response_template(
                status=HTTP_403_FORBIDDEN,
                success=False,
                message=['User not allowed']
            )

        try:
            is_success, action_assignment = create_cfs_action_assignment_verify_address(
                application, request.data['latitude'], request.data['longitude']
            )
        except CfsActionNotFound:
            return response_template(
                status=HTTP_404_NOT_FOUND, success=False,
                message=['Action not found']
            )

        except (DoMissionFailed, InvalidStatusChange) as err:
            return response_template(
                status=HTTP_400_BAD_REQUEST,
                success=False,
                message=[err.message]
            )

        if not is_success:
            send_cfs_ga_event(
                application.customer, CfsActionId.VERIFY_ADDRESS,
                GoogleAnalyticsActionTracking.REFUSE
            )
            return response_template(
                status=HTTP_400_BAD_REQUEST,
                success=False,
                message=['Alamat tidak sesuai dengan yang kamu gunakan saat pengajuan aplikasi']
            )

        return success_response({
            "action_assignment_id": action_assignment.id,
            "progress_status": CfsProgressStatus.UNCLAIMED,
        })


class CfsAssignmentActionConnectBank(APIView):
    serializer_class = CfsAssignmentConnectBank

    def post(self, request, application_id):
        """
        The logic of `create_cfs_action_assignment_verify_address` is moved to
        juloserver.cfs.services.core_services.process_post_connect_bank
        """
        return success_response({
            'message': 'Berhasil'
        })


class CfsAssignmentActionConnectBPJS(APIView):
    def post(self, request, application_id):
        customer = request.user.customer
        application = customer.account.get_active_application()
        if not application:
            return response_template(
                status=HTTP_404_NOT_FOUND,
                success=False,
                message=['Application not found']
            )

        user = self.request.user
        if user.id != application.customer.user_id:
            return response_template(
                status=HTTP_403_FORBIDDEN,
                success=False,
                message=['User not allowed']
            )

        try:
            action_assignment = create_cfs_action_assignment_connect_bpjs(
                application, CfsProgressStatus.START
            )
        except CfsActionNotFound:
            return response_template(
                status=HTTP_404_NOT_FOUND,
                success=False,
                message=['Action not found']
            )

        except (DoMissionFailed, InvalidStatusChange) as err:
            return response_template(
                status=HTTP_400_BAD_REQUEST,
                success=False,
                message=[err.message]
            )

        return success_response({
            "action_assignment_id": action_assignment.id,
            "progress_status": CfsProgressStatus.UNCLAIMED,
        })


class CfsAssignmentActionAddRelatedPhone(APIView):
    serializer_class = CfsAssignmentPhoneRelated

    def post(self, request, application_id):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer = request.user.customer
        application = customer.account.get_active_application()
        if not application:
            return response_template(
                status=HTTP_404_NOT_FOUND,
                success=False,
                message=['Application not found']
            )

        user = self.request.user
        if user.id != application.customer.user_id:
            return response_template(
                status=HTTP_403_FORBIDDEN,
                success=False,
                message=['User not allowed']
            )

        request_data = request.data
        phone_number = request_data['phone_number']
        try:
            action_assignment = create_cfs_action_assignment_phone_related(
                application,
                request_data['phone_related_type'], phone_number,
                request_data.get('company_name'), request_data.get('contact_type'),
                request_data.get('contact_name')
            )
        except CfsActionNotFound:
            return response_template(
                status=HTTP_404_NOT_FOUND,
                success=False,
                message=['Action not found']
            )

        except (DoMissionFailed, InvalidStatusChange) as err:
            return response_template(
                status=HTTP_400_BAD_REQUEST,
                success=False,
                message=[err.message]
            )

        return success_response({
            "action_assignment_id": action_assignment.id,
            "progress_status": action_assignment.progress_status,
        })


class CfsAssignmentActionShareSocialMedia(APIView):
    serializer_class = CfsAssignmentShareSocialMedia

    def post(self, request, application_id):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer = request.user.customer
        application = customer.account.get_active_application()
        if not application:
            return response_template(
                status=HTTP_404_NOT_FOUND,
                success=False,
                message=['Application not found']
            )

        user = self.request.user
        if user.id != application.customer.user_id:
            return response_template(
                status=HTTP_403_FORBIDDEN,
                success=False,
                message=['User not allowed']
            )

        try:
            action_assignment = create_cfs_action_assignment_share_social_media(
                application, request.data['app_name']
            )
        except CfsActionNotFound:
            return response_template(
                status=HTTP_404_NOT_FOUND,
                success=False,
                message=['Action not found']
            )

        except (DoMissionFailed, InvalidStatusChange) as err:
            return response_template(
                status=HTTP_400_BAD_REQUEST,
                success=False,
                message=[err.message]
            )

        return success_response({
            "action_assignment_id": action_assignment.id,
            "progress_status": CfsProgressStatus.UNCLAIMED,
        })


class CfsAssignmentActionVerifyPhoneNumber(APIView):
    serializer_class = CfsAssignmentVerifyPhoneNumberViaOTP

    def post(self, request, application_id, session_token_action):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer = request.user.customer
        application = customer.account.get_active_application()
        if not application:
            return response_template(
                status=HTTP_404_NOT_FOUND,
                success=False,
                message=['Application not found']
            )

        user = self.request.user
        if user.id != application.customer.user_id:
            return response_template(
                status=HTTP_403_FORBIDDEN,
                success=False,
                message=['User not allowed']
            )

        try:
            action_assignment = create_cfs_action_assignment_verify_phone_via_otp(
                application, request.user, request.data['session_token'],
                session_token_action
            )
        except CfsActionNotFound:
            return response_template(
                status=HTTP_404_NOT_FOUND,
                success=False,
                message=['Action not found']
            )

        except (DoMissionFailed, InvalidStatusChange) as err:
            return response_template(
                status=HTTP_400_BAD_REQUEST,
                success=False,
                message=[err.message]
            )

        return success_response({
            "action_assignment_id": action_assignment.id,
            "progress_status": CfsProgressStatus.UNCLAIMED,
        })


class CfsAssignmentActionVerifyPhoneNumber1(CfsAssignmentActionVerifyPhoneNumber):
    @verify_otp_session(SessionTokenAction.VERIFY_PHONE_NUMBER)
    @blocked_session()
    def post(self, request, application_id, *args, **kwargs):
        return super().post(request, application_id, SessionTokenAction.VERIFY_PHONE_NUMBER)


class CfsAssignmentActionVerifyPhoneNumber2(CfsAssignmentActionVerifyPhoneNumber):
    @verify_otp_session(SessionTokenAction.VERIFY_PHONE_NUMBER_2)
    @blocked_session()
    def post(self, request, application_id, *args, **kwargs):
        return super().post(request, application_id, SessionTokenAction.VERIFY_PHONE_NUMBER_2)


class CfsAndroidCheckNotificationValidity(APIView):
    serializer_class = CfsActionType

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer = request.user.customer
        application = customer.account.get_active_application()
        if not application:
            return response_template(
                status=HTTP_404_NOT_FOUND,
                success=False,
                message=['Application not found']
            )

        mission_enable_state = get_mission_enable_state(application)
        if not mission_enable_state:
            return response_template(
                status=HTTP_400_BAD_REQUEST,
                success=False,
                message=['User status code is not valid']
            )

        return success_response({
            "isValid": True
        })


class CfsGetTiers(APIView):

    def get(self, request):
        customer = request.user.customer
        application = customer.account.get_active_application()
        if not application:
            return response_template(
                status=HTTP_404_NOT_FOUND,
                success=False,
                message=['Application not found']
            )

        try:
            tiers_dict = get_tiers_dict()
        except CfsTierNotFound:
            return response_template(
                status=HTTP_404_NOT_FOUND,
                success=False, message=['Tier not found']
            )
        j_score, _ = get_customer_tier_info(application)

        return success_response({
            "tiers": tiers_dict.values(),
            "j_score": j_score,
        })


class CustomerJScoreHistories(APIView):

    def get(self, request):
        customer = request.user.customer
        application = customer.account.get_active_application()
        if not application:
            return response_template(
                status=HTTP_404_NOT_FOUND,
                success=False,
                message=['Application not found']
            )

        j_score_histories = get_customer_j_score_histories(application)

        return success_response({
            "j_score_histories": j_score_histories,
        })


class PageAccessibility(APIView):
    def get(self, request):
        customer = request.user.customer
        application = customer.account.get_active_application()
        if not application:
            return response_template(
                status=HTTP_404_NOT_FOUND,
                success=False,
                message=['Application not found']
            )

        is_entry_level = is_entry_level_type(application)

        return success_response({
            "is_entry_level": is_entry_level,
        })


class CustomerJScoreHistoryDetails(APIView):
    serializer_class = CfsMonthHistoryDetails

    def get(self, request, *args, **kwargs):
        """
        Purpose: get request to handle scenarios where user wants to view the Month Score History
        in details
        """
        data = request.query_params
        serializer = self.serializer_class(data=data)
        serializer.is_valid()
        if serializer.errors:
            return response_template(
                status=HTTP_400_BAD_REQUEST,
                success=False,
                message=['Incorrect request data']
            )
        month = data['month']
        year = data['year']
        customer = request.user.customer

        j_score_history_details = get_j_score_history_details(int(month), int(year), customer)
        return success_response({
            "j_score_history_details": j_score_history_details
        })


class MissionWebUrlView(APIView):
    permission_classes = []

    def get(self, request, *args, **kwargs):
        action = request.query_params.get("action", None)
        user = request.user
        application = None
        if hasattr(user, 'customer'):
            application = user.customer.account.get_active_application()

        mission_web_url = get_cfs_mission_web_url(
            user=user, application=application, action=action
        )

        if not mission_web_url:
            return success_response({"url": None})

        today_date = timezone.localtime(timezone.now()).date()
        dbr_log = LoanDbrLog.objects.filter(
            application_id=application.id,
            log_date=today_date,
        ).last()
        if dbr_log:
            loan_dbr = LoanDbrSetting(application, True)
            loan_dbr.update_popup_banner(True, dbr_log.transaction_method_id)
            web_url = loan_dbr.get_popup_banner_url()
            return success_response({"url": web_url})

        return success_response({"url": mission_web_url})


class EasyIncomeView(APIView):
    def get(self, request, *args, **kwargs):
        customer = request.user.customer
        resp_data = get_data_for_easy_income_eligible_and_status(customer)
        return success_response(resp_data)


class PerfiosPageURLListView(APIView):
    def get(self, request, *args, **kwargs):
        customer = request.user.customer
        application = customer.account.get_active_application()
        url = get_perfios_url(application)
        return success_response({"url": url})
