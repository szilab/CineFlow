# CineFlow - Media Management System

This project is a media management system that automates the collection, search, and export of media information from various sources. It supports integration with multiple modules such as Jackett, Jellyfin, TMDb, and qBittorrent currentl.

Planned fatures:
    - Support Plex.tv, Transmission and other media sources

## Getting Started

### Prerequisites

- Python 3.x
- Required Python packages: PyYAML, requests, pillow

### Installation

1. Clone the repository:
    ```sh
    git clone https://github.com/huszilagyisandor/CineFlow.git
    cd CineFlow
    ```

2. Install the required packages:
    ```sh
    pip install PyYAML, requests, pillow
    ```

### Configuration

Configure the system by setting environment variables or modifying the `ConfigParams` in `system/config.py`.

### Running the Application

To start the application, run the `main.py` script:
```sh
python3 main.py
```

## Contributing

At the moment this project in the really early phase and still developed by original author only.

## License

This project is licensed under the MIT License.