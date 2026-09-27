"""Map inspection: main direction and ghost / gap candidates. Read only; it never changes the map."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from dataclasses import asdict

import numpy as np
from loguru import logger

from component.map_inspection.candidate import CandidateDetection
from component.map_inspection.direction import MainDirection
from component.map_inspection.protection import ProtectionZone
from component.map_storage.service import MapDocument, MapStorage
from config.settings import use_utf8_output


class MapInspection:
    def __init__(self, **kwargs) -> None:
        self.direction = MainDirection(**kwargs)
        self.candidates = CandidateDetection(**kwargs)
        self.protection = ProtectionZone(**kwargs)

    def main_direction(self, document: MapDocument) -> float:
        theta = self.direction.detect(document)
        return theta

    def protection_mask(self, document: MapDocument) -> np.ndarray:
        mask = self.protection.mask(document)
        return mask

    def candidate_list(self, document: MapDocument, **kwargs) -> list[dict]:
        """Largest first, as plain dicts for the page."""
        candidates = [asdict(candidate) for candidate in self.candidates.detect(document, **kwargs)]
        return candidates


def demo_inspection() -> None:
    document = MapStorage().load()
    inspection = MapInspection()
    candidates = inspection.candidate_list(document)
    logger.info("Main direction {:.1f}°; {} candidates, largest {}", inspection.main_direction(document),
                len(candidates), {key: candidates[0][key] for key in ("kind", "cells", "centre")})


def main() -> None:
    use_utf8_output()
    demo_inspection()


if __name__ == "__main__":
    main()
