"""Setup configuration for CineFlow package."""

from setuptools import setup, find_packages
import os


# Read the contents of README file
def read_long_description():
    """Read the long description from README.md if it exists."""
    readme_path = os.path.join(os.path.dirname(__file__), 'README.md')
    if os.path.exists(readme_path):
        with open(readme_path, 'r', encoding='utf-8') as f:
            return f.read()
    raise FileNotFoundError(
        "README.md not found. Please create a README.md file in the package root directory."
    )


# Read requirements from requirements.txt if it exists
def read_requirements():
    """Read requirements from requirements.txt if it exists."""
    req_path = os.path.join(os.path.dirname(__file__), 'requirements.txt')
    if os.path.exists(req_path):
        with open(req_path, 'r', encoding='utf-8') as f:
            return [line.strip() for line in f if line.strip() and not line.startswith('#')]
    raise FileNotFoundError(
        "requirements.txt not found. Please create a requirements.txt file in the package root directory."
    )


# Read version from __init__.py or set default
def read_version():
    """Read version from package __init__.py or set default."""
    version_file = os.path.join(os.path.dirname(__file__), 'cineflow', '__init__.py')
    if os.path.exists(version_file):
        with open(version_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('__version__'):
                    return line.split('=')[1].strip().strip('"\'')
    return '1.0.0'


setup(
    # Basic package information
    name='cineflow',
    version=read_version(),
    author='Sandor Szilagyi',
    description='A workflow automation system for media processing',
    long_description=read_long_description(),
    long_description_content_type='text/markdown',
    url='https://github.com/huszilagyisandor/CineFlow',  # Replace with your repo URL
    license='MIT',
    packages=find_packages(exclude=['tests*', 'docs*', 'examples*']),
    py_modules=['main'],
    package_dir={'': '.'},
    # Include non-Python files
    include_package_data=True,
    package_data={
        '': ['*.yaml', '*.yml', '*.txt', '*.md'],
        'cineflow': [
            'config/*.yaml',
            'config/*.yml',
            'flows/*.yaml',
            'flows/*.yml',
        ],
    },
    # Python version requirement
    python_requires='>=3.13',
    # Dependencies
    install_requires=read_requirements(),
    # Console scripts / entry points
    entry_points={
        'console_scripts': [
            'cineflow=main:main',
        ],
    },
    # Zip safe or not
    zip_safe=False,
)
