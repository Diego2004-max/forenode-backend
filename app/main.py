from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime, timedelta
import httpx
from . import models, database, ai_service, auth

models.Base.metadata.create_all(bind=database.engine)

app = FastAPI(
    title="Forenode Global AI Enterprise Engine",
    description="Enterprise Agricultural Logistics & Supply-Demand Matching Platform",
    version="4.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Ruta raíz para evitar el 404 en Render y mantener el servicio activo
@app.get("/")
def read_root():
    return {"status": "online", "message": "Forenode Global AI Enterprise Engine is running successfully."}

class UserRegister(BaseModel):
    email: str
    password: str
    full_name: str

class Token(BaseModel):
    access_token: str
    token_type: str
    full_name: str
    email: str

class GlobalPredictionRequest(BaseModel):
    product_id: int
    product_name: str
    region_name: str
    latitude: float
    longitude: float
    target_date: datetime

class MatchingResponse(BaseModel):
    product_id: int
    product_name: str
    region_name: str
    target_date: datetime
    forecast_temperature_c: float
    forecast_rainfall_mm: float
    predicted_demand_kg: float
    available_supply_kg: float
    deficit_or_surplus_kg: float
    market_status: str
    confidence_score: float

@app.post("/api/v1/auth/register", response_model=Token, status_code=status.HTTP_201_CREATED)
def register_user(user_data: UserRegister, db: Session = Depends(database.get_db)):
    existing_user = db.query(models.User).filter(models.User.email == user_data.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_pwd = auth.get_password_hash(user_data.password)
    new_user = models.User(
        email=user_data.email,
        hashed_password=hashed_pwd,
        full_name=user_data.full_name
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    access_token = auth.create_access_token(
        data={"sub": new_user.email}, expires_delta=timedelta(minutes=1440)
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "full_name": new_user.full_name,
        "email": new_user.email
    }

@app.post("/api/v1/auth/login", response_model=Token)
def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(database.get_db)):
    user = db.query(models.User).filter(models.User.email == form_data.username).first()
    if not user or not auth.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = auth.create_access_token(
        data={"sub": user.email}, expires_delta=timedelta(minutes=1440)
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "full_name": user.full_name,
        "email": user.email
    }

@app.post("/api/v1/matching/engine", response_model=MatchingResponse)
async def run_matching_engine(
    request: GlobalPredictionRequest,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(database.get_db)
):
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={request.latitude}&longitude={request.longitude}&current=temperature_2m,precipitation"
        async with httpx.AsyncClient() as client:
            res = await client.get(url, timeout=5.0)
            data = res.json() if res.status_code == 200 else {}
            current = data.get("current", {})
            temp = float(current.get("temperature_2m", 15.0))
            rain = float(current.get("precipitation", 35.0))

        month = request.target_date.month
        base_predicted = ai_service.ai_model_instance.predict_demand(month=month, temp=temp, rain=rain)
        
        multiplier = 1.0
        if request.product_id == 2:  # Papa Pastusa
            multiplier = 2.4
        elif request.product_id == 4:  # Quinoa
            multiplier = 0.8
        elif request.product_id == 3:  # Lulo
            multiplier = 1.3

        predicted_kg = round(base_predicted * multiplier, 2)
        available_supply = round(950.0 + (request.product_id * 180.0) - (rain * 3.5), 2)
        gap = round(predicted_kg - available_supply, 2)
        
        if gap > 150:
            market_status = "Déficit Crítico (Riesgo de desabastecimiento regional)"
        elif gap < -150:
            market_status = "Superávit Alto (Riesgo de merma y desperdicio)"
        else:
            market_status = "Equilibrio Óptimo de Mercado"

        confidence = round(0.96 - (abs(rain - 30) * 0.001), 2)
        confidence = max(0.75, min(0.98, confidence))

        product = db.query(models.Product).filter(models.Product.id == request.product_id).first()
        if not product:
            product = models.Product(
                id=request.product_id,
                name=request.product_name,
                category="Enterprise Global Agro",
                region=request.region_name,
                latitude=request.latitude,
                longitude=request.longitude
            )
            db.merge(product)
            db.commit()

        db_pred = models.DemandPrediction(
            product_id=request.product_id,
            target_date=request.target_date,
            predicted_demand_kg=predicted_kg,
            available_supply_kg=available_supply,
            gap_status=market_status,
            confidence_score=confidence
        )
        db.add(db_pred)
        db.commit()

        return MatchingResponse(
            product_id=request.product_id,
            product_name=request.product_name,
            region_name=request.region_name,
            target_date=request.target_date,
            forecast_temperature_c=temp,
            forecast_rainfall_mm=rain,
            predicted_demand_kg=predicted_kg,
            available_supply_kg=available_supply,
            deficit_or_surplus_kg=gap,
            market_status=market_status,
            confidence_score=confidence
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Global Engine Error: {str(e)}")