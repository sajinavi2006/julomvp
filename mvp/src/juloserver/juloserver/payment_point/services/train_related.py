import json
import copy
import logging

from babel.dates import format_datetime
from django.utils import timezone

from collections import OrderedDict

from django.db.models import F, Q

from juloserver.customer_module.services.view_related import (
    get_transaction_method_whitelist_feature,
)
from juloserver.julo.clients.sepulsa import SepulsaResponseCodes
from juloserver.julo.models import (
    Document,
    Loan,
)
from juloserver.julo.statuses import LoanStatusCodes

from juloserver.payment_point.exceptions import TrainTicketException
from juloserver.payment_point.constants import (
    ErrorMessage,
    SepulsaAdminFee,
    TrainTicketStatus,
    TransactionMethodCode,
)

from juloserver.payment_point.models import (
    TrainStation,
    TrainTransaction,
    CustomerPassanger,
    TrainPassanger,
)
from juloserver.payment_point.serializers import TrainTransactionSerializer
from juloserver.account.models import AccountLimit

from juloserver.loan.services.loan_related import get_credit_matrix_and_credit_matrix_product_line
from juloserver.payment_point.services.sepulsa import SepulsaLoanService

from juloserver.payment_point.services.train_tasks_related import get_passanger_seat
from juloserver.payment_point.tasks.train_related import update_train_stations
from juloserver.payment_point.utils import (
    reformat_train_duration,
    convert_string_to_datetime,
    get_train_duration,
)

logger = logging.getLogger(__name__)


def get_train_station(q=None):
    station_qs = TrainStation.objects.annotate(
        station_name=F("name"), station_code=F("code")
    )
    stations = station_qs.filter(is_popular_station=True)
    if q:
        stations = station_qs.filter(
            Q(code__icontains=q) | Q(city__icontains=q) | Q(name__icontains=q)
        )
    if stations:
        return stations.values("city", "station_code", "station_name"), None

    api_response, error = SepulsaLoanService().inquire_train_station()
    if error:
        return api_response, error

    update_train_stations.delay(api_response["data"])
    stations = []
    for station in api_response["data"]:
        if (
            q.lower() in station["city"].lower()
            or q.lower() in station["station_code"].lower()
            or q.lower() in station["station_name"].lower()
        ):
            stations.append(station)

    if not stations:
        return [], "Stasiun tidak ditemukan"

    return stations, None


def get_train_ticket(data, sepulsa_product):
    if sepulsa_product and sepulsa_product.product_id:
        data['product_code'] = sepulsa_product.product_id
    api_response, error = SepulsaLoanService().inquire_train_ticket(data)
    if error:
        return api_response, error

    if 'response_code' in api_response:
        return api_response, api_response['message']

    if not api_response['data'].get('schedule'):
        return {
            'reference_number': api_response['reference_number'],
            'expired_at': api_response['data']['expired_at'],
            'schedule': [],
        }, None

    current_ts = timezone.localtime(timezone.now())
    for schedule in api_response['data']['schedule']:
        schedule['duration_in_second'] = reformat_train_duration(schedule['duration'])
        schedule['transportation']['class'] = get_train_class_name(
            schedule['transportation'].get('class')
        )
        departure_datetime = convert_string_to_datetime(
            schedule["departure_datetime"], "%Y-%m-%d %H:%M"
        )
        datediff = departure_datetime - current_ts
        hours = float(datediff.days * 12)
        hours += float(datediff.seconds / 3600)
        schedule['hours'] = hours
        schedule['diff'] = datediff
        if hours <= 7:
            schedule['is_disabled'] = True
            schedule['available_seat'] = 0

    return {
        'reference_number': api_response['reference_number'],
        'expired_at': api_response['data']['expired_at'],
        'schedule': api_response['data']['schedule'],
    }, None


def get_train_class_name(train_class):
    if train_class == 'K':
        return 'Ekonomi'
    elif train_class == 'E':
        return 'Eksekutif'
    elif train_class == 'B':
        return 'Bisnis'
    elif train_class == 'L':
        return 'Luxury'

    return train_class


