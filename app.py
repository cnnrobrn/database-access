from flask import Flask, jsonify, request
from flask_cors import CORS
import psycopg2
import os
from dotenv import load_dotenv
import cohere  # Import the Cohere library

app = Flask(__name__)
CORS(app)

load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL')
YOUR_COHERE_API_KEY = os.getenv('YOUR_COHERE_API_KEY')
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable not set.")

co = cohere.Client('YOUR_COHERE_API_KEY')  # Initialize Cohere client
# Call the function to generate and store embeddings
generate_and_store_embeddings()


@app.route('/api/links', methods=['GET'])
def api_links():
    item_id = request.args.get('item_id')
    if not item_id:
        return jsonify({'error': 'Item ID is required'}), 400

    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        # Query to get all links for an item
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
        
        # Format the results
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
        
    except Exception as e:
        app.logger.error(f"Database error: {e}")
        return jsonify({'error': 'Database error'}), 500
        
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def format_phone_number(phone_number):
    phone_number = phone_number.strip().replace("-", "").replace("(", "").replace(")", "").replace(" ", "")
    if not phone_number.startswith("+1"):
        phone_number = "+1" + phone_number
    return phone_number


def get_items_from_db(outfit_id):
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        # First get the items
        cursor.execute("""
            SELECT DISTINCT id, outfit_id, description
            FROM items 
            WHERE outfit_id = %s
        """, (outfit_id,))
        items = cursor.fetchall()
        items_with_links = []
        # For each item, get its links
        for item_id, outfit_id, description in items:
            # Get links for this item
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
            # Format links
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
            # Add item with its links
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
def clean_url(url):
    if not url:
        return ''
    
    # Remove '/url?q=' prefix if it exists
    if url.startswith('/url?q='):
        url = url[7:]
    
    # URL decode
    try:
        url = urllib.parse.unquote(url)
    except:
        pass
    
    # Ensure https:// prefix
    if not url.startswith('http://') and not url.startswith('https://'):
        url = 'https://' + url
    
    return url


@app.route('/api/items', methods=['GET'])
def api_items():
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
    # Clean URLs in the response
    for item in items:
        if 'links' in item:
            for link in item['links']:
                if 'url' in link:
                    link['url'] = clean_url(link['url'])
    return jsonify(items)



@app.route('/api/data_all', methods=['GET'])
def api_data_all():
    # Get pagination parameters from request
    page = request.args.get('page', default=1, type=int)
    per_page = request.args.get('per_page', default=10, type=int)
    
    data = get_all_data_from_db(page, per_page)
    if data is None:
        return jsonify({'error': 'Database error'}), 500
    if len(data) == 0:
        return jsonify({'error': 'No outfits found'}), 404
        
    data_list = [{'outfit_id': outfit_id, 'image_data': image_data, 'description': description} 
                 for outfit_id, image_data, description in data]
    
    # Return total count along with the data
    return jsonify({
        'outfits': data_list,
        'has_more': len(data_list) == per_page  # If we got full page, there might be more
    })

def get_all_data_from_db(page, per_page):
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        # Calculate offset
        offset = (page - 1) * per_page
        
        cursor.execute("""
            SELECT DISTINCT o.id, o.image_data, o.description 
            FROM outfits o 
            ORDER BY o.id DESC
            LIMIT %s OFFSET %s
        """, (per_page, offset))
        
        rows = cursor.fetchall()
    except Exception as e:
        app.logger.error(f"Database error: {e}")
        return None
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    return rows

@app.route('/api/data', methods=['GET'])
def api_data():
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
    
    # Return in same format as global feed
    return jsonify({
        'outfits': data_list,
        'has_more': len(data_list) == per_page
    })

def get_data_from_db(phone_number, page, per_page):
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        # Calculate offset
        offset = (page - 1) * per_page
        
        cursor.execute("""
            SELECT o.id, o.image_data, o.description 
            FROM outfits o 
            LEFT JOIN phone_numbers pn ON o.phone_id = pn.id 
            WHERE pn.phone_number = %s 
            ORDER BY o.id DESC
            LIMIT %s OFFSET %s
        """, (phone_number, per_page, offset))
        
        rows = cursor.fetchall()
    except Exception as e:
        app.logger.error(f"Database error: {e}")
        return None
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    return rows

def generate_and_store_embeddings():
    """
    Generates embeddings for all clothing items and stores them 
    along with the item IDs in a new database table.
    """
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()

        # 1. Create a table to store embeddings (if it doesn't exist)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS item_embeddings (
                item_id INT PRIMARY KEY,
                embedding VECTOR(1024)  -- Adjust dimensionality if needed
            )
        """)
        conn.commit()

        # 2. Fetch all items with their descriptions and image features
        cursor.execute("""
            SELECT i.id, i.description, o.image_data 
            FROM items i
            JOIN outfits o ON i.outfit_id = o.id
        """)
        items = cursor.fetchall()

        for item_id, description, image_data in items:
            # 3. Combine text and image features (you'll need image processing here)
            # For now, let's assume you have a function to extract image features:
            image_features = extract_image_features(image_data)  
            combined_text = f"{description} {image_features}" 

            # 4. Generate embeddings using Cohere
            embedding = co.embed(texts=[combined_text], model="large").embeddings[0]

            # 5. Store the embedding in the database
            cursor.execute("""
                INSERT INTO item_embeddings (item_id, embedding) 
                VALUES (%s, %s)
                ON CONFLICT (item_id) DO UPDATE 
                SET embedding = EXCLUDED.embedding
            """, (item_id, embedding)) 
        conn.commit()

    except Exception as e:
        app.logger.error(f"Database error: {e}")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()



    
if __name__ == '__main__':
    app.run(debug=False)
