#!/bin/bash

OUTPUT="$(ls -t1 {{ application_log_dir }}/nginx_access.log-*.gz | head -1)"

/usr/local/bin/aws s3  cp "${OUTPUT}" s3://{{ s3_logs_bucket }}/{{ application_name }}/{{ nginx_server_name }}/
