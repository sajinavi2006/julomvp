#!/bin/bash

OUTPUT="$(ls -t1 {{ django_path }}/julo_server.log.* | head -1)"

/usr/local/bin/aws s3 cp "${OUTPUT}" s3://{{ s3_logs_bucket }}/{{ application_name }}/{{ inventory_hostname }}/
