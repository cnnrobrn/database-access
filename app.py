"""
Flask Application for Product Search and Management
------------------------------------------------
This application provides a REST API for searching products, managing outfits,
and handling product links using vector embeddings for similarity search.
Main Features:
- RAG (Retrieval-Augmented Generation) search using Cohere embeddings
- Product and outfit management
- Link tracking and organization
- Phone number-based user management
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import psycopg2
import os
from dotenv import load_dotenv
import cohere
import urllib.parse
from functools import wraps
import random
import string
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from wha7_models import Base, init_db, PhoneNumber, Outfit, Item, Link, ReferralCode, Referral

# Add these at the top of your file with other constants
EMBED_MODEL = "embed-english-v3.0"
EMBED_DIMENSIONS = 1024

# ===============================
# Application Initialization
# ===============================

app = Flask(__name__)
CORS(app)

# Load environment variables from .env file
load_dotenv()

# Configure environment variables
DATABASE_URL = os.getenv('DATABASE_URL')
COHERE_API_KEY = os.getenv('YOUR_COHERE_API_KEY')

# Configure SQLAlchemy
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize SQLAlchemy
db = SQLAlchemy(app)

# Initialize database connection from wha7_models
engine, session_factory = init_db()

# Create tables if they don't exist
with app.app_context():
    db.create_all()
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

def get_db_connection():
    """
    Create and return a new database connection.
    Raises exception if connection fails.
    """
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except Exception as e:
        app.logger.error(f"Database connection error: {str(e)}")
        raise

def handle_errors(f):
    """
    Decorator to standardize error handling across routes.
    Catches and logs errors, returns appropriate HTTP responses.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except psycopg2.Error as e:
            app.logger.error(f"Database error: {str(e)}")
            return jsonify({'error': 'Database error occurred'}), 500
        except Exception as e:
            app.logger.error(f"Unexpected error: {str(e)}")
            return jsonify({'error': 'An unexpected error occurred'}), 500
    return wrapper

def get_data_from_db_combined(phone_number=None, instagram_username=None, page=1, per_page=10):
    """
    Retrieve paginated outfit data for either a phone number or Instagram username or both.
    """
    print(f"Phone Number: {phone_number} \n instagram username {instagram_username}")
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()

        offset = (page - 1) * per_page

        query = """
            SELECT DISTINCT o.id, o.image_data, o.description 
            SELECT DISTINCT o.id, o.image_data, o.description, pn.phone_number, pn.instagram_username 
            FROM outfits o 
            LEFT JOIN phone_numbers pn ON o.phone_id = pn.id 
            WHERE (pn.phone_number = %s OR pn.instagram_username = %s)
            ORDER BY o.id DESC
            LIMIT %s OFFSET %s
        """
        cursor.execute(query, (phone_number, instagram_username, per_page, offset))
        final = cursor.fetchall()
        print(f"{final}")
        return final
    except Exception as e:
        app.logger.error(f"Database error: {e}")
        return None
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
def link_instagram_to_phone(phone_number, instagram_username):
    """
    Link an Instagram username to an existing phone number.
    Returns (success, message) tuple.
    """
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()

        # Format phone number
        phone_number = format_phone_number(phone_number)
        # Remove @ symbol if present
        instagram_username = instagram_username.lstrip('@')

        # First check if phone number exists
        cursor.execute("""
            SELECT id FROM phone_numbers 
            WHERE phone_number = %s
        """, (phone_number,))

        if not cursor.fetchone():
            return False, "Phone number not found"

        # Then check if Instagram username is already taken by another user
        cursor.execute("""
            SELECT phone_number FROM phone_numbers 
            WHERE instagram_username = %s AND phone_number != %s
        """, (instagram_username, phone_number))

        existing = cursor.fetchone()
        if existing:
            return False, "Instagram username already linked to another account"

        # Update the record
        cursor.execute("""
            UPDATE phone_numbers 
            SET instagram_username = %s 
            WHERE phone_number = %s
            RETURNING id
        """, (instagram_username, phone_number))

        conn.commit()
        return True, "Successfully linked Instagram username"

    except Exception as e:
        conn.rollback()
        app.logger.error(f"Database error: {e}")
        return False, str(e)
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def format_phone_number(phone_number):
    """
    Standardize phone number format to include +1 prefix and remove special characters.
    """
    phone_number = phone_number.strip().replace("-", "").replace("(", "").replace(")", "").replace(" ", "")
    if not phone_number.startswith("+1"):
        phone_number = "+1" + phone_number
    return phone_number

def clean_url(url):
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

def generate_referral_code():
    """Generate a unique 6-character referral code"""
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if not ReferralCode.query.filter_by(code=code).first():
            return code

def get_items_from_db(outfit_id):
    """
    Retrieve all items and their associated links for a given outfit ID.
    Returns a list of items with their links, sorted by rating and review count.
    """
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        # Get items
        cursor.execute("""
            SELECT DISTINCT id, outfit_id, description
            FROM items 
            WHERE outfit_id = %s
        """, (outfit_id,))
        items = cursor.fetchall()
        items_with_links = []

        # Get links for each item
        for item_id, outfit_id, description in items:
            cursor.execute("""
                SELECT id, photo_url, url, price, title, rating, reviews_count, merchant_name
                FROM links 
                WHERE item_id = %s
                ORDER BY 
                    CASE 
                        WHEN rating IS NULL THEN 2
                        ELSE 1
                    END,
                    rating DESC,
                    reviews_count DESC
            """, (item_id,))
            links = cursor.fetchall()

            formatted_links = [{
                'id': link[0],
                'photo_url': link[1],
                'url': link[2],
                'price': link[3],
                'title': link[4],
                'rating': link[5],
                'reviews_count': link[6],
                'merchant_name': link[7]
            } for link in links]

            items_with_links.append({
                'item_id': item_id,
                'outfit_id': outfit_id,
                'description': description,
                'links': formatted_links
            })
        return items_with_links
    except Exception as e:
        app.logger.error(f"Database error: {e}")
        return None
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def get_all_data_from_db(page, per_page):
    """
    Retrieve paginated outfit data from the database.
    """
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()

        offset = (page - 1) * per_page

        cursor.execute("""
            SELECT DISTINCT o.id, o.image_data, o.description 
            FROM outfits o 
            ORDER BY o.id DESC
            LIMIT %s OFFSET %s
        """, (per_page, offset))

        return cursor.fetchall()
    except Exception as e:
        app.logger.error(f"Database error: {e}")
        return None
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def get_data_from_db(phone_number, page, per_page):
    """
    Retrieve paginated outfit data for a specific phone number.
    """
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()

        offset = (page - 1) * per_page

        cursor.execute("""
            SELECT o.id, o.image_data, o.description 
            FROM outfits o 
            LEFT JOIN phone_numbers pn ON o.phone_id = pn.id 
            WHERE pn.phone_number = %s 
            ORDER BY o.id DESC
            LIMIT %s OFFSET %s
        """, (phone_number, per_page, offset))

        return cursor.fetchall()
    except Exception as e:
        app.logger.error(f"Database error: {e}")
        return None
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def generate_and_store_embeddings():
    """Generate embeddings for all clothing items and store them in the database."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                # Enable vector extension
                cursor.execute("CREATE EXTENSION IF NOT EXISTS vector SCHEMA public;")
                conn.commit()

                # Drop existing table if it exists with wrong dimensions
                cursor.execute("DROP TABLE IF EXISTS item_embeddings;")

                # Create embeddings table with correct dimensions (1024 for embed-english-v3.0)
                cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS item_embeddings (
                        item_id INT PRIMARY KEY,
                        embedding vector({EMBED_DIMENSIONS})
                    )
                """)
                conn.commit()

                # First check if there are any items to process
                cursor.execute("SELECT COUNT(*) FROM items")
                count = cursor.fetchone()[0]

                if count == 0:
                    app.logger.warning("No items found in the database to generate embeddings for")
                    return

                # Process items in batches
                batch_size = 100
                offset = 0

                while True:
                    cursor.execute("""
                        SELECT id, description 
                        FROM items 
                        WHERE id NOT IN (SELECT item_id FROM item_embeddings)
                        ORDER BY id 
                        LIMIT %s OFFSET %s
                    """, (batch_size, offset))

                    items = cursor.fetchall()
                    if not items:
                        break

                    app.logger.info(f"Processing batch of {len(items)} items")

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
                                cursor.execute("""
                                    INSERT INTO item_embeddings (item_id, embedding) 
                                    VALUES (%s, %s::vector)
                                    ON CONFLICT (item_id) DO UPDATE 
                                    SET embedding = EXCLUDED.embedding
                                """, (item_id, embedding))

                        conn.commit()
                        app.logger.info(f"Successfully processed batch starting at offset {offset}")

                    except Exception as e:
                        app.logger.error(f"Error processing batch at offset {offset}: {str(e)}")
                        conn.rollback()

                    offset += batch_size

    except Exception as e:
        app.logger.error(f"Failed to generate embeddings: {str(e)}")
        raise

def get_data_from_db_by_instagram(instagram_username, page, per_page):
    """
    Retrieve paginated outfit data for a specific Instagram username.
    """
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()

        offset = (page - 1) * per_page

        cursor.execute("""
            SELECT o.id, o.image_data, o.description 
            FROM outfits o 
            LEFT JOIN phone_numbers pn ON o.phone_id = pn.id 
            WHERE pn.instagram_username = %s 
            ORDER BY o.id DESC
            LIMIT %s OFFSET %s
        """, (instagram_username, per_page, offset))

        return cursor.fetchall()
    except Exception as e:
        app.logger.error(f"Database error: {e}")
        return None
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# ===============================
# Route Handlers
# ===============================

@app.route("/api/referral/check", methods=['POST'])
def check_referral_code():
    """Check if user already has a referral code"""
    phone_number = request.json.get('phone_number')
    if not phone_number:
        return jsonify({"error": "Phone number required"}), 400

    user = PhoneNumber.query.filter_by(phone_number=phone_number).first()
    if not user:
        return jsonify({"error": "User not found"}), 404

    # Get most recent referral code
    code = ReferralCode.query.filter_by(phone_id=user.id).order_by(ReferralCode.created_at.desc()).first()

    if code:
        return jsonify({"code": code.code})
    else:
        return jsonify({"code": None})

@app.route("/api/referral/generate", methods=['POST'])
def generate_code():
    """Generate a new referral code for user"""
    phone_number = request.json.get('phone_number')
    if not phone_number:
        return jsonify({"error": "Phone number required"}), 400

    user = PhoneNumber.query.filter_by(phone_number=phone_number).first()
    if not user:
        return jsonify({"error": "User not found"}), 404

    # Generate new code
    code = generate_referral_code()  # Your existing function
    new_code = ReferralCode(phone_id=user.id, code=code)
    db.session.add(new_code)
    db.session.commit()

    return jsonify({"code": code})

@app.route('/api/user/check_activation', methods=['POST'])
def check_activation():
    phone_number = request.json.get('phone_number')
    if not phone_number:
        return jsonify({'error': 'Phone number required'}), 400

    phone_number = format_phone_number(phone_number)
    user = PhoneNumber.query.filter_by(phone_number=phone_number).first()

    if not user:
        # New user
        return jsonify({
            'is_activated': False,
            'needs_referral': True,
            'message': 'Please enter a referral code to activate your account'
        })

    return jsonify({
        'is_activated': user.is_activated,
        'needs_referral': not user.is_activated,
        'message': 'Please enter a referral code to activate your account' if not user.is_activated else None
    })

@app.route("/api/referral/validate", methods=['POST'])
def validate_referral():
    try:
        print("Received referral validation request")
        data = request.get_json()
        code = data.get('code')
        new_user_phone = data.get('phone_number')

        print(f"Processing code: {code} for phone: {new_user_phone}")

        if not code or not new_user_phone:
            return jsonify({
                "error": "Code and phone number required",
                "is_activated": False,
                "needs_referral": True
            }), 400

        referral_code = ReferralCode.query.filter_by(code=code).first()
        if not referral_code:
            return jsonify({
                "error": "Invalid referral code",
                "is_activated": False,
                "needs_referral": True
            }), 404

        new_user = PhoneNumber.query.filter_by(phone_number=new_user_phone).first()

        if new_user and new_user.is_activated:
            return jsonify({
                "is_activated": True,
                "needs_referral": False,
                "message": "User already activated"
            })

        if not new_user:
            new_user = PhoneNumber(phone_number=new_user_phone)
            db.session.add(new_user)
            db.session.commit()  # Commit to get the new user's ID

        referral = Referral(
            referrer_id=referral_code.phone_id,
            referred_id=new_user.id,
            code_used=code
        )

        referral_code.used_count += 1
        new_user.is_activated = True

        db.session.add(referral)
        db.session.commit()

        return jsonify({
            "is_activated": True,
            "needs_referral": False,
            "message": "Account successfully activated"
        })

    except Exception as e:
        db.session.rollback()
        print(f"Error in validate_referral: {str(e)}")
        return jsonify({
            "error": "Server error",
            "is_activated": False,
            "needs_referral": True,
            "message": str(e)
        }), 500

