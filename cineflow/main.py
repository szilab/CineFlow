"""CineFlow application and command-line entry point."""

import argparse
import json
import os
import signal
import sys
import threading
from collections.abc import Sequence
from cineflow import __version__
from cineflow.core.logger import log
from cineflow.core.config import Config
from cineflow.core.database import Database
from cineflow.core.runner import FlowManager
from cineflow.runtime import bootstrap_configuration
from cineflow.utils.directory import CleanupScheduler


class MainApp:
    """Class to manage the application lifecycle"""

    def __init__(self, web_port: int | None = None):
        """Initialize the application"""
        log("Application started", level="MSG")
        self._components = []
        self._shutdown_event = threading.Event()
        try:
            log("Initialize singleton modules", level="MSG")
            self._components.append(Config())
            self._components.append(Database())
            self._components.append(CleanupScheduler())
            log("Start FlowManager", level="MSG")
            flow_manager = FlowManager()
            self._components.append(flow_manager)
            if web_port is not None:
                from cineflow.web.server import WebServer  # pylint: disable=import-outside-toplevel

                self._components.append(WebServer(port=web_port, flow_manager=flow_manager))
        except Exception as e:
            log(f"Error during initialization: {e}", level="ERROR")
            raise

    def run(self):
        """Run the application"""
        try:
            while not self._shutdown_event.wait(timeout=1):
                pass
        except KeyboardInterrupt:
            log("Application stopped by input", level="INFO")
            self.shutdown()

    def shutdown(self):
        """Shutdown the application gracefully"""
        if self._shutdown_event.is_set():
            return
        self._shutdown_event.set()
        for component in reversed(self._components):
            log(f"Stopping component: {component.__class__.__name__}", level="MSG")
            if hasattr(component, 'stop') and callable(getattr(component, 'stop')):
                component.stop()
        safe_to_close = True
        for component in reversed(self._components):
            if not safe_to_close:
                log(
                    f"Leaving component open after worker shutdown timeout: "
                    f"{component.__class__.__name__}", level="WARNING"
                )
                continue
            if hasattr(component, 'close') and callable(getattr(component, 'close')):
                if component.close() is False:
                    safe_to_close = False
        log("Application shutdown complete", level="INFO")


def _web_port(value: str | None) -> int | None:
    """Return the web GUI port, None when the GUI is disabled."""
    if value in (None, ''):
        return None
    port = int(value)
    if not 0 <= port <= 65535:
        raise ValueError(f"Invalid web port {port}.")
    return port


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line options before runtime initialization."""
    parser = argparse.ArgumentParser(description="CineFlow media automation worker")
    parser.add_argument("--version", action="version", version=f"CineFlow {__version__}")
    parser.add_argument(
        "--web-port", default=os.environ.get("CINEFLOW_WEB_PORT"),
        help="serve the web GUI on this port (default: $CINEFLOW_WEB_PORT, disabled when unset)",
    )
    commands = parser.add_subparsers(dest="command")
    validate = commands.add_parser(
        "validate", help="validate config.yaml and every flow without running anything",
    )
    validate.add_argument("--json", action="store_true", help="print the issues as JSON")
    commands.add_parser(
        "hash-password", help="print a hash for CINEFLOW_AUTH_PASSWORD_HASH (reads the password from stdin)",
    )
    return parser.parse_args(argv)


def hash_password_command() -> int:
    """Ask for a password and print its hash."""
    # pylint: disable=import-outside-toplevel
    import getpass
    from cineflow.web.auth import hash_password

    if sys.stdin.isatty():
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Repeat: "):
            print("The passwords differ.", file=sys.stderr)
            return 1
    else:
        password = sys.stdin.readline().rstrip("\n")
    if len(password) < 8:
        print("Use at least 8 characters.", file=sys.stderr)
        return 1
    print(hash_password(password))
    return 0


def _read_config_file():
    """Read config.yaml for validation without creating it; return (config, issues)."""
    # pylint: disable=import-outside-toplevel
    import yaml
    from cineflow.core import store, validation
    from cineflow.runtime import config_directory

    config_file = config_directory() / store.CONFIG_FILE
    try:
        config = yaml.safe_load(config_file.read_text(encoding='utf-8')) if config_file.is_file() else {}
    except (OSError, yaml.YAMLError) as exc:
        return {}, [validation.error((), f"Cannot read: {exc}", 'yaml')]
    return config or {}, validation.validate_config(config)


def validate_command(as_json: bool = False) -> int:
    """Validate the configuration and flows; return the process exit code."""
    # pylint: disable=import-outside-toplevel
    from cineflow.core import store, validation
    from cineflow.core.schema import has_errors

    config, config_issues = _read_config_file()
    report = {'config.yaml': config_issues}
    config = config if isinstance(config, dict) else {}
    for path in store.flow_files():
        try:
            report[path.name] = validation.validate_flow(store.read_flow(path.stem), config)
        except store.StoreError as exc:
            report[path.name] = [validation.error((), str(exc), 'yaml')]
    if as_json:
        print(json.dumps({name: [issue.to_dict() for issue in issues] for name, issues in report.items()}, indent=2))
    else:
        for name, issues in report.items():
            print(f"{name}: {'FAILED' if has_errors(issues) else 'ok'}")
            for issue in issues:
                print(f"  {issue}")
    return 1 if any(has_errors(issues) for issues in report.values()) else 0


def main(argv: Sequence[str] | None = None):
    """Run the long-lived CineFlow worker, or a one-off command."""
    args = _parse_args(argv)
    if args.command == "validate":
        sys.exit(validate_command(as_json=args.json))
    if args.command == "hash-password":
        sys.exit(hash_password_command())
    try:
        web_port = _web_port(args.web_port)
    except ValueError as exc:
        raise SystemExit(f"Invalid web port: {exc}") from exc
    bootstrap_configuration()
    app = MainApp(web_port=web_port)

    def shutdown(_signum, _frame):
        app.shutdown()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    app.run()


if __name__ == '__main__':
    main()
