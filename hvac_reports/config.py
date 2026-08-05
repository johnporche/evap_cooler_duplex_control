from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class ReportConfig:
    site_name: str = "Evaporative Cooler Duplex"
    timezone: str = "America/Denver"
    latitude: float = 39.7392
    longitude: float = -104.9903
    expected_sample_seconds: float = 5.0
    maximum_sample_gap_seconds: float = 30.0

    @classmethod
    def load(cls, path=None):
        if path is None:
            return cls()
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{key: value for key, value in data.items() if key in allowed})