@app.route('/rag_search', methods=['POST'])
@handle_errors
def rag_search():
    item_description = request.json.get("item_description")
    if not item_description:
        return jsonify({"error": "Item description is required"}), 400

    query_embedding = co.embed(
        texts=[item_description], 
        model=EMBED_MODEL,  # Fixed model name
        input_type="search_query"
    ).embeddings[0]

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT item_id, embedding <=> %s::vector as distance
                FROM item_embeddings
                ORDER BY distance ASC
                LIMIT 1
            """, (query_embedding,))

            result = cursor.fetchone()
            if not result:
                return jsonify({"error": "No matching items found"}), 404
            # Change the response format to match what Swift expects    
            return jsonify({"item_id": result[0]})  # Return as item_id, not item_id

@app.route('/api/links', methods=['GET'])
@handle_errors
def api_links():
    """
    Retrieve all links for a specific item.
    Requires item_id query parameter.
    Returns sorted list of links with their details.
    """
    item_id = request.args.get('item_id')
    if not item_id:
        return jsonify({'error': 'Item ID is required'}), 400

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT id, photo_url, url, price, title, rating, reviews_count, merchant_name
                FROM links 
                WHERE item_id = %s
                ORDER BY 
                    CASE 
                        WHEN rating IS NULL THEN 2
                        ELSE 1
                    END,
                    rating DESC,
                    reviews_count DESC
            """, (item_id,))

            rows = cursor.fetchall()

            links = [{
                'id': row[0],
                'photo_url': row[1],
                'url': row[2],
                'price': row[3],
                'title': row[4],
                'rating': row[5],
                'reviews_count': row[6],
                'merchant_name': row[7]
            } for row in rows]

            return jsonify(links)

@app.route('/api/items', methods=['GET'])
@handle_errors
def api_items():
    """
    Retrieve all items for a specific outfit.
    Requires outfit_id query parameter.
    Returns items with their associated links.
    """
    outfit_id = request.args.get('outfit_id')
    if not outfit_id:
        return jsonify({'error': 'Outfit ID is required'}), 400
    try:
        outfit_id = int(outfit_id)
    except ValueError:
        return jsonify({'error': 'Invalid outfit ID format'}), 400

    items = get_items_from_db(outfit_id)
    if items is None:
        return jsonify({'error': 'Database error'}), 500
    if len(items) == 0:
        return jsonify({'error': 'No items found for this outfit'}), 404

    # Clean URLs in response
    for item in items:
        if 'links' in item:
            for link in item['links']:
                if 'url' in link:
                    link['url'] = clean_url(link['url'])
    return jsonify(items)

@app.route('/api/data_all', methods=['GET'])
@handle_errors
def api_data_all():
    """
    Retrieve paginated list of all outfits.
    Supports page and per_page query parameters for pagination.
    """
    page = request.args.get('page', default=1, type=int)
    per_page = request.args.get('per_page', default=10, type=int)

    data = get_all_data_from_db(page, per_page)
    if data is None:
        return jsonify({'error': 'Database error'}), 500
    if len(data) == 0:
        return jsonify({'error': 'No outfits found'}), 404

    data_list = [{'outfit_id': outfit_id, 'image_data': image_data, 'description': description} 
                 for outfit_id, image_data, description in data]

    return jsonify({
        'outfits': data_list,
        'has_more': len(data_list) == per_page
    })

@app.route('/api/data', methods=['GET'])
@handle_errors
def api_data():
    """
    Retrieve paginated list of outfits for a phone number and/or Instagram username.
    """
    phone_number = request.args.get('phone_number')
    instagram_username = request.args.get('instagram_username')
    page = request.args.get('page', default=1, type=int)
    per_page = request.args.get('per_page', default=10, type=int)

    if not phone_number and not instagram_username:
        return jsonify({'error': 'Either phone number or Instagram username is required'}), 400

    if phone_number:
        phone_number = format_phone_number(phone_number)
    if instagram_username:
        instagram_username = instagram_username.lstrip('@')

    data = get_data_from_db_combined(phone_number, instagram_username, page, per_page)

    if data is None:
        return jsonify({'error': 'Database error'}), 500
    if len(data) == 0:
        return jsonify({'error': 'No outfits found'}), 404

    data_list = [{'outfit_id': outfit_id, 'image_data': image_data, 'description': description} 
                 for outfit_id, image_data, description in data]

    return jsonify({
        'outfits': data_list,
        'has_more': len(data_list) == per_page
    })

# ===============================
# Application Initialization
# ===============================

# Initialize Cohere client
try:
    co = cohere.Client(COHERE_API_KEY)
except Exception as e:
    app.logger.error(f"Cohere client initialization error: {str(e)}")
    raise

