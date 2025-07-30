FROM python:3.10-alpine3.19

ARG PYTHON_PACKAGE=dummy
ARG APP_VERSION=0.0.1
ARG WHEEL_FILE=${PYTHON_PACKAGE}-${APP_VERSION}-py3-none-any.whl

ENV GID=1000 \
    UID=1000 \
    IMAGE_USER=nonroot \
    EXPORT_DIRECTORY=/library \
    CFG_DIRECTORY=/config \
    EXAMPLES_DIRECTORY=/tmp/examples \
    LOG_LEVEL=INFO \
    LOG_COLORS=false \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN addgroup -S -g $GID $IMAGE_USER && \
    adduser -S -G $IMAGE_USER -u $UID $IMAGE_USER && \
    mkdir -p /usr/src/$IMAGE_USER $EXPORT_DIRECTORY $CFG_DIRECTORY && \
    chown -R $IMAGE_USER:$IMAGE_USER $EXPORT_DIRECTORY $CFG_DIRECTORY

RUN apk add --no-cache \
    gcc \
    musl-dev \
    linux-headers \
    ca-certificates

WORKDIR /tmp

COPY dist/$WHEEL_FILE ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --force-reinstall $WHEEL_FILE[all]

COPY docker/examples/*.* $EXAMPLES_DIRECTORY/

VOLUME ["$CFG_DIRECTORY", "$EXPORT_DIRECTORY"]

COPY docker/entrypoint.sh /bin/entrypoint.sh
RUN chmod +x /bin/entrypoint.sh

USER $IMAGE_USER
ENTRYPOINT ["/bin/entrypoint.sh"]
