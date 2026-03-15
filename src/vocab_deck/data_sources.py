"""Source configuration for warm-up enrichment inputs."""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


@dataclass(frozen=True)
class SourceSpec:
    key: str
    label: str
    default_pdf: str
    line_regex: str
    skip_prefixes: List[str]


SOURCE_SPECS: Dict[str, SourceSpec] = {
    "vocab": SourceSpec(
        key="vocab",
        label="GregMat Vocabulary",
        default_pdf="GregMat Vocab.pdf",
        line_regex=r"^([a-z]+)",
        skip_prefixes=["Group"],
    ),
    "gre_quant": SourceSpec(
        key="gre_quant",
        label="GRE Quant",
        default_pdf="GregMat Quant.pdf",
        line_regex=r"^([A-Za-z][A-Za-z0-9\- ]{1,80})",
        skip_prefixes=["Group", "Section", "Set"],
    ),
}


def get_source_spec(source_key: str) -> SourceSpec:
    key = (source_key or "vocab").strip().lower()
    if key not in SOURCE_SPECS:
        supported = ", ".join(sorted(SOURCE_SPECS.keys()))
        raise ValueError(f"Unknown source '{source_key}'. Supported: {supported}")
    return SOURCE_SPECS[key]


def get_default_pdf_path(source_key: str, base_dir: Path) -> Path:
    spec = get_source_spec(source_key)
    return base_dir / "data" / "raw" / spec.default_pdf