def book_train_ticket(data, sepulsa_product, customer):
    if not sepulsa_product and not sepulsa_product.product_id:
        raise Exception

    if 'data' in data and type(data['data']) == OrderedDict:
        data['data'] = json.loads(json.dumps(data['data']))

    data["product_code"] = sepulsa_product.product_id
    data.pop('total_price', None)
    api_response, error = SepulsaLoanService().inquire_booking_train_ticket(data)
    if error or api_response['response_code'] in SepulsaResponseCodes.TRAIN_TICKET_ERROR_RESPONSE:
        logger.info({
            'action': 'juloserver.payment_point.service.train_related.book_train_ticket',
            'request': data,
            'api_response': api_response,
            'error_message': error,
        })
        return api_response, error

    prepared_data = prepare_data_from_booking_response(api_response)

    transaction = create_train_transaction(prepared_data, customer)
    create_train_passanger_seat(api_response, transaction)

    # serializer to show front end
    serializer = TrainTransactionSerializer(instance=transaction)
    return_data = serializer.data
    return_data['payment_point_product_id'] = sepulsa_product.id
    if 'bill_detail' in api_response["data"]:
        return_data['seat'] = api_response["data"]["bill_detail"]['seat']
    return {
        "data": return_data,
    }, None


def prepare_data_from_booking_response(response):
    schedule = response["data"]["bill_detail"]["schedule"]
    return dict(
        depart_station=schedule["station"]["depart"],
        destination_station=schedule["station"]["destination"],
        adult=response["data"]["bill_detail"]["passenger"]["number"]["adult"],
        infant=response["data"]["bill_detail"]["passenger"]["number"]["infant"],
        account_email=response["data"]["account"]["email"],
        account_mobile_phone=response["customer_id"],
        reference_number=response["reference_number"],
        expired_at=response["data"]["expired_at"],
        train_schedule_id=schedule["schedule_id"],
        departure_datetime=convert_string_to_datetime(
            schedule["departure_datetime"], "%Y-%m-%d %H:%M"
        ),
        arrival_datetime=convert_string_to_datetime(schedule["arrival_datetime"], "%Y-%m-%d %H:%M"),
        duration=schedule["duration"],
        train_name=schedule["transportation"]["name"],
        train_class=get_train_class_name(schedule["transportation"].get('class')),
        train_subclass=schedule["transportation"]["subclass"],
        adult_train_fare=schedule["transportation"]["fare"]["adult"],
        infant_train_fare=schedule["transportation"]["fare"]["infant"],
        booking_code=response["data"]["booking_code"],
        price=response["price"],
        admin_fee=response['data']['bill_summary']['admin_fee'],
    )


def prepared_data_for_passanger(data):
    passangers = data['passenger']
    seats = data['seat'][0]
    decrement = 0
    for idx, passanger_detail in enumerate(passangers['list']):
        passangers['list'][idx].update(
            {
                'seat': {'wagon': "", 'row': "", 'column': ""},
                'passanger_type': passanger_detail["type"],
            }
        )
        passangers['list'][idx].pop('type', None)
        if passanger_detail["passanger_type"] == "infant":
            decrement += 1
            continue
        idx -= decrement
        passangers['list'][idx]['seat'] = {
            'wagon': seats['wagon'],
            'row': seats['list'][idx]['row'],
            'column': seats['list'][idx]['column'],
        }
    return passangers


def create_train_transaction(prepared_data, customer):
    depart_station = TrainStation.objects.filter(
        code__iexact=prepared_data["depart_station"],
    ).first()
    destination_station = TrainStation.objects.filter(
        code__iexact=prepared_data["destination_station"]
    ).first()
    if not depart_station or not destination_station:
        raise TrainTicketException("no depart or destination station")

    return TrainTransaction.objects.create(
        depart_station=depart_station,
        customer=customer,
        destination_station=destination_station,
        adult=prepared_data["adult"],
        infant=prepared_data["infant"],
        account_email=prepared_data["account_email"],
        account_mobile_phone=prepared_data["account_mobile_phone"],
        reference_number=prepared_data["reference_number"],
        expired_at=prepared_data["expired_at"],
        train_schedule_id=prepared_data["train_schedule_id"],
        departure_datetime=prepared_data["departure_datetime"],
        arrival_datetime=prepared_data["arrival_datetime"],
        duration=prepared_data["duration"],
        train_name=prepared_data["train_name"],
        train_class=prepared_data["train_class"],
        train_subclass=prepared_data["train_subclass"],
        adult_train_fare=prepared_data["adult_train_fare"],
        infant_train_fare=prepared_data["infant_train_fare"],
        booking_code=prepared_data["booking_code"],
        price=prepared_data["price"],
        admin_fee=prepared_data["admin_fee"],
    )


