"""Main"""

from system.logger import log
from system.config import Config
from system.database import Database
from system.runner import FlowManager



def main():
    """Main function"""
    log("Initialize singleton modules", level="MSG")
    Config()
    Database()

    log("Start FlowManager", level="MSG")
    FlowManager()


if __name__ == '__main__':
    main()
