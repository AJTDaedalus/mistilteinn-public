"""Adapters that import character/weapon/artifact/enemy data from external sources into the DB.

Only the abstract interface survives the port; `NanokaImporter` and the hakushin, ezod,
dimbreath and scanner adapters were deleted in B.8. Chunk D adds `nanoka_gi_importer`.
"""

from app.data.importers.base_importer import BaseImporter

__all__ = ["BaseImporter"]
