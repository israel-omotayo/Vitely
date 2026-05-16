web: gunicorn vitely.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --threads 2 --timeout 60
release: python manage.py migrate --no-input && python manage.py collectstatic --no-input