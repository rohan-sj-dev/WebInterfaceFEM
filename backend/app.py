from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from flask_jwt_extended import JWTManager, jwt_required, create_access_token, get_jwt_identity
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
import sqlite3
import uuid
import tempfile
import threading
import zipfile
import subprocess
import io
from datetime import datetime, timedelta
import logging
import requests
import time
from dotenv import load_dotenv
from io import BytesIO
import pikepdf
import base64
from glm_vision_service import GLMVisionService
import convertapi
import ocrmypdf


# Load environment variables from .env file
load_dotenv()

# GLM CONFIGURATION
GLM_API_KEY = os.getenv('GLM_API_KEY', '')

# CONVERTAPI CONFIGURATION
CONVERT_API_KEY = os.getenv('CONVERT_API_KEY', '')
if CONVERT_API_KEY:
    convertapi.api_credentials = CONVERT_API_KEY

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['JWT_SECRET_KEY'] = 'dDaysadadREfj@38u983293*#(&#*u8w'
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  

jwt = JWTManager(app)
CORS(app, origins=["http://localhost:3000"])
@jwt.expired_token_loader
def expired_token_callback(jwt_header, jwt_payload):
    print(f"JWT expired token error")
    return jsonify({'error': 'Token has expired'}), 401

@jwt.invalid_token_loader
def invalid_token_callback(error):
    print(f"JWT invalid token error: {error}")
    return jsonify({'error': 'Invalid token'}), 422

@jwt.unauthorized_loader
def missing_token_callback(error):
    print(f"JWT missing token error: {error}")
    return jsonify({'error': 'Authorization token is required'}), 401

@app.before_request
def log_request_info():
    print(f"=== REQUEST: {request.method} {request.path} ===")
    if request.path == '/api/upload':
        print(f"Content-Type: {request.content_type}")
        print(f"Content-Length: {request.content_length}")

UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'outputs'
ALLOWED_EXTENSIONS = {'pdf'}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# Task storage for tracking async processing
task_storage = {}

def setup_ocr_environment():
    os.environ['TESSERACT_CMD'] = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    os.environ['PATH'] = r'C:\Program Files\gs\gs10.05.1\bin;' + os.environ.get('PATH', '')

setup_ocr_environment()

def init_db():
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS processing_jobs (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    conn.commit()
    conn.close()

init_db()

processing_status = {}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_user_by_email(email):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, email, password_hash, full_name FROM users WHERE email = ?', (email,))
    user = cursor.fetchone()
    conn.close()
    return user

def create_user(email, password, full_name):
    try:
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        password_hash = generate_password_hash(password)
        cursor.execute(
            'INSERT INTO users (email, password_hash, full_name) VALUES (?, ?, ?)',
            (email, password_hash, full_name)
        )
        user_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return user_id
    except sqlite3.IntegrityError:
        return None

def process_pdf_with_ocr_and_camelot(input_path, output_path, options, task_id, user_id):
    try:
        processing_status[task_id] = {
            'status': 'processing',
            'message': 'Starting OCR processing...',
            'progress': 10,
            'user_id': user_id
        }
        
        import ocrmypdf

        processing_status[task_id]['message'] = 'Running OCR on PDF...'
        processing_status[task_id]['progress'] = 30
        
        ocr_options = {
            'language': options.get('language', 'eng'),
            'deskew': options.get('deskew', True),
            'optimize': int(options.get('optimize', 1)),
            'force_ocr': options.get('force_ocr', False),
            'progress_bar': False
        }
        
        if options.get('clean', False):
            try:
                import subprocess
                subprocess.run(['unpaper', '--version'], capture_output=True, timeout=5)
                ocr_options['clean'] = True
            except:
                logger.warning("Unpaper not available, skipping clean option")
        
        ocrmypdf.ocr(input_path, output_path, **ocr_options)
        
        processing_status[task_id]['message'] = 'OCR completed, extracting tables...'
        processing_status[task_id]['progress'] = 60

        tables_data = []
        tables_dir = None
        
        if options.get('extract_tables', True):
            try:
                import camelot

                tables_dir = os.path.join(OUTPUT_FOLDER, f"tables_{task_id}")
                os.makedirs(tables_dir, exist_ok=True)
                
                processing_status[task_id]['message'] = 'Extracting tables with Camelot...'
                processing_status[task_id]['progress'] = 80
                
                # Try lattice method first 
                try:
                    tables = camelot.read_pdf(
                        output_path, 
                        pages='all',
                        flavor='lattice',  # Better for bordered tables
                        table_areas=None,  # Auto-detect table areas
                        columns=None,      # Auto-detect columns
                        split_text=True,   # Split text that spans multiple lines
                        flag_size=True,    # Flag text size differences
                        strip_text='\n',   # Strip newlines
                        line_scale=60,     # Even more aggressive line detection
                        copy_text=['v', 'h'],  # Copy text for better detection
                        shift_text=['l', 't'],  # Shift text for better alignment
                        background_color='#ffffff',  # Assume white background
                        process_background=True  # Process background for better detection
                    )
                    
                    logger.info(f"Lattice method found {len(tables)} tables")
                    
                    # Try stream method as well for comprehensive detection
                    stream_tables = camelot.read_pdf(
                        output_path,
                        pages='all', 
                        flavor='stream',   # Better for tables without borders
                        table_areas=None,
                        columns=None,
                        row_tol=1,         # More strict row tolerance
                        column_tol=0,      # No column tolerance
                        edge_tol=100,      # Very aggressive edge detection
                        strip_text='\n'    # Strip newlines
                    )
                    
                    logger.info(f"Stream method found {len(stream_tables)} tables")
                    
                    # Combine all results
                    all_tables = list(tables) + list(stream_tables)
                    
                except Exception as lattice_error:
                    logger.warning(f"Lattice method failed: {lattice_error}, trying stream method only")
                    # Fallback to stream method only
                    try:
                        all_tables = camelot.read_pdf(
                            output_path,
                            pages='all',
                            flavor='stream',
                            table_areas=None,
                            columns=None,
                            row_tol=1,
                            column_tol=0,
                            edge_tol=100,
                            strip_text='\n'
                        )
                        logger.info(f"Stream fallback found {len(all_tables)} tables")
                    except Exception as stream_error:
                        logger.error(f"Both lattice and stream methods failed: {stream_error}")
                        all_tables = []
                
                processed_tables = []
                seen_tables = set()  
                
                for i, table in enumerate(all_tables):
                    # Get accuracy if available, default to reasonable value
                    accuracy = getattr(table, 'accuracy', 50.0)
                    
                    # More lenient accuracy threshold - accept even lower accuracy tables
                    if accuracy < 15:  # Only filter out extremely poor tables
                        logger.warning(f"Skipping table {i+1} due to very low accuracy: {accuracy}%")
                        continue
                    
                    # Check table dimensions - be very lenient
                    if len(table.df) < 1 or len(table.df.columns) < 1:
                        logger.warning(f"Skipping table {i+1} due to no data")
                        continue
                    
                    # Clean the dataframe
                    cleaned_df = table.df.dropna(how='all').dropna(axis=1, how='all')
                    
                    # Accept even single-column or single-row tables if they have content
                    if cleaned_df.empty:
                        continue
                    
                    # Simple duplicate detection based on content
                    content_hash = hash(str(cleaned_df.values.tolist()))
                    if content_hash in seen_tables:
                        logger.info(f"Skipping duplicate table {i+1}")
                        continue
                    seen_tables.add(content_hash)
                    
                    # Log table details for debugging
                    logger.info(f"Processing table {len(processed_tables)+1}: {len(cleaned_df)} rows, {len(cleaned_df.columns)} cols, accuracy: {accuracy}%")
                    
                    processed_tables.append((cleaned_df, accuracy))
                
                for idx, (cleaned_df, accuracy) in enumerate(processed_tables):
                    table_num = idx + 1
                    
                    # Save table as CSV
                    csv_filename = f'table_{table_num}.csv'
                    csv_path = os.path.join(tables_dir, csv_filename)
                    cleaned_df.to_csv(csv_path, index=False)
                    
                    # Save table as Excel
                    excel_filename = f'table_{table_num}.xlsx'
                    excel_path = os.path.join(tables_dir, excel_filename)
                    cleaned_df.to_excel(excel_path, index=False)
                    
                    tables_data.append({
                        'table_num': table_num,
                        'csv_file': csv_filename,
                        'excel_file': excel_filename,
                        'rows': len(cleaned_df),
                        'columns': len(cleaned_df.columns),
                        'accuracy': f"{accuracy:.1f}%" if isinstance(accuracy, (int, float)) else str(accuracy),
                        'extraction_method': 'camelot'
                    })
            except ImportError:
                logger.warning("Camelot not available, skipping table extraction")
        
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE processing_jobs SET status = ?, completed_at = CURRENT_TIMESTAMP WHERE id = ?',
            ('completed', task_id)
        )
        conn.commit()
        conn.close()
        
        processing_status[task_id] = {
            'status': 'completed',
            'message': f'Processing completed! Found {len(tables_data)} table(s).',
            'progress': 100,
            'output_file': os.path.basename(output_path),
            'tables': tables_data,
            'tables_dir': tables_dir,
            'user_id': user_id
        }
        
    except Exception as e:
        processing_status[task_id] = {
            'status': 'error',
            'message': f'Processing failed: {str(e)}',
            'progress': 0,
            'user_id': user_id
        }
        logger.error(f"Processing failed: {e}")

