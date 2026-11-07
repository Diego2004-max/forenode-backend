from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from math import cos, pi, sin

import joblib
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.base import clone
from sklearn.model_selection import TimeSeriesSplit
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from . import models

MINIMUM_TRAINING_ROWS = 12


def feature_vector(month: int, temperature_c: float, precipitation_mm: float) -> list[float]:
    angle = 2 * pi * month / 12
    return [sin(angle), cos(angle), temperature_c, precipitation_mm]


@dataclass(frozen=True)
class Prediction:
    demand_kg: float
    lower_kg: float
    upper_kg: float
    confidence: float


def train_model(db: Session, product_code: str, region_code: str) -> models.ModelArtifact:
    observations = db.scalars(
        select(models.DemandObservation)
        .where(models.DemandObservation.product_code == product_code, models.DemandObservation.region_code == region_code)
        .order_by(models.DemandObservation.observed_on)
    ).all()
    if len(observations) < MINIMUM_TRAINING_ROWS:
        raise ValueError(f"Se requieren al menos {MINIMUM_TRAINING_ROWS} observaciones reales; hay {len(observations)}.")
    features = np.asarray([feature_vector(x.observed_on.month, x.temperature_c, x.precipitation_mm) for x in observations])
    target = np.asarray([x.demand_kg for x in observations])
    estimator = RandomForestRegressor(n_estimators=300, min_samples_leaf=2, random_state=42, n_jobs=-1)
    splits = min(5, max(2, len(observations) // 4))
    actual_parts: list[np.ndarray] = []
    forecast_parts: list[np.ndarray] = []
    for train_indices, test_indices in TimeSeriesSplit(n_splits=splits).split(features):
        fold_model = clone(estimator)
        fold_model.fit(features[train_indices], target[train_indices])
        actual_parts.append(target[test_indices])
        forecast_parts.append(fold_model.predict(features[test_indices]))
    actual = np.concatenate(actual_parts)
    forecast = np.concatenate(forecast_parts)
    mae = float(mean_absolute_error(actual, forecast))
    r2 = float(r2_score(actual, forecast)) if len(actual) > 1 else 0.0
    residual_p90 = float(np.percentile(np.abs(actual - forecast), 90))
    estimator.fit(features, target)
    buffer = BytesIO()
    joblib.dump(estimator, buffer)
    version = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{product_code}-{region_code}"
    db.execute(update(models.ModelArtifact).where(
        models.ModelArtifact.product_code == product_code,
        models.ModelArtifact.region_code == region_code,
    ).values(is_active=False))
    artifact = models.ModelArtifact(
        product_code=product_code, region_code=region_code, version=version,
        training_rows=len(observations), mae_kg=mae, r2_score=r2,
        residual_p90_kg=residual_p90, artifact=buffer.getvalue(), is_active=True,
    )
    db.add(artifact)
    db.commit()
    db.refresh(artifact)
    return artifact


def predict(artifact: models.ModelArtifact, month: int, temperature_c: float, precipitation_mm: float) -> Prediction:
    estimator = joblib.load(BytesIO(artifact.artifact))
    value = max(0.0, float(estimator.predict([feature_vector(month, temperature_c, precipitation_mm)])[0]))
    confidence = max(0.0, min(0.99, 1.0 - artifact.mae_kg / max(value, 1.0)))
    return Prediction(value, max(0.0, value - artifact.residual_p90_kg), value + artifact.residual_p90_kg, confidence)
