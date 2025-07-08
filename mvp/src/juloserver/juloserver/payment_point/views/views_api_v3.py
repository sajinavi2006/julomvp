import json
from rest_framework.views import APIView

from juloserver.julo.clients.sepulsa import SepulsaResponseCodes
from juloserver.payment_point.permissions import TrainTicketPermission
from juloserver.payment_point.serializers import (
    BookingTrainTicketDataSerializer,
    TrainTicketDataSeatSerializer,
    TrainTicketDataChangeSeatSerializer,
)
from juloserver.payment_point.services.train_related import (
    book_train_ticket,
    get_train_station,
    get_train_ticket,
    train_ticket_limit_validation,
    train_ticket_passenger_seat,
    train_ticket_change_passenger_seat,
    get_train_transaction_history,
    get_train_transaction_booking_info,
)
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    success_response,
    general_error_response,
    not_found_response_custom_message,
    not_acceptable_response,
    request_timeout_response,
    custom_bad_request_response,
    not_found_response,
)

from juloserver.payment_point.constants import (
    SepulsaProductType,
    SepulsaProductCategory,
    TransactionMethodCode,
)
from juloserver.payment_point.serializers import (
    InquiryTrainTicketSerializer,
    InquiryPdamSerializer,
)
from juloserver.payment_point.services.pdam_related import (
    get_pdam_operator,
    get_pdam_bill_information,
)
from juloserver.payment_point.services.views_related import (
    validate_data_and_get_sepulsa_product,
    get_pdam_sepulsa_product,
    get_error_message,
)
from juloserver.payment_point.services.sepulsa import (
    create_sepulsa_payment_point_inquire_tracking_id,
)


class InquireTrainStationView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = None

    def get(self, request):
        stations, error = get_train_station(request.GET.get("query", "").strip())
        if error:
            if isinstance(error, list):
                return custom_bad_request_response(error)
            return general_error_response(error)
        return success_response({"station": stations})


class InquireTrainTicketView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = InquiryTrainTicketSerializer
    permission_classes = [TrainTicketPermission]
    http_method_names = ["post"]

    def post(self, request):
        data, sepulsa_product = validate_data_and_get_sepulsa_product(
            request.data,
            self.serializer_class,
            SepulsaProductType.TRAIN_TICKET,
            SepulsaProductCategory.TRAIN_TICKET
        )
        if not sepulsa_product:
            return general_error_response('Produk tidak ditemukan')

        response, error = get_train_ticket(data, sepulsa_product)
        if error:
            if response and 'response_code' in response:
                error_message = get_error_message(
                    response['response_code'], SepulsaProductType.TRAIN_TICKET
                )
                if error_message and isinstance(error_message, list):
                    return custom_bad_request_response(error_message)
                error = error_message if error_message else error
            return general_error_response(error)
        return success_response(response)


class InquirePdamOperatorView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = None

    def get(self, request):
        operators, error = get_pdam_operator(request.GET.get('query', '').strip())
        if error:
            return general_error_response(error)
        return success_response({"operator": operators})


class InquirePdamView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = InquiryPdamSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.data
        if len(data['customer_number']) >= 20:
            error = [
                'Nomor Pelanggan Terlalu Panjang',
                'Masukan nomor pelanggan dengan jumlah karakter yang sesuai, Ya!'
            ]
            return custom_bad_request_response(message=error)
        sepulsa_product = get_pdam_sepulsa_product(
            data['operator_code'],
            data['operator_name']
        )
        if not sepulsa_product:
            return general_error_response('Produk yang kamu inginkan belum tersedia')
        data_api = {
            'customer_number': data['customer_number'],
            'product_id': sepulsa_product.product_id,
            'operator_code': data['operator_code'],
        }
        data_for_android, error = get_pdam_bill_information(data_api, sepulsa_product)
        if error:
            error = [
                'Sepertinya Ada yang Salah',
                'Pastikan nomor pelangganmu benar. Jika sudah, silakan coba lagi, ya!'
            ]
            return custom_bad_request_response(message=error)
        elif 'status' in data_for_android and data_for_android['status'] is False:
            if data_for_android['response_code'] == "20":
                error = [
                    'Nomor Pelanggan Tidak Ditemukan',
                    'Nomor salah atau tidak terdaftar. Harap masukkan nomor dengan benar'
                ]
                return not_found_response_custom_message(message=error)
            elif data_for_android['response_code'] == "50":
                error = 'Tagihan sudah terbayar'
                return not_acceptable_response(message=error)
            elif data_for_android['response_code'] == "23":
                error = [
                    'Terdapat Masalah pada Operator',
                    'Silakan coba lagi'
                ]
                return request_timeout_response(message=error)
            else:
                error = [
                    'Sepertinya Ada yang Salah',
                    'Pastikan nomor pelangganmu benar. Jika sudah, silakan coba lagi, ya!'
                ]
                return custom_bad_request_response(message=error)

        inquire_tracking_id = create_sepulsa_payment_point_inquire_tracking_id(
            account=request.user.customer.account,
            transaction_method_id=TransactionMethodCode.PDAM.code,
            price=data_for_android["total_bills"],
            sepulsa_product_id=sepulsa_product.id,
            identity_number=data["customer_number"],
            other_data={
                "customer_name": data_for_android["customer_name"],
            },
        )
        data_for_android["sepulsa_payment_point_inquire_tracking_id"] = inquire_tracking_id

        return success_response(data=data_for_android)


