#!/bin/bash

# install dependencies
pip install setuptools
pip install -r requirements.txt

# Run django commnads
python manage.py makemigrations
python manage.py migrate
python manage.py collectstatic --noinput
