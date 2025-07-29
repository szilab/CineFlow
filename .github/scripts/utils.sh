#!/bin/bash

export PYTHON_PACKAGE="cineflow"

export RED='\033[0;31m'
export GREEN='\033[0;32m'
export YELLOW='\033[1;33m'
export BLUE='\033[0;34m'
export NC='\033[0m'

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
    echo -e "${BLUE}$1${NC}"
    echo "$(printf '=%.0s' $(seq 1 ${#1}))"
}

ensure_project_root() {
    local script_dir="$( cd "$( dirname "${BASH_SOURCE[1]}" )" &> /dev/null && pwd )"
    local project_root="$(dirname "$(dirname "$script_dir")")"
    echo "Project root: $project_root"
    if [ ! -f "setup.py" ]; then
        print_error "setup.py not found. Unable to locate project root."
        exit 1
    fi
    print_info "Working in project root: $(pwd)"
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

get_version() {
    if [ -f "VERSION" ]; then
        local version=$(cat VERSION)
        echo "$version"
    else
        print_error "VERSION file not found."
        exit 1
    fi
}

clean_build() {
    rm -rf build/ *.egg-info/
}