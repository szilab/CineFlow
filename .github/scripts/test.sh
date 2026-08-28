#!/bin/bash

set -e

source "$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )/utils.sh"

print_header "Starting CineFlow Tests"
sync_dev_deps
clean_build

print_header "Running linters..."

if uv run flake8 . --count --max-complexity=10 --max-line-length=120 --statistics --exclude .venv; then
    print_status "Flake8 passed"
else
    print_error "Flake8 failed"
    exit 1
fi

if uv run pylint $(find "./$PYTHON_PACKAGE" -name "*.py") -d="E0401,F0001,C0116" --max-line-length=120 2>/dev/null; then
    print_status "Pylint passed"
else
    print_error "Pylint failed"
    exit 1
fi

print_header "Testing package build..."

if uv build --out-dir .tmp_build_check; then
    print_status "Package build check passed"
else
    print_error "Package build check failed"
    exit 1
fi

print_header "Testing package installation..."

WHEEL_PATH="$(realpath .tmp_build_check/$PYTHON_PACKAGE-$VERSION-py3-none-any.whl)"
WHEEL_TEST_DIRECTORY="$(mktemp -d)"

if (
    cd "$WHEEL_TEST_DIRECTORY"
    uv run --isolated --no-project --with "$WHEEL_PATH" python -c "import $PYTHON_PACKAGE.main; print('Wheel import successful')"
); then
    print_status "Wheel installation and import test passed"
else
    print_error "Wheel installation or import test failed"
    exit 1
fi
rm -rf "$WHEEL_TEST_DIRECTORY"

print_header "Running pytest..."

if [ -d "tests" ]; then
    if uv run pytest tests/ -v --cov="$PYTHON_PACKAGE" --cov-report=term-missing --cov-report=xml:coverage.xml; then
        print_status "Pytest passed"
    else
        print_error "Pytest failed"
        exit 1
    fi
else
    print_warning "No tests directory found, skipping pytest"
fi

rm -rf .tmp_build_check
print_status "All tests completed successfully!"
clean_build
