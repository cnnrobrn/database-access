from flask import Flask, jsonify
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

def get_data_from_db():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute("SELECT image_data, description FROM outfits")
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
    data = get_data_from_db()
    if data is None:
        return jsonify({'error': 'Database error'}), 500
    data_list = [{'image_data': image_data, 'description': description} for image_data, description in data]
    return jsonify(data_list)

if __name__ == '__main__':
    app.run(debug=False)