@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    
    if not data or not all(k in data for k in ('email', 'password', 'fullName')):
        return jsonify({'error': 'Missing required fields'}), 400
    
    email = data['email'].lower().strip()
    password = data['password']
    full_name = data['fullName'].strip()

    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400

    if get_user_by_email(email):
        return jsonify({'error': 'Email already registered'}), 400

    user_id = create_user(email, password, full_name)
    if not user_id:
        return jsonify({'error': 'Registration failed'}), 500
    
    # Create access token
    access_token = create_access_token(identity=str(user_id))
    
    return jsonify({
        'message': 'Registration successful',
        'access_token': access_token,
        'user': {
            'id': user_id,
            'email': email,
            'fullName': full_name
        }
    })

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    
    if not data or not all(k in data for k in ('email', 'password')):
        return jsonify({'error': 'Missing email or password'}), 400
    
    email = data['email'].lower().strip()
    password = data['password']
    
    user = get_user_by_email(email)
    if not user or not check_password_hash(user[2], password):
        return jsonify({'error': 'Invalid email or password'}), 401

    access_token = create_access_token(identity=str(user[0]))
    
    return jsonify({
        'message': 'Login successful',
        'access_token': access_token,
        'user': {
            'id': user[0],
            'email': user[1],
            'fullName': user[3]
        }
    })

@app.route('/api/profile', methods=['GET'])
@jwt_required()
def get_profile():
    user_id = int(get_jwt_identity())
    
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, email, full_name FROM users WHERE id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    return jsonify({
        'user': {
            'id': user[0],
            'email': user[1],
            'fullName': user[2]
        }
    })


@app.route('/api/upload', methods=['POST'])
@jwt_required()
def upload_file():
    print("=== UPLOAD ENDPOINT CALLED ===")
    print(f"Request method: {request.method}")
    print(f"Request content type: {request.content_type}")
    print(f"Request headers: {dict(request.headers)}")
    
    user_id = int(get_jwt_identity())
    print(f"JWT validation successful, user_id: {user_id}")
    
    print(f"Upload request from user {user_id}")
    print(f"Files in request: {list(request.files.keys())}")
    print(f"Form data: {dict(request.form)}")
    
    if 'file' not in request.files:
        print("Error: No file provided")
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    print(f"File received: {file.filename}")
    
    if file.filename == '' or not allowed_file(file.filename):
        print(f"Error: Invalid file type or empty filename: {file.filename}")
        return jsonify({'error': 'Invalid file type. Please upload a PDF file.'}), 400
    
    options = {
        'language': request.form.get('language', 'eng'),
        'deskew': request.form.get('deskew', 'true').lower() == 'true',
        'clean': request.form.get('clean', 'false').lower() == 'true',
        'optimize': request.form.get('optimize', '1'),
        'force_ocr': request.form.get('force_ocr', 'false').lower() == 'true',
        'extract_tables': request.form.get('extract_tables', 'true').lower() == 'true'
    }
    task_id = str(uuid.uuid4())
    filename = secure_filename(file.filename)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    input_filename = f"{timestamp}_{filename}"
    input_path = os.path.join(UPLOAD_FOLDER, input_filename)
    file.save(input_path)
    output_filename = f"OCR_{input_filename}"
    output_path = os.path.join(OUTPUT_FOLDER, output_filename)

    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO processing_jobs (id, user_id, filename, status) VALUES (?, ?, ?, ?)',
        (task_id, user_id, filename, 'processing')
    )
    conn.commit()
    conn.close()
    thread = threading.Thread(
        target=process_pdf_with_ocr_and_camelot,
        args=(input_path, output_path, options, task_id, user_id)
    )
    thread.start()
    
    print(f"Processing started for task_id: {task_id}")
    return jsonify({
        'task_id': task_id,
        'message': 'File uploaded successfully, processing started',
        'filename': filename
    })

@app.route('/api/upload_llmwhisperer', methods=['POST'])
@jwt_required()
def upload_file_llmwhisperer():
    """Upload file for LLMWhisperer text extraction"""
    print("=== LLMWHISPERER UPLOAD ENDPOINT CALLED ===")
    
    user_id = int(get_jwt_identity())
    print(f"JWT validation successful, user_id: {user_id}")
    
    if 'file' not in request.files:
        print("Error: No file provided")
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    print(f"File received: {file.filename}")
    
    if file.filename == '' or not allowed_file(file.filename):
        print(f"Error: Invalid file type or empty filename: {file.filename}")
        return jsonify({'error': 'Invalid file type. Please upload a PDF file.'}), 400
    
    task_id = str(uuid.uuid4())
    filename = secure_filename(file.filename)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    input_filename = f"{timestamp}_{filename}"
    input_path = os.path.join(UPLOAD_FOLDER, input_filename)
    file.save(input_path)

    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO processing_jobs (id, user_id, filename, status, created_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)',
        (task_id, user_id, filename, 'processing')
    )
    conn.commit()
    conn.close()

    processing_status[task_id] = {
        'status': 'queued',
        'message': 'File uploaded, queued for LLMWhisperer processing',
        'progress': 0,
        'user_id': user_id
    }

    thread = threading.Thread(
        target=process_pdf_with_llmwhisperer,
        args=(input_path, task_id, user_id)
    )
    thread.start()
    
    print(f"LLMWhisperer processing started for task_id: {task_id}")
    return jsonify({
        'task_id': task_id,
        'message': 'File uploaded successfully, processing with LLMWhisperer',
        'filename': filename
    })

@app.route('/api/upload_textract', methods=['POST'])
@app.route('/api/upload_direct_llm', methods=['POST'])  # Keep old endpoint for backwards compatibility
@jwt_required()
def upload_file_textract():
    """Upload file for AWS Textract processing with custom queries"""
    print("=== AWS TEXTRACT UPLOAD ENDPOINT CALLED ===")
    
    user_id = int(get_jwt_identity())
    print(f"JWT validation successful, user_id: {user_id}")
    
    if 'file' not in request.files:
        print("Error: No file provided")
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    print(f"File received: {file.filename}")
    
    if file.filename == '' or not allowed_file(file.filename):
        print(f"Error: Invalid file type or empty filename: {file.filename}")
        return jsonify({'error': 'Invalid file type. Please upload a PDF file.'}), 400
    
    # Get custom query from request
    custom_query = request.form.get('custom_prompt', '')  # Keep 'custom_prompt' for backwards compatibility
    if not custom_query:
        custom_query = request.form.get('custom_query', '')
    print(f"Custom query received: {custom_query}")
    
    task_id = str(uuid.uuid4())
    filename = secure_filename(file.filename)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    input_filename = f"{timestamp}_{filename}"
    input_path = os.path.join(UPLOAD_FOLDER, input_filename)
    file.save(input_path)

    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO processing_jobs (id, user_id, filename, status, created_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)',
        (task_id, user_id, filename, 'processing')
    )
    conn.commit()
    conn.close()

    processing_status[task_id] = {
        'status': 'queued',
        'message': 'File uploaded, queued for AWS Textract processing',
        'progress': 0,
        'user_id': user_id
    }

    thread = threading.Thread(
        target=process_pdf_with_textract,
        args=(input_path, task_id, user_id, custom_query)
    )
    thread.start()
    
    print(f"AWS Textract processing started for task_id: {task_id}")
    return jsonify({
        'task_id': task_id,
        'message': 'File uploaded successfully, processing with AWS Textract',
        'filename': filename,
        'has_custom_query': bool(custom_query)
    })

