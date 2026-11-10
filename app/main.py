from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import desc, func, inspect, select, text
from sqlalchemy.orm import Session

from . import ai_service, auth, models, schemas
from .catalog import PRODUCTS, REGIONS
from .config import get_settings
from .database import Base, SessionLocal, engine, get_db
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
    inspector = inspect(engine)
    user_columns = {column["name"] for column in inspector.get_columns("forenode_users")}
    observation_columns = {column["name"] for column in inspector.get_columns("demand_observations")}
    with engine.begin() as connection:
        if "is_active" not in user_columns:
            connection.execute(text("ALTER TABLE forenode_users ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE"))
        if "is_valid" not in observation_columns:
            connection.execute(text("ALTER TABLE demand_observations ADD COLUMN is_valid BOOLEAN NOT NULL DEFAULT TRUE"))
    with SessionLocal() as db:
        for region in REGIONS.values():
            if db.scalar(select(models.RegionNode.id).where(models.RegionNode.code == region.code)) is None:
                db.add(models.RegionNode(code=region.code, name=region.name, latitude=region.latitude, longitude=region.longitude, is_active=True))
        db.commit()
    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            sample_rows = [(date(2025, 12, 1), 720), (date(2026, 1, 1), 760), (date(2026, 2, 1), 810), (date(2026, 3, 1), 790), (date(2026, 4, 1), 850), (date(2026, 5, 1), 900), (date(2026, 6, 1), 940), (date(2026, 7, 1), 980), (date(2026, 8, 1), 930), (date(2026, 9, 1), 890), (date(2026, 10, 1), 950), (date(2026, 11, 1), 1020)]
            for observed_on, demand_kg in sample_rows:
                connection.execute(text("UPDATE demand_observations SET is_valid = FALSE WHERE product_code = 'papa-pastusa' AND region_code = 'pasto' AND observed_on = :observed_on AND demand_kg = :demand_kg AND source_reference = 'Registro historico de comercializacion'"), {"observed_on": observed_on, "demand_kg": demand_kg})
            connection.execute(text("UPDATE model_artifacts SET is_active = FALSE WHERE version = '20261107T233418Z-papa-pastusa-pasto'"))
    if settings.admin_email:
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE forenode_users SET role = 'admin' WHERE lower(email) = lower(:email)"),
                {"email": settings.admin_email},
            )
    yield


api = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Motor verificable de pronóstico y balance logístico agrícola.",
    lifespan=lifespan,
)



def require_catalog(product_code: str, region_code: str, db: Session | None = None) -> None:
    if product_code not in PRODUCTS:
        raise HTTPException(status_code=422, detail="Producto no soportado.")
    node_exists = region_code in REGIONS if db is None else db.scalar(select(models.RegionNode.id).where(models.RegionNode.code == region_code, models.RegionNode.is_active.is_(True))) is not None
    if not node_exists:
        raise HTTPException(status_code=422, detail="Nodo regional no soportado.")


def get_region(db: Session, region_code: str):
    node = db.scalar(select(models.RegionNode).where(models.RegionNode.code == region_code, models.RegionNode.is_active.is_(True)))
    if node is None:
        raise HTTPException(status_code=422, detail="Nodo regional no disponible.")
    return node


def token_for(user: models.User) -> schemas.TokenResponse:
    return schemas.TokenResponse(
        access_token=auth.create_access_token(user.email),
        expires_in=settings.access_token_expire_minutes * 60,
        full_name=user.full_name,
        email=user.email,
        role=user.role,
    )


@api.get("/", tags=["system"])
def root() -> dict[str, str]:
    return {"service": settings.app_name, "version": settings.app_version, "status": "online"}


@api.get("/api/v1/health", tags=["system"])
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "healthy", "database": "connected"}


@api.get("/api/v1/catalog", response_model=schemas.CatalogResponse, tags=["catalog"])
def catalog(db: Session = Depends(get_db)) -> schemas.CatalogResponse:
    return schemas.CatalogResponse(
        regions=[{"code": node.code, "name": node.name, "latitude": node.latitude, "longitude": node.longitude} for node in db.scalars(select(models.RegionNode).where(models.RegionNode.is_active.is_(True)).order_by(models.RegionNode.name)).all()],
        products=[vars(item) for item in PRODUCTS.values()],
    )


