from fastapi import FastAPI, Request, HTTPException, Query, Depends
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
import os
from dotenv import load_dotenv
import cohere
import urllib.parse
from functools import wraps
import random
import string
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base, relationship, Session
from datetime import datetime
import logging

# Add these at the top of your file with other constants
EMBED_MODEL = "embed-english-v3.0"
EMBED_DIMENSIONS = 1024

# ===============================
# Application Initialization
# ===============================

app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# Load environment variables from .env file
load_dotenv()

# Configure environment variables
DATABASE_URL = os.getenv('DATABASE_URL')
COHERE_API_KEY = os.getenv('YOUR_COHERE_API_KEY')

# Initialize Cohere client
try:
    co = cohere.Client(COHERE_API_KEY)
except Exception as e:
    logging.error(f"Cohere client initialization error: {str(e)}")
    raise

# SQLAlchemy setup
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Define your database models here
class PhoneNumber(Base):
    __tablename__ = "phone_numbers"
    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, unique=True, index=True)
    instagram_username = Column(String, unique=True, index=True, nullable=True)
    is_activated = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    outfits = relationship("Outfit", back_populates="phone")
    referral_codes = relationship("ReferralCode", back_populates="phone")

class Outfit(Base):
    __tablename__ = "outfits"
    id = Column(Integer, primary_key=True, index=True)
    phone_id = Column(Integer, ForeignKey("phone_numbers.id"))
    image_data = Column(String)
    description = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    phone = relationship("PhoneNumber", back_populates="outfits")
    items = relationship("Item", back_populates="outfit")

class Item(Base):
    __tablename__ = "items"
    id = Column(Integer, primary_key=True, index=True)
    outfit_id = Column(Integer, ForeignKey("outfits.id"))
    description = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    outfit = relationship("Outfit", back_populates="items")
    links = relationship("Link", back_populates="item")

class Link(Base):
    __tablename__ = "links"
    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, ForeignKey("items.id"))
    photo_url = Column(String, nullable=True)
    url = Column(String)
    price = Column(String, nullable=True)
    title = Column(String, nullable=True)
    rating = Column(String, nullable=True)
    reviews_count = Column(String, nullable=True)
    merchant_name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    item = relationship("Item", back_populates="links")

class ReferralCode(Base):
    __tablename__ = "referral_codes"
    id = Column(Integer, primary_key=True, index=True)
    phone_id = Column(Integer, ForeignKey("phone_numbers.id"))
    code = Column(String, unique=True, index=True)
    used_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    phone = relationship("PhoneNumber", back_populates="referral_codes")

# Create tables if they don't exist
Base.metadata.create_all(bind=engine)

# ===============================
# Utility Functions
# ===============================

def get_db():
    """
    Dependency function to yield a database session
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def validate_environment():
    """
    Validate that all required environment variables are set.
    Raises EnvironmentError if any required variables are missing.
    """
    missing_vars = []
    if not DATABASE_URL:
        missing_vars.append('DATABASE_URL')
    if not COHERE_API_KEY:
        missing_vars.append('YOUR_COHERE_API_KEY')

    if missing_vars:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing_vars)}. "
            "Please set these in your .env file or deployment environment."
        )

def format_phone_number(phone_number: str):
    """
    Standardize phone number format to include +1 prefix and remove special characters.
    """
    phone_number = phone_number.strip().replace("-", "").replace("(", "").replace(")", "").replace(" ", "")
    if not phone_number.startswith("+1"):
        phone_number = "+1" + phone_number
    return phone_number

def clean_url(url: str):
    """
    Clean and standardize URLs:
    - Remove Google redirect prefixes
    - Ensure https:// prefix
    - URL decode the string
    """
    if not url:
        return ''

    if url.startswith('/url?q='):
        url = url[7:]

    try:
        url = urllib.parse.unquote(url)
    except Exception:
        pass

    if not url.startswith('http://') and not url.startswith('https://'):
        url = 'https://' + url

    return url

# ===============================
# Decorators
# ===============================

def handle_errors(f):
    """
    Decorator to standardize error handling across routes.
    """
    @wraps(f)
    async def wrapper(*args, **kwargs):
        try:
            return await f(*args, **kwargs)
        except psycopg2.Error as e:
            logging.error(f"Database error: {str(e)}")
            return JSONResponse({'error': 'Database error occurred'}, status_code=500)
        except Exception as e:
            logging.error(f"Unexpected error: {str(e)}")
            return JSONResponse({'error': 'An unexpected error occurred'}, status_code=500)
    return wrapper

# ===============================
# Route Handlers
# ===============================

@app.post('/rag_search')
@handle_errors
async def rag_search(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    item_description = data.get("item_description")
    if not item_description:
        raise HTTPException(status_code=400, detail="Item description is required")

    query_embedding = co.embed(
        texts=[item_description],
        model=EMBED_MODEL,
        input_type="search_query"
    ).embeddings[0]

    result = db.execute(
        """
        SELECT item_id, embedding <=> :query_embedding AS distance
        FROM item_embeddings
        ORDER BY distance ASC
        LIMIT 1
        """,
        {"query_embedding": query_embedding}
    ).fetchone()

    if not result:
        raise HTTPException(status_code=404, detail="No matching items found")

    return {"item_id": result[0]}

@app.get('/api/items')
@handle_errors
async def get_items(outfit_id: int = Query(..., description="ID of the outfit"), db: Session = Depends(get_db)):
    """
    Retrieve all items for a specific outfit along with links.
    """
    items = db.query(Item).filter(Item.outfit_id == outfit_id).all()
    if not items:
        raise HTTPException(status_code=404, detail="No items found for this outfit")

    results = []
    for item in items:
        links = db.query(Link).filter(Link.item_id == item.id).all()
        formatted_links = [{
            "id": link.id,
            "photo_url": link.photo_url,
            "url": clean_url(link.url),
            "price": link.price,
            "title": link.title,
            "rating": link.rating,
            "reviews_count": link.reviews_count,
            "merchant_name": link.merchant_name
        } for link in links]

        results.append({
            "item_id": item.id,
            "description": item.description,
            "links": formatted_links
        })

    return results

@app.get('/api/outfits')
@handle_errors
async def get_outfits(page: int = Query(1, ge=1, description="Page number"), per_page: int = Query(10, ge=1, description="Items per page"), db: Session = Depends(get_db)):
    """
    Retrieve paginated list of all outfits.
    """
    offset = (page - 1) * per_page
    outfits = db.query(Outfit).order_by(Outfit.created_at.desc()).offset(offset).limit(per_page).all()

    if not outfits:
        raise HTTPException(status_code=404, detail="No outfits found")

    return [{
        "id": outfit.id,
        "image_data": outfit.image_data,
        "description": outfit.description,
        "created_at": outfit.created_at
    } for outfit in outfits]

# ===============================
# Final Initialization
# ===============================

validate_environment()
logging.info("Application started successfully.")