print("DEBUG: After upload_file_textract function, about to register searchable PDF route...")

# Register searchable PDF route
print("DEBUG: Registering searchable PDF route...")

def process_pdf_with_glm_custom_query(input_path, task_id, user_id, custom_query):
    """Process PDF with GLM-4.5V for custom query extraction"""
    try:
        processing_status[task_id] = {
            'status': 'processing',
            'message': 'Extracting custom query data with GLM-4.5V...',
            'progress': 10,
            'user_id': user_id
        }
        
        # Initialize GLM service
        glm_service = GLMVisionService(api_key=GLM_API_KEY)
        
        processing_status[task_id]['message'] = 'Uploading PDF to GLM-4.5V...'
        processing_status[task_id]['progress'] = 30
        
        # Extract custom query data from PDF
        result = glm_service.extract_tables_from_pdf(
            pdf_path=input_path,
            custom_prompt=custom_query,
            model="glm-4.5v",
            return_format="csv"  # Use csv format for better text output
        )
        
        if not result.get('success'):
            raise Exception(result.get('error', 'GLM extraction failed'))
        
        processing_status[task_id]['message'] = 'Processing GLM response...'
        processing_status[task_id]['progress'] = 70
        
        # Save the result as text file
        base_name = os.path.splitext(os.path.basename(input_path))[0]
        output_filename = f"{base_name}_glm_query_result.txt"
        output_path = os.path.join(OUTPUT_FOLDER, output_filename)
        
        # Extract the response text
        extracted_text = result.get('content', '')
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(f"Query: {custom_query}\n\n")
            f.write("=" * 80 + "\n\n")
            f.write(extracted_text)
        
        processing_status[task_id]['message'] = 'GLM custom query extraction completed!'
        processing_status[task_id]['progress'] = 90
        
        # Update database
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE processing_jobs SET status = ?, completed_at = CURRENT_TIMESTAMP WHERE id = ?',
            ('completed', task_id)
        )
        conn.commit()
        conn.close()
        
        processing_status[task_id] = {
            'status': 'completed',
            'message': 'GLM custom query extraction completed',
            'progress': 100,
            'extraction_method': 'glm_custom_query',
            'result': {
                'output_file': output_filename,
                'query': custom_query,
                'extracted_text': extracted_text
            },
            'user_id': user_id
        }
        
        logger.info(f"GLM custom query extraction completed for task {task_id}")
        
    except Exception as e:
        logger.error(f"GLM custom query extraction failed for task {task_id}: {str(e)}")
        processing_status[task_id] = {
            'status': 'failed',
            'message': f'GLM custom query extraction failed: {str(e)}',
            'progress': 0,
            'user_id': user_id
        }
        
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE processing_jobs SET status = ? WHERE id = ?',
            ('failed', task_id)
        )
        conn.commit()
        conn.close()

def convert_pdf_to_searchable_ocrmypdf(input_path, task_id, user_id):
    """Convert PDF to searchable using OCRmyPDF (local, fast)"""
    try:
        processing_status[task_id] = {
            'status': 'processing',
            'message': 'Converting PDF to searchable format with OCRmyPDF (local)...',
            'progress': 10,
            'user_id': user_id
        }
        
        # Generate output filename
        base_name = os.path.splitext(os.path.basename(input_path))[0]
        output_filename = f"{base_name}-converted.pdf"
        output_path = os.path.join(OUTPUT_FOLDER, output_filename)
        
        processing_status[task_id]['message'] = 'Running OCR with Tesseract...'
        processing_status[task_id]['progress'] = 30
        
        # Suppress OCRmyPDF verbose logging
        ocrmypdf_logger = logging.getLogger('ocrmypdf')
        original_level = ocrmypdf_logger.level
        ocrmypdf_logger.setLevel(logging.ERROR)
        
        try:
            # Convert using OCRmyPDF
            ocrmypdf.ocr(
                input_path,
                output_path,
                language='eng',           # English language
                deskew=True,              # Straighten pages
                optimize=1,               # Optimize output file size
                skip_text=True,           # Skip pages that already have text
                force_ocr=False,          # Don't OCR pages that already have text
                progress_bar=False        # No progress bar in background
            )
        finally:
            # Restore original logging level
            ocrmypdf_logger.setLevel(original_level)
        
        processing_status[task_id]['message'] = 'Searchable PDF created successfully!'
        processing_status[task_id]['progress'] = 90
        
        # Update database status only
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE processing_jobs SET status = ?, completed_at = CURRENT_TIMESTAMP WHERE id = ?',
            ('completed', task_id)
        )
        conn.commit()
        conn.close()
        
        processing_status[task_id] = {
            'status': 'completed',
            'message': 'Searchable PDF created successfully with OCRmyPDF',
            'progress': 100,
            'extraction_method': 'ocrmypdf',
            'result': {
                'output_file': output_filename,
                'original_size_kb': round(os.path.getsize(input_path) / 1024, 2),
                'converted_size_kb': round(os.path.getsize(output_path) / 1024, 2)
            },
            'user_id': user_id
        }
        
        logger.info(f"OCRmyPDF conversion completed for task {task_id}")
        
    except ocrmypdf.exceptions.PriorOcrFoundError:
        # PDF already has text, just copy it
        output_filename = f"{os.path.splitext(os.path.basename(input_path))[0]}-converted.pdf"
        output_path = os.path.join(OUTPUT_FOLDER, output_filename)
        import shutil
        shutil.copy2(input_path, output_path)
        
        processing_status[task_id] = {
            'status': 'completed',
            'message': 'PDF already contains searchable text',
            'progress': 100,
            'extraction_method': 'ocrmypdf',
            'result': {
                'output_file': output_filename,
                'original_size_kb': round(os.path.getsize(input_path) / 1024, 2),
                'converted_size_kb': round(os.path.getsize(output_path) / 1024, 2)
            },
            'user_id': user_id
        }
        
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE processing_jobs SET status = ?, completed_at = CURRENT_TIMESTAMP WHERE id = ?',
            ('completed', task_id)
        )
        conn.commit()
        conn.close()
        
    except Exception as e:
        logger.error(f"OCRmyPDF conversion failed for task {task_id}: {str(e)}")
        processing_status[task_id] = {
            'status': 'failed',
            'message': f'OCRmyPDF conversion failed: {str(e)}',
            'progress': 0,
            'user_id': user_id
        }
        
        # Update database status only
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE processing_jobs SET status = ? WHERE id = ?',
            ('failed', task_id)
        )
        conn.commit()
        conn.close()

