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
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            # Enable vector extension
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector SCHEMA public;")
            conn.commit()

            # Create embeddings table with explicit vector type
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS item_embeddings (
                    item_id INT PRIMARY KEY,
                    embedding vector(1024)
                )
            """)
            conn.commit()

            # Process items in batches
            batch_size = 100
            cursor.execute("SELECT id, description FROM items")
            while True:
                items = cursor.fetchmany(batch_size)
                if not items:
                    break
                
                descriptions = [item[1] for item in items]
                embeddings = co.embed(texts=descriptions, model="embed-english-light").embeddings
                
                for (item_id, _), embedding in zip(items, embeddings):
                    # Cast the array to vector type during insertion
                    cursor.execute("""
                        INSERT INTO item_embeddings (item_id, embedding) 
                        VALUES (%s, %s::vector)
                        ON CONFLICT (item_id) DO UPDATE 
                        SET embedding = EXCLUDED.embedding
                    """, (item_id, embedding))
                
                conn.commit()
# ===============================
# Route Handlers
# ===============================

@app.route('/rag_search', methods=['POST'])
@handle_errors
def rag_search():
    item_description = request.json.get("item_description")
    if not item_description:
        return jsonify({"error": "Item description is required"}), 400

    query_embedding = co.embed(texts=[item_description], model="large").embeddings[0]
    
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            # Cast the array to vector type
            cursor.execute("""
                SELECT item_id, embedding <=> %s::vector as distance
                FROM item_embeddings
                ORDER BY distance ASC
                LIMIT 1
            """, (query_embedding,))
            
            result = cursor.fetchone()
            if not result:
                return jsonify({"error": "No matching items found"}), 404
            
            return jsonify({"item_id": result[0]})

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
    Retrieve paginated list of outfits for a specific phone number.
    Requires phone_number query parameter.
    Supports page and per_page query parameters for pagination.
    """
    phone_number = request.args.get('phone_number')
    page = request.args.get('page', default=1, type=int)
    per_page = request.args.get('per_page', default=10, type=int)
    
    if not phone_number:
        return jsonify({'error': 'Phone number is required'}), 400
        
    formatted_phone = format_phone_number(phone_number)
    data = get_data_from_db(formatted_phone, page, per_page)
    
    if data is None:
        return jsonify({'error': 'Database error'}), 500
    if len(data) == 0:
        return jsonify({'error': f'No outfits found for phone number: {formatted_phone}'}), 404
        
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

# ===============================
# Main Entry Point
# ===============================


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
    
