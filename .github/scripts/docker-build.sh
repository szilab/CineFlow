#!/bin/bash

set -e

source "$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )/utils.sh"

print_header "🐳 Building Docker Image for $VERSION"

if [ ! -f "$WHEEL_FILE" ]; then
    ./.github/scripts/python-build.sh
fi
if [ ! -f "$WHEEL_FILE" ]; then
    print_error "Failed to build wheel file. Please check the build script."
    exit 1
fi

docker build \
    --no-cache \
    --build-arg APP_VERSION="$VERSION" \
    --build-arg PYTHON_PACKAGE="$PYTHON_PACKAGE" \
    --build-arg WHEEL_FILE="$PYTHON_PACKAGE-$VERSION-py3-none-any.whl" \
    -t $PYTHON_PACKAGE:local-$VERSION \
    -f "docker/Dockerfile" \
    .

if [ $? -ne 0 ]; then
    print_error "Docker build failed. Please check the Dockerfile and build context."
    exit 1
fi

print_info "Local docker image '$PYTHON_PACKAGE:local-$VERSION' built successfully!"

if [ -n "$GITHUB_ACTIONS" ]; then
    REGISTRY="ghcr.io/${GITHUB_REPOSITORY_OWNER,,}"
    if [ "$GITHUB_REF" = "refs/heads/master" ] || [ "$GITHUB_REF" = "refs/heads/main" ]; then
        docker tag $PYTHON_PACKAGE:local-$VERSION $REGISTRY/$PYTHON_PACKAGE:$VERSION
        docker push $REGISTRY/$PYTHON_PACKAGE:$VERSION
        print_info "Docker image tagged and pushed to '$REGISTRY/$PYTHON_PACKAGE:$VERSION'"
    elif [ "$GITHUB_REF" = "refs/heads/develop" ]; then
        docker tag $PYTHON_PACKAGE:local-$VERSION $REGISTRY/$PYTHON_PACKAGE:dev-$VERSION
        docker push $REGISTRY/$PYTHON_PACKAGE:dev-$VERSION
        print_info "Docker image tagged and pushed to '$REGISTRY/$PYTHON_PACKAGE:dev-$VERSION'"
    fi
fi
