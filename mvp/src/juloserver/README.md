# juloserver
The application server that talks to the DB and provides RESTful API.

It uses django as its web framework, stores data in PostgreSQL, and runs
asynchronous tasks with celery and RabbitMQ as its message broker.

## Prerequisites

For running stuff locally:
* Having Python3.7 installed (recommended to use [pyenv]())
* Being able to create Python virtual environment. See [virtualenv]()
* install libpq-dev, python-dev, libjpeg8-dev

If using docker, make sure [docker](https://docs.docker.com/engine/installation/#installation) installed.


## Running the server locally

There are two methods:
* method 1: Entirely using Docker containers
* method 2: Django & celery on the host using virtualenv but DB & message broker
  on Docker containers

### Method 1

1. Run specific `docker compose` command for running server from the root directory of this repo.
    * Make sure docker engine is running on your laptop

    ```
    cd ../..
   
    pip install pre-commit==2.20.0
    pre-commit install -t prepare-commit-msg 
   
    docker compose -f docker-compose.yml up --build
    ```

### Method 2

1. Create a `virtualenv` using Python3.7:
    * The version of python is important, please make sure the virtualenv is created with Python3.7
    * You may use [pyenv](https://github.com/pyenv/pyenv)
      and its plugin [pyenv-virtualenv](https://github.com/pyenv/pyenv-virtualenv).
    * See example commands below:

    ```
    # creating the virtualenv
    pyenv virtualenv 2.7.16 mvp-2716-25022020ve
    
    # activating the virtualenv
    pyenv activate mvp-2716-25022020ve
    
    # checking that virtualenv is activated
    pyenv version
    ```

2. Install the dependencies needed on the activated virtualenv. In this directory, run:

    ```
    pip install -r requirements/python3/requirements_local.txt
    ```

3. On a separate shell, run the DB and message broker using docker-compose from
   the root directory of this repo.
    * Make sure this is running while the tests are run.

    ```
    cd ../..
    docker-compose -f docker-compose.db_broker_only.yml up -d
    ```

4. Create the database tables and initial data on your previous shell
   with the virtualenv activated.

    ```
    # Load all the environment variables needed for local server
    source ./postactivate
   
   # Before migrate, run this script setup_database.sql to set up users & privileges needed first
    
    # Create the database tables and initial data
    python manage.py centralized_migrate
   
    # Create the application's super user
    python manage.py createsuperuser
    ```

5. Run the server with Django entry point command on your previous shell with
   the virtualenv activated.

    ```
    # Load all the environment variables needed for local server
    source ./postactivate
    
    python manage.py runserver
    ```

5. On another separate shell, run celery workers and celerybeat (scheduler)

    ```
    ./run_celery
    ```

## Running unit tests

This is set up similar to running the server locally. The difference is
instead of running Django, [pytest](https://docs.pytest.org/en/latest/) is run.
There are two methods:
* method 1: Entirely using Docker containers
* method 2: On the host using virtualenv but DB & message broker on Docker containers

### Method 1

1. Run specific docker-compose command for running unit tests from
   the root directory of this repo.
    * Make sure docker engine is running on your laptop

    ```
    cd ../..
    docker-compose -f docker-compose.unit_tests.yml up --build
    ```

### Method 2

1. Create a `virtualenv` using Python3.7:
    * The version of python is important, please make sure the virtualenv is created with Python3.7
    * You may use [pyenv](https://github.com/pyenv/pyenv)
      and its plugin [pyenv-virtualenv](https://github.com/pyenv/pyenv-virtualenv).
    * See example commands below:

    ```
    # creating the virtualenv
    pyenv virtualenv 2.7.16 mvp-2716-25022020ve
    
    # activating the virtualenv
    pyenv activate mvp-2716-25022020ve
    
    # checking that virtualenv is activated
    pyenv version
    ```

2. Install the dependencies needed on the activated virtualenv. In this directory, run:

    ```
    pip install -r requirements/python3/requirements_local.txt
    ```

3. On a separate shell, run the DB and message broker using docker-compose from
   the root directory of this repo.
    * Make sure this is running while the tests are run.

    ```
    cd ../..
    docker-compose -f docker-compose.db_broker_only.yml up -d
    ```

4. Run the unit test script on your previous shell with the virtualenv activated.

    ```
    ./run_unit_tests
    ```

    * View the test report by opening unit_test_results.html


## Notes

* If you switch between running the server / unit tests on the host vs. on docker,
  you need to make sure the compiled Python files are cleaned.

    ```
    find . -name '*.pyc' -delete
    ```

## Tools

* The coding style follows [Django coding style](https://docs.djangoproject.com/en/1.10/internals/contributing/writing-code/coding-style/).
* It is based on PEP8 and enforced using [`flake8`](http://flake8.pycqa.org/en/latest/).
* `flake8` is run like tests, through [`tox`](https://tox.readthedocs.io/en/latest/).
    ```
    $ tox -e flake8 -- juloserver/<my_file>.py
    ```
## Update Models

after updating models use this script to create migrations and apply changes to the database
```
python manage.py centralized_makemigrations
python manage.py centralized_migrate
```
