FROM python:3.8-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN useradd --create-home app
USER app
WORKDIR /home/app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY migrate.py .
COPY config.yml.sample ./config.yml

CMD python3 migrate.py