class TrainTicketView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = BookingTrainTicketDataSerializer
    permission_classes = [TrainTicketPermission]
    http_method_names = ["post"]

    def post(self, request):
        data, sepulsa_product = validate_data_and_get_sepulsa_product(
            request.data,
            self.serializer_class,
            SepulsaProductType.TRAIN_TICKET,
            SepulsaProductCategory.TRAIN_TICKET,
        )
        if not sepulsa_product:
            return general_error_response("Produk tidak ditemukan")

        customer = request.user.customer
        validation_error = train_ticket_limit_validation(customer, sepulsa_product, data)
        if validation_error:
            return general_error_response(message=validation_error)

        data_for_android, error = book_train_ticket(data, sepulsa_product, customer)
        if error:
            if isinstance(error, list):
                return custom_bad_request_response(error)
            return general_error_response(message=error)
        elif 'response_code' in data_for_android:
            response_code = data_for_android['response_code']
            if response_code == SepulsaResponseCodes.WRONG_NUMBER:
                error = [
                    'Nomor Pelanggan Tidak Ditemukan',
                ]
                return not_found_response(message=error)
            elif data_for_android['response_code'] == '23':
                error = ['Terdapat Masalah pada Operator', 'Silakan coba lagi']
                return request_timeout_response(message=error)
            elif response_code == SepulsaResponseCodes.GENERAL_ERROR:
                error = 'Terdapat Masalah saat Booking'
                return general_error_response(message=error)

        return success_response(data=data_for_android)


class TrainTicketPessengerSeat(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = TrainTicketDataSeatSerializer
    permission_classes = [TrainTicketPermission]
    http_method_names = ["post"]

    def post(self, request):
        data, sepulsa_product = validate_data_and_get_sepulsa_product(
            request.data,
            self.serializer_class,
            SepulsaProductType.TRAIN_TICKET,
            SepulsaProductCategory.TRAIN_TICKET,
        )
        if not sepulsa_product:
            return general_error_response("Produk tidak ditemukan")

        data['product_code'] = sepulsa_product.product_id
        data_for_android, error = train_ticket_passenger_seat(data)
        if error:
            if isinstance(error, list):
                return custom_bad_request_response(error)
            return general_error_response(message=error)
        elif 'response_code' in data_for_android:
            response_code = data_for_android['response_code']
            if response_code in SepulsaResponseCodes.TRAIN_TICKET_ERROR_RESPONSE:
                error_message = get_error_message(
                    response_code, SepulsaProductType.TRAIN_TICKET
                )
                return custom_bad_request_response(error_message)
        return success_response(data=data_for_android)


class TrainTicketChangeSeat(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = TrainTicketDataChangeSeatSerializer
    permission_classes = [TrainTicketPermission]
    http_method_names = ["post"]

    def post(self, request):
        data, sepulsa_product = validate_data_and_get_sepulsa_product(
            request.data,
            self.serializer_class,
            SepulsaProductType.TRAIN_TICKET,
            SepulsaProductCategory.TRAIN_TICKET,
        )
        if not sepulsa_product:
            return general_error_response('Produk tidak ditemukan')

        data['data'] = json.loads(data['data'].replace("'", '"'))
        data['product_code'] = sepulsa_product.product_id
        data_for_android, error = train_ticket_change_passenger_seat(data)
        if error:
            if isinstance(error, list):
                return custom_bad_request_response(error)
            return general_error_response(message=error)
        elif 'response_code' in data_for_android:
            response_code = data_for_android['response_code']
            if response_code in SepulsaResponseCodes.GENERAL_ERROR:
                error = 'Terdapat Masalah saat Pilih Kursi'
                return general_error_response(message=error)

        return success_response(data=data_for_android)


class TrainTicketTransactionHistory(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        customer = self.request.user.customer
        if not customer:
            return general_error_response('Customer tidak ditemukan')

        data_for_android, error = get_train_transaction_history(customer)
        if error:
            return general_error_response(message=error)
        return success_response(data=data_for_android)


class TrainTicketTransactionBookingInfo(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request, *args, **kwargs):
        booking_code = kwargs['booking_code']
        data_for_android, error = get_train_transaction_booking_info(
            booking_code=booking_code, user_id=request.user.id
        )
        if error:
            return general_error_response(message=error)
        return success_response(data=data_for_android)


class TrainTicketTransactionInfo(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request, *args, **kwargs):
        loan_xid = kwargs['loan_xid']
        data_for_android, error = get_train_transaction_booking_info(
            loan_xid=loan_xid, user_id=request.user.id
        )
        if error:
            return general_error_response(message=error)
        return success_response(data=data_for_android)
