# Contributing to CineFlow

Thank you for your interest in contributing to CineFlow! This guide will help you get started with development and contributing to the project.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Development Workflow](#development-workflow)
- [Coding Standards](#coding-standards)
- [Testing](#testing)
- [Building and Packaging](#building-and-packaging)
- [Pull Request Process](#pull-request-process)
- [Issue Reporting](#issue-reporting)
- [Community](#community)

## Code of Conduct

This project adheres to a code of conduct. By participating, you are expected to uphold this code. Please be respectful and constructive in all interactions.

## Getting Started

### Prerequisites

- **Python 3.10+** - Required for development
- **Git** - Version control
- **Docker** (optional) - For containerized development and testing
- **Your favorite IDE** - VS Code, PyCharm, etc.

### Fork and Clone

1. Fork the repository on GitHub
2. Clone your fork locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/CineFlow.git
   cd CineFlow
   ```

3. Add the upstream repository:
   ```bash
   git remote add upstream https://github.com/szilab/CineFlow.git
   ```

## Development Setup

### 1. Create Virtual Environment

```bash
# Create virtual environment
python -m venv .cflow

# Activate it (Linux/Mac)
source .cflow/bin/activate

# Activate it (Windows)
.cflow\Scripts\activate
```

### 2. Install Development Dependencies

```bash
# Install the package in editable mode with all dependencies
pip install -e .
```

### 4. Set Up Configuration

Create a test configuration file for development:

```bash
# Create config directory
mkdir -p test-config

# Create minimal config.yaml for testing
cat > test-config/config.yaml << EOF
tmdb:
  token: "your_test_token_here"
  lang: "en-US"

jackett:
  url: "http://localhost:9117"
  token: "your_test_token"

jellyfin:
  url: "http://localhost:8096"
  token: "your_test_token"

transmission:
  url: "http://localhost:9091"
EOF
```

## Development Workflow

### Branch Strategy

- `main` - Production ready code
- `develop` - Development branch for features
- `feature/feature-name` - Feature branches
- `fix/bug-description` - Fix branches

### Working on Features

1. **Sync with upstream**:
   ```bash
   git checkout develop
   git pull upstream develop
   ```

2. **Create feature branch**:
   ```bash
   git checkout -b feature/your-feature-name
   ```

3. **Make your changes**:
   - Write code following our [coding standards](#coding-standards)
   - Add tests for new functionality
   - Update documentation if needed

4. **Test your changes**:
   ```bash
   # Run tests
   python -m pytest

   # Test CLI functionality
   CFG_DIRECTORY=test-config LOG_LEVEL=DEBUG cineflow
   ```

5. **Commit your changes**:
   ```bash
   git add .
   git commit -m "feat: add new feature description"
   ```

6. **Push and create PR**:
   ```bash
   git push origin feature/your-feature-name
   ```

## Coding Standards

### Python Style

- Follow **PEP 8** style guidelines
- Use **type hints** where possible
- Maximum line length: **120 characters** (Black formatter standard)
- Use **docstrings** for all public functions and classes except properties

### Naming Conventions

- **Classes**: `PascalCase` (e.g., `MediaManager`)
- **Functions/Variables**: `snake_case` (e.g., `get_movie_info`)
- **Constants**: `UPPER_CASE` (e.g., `DEFAULT_TIMEOUT`)
- **Private methods and class properties**: `_leading_underscore` (e.g., `_internal_method`)

## Testing

### Running Tests

Run provided script: `.github/scripts/test.sh`

### Writing Tests

- Place tests in the `tests/` directory
- Use `pytest` framework
- Mock external API calls
- Test both success and failure cases

Example test:
```python
def test_tmdb_search():
    """Test TMDb movie search functionality."""
    tmdb = TMDb(token="test_token")

    with patch('requests.get') as mock_get:
        mock_get.return_value.json.return_value = {
            'results': [{'id': 123, 'title': 'Test Movie'}]
        }

        results = tmdb.search_movie("Test Movie")
        assert len(results) == 1
        assert results[0]['title'] == 'Test Movie'
```

## Building and Packaging

### Build Python Package

Run the provided script: `.github/scripts/python-build.sh`

### Build Docker Image

Run the provided script: `.github/scripts/docker-build.sh`

## Pull Request Process

### Before Submitting

1. **Sync with upstream**:
   ```bash
   git checkout develop
   git pull upstream develop
   git checkout your-branch
   git rebase develop
   ```

2. **Run all test**:

3. **Update documentation** if needed

## Issue Reporting

### Bug Reports

Use the bug report template and include:
- **Environment**: OS, Python version, CineFlow version
- **Steps to reproduce**
- **Expected vs actual behavior**
- **Error messages/logs**
- **Configuration** (sanitized)

### Feature Requests

- **Use case**: Describe the problem this solves
- **Proposed solution**: How should it work?
- **Alternatives**: What other solutions did you consider?

## Community

### Getting Help

- 💬 [GitHub Discussions](https://github.com/szilab/CineFlow/discussions) - General questions
- 🐛 [GitHub Issues](https://github.com/szilab/CineFlow/issues) - Bug reports
- 📚 [Wiki](https://github.com/szilab/CineFlow/wiki) - Documentation

### Communication

- Be respectful and constructive
- Use clear, descriptive titles for issues
- Provide context and examples
- Be patient - maintainers are volunteers

### Common Issues

- **Import errors**: Make sure you installed with `pip install -e .`
- **Config not found**: Set `CFG_DIRECTORY` environment variable
- **API timeouts**: Check network connectivity and API credentials

Thank you for contributing to CineFlow! 🎬