def initialize_app():
    """Initialize the application and set up necessary components."""
    validate_environment()
    try:
        generate_and_store_embeddings()
    except Exception as e:
        app.logger.error(f"Failed to generate embeddings: {str(e)}")

# Create initialization route
@app.route('/initialize', methods=['POST'])
@handle_errors
def init_route():
    """Route to trigger initialization - should be called once after deployment"""
    initialize_app()
    return jsonify({"status": "initialization complete"})


# Add new database function for Instagram username queries
# Add new route for Instagram username queries
@app.route('/api/data/instagram', methods=['GET'])
@handle_errors
def api_data_instagram():
    """
    Retrieve paginated list of outfits for a specific Instagram username.
    Requires instagram_username query parameter.
    Supports page and per_page query parameters for pagination.
    """
    instagram_username = request.args.get('instagram_username')
    page = request.args.get('page', default=1, type=int)
    per_page = request.args.get('per_page', default=10, type=int)

    if not instagram_username:
        return jsonify({'error': 'Instagram username is required'}), 400

    # Remove @ symbol if present
    instagram_username = instagram_username.lstrip('@')

    data = get_data_from_db_by_instagram(instagram_username, page, per_page)

    if data is None:
        return jsonify({'error': 'Database error'}), 500
    if len(data) == 0:
        return jsonify({'error': f'No outfits found for Instagram username: {instagram_username}'}), 404

    data_list = [{'outfit_id': outfit_id, 'image_data': image_data, 'description': description} 
                 for outfit_id, image_data, description in data]

    return jsonify({
        'outfits': data_list,
        'has_more': len(data_list) == per_page
    })

# ===============================
# Main Entry Point
# ===============================


# Add these functions after the other database operations

def check_instagram_username(instagram_username):
    """
    Check if an Instagram username already exists in the database.
    Returns the associated phone number if found, None otherwise.
    """
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT phone_number 
            FROM phone_numbers 
            WHERE instagram_username = %s
        """, (instagram_username,))

        result = cursor.fetchone()
        return result[0] if result else None

    except Exception as e:
        app.logger.error(f"Database error: {e}")
        return None
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# Add this after the other Instagram-related functions

def unlink_instagram(phone_number):
    """
    Remove Instagram username association from a phone number.
    Returns (success, message) tuple.
    """
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()

        # Format phone number
        phone_number = format_phone_number(phone_number)

        # Check if phone number exists
        cursor.execute("""
            SELECT id FROM phone_numbers 
            WHERE phone_number = %s
        """, (phone_number,))

        if not cursor.fetchone():
            return False, "Phone number not found"

        # Remove Instagram username
        cursor.execute("""
            UPDATE phone_numbers 
            SET instagram_username = NULL 
            WHERE phone_number = %s
            RETURNING id
        """, (phone_number,))

        conn.commit()
        return True, "Successfully unlinked Instagram username"

    except Exception as e:
        conn.rollback()
        app.logger.error(f"Database error: {e}")
        return False, str(e)
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# Modify the existing link_instagram route to match Swift app expectations
@app.route('/api/instagram/link', methods=['POST'])
@handle_errors
def link_instagram():
    """
    Link an Instagram username to an existing phone number.
    """
    data = request.get_json()
    phone_number = data.get('phone_number')
    instagram_username = data.get('instagram_username')

    if not phone_number or not instagram_username:
        return jsonify({'error': 'Both phone number and Instagram username are required'}), 400

    success, message = link_instagram_to_phone(phone_number, instagram_username)

    if success:
        return jsonify({'username': instagram_username}), 200
    else:
        return jsonify({'error': message}), 400

# Add new unlink endpoint
@app.route('/api/instagram/unlink', methods=['POST'])
@handle_errors
def unlink_instagram_route():
    """
    Remove Instagram username association from a phone number.
    """
    data = request.get_json()
    phone_number = data.get('phone_number')

    if not phone_number:
        return jsonify({'error': 'Phone number is required'}), 400

    success, message = unlink_instagram(phone_number)

    if success:
        return jsonify({'message': message}), 200
    else:
        return jsonify({'error': message}), 400
# Add new routes
@app.route('/api/instagram/check', methods=['GET'])
@handle_errors
def check_instagram():
    """
    Check if an Instagram username is already in use.
    """
    instagram_username = request.args.get('instagram_username')
    if not instagram_username:
        return jsonify({'error': 'Instagram username is required'}), 400

    instagram_username = instagram_username.lstrip('@')
    existing_phone = check_instagram_username(instagram_username)

    return jsonify({
        'is_taken': existing_phone is not None,
        'phone_number': existing_phone if existing_phone else None
    })



if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
