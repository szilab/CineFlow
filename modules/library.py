import shutil
from pathlib import Path
from bases.abs import ModuleBase
from bases.enums import MediaType
from bases.utils import sort_data
from bases.image import ImageHandler
from system.config import Config
from system.database import Database as db
from system.logger import log


class LibraryModule(ModuleBase):
    def __init__(self, type: MediaType):
        self._name = "Library"
        self._type = type.value
        self._limit = 20
        self._ready = self._is_required_config_set(['DATA_DIR'])
        self._exported = []
        if self._ready:
            self._library = Path(Config().DATA_DIR + "/" + self._type)
            self._library.mkdir(parents=True, exist_ok=True)
            self._ready = self._library.exists()

    def export(self):
        all = sort_data(data=db().get_all(self._type), param='updated_at', reverse=True)
        self._exported = []
        for item in all:
            if item.get('collected') != 'false':
                if item.get('title') and item.get('poster'):
                    name = item.get('title') + " (" + item.get('year') + ")"
                    folder = Path(self._library / name)
                    self._export_video(folder=folder, name=name)
                    self._export_poster(item=item, folder=folder)
                    if len(self._exported) >= self._limit:
                        break
                else:
                    log(f"Skipping item export {item.get('title')} due to missing data", level='WARNING')
            else:
                log(f"Skipping item export {item.get('title')} due to already available in media server", level='DEBUG')
        for f in self._library.iterdir():
            self._rm(folder=f)

    def _export_video(self, folder: Path, name: str):
        self._exported.append(name)
        if not folder.exists():
            log(f"Exported {name} to {self._library}", level='DEBUG')
            self._create_dir(folder=folder)
            self._create_video(folder=folder)

    def _create_video(self, folder: Path):
        video = folder / f"{folder.name.replace(' ', '_')}.mkv"
        if not video.exists():
            video.touch()

    def _create_dir(self, folder: Path):
        if not folder.exists():
            folder.mkdir(parents=True)

    def _export_poster(self, item: dict, folder: Path):
        ImageHandler(metadata=item).save(folder=folder)

    def _rm(self, folder: Path):
        if folder.is_dir() and folder.name not in self._exported:
            shutil.rmtree(folder)
            log(f"Removed {folder} from {self._library}", level='DEBUG')