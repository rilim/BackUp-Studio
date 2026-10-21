"""Application settings. No third-party Python dependencies are required."""
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
import json
import os
import tempfile
from path_utils import io_path

APP_NAME = "BackUp Studio"
APP_VERSION = "2.6.0"


def state_directory() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "BackUpStudio"


@dataclass
class Settings:
    source: str = "C:/D/BackUp/origin"
    destination: str = "C:/D/BackUp/Copy"
    exclusions: list[str] = field(default_factory=lambda: ["Investavimas", "Islaidos/Islaidos UK"])
    workers: int = 4
    retries: int = 3
    keep_versions: bool = True
    versions_directory: str = ""
    language: str = "lt"
    theme: str = "light"

    def validate(self):
        if not isinstance(self.source, str) or not isinstance(self.destination, str):
            raise ValueError("Aplankų keliai turi būti tekstas.")
        if not isinstance(self.exclusions, list) or not all(isinstance(x, str) for x in self.exclusions):
            raise ValueError("Netinkamas išimčių sąrašas.")
        if type(self.workers) is not int or not 1 <= self.workers <= 16:
            raise ValueError("Lygiagrečių užduočių skaičius turi būti nuo 1 iki 16.")
        if type(self.retries) is not int or not 1 <= self.retries <= 5:
            raise ValueError("Bandymų skaičius turi būti nuo 1 iki 5.")
        if type(self.keep_versions) is not bool or not isinstance(self.versions_directory, str):
            raise ValueError("Netinkami versijų nustatymai.")
        if self.language not in ("lt", "en") or self.theme not in ("light", "dark"):
            raise ValueError("Netinkami kalbos arba temos nustatymai.")
        return self


def write_json(path: Path, data):
    """Write without exposing a partially written settings file or log."""
    path = io_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".writing-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(data, output, ensure_ascii=False, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_settings(directory: Path | None = None) -> tuple[Settings, str]:
    path = (directory or state_directory()) / "settings.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        allowed = {item.name for item in fields(Settings)}
        return Settings(**{key: value for key, value in data.items() if key in allowed}).validate(), ""
    except FileNotFoundError:
        return Settings(), ""
    except (OSError, ValueError, TypeError, AttributeError) as error:
        return Settings(), f"Nepavyko įkelti nustatymų. Naudojamos pradinės reikšmės. {error}"


def save_settings(settings: Settings, directory: Path | None = None):
    write_json((directory or state_directory()) / "settings.json", asdict(settings.validate()))