@api.get("/api/v1/auth/me", response_model=schemas.UserResponse, tags=["auth"])
def current_profile(user: models.User = Depends(auth.get_current_user)) -> models.User:
    return user


@api.post("/api/v1/auth/register", response_model=schemas.TokenResponse, status_code=201, tags=["auth"])
def register(payload: schemas.UserRegister, db: Session = Depends(get_db)) -> schemas.TokenResponse:
    email = payload.email.lower()
    if db.scalar(select(models.User).where(models.User.email == email)):
        raise HTTPException(status_code=409, detail="El correo ya está registrado.")
    user = models.User(email=email, hashed_password=auth.get_password_hash(payload.password), full_name=payload.full_name.strip(), role="viewer")
    db.add(user)
    db.commit()
    db.refresh(user)
    return token_for(user)


@api.get("/api/v1/admin/users", response_model=list[schemas.UserResponse], tags=["admin"])
def list_users(_: models.User = Depends(auth.require_role("admin")), db: Session = Depends(get_db)) -> list[models.User]:
    return list(db.scalars(select(models.User).order_by(models.User.created_at)).all())


@api.post("/api/v1/admin/users", response_model=schemas.UserResponse, status_code=201, tags=["admin"])
def create_admin_user(payload: schemas.AdminUserCreate, _: models.User = Depends(auth.require_role("admin")), db: Session = Depends(get_db)) -> models.User:
    raise HTTPException(status_code=410, detail="Las cuentas se crean desde registro; el panel administrativo no define contraseñas.")
    email = payload.email.lower()
    if db.scalar(select(models.User).where(models.User.email == email)):
        raise HTTPException(status_code=409, detail="El correo ya está registrado.")
    user = models.User(email=email, hashed_password=auth.get_password_hash(payload.password), full_name=payload.full_name.strip(), role=payload.role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@api.patch("/api/v1/admin/users/{user_id}/role", response_model=schemas.UserResponse, tags=["admin"])
def update_user_role(user_id: int, payload: schemas.RoleUpdate, current: models.User = Depends(auth.require_role("admin")), db: Session = Depends(get_db)) -> models.User:
    user = db.get(models.User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    if user.role == "admin" and payload.role != "admin" and db.scalar(select(models.User.id).where(models.User.role == "admin", models.User.is_active.is_(True), models.User.id != user.id)) is None:
        raise HTTPException(status_code=409, detail="Debe permanecer al menos un administrador activo.")
    user.role = payload.role
    db.commit()
    db.refresh(user)
    return user


@api.delete("/api/v1/admin/users/{user_id}", status_code=204, tags=["admin"])
def delete_user(user_id: int, current: models.User = Depends(auth.require_role("admin")), db: Session = Depends(get_db)) -> None:
    user = db.get(models.User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    if user.id == current.id:
        raise HTTPException(status_code=409, detail="No puedes eliminar tu propia cuenta administradora.")
    if user.role == "admin" and db.scalar(select(models.User.id).where(models.User.role == "admin", models.User.id != user.id)) is None:
        raise HTTPException(status_code=409, detail="No se puede eliminar al último administrador.")
    user.is_active = False
    db.commit()


@api.patch("/api/v1/admin/users/{user_id}/status", response_model=schemas.UserResponse, tags=["admin"])
def update_user_status(user_id: int, payload: schemas.AccountStatusUpdate, current: models.User = Depends(auth.require_role("admin")), db: Session = Depends(get_db)) -> models.User:
    user = db.get(models.User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    if user.id == current.id and not payload.is_active:
        raise HTTPException(status_code=409, detail="No puedes desactivar tu propia cuenta.")
    user.is_active = payload.is_active
    db.commit()
    db.refresh(user)
    return user


@api.patch("/api/v1/admin/users/{user_id}", response_model=schemas.UserResponse, tags=["admin"])
def update_user_profile(user_id: int, payload: schemas.UserProfileUpdate, _: models.User = Depends(auth.require_role("admin")), db: Session = Depends(get_db)) -> models.User:
    user = db.get(models.User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    email = payload.email.lower()
    duplicate = db.scalar(select(models.User.id).where(models.User.email == email, models.User.id != user_id))
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="Ese correo ya pertenece a otra cuenta.")
    user.email = email
    user.full_name = payload.full_name.strip()
    db.commit()
    db.refresh(user)
    return user


@api.get("/api/v1/admin/nodes", response_model=list[schemas.RegionNodeResponse], tags=["admin"])
def list_nodes(_: models.User = Depends(auth.require_role("admin", "analyst")), db: Session = Depends(get_db)) -> list[models.RegionNode]:
    return list(db.scalars(select(models.RegionNode).order_by(models.RegionNode.name)).all())


@api.post("/api/v1/admin/nodes", response_model=schemas.RegionNodeResponse, status_code=201, tags=["admin"])
def create_node(payload: schemas.RegionNodeCreate, _: models.User = Depends(auth.require_role("admin", "analyst")), db: Session = Depends(get_db)) -> models.RegionNode:
    if db.scalar(select(models.RegionNode.id).where(models.RegionNode.code == payload.code)) is not None:
        raise HTTPException(status_code=409, detail="Ya existe un nodo con ese código.")
    node = models.RegionNode(**payload.model_dump(), is_active=True)
    db.add(node)
    db.commit()
    db.refresh(node)
    return node


@api.patch("/api/v1/admin/nodes/{node_id}", response_model=schemas.RegionNodeResponse, tags=["admin"])
def update_node(node_id: int, payload: schemas.RegionNodeUpdate, _: models.User = Depends(auth.require_role("admin", "analyst")), db: Session = Depends(get_db)) -> models.RegionNode:
    node = db.get(models.RegionNode, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Nodo no encontrado.")
    node.name = payload.name.strip()
    node.latitude = payload.latitude
    node.longitude = payload.longitude
    node.is_active = payload.is_active
    db.commit()
    db.refresh(node)
    return node


@api.post("/api/v1/auth/login", response_model=schemas.TokenResponse, tags=["auth"])
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)) -> schemas.TokenResponse:
    user = db.scalar(select(models.User).where(models.User.email == form.username.lower()))
    if not user or not user.is_active or not auth.verify_password(form.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Correo o contraseña incorrectos.", headers={"WWW-Authenticate": "Bearer"})
    return token_for(user)


@api.post("/api/v1/inventory", response_model=schemas.InventoryResponse, status_code=201, tags=["data"])
def create_inventory(
    payload: schemas.InventoryCreate,
    user: models.User = Depends(auth.require_role("admin", "analyst")),
    db: Session = Depends(get_db),
) -> models.InventorySnapshot:
    require_catalog(payload.product_code, payload.region_code, db)
    if payload.quantity_kg <= 0:
        raise HTTPException(status_code=422, detail="La oferta disponible debe ser mayor que cero.")
    record = models.InventorySnapshot(**payload.model_dump(), created_by=user.id)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@api.post("/api/v1/demand-observations", status_code=201, tags=["data"])
async def create_observation(
    payload: schemas.DemandObservationCreate,
    user: models.User = Depends(auth.require_role("admin", "analyst")),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    require_catalog(payload.product_code, payload.region_code, db)
    region = get_region(db, payload.region_code)
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


@api.post("/api/v1/models/train", response_model=schemas.ModelResponse, tags=["models"])
def train(
    payload: schemas.TrainingRequest,
    _: models.User = Depends(auth.require_role("admin", "analyst")),
    db: Session = Depends(get_db),
) -> schemas.ModelResponse:
    require_catalog(payload.product_code, payload.region_code, db)
    try:
        artifact = ai_service.train_model(db, payload.product_code, payload.region_code)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return schemas.ModelResponse.model_validate(artifact, from_attributes=True)


@api.get("/api/v1/models", response_model=list[schemas.ModelResponse], tags=["models"])
def list_models(_: models.User = Depends(auth.require_role("admin", "analyst")), db: Session = Depends(get_db)) -> list[schemas.ModelResponse]:
    artifacts = db.scalars(select(models.ModelArtifact).where(models.ModelArtifact.is_active.is_(True)).order_by(desc(models.ModelArtifact.trained_at))).all()
    return [schemas.ModelResponse.model_validate(item, from_attributes=True) for item in artifacts]


@api.get("/api/v1/models/coverage", response_model=schemas.ObservationCoverage, tags=["models"])
def model_coverage(product_code: str, region_code: str, _: models.User = Depends(auth.require_role("admin", "analyst")), db: Session = Depends(get_db)) -> schemas.ObservationCoverage:
    require_catalog(product_code, region_code, db)
    count = db.scalar(select(func.count(models.DemandObservation.id)).where(
        models.DemandObservation.product_code == product_code,
        models.DemandObservation.region_code == region_code,
        models.DemandObservation.is_valid.is_(True),
    )) or 0
    return schemas.ObservationCoverage(product_code=product_code, region_code=region_code, valid_observations=count, minimum_required=ai_service.MINIMUM_TRAINING_ROWS)


@api.post("/api/v1/matching/engine", response_model=schemas.MatchingResponse, tags=["matching"])
async def run_matching(
    payload: schemas.MatchingRequest,
    user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
) -> schemas.MatchingResponse:
    require_catalog(payload.product_code, payload.region_code, db)
    region = get_region(db, payload.region_code)
    product = PRODUCTS[payload.product_code]
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.inventory_max_age_hours)
    inventory_query = select(models.InventorySnapshot).where(
        models.InventorySnapshot.product_code == payload.product_code,
        models.InventorySnapshot.region_code == payload.region_code,
        models.InventorySnapshot.quantity_kg > 0,
        models.InventorySnapshot.recorded_at >= cutoff,
    )
    inventory = db.scalar(
        inventory_query
        .order_by(desc(models.InventorySnapshot.recorded_at))
    )
    if inventory is None:
        message = "Registra primero tu oferta para este producto y nodo; el análisis no se ejecutó ni generó una predicción." if user.role == "viewer" else "No hay un inventario real y vigente para esta combinación. Registra la oferta antes de ejecutar el motor."
        raise HTTPException(status_code=409, detail=message)
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


@api.get("/api/v1/matching/readiness", response_model=schemas.MatchingReadiness, tags=["matching"])
def matching_readiness(
    product_code: str,
    region_code: str,
    user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
) -> schemas.MatchingReadiness:
    require_catalog(product_code, region_code, db)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.inventory_max_age_hours)
    inventory_query = select(models.InventorySnapshot.id).where(
        models.InventorySnapshot.product_code == product_code,
        models.InventorySnapshot.region_code == region_code,
        models.InventorySnapshot.quantity_kg > 0,
        models.InventorySnapshot.recorded_at >= cutoff,
    )
    has_inventory = db.scalar(inventory_query.limit(1)) is not None
    has_model = db.scalar(select(models.ModelArtifact.id).where(
        models.ModelArtifact.product_code == product_code,
        models.ModelArtifact.region_code == region_code,
        models.ModelArtifact.is_active.is_(True),
    ).limit(1)) is not None
    return schemas.MatchingReadiness(has_inventory=has_inventory, has_model=has_model, can_run=has_inventory and has_model)


@api.get("/api/v1/matching/availability", response_model=list[schemas.ScenarioAvailability], tags=["matching"])
def matching_availability(user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)) -> list[schemas.ScenarioAvailability]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.inventory_max_age_hours)
    active_models = {(product, region) for product, region in db.execute(select(models.ModelArtifact.product_code, models.ModelArtifact.region_code).where(models.ModelArtifact.is_active.is_(True))).all()}
    stocked = {(product, region) for product, region in db.execute(select(models.InventorySnapshot.product_code, models.InventorySnapshot.region_code).where(models.InventorySnapshot.quantity_kg > 0, models.InventorySnapshot.recorded_at >= cutoff)).all()}
    return [
        schemas.ScenarioAvailability(product_code=product, region_code=region, available=(product, region) in stocked)
        for product, region in sorted(active_models)
    ]

# Wrap the complete ASGI application so CORS headers also reach unhandled
# exceptions converted to 500 responses by Starlette's server error layer.
app = CORSMiddleware(
    api,
    allow_origins=list(dict.fromkeys([origin.rstrip("/") for origin in settings.cors_origins] + ["https://forenode-frontend.vercel.app"])),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["X-Request-ID"],
    max_age=600,
)
