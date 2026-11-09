FROM python:latest
ADD https://example.com/install.sh /tmp/install.sh
COPY .env /app/.env
COPY web /app
RUN pip install -r /app/requirements.txt
CMD ["python", "/app/app.py"]