def create_train_passanger_seat(api_response, train_transaction):
    passanger_data = prepared_data_for_passanger(api_response['data']['bill_detail'])
    customer = train_transaction.customer
    train_passangers = []
    for idx, passanger in enumerate(passanger_data['list']):
        customer_passanger = CustomerPassanger.objects.get_or_none(
            customer=customer, identity_number=passanger['identity_number']
        )
        seat = passanger['seat']
        passanger.pop('seat', None)
        if customer_passanger:
            customer_passanger.update_safely(**passanger)
        else:
            customer_passanger = CustomerPassanger.objects.create(customer=customer, **passanger)

        train_passangers.append(
            TrainPassanger(
                train_transaction=train_transaction,
                passanger=customer_passanger,
                number=idx + 1,
                **seat
            )
        )
    if train_passangers:
        TrainPassanger.objects.bulk_create(train_passangers)

    return passanger_data


def train_ticket_passenger_seat(data):
    api_response, error = SepulsaLoanService().inquire_train_ticket_seat(data)

    if error or api_response['response_code'] in SepulsaResponseCodes.TRAIN_TICKET_ERROR_RESPONSE:
        logger.info({
            'action': 'train_ticket_passenger_seat',
            'data': data,
            'api_response': api_response,
            'error_message': error,
        })
        return api_response, error

    train_transaction = TrainTransaction.objects.filter(
        train_schedule_id=data['schedule_id'], reference_number=data['reference_number']
    ).first()

    if not train_transaction:
        return None, "Train transaction not found"

    api_response_data_station = api_response['data']['station']
    api_response_data_seat = api_response['data']['seat']
    depart_station = TrainStation.objects.filter(
        code__iexact=api_response_data_station["depart"],
    ).first()
    destination_station = TrainStation.objects.filter(
        code__iexact=api_response_data_station["destination"]
    ).first()

    if not depart_station:
        return None, "Depart station not found"

    if not destination_station:
        return None, "Destination station not found"

    total_wagon = len(api_response_data_seat)
    seats = []
    for seat in api_response_data_seat:
        wagon = seat
        available_seat = 0
        for list in seat['list']:
            if list['is_filled'] is False:
                available_seat += 1
        wagon['available_seat'] = available_seat
        seat_list = check_seat_column(seat['list'])
        wagon['list'] = seat_list['list_seat']
        seats.append(wagon)

    return {
        "departure_datetime": timezone.localtime(train_transaction.departure_datetime),
        "arrival_datetime": timezone.localtime(train_transaction.arrival_datetime),
        "station": {
            "depart": {"city": depart_station.city, "station_name": depart_station.name},
            "destination": {
                "city": destination_station.city,
                "station_name": destination_station.name,
            },
        },
        "duration": train_transaction.duration,
        "transportation": {
            "name": train_transaction.train_name,
            "class": train_transaction.train_class,
            "subclass": train_transaction.train_subclass,
        },
        "adult_price": train_transaction.adult_train_fare,
        "infant_price": train_transaction.infant_train_fare,
        "wagon_info": {
            "total_wagon": total_wagon,
            "left_seat": seat_list['wagon_info_left_seat'],
            "right_seat": seat_list['wagoon_info_right_seat'],
            "total_row": seat_list['wagon_total_row'],
        },
        "seat": seats,
    }, None


def check_seat_column(lists):
    column = []
    list_row = []

    for list in lists:
        if list['column'] not in column:
            column.append(list['column'])

        if list['row'] not in list_row:
            list_row.append(int(list['row']))

    if 'E' in column:
        wagon_info_left_seat = 3
        wagon_info_right_seat = 2
    elif 'D' in column:
        wagon_info_left_seat = 2
        wagon_info_right_seat = 2
    elif 'C' in column:
        wagon_info_left_seat = 2
        wagon_info_right_seat = 1
    else:
        wagon_info_left_seat = 1
        wagon_info_right_seat = 1

    res = {
        'list_seat': lists,
        'wagon_info_left_seat': wagon_info_left_seat,
        'wagoon_info_right_seat': wagon_info_right_seat,
        'wagon_total_row': max(list_row),
    }
    return res


