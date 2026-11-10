from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    full_name: str = Field(min_length=2, max_length=160)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    full_name: str
    email: EmailStr
    role: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: EmailStr
    full_name: str
    role: str
    is_active: bool = True


class RoleUpdate(BaseModel):
    role: str = Field(pattern="^(viewer|analyst|admin)$")


class AccountStatusUpdate(BaseModel):
    is_active: bool


class UserProfileUpdate(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    email: EmailStr


class RegionNodeCreate(BaseModel):
    code: str = Field(pattern="^[a-z0-9-]{2,40}$")
    name: str = Field(min_length=2, max_length=120)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class RegionNodeUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    is_active: bool


class RegionNodeResponse(RegionNodeCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    is_active: bool


class AdminUserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    full_name: str = Field(min_length=2, max_length=160)
    role: str = Field(default="viewer", pattern="^(viewer|analyst|admin)$")


class InventoryCreate(BaseModel):
    product_code: str
    region_code: str
    quantity_kg: float = Field(ge=0)
    recorded_at: datetime
    source_reference: str = Field(min_length=3, max_length=500)


class InventoryResponse(InventoryCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


class DemandObservationCreate(BaseModel):
    product_code: str
    region_code: str
    observed_on: date
    demand_kg: float = Field(gt=0)
    source_reference: str = Field(min_length=3, max_length=500)


class TrainingRequest(BaseModel):
    product_code: str
    region_code: str


class ModelResponse(BaseModel):
    version: str
    product_code: str
    region_code: str
    training_rows: int
    mae_kg: float
    r2_score: float
    residual_p90_kg: float


class MatchingRequest(BaseModel):
    product_code: str
    region_code: str
    target_date: date


class MatchingReadiness(BaseModel):
    has_inventory: bool
    has_model: bool
    can_run: bool


class ScenarioAvailability(BaseModel):
    product_code: str
    region_code: str
    available: bool


class ObservationCoverage(BaseModel):
    product_code: str
    region_code: str
    valid_observations: int
    minimum_required: int


class WeatherResponse(BaseModel):
    temperature_c: float
    precipitation_mm: float
    observed_or_forecast: str
    source: str


class MatchingResponse(BaseModel):
    run_id: int
    product_code: str
    product_name: str
    region_code: str
    region_name: str
    target_date: date
    weather: WeatherResponse
    predicted_demand_kg: float
    demand_lower_kg: float
    demand_upper_kg: float
    available_supply_kg: float
    inventory_recorded_at: datetime
    inventory_source: str
    gap_kg: float
    market_status: str
    confidence_score: float
    model_version: str
    model_mae_kg: float
    explanation: str


class CatalogResponse(BaseModel):
    regions: list[dict[str, str | float]]
    products: list[dict[str, str]]

