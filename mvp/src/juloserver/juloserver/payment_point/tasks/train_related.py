from celery import task
from juloserver.payment_point.models import TrainStation


@task(queue="loan_low")
def update_train_stations(station_data):
    bulk_station_data = []
    for station in station_data:
        if not TrainStation.objects.filter(code=station['station_code']).exists():
            bulk_station_data.append(
                TrainStation(
                    code=station['station_code'],
                    city=station['city'],
                    name=station['station_name'],
                )
            )
    TrainStation.objects.bulk_create(bulk_station_data, batch_size=100)
