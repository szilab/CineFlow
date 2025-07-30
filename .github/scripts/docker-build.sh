#!/bin/bash

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
source "$SCRIPT_DIR/utils.sh"

print_header "🐳 Building Docker Image"

ensure_project_root

VERSION=$(get_version)

# Determine environment and set appropriate tags
if [ -n "$GITHUB_ACTIONS" ]; then
    # Running in GitHub Actions
    REGISTRY="ghcr.io/${GITHUB_REPOSITORY_OWNER,,}"  # Lowercase owner name
    if [ "$GITHUB_REF" = "refs/heads/master" ] || [ "$GITHUB_REF" = "refs/heads/main" ]; then
        # Master/Main branch - production tags
        TAGS="-t $REGISTRY/cineflow:$VERSION -t $REGISTRY/cineflow:latest"
        ENV_INFO="production (master/main branch)"
    elif [ "$GITHUB_REF" = "refs/heads/develop" ]; then
        # Develop branch - development tags
        TAGS="-t $REGISTRY/cineflow:dev-$VERSION"
        ENV_INFO="development (develop branch)"
    else
        # Other branches - branch-specific tags
        BRANCH_NAME=$(echo "$GITHUB_REF" | sed 's/refs\/heads\///')
        TAGS="-t $REGISTRY/cineflow:branch-$BRANCH_NAME-$VERSION"
        ENV_INFO="branch build ($BRANCH_NAME)"
    fi
else
    # Running locally
    TAGS="-t cineflow:local -t cineflow:local-$VERSION"
    ENV_INFO="local development"
fi

print_info "Building CineFlow Docker image version: $VERSION"
print_info "Environment: $ENV_INFO"
print_info "Tags: $(echo $TAGS | sed 's/-t //g')"

if [ ! -d "dist" ] || [ -z "$(ls -A dist/$PYTHON_PACKAGE-$VERSION-py3-none-any.whl 2>/dev/null)" ]; then
    print_warning "No wheel file found. Building first..."
    ./.github/scripts/python-build.sh
    if [ ! -d "dist" ] || [ -z "$(ls -A dist/$PYTHON_PACKAGE-$VERSION-py3-none-any.whl 2>/dev/null)" ]; then
        print_error "Failed to build wheel file. Please check the build script."
        exit 1
    fi
fi

print_info "Using wheel file match to -> dist/$PYTHON_PACKAGE-$VERSION-*-any.whl"
ls dist/$PYTHON_PACKAGE-$VERSION-*-any.whl

# Build Docker image
docker build \
    --no-cache \
    --build-arg APP_VERSION="$VERSION" \
    --build-arg PYTHON_PACKAGE="$PYTHON_PACKAGE" \
    --build-arg WHEEL_FILE="$PYTHON_PACKAGE-$VERSION-py3-none-any.whl" \
    $TAGS \
    -f "docker/Dockerfile" \
    .

print_status "Docker image built successfully!"
print_info "Environment: $ENV_INFO"
print_info "Tags created: $(echo $TAGS | sed 's/-t //g')"
