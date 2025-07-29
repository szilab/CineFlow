#!/bin/bash

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
source "$SCRIPT_DIR/utils.sh"

print_header "🧪 Starting CineFlow Tests"

ensure_project_root
install_dev_deps
install_base_deps


echo ""
echo "🔍 Running linters..."
echo "===================="

echo "Running flake8..."
if flake8 . --count --max-complexity=10 --max-line-length=120 --statistics --exclude .venv; then
    print_status "Flake8 passed"
else
    print_error "Flake8 failed"
    exit 1
fi

echo ""
echo "Running pylint..."
if pylint $(find "./$PYTHON_PACKAGE" -name "*.py") -d="E0401,F0001,C0116" --max-line-length=120 2>/dev/null; then
    print_status "Pylint passed"
else
    print_error "Pylint failed"
    exit 1
fi


echo ""
echo "🔧 Testing setup.py..."
echo "====================="

if python setup.py check --metadata --strict; then
    print_status "Setup.py metadata check passed"
else
    print_error "Setup.py metadata check failed"
    exit 1
fi

if python setup.py sdist bdist_wheel --dry-run; then
    print_status "Setup.py dry-run build passed"
else
    print_error "Setup.py dry-run build failed"
    exit 1
fi


echo ""
echo "📦 Testing package installation..."
echo "================================="

if pip install -e .; then
    print_status "Package installation successful"
else
    print_error "Package installation failed"
    exit 1
fi

echo "Testing imports..."
if python -c "import $PYTHON_PACKAGE.main; print('Main module imported successfully')"; then
    print_status "Import test passed"
else
    print_error "Import test failed"
    exit 1
fi


echo ""
echo "🧪 Running pytest..."
echo "==================="

if [ -d "tests" ]; then
    if pytest tests/ -v --cov=. --cov-report=xml --cov-report=term; then
        print_status "Pytest passed"
    else
        print_error "Pytest failed"
        exit 1
    fi
else
    print_warning "No tests directory found, skipping pytest"
fi

clean_build

echo ""
print_status "All tests completed successfully! 🎉"