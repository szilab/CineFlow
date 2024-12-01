import re
import os
from os import path as p
from typing import Any
from io import BytesIO
from PIL import Image, ImageOps
from pathlib import Path
from lib.handlers.request import RequestHandler
from sys.logger import Logger


class ImageHandler():
    # __download_image = f"{Path(__file__).resolve().parents[2]}/res/download_overlay.png"
    # __default_size = (600, 900)

    def __init__(self, image_config: dict) -> None:
        from lib.misc.config import InstanceConfig
        self.config = InstanceConfig(config=image_config)
        if re.search(r'\dx\d', self.config.get('scale', default='')):
            self.scale = self.config.get('scale').split('x')
            Logger.debug(f"Image scale: {self.scale}")
        else:
            self.scale = (600, 900)
            Logger.warning(f"Missing or wrong image scale, using default: {self.scale}")
        icon_folder = p.join(p.dirname(p.dirname(p.dirname(__file__))), 'res/icons')
        icons_list = os.listdir(icon_folder)
        self.icons = []
        for i in icons_list:
            self.icons.append({'name': i.replace('.png', ''), 'path': f"{icon_folder}/{i}"})
        self.positions = ['center', 'top-left', 'top-right', 'bottom-left', 'bottom-right']
        # data = self.__fetch_image_data(path)
        # self.pathdata = self.__parse_path(path)
        # self.img = Image.open(BytesIO(data))
        # if scale:
        #     self.img = self.img.resize(self.__default_size, Image.ANTIALIAS)


    def apply(self, path: str, directory: dict, name: str = None, metadata: dict = {}) -> None:
        """Save an image to the given directory."""
        dst_path = f"{directory}/{name}.png" if name else f"{directory}/{Path(path).stem}.png"
        img = self.load(path=dst_path) if Path(dst_path).exists() else self.load(path=path)
        if not img:
            return
        img = self.grayscale(img=img, metadata=metadata)
        img = self.apply_icon(img=img, metadata=metadata)
        img = self.apply_border(img=img, metadata=metadata)
        try:
            img.save(dst_path)
            Logger.debug(f"Image saved: {dst_path}")
        except Exception as e:
            Logger.error(f"Error saving image: {e}")

    def load(self, path: str) -> Image.Image:
        """Load an image from the given path."""
        try:
            img = self.__fetch_image(path)
            img = img.resize(self.scale)
        except Exception as e:
            Logger.error(f"Error loading image: {e}")
            return None
        return img.convert("RGBA")

    def grayscale(self, img: Image.Image, metadata: dict = {}) -> Image.Image:
        """Convert the image to grayscale."""
        exp = self.config.get('grayscale', {}).get('expression')
        exp_value = self.__eval_expression(expression=exp, metadata=metadata) if exp else False
        if exp_value:
            return ImageOps.grayscale(img)
        return img

    def apply_icon(self, img: Image.Image, metadata: dict = {}) -> Image.Image:
        """Add an icon to the image."""
        if not self.config.get('icon'):
            return img

        icon_name = self.config.get('icon').get('name')
        if not icon_name:
            Logger.warning("Missing 'name' is mandatory for 'icon' type image operation")
            return img

        icon = self.__load_icon(name=icon_name)
        position = self.config.get('icon').get('position', 'top-right')
        if not icon:
            Logger.warning(f"Icon '{icon_name}' not found for image operation")
            return img

        exp = self.config.get('icon').get('expression')
        exp_value = self.__eval_expression(expression=exp, metadata=metadata) if exp else True
        if exp_value:
            return self.__apply_overlay(img=img, overlay=icon, position=position)
        return img

    def apply_border(self, img: Image.Image, metadata: dict = {}) -> Image.Image:
        """Add a border to the image."""
        if not self.config.get('border'):
            return img
        color = self.config.get('border').get('color', 'ffffff')
        color = self.__fix_color_names(color)
        exp = self.config.get('border').get('expression')
        exp_value = self.__eval_expression(expression=exp, metadata=metadata) if exp else True
        if exp_value:
            border_width = self.scale[0] // 60 if not self.config.get('border').get('width') else self.config.get('border').get('width')
            return ImageOps.expand(img, border=border_width, fill=f"#{color}").resize(self.scale)
        return img

    def __fetch_image(self, path: str) -> bytes:
        if path.startswith("http"):
            img_data = RequestHandler.get_file(url=path)
        else:
            with open(path, 'rb') as f:
                img_data = f.read()
        return Image.open(BytesIO(img_data))

    def __eval_expression(self, expression: str, metadata: dict) -> Any:
        """Evaluate a string expression."""
        if isinstance(expression, bool):
            return expression
        groups = re.search(r'(\w+) (\-eq|\-lt|\-gt|\-match) (.+)', expression).groups()
        if not groups:
            Logger.warning(f"Unsupported expression '{expression}' for image operation")
            return False
        param = metadata.get(groups[0])
        value = groups[2]
        if not param:
            Logger.warning(
                f"Wrong expression for image operation: "
                f"Missing metadata key '{groups[0]}', valid keys: {metadata.keys()}"
            )
            return False
        if groups[1] == '-eq':
            return param == value
        elif groups[1] == '-lt':
            return int(param) < int(value)
        elif groups[1] == '-gt':
            return int(param) > int(value)
        elif groups[1] == '-match':
            return re.search(value.replace("'", ""), param)
        return False

    def __load_icon(self, name: str) -> Image.Image:
        if not name in [i['name'] for i in self.icons]:
            return None
        icon_path = [i['path'] for i in self.icons if i['name'] == name][0]
        icon = Image.open(icon_path)
        icon_scale = self.scale[0] // 10
        return icon.resize((icon_scale, icon_scale))

    def __apply_overlay(self, img: Image.Image, overlay: Image.Image, position: str = None) -> Image.Image:
        if position not in self.positions:
            Logger.warning(f"Unsupported position '{position}' for image operation using 'top-right'")
            position = 'top-right'
        cordinates = self.__calc_position(position=position, img=img, overlay=overlay)
        combined = Image.alpha_composite(img.convert("RGBA"), Image.new("RGBA", img.size))
        combined.paste(overlay, cordinates, overlay)
        return combined

    def __calc_position(self, position: str, img: Image.Image, overlay: Image.Image) -> tuple:
        iW, iH = img.size
        oW, oH = overlay.size
        spc = iW // 20
        if position == "center":
            return ((iW - oW) // 2, (iH - oH) // 2)
        elif position == "top-left":
            return (spc, spc)
        elif position == "top-right":
            return (iW - oW - spc, spc)
        elif position == "bottom-left":
            return (spc, iH - oH - spc)
        elif position == "bottom-right":
            return (iW - oW - spc, iH - oH - spc)

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

    # def name(self, new : str = None) -> "ImageHandler":
    #     """Set or get the image's file name."""
    #     if new:
    #         self.pathdata['name'] = new
    #     return self

    # def indicate(self, overlay_type: str, position: str = None) -> "ImageHandler":
    #     """Add an overlay to the image."""
    #     if overlay_type == "download":
    #         return self.__add_download_overlay(position)
    #     return self


    # def __add_download_overlay(self, position: str = None) -> "ImageHandler":
    #     overlay = ImageHandler(self.__download_image).img.convert("RGBA")
    #     self.img = self.__apply_overlay(img=self.img, overlay=overlay, position=position)
    #     return self

    # def __apply_overlay(self, img: Image.Image, overlay: Image.Image, position: str = None) -> Image.Image:
    #     img = img.convert("RGBA")
    #     cordinates = self.__position_to_cordinates(position=position, overlay=overlay)
    #     combined = Image.alpha_composite(img, Image.new("RGBA", img.size))
    #     combined.paste(overlay, cordinates, overlay)
    #     self.pathdata['ext'] = 'png'
    #     return combined

    # def __position_to_cordinates(self, position: str, overlay: Image.Image) -> tuple:
    #     if not overlay:
    #         return (0, 0)
    #     if position == "center":
    #         return (int((self.img.width - overlay.width) / 2), int((self.img.height - overlay.height) / 2))
    #     elif position == "top-left":
    #         return (10, 10)
    #     elif position == "top-right":
    #         return (self.img.width - overlay.width - 10, 10)
    #     elif position == "bottom-left":
    #         return (10, self.img.height - overlay.height - 10)
    #     return (self.img.width - overlay.width - 10, self.img.height - overlay.height - 10)