def train_ticket_change_passenger_seat(datas):
    api_data = copy.deepcopy(datas)
    train_transaction = TrainTransaction.objects.filter(
        reference_number=datas['reference_number']
    ).first()

    changes_data = 0
    total_data = 0
    for idx, api in enumerate(api_data['data']):
        for jdx, list in enumerate(api['list']):
            identity = datas['data'][idx]['list'][jdx].get('identity_number')
            wagon = datas['data'][idx].get('wagon')
            column = datas['data'][idx]['list'][jdx].get('column')
            row = datas['data'][idx]['list'][jdx].get('row')
            train_passenger = TrainPassanger.objects.get_or_none(
                passanger__identity_number=str(identity),
                train_transaction=train_transaction,
                wagon=wagon,
                row=row,
                column=column
            )
            if not train_passenger:
                changes_data += 1
            total_data += 1

    if changes_data and total_data != changes_data:
        return None, "Anda harus mengubah semua tempat duduk yang anda pesan"

    if changes_data == 0:
        return {
            "customer_id": datas['customer_id'],
            "reference_number": datas['reference_number'],
        }, None

    api_response, error = SepulsaLoanService().inquire_train_change_seats(api_data)
    if error or api_response['response_code'] in SepulsaResponseCodes.TRAIN_TICKET_ERROR_RESPONSE:
        action = 'juloserver.payment_point.service.train_related.train_ticket_change_passenger_seat'
        logger.info({
            'action': action,
            'request': api_data,
            'api_response': api_response,
            'error_message': error,
        })
        return api_response, error

    if not train_transaction:
        return None, "Train transaction not found"

    for idx, api in enumerate(datas['data']):
        for jdx, list in enumerate(api['list']):
            identity = datas['data'][idx]['list'][jdx].get('identity_number')
            wagon = datas['data'][idx].get('wagon')
            column = datas['data'][idx]['list'][jdx].get('column')
            row = datas['data'][idx]['list'][jdx].get('row')
            if identity:
                train_passenger = TrainPassanger.objects.get_or_none(
                    passanger__identity_number=str(identity), train_transaction=train_transaction
                )
                if train_passenger:
                    train_passenger.row = row
                    train_passenger.column = column
                    train_passenger.wagon = wagon
                    train_passenger.save()

    return {
        "customer_id": api_response['customer_id'],
        "reference_number": api_response['reference_number'],
    }, None


def get_train_transaction_history(customer):
    train_transactions = TrainTransaction.objects.filter(
        customer=customer, sepulsa_transaction__isnull=False
    ).order_by("-id")

    if not train_transactions:
        return None, "Train transaction not found"

    train_transaction_list = []
    for train_transaction in train_transactions:
        loan = train_transaction.sepulsa_transaction.loan
        train_transaction_list.append(
            {
                'transaction_status': get_transaction_status(train_transaction),
                'booking_code': train_transaction.booking_code,
                'loan_xid': loan.loan_xid,
                'is_round_trip': train_transaction.is_round_trip,
                'depart_station': "{} ({})".format(
                    train_transaction.depart_station.name,
                    train_transaction.depart_station.code,
                ),
                'destination_station': "{} ({})".format(
                    train_transaction.destination_station.name,
                    train_transaction.destination_station.code,
                ),
                'departure_datetime': timezone.localtime(train_transaction.departure_datetime),
                'total_passenger': {
                    'adult': train_transaction.adult,
                    'infant': train_transaction.infant,
                },
            }
        )

    return train_transaction_list, None


def get_train_ticket_whitelist_feature():
    return get_transaction_method_whitelist_feature(TransactionMethodCode.TRAIN_TICKET.name)


