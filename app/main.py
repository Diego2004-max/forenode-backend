from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import desc, select, text
from sqlalchemy.orm import Session

from . import ai_service, auth, models, schemas
from .catalog import PRODUCTS, REGIONS
from .config import get_settings
from .database import Base, engine, get_db
from .weather import WeatherService

settings = get_settings()


def migrate_legacy_user_foreign_keys() -> None:
    """Point existing Enterprise tables at the isolated user table.

    The first Enterprise deployment created these FKs against the legacy
    `users` table. `create_all` cannot alter an existing constraint, so the
    adjustment is intentionally small and idempotent.
    """
    if engine.dialect.name != "postgresql":
        return
    targets = {
        "inventory_snapshots": "created_by",
        "demand_observations": "created_by",
        "matching_runs": "requested_by",
    }
    with engine.begin() as connection:
        connection.execute(text(
            "ALTER TABLE IF EXISTS matching_runs "
            "ALTER COLUMN weather_source TYPE VARCHAR(500)"
        ))
        for table, column in targets.items():
            constraints = connection.execute(text("""
                SELECT c.conname
                FROM pg_constraint AS c
                JOIN pg_class AS t ON t.oid = c.conrelid
                JOIN pg_attribute AS a ON a.attrelid = t.oid AND a.attnum = ANY(c.conkey)
                WHERE c.contype = 'f' AND t.relname = :table_name AND a.attname = :column_name
            """), {"table_name": table, "column_name": column}).scalars().all()
            for constraint in constraints:
                connection.execute(text(f'ALTER TABLE "{table}" DROP CONSTRAINT "{constraint}"'))
            connection.execute(text(
                f'ALTER TABLE "{table}" ADD CONSTRAINT "{table}_{column}_enterprise_fkey" '
                f'FOREIGN KEY ("{column}") REFERENCES "forenode_users" (id)'
            ))


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    migrate_legacy_user_foreign_keys()
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Motor verificable de pronóstico y balance logístico agrícola.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["X-Request-ID"],
    max_age=600,
)


def require_catalog(product_code: str, region_code: str) -> None:
    if product_code not in PRODUCTS:
        raise HTTPException(status_code=422, detail="Producto no soportado.")
    if region_code not in REGIONS:
        raise HTTPException(status_code=422, detail="Nodo regional no soportado.")


def token_for(user: models.User) -> schemas.TokenResponse:
    return schemas.TokenResponse(
        access_token=auth.create_access_token(user.email),
        expires_in=settings.access_token_expire_minutes * 60,
        full_name=user.full_name,
        email=user.email,
    )


@app.get("/", tags=["system"])
def root() -> dict[str, str]:
    return {"service": settings.app_name, "version": settings.app_version, "status": "online"}


@app.get("/api/v1/health", tags=["system"])
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "healthy", "database": "connected"}


@app.get("/api/v1/catalog", response_model=schemas.CatalogResponse, tags=["catalog"])
def catalog() -> schemas.CatalogResponse:
    return schemas.CatalogResponse(
        regions=[vars(item) for item in REGIONS.values()],
        products=[vars(item) for item in PRODUCTS.values()],
    )


@app.post("/api/v1/auth/register", response_model=schemas.TokenResponse, status_code=201, tags=["auth"])
def register(payload: schemas.UserRegister, db: Session = Depends(get_db)) -> schemas.TokenResponse:
    email = payload.email.lower()
    if db.scalar(select(models.User).where(models.User.email == email)):
        raise HTTPException(status_code=409, detail="El correo ya está registrado.")
    user = models.User(email=email, hashed_password=auth.get_password_hash(payload.password), full_name=payload.full_name.strip())
    db.add(user)
    db.commit()
    db.refresh(user)
    return token_for(user)


