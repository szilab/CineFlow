FROM python:3.13-alpine3.20

ARG APP_NAME=cineflow

ENV GID=1000 UID=1000 DATA_DIR=/data LIBRARY_DIR=/data/library

RUN addgroup -S -g $GID pythonapp && \
    adduser -S -G pythonapp -u $UID pythonapp && \
    mkdir -p /usr/src/$APP_NAME /data

WORKDIR /usr/src/$APP_NAME

COPY . /usr/src/$APP_NAME

RUN pip install --no-cache-dir -r requirements.txt

USER pythonapp

ENTRYPOINT ["python", "-u", "main.py"]