def is_train_ticket_whitelist_user(application_id, feature_setting=None):
    feature_setting = feature_setting or get_train_ticket_whitelist_feature()
    if not feature_setting:
        return True

    parameters = feature_setting.parameters.get(TransactionMethodCode.TRAIN_TICKET.name, {})
    return application_id in parameters.get('application_ids', [])


def train_ticket_limit_validation(customer, sepulsa_product, data):
    account = customer.account
    account_limit = AccountLimit.objects.filter(account=account).last()
    application = account.get_active_application()
    if 'data' in data and type(data['data']) == OrderedDict:
        data['data'] = json.loads(json.dumps(data['data']))
    total_price = data['data'].get('total_price')
    transaction_type = None
    (
        credit_matrix,
        credit_matrix_product_line,
    ) = get_credit_matrix_and_credit_matrix_product_line(application, True, None, transaction_type)

    if credit_matrix:
        if not credit_matrix.product:
            return ErrorMessage.NOT_ELIGIBLE_FOR_THE_TRANSACTION
        provision_fee = account_limit.available_limit * credit_matrix.product.origination_fee_pct
        product_admin_fee = sepulsa_product.admin_fee or SepulsaAdminFee.TRAINT_ICKET
        total_min = total_price + product_admin_fee + provision_fee
        if account_limit.available_limit < total_min:
            return ErrorMessage.AVAILABLE_LIMIT

        return None


def get_train_transaction_booking_info(loan_xid=None, booking_code=None, user_id=None):
    if loan_xid:
        loan = Loan.objects.get_or_none(loan_xid=loan_xid)
        if not loan:
            return None, "Loan not found"

        train_transaction = TrainTransaction.objects.filter(sepulsa_transaction__loan=loan).first()
        if not train_transaction:
            return None, "Train transaction not found"
    else:
        train_transaction = TrainTransaction.objects.filter(booking_code=booking_code).first()
        if not train_transaction:
            return None, "Train transaction not found"

    if user_id != train_transaction.customer.user_id:
        # user can only access their own ticket
        return None, "Train transaction not found"

    depart_station = train_transaction.depart_station
    destination_station = train_transaction.destination_station
    sepulsa_transaction = train_transaction.sepulsa_transaction
    loan = sepulsa_transaction.loan
    document = Document.objects.filter(document_source=loan.id, document_type='train_ticket').last()
    passengers = get_passanger_seat(train_transaction)
    transaction_status = get_transaction_status(train_transaction)
    booking_code = ''
    if transaction_status == TrainTicketStatus.DONE:
        booking_code = train_transaction.booking_code

    res = {
        "status": transaction_status,
        "booking_code": booking_code,
        "eticket_link": document.document_url if document else None,
        "schedule": {
            "departure_datetime": format_datetime(
                timezone.localtime(train_transaction.departure_datetime),
                'YYYY-MM-dd HH:mm',
                locale='id_ID',
            ),
            "arrival_datetime": format_datetime(
                timezone.localtime(train_transaction.arrival_datetime),
                'YYYY-MM-dd HH:mm',
                locale='id_ID',
            ),
            "duration": get_train_duration(train_transaction.duration),
            "transportation": {
                "name": train_transaction.train_name,
                "class": train_transaction.train_class,
                "subclass": train_transaction.train_subclass,
            },
            "station": {
                "depart": {
                    "city": depart_station.city,
                    "station_code": depart_station.code,
                    "station_name": depart_station.name,
                },
                "destination": {
                    "city": destination_station.city,
                    "station_code": destination_station.code,
                    "station_name": destination_station.name,
                },
            },
        },
        "passenger": sorted(passengers, key=lambda d: d['number']),
    }

    return res, None


def get_transaction_status(train_transaction):
    if train_transaction.sepulsa_transaction:
        sepulsa_transaction = train_transaction.sepulsa_transaction
        loan = sepulsa_transaction.loan
        if loan.status in LoanStatusCodes.train_ticket_pending_status():
            return TrainTicketStatus.PENDING

        if loan.status in LoanStatusCodes.train_ticket_cancel_status():
            return TrainTicketStatus.CANCELED

        if loan.status in LoanStatusCodes.train_ticket_failed_status():
            return TrainTicketStatus.FAILED

        if loan.status >= LoanStatusCodes.CURRENT:
            return TrainTicketStatus.DONE

    return ''
