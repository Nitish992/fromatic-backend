from sqlalchemy.orm import sessionmaker, relationship, Session
from sqlalchemy import create_engine
from app.models import Base

# Database setup
DATABASE_URL = "postgresql://genieform_owner:obkpFTI1Cd5N@ep-ancient-night-a11fkbyj.ap-southeast-1.aws.neon.tech/genieform?sslmode=require"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create the database tables
Base.metadata.create_all(bind=engine)


# Dependency for getting the database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()