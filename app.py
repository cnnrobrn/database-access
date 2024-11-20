from flask import Flask, jsonify, request
from flask_cors import CORS
import psycopg2
import os
from dotenv import load_dotenv

app = Flask(__name__)
CORS(app)

load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable not set.")

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


def get_data_from_db(phone_number):
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT o.id, o.image_data, o.description 
            FROM outfits o 
            LEFT JOIN phone_numbers pn ON o.phone_id = pn.id 
            WHERE pn.phone_number = %s 
            ORDER BY o.id DESC
        """, (phone_number,))
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

def format_phone_number(phone_number):
    phone_number = phone_number.strip().replace("-", "").replace("(", "").replace(")", "").replace(" ", "")
    if not phone_number.startswith("+1"):
        phone_number = "+1" + phone_number
    return phone_number

@app.route('/api/data', methods=['GET'])
def api_data():
    phone_number = request.args.get('phone_number')
    if not phone_number:
        return jsonify({'error': 'Phone number is required'}), 400
    formatted_phone = format_phone_number(phone_number)
    data = get_data_from_db(formatted_phone)
    if data is None:
        return jsonify({'error': 'Database error'}), 500
    if len(data) == 0:
        return jsonify({'error': 'No outfits found for this phone number'}), 404
    data_list = [{'outfit_id': outfit_id, 'image_data': image_data, 'description': description} for outfit_id, image_data, description in data]
    return jsonify(data_list)

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
    data = get_all_data_from_db()
    if data is None:
        return jsonify({'error': 'Database error'}), 500
    if len(data) == 0:
        return jsonify({'error': 'No outfits found for this phone number'}), 404
    data_list = [{'outfit_id': outfit_id, 'image_data': image_data, 'description': description} for outfit_id, image_data, description in data]
    return jsonify(data_list)

def get_all_data_from_db():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT o.id, o.image_data, o.description 
            FROM outfits o 
            LEFT JOIN phone_numbers pn ON o.phone_id = pn.id 
            ORDER BY o.id DESC LIMIT 100
        """)
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
    
if __name__ == '__main__':
    app.run(debug=False)
