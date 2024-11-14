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

def get_data_from_db(phone_number):
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT o.image_data, o.description 
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

@app.route('/api/data', methods=['GET'])
def api_data():
    phone_number = request.args.get('phone_number')
    if not phone_number:
        return jsonify({'error': 'Phone number is required'}), 400
    data = get_data_from_db(phone_number)
    if data is None:
        return jsonify({'error': 'Database error'}), 500
    if len(data) == 0:
        return jsonify({'error': 'No outfits found for this phone number'}), 404
    data_list = [{'image_data': image_data, 'description': description} for image_data, description in data]
    return jsonify(data_list)

if __name__ == '__main__':
    app.run(debug=False)
