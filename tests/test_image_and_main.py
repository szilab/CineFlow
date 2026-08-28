"""Image transformations and application lifecycle behavior."""

from io import BytesIO

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
    assert calls == ["close:flow", "stop:flow", "close:database", "stop:database", "close:config", "stop:config"]
    monkeypatch.setattr("cineflow.main.MainApp", lambda: type("App", (), {"run": lambda self: calls.append("run")})())
    main()
    assert calls[-1] == "run"
