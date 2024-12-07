from fastapi import FastAPI, Request, HTTPException, Query
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
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime

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
    print(f"Cohere client initialization error: {str(e)}")
    raise

# SQLAlchemy setup
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Define your database models here (same as your wha7_models.py)
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

class Referral(Base):
    __tablename__ = "referrals"
    id = Column(Integer, primary_key=True, index=True)
    referrer_id = Column(Integer, ForeignKey("phone_numbers.id"))
    referred_id = Column(Integer, ForeignKey("phone_numbers.id"))
    code_used = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

# Create tables if they don't exist
Base.metadata.create_all(bind=engine)

# ===============================
# Utility Functions
# ===============================

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

def get_db():
    """
    Dependency function to yield a database session
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

async def handle_errors(f):
    """
    Decorator to standardize error handling across routes.
    Catches and logs errors, returns appropriate HTTP responses.
    """
    @wraps(f)
    async def wrapper(*args, **kwargs):
        try:
            return await f(*args, **kwargs)
        except psycopg2.Error as e:
            print(f"Database error: {str(e)}")
            return JSONResponse({'error': 'Database error occurred'}, status_code=500)
        except Exception as e:
            print(f"Unexpected error: {str(e)}")
            return JSONResponse({'error': 'An unexpected error occurred'}, status_code=500)
    return wrapper

def get_data_from_db_combined(db: SessionLocal, phone_number: str = None, instagram_username: str = None, page: int = 1, per_page: int = 10):
    """
    Retrieve paginated outfit data for either a phone number or Instagram username or both.
    """
    print(f"Phone Number: {phone_number} \n instagram username {instagram_username}")
    try:
        query = db.query(Outfit.id, Outfit.image_data, Outfit.description).join(PhoneNumber)
        if phone_number:
            query = query.filter(PhoneNumber.phone_number == phone_number)
        if instagram_username:
            query = query.filter(PhoneNumber.instagram_username == instagram_username)
        outfits = query.order_by(Outfit.id.desc()).offset((page - 1) * per_page).limit(per_page).all()
        return outfits
    except Exception as e:
        print(f"Database error: {e}")
        return None

def link_instagram_to_phone(db: SessionLocal, phone_number: str, instagram_username: str):
    """
    Link an Instagram username to an existing phone number.
    Returns (success, message) tuple.
    """
    try:
        # Format phone number
        phone_number = format_phone_number(phone_number)
        # Remove @ symbol if present
        instagram_username = instagram_username.lstrip('@')
        
        # First check if phone number exists
        user = db.query(PhoneNumber).filter(PhoneNumber.phone_number == phone_number).first()
        if not user:
            return False, "Phone number not found"
            
        # Then check if Instagram username is already taken by another user
        existing = db.query(PhoneNumber).filter(PhoneNumber.instagram_username == instagram_username, PhoneNumber.phone_number != phone_number).first()
        if existing:
            return False, "Instagram username already linked to another account"
        
        # Update the record
        user.instagram_username = instagram_username
        db.commit()
        return True, "Successfully linked Instagram username"
        
    except Exception as e:
        db.rollback()
        print(f"Database error: {e}")
        return False, str(e)

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
    except:
        pass
    
    if not url.startswith('http://') and not url.startswith('https://'):
        url = 'https://' + url
    
    return url

# ===============================
# Database Operations
# ===============================

def generate_referral_code(db: SessionLocal):
    """Generate a unique 6-character referral code"""
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if not db.query(ReferralCode).filter(ReferralCode.code == code).first():
            return code

def get_items_from_db(db: SessionLocal, outfit_id: int):
    """
    Retrieve all items and their associated links for a given outfit ID.
    Returns a list of items with their links, sorted by rating and review count.
    """
    try:
        # Get items
        items = db.query(Item).filter(Item.outfit_id == outfit_id).all()
        items_with_links = []
        
        # Get links for each item
        for item in items:
            links = db.query(Link).filter(Link.item_id == item.id).order_by(
                Link.rating.desc(),
                Link.reviews_count.desc()
            ).all()
            
            formatted_links = [{
                'id': link.id,
                'photo_url': link.photo_url,
                'url': link.url,
                'price': link.price,
                'title': link.title,
                'rating': link.rating,
                'reviews_count': link.reviews_count,
                'merchant_name': link.merchant_name
            } for link in links]
            
            items_with_links.append({
                'item_id': item.id,
                'outfit_id': item.outfit_id,
                'description': item.description,
                'links': formatted_links
            })
        return items_with_links
    except Exception as e:
        print(f"Database error: {e}")
        return None

def get_all_data_from_db(db: SessionLocal, page: int, per_page: int):
    """
    Retrieve paginated outfit data from the database.
    """
    try:
        outfits = db.query(Outfit.id, Outfit.image_data, Outfit.description).order_by(Outfit.id.desc()).offset((page - 1) * per_page).limit(per_page).all()
        return outfits
    except Exception as e:
        print(f"Database error: {e}")
        return None

def get_data_from_db(db: SessionLocal, phone_number: str, page: int, per_page: int):
    """
    Retrieve paginated outfit data for a specific phone number.
    """
    try:
        outfits = db.query(Outfit.id, Outfit.image_data, Outfit.description).join(PhoneNumber).filter(PhoneNumber.phone_number == phone_number).order_by(Outfit.id.desc()).offset((page - 1) * per_page).limit(per_page).all()
        return outfits
    except Exception as e:
        print(f"Database error: {e}")
        return None

def generate_and_store_embeddings(db: SessionLocal):
    """Generate embeddings for all clothing items and store them in the database."""
    try:
        # Enable vector extension
        db.execute("CREATE EXTENSION IF NOT EXISTS vector SCHEMA public;")
        db.commit()

        # Drop existing table if it exists with wrong dimensions
        db.execute("DROP TABLE IF EXISTS item_embeddings;")
        
        # Create embeddings table with correct dimensions (1024 for embed-english-v3.0)
        db.execute(f"""
            CREATE TABLE IF NOT EXISTS item_embeddings (
                item_id INT PRIMARY KEY,
                embedding vector({EMBED_DIMENSIONS})
            )
        """)
        db.commit()

        # First check if there are any items to process
        count = db.query(Item).count()
        
        if count == 0:
            print("No items found in the database to generate embeddings for")
            return

        # Process items in batches
        batch_size = 100
        offset = 0
        
        while True:
            items = db.query(Item.id, Item.description).filter(Item.id.notin_(db.query(Item.id).filter(Item.id == Item.id))).order_by(Item.id).offset(offset).limit(batch_size).all()
            
            if not items:
                break
            
            print(f"Processing batch of {len(items)} items")
            
            descriptions = [item[1] for item in items if item[1]]  # Filter out None descriptions
            if not descriptions:
                offset += batch_size
                continue
            
            try:
                embeddings = co.embed(
                    texts=descriptions,
                    model=EMBED_MODEL,
                    input_type="search_query"
                ).embeddings
                
                # Insert embeddings in batches
                for (item_id, _), embedding in zip(items, embeddings):
                    if embedding is not None:
                        db.execute("""
                            INSERT INTO item_embeddings (item_id, embedding) 
                            VALUES (:item_id, :embedding::vector)
                            ON CONFLICT (item_id) DO UPDATE 
                            SET embedding = EXCLUDED.embedding
                        """, {"item_id": item_id, "embedding": embedding})
                
                db.commit()
                print(f"Successfully processed batch starting at offset {offset}")
                
            except Exception as e:
                print(f"Error processing batch at offset {offset}: {str(e)}")
                db.rollback()
            
            offset += batch_size

    except Exception as e:
        print(f"Failed to generate embeddings: {str(e)}")
        raise

def get_data_from_db_by_instagram(db: SessionLocal, instagram_username: str, page: int, per_page: int):
    """
    Retrieve paginated outfit data for a specific Instagram username.
    """
    try:
        outfits = db.query(Outfit.id, Outfit.image_data, Outfit.description).join(PhoneNumber).filter(PhoneNumber.instagram_username == instagram_username).order_by(Outfit.id.desc()).offset((page - 1) * per_page).limit(per_page).all()
        return outfits
    except Exception as e:
        print(f"Database error: {e}")
        return None

# ===============================
# Route Handlers
# ===============================

@app.post("/api/referral/check")
async def check_referral_code(request: Request, db: SessionLocal = Depends(get_db)):
    """Check if user already has a referral code"""
    data = await request.json()
    phone_number = data.get('phone_number')
    if not phone_number:
        raise HTTPException(status_code=400, detail="Phone number required")
        
    user = db.query(PhoneNumber).filter(PhoneNumber.phone_number == phone_number).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    # Get most recent referral code
    code = db.query(ReferralCode).filter(ReferralCode.phone_id == user.id).order_by(ReferralCode.created_at.desc()).first()
    
    if code:
        return {"code": code.code}
    else:
        return {"code":       None}

@app.post("/api/referral/generate")
async def generate_code(request: Request, db: SessionLocal = Depends(get_db)):
    """Generate a new referral code for user"""
    data = await request.json()
    phone_number = data.get('phone_number')
    if not phone_number:
        raise HTTPException(status_code=400, detail="Phone number required")
        
    user = db.query(PhoneNumber).filter(PhoneNumber.phone_number == phone_number).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    # Generate new code
    code = generate_referral_code(db)  # Your existing function
    new_code = ReferralCode(phone_id=user.id, code=code)
    db.add(new_code)
    db.commit()
    
    return {"code": code}

@app.post('/api/user/check_activation')
async def check_activation(request: Request, db: SessionLocal = Depends(get_db)):
    data = await request.json()
    phone_number = data.get('phone_number')
    if not phone_number:
        raise HTTPException(status_code=400, detail='Phone number required')
        
    phone_number = format_phone_number(phone_number)
    user = db.query(PhoneNumber).filter(PhoneNumber.phone_number == phone_number).first()
    
    if not user:
        # New user
        return {
            'is_activated': False,
            'needs_referral': True,
            'message': 'Please enter a referral code to activate your account'
        }
    
    return {
        'is_activated': user.is_activated,
        'needs_referral': not user.is_activated,
        'message': 'Please enter a referral code to activate your account' if not user.is_activated else None
    }

@app.post("/api/referral/validate")
async def validate_referral(request: Request, db: SessionLocal = Depends(get_db)):
    try:
        print("Received referral validation request")
        data = await request.json()
        code = data.get('code')
        new_user_phone = data.get('phone_number')
        
        print(f"Processing code: {code} for phone: {new_user_phone}")
        
        if not code or not new_user_phone:
            return JSONResponse({
                "error": "Code and phone number required",
                "is_activated": False,
                "needs_referral": True
            }, status_code=400)
        
        referral_code = db.query(ReferralCode).filter(ReferralCode.code == code).first()
        if not referral_code:
            return JSONResponse({
                "error": "Invalid referral code",
                "is_activated": False,
                "needs_referral": True
            }, status_code=404)
        
        new_user = db.query(PhoneNumber).filter(PhoneNumber.phone_number == new_user_phone).first()
        
        if new_user and new_user.is_activated:
            return {
                "is_activated": True,
                "needs_referral": False,
                "message": "User already activated"
            }
        
        if not new_user:
            new_user = PhoneNumber(phone_number=new_user_phone)
            db.add(new_user)
            db.commit()  # Commit to get the new user's ID
            
        referral = Referral(
            referrer_id=referral_code.phone_id,
            referred_id=new_user.id,
            code_used=code
        )
        
        referral_code.used_count += 1
        new_user.is_activated = True
        
        db.add(referral)
        db.commit()
        
        return {
            "is_activated": True,
            "needs_referral": False,
            "message": "Account successfully activated"
        }
        
    except Exception as e:
        db.rollback()
        print(f"Error in validate_referral: {str(e)}")
        return JSONResponse({
            "error": "Server error",
            "is_activated": False,
            "needs_referral": True,
            "message": str(e)
        }, status_code=500)

@app.post('/rag_search')
@handle_errors
async def rag_search(request: Request, db: SessionLocal = Depends(get_db)):
    data = await request.json()
    item_description = data.get("item_description")
    if not item_description:
        raise HTTPException(status_code=400, detail="Item description is required")

    query_embedding = co.embed(
        texts=[item_description], 
        model=EMBED_MODEL,  # Fixed model name
        input_type="search_query"
    ).embeddings[0]
    
    result = db.execute("""
        SELECT item_id, embedding <=> :query_embedding::vector as distance
        FROM item_embeddings
        ORDER BY distance ASC
        LIMIT 1
    """, {"query_embedding": query_embedding}).fetchone()
        
    if not result:
        raise HTTPException(status_code=404, detail="No matching items found")
    # Change the response format to match what Swift expects   
    return {"item_id": result[0]}  # Return as item_id, not item_id

@app.get('/api/links')
@handle_errors
async def api_links(item_id: int = Query(..., description="ID of the item")):
    """
    Retrieve all links for a specific item.
    Requires item_id query parameter.
    Returns sorted list of links with their details.
    """

    db = SessionLocal()
    
    links = db.query(Link).filter(Link.item_id == item_id).order_by(
        Link.rating.desc(),
        Link.reviews_count.desc()
    ).all()

    formatted_links = [{
        'id': link.id,
        'photo_url': link.photo_url,
        'url': link.url,
        'price': link.price,
        'title': link.title,
        'rating': link.rating,
        'reviews_count': link.reviews_count,
        'merchant_name': link.merchant_name
    } for link in links]
    db.close()
    return formatted_links

@app.get('/api/items')
@handle_errors
async def api_items(outfit_id: int = Query(..., description="ID of the outfit")):
    """
    Retrieve all items for a specific outfit.
    Requires outfit_id query parameter.
    Returns items with their associated links.
    """
    
    db = SessionLocal()
    items = get_items_from_db(db, outfit_id)
    if items is None:
        raise HTTPException(status_code=500, detail='Database error')
    if len(items) == 0:
        raise HTTPException(status_code=404, detail='No items found for this outfit')
        
    # Clean URLs in response
    for item in items:
        if 'links' in item:
            for link in item['links']:
                if 'url' in link:
                    link['url'] = clean_url(link['url'])
    db.close()
    return items

@app.get('/api/data_all')
@handle_errors
async def api_data_all(
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(10, ge=1, description="Items per page")
):
    """
    Retrieve paginated list of all outfits.
    Supports page and per_page query parameters for pagination.
    """
    
    db = SessionLocal()
    data = get_all_data_from_db(db, page, per_page)
    if data is None:
        raise HTTPException(status_code=500, detail='Database error')
    if len(data) == 0:
        raise HTTPException(status_code=404, detail='No outfits found')
        
    data_list = [{'outfit_id': outfit_id, 'image_data': image_data, 'description': description} 
                 for outfit_id, image_data, description in data]
    db.close()
    return {
        'outfits': data_list,
        'has_more': len(data_list) == per_page
    }

@app.get('/api/data')
@handle_errors
async def api_data(
    phone_number: str = Query(None, description="Phone number of the user"),
    instagram_username: str = Query(None, description="Instagram username of the user"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(10, ge=1, description="Items per page")
):
    """
    Retrieve paginated list of outfits for a phone number and/or Instagram username.
    """
   
    if not phone_number and not instagram_username:
        raise HTTPException(status_code=400, detail='Either phone number or Instagram username is required')
        
    if phone_number:
        phone_number = format_phone_number(phone_number)
    if instagram_username:
        instagram_username = instagram_username.lstrip('@')
    
    db = SessionLocal()
    data = get_data_from_db_combined(db, phone_number, instagram_username, page, per_page)
    
    if data is None:
        raise HTTPException(status_code=500, detail='Database error')
    if len(data) == 0:
        raise HTTPException(status_code=404, detail='No outfits found')
        
    data_list = [{'outfit_id': outfit_id, 'image_data': image_data, 'description': description} 
                 for outfit_id, image_data, description in data]
    db.close()
    return {
        'outfits': data_list,
        'has_more': len(data_list) == per_page
    }


# Create initialization route
@app.on_event("startup")
@handle_errors
async def startup_event():
    """Route to trigger initialization - should be called once after deployment"""
    db = SessionLocal()
    initialize_app(db)
    db.close()
    print("initialization complete")


# Add new database function for Instagram username queries
# Add new route for Instagram username queries
@app.get('/api/data/instagram')
@handle_errors
async def api_data_instagram(
    instagram_username: str = Query(..., description="Instagram username of the user"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(10, ge=1, description="Items per page")
):
    """
    Retrieve paginated list of outfits for a specific Instagram username.
    Requires instagram_username query parameter.
    Supports page and per_page query parameters for pagination.
    """
   
    # Remove @ symbol if present
    instagram_username = instagram_username.lstrip('@')
    
    db = SessionLocal()
    data = get_data_from_db_by_instagram(db, instagram_username, page, per_page)
    
    if data is None:
        raise HTTPException(status_code=500, detail='Database error')
    if len(data) == 0:
        raise HTTPException(status_code=404, detail=f'No outfits found for Instagram username: {instagram_username}')
        
    data_list = [{'outfit_id': outfit_id, 'image_data': image_data, 'description': description} 
                 for outfit_id, image_data, description in data]
    db.close()
    return {
        'outfits': data_list,
        'has_more': len(data_list) == per_page
    }

# ===============================
# Application Initialization
# ===============================


def initialize_app(db: SessionLocal):
    """Initialize the application and set up necessary components."""
    validate_environment()
    try:
        generate_and_store_embeddings(db)
    except Exception as e:
        print(f"Failed to generate embeddings: {str(e)}")

# Add these functions after the other database operations

def check_instagram_username(db: SessionLocal, instagram_username: str):
    """
    Check if an Instagram username already exists in the database.
    Returns the associated phone number if found, None otherwise.
    """
    try:
        result = db.query(PhoneNumber.phone_number).filter(PhoneNumber.instagram_username == instagram_username).first()
        return result[0] if result else None
        
    except Exception as e:
        print(f"Database error: {e}")
        return None

# Add this after the other Instagram-related functions

def unlink_instagram(db: SessionLocal, phone_number: str):
    """
    Remove Instagram username association from a phone number.
    Returns (success, message) tuple.
    """
    try:
        # Format phone number
        phone_number = format_phone_number(phone_number)
        
        # Check if phone number exists
        user = db.query(PhoneNumber).filter(PhoneNumber.phone_number == phone_number).first()
        if not user:
            return False, "Phone number not found"
        
        # Remove Instagram username
        user.instagram_username = None
        db.commit()
        return True, "Successfully unlinked Instagram username"
        
    except Exception as e:
        db.rollback()
        print(f"Database error: {e}")
        return False, str(e)

# Modify the existing link_instagram route to match Swift app expectations
@app.post('/api/instagram/link')
@handle_errors
async def link_instagram(request: Request, db: SessionLocal = Depends(get_db)):
    """
    Link an Instagram username to an existing phone number.
    """
    data = await request.json()
    phone_number = data.get('phone_number')
    instagram_username = data.get('instagram_username')
    
    if not phone_number or not instagram_username:
        raise HTTPException(status_code=400, detail='Both phone number and Instagram username are required')
    
    success, message = link_instagram_to_phone(db, phone_number, instagram_username)
    
    if success:
        return {"username": instagram_username}
    else:
        raise HTTPException(status_code=400, detail=message)

# Add new unlink endpoint
@app.post('/api/instagram/unlink')
@handle_errors
async def unlink_instagram_route(request: Request, db: SessionLocal = Depends(get_db)):
    """
    Remove Instagram username association from a phone number.
    """
    data = await request.json()
    phone_number = data.get('phone_number')
    
    if not phone_number:
        raise HTTPException(status_code=400, detail='Phone number is required')
    
    success, message = unlink_instagram(db, phone_number)
    
    if success:
        return {'message': message}
    else:
        raise HTTPException(status_code=400, detail=message)

# Add new routes
@app.get('/api/instagram/check')
@handle_errors
async def check_instagram(
    instagram_username: str = Query(..., description="Instagram username to check")
):
    """
    Check if an Instagram username is already in use.
    """

    instagram_username = instagram_username.lstrip('@')
    db = SessionLocal()
    existing_phone = check_instagram_username(db, instagram_username)
    db.close()
    return {
        'is_taken': existing_phone is not None,
        'phone_number': existing_phone if existing_phone else None
    }
