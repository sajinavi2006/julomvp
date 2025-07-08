import csv

from juloserver.julo.models import Application


def fill_empty_dana_marital_status(csv_file_path):
    counter = 0
    not_found_application = []
    with open(csv_file_path) as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            counter += 1
            application = Application.objects.filter(id=row["application_id"]).only("id").last()
            if not application:
                not_found_application.append(application.id)
                continue

            if row["marital_status"] == "BELUM KAWIN":
                marital_status = "Lajang"
            elif row["marital_status"] == "KAWIN":
                marital_status = "Menikah"
            elif row["marital_status"] == "CERAI HIDUP":
                marital_status = "Cerai"
            else:
                continue

            application.update_safely(marital_status=marital_status)
            print(
                "{} - Application {} successfuly update marital status".format(
                    counter, application.id
                )
            )

    if not_found_application:
        print("------ Not found application ------")
        for app_id in not_found_application:
            print("App {} not found".format(app_id))
