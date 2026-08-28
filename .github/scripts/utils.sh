#!/bin/bash

export PYTHON_PACKAGE="cineflow"
export VERSION=$(cat VERSION 2>/dev/null)
export WHEEL_FILE="dist/$PYTHON_PACKAGE-$VERSION-py3-none-any.whl"

export RED='\033[0;31m'
export GREEN='\033[0;32m'
export YELLOW='\033[1;33m'
export BLUE='\033[0;34m'
export NC='\033[0m'

if [ ! -f "pyproject.toml" ]; then
    echo -e "${RED}pyproject.toml not found. Unable to locate project root.${NC}"
    exit 1
fi
echo -e "${BLUE}Working in project root: $(pwd)${NC}"

if [ -z "$VERSION" ]; then
    echo -e "${RED}VERSION file not found or empty. Please create a VERSION file with the version number.${NC}"
    exit 1
fi
echo -e "${BLUE}Using version: $VERSION${NC}"

print_status() { echo -e "${GREEN}$1${NC}"; }
print_info() { echo -e "${BLUE}$1${NC}"; }
print_warning() { echo -e "${YELLOW}$1${NC}"; }
print_error() { echo -e "${RED}$1${NC}"; }

print_header() {
    echo ""
    echo -e "$1"
    echo "$(printf '=%.0s' $(seq 1 ${#1}))"
}

sync_dev_deps() {
    print_info "Syncing locked development dependencies..."
    uv sync --locked --group dev
}

clean_build() {
    rm -rf build/ *.egg-info/
}
