# Forenode AI — Backend

API de Forenode AI Enterprise Core V4.0 para autenticación, trazabilidad de datos, entrenamiento de modelos y balance logístico agrícola.

## Principios del motor

- No genera oferta ni demanda sintética en producción.
- Cada inventario exige fecha y referencia de origen.
- El clima histórico o pronosticado se obtiene desde Open-Meteo.
- Cada combinación producto–región requiere al menos 12 observaciones antes de entrenarse.
- Los artefactos `joblib` y sus métricas se versionan en PostgreSQL.
- La confianza deriva del error absoluto validado temporalmente.

## Desarrollo local

1. Crea un entorno virtual e instala `requirements-dev.txt`.
2. Copia `.env.example` a `.env` y completa las variables.
3. Ejecuta `uvicorn app.main:app --reload`.
4. Abre `http://localhost:8000/docs`.

```bash
python -m pip install -r requirements-dev.txt
uvicorn app.main:app --reload
pytest -q
```

## Flujo de datos

1. Registra demanda histórica mediante `POST /api/v1/demand-observations`.
2. Entrena el modelo con `POST /api/v1/models/train`.
3. Registra la oferta vigente en `POST /api/v1/inventory`.
4. Ejecuta `POST /api/v1/matching/engine`.

Los endpoints operativos requieren un Bearer token emitido por la API o por Supabase Auth.

La autenticación propia utiliza la tabla `forenode_users` para mantener aislado el esquema Enterprise de tablas `users` heredadas de prototipos anteriores.

## Variables de producción

`DATABASE_URL`, `JWT_SECRET`, `CORS_ORIGINS` y `SUPABASE_URL` son obligatorias para un despliegue completo. `SUPABASE_JWT_SECRET` solo se necesita en proyectos Supabase que todavía firman tokens con HS256.

