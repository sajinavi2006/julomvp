from django.db import transaction
from datetime import datetime, timedelta
from juloserver.minisquad.models import (
    KangtauUploadedCustomerList,
    AIRudderPayloadTemp,
)
from juloserver.julo.models import FeatureSetting
from juloserver.minisquad.clients import get_julo_kangtau_client
from juloserver.minisquad.constants import (
    KangtauBucketWhitelist,
    FeatureNameConst,
)
from juloserver.minisquad.services2.kangtau import KangtauService
from juloserver.minisquad.utils import chunked
from celery import task
import math
import logging
from django.utils.timezone import make_aware
import time


logger = logging.getLogger(__name__)



@task(bind=True, queue='collection_normal')
def upload_customer_list(self):
    """
    Celery task to upload customer data to Kangtau.
    """
    start_time = time.time()
    # 1. Prepare bucket lists and quotas
    buckets = {
        "B0": KangtauBucketWhitelist.B0_LIST,
        "B1": KangtauBucketWhitelist.B1_LIST,
        "B2": KangtauBucketWhitelist.B2_LIST,
        "B3": KangtauBucketWhitelist.B3_LIST,
        "B4": KangtauBucketWhitelist.B4_LIST,
        "B5": KangtauBucketWhitelist.B5_LIST,
    }
    today = datetime.now().date()
    start_of_day = make_aware(datetime.combine(today, datetime.min.time()))
    end_of_day = start_of_day + timedelta(days=1)

    # Fetch bucket quotas
    bucket_quota_config = FeatureSetting.objects.get(
        feature_name=FeatureNameConst.KANGTAU_CUSTOMER_BUCKET_QUOTA
    ).parameters
    bucket_quotas = {k: v for bucket in bucket_quota_config['buckets'] for k, v in bucket.items()}

    # 2. Gather stats per bucket
    stats = {}
    for group_bucket_name, whitelist in buckets.items():
        qs_customer_records = []  # Start with an empty list for each bucket

        if group_bucket_name == 'B0':
            from juloserver.cootek.services import get_j1_account_payment_for_cootek

            filter_dict = dict(due_date=today)
            qs = get_j1_account_payment_for_cootek(filter_dict).exclude(due_amount=0)
            qs_customer_records.extend(list(qs))
        else:
            qs = (
                AIRudderPayloadTemp.objects.filter(
                    bucket_name__in=whitelist,
                    cdate__gte=start_of_day,
                    cdate__lt=end_of_day,
                )
                .order_by('account_id', '-total_due_amount')
                .distinct('account_id')
            )
            qs_customer_records.extend(list(qs))

        total = len(qs_customer_records)
        quota = bucket_quotas.get(group_bucket_name, 0)
        stats[group_bucket_name] = {
            'qs_customer_records': qs_customer_records,
            'total': total,
            'quota': quota,
        }

    # 3. Initial allocation
    initial_alloc = {}
    surplus_buckets = []  # buckets with more customer than quota
    under_quota_buckets = []  # buckets with fewer customer than quota
    for name, data in stats.items():
        alloc = min(data['total'], data['quota'])
        initial_alloc[name] = alloc
        if data['total'] > data['quota']:
            surplus_buckets.append(name)
        elif data['total'] < data['quota']:
            under_quota_buckets.append(name)

    # 4. Redistribute excess
    total_excess = sum(stats[d]['total'] - stats[d]['quota'] for d in surplus_buckets)
    num_def = len(under_quota_buckets)
    extra_per = math.floor(total_excess / num_def) if num_def and total_excess > 0 else 0
    remainder = total_excess - extra_per * num_def

    final_alloc = initial_alloc.copy()
    for idx, name in enumerate(under_quota_buckets):
        need = stats[name]['quota'] - stats[name]['total']
        add = min(need, extra_per + (1 if idx < remainder else 0))
        final_alloc[name] += add

    # 5. Process each bucket: upload and persist
    client = get_julo_kangtau_client()
    db_batch = 1000
    api_batch = 500  # Kangtau API limit per request

    errors = []  # List to collect errors
    bucket_info = {}  # Track uploaded count per bucket

    errors = []  # List to collect errors

    for bucket_name, data in stats.items():
        bucket_start_time = time.time()
        limit = final_alloc[bucket_name]
        if limit == 0:
            continue

        # Fail safe mechanism, if failed sending to Kangtau, skip this bucket
        try:
            # Check for existing customer form
            existing_form_name = KangtauService.create_customer_form_name(bucket_name)
            existing_form = KangtauService.get_customer_form_list(
                page=1, search_key=existing_form_name, take=1
            )

            form_id = None
            form_name = None

            # If customer form exists, use the first one
            if (
                existing_form
                and existing_form.get('totalData', 0) > 0
                and existing_form.get('data')
            ):
                form_id = existing_form['data'][0]['id']
                form_name = existing_form['data'][0]['name']
                logger.info(
                    "Using existing customer form for bucket %s: %s (%s)",
                    bucket_name,
                    form_name,
                    form_id,
                )
            else:
                # Create new customer form if none exists
                form = KangtauService.create_customer_form(self, bucket_name=bucket_name)
                form_id = form['customerForm']['id']
                form_name = form['customerForm']['name']
                logger.info(
                    "Created new customer form for bucket %s: %s (%s)",
                    bucket_name,
                    form_name,
                    form_id,
                )

            records = list(data['qs_customer_records'][:limit])

            # Upload via API in batches of 1000 and store successfully uploaded records
            successfully_uploaded_records = []
            total_uploaded = 0

            for batch_start in range(0, len(records), api_batch):
                batch_end = min(batch_start + api_batch, len(records))
                batch_records = records[batch_start:batch_end]

                try:
                    payload = []
                    if bucket_name == 'B0':
                        serialized_record = [
                            KangtauService.serialize_customer_list_record_t0(r)
                            for r in batch_records
                        ]
                        payload.extend(serialized_record)
                    else:
                        serialized_record = [
                            KangtauService.serialize_customer_list_record(r) for r in batch_records
                        ]
                        payload.extend(serialized_record)

                    KangtauService.upload_customer_list(
                        client, form_id, payload, self.request.id, bucket_name
                    )

                    # If API upload successful, add to successfully uploaded records
                    successfully_uploaded_records.extend(batch_records)
                    total_uploaded += len(batch_records)

                    logger.info(
                        "Successfully uploaded batch %d-%d (%d records) for bucket %s",
                        batch_start + 1,
                        batch_end,
                        len(batch_records),
                        bucket_name,
                    )
                except Exception as batch_exc:
                    logger.error(
                        "Failed to upload batch %d-%d for bucket %s: %s",
                        batch_start + 1,
                        batch_end,
                        bucket_name,
                        str(batch_exc),
                    )
                    errors.append(
                        f"Bucket {bucket_name} batch {batch_start + 1}-{batch_end} failed: {str(batch_exc)}"
                    )
                    # Continue with next batch instead of skipping entire bucket
                    continue

                # Add delay to avoid hitting API rate limits
                time.sleep(5)

            logger.info(
                "Completed API upload for bucket %s: %d/%d records uploaded successfully",
                bucket_name,
                total_uploaded,
                len(records),
            )

            # Calculate bucket processing duration
            bucket_duration = time.time() - bucket_start_time

            # Store bucket info for return data
            bucket_info[bucket_name] = {
                'uploaded_count': total_uploaded,
                'total_records': len(records),
                'success_rate': f"{(total_uploaded/len(records)*100):.1f}%"
                if len(records) > 0
                else "0%",
                'duration_seconds': round(bucket_duration, 2),
                'form_name': form_name,
            }

            # Store to database only successfully uploaded records
            if successfully_uploaded_records:
                objs = [
                    KangtauService.build_uploaded_object(r, form_id, form_name, bucket_name)
                    for r in successfully_uploaded_records
                ]

                # Store to database in batches
                for db_batch_start in range(0, len(objs), db_batch):
                    db_batch_end = min(db_batch_start + db_batch, len(objs))
                    batch_objs = objs[db_batch_start:db_batch_end]

                    try:
                        with transaction.atomic():
                            KangtauUploadedCustomerList.objects.bulk_create(batch_objs)
                    except Exception as db_exc:
                        logger.error(
                            "Failed to save database batch %d-%d for bucket %s: %s",
                            db_batch_start + 1,
                            db_batch_end,
                            bucket_name,
                            str(db_exc),
                        )
                        errors.append(
                            f"Bucket {bucket_name} database batch {db_batch_start + 1}-{db_batch_end} failed: {str(db_exc)}"
                        )

        except Exception as exc:
            logger.error("Bucket %s processing failed: %s", bucket_name, exc)
            errors.append(f"Bucket {bucket_name} failed: {str(exc)}")

            # Calculate bucket processing duration even for failed buckets
            bucket_duration = time.time() - bucket_start_time

            # Track failed bucket
            bucket_info[bucket_name] = {
                'uploaded_count': 0,
                'total_records': 0,
                'success_rate': "0%",
                'duration_seconds': round(bucket_duration, 2),
            }
            continue  # Skip to next bucket

    # Calculate total duration
    total_duration = time.time() - start_time

    logger.info('Upload customer data task completed. Errors: %s', errors)
    logger.info('Final allocation: %s', final_alloc)
    logger.info(
        'Total successfully uploaded records: %d',
        sum(info['uploaded_count'] for info in bucket_info.values()),
    )
    logger.info('Total processing duration: %.2f seconds', total_duration)
    logger.info('Bucket upload info: %s', bucket_info)

    return {
        'status': 'completed',
        'processed': sum(final_alloc.values()),
        'successfully_uploaded': sum(info['uploaded_count'] for info in bucket_info.values()),
        'duration_seconds': round(total_duration, 2),
        'errors': errors,
        'info': bucket_info,
    }
