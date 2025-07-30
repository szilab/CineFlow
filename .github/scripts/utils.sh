#!/bin/bash

export PYTHON_PACKAGE="cineflow"
export VERSION=$(cat VERSION 2>/dev/null)
export WHEEL_FILE="dist/$PYTHON_PACKAGE-$VERSION-py3-none-any.whl"

export RED='\033[0;31m'
export GREEN='\033[0;32m'
export YELLOW='\033[1;33m'
export BLUE='\033[0;34m'
export NC='\033[0m'


if [ ! -f "setup.py" ]; then
    echo -e "${RED}❌ setup.py not found. Unable to locate project root.${NC}"
    exit 1
fi
echo -e "${BLUE}ℹ️  Working in project root: $(pwd)${NC}"


if [ -z "$VERSION" ]; then
    echo -e "${RED}❌ VERSION file not found or empty. Please create a VERSION file with the version number.${NC}"
    exit 1
fi
echo -e "${BLUE}ℹ️  Using version: $VERSION${NC}"


print_status() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_header() {
    echo ""
    echo -e "$1"
    echo "$(printf '=%.0s' $(seq 1 ${#1}))"
}

install_base_deps() {
    print_info "Installing base dependencies..."
    python -m pip install --upgrade pip
    if [ -f "setup.py" ]; then
        print_status "Installing dependencies from setup.py"
        pip install -e .
    else
        print_error "setup.py not found"
        exit 1
    fi
}

install_dev_deps() {
    print_info "Installing development dependencies..."
    pip install build twine pytest pytest-cov setuptools pylint wheel flake8
}

clean_build() {
    rm -rf build/ *.egg-info/
}
