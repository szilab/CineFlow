import requests
import re
from PIL import Image, ImageOps
from system.config import Config
from system.logger import log


class ImageHandler():
    def __init__(self, metadata: dict) -> None:
        self._metadata = metadata
        self._scale = (600, 900)
        self._icons = []
        self._positions = ['center', 'top-left', 'top-right', 'bottom-left', 'bottom-right']

    def save(self, folder: str) -> None:
        url = self._metadata.get('poster')
        if not url:
            return
        img = self._load_image_from_url(url=url)
        if not img:
            return
        img = self._apply_rules(img=img)
        img.save(folder / "poster.png")
        log(f"Saved poster to '{folder}'", level='DEBUG')

    def _load_image_from_url(self, url: str) -> Image.Image:
        try:
            img = Image.open(requests.get(url, stream=True).raw)
        except Exception as e:
            log(f"Error loading image: {e}", level='WARNING')
            return None
        return img

    def _apply_rules(self, img: Image.Image) -> Image.Image:
        if not self._metadata.get('link'):
            img = ImageOps.grayscale(img)
            log(f"Applied grayscale to image '{self._metadata.get('title')}'", level='DEBUG')
        if Config().BORDER_RULES and self._metadata.get('torrent'):
            for rule in Config().BORDER_RULES.split(';'):
                if '=' in rule:
                    match, color = rule.split('=')
                    if re.search(match, self._metadata.get('torrent').lower()):
                        img = self._apply_border(img=img, color=color)
                        log(f"Applied border '{color}' to image '{self._metadata.get('title')}'", level='DEBUG')
        return img

    def _apply_border(self, img: Image.Image, color: str) -> Image.Image:
        color = self.__fix_color_names(color)
        width = img.width // 60
        scale = (img.width, img.height)
        return ImageOps.expand(img, border=width, fill=f"#{color}").resize(scale)

    def __fix_color_names(self, color: str) -> str:
        if color == 'red':
            return 'ea1029'
        elif color == 'green':
            return '18dd32'
        elif color == 'blue':
            return '183fdd'
        elif color == 'yellow':
            return 'fce705'
        elif color == 'magenta':
            return 'dd18a4'
        return color