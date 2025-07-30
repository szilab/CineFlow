"""Image handler for the metadata posters."""

import os
from dataclasses import dataclass
import requests
from PIL import Image, ImageOps, ImageDraw, UnidentifiedImageError
from cineflow.system.logger import log


@dataclass
class KnownColors:
    """Dataclass to store known colors."""
    yellow: str = '#FEBA17'
    blue: str = '#3A59D1'
    red: str = '#CF0F47'
    green: str = '#1DCD9F'
    white: str = '#FFFFFF'
    black: str = '#000000'
    orange: str = '#FF7F00'


class ImageHandler():
    """Image handler for the metadata"""

    def __init__(self, url: str, scale: tuple = (600, 900)) -> None:
        self._scale = scale
        self._positions = ['top-left', 'top-right', 'bottom-left', 'bottom-right']
        self._mods = ['grayscale', 'border', 'triangle']
        self._img = self._load(url=url)
        self._filename = 'cover.png'

    def save(self, path: str) -> None:
        """Save the image to a file."""
        if not self._img:
            log("No image to save.", level='WARNING')
            return
        try:
            self._img.save(os.path.join(path, self._filename))
            log(f"Image saved successfully to {path}")
        except (OSError, ValueError) as e:
            log(f"Error saving image: {e}", level='WARNING')

    def apply(self, mod: str, color: str = 'red', position: str = 'top-right') -> None:
        """Apply a modification to the image."""
        if not self._img:
            log("No image loaded to apply modifications.", level='WARNING')
        try:
            if mod == 'grayscale':
                self._img = ImageOps.grayscale(image=self._img)
            elif mod == 'border':
                self._img = self._apply_border(color=color)
            elif mod == 'triangle':
                self._apply_triangle(color=color, position=position)
            else:
                log(f"Unknown image modification '{mod}'", level='WARNING')
        except (Exception) as e:  # pylint: disable=broad-except
            log(f"Failed to applying image modification '{mod}': {e}", level='WARNING')
        log(f"Image modification '{mod}' applied successfully")

    def apply_from_rule(self, rule: dict) -> None:
        self.apply(
            mod=rule.get('modification'),
            color=rule.get('color', 'red'),
            position=rule.get('position', 'top-right')
        )

    def _load(self, url: str) -> Image.Image:
        try:
            response = requests.get(url, stream=True, timeout=10)
            response.raise_for_status()
            img = Image.open(response.raw)
            img = img.resize(self._scale)
            log(f"Image loaded successfully from '{url}'")
        except (requests.RequestException, UnidentifiedImageError, OSError) as e:
            log(f"Error loading image: {e}", level='WARNING')
            return None
        return img

    def _apply_border(self, color: str) -> None:
        width = self._img.width // 60
        color = self._translate_color(color)
        return ImageOps.expand(self._img, border=width, fill=color).resize(self._scale)

    def _apply_triangle(self, color: str, position: str) -> None:
        if position not in self._positions:
            log(f"Invalid triangle position '{position}'", level='WARNING')
            return
        color = self._translate_color(color)
        size = self._img.width // 4
        tria = Image.new('RGBA', size=(size, size), color=(0, 0, 0, 0))
        draw = ImageDraw.Draw(tria)
        if position == 'top-left':
            draw.polygon([(0, 0), (0, tria.height), (tria.width, 0)], fill=color)
            self._img.paste(tria, (0, 0), tria)
        elif position == 'top-right':
            draw.polygon([(tria.width, 0), (tria.width, tria.height), (0, 0)], fill=color)
            self._img.paste(tria, (self._img.width - size, 0), tria)
        elif position == 'bottom-left':
            draw.polygon([(0, tria.height), (0, 0), (tria.width, tria.height)], fill=color)
            self._img.paste(tria, (0, self._img.height - size), tria)
        elif position == 'bottom-right':
            draw.polygon([(tria.width, tria.height), (0, tria.height), (tria.width, 0)], fill=color)
            self._img.paste(tria, (self._img.width - size, self._img.height - size), tria)

    def _translate_color(self, color: str) -> str:
        """Translate a color name to its hex value."""
        colors = KnownColors()
        return getattr(colors, color, '#000000')

    @property
    def filename(self) -> str:
        return self._filename

    @filename.setter
    def filename(self, value: str) -> None:
        self._filename = value