def convert_pdf_to_searchable_convertapi(input_path, task_id, user_id):
    """Convert PDF to searchable using ConvertAPI"""
    try:
        logger.info(f"=== STARTING CONVERTAPI CONVERSION FOR TASK {task_id} ===")
        logger.info(f"Input file: {input_path}")
        logger.info(f"File size: {os.path.getsize(input_path)} bytes")
        
        processing_status[task_id] = {
            'status': 'processing',
            'message': 'Converting PDF to searchable format with ConvertAPI...',
            'progress': 10,
            'user_id': user_id
        }
        
        # Generate output filename
        base_name = os.path.splitext(os.path.basename(input_path))[0]
        output_filename = f"{base_name}-converted"
        output_dir = OUTPUT_FOLDER
        
        processing_status[task_id]['message'] = 'Uploading to ConvertAPI...'
        processing_status[task_id]['progress'] = 30
        
        logger.info(f"Calling ConvertAPI with output filename: {output_filename}")
        # Convert using ConvertAPI with timeout
        result = convertapi.convert('ocr', {
            'File': input_path,
            'FileName': output_filename,
            'Timeout': 300  # 5 minutes timeout
        }, from_format='pdf')
        
        logger.info(f"ConvertAPI returned result: {result}")
        logger.info(f"ConvertAPI returned result: {result}")
        
        processing_status[task_id]['message'] = 'Downloading converted PDF...'
        processing_status[task_id]['progress'] = 60
        
        logger.info(f"Saving files to output directory: {output_dir}")
        # Save the converted file
        saved_files = result.save_files(output_dir)
        
        logger.info(f"Saved files: {saved_files}")
        if not saved_files or len(saved_files) == 0:
            raise Exception("No files were returned from ConvertAPI")
        
        output_path = saved_files[0]
        logger.info(f"Output file path: {output_path}")
        
        processing_status[task_id]['message'] = 'Searchable PDF created successfully!'
        processing_status[task_id]['progress'] = 90
        
        # Update database status only
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE processing_jobs SET status = ?, completed_at = CURRENT_TIMESTAMP WHERE id = ?',
            ('completed', task_id)
        )
        conn.commit()
        conn.close()
        
        processing_status[task_id] = {
            'status': 'completed',
            'message': 'Searchable PDF created successfully',
            'progress': 100,
            'extraction_method': 'convertapi_ocr',
            'result': {
                'output_file': os.path.basename(output_path),
                'original_size_kb': round(os.path.getsize(input_path) / 1024, 2),
                'converted_size_kb': round(os.path.getsize(output_path) / 1024, 2)
            },
            'user_id': user_id
        }
        
        logger.info(f"ConvertAPI conversion completed for task {task_id}")
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"=== CONVERTAPI CONVERSION FAILED FOR TASK {task_id} ===")
        logger.error(f"Error: {str(e)}")
        logger.error(f"Full traceback:\n{error_details}")
        
        processing_status[task_id] = {
            'status': 'failed',
            'message': f'ConvertAPI conversion failed: {str(e)}',
            'progress': 0,
            'user_id': user_id
        }
        
        # Update database status only
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE processing_jobs SET status = ? WHERE id = ?',
            ('failed', task_id)
        )
        conn.commit()
        conn.close()

@app.route('/api/upload_glm_custom_query', methods=['POST'])
@jwt_required()
def upload_file_glm_custom_query():
    """Upload PDF for GLM-4.5V custom query extraction"""
    print("=== GLM CUSTOM QUERY UPLOAD ENDPOINT CALLED ===")
    
    user_id = int(get_jwt_identity())
    print(f"JWT validation successful, user_id: {user_id}")
    
    # Check if GLM API is configured
    if not GLM_API_KEY:
        return jsonify({'error': 'GLM API is not configured. Please add GLM_API_KEY to environment variables.'}), 500
    
    if 'file' not in request.files:
        print("Error: No file provided")
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    print(f"File received: {file.filename}")
    
    if file.filename == '' or not allowed_file(file.filename):
        print(f"Error: Invalid file type or empty filename: {file.filename}")
        return jsonify({'error': 'Invalid file type. Please upload a PDF file.'}), 400
    
    # Get custom query
    custom_query = request.form.get('custom_query', '')
    if not custom_query or custom_query.strip() == '':
        return jsonify({'error': 'Custom query is required for GLM extraction'}), 400
    
    print(f"Custom query received: {custom_query}")
    
    task_id = str(uuid.uuid4())
    filename = secure_filename(file.filename)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    input_filename = f"{timestamp}_{filename}"
    input_path = os.path.join(UPLOAD_FOLDER, input_filename)
    file.save(input_path)

    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO processing_jobs (id, user_id, filename, status, created_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)',
        (task_id, user_id, filename, 'processing')
    )
    conn.commit()
    conn.close()

    processing_status[task_id] = {
        'status': 'queued',
        'message': 'File uploaded, queued for GLM custom query extraction',
        'progress': 0,
        'user_id': user_id
    }

    thread = threading.Thread(
        target=process_pdf_with_glm_custom_query,
        args=(input_path, task_id, user_id, custom_query)
    )
    thread.start()
    
    print(f"GLM custom query extraction started for task_id: {task_id}")
    return jsonify({
        'task_id': task_id,
        'message': 'File uploaded successfully, extracting data with GLM-4.5V',
        'filename': filename
    })

@app.route('/api/upload_ocrmypdf', methods=['POST'])
@jwt_required()
def upload_file_ocrmypdf():
    """Upload scanned PDF and convert to searchable PDF using OCRmyPDF (local)"""
    print("=== OCRMYPDF UPLOAD ENDPOINT CALLED ===")
    
    user_id = int(get_jwt_identity())
    print(f"JWT validation successful, user_id: {user_id}")
    
    if 'file' not in request.files:
        print("Error: No file provided")
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    print(f"File received: {file.filename}")
    
    if file.filename == '' or not allowed_file(file.filename):
        print(f"Error: Invalid file type or empty filename: {file.filename}")
        return jsonify({'error': 'Invalid file type. Please upload a PDF file.'}), 400
    
    task_id = str(uuid.uuid4())
    filename = secure_filename(file.filename)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    input_filename = f"{timestamp}_{filename}"
    input_path = os.path.join(UPLOAD_FOLDER, input_filename)
    file.save(input_path)

    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO processing_jobs (id, user_id, filename, status, created_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)',
        (task_id, user_id, filename, 'processing')
    )
    conn.commit()
    conn.close()

    processing_status[task_id] = {
        'status': 'queued',
        'message': 'File uploaded, queued for OCRmyPDF conversion',
        'progress': 0,
        'user_id': user_id
    }

    thread = threading.Thread(
        target=convert_pdf_to_searchable_ocrmypdf,
        args=(input_path, task_id, user_id)
    )
    thread.start()
    
    print(f"OCRmyPDF conversion started for task_id: {task_id}")
    return jsonify({
        'task_id': task_id,
        'message': 'File uploaded successfully, converting to searchable PDF with OCRmyPDF (local)',
        'filename': filename
    })

@app.route('/api/upload_convertapi_ocr', methods=['POST'])
@jwt_required()
def upload_file_convertapi_ocr():
    """Upload scanned PDF and convert to searchable PDF using ConvertAPI"""
    print("=== CONVERTAPI OCR UPLOAD ENDPOINT CALLED ===")
    
    user_id = int(get_jwt_identity())
    print(f"JWT validation successful, user_id: {user_id}")
    
    # Check if ConvertAPI is configured
    if not CONVERT_API_KEY:
        return jsonify({'error': 'ConvertAPI is not configured. Please add CONVERT_API_KEY to environment variables.'}), 500
    
    if 'file' not in request.files:
        print("Error: No file provided")
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    print(f"File received: {file.filename}")
    
    if file.filename == '' or not allowed_file(file.filename):
        print(f"Error: Invalid file type or empty filename: {file.filename}")
        return jsonify({'error': 'Invalid file type. Please upload a PDF file.'}), 400
    
    task_id = str(uuid.uuid4())
    filename = secure_filename(file.filename)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    input_filename = f"{timestamp}_{filename}"
    input_path = os.path.join(UPLOAD_FOLDER, input_filename)
    file.save(input_path)

    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO processing_jobs (id, user_id, filename, status, created_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)',
        (task_id, user_id, filename, 'processing')
    )
    conn.commit()
    conn.close()

    processing_status[task_id] = {
        'status': 'queued',
        'message': 'File uploaded, queued for ConvertAPI OCR',
        'progress': 0,
        'user_id': user_id
    }

    thread = threading.Thread(
        target=convert_pdf_to_searchable_convertapi,
        args=(input_path, task_id, user_id)
    )
    thread.start()
    
    print(f"ConvertAPI OCR started for task_id: {task_id}")
    return jsonify({
        'task_id': task_id,
        'message': 'File uploaded successfully, converting to searchable PDF with ConvertAPI',
        'filename': filename
    })

@app.route('/api/upload_searchable_pdf', methods=['POST'])
@jwt_required()
def upload_file_searchable_pdf():
    """Upload scanned PDF and convert to searchable PDF using AWS Textract"""
    print("=== SEARCHABLE PDF UPLOAD ENDPOINT CALLED ===")
    
    user_id = int(get_jwt_identity())
    print(f"JWT validation successful, user_id: {user_id}")
    
    if 'file' not in request.files:
        print("Error: No file provided")
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    print(f"File received: {file.filename}")
    
    if file.filename == '' or not allowed_file(file.filename):
        print(f"Error: Invalid file type or empty filename: {file.filename}")
        return jsonify({'error': 'Invalid file type. Please upload a PDF file.'}), 400
    
    task_id = str(uuid.uuid4())
    filename = secure_filename(file.filename)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    input_filename = f"{timestamp}_{filename}"
    input_path = os.path.join(UPLOAD_FOLDER, input_filename)
    file.save(input_path)

    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO processing_jobs (id, user_id, filename, status, created_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)',
        (task_id, user_id, filename, 'processing')
    )
    conn.commit()
    conn.close()

    processing_status[task_id] = {
        'status': 'queued',
        'message': 'File uploaded, queued for searchable PDF creation',
        'progress': 0,
        'user_id': user_id
    }

    thread = threading.Thread(
        target=create_searchable_pdf_from_textract,
        args=(input_path, task_id, user_id)
    )
    thread.start()
    
    print(f"Searchable PDF creation started for task_id: {task_id}")
    return jsonify({
        'task_id': task_id,
        'message': 'File uploaded successfully, creating searchable PDF',
        'filename': filename
    })

