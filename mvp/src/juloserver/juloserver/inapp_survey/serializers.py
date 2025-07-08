from collections import OrderedDict  # noqa
import uuid

from django.db import transaction
from rest_framework import serializers

from juloserver.customer_module.services.customer_related import (
    get_ongoing_account_deletion_requests,
)
from juloserver.inapp_survey.const import QUESTION_CACHE_KEY
from juloserver.inapp_survey.models import InAppSurveyUserAnswer
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import Customer
from juloserver.julo.services2 import get_redis_client

sentry = get_julo_sentry_client()


class InAppSurveyQuestionSerializer(serializers.Serializer):
    id = serializers.ReadOnlyField()
    question = serializers.ReadOnlyField()
    survey_type = serializers.ReadOnlyField()
    survey_usage = serializers.ReadOnlyField()
    answer_type = serializers.ReadOnlyField()
    is_first_question = serializers.ReadOnlyField()
    is_optional_question = serializers.ReadOnlyField()
    should_randomize = serializers.ReadOnlyField()
    page = serializers.ReadOnlyField()


class InAppSurveyAnswerSerializer(serializers.Serializer):
    id = serializers.ReadOnlyField()
    answer = serializers.ReadOnlyField()
    question = InAppSurveyQuestionSerializer()
    cdate = serializers.ReadOnlyField()
    udate = serializers.ReadOnlyField()
    answer_type = serializers.ReadOnlyField()
    is_bottom_position = serializers.ReadOnlyField()


class InAppSurveyUserAnswerSerializer(serializers.ModelSerializer):
    answers = serializers.ListField(write_only=True)

    class Meta:
        model = InAppSurveyUserAnswer
        fields = ("answers",)

    def validate(self, data):
        survey_type = self.context.get("survey_type")
        _ = self.context.get("survey_usage")
        customer = self.context.get("request").user.customer

        if survey_type == "account-deletion-request":
            is_account_deletion_request_exists = get_ongoing_account_deletion_requests(
                [customer.id]
            )
            if is_account_deletion_request_exists:
                raise serializers.ValidationError(
                    "Failed to submit survey because customer already requested account deletion."
                )
        elif survey_type == "complaint-form":
            pass
        elif survey_type == "autodebet-deactivation":
            pass
        else:
            customer_exists = InAppSurveyUserAnswer.objects.filter(customer_id=customer.id).exists()
            if customer_exists:
                raise serializers.ValidationError(
                    "Failed to submit because customer already submitted survey."
                )

        return data

    def create(self, validated_data):
        customer = self.context.get("request").user.customer
        survey_type = self.context.get("survey_type")
        submission_uid = uuid.uuid4()

        redis_client = get_redis_client()
        key = QUESTION_CACHE_KEY.format(customer.id)
        cached_data = redis_client.get(key)
        if not cached_data:
            return False, "Failed to submit, please try again."

        questions = [dict(data_dict) for data_dict in eval(cached_data)]

        answers = []
        with transaction.atomic(using="juloplatform_db"):
            for item in validated_data["answers"]:
                ori_question = [
                    ori_item for ori_item in questions if item["question_id"] == ori_item["id"]
                ][0]
                if (not ori_question["is_optional_question"] and "answer" not in item) or (
                    not ori_question["is_optional_question"] and not item["answer"]
                ):
                    msg = "Answer must be filled, please try again."
                    return False, msg

                if "answer" not in item or not item["answer"]:
                    answer = ''
                else:
                    answer = item["answer"]

                answers.append(
                    InAppSurveyUserAnswer(
                        customer_id=customer.id,
                        question=item["question"],
                        answer=answer,
                        submission_uid=submission_uid,
                        survey_type=survey_type,
                    )
                )

            InAppSurveyUserAnswer.objects.bulk_create(answers)
            redis_client.delete_key(key)
            return True, submission_uid


class WebInAppSurveyUserAnswerSerializer(serializers.ModelSerializer):
    nik = serializers.CharField(write_only=True)
    email = serializers.CharField(write_only=True)
    phone = serializers.CharField(write_only=True)
    answers = serializers.ListField(write_only=True)

    class Meta:
        model = InAppSurveyUserAnswer
        fields = (
            "nik",
            "email",
            "phone",
            "answers",
        )

    def create(self, validated_data):
        identifier = self.context.get("ip_addr")

        customer = Customer.objects.filter(
            nik=validated_data["nik"],
            phone=validated_data["phone"],
            email=validated_data["email"],
        ).first()

        submission_uid = uuid.uuid4()

        redis_client = get_redis_client()
        key = QUESTION_CACHE_KEY.format(identifier)
        cached_data = redis_client.get(key)
        if not cached_data:
            return False, "Failed to submit, please try again. IP Address: " + identifier

        questions = [dict(data_dict) for data_dict in eval(cached_data)]

        answers = []
        with transaction.atomic(using="juloplatform_db"):
            for item in validated_data["answers"]:
                ori_question = [
                    ori_item for ori_item in questions if item["question_id"] == ori_item["id"]
                ][0]
                if (not ori_question["is_optional_question"] and "answer" not in item) or (
                    not ori_question["is_optional_question"] and not item["answer"]
                ):
                    msg = "Answer must be filled, please try again."
                    return False, msg

                if "answer" not in item or not item["answer"]:
                    answer = ''
                else:
                    answer = item["answer"]

                answers.append(
                    InAppSurveyUserAnswer(
                        customer_id=customer.id if customer else None,
                        question=item["question"],
                        answer=answer,
                        submission_uid=submission_uid,
                        email=validated_data["email"],
                        nik=validated_data["nik"],
                        phone=validated_data["phone"],
                    )
                )

            InAppSurveyUserAnswer.objects.bulk_create(answers)
            redis_client.delete_key(key)
            return True, submission_uid
