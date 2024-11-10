from flask import Flask, render_template
import psycopg2
import os
from dotenv import load_dotenv
import gunicorn



app = Flask(__name__)

# Load environment variables from a .env file
load_dotenv()
DATABASE_URL = os.environ['DATABASE_URL']

# Function to query data from the PostgreSQL database
def get_data_from_db():
    # Connect to the PostgreSQL database (replace with your connection details)
    conn = psycopg2.connect(
        DATABASE_URL
    )
    cursor = conn.cursor()
    
    # Execute the query to get data from the phone_numbers and outfits tables
    cursor.execute("SELECT o.image_data, o.description FROM outfits")
    rows = cursor.fetchall()
    
    # Close the connection
    conn.close()
    
    return rows

# Route to display data on the UI
@app.route('/')
def index():
    # Get data from the database
    data = get_data_from_db()
    
    # Render the data in an HTML template
    return render_template('index.html', data=data)

if __name__ == '__main__':
    app.run(debug=True)
