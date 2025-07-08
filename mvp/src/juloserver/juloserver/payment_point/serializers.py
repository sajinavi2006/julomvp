import logging
from juloserver.registration_flow.serializers import phone_regex_pattern
from juloserver.apiv2.utils import custom_error_messages_for_required

from rest_framework import serializers

from juloserver.payment_point.models import TrainStation, TrainTransaction


logger = logging.getLogger(__name__)


class InquiryElectricitySerializer(serializers.Serializer):
    customer_number = serializers.CharField(required=True)
    product_id = serializers.CharField(required=True)


class PaymentProductSerializer(serializers.Serializer):
    mobile_operator_id = serializers.IntegerField(required=False, default=None)
    type = serializers.CharField(required=True)
    category = serializers.CharField(required=True)
    transaction_type_code = serializers.IntegerField(required=False, default=None)


class MobileOperatorSerializer(serializers.Serializer):
    mobile_phone = serializers.CharField(required=True)


class MobilePhoneSerializer(serializers.Serializer):
    mobile_phone = serializers.RegexField(
        phone_regex_pattern,
        required=True,
        error_messages=custom_error_messages_for_required("Phone"))


class InquireBpjsSerializer(serializers.Serializer):
    bpjs_number = serializers.CharField(required=True)
    bpjs_times = serializers.IntegerField(required=True)


class InquireMobilePostpaidSerializer(serializers.Serializer):
    product_id = serializers.CharField(required=True)
    mobile_number = serializers.CharField(required=True)


class InquiryElectricityPostpaidSerializer(serializers.Serializer):
    customer_number = serializers.CharField(required=True)


class InquiryTrainTicketSerializer(serializers.Serializer):
    depart = serializers.CharField(required=True)
    destination = serializers.CharField(required=True)
    date = serializers.DateField(input_formats=["%Y-%m-%d"], required=True)
    adult = serializers.IntegerField(required=True)
    infant = serializers.IntegerField(required=True)


class InquiryPdamSerializer(serializers.Serializer):
    customer_number = serializers.CharField(required=True)
    operator_code = serializers.CharField(required=True)
    operator_name = serializers.CharField(required=True)


class BookingTrainTicketDataSerializer(serializers.Serializer):
    def validate(self, data):
        passenger = data['data']['passenger']
        total_passenger = {"adult": 0, "infant": 0}
        for passenger_data in passenger['list']:
            if len(passenger_data['identity_number']) != 16:
                raise serializers.ValidationError(
                    {"data": "Nomor identitas harus 16 digit"}
                )
            if passenger_data['type'] not in total_passenger:
                total_passenger[passenger_data['type']] = 0
            total_passenger[passenger_data['type']] += 1

        passenger_number = passenger['number']
        for key, value in total_passenger.items():
            if key in passenger_number and passenger_number[key] != value:
                raise serializers.ValidationError(
                    {"data": "Number of %s passenger not match" % key}
                )
        return data

    class _Data(serializers.Serializer):
        class AccountInfo(serializers.DictField):
            name = serializers.CharField()
            email = serializers.CharField()

        class Passenger(serializers.Serializer):
            class Number(serializers.DictField):
                adult = serializers.IntegerField()
                infant = serializers.IntegerField(required=False)

            class List_(serializers.ListField):
                type = (serializers.CharField(),)
                title = (serializers.CharField(),)
                name = (serializers.CharField(),)
                identity_number = (serializers.CharField(max_length=16, min_length=16),)

            number = Number()
            list = List_()

        # top level fields
        schedule_id = serializers.CharField()
        account = AccountInfo()
        passenger = Passenger()
        total_price = serializers.IntegerField(required=False)

    data = _Data()
    reference_number = serializers.CharField()
    customer_id = serializers.CharField()  # phone number


class TrainStationSerializer(serializers.ModelSerializer):
    class Meta:
        model = TrainStation
        exclude = ("id",)


class TrainTransactionSerializer(serializers.ModelSerializer):
    depart_station = TrainStationSerializer()
    destination_station = TrainStationSerializer()

    class Meta:
        model = TrainTransaction
        exclude = (
            "id",
            "sepulsa_transaction",
            "round_trip_train_transaction",
        )


class TrainTicketDataSeatSerializer(serializers.Serializer):
    reference_number = serializers.CharField(required=True)
    schedule_id = serializers.CharField(required=True)


class TrainTicketDataChangeSeatSerializer(serializers.Serializer):
    customer_id = serializers.CharField(required=True)
    reference_number = serializers.CharField(required=True)
    data = serializers.CharField(required=True)


class InquiryInternetBillSerializer(serializers.Serializer):
    customer_number = serializers.RegexField(
        regex=r'^[0-9]{1,20}$',
        required=True,
    )
    product_id = serializers.IntegerField(required=True)
