from flask import Flask, render_template, jsonify, request
import psycopg2
from psycopg2 import OperationalError, DatabaseError
import os
from dotenv import load_dotenv

app = Flask(__name__)

# Load environment variables from a .env file
load_dotenv()

# Fetch database URL with error handling for missing environment variable
DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable not set. Please set it in your .env file.")

# Function to query data from the PostgreSQL database
def get_data_from_db():
    try:
        # Connect to the PostgreSQL database (replace with your connection details)
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        # Execute the query to get data from the outfits table
        cursor.execute("SELECT o.image_data, o.description FROM outfits")
        rows = cursor.fetchall()
        
    except OperationalError as e:
        # Log and handle database connection issues
        app.logger.error(f"Database connection failed: {e}")
        return None
    except DatabaseError as e:
        # Log other database errors
        app.logger.error(f"Database query failed: {e}")
        return None
    finally:
        # Close the cursor and connection if they are open
        if 'cursor' in locals() and cursor:
            cursor.close()
        if 'conn' in locals() and conn:
            conn.close()
    
    return rows

# Route to display data on the UI
@app.route('/')
def index():
    print("run")
    # Get data from the database
    data = get_data_from_db()
    print(data)
    
    if data is None:
        return render_template('error.html', message="Could not fetch data from the database. Please try again later.")
    
    # Render the data in an HTML template
    return render_template('index.html', data=data)

# Handle 404 errors
@app.errorhandler(404)
def page_not_found(error):
    return render_template('error.html', message="Page not found."), 404

# Handle 500 errors
@app.errorhandler(500)
def internal_error(error):
    return render_template('error.html', message="Internal server error. Please try again later."), 500

if __name__ == '__main__':
    app.run(debug=True)
