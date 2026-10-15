release: python canvas_plus/manage.py migrate --noinput
web: gunicorn --chdir canvas_plus canvas_plus.wsgi:application --bind 0.0.0.0:$PORT