"""Validated, explicit baseline configuration, hashed into every persisted run."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


class BaselineSettings(BaseModel):
    """Settings govern readiness checks, never permission to invent missing targets."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    horizons_days: tuple[Literal[7], Literal[14], Literal[28]] = (7, 14, 28)
    daily_min_history_observations: int = Field(28, ge=1, strict=True)
    max_daily_data_age_days: int = Field(3, ge=0, strict=True)
    max_monthly_context_age_days: int = Field(90, ge=0, strict=True)
    methods: tuple[Literal["last_value"], Literal["seasonal_naive"], Literal["seasonal_mean"]] = (
        "last_value",
        "seasonal_naive",
        "seasonal_mean",
    )
    calibration_min_samples: int = Field(20, ge=1, strict=True)
    nominal_interval_coverage: float = Field(0.90, gt=0, lt=1)


def load_settings(path: Path | None = None) -> BaselineSettings:
    """Read settings explicitly; no mutable singleton or hidden environment overrides."""
    target = path or Path(__file__).resolve().parents[2] / "configs/forecasting.yaml"
    return BaselineSettings.model_validate(yaml.safe_load(target.read_text()))