@app.post("/api/v1/auth/login", response_model=schemas.TokenResponse, tags=["auth"])
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)) -> schemas.TokenResponse:
    user = db.scalar(select(models.User).where(models.User.email == form.username.lower()))
    if not user or not auth.verify_password(form.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Correo o contraseña incorrectos.", headers={"WWW-Authenticate": "Bearer"})
    return token_for(user)


@app.post("/api/v1/inventory", response_model=schemas.InventoryResponse, status_code=201, tags=["data"])
def create_inventory(
    payload: schemas.InventoryCreate,
    user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
) -> models.InventorySnapshot:
    require_catalog(payload.product_code, payload.region_code)
    record = models.InventorySnapshot(**payload.model_dump(), created_by=user.id)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@app.post("/api/v1/demand-observations", status_code=201, tags=["data"])
async def create_observation(
    payload: schemas.DemandObservationCreate,
    user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    require_catalog(payload.product_code, payload.region_code)
    region = REGIONS[payload.region_code]
    weather = await WeatherService().get_daily(region.latitude, region.longitude, payload.observed_on)
    record = models.DemandObservation(
        **payload.model_dump(),
        temperature_c=weather.temperature_c,
        precipitation_mm=weather.precipitation_mm,
        created_by=user.id,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return {"id": record.id}


@app.post("/api/v1/models/train", response_model=schemas.ModelResponse, tags=["models"])
def train(
    payload: schemas.TrainingRequest,
    _: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
) -> schemas.ModelResponse:
    require_catalog(payload.product_code, payload.region_code)
    try:
        artifact = ai_service.train_model(db, payload.product_code, payload.region_code)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return schemas.ModelResponse.model_validate(artifact, from_attributes=True)


@app.post("/api/v1/matching/engine", response_model=schemas.MatchingResponse, tags=["matching"])
async def run_matching(
    payload: schemas.MatchingRequest,
    user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
) -> schemas.MatchingResponse:
    require_catalog(payload.product_code, payload.region_code)
    region = REGIONS[payload.region_code]
    product = PRODUCTS[payload.product_code]
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.inventory_max_age_hours)
    inventory = db.scalar(
        select(models.InventorySnapshot)
        .where(
            models.InventorySnapshot.product_code == payload.product_code,
            models.InventorySnapshot.region_code == payload.region_code,
            models.InventorySnapshot.recorded_at >= cutoff,
        )
        .order_by(desc(models.InventorySnapshot.recorded_at))
    )
    if inventory is None:
        raise HTTPException(status_code=409, detail="No hay un inventario real y vigente para esta combinación. Registra la oferta antes de ejecutar el motor.")
    artifact = db.scalar(
        select(models.ModelArtifact)
        .where(
            models.ModelArtifact.product_code == payload.product_code,
            models.ModelArtifact.region_code == payload.region_code,
            models.ModelArtifact.is_active.is_(True),
        )
        .order_by(desc(models.ModelArtifact.trained_at))
    )
    if artifact is None:
        raise HTTPException(status_code=409, detail="No existe un modelo entrenado con observaciones reales para esta combinación.")
    weather = await WeatherService().get_daily(region.latitude, region.longitude, payload.target_date)
    prediction = ai_service.predict(artifact, payload.target_date.month, weather.temperature_c, weather.precipitation_mm)
    gap = prediction.demand_kg - inventory.quantity_kg
    ratio = gap / max(prediction.demand_kg, 1.0)
    if ratio > 0.10:
        market_status = "critical_deficit"
        explanation = "La oferta vigente no cubre el límite central de demanda; se recomienda activar abastecimiento alterno."
    elif ratio < -0.10:
        market_status = "high_surplus"
        explanation = "La oferta supera la demanda prevista; conviene priorizar redistribución y conservación."
    else:
        market_status = "balanced"
        explanation = "La oferta está dentro de una banda del 10 % respecto de la demanda prevista."
    run = models.MatchingRun(
        product_code=payload.product_code, region_code=payload.region_code, target_date=payload.target_date,
        predicted_demand_kg=prediction.demand_kg, available_supply_kg=inventory.quantity_kg, gap_kg=gap,
        status=market_status, confidence_score=prediction.confidence, model_version=artifact.version,
        weather_source=weather.source, inventory_snapshot_id=inventory.id, requested_by=user.id, explanation=explanation,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return schemas.MatchingResponse(
        run_id=run.id, product_code=product.code, product_name=product.name,
        region_code=region.code, region_name=region.name, target_date=payload.target_date,
        weather=schemas.WeatherResponse(
            temperature_c=round(weather.temperature_c, 1), precipitation_mm=round(weather.precipitation_mm, 1),
            observed_or_forecast=weather.kind, source=weather.source,
        ),
        predicted_demand_kg=round(prediction.demand_kg, 2), demand_lower_kg=round(prediction.lower_kg, 2),
        demand_upper_kg=round(prediction.upper_kg, 2), available_supply_kg=round(inventory.quantity_kg, 2),
        inventory_recorded_at=inventory.recorded_at, inventory_source=inventory.source_reference,
        gap_kg=round(gap, 2), market_status=market_status, confidence_score=round(prediction.confidence, 3),
        model_version=artifact.version, model_mae_kg=round(artifact.mae_kg, 2), explanation=explanation,
    )