@app.errorhandler(422)
def handle_unprocessable_entity(e):
    print(f"422 Error occurred: {str(e)}")
    print(f"Error description: {e.description if hasattr(e, 'description') else 'No description'}")
    return jsonify({'error': 'Unprocessable Entity', 'details': str(e)}), 422

@app.errorhandler(Exception)
def handle_general_exception(e):
    print(f"General exception: {str(e)}")
    print(f"Exception type: {type(e).__name__}")
    import traceback
    traceback.print_exc()
    return jsonify({'error': 'Internal server error', 'details': str(e)}), 500

@app.route('/api/status/<task_id>', methods=['GET'])
@jwt_required()
def get_status(task_id):
    """Get processing status"""
    user_id = get_jwt_identity()
    # Convert to int for comparison (handles both string and int user_ids)
    try:
        user_id_int = int(user_id)
    except (ValueError, TypeError):
        user_id_int = user_id
    
    if task_id not in processing_status:
        return jsonify({'error': 'Task not found'}), 404
    
    status = processing_status[task_id]

    # Handle both string and int user_id comparisons
    status_user_id = status.get('user_id')
    try:
        status_user_id_int = int(status_user_id)
    except (ValueError, TypeError):
        status_user_id_int = status_user_id
    
    if status_user_id_int != user_id_int and str(status_user_id) != str(user_id):
        return jsonify({'error': 'Unauthorized'}), 403
    
    return jsonify(status)

@app.route('/api/download/<task_id>', methods=['GET'])
@jwt_required()
def download_file(task_id):
    user_id = get_jwt_identity()
    # Convert to int for comparison (handles both string and int user_ids)
    try:
        user_id_int = int(user_id)
    except (ValueError, TypeError):
        user_id_int = user_id
    
    if task_id not in processing_status:
        return jsonify({'error': 'Task not found'}), 404
    
    status = processing_status[task_id]

    # Handle both string and int user_id comparisons
    status_user_id = status.get('user_id')
    try:
        status_user_id_int = int(status_user_id)
    except (ValueError, TypeError):
        status_user_id_int = status_user_id
    
    if status_user_id_int != user_id_int and str(status_user_id) != str(user_id):
        return jsonify({'error': 'Unauthorized'}), 403
    
    if status['status'] != 'completed':
        return jsonify({'error': 'File not ready for download'}), 400
    
    # Handle different status structures - check both direct and nested in 'result'
    if 'output_file' in status:
        output_file = status['output_file']
    elif 'result' in status and 'output_file' in status['result']:
        output_file = status['result']['output_file']
    else:
        return jsonify({'error': 'Output file information not found'}), 404
    
    output_path = os.path.join(OUTPUT_FOLDER, output_file)
    
    if not os.path.exists(output_path):
        return jsonify({'error': 'File not found'}), 404
    
    return send_file(output_path, as_attachment=True, download_name=output_file)

@app.route('/api/download_all/<task_id>', methods=['GET'])
@jwt_required()
def download_all(task_id):
    user_id = int(get_jwt_identity())
    
    if task_id not in processing_status:
        return jsonify({'error': 'Task not found'}), 404
    
    status = processing_status[task_id]
    if status.get('user_id') != user_id:
        return jsonify({'error': 'Unauthorized'}), 403
    
    if status['status'] != 'completed':
        return jsonify({'error': 'Files not ready for download'}), 400

    zip_filename = f"OCR_Results_{task_id}.zip"
    zip_path = os.path.join(OUTPUT_FOLDER, zip_filename)
    
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        # Handle different status structures
        if 'output_file' in status:
            output_file = status['output_file']
        elif 'result' in status and 'output_file' in status['result']:
            output_file = status['result']['output_file']
        else:
            output_file = None
            
        if output_file:
            output_path = os.path.join(OUTPUT_FOLDER, output_file)
            if os.path.exists(output_path):
                zipf.write(output_path, output_file)
    
        if 'tables' in status and status['tables'] and status['tables_dir']:
            tables_dir = status['tables_dir']
            for table_info in status['tables']:
                for file_key in ['csv_file', 'excel_file']:
                    if file_key in table_info:
                        table_path = os.path.join(tables_dir, table_info[file_key])
                        if os.path.exists(table_path):
                            zipf.write(table_path, f"tables/{table_info[file_key]}")
    
    return send_file(zip_path, as_attachment=True, download_name=zip_filename)

