"""Image transformations and application lifecycle behavior."""

from io import BytesIO
import threading

from PIL import Image

from cineflow.main import MainApp, main
from cineflow.utils.image import ImageHandler


def image_bytes() -> bytes:
    image = Image.new("RGB", (20, 30), "white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_image_handler_loads_transforms_and_saves(tmp_path, monkeypatch) -> None:

    class Response:
        content = image_bytes()

        def raise_for_status(self): pass
    monkeypatch.setattr("cineflow.utils.image.requests.get", lambda *args, **kwargs: Response())
    handler = ImageHandler("https://poster", scale=(60, 90))
    handler.apply("grayscale")
    handler.apply("border", color="blue")
    for position in ("top-left", "top-right", "bottom-left", "bottom-right"):
        handler.apply("triangle", color="green", position=position)
    handler.apply_from_rule({"modification": "none"})
    handler.filename = "poster.png"
    handler.save(str(tmp_path))
    assert (tmp_path / "poster.png").exists()
    assert handler._translate_color("unknown") == "#000000"


def test_image_handler_handles_request_failure_and_invalid_operations(monkeypatch, tmp_path) -> None:
    import requests

    def failing_get(*args, **kwargs):
        raise requests.RequestException()

    monkeypatch.setattr("cineflow.utils.image.requests.get", failing_get)
    handler = ImageHandler("https://broken")
    handler.save(str(tmp_path))
    handler.apply("unknown")
    handler.apply("triangle", position="invalid")
    assert handler._img is None


def test_main_initializes_shuts_down_and_entrypoint(monkeypatch) -> None:
    calls = []

    class Component:
        def __init__(self, name):
            self.name = name

        def close(self):
            calls.append(f"close:{self.name}")

        def stop(self):
            calls.append(f"stop:{self.name}")
    monkeypatch.setattr("cineflow.main.Config", lambda: Component("config"))
    monkeypatch.setattr("cineflow.main.Database", lambda: Component("database"))
    monkeypatch.setattr("cineflow.main.FlowManager", lambda: Component("flow"))
    app = MainApp()
    app.shutdown()
    app.shutdown()
    assert calls == [
        "stop:flow", "stop:database", "stop:config",
        "close:flow", "close:database", "close:config",
    ]

    class SignalApp:
        def run(self):
            calls.append("run")

        def shutdown(self):
            calls.append("signal-shutdown")

    monkeypatch.setattr("cineflow.main.MainApp", SignalApp)
    handlers = {}
    monkeypatch.setattr(
        "cineflow.main.signal.signal", lambda signum, handler: handlers.setdefault(signum, handler)
    )
    monkeypatch.setattr("cineflow.main.bootstrap_configuration", lambda: ())
    main([])
    assert calls[-1] == "run"
    assert len(handlers) == 2
    for handler in handlers.values():
        handler(None, None)
    assert calls[-2:] == ["signal-shutdown", "signal-shutdown"]


def test_version_exits_without_initializing_application(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "cineflow.main.MainApp", lambda: (_ for _ in ()).throw(AssertionError("initialized"))
    )

    try:
        main(["--version"])
    except SystemExit as exc:
        assert exc.code == 0

    assert capsys.readouterr().out.startswith("CineFlow ")


def test_shutdown_leaves_dependencies_open_when_flow_close_times_out() -> None:
    calls = []

    class Component:
        def __init__(self, name, close_result=True):
            self.name = name
            self.close_result = close_result

        def stop(self):
            calls.append(f"stop:{self.name}")
            return self.close_result

        def close(self):
            calls.append(f"close:{self.name}")
            return self.close_result

    app = MainApp.__new__(MainApp)
    app._shutdown_event = threading.Event()
    app._components = [Component("database"), Component("flow", close_result=False)]

    app.shutdown()

    assert calls == ["stop:flow", "stop:database", "close:flow"]
