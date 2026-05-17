from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool
from config import DATABASE_URL

# Create engine with proper configuration
engine = create_engine(
    DATABASE_URL,
    poolclass=NullPool,
    echo=False,
    connect_args={
        "connect_timeout": 10,
        "options": "-c timezone=UTC"
    }
)

# Create session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

# Base class for models
Base = declarative_base()

# Dependency to get database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Initialize database (create tables)
def init_db():
    Base.metadata.create_all(bind=engine)