@app.route('/api/jobs', methods=['GET'])
@jwt_required()
def get_user_jobs():
    user_id = int(get_jwt_identity())
    
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, filename, status, created_at, completed_at 
        FROM processing_jobs 
        WHERE user_id = ? 
        ORDER BY created_at DESC
    ''', (user_id,))
    jobs = cursor.fetchall()
    conn.close()
    
    return jsonify({
        'jobs': [{
            'id': job[0],
            'filename': job[1],
            'status': job[2],
            'created_at': job[3],
            'completed_at': job[4]
        } for job in jobs]
    })

# ============================================================================
# ABAQUS FEM INTEGRATION - Extract dimensions & stress-strain, modify .inp
# ============================================================================


def modify_abaqus_inp(base_inp_path, output_inp_path, dimensions, stress_strain_data):
    """
    Modify Abaqus .inp file with extracted dimensions and stress-strain data.
    
    For cylindrical specimens:
    - X, Y coordinates represent the circular cross-section (diameter in XY plane)
    - Z coordinate represents the cylinder height/length
    
    Parameters:
    - base_inp_path: Path to base Compression.inp file
    - output_inp_path: Path to save modified .inp file
    - dimensions: Dict with 'diameter', 'length' keys
    - stress_strain_data: List of {'stress': float, 'strain': float} dicts
    """
    try:
        # Base Compression.inp dimensions (measured from coordinates)
        # Max X,Y ≈ ±99.95 → radius ≈ 100mm → diameter = 100mm
        # Max Z = 150mm → length = 150mm
        base_diameter = 100.0
        base_length = 150.0
        
        # Get new dimensions
        new_diameter = dimensions.get('diameter')
        new_length = dimensions.get('length')
        
        # Calculate scale factors for XY (diameter) and Z (length)
        if new_diameter is None or not isinstance(new_diameter, (int, float)) or new_diameter <= 0:
            logger.warning(f"Diameter not found or invalid ({new_diameter}), using base diameter {base_diameter}mm (XY scale factor 1.0)")
            new_diameter = base_diameter
            scale_xy = 1.0
        else:
            scale_xy = new_diameter / base_diameter
            logger.info(f"Scaling diameter from {base_diameter}mm to {new_diameter}mm (XY scale factor: {scale_xy})")
        
        if new_length is None or not isinstance(new_length, (int, float)) or new_length <= 0:
            logger.warning(f"Length not found or invalid ({new_length}), using base length {base_length}mm (Z scale factor 1.0)")
            new_length = base_length
            scale_z = 1.0
        else:
            scale_z = new_length / base_length
            logger.info(f"Scaling length from {base_length}mm to {new_length}mm (Z scale factor: {scale_z})")
        
        # Calculate strain from stress-strain data
        # Use the maximum strain value or average
        if stress_strain_data and len(stress_strain_data) > 0:
            # Get the strain at maximum stress
            max_stress_point = max(stress_strain_data, key=lambda x: x.get('stress', 0))
            strain_value = max_stress_point.get('strain', -0.3)
        else:
            strain_value = -0.3  # Default compression strain
        
        # Read base file
        with open(base_inp_path, 'r') as f:
            lines = f.readlines()
        
        modified_lines = []
        in_node_section = False
        original_length = None
        
        for line in lines:
            # Check if we're entering the *Node section
            if line.strip().startswith('*Node'):
                in_node_section = True
                modified_lines.append(line)
                continue
            
            # Check if we're leaving the *Node section
            if in_node_section and line.strip().startswith('*'):
                in_node_section = False
            
            # Modify node coordinates if in *Node section
            if in_node_section and not line.strip().startswith('*'):
                parts = line.strip().split(',')
                if len(parts) >= 4:
                    try:
                        node_id = parts[0].strip()
                        # Scale X,Y by diameter ratio, Z by length ratio
                        x = float(parts[1].strip()) * scale_xy
                        y = float(parts[2].strip()) * scale_xy
                        z = float(parts[3].strip()) * scale_z
                        
                        if original_length is None or z > original_length:
                            original_length = z
                        
                        def format_coord(value):
                            if abs(value) < 1e-10:
                                return f"{'0.':>13}"
                            else:
                                formatted = f"{value:.7f}".rstrip('0')
                                if '.' not in formatted:
                                    formatted += '.'
                                elif formatted.endswith('.'):
                                    pass
                                return f"{formatted:>13}"
                        
                        modified_line = f"{node_id:>7}, {format_coord(x)}, {format_coord(y)}, {format_coord(z)}\n"
                        modified_lines.append(modified_line)
                        continue
                    except (ValueError, IndexError):
                        pass
            
            # Modify boundary condition displacement
            if line.strip().startswith('loading, 3, 3,') and strain_value != 0.0:
                if original_length is not None:
                    displacement = strain_value * original_length
                    if displacement == int(displacement):
                        modified_line = f"loading, 3, 3, {int(displacement)}.\n"
                    else:
                        modified_line = f"loading, 3, 3, {displacement}.\n"
                    modified_lines.append(modified_line)
                    logger.info(f"Modified displacement: {displacement} (strain: {strain_value}, length: {original_length})")
                    continue
            
            # Keep all other lines unchanged
            modified_lines.append(line)
        
        # Write modified file
        with open(output_inp_path, 'w') as f:
            f.writelines(modified_lines)
        
        logger.info(f"Modified .inp file saved: {output_inp_path}")
        return True
        
    except Exception as e:
        logger.error(f"Error modifying .inp file: {str(e)}")
        raise

@app.route('/api/download_inp/<task_id>', methods=['GET'])
@jwt_required()
def download_inp_file(task_id):
    """Download the generated .inp file"""
    try:
        user_id = int(get_jwt_identity())
        
        if task_id not in processing_status:
            return jsonify({'error': 'Task not found'}), 404
        
        task_data = processing_status[task_id]
        
        if task_data.get('user_id') != user_id:
            return jsonify({'error': 'Unauthorized'}), 403
        
        if task_data.get('status') != 'completed':
            return jsonify({'error': 'Processing not completed'}), 400
        
        output_file = task_data.get('output_file')
        output_filename = task_data.get('output_filename', 'modified.inp')
        
        if not output_file or not os.path.exists(output_file):
            return jsonify({'error': 'Output file not found'}), 404
        
        return send_file(
            output_file,
            as_attachment=True,
            download_name=output_filename,
            mimetype='text/plain'
        )
        
    except Exception as e:
        logger.error(f"Error downloading .inp file: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/download_csv/<task_id>', methods=['GET'])
@jwt_required()
def download_csv_file(task_id):
    """Download the stress-strain CSV file from GLM ABAQUS generation"""
    try:
        # Convert user_id to int for comparison
        user_id = get_jwt_identity()
        try:
            user_id_int = int(user_id)
        except (ValueError, TypeError):
            user_id_int = user_id
        
        if task_id not in processing_status:
            return jsonify({'error': 'Task not found'}), 404
        
        task_data = processing_status[task_id]
        
        # Handle both string and int user_id comparisons
        status_user_id = task_data.get('user_id')
        try:
            status_user_id_int = int(status_user_id)
        except (ValueError, TypeError):
            status_user_id_int = status_user_id
        
        if status_user_id_int != user_id_int and str(status_user_id) != str(user_id):
            return jsonify({'error': 'Unauthorized'}), 403
        
        if task_data.get('status') != 'completed':
            return jsonify({'error': 'Processing not completed'}), 400
        
        csv_filename = task_data.get('csv_file')
        
        if not csv_filename:
            return jsonify({'error': 'No CSV file available for this task'}), 404
        
        csv_path = os.path.join(OUTPUT_FOLDER, csv_filename)
        
        if not os.path.exists(csv_path):
            return jsonify({'error': 'CSV file not found'}), 404
        
        return send_file(
            csv_path,
            as_attachment=True,
            download_name=csv_filename,
            mimetype='text/csv'
        )
        
    except Exception as e:
        logger.error(f"Error downloading CSV file: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/upload_glm_table_extraction', methods=['POST'])
@jwt_required()
def upload_glm_table_extraction():
    """
    Extract tables from PDF using GLM-4.5V Vision API
    Converts PDF pages to images and sends to GLM for table extraction
    Returns CSV format by default, supports custom prompts
    """
    try:
        current_user = get_jwt_identity()
        logger.info(f"User {current_user} requested GLM table extraction")
        
        # Validate file upload
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'Empty filename'}), 400
        
        # Get custom prompt (optional)
        custom_prompt = request.form.get('custom_prompt', '').strip() or None
        
        # Save uploaded PDF
        filename = secure_filename(file.filename)
        task_id = str(uuid.uuid4())
        pdf_path = os.path.join(UPLOAD_FOLDER, f"{task_id}_{filename}")
        file.save(pdf_path)
        
        # Task status
        task_status = {
            'status': 'processing',
            'message': 'Converting PDF to images...',
            'progress': 0,
            'user_id': int(current_user),
            'extraction_method': 'glm_table_extraction'
        }
        
        processing_status[task_id] = task_status
        
        def process_glm_extraction():
            try:
                task_status['message'] = 'Converting PDF to images...'
                task_status['progress'] = 20
                
                # Convert PDF to images using pdf2image (same as glmextract.py)
                from pdf2image import convert_from_path
                import base64
                
                images = convert_from_path(pdf_path)
                page_count = len(images)
                logger.info(f"Converted {page_count} PDF pages to images")
                
                task_status['message'] = 'Extracting tables with GLM-4.5V...'
                task_status['progress'] = 40
                
                # Build content array with all images in sequence
                content = []
                
                # Add all images first (in order)
                for idx, img in enumerate(images):
                    img_byte_arr = io.BytesIO()
                    img.save(img_byte_arr, format='JPEG')
                    base64_image = base64.b64encode(img_byte_arr.getvalue()).decode('utf-8')
                    
                    content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        }
                    })
                
                # Add the text prompt
                if custom_prompt:
                    prompt_text = custom_prompt
                else:
                    prompt_text = "Extract all the tables from this series of images in their sequence and output it as CSV."
                
                content.append({
                    "type": "text",
                    "text": prompt_text
                })
                
                # Send to GLM-4.5V
                from zhipuai import ZhipuAI
                client = ZhipuAI(api_key=GLM_API_KEY)
                
                response = client.chat.completions.create(
                    model="glm-4.5v",
                    messages=[
                        {
                            "role": "user",
                            "content": content
                        }
                    ],
                    temperature=0.1,
                    thinking={
                        "type": "disabled"
                    }
                )
                
                extracted_content = response.choices[0].message.content
                usage = {
                    'prompt_tokens': response.usage.prompt_tokens,
                    'completion_tokens': response.usage.completion_tokens,
                    'total_tokens': response.usage.total_tokens
                }
                
                task_status['progress'] = 80
                task_status['message'] = 'Saving extracted tables...'
                
                # Save CSV output
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                csv_filename = f"tables_{timestamp}_{task_id[:8]}.csv"
                csv_path = os.path.join(OUTPUT_FOLDER, csv_filename)
                
                with open(csv_path, 'w', encoding='utf-8') as f:
                    f.write(extracted_content)
                
                # Save full output as text file too
                txt_filename = f"tables_{timestamp}_{task_id[:8]}.txt"
                txt_path = os.path.join(OUTPUT_FOLDER, txt_filename)
                
                with open(txt_path, 'w', encoding='utf-8') as f:
                    f.write(extracted_content)
                
                logger.info(f"GLM table extraction completed: {csv_path}")
                
                task_status['status'] = 'completed'
                task_status['message'] = 'Table extraction completed'
                task_status['progress'] = 100
                task_status['output_file'] = csv_filename
                task_status['output_filename'] = csv_filename
                task_status['txt_file'] = txt_filename
                task_status['txt_filename'] = txt_filename
                task_status['extracted_content'] = extracted_content
                task_status['model_used'] = 'glm-4.5v'
                task_status['token_usage'] = usage
                task_status['tokens_used'] = usage.get('total_tokens', 0)
                task_status['pages_processed'] = page_count
                
            except Exception as e:
                logger.error(f"GLM table extraction error: {str(e)}", exc_info=True)
                task_status['status'] = 'error'
                task_status['message'] = f'Error: {str(e)}'
        
        # Start background processing
        thread = threading.Thread(target=process_glm_extraction)
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'task_id': task_id,
            'message': 'GLM table extraction started',
            'status': 'processing'
        }), 202
        
    except Exception as e:
        logger.error(f"Error in GLM table extraction upload: {str(e)}")
        return jsonify({'error': str(e)}), 500


# GLM ABAQUS Generator Endpoint
# Add this to app.py before "if __name__ == '__main__':"

@app.route('/api/upload_glm_abaqus_generator', methods=['POST'])
@jwt_required()
def upload_glm_abaqus_generator():
    """
    GLM-4.5V based ABAQUS input file generator
    Extracts stress-strain data and dimensions for a specific serial number,
    then generates modified ABAQUS .inp file
    """
    try:
        user_id = get_jwt_identity()
        
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        serial_number = request.form.get('serial_number', '').strip()  # Changed from serialNumber to serial_number
        
        if not serial_number:
            return jsonify({'error': 'Serial number is required'}), 400
        
        if file.filename == '':
            return jsonify({'error': 'Empty filename'}), 400
        
        # Save uploaded PDF
        filename = secure_filename(file.filename)
        task_id = str(uuid.uuid4())
        pdf_path = os.path.join(UPLOAD_FOLDER, f"{task_id}_{filename}")
        file.save(pdf_path)
        
        logger.info(f"GLM ABAQUS generator started for serial: {serial_number}")
        
        # Initialize task status
        task_status = {
            'status': 'processing',
            'message': 'Starting ABAQUS input generation...',
            'progress': 10,
            'user_id': user_id,
            'serial_number': serial_number,
            'extraction_method': 'glm_abaqus_generator'
        }
        
        processing_status[task_id] = task_status
        
        def process_glm_abaqus():
            try:
                task_status['message'] = 'Converting PDF to images...'
                task_status['progress'] = 20
                
                # Convert PDF to images
                from pdf2image import convert_from_path
                import base64
                import re
                
                images = convert_from_path(pdf_path)
                page_count = len(images)
                logger.info(f"Converted {page_count} PDF pages to images")
                
                task_status['message'] = f'Extracting data for serial {serial_number}...'
                task_status['progress'] = 30
                
                # Build content array with all images
                content = []
                for idx, img in enumerate(images):
                    img_byte_arr = io.BytesIO()
                    img.save(img_byte_arr, format='JPEG')
                    base64_image = base64.b64encode(img_byte_arr.getvalue()).decode('utf-8')
                    
                    content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        }
                    })
                
                # Add extraction prompt
                prompt_text = f"""Extract the following information for specimen with serial number {serial_number}:

1. Stress-Strain Data Table - Extract ALL stress and strain values in CSV format with headers: Sample ID, Stress, Strain
2. Dimensions - Extract the Length (Len) and Diameter (Dia) in mm

Output format:
DIMENSIONS:
Length: <value> mm
Diameter: <value> mm

STRESS_STRAIN_DATA:
<CSV data with Sample ID, Stress, Strain headers>

Extract only data for serial number {serial_number}. Be precise with numerical values."""
                
                content.append({
                    "type": "text",
                    "text": prompt_text
                })
                
                # Send to GLM-4.5V
                from zhipuai import ZhipuAI
                client = ZhipuAI(api_key=GLM_API_KEY)
                
                task_status['progress'] = 50
                
                response = client.chat.completions.create(
                    model="glm-4.5v",
                    messages=[{
                        "role": "user",
                        "content": content
                    }],
                    temperature=0.1,
                    thinking={"type": "disabled"}
                )
                
                extracted_content = response.choices[0].message.content
                logger.info(f"GLM extraction complete: {extracted_content[:500]}")
                
                task_status['progress'] = 60
                task_status['message'] = 'Parsing extracted data...'
                
                # Parse dimensions
                length_match = re.search(r'Length:\s*(\d+(?:\.\d+)?)', extracted_content)
                diameter_match = re.search(r'Diameter:\s*(\d+(?:\.\d+)?)', extracted_content)
                
                if not length_match or not diameter_match:
                    raise ValueError("Could not extract dimensions from PDF")
                
                length = float(length_match.group(1))
                diameter = float(diameter_match.group(1))
                
                # Calculate scale factors
                # Template dimensions: Length=100mm, Diameter=100mm
                scale_factor_length = length / 100.0
                scale_factor_diameter = diameter / 100.0
                
                logger.info(f"Dimensions: L={length}mm, D={diameter}mm, Scale: L={scale_factor_length}, D={scale_factor_diameter}")
                
                # Extract CSV data
                csv_match = re.search(r'STRESS_STRAIN_DATA:\s*\n(.*?)(?:\n\n|$)', extracted_content, re.DOTALL)
                if not csv_match:
                    # Try alternate format
                    csv_match = re.search(r'Sample ID,Stress,Strain\s*\n(.*?)(?:\n\n|$)', extracted_content, re.DOTALL)
                
                if not csv_match:
                    raise ValueError("Could not extract stress-strain data")
                
                stress_strain_csv = csv_match.group(1).strip()
                
                # Save stress-strain data
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                csv_filename = f"stress_strain_{serial_number}_{timestamp}.csv"
                csv_path = os.path.join(OUTPUT_FOLDER, csv_filename)
                
                with open(csv_path, 'w', encoding='utf-8') as f:
                    f.write("Sample ID,Stress,Strain\n")
                    f.write(stress_strain_csv)
                
                task_status['progress'] = 70
                task_status['message'] = 'Generating ABAQUS input file...'
                
                # Run modify_abaqus_input.py
                from modify_abaqus_input import modify_abaqus_file
                
                base_inp = "Compression.inp"
                output_inp_filename = f"Compression_{serial_number}_{timestamp}.inp"
                output_inp_path = os.path.join(OUTPUT_FOLDER, output_inp_filename)
                
                # Calculate strain (assume max strain from data or use -0.18 as default)
                strain = -0.18  # Default compression strain
                
                modify_abaqus_file(
                    base_inp,
                    output_inp_path,
                    scale_factor_d=scale_factor_diameter,
                    scale_factor=scale_factor_length,
                    strain=strain,
                    stress_strain_csv=csv_path
                )
                
                logger.info(f"ABAQUS file generated: {output_inp_path}")
                
                task_status['progress'] = 100
                task_status['status'] = 'completed'
                task_status['message'] = 'ABAQUS input file generated successfully'
                task_status['output_file'] = output_inp_filename
                task_status['output_file_path'] = output_inp_path  # Full path for simulation
                task_status['csv_file'] = csv_filename
                task_status['length'] = length
                task_status['diameter'] = diameter
                task_status['scale_factor_length'] = scale_factor_length
                task_status['scale_factor_diameter'] = scale_factor_diameter
                task_status['extracted_content'] = extracted_content
                
            except Exception as e:
                logger.error(f"GLM ABAQUS generation error: {str(e)}", exc_info=True)
                task_status['status'] = 'error'
                task_status['message'] = f'Error: {str(e)}'
        
        # Start background processing
        thread = threading.Thread(target=process_glm_abaqus)
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'task_id': task_id,
            'message': 'ABAQUS generation started',
            'status': 'processing'
        }), 202
        
    except Exception as e:
        logger.error(f"Error in GLM ABAQUS generator: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/run_abaqus_simulation/<task_id>', methods=['POST'])
@jwt_required()
def run_abaqus_simulation(task_id):
    """
    Run ABAQUS simulation using the generated .inp file
    Executes ABAQUS CLI command and streams output
    """
    try:
        # Convert user_id for authorization
        user_id = get_jwt_identity()
        try:
            user_id_int = int(user_id)
        except (ValueError, TypeError):
            user_id_int = user_id
        
        if task_id not in processing_status:
            logger.error(f"Task {task_id} not found in processing_status. Available tasks: {list(processing_status.keys())}")
            return jsonify({'error': 'Task not found'}), 404
        
        task_data = processing_status[task_id]
        
        # Authorization check
        status_user_id = task_data.get('user_id')
        try:
            status_user_id_int = int(status_user_id)
        except (ValueError, TypeError):
            status_user_id_int = status_user_id
        
        if status_user_id_int != user_id_int and str(status_user_id) != str(user_id):
            return jsonify({'error': 'Unauthorized'}), 403
        
        if task_data.get('status') != 'completed':
            return jsonify({'error': 'Input file generation not completed'}), 400
        
        # Get the full path to the .inp file
        output_file = task_data.get('output_file_path')
        
        # Fallback: if output_file_path doesn't exist, construct from output_file
        if not output_file:
            output_filename = task_data.get('output_file')
            if output_filename:
                output_file = os.path.join(OUTPUT_FOLDER, output_filename)
        
        if not output_file or not os.path.exists(output_file):
            return jsonify({'error': 'Input file not found'}), 404
        
        # Create simulation task ID
        sim_task_id = str(uuid.uuid4())
        sim_status = {
            'task_id': sim_task_id,
            'user_id': user_id,
            'status': 'running',
            'message': 'Starting ABAQUS simulation...',
            'progress': 0,
            'output': [],
            'inp_file': output_file
        }
        processing_status[sim_task_id] = sim_status
        
        def run_simulation():
            try:
                import subprocess
                
                # Get the directory and filename
                inp_dir = os.path.dirname(output_file)
                inp_name = os.path.splitext(os.path.basename(output_file))[0]
                inp_filename = os.path.basename(output_file)
                
                sim_status['message'] = 'Executing ABAQUS command...'
                sim_status['progress'] = 10
                
                # ABAQUS command: abaqus job=<jobname> input=<inputfile> interactive
                # Use shell=True on Windows to access PATH commands properly
                # Since cwd is set to inp_dir, use only the filename for input
                abaqus_cmd = f'abaqus job={inp_name} input="{inp_filename}" interactive ask_delete=OFF'
                
                logger.info(f"Running ABAQUS: {abaqus_cmd}")
                logger.info(f"Working directory: {inp_dir}")
                sim_status['output'].append(f"Command: {abaqus_cmd}\n")
                sim_status['output'].append(f"Working directory: {inp_dir}\n")
                
                # Run ABAQUS process with shell=True for Windows
                process = subprocess.Popen(
                    abaqus_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    cwd=inp_dir,
                    bufsize=1,
                    universal_newlines=True,
                    shell=True
                )
                
                sim_status['progress'] = 20
                
                # Stream output
                for line in iter(process.stdout.readline, ''):
                    if line:
                        sim_status['output'].append(line)
                        logger.info(f"ABAQUS: {line.strip()}")
                        
                        # Update progress based on output
                        if 'COMPLETED' in line.upper() or 'completed successfully' in line.lower():
                            sim_status['progress'] = 90
                        elif 'Begin Abaqus/Standard Analysis' in line:
                            sim_status['progress'] = 40
                        elif 'End Abaqus/Standard Analysis' in line:
                            sim_status['progress'] = 80
                        elif 'Step' in line or 'Increment' in line:
                            sim_status['progress'] = min(75, sim_status['progress'] + 5)
                
                process.wait()
                
                if process.returncode == 0:
                    sim_status['status'] = 'completed'
                    sim_status['message'] = 'Simulation completed successfully'
                    sim_status['progress'] = 100
                    
                    # Look for output files
                    odb_file = os.path.join(inp_dir, f"{inp_name}.odb")
                    dat_file = os.path.join(inp_dir, f"{inp_name}.dat")
                    msg_file = os.path.join(inp_dir, f"{inp_name}.msg")
                    sta_file = os.path.join(inp_dir, f"{inp_name}.sta")
                    
                    output_files_dict = {}
                    if os.path.exists(odb_file):
                        output_files_dict['odb'] = odb_file
                    if os.path.exists(dat_file):
                        output_files_dict['dat'] = dat_file
                    if os.path.exists(msg_file):
                        output_files_dict['msg'] = msg_file
                    if os.path.exists(sta_file):
                        output_files_dict['sta'] = sta_file
                    
                    sim_status['output_files'] = output_files_dict
                    logger.info(f"Output files found: {list(output_files_dict.keys())}")
                    
                    sim_status['output'].append("\n=== Simulation completed successfully ===\n")
                else:
                    sim_status['status'] = 'error'
                    sim_status['message'] = f'Simulation failed with exit code {process.returncode}'
                    sim_status['output'].append(f"\n=== Simulation failed with exit code {process.returncode} ===\n")
                
            except FileNotFoundError:
                sim_status['status'] = 'error'
                sim_status['message'] = 'ABAQUS not found. Please ensure ABAQUS is installed and in PATH.'
                sim_status['output'].append("ERROR: ABAQUS executable not found in system PATH\n")
                logger.error("ABAQUS executable not found")
            except Exception as e:
                sim_status['status'] = 'error'
                sim_status['message'] = f'Simulation error: {str(e)}'
                sim_status['output'].append(f"\nERROR: {str(e)}\n")
                logger.error(f"ABAQUS simulation error: {str(e)}", exc_info=True)
        
        # Start simulation in background thread
        thread = threading.Thread(target=run_simulation)
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'simulation_task_id': sim_task_id,
            'message': 'ABAQUS simulation started',
            'status': 'running'
        }), 202
        
    except Exception as e:
        logger.error(f"Error starting ABAQUS simulation: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/simulation_status/<sim_task_id>', methods=['GET'])
@jwt_required()
def get_simulation_status(sim_task_id):
    """Get the status and output of a running ABAQUS simulation"""
    try:
        user_id = get_jwt_identity()
        try:
            user_id_int = int(user_id)
        except (ValueError, TypeError):
            user_id_int = user_id
        
        if sim_task_id not in processing_status:
            return jsonify({'error': 'Simulation task not found'}), 404
        
        sim_data = processing_status[sim_task_id]
        
        # Authorization check
        status_user_id = sim_data.get('user_id')
        try:
            status_user_id_int = int(status_user_id)
        except (ValueError, TypeError):
            status_user_id_int = status_user_id
        
        if status_user_id_int != user_id_int and str(status_user_id) != str(user_id):
            return jsonify({'error': 'Unauthorized'}), 403
        
        return jsonify({
            'status': sim_data.get('status'),
            'message': sim_data.get('message'),
            'progress': sim_data.get('progress', 0),
            'output': ''.join(sim_data.get('output', [])),
            'output_files': sim_data.get('output_files', {})
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting simulation status: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/download_result/<sim_task_id>/<file_type>', methods=['GET'])
@jwt_required()
def download_simulation_result(sim_task_id, file_type):
    """Download ABAQUS simulation result files (.dat, .msg, .sta, etc.)"""
    try:
        user_id = get_jwt_identity()
        try:
            user_id_int = int(user_id)
        except (ValueError, TypeError):
            user_id_int = user_id
        
        if sim_task_id not in processing_status:
            return jsonify({'error': 'Simulation task not found'}), 404
        
        sim_data = processing_status[sim_task_id]
        
        # Authorization check
        status_user_id = sim_data.get('user_id')
        try:
            status_user_id_int = int(status_user_id)
        except (ValueError, TypeError):
            status_user_id_int = status_user_id
        
        if status_user_id_int != user_id_int and str(status_user_id) != str(user_id):
            return jsonify({'error': 'Unauthorized'}), 403
        
        if sim_data.get('status') != 'completed':
            return jsonify({'error': 'Simulation not completed'}), 400
        
        output_files = sim_data.get('output_files', {})
        file_path = output_files.get(file_type)
        
        if not file_path or not os.path.exists(file_path):
            return jsonify({'error': f'{file_type.upper()} file not found'}), 404
        
        return send_file(
            file_path,
            as_attachment=True,
            download_name=os.path.basename(file_path)
        )
        
    except Exception as e:
        logger.error(f"Error downloading result file: {str(e)}")
        return jsonify({'error': str(e)}), 500



if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)
