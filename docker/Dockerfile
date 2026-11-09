FROM python:3.13-alpine

ARG PYTHON_PACKAGE=dummy
ARG APP_VERSION=0.0.1
ARG WHEEL_FILE=${PYTHON_PACKAGE}-${APP_VERSION}-py3-none-any.whl

ENV GID=1000 \
    UID=1000 \
    IMAGE_USER=nonroot \
    XDG_CONFIG_HOME=/data \
    LOG_LEVEL=INFO \
    LOG_COLORS=false \
    CINEFLOW_WEB_HOST=0.0.0.0 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN addgroup -S -g $GID $IMAGE_USER && \
    adduser -S -G $IMAGE_USER -u $UID $IMAGE_USER && \
    mkdir -p /usr/src/$IMAGE_USER $XDG_CONFIG_HOME && \
    chown -R $IMAGE_USER:$IMAGE_USER $XDG_CONFIG_HOME

WORKDIR /tmp

COPY dist/$WHEEL_FILE ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --force-reinstall $WHEEL_FILE

# everything CineFlow keeps is in /data/cineflow: config, library, cache and debug files;
# EXPORT_DIRECTORY moves the library elsewhere, e.g. to a mounted media share
VOLUME ["$XDG_CONFIG_HOME"]
# the web GUI listens only when CINEFLOW_WEB_PORT is set, e.g. 8080;
# it also needs CINEFLOW_AUTH (password, oidc, header, or none behind an authenticating proxy)
EXPOSE 8080

USER $IMAGE_USER
ENTRYPOINT ["cineflow"]
