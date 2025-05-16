"""Image handler for the metadata posters."""

import os
import requests
from PIL import Image, ImageOps, ImageDraw, UnidentifiedImageError
from system.logger import log


class ImageHandler():
    """Image handler for the metadata"""

    def __init__(self, url: str, scale: tuple = (600, 900)) -> None:
        self._scale = scale
        self._positions = ['top-left', 'top-right', 'bottom-left', 'bottom-right']
        self._mods = ['grayscale', 'border', 'triangle']
        self._colors = {
            'yellow': '#FEBA17',
            'blue': '#3A59D1',
            'red': '#CF0F47',
            'green': '#1DCD9F',
            'white': '#FFFFFF',
        }
        if url:
            self._img = self._load(url=url)
        else:
            self._img = None
            log("No image url specified.", level='WARNING')

    def _load(self, url: str) -> Image.Image:
        try:
            img = Image.open(requests.get(url, stream=True, timeout=10).raw)
            img = img.resize(self._scale)
            log(f"Image loaded successfully from '{url}'", level='DEBUG')
        except (FileNotFoundError, UnidentifiedImageError) as e:
            log(f"Error loading image: {e}", level='WARNING')
            return None
        return img

    def _apply_border(self, color: str) -> None:
        width = self._img.width // 60
        return ImageOps.expand(self._img, border=width, fill=color).resize(self._scale)

    def _apply_triangle(self, color: str, position: str) -> None:
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

    def apply(self, mod: str, color: str = 'white', position: str = 'top-right') -> "ImageHandler":
        """Apply a modification to the image."""
        if not self._img:
            return self
        if mod not in self._mods:
            log(f"Invalid image modification '{mod}'", level='WARNING')
            return self
        if color not in self._colors:
            log(f"Invalid image modification color '{color}'", level='WARNING')
            return self
        if position not in self._positions:
            log(f"Invalid image modification position '{position}'", level='WARNING')
            return self

        if mod == 'grayscale':
            self._img = ImageOps.grayscale(self._img)
        elif mod == 'border':
            self._img = self._apply_border(self._colors[color])
        elif mod == 'triangle':
            self._apply_triangle(self._colors[color], position)
        else:
            log(f"Unknown image modification '{mod}'", level='WARNING')
            return self
        log(f"Image modification '{mod}' applied successfully", level='DEBUG')
        return self

    def save(self, path: str, directory: str = None, file: str = 'cover.png') -> None:
        """Save the image to a file."""
        if not self._img:
            return
        try:
            if directory:
                path = os.path.join(directory, path)
            path = os.path.join(path, file)
            self._img.save(path, format=path.split('.')[-1].upper())
            log(f"Image saved successfully to {path}", level='DEBUG')
        except OSError as e:
            log(f"Error saving image: {e}", level='WARNING')
