"""Setup configuration for CineFlow package."""

import os
from setuptools import setup, find_packages

MODULE_NAME = 'cineflow'
PROJECT_NAME = MODULE_NAME.replace('-', '_')
PROJECT_DESC = 'A workflow automation system for media processing'
REPOSITORY_URL = 'https://github.com/szilab/CineFlow'
AUTHOR = 'Sandor Szilagyi'
PYTHON_REQUIRES = '>=3.10'
INSTALL_REQUIRES = [
    'pyyaml>=6.0',
    'requests>=2.32.3',
    'pillow>=11.2.1',
]


def read_version():
    """Read version from package __init__.py or set default."""
    if os.getenv('VERSION', None) is not None:
        return os.getenv('VERSION')
    version_file = os.path.join(os.path.dirname(__file__), 'VERSION')
    if os.path.exists(version_file):
        with open(version_file, "r") as f:
            return f.read().strip()
    return '0.0.1'


def readme():
    try:
        with open('README.md') as f:
            return f.read()
    except FileNotFoundError:
        return f"Cannot find README.md, please visit '{REPOSITORY_URL}' ."


setup(
    # Basic package information
    name=PROJECT_NAME,
    version=read_version(),
    author=AUTHOR,
    description=PROJECT_DESC,
    long_description=readme(),
    long_description_content_type='text/markdown',
    url=REPOSITORY_URL,
    license='MIT',
    packages=find_packages(),
    include_package_data=True,
    package_data={
        '': ['*.yaml', '*.yml', '*.txt', '*.md', '*.json'],
    },
    install_requires=INSTALL_REQUIRES,
    entry_points={
        'console_scripts': [
            'cineflow=cineflow.main:main',
        ],
    },
    zip_safe=False,
)
