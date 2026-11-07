import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./forenode_test.db")
os.environ.setdefault("JWT_SECRET", "test-secret-with-at-least-thirty-two-characters")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:4200")

