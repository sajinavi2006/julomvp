FROM python:3.7-slim as base

####Stage BUILD ####
FROM base as builder

RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install openssh-client -y

RUN mkdir -p /root/.ssh &&\
    chmod 0700 /root/.ssh &&\
    ssh-keyscan github.com > /root/.ssh/known_hosts

RUN apt-get install -y --no-install-recommends \
        tzdata \
        python3-setuptools \
        python3-pip \
        python3-dev \
        python3-venv \
        build-essential \
        libssl-dev \
        libffi-dev \
        && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY ./requirements /requirements

RUN pip3 install --upgrade pip && \
    pip3 install --upgrade setuptools wheel && \
    pip3 install -r /requirements/python3/requirements_local.txt

####Stage BUILD RUNNER ####
FROM base as runner

RUN set -ex && \
    mkdir -p /service && \
    apt-get update && apt-get upgrade -y && \
    apt-get install -y \
        netcat-traditional \
        git \
        libsm6 \
        procps \
        libglib2.0-0 \
        libxrender1 \
        libfontconfig1 \
        libmagickwand-dev && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /usr/local/lib /usr/local/lib

EXPOSE 8000

WORKDIR /service

COPY . /service/
