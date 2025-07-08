import csv

from django.core.management.base import BaseCommand

from juloserver.face_recognition.models import FaceCollection, IndexedFace
from juloserver.julo.models import Application, Customer, Image


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            '-m', '--Mock', action='store_true', help='mocking retroload ' 'on indexed_face table'
        )
        parser.add_argument('-f', '--File', help='retroload certain files')

    def handle(self, *args, **options):
        argument = options['Mock']
        file = options['File']

        self.stdout.write(
            '======================================START INSERTING DATA'
            '========================================'
        )
        filename = 'indexed_faces.csv'
        if file:
            filename = file
        path_data_file = '../../new_indexed_face_data/' + filename
        self.stdout.write('retroload ' + filename)

        image = Image.objects.filter(image_type='crop_selfie').first()
        application = Application.objects.get_or_none(pk=image.image_source)
        customer = Customer.objects.get_or_none(pk=application.customer_id)

        troubled_insertion = []

        with open(path_data_file, "r") as matrix_file:
            reader = csv.DictReader(matrix_file)
            fail_counter = 0
            counter = 0
            for line in reader:
                if argument:
                    if counter == 1000:
                        break
                face_collection = FaceCollection.objects.filter(
                    face_collection_name='face_collection_x105'
                ).last()
                if not argument:
                    if isinstance(line['julo_image_id'], int):
                        image_id = int(line['julo_image_id'])
                    else:
                        float_image = float(line['julo_image_id'])
                        image_id = int(float_image)

                    image = Image.objects.get_or_none(pk=image_id)

                    if isinstance(line['application_id'], int):
                        application_id = int(line['application_id'])
                    else:
                        float_application = float(line['application_id'])
                        application_id = int(float_application)

                    application = Application.objects.get_or_none(pk=application_id)

                    if isinstance(line['customer_id'], int):
                        customer_id = int(line['customer_id'])
                    else:
                        float_customer = float(line['customer_id'])
                        customer_id = int(float_customer)

                    customer = Customer.objects.get_or_none(pk=customer_id)
                if face_collection and image and application and customer:
                    try:
                        indexed_face = IndexedFace.objects.filter(image=image).last()

                        if not indexed_face:
                            IndexedFace.objects.create(
                                face_collection=face_collection,
                                image=image,
                                application=application,
                                customer=customer,
                                collection_face_id=line['collection_face_id'],
                                collection_image_id=line['collection_image_id'],
                                collection_image_url=line['collection_image_url'],
                                match_status=line['match_status'],
                                application_status_code=line['application_status_code'],
                                latency=line['latency'],
                            )

                        counter += 1
                        self.stdout.write(
                            self.style.SUCCESS(
                                'Successfully retroloaded '
                                + str(counter)
                                + ' image(s) into `indexed_face`'
                            )
                        )
                    except Exception as e:
                        fail_counter += 1
                        troubled_insertion.append(image.id)
                        self.stdout.write(
                            self.style.ERROR(
                                'Failed retroloaded '
                                + str(fail_counter)
                                + ' image(s) into `indexed_face` '
                                'with this error: ' + self.style.ERROR(str(e))
                            )
                        )
                else:
                    fail_counter += 1
                    self.stdout.write(
                        self.style.ERROR(
                            'Failed retroloaded '
                            + str(fail_counter)
                            + ' image(s) into `indexed_face`'
                            ' found None on foreign key records.'
                        )
                    )

        self.stdout.write(
            self.style.SUCCESS(
                'Successfully retroloaded '
                + str(counter)
                + ' and failed retroloaded '
                + str(fail_counter)
                + ' image(s) into `indexed_face`'
            )
        )
        self.stdout.write(self.style.ERROR('List of failed insertions: ' + str(troubled_insertion)))
        self.stdout.write(
            '====================================COMPLETE INSERTING DATA'
            '=========================================='
        )
