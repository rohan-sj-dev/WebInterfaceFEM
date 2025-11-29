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
from openai import OpenAI
from glm_vision_service import GLMVisionService


# Load environment variables from .env file
load_dotenv()

# UNSTRACT CONFIGURATION
UNSTRACT_DEFAULT_URL = os.getenv('UNSTRACT_API_URL', 'https://us-central.unstract.com/deployment/api/org_XYP7vV7oXBLVNmLG/invoice-extract/')
UNSTRACT_DEFAULT_API_KEY = os.getenv('UNSTRACT_API_KEY', '')
UNSTRACT_QA_URL = os.getenv('UNSTRACT_QA_URL', None)

# AWS TEXTRACT CONFIGURATION
AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID', '')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY', '')
AWS_DEFAULT_REGION = os.getenv('AWS_DEFAULT_REGION', 'us-east-1')

# LLMWHISPERER CONFIGURATION
LLMWHISPERER_API_URL = os.getenv('LLMWHISPERER_API_URL', 'https://llmwhisperer-api.us-central.unstract.com/api/v2')
LLMWHISPERER_API_KEY = os.getenv('LLMWHISPERER_API_KEY', '')

# OPENAI CONFIGURATION
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')

# GLM CONFIGURATION
GLM_API_KEY = os.getenv('GLM_API_KEY', '')

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

def process_pdf_with_unstract(input_path, task_id, user_id, api_key=None, custom_prompts='', model_name='gpt-4-turbo'):
    """Process PDF using Unstract Cloud API with custom prompts and model selection"""
    try:
        processing_status[task_id] = {
            'status': 'processing',
            'message': 'Starting Unstract extraction...',
            'progress': 10,
            'user_id': user_id,
            'custom_prompts': custom_prompts,
            'model_name': model_name
        }
        
        # Get Unstract URL from environment or use configured default
        api_url = os.environ.get('UNSTRACT_API_URL', UNSTRACT_DEFAULT_URL)
        
        # If custom prompts are provided and we have a separate Q&A workflow, use it
        if custom_prompts and UNSTRACT_QA_URL:
            api_url = UNSTRACT_QA_URL
            logger.info(f"Using Unstract Q&A workflow for custom query")
        
        # Use provided API key or default from .env
        if api_key is None:
            api_key = UNSTRACT_DEFAULT_API_KEY
        
        logger.info(f"Using Unstract Cloud API URL: {api_url}")
        logger.info(f"Custom prompts: {custom_prompts}")
        logger.info(f"Selected model: {model_name}")
        
        headers = {
            'Authorization': f'Bearer {api_key}'
        }
        
        # Model to LLM Profile ID mapping
        # TODO: Replace these with your actual LLM Profile IDs from Unstract Prompt Studio
        # Get these from: Prompt Studio -> Settings -> LLM Profiles -> Copy Profile ID
        MODEL_PROFILE_MAPPING = {
            'gpt-4-turbo': None,  # Will use default profile if None
            'azure-gpt-4o': None   # Replace with actual profile ID
        }
        
        # Prepare form data for Unstract API
        # Matches the Postman collection format exactly
        form_data = {
            'timeout': '300',
            'include_metadata': 'False',  # Reduce overhead by excluding metadata
            'include_metrics': 'False'    # Reduce overhead by excluding metrics
        }
        
        # Add LLM profile selection if specified
        # This allows user to choose which model runs (GPT-4 Turbo or Azure GPT-4o)
        llm_profile_id = MODEL_PROFILE_MAPPING.get(model_name)
        if llm_profile_id:
            form_data['llm_profile_id'] = llm_profile_id
            logger.info(f"Using LLM profile ID: {llm_profile_id} for model: {model_name}")
        else:
            logger.info(f"Using default LLM profile (model: {model_name})")
        
        # Custom prompts override the default invoice extraction
        # If user provides custom prompts, those take precedence over the single invoice output
        # The prompts must be valid JSON and can be accessed in Unstract templates via {{custom_data.key}}
        if custom_prompts:
            import json
            custom_data_obj = {
                "instructions": custom_prompts,
                "user_query": custom_prompts,
                "override_default": True  # Flag to indicate custom extraction
            }
            form_data['custom_data'] = json.dumps(custom_data_obj)
            logger.info(f"Custom prompts will override default invoice extraction")
            logger.info(f"Custom data: {form_data['custom_data']}")
        else:
            logger.info(f"Using default invoice extraction (no custom prompts provided)")
        
        processing_status[task_id]['message'] = 'Uploading file to Unstract Cloud...'
        processing_status[task_id]['progress'] = 30
        
        # Add timing to identify bottlenecks
        upload_start_time = time.time()
        
        # Upload file to Unstract - field name MUST be 'files' (plural)
        # Add SSL/TLS retry logic for connection errors
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                request_start = time.time()
                
                with open(input_path, 'rb') as f:
                    # Unstract API requires 'files' as the field name (not 'file')
                    files = {'files': (os.path.basename(input_path), f, 'application/pdf')}
                    
                    logger.info(f"Sending request to Unstract API (attempt {attempt + 1}/{max_retries}): {api_url}")
                    logger.info(f"Form data: {form_data}")
                    logger.info(f"File name: {os.path.basename(input_path)}")
                    
                    # Disable SSL verification as a fallback (only if needed)
                    # Note: This is less secure but helps with SSL certificate issues
                    response = requests.post(
                        api_url, 
                        headers=headers, 
                        data=form_data,
                        files=files, 
                        timeout=120,  # Increased timeout to 120 seconds
                        verify=True  # Keep SSL verification enabled by default
                    )
                    
                    request_end = time.time()
                    request_duration = request_end - request_start
                    
                    logger.info(f"Unstract response status: {response.status_code}")
                    logger.info(f"Request took {request_duration:.2f} seconds")
                    logger.info(f"Unstract response: {response.text[:500]}")  # Log first 500 chars
                    break  # Success, exit retry loop
                    
            except requests.exceptions.SSLError as e:
                logger.warning(f"SSL Error on attempt {attempt + 1}/{max_retries}: {str(e)}")
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    # Last attempt failed, try without SSL verification
                    logger.warning("All SSL attempts failed, trying without SSL verification...")
                    try:
                        with open(input_path, 'rb') as f:
                            files = {'files': (os.path.basename(input_path), f, 'application/pdf')}
                            response = requests.post(
                                api_url, 
                                headers=headers, 
                                data=form_data,
                                files=files, 
                                timeout=120,
                                verify=False  # Disable SSL verification as last resort
                            )
                            logger.info(f"Request succeeded without SSL verification")
                            logger.info(f"Unstract response status: {response.status_code}")
                            logger.info(f"Unstract response: {response.text[:500]}")
                    except Exception as final_error:
                        raise Exception(f"Cannot connect to Unstract API at {api_url}. SSL connection failed even without verification. Error: {str(final_error)}")
                        
            except requests.exceptions.ConnectionError as e:
                logger.warning(f"Connection error on attempt {attempt + 1}/{max_retries}: {str(e)}")
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    raise Exception(f"Cannot connect to Unstract API at {api_url}. Please verify: 1) Unstract is running, 2) Network/firewall allows HTTPS connections, 3) API URL is correct. Error: {str(e)}")
                    
            except requests.exceptions.Timeout:
                logger.warning(f"Timeout on attempt {attempt + 1}/{max_retries}")
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    raise Exception("Unstract API request timed out after multiple attempts. Please check your network connection or try a smaller file.")
        
        if response.status_code != 200:
            error_msg = f"Unstract upload failed with status {response.status_code}: {response.text}"
            logger.error(error_msg)
            raise Exception(error_msg)
        
        try:
            upload_response = response.json()
            logger.info(f"Upload response: {upload_response}")
        except Exception as e:
            logger.error(f"Failed to parse Unstract response as JSON: {response.text}")
            raise Exception(f"Invalid response from Unstract API: {str(e)}")
        
        # Unstract wraps response in 'message' field
        message = upload_response.get('message', upload_response)
        execution_status = message.get('execution_status')
        result = message.get('result')
        
        logger.info(f"Initial execution status: {execution_status}")
        
        # Check if processing failed immediately
        if execution_status == 'ERROR':
            logger.error(f"Unstract processing failed immediately")
            
            # Extract error details from result
            error_details = "Unknown error"
            if result and len(result) > 0:
                file_result = result[0]
                error_details = file_result.get('error', 'Unknown error')
                logger.error(f"Error details: {error_details}")
            
            conn = sqlite3.connect('users.db')
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE processing_jobs SET status = ?, completed_at = CURRENT_TIMESTAMP WHERE id = ?',
                ('error', task_id)
            )
            conn.commit()
            conn.close()
            
            processing_status[task_id] = {
                'status': 'error',
                'message': f'Unstract processing failed: {error_details}',
                'progress': 100,
                'extraction_method': 'unstract',
                'error': error_details,
                'unstract_data': result,
                'user_id': user_id
            }
            logger.error(f"Unstract processing failed for task {task_id}: {error_details}")
            return
        
        # Check if already completed (fast processing)
        if execution_status == 'COMPLETED' and result:
            upload_end_time = time.time()
            total_upload_time = upload_end_time - upload_start_time
            
            logger.info("Processing completed immediately!")
            logger.info(f"Total time from upload to completion: {total_upload_time:.2f} seconds")
            
            # Log Unstract's internal timing if available
            if result and len(result) > 0:
                metadata = result[0].get('metadata', {})
                unstract_elapsed = metadata.get('total_elapsed_time', 0)
                logger.info(f"Unstract internal processing time: {unstract_elapsed:.2f} seconds")
                logger.info(f"Network + overhead time: {(total_upload_time - unstract_elapsed):.2f} seconds")
            
            # Extract execution_id from result metadata if available
            execution_id = None
            if result and len(result) > 0:
                execution_id = result[0].get('metadata', {}).get('execution_id')
            
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
                'message': 'Unstract extraction completed!',
                'progress': 100,
                'extraction_method': 'unstract',
                'unstract_data': result,
                'execution_id': execution_id,
                'execution_status': execution_status,
                'user_id': user_id
            }
            logger.info(f"Unstract processing completed immediately for task {task_id}")
            return
        
        # Get execution_id for polling
        execution_id = message.get('execution_id')
        
        if not execution_id:
            logger.error(f"No execution_id in response: {upload_response}")
            raise Exception(f"No execution_id returned from Unstract. Response: {upload_response}")
        
        logger.info(f"Got execution_id: {execution_id}")
        processing_status[task_id]['message'] = 'Processing with Unstract...'
        processing_status[task_id]['progress'] = 60
        
        # Poll for results
        max_attempts = 60  # 5 minutes with 5-second intervals
        for attempt in range(max_attempts):
            time.sleep(5)
            
            get_url = f'{api_url}?execution_id={execution_id}&include_metadata=false'
            logger.info(f"Polling Unstract (attempt {attempt + 1}/{max_attempts}): {get_url}")
            
            try:
                get_response = requests.get(get_url, headers=headers, timeout=30)
                logger.info(f"Poll response status: {get_response.status_code}")
                
                if get_response.status_code == 200:
                    result_data = get_response.json()
                    logger.info(f"Poll response data: {str(result_data)[:500]}")
                    
                    # Unstract API response structure has 'message' wrapper
                    message = result_data.get('message', result_data)
                    execution_status = message.get('execution_status', '')
                    result = message.get('result')
                    
                    logger.info(f"Execution status: {execution_status}")
                    
                    # Check if processing is complete
                    if execution_status == 'COMPLETED' and result:
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
                            'message': 'Unstract extraction completed!',
                            'progress': 100,
                            'extraction_method': 'unstract',
                            'unstract_data': result,  # The actual result array
                            'execution_id': execution_id,
                            'execution_status': execution_status,
                            'user_id': user_id
                        }
                        logger.info(f"Unstract processing completed for task {task_id}")
                        return
                    elif execution_status == 'ERROR':
                        error_detail = message.get('error', 'Unknown error')
                        logger.error(f"Unstract processing failed: {error_detail}")
                        raise Exception(f"Unstract processing failed: {error_detail}")
                    elif execution_status in ['PENDING', 'EXECUTING']:
                        logger.info(f"Still processing... Status: {execution_status}")
                    else:
                        logger.info(f"Unknown status: {execution_status}, continuing to poll...")
                else:
                    logger.warning(f"Poll returned status {get_response.status_code}: {get_response.text[:200]}")
                        
            except requests.exceptions.RequestException as e:
                logger.warning(f"Poll request failed (attempt {attempt + 1}): {str(e)}")
                
            processing_status[task_id]['progress'] = 60 + (attempt / max_attempts * 35)
        
        # Timeout
        raise Exception("Unstract processing timeout")
        
    except Exception as e:
        processing_status[task_id] = {
            'status': 'error',
            'message': f'Unstract processing failed: {str(e)}',
            'progress': 0,
            'user_id': user_id
        }
        logger.error(f"Unstract processing failed: {e}")

def process_pdf_with_textract(input_path, task_id, user_id, custom_query=''):
    """
    Process PDF using AWS Textract for document analysis with custom queries
    Supports: Text extraction, Tables, Forms, and Queries API
    """
    try:
        processing_status[task_id] = {
            'status': 'processing',
            'message': 'Uploading to AWS Textract...',
            'progress': 10,
            'user_id': user_id
        }
        
        # Check AWS credentials
        if not AWS_ACCESS_KEY_ID or not AWS_SECRET_ACCESS_KEY:
            raise Exception("AWS credentials not configured. Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables.")
        
        import boto3
        from botocore.exceptions import ClientError
        
        # Initialize Textract client
        textract_client = boto3.client(
            'textract',
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_DEFAULT_REGION
        )
        
        logger.info(f"Processing with AWS Textract: {input_path}")
        
        # Read the PDF file
        with open(input_path, 'rb') as document:
            document_bytes = document.read()
        
        processing_status[task_id]['message'] = 'Analyzing document with Textract...'
        processing_status[task_id]['progress'] = 30
        
        # Use Textract Queries feature if custom query is provided
        if custom_query:
            logger.info(f"Using Textract Queries API with query: {custom_query}")
            
            # Parse multiple queries (separated by newlines or semicolons)
            queries = [q.strip() for q in custom_query.replace(';', '\n').split('\n') if q.strip()]
            
            # Prepare queries for Textract
            query_config = {
                'Queries': [{'Text': q, 'Alias': f'Query_{i+1}'} for i, q in enumerate(queries)]
            }
            
            # Call Textract with Queries
            response = textract_client.analyze_document(
                Document={'Bytes': document_bytes},
                FeatureTypes=['TABLES', 'FORMS', 'QUERIES'],
                QueriesConfig=query_config
            )
        else:
            # Standard document analysis (text, tables, forms)
            logger.info("Using standard Textract analysis")
            response = textract_client.analyze_document(
                Document={'Bytes': document_bytes},
                FeatureTypes=['TABLES', 'FORMS']
            )
        
        processing_status[task_id]['message'] = 'Processing Textract results...'
        processing_status[task_id]['progress'] = 70
        
        # Extract text, tables, and query results
        extracted_data = parse_textract_response(response, custom_query)
        
        processing_status[task_id]['progress'] = 90
        
        # Save result to file
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_filename = f"textract_{timestamp}_{task_id[:8]}.txt"
        output_path = os.path.join(OUTPUT_FOLDER, output_filename)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(f"AWS Textract Extraction Results\n")
            f.write(f"File: {os.path.basename(input_path)}\n")
            f.write(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            if custom_query:
                f.write(f"Custom Queries: {custom_query}\n")
            f.write("=" * 80 + "\n\n")
            f.write(extracted_data)
        
        logger.info(f"Saved Textract results to: {output_path}")
        
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
            'message': 'AWS Textract extraction completed!',
            'progress': 100,
            'extraction_method': 'textract',
            'output_file': output_filename,
            'unstract_data': [{
                'file': os.path.basename(input_path),
                'status': 'Success',
                'result': {
                    'output': {
                        'Textract_Extraction': extracted_data
                    }
                }
            }],
            'user_id': user_id
        }
        logger.info(f"AWS Textract processing completed for task {task_id}")
        
    except ClientError as e:
        error_msg = f"AWS Textract API error: {e.response['Error']['Message']}"
        processing_status[task_id] = {
            'status': 'error',
            'message': error_msg,
            'progress': 0,
            'user_id': user_id
        }
        logger.error(error_msg)
    except Exception as e:
        processing_status[task_id] = {
            'status': 'error',
            'message': f'Textract processing failed: {str(e)}',
            'progress': 0,
            'user_id': user_id
        }
        logger.error(f"Textract processing failed: {e}")

def parse_textract_response(response, custom_query=''):
    """Parse AWS Textract response and format results"""
    result_text = ""
    
    # Extract query answers if queries were used
    if custom_query:
        result_text += "QUERY RESULTS:\n"
        result_text += "=" * 80 + "\n\n"
        
        for block in response['Blocks']:
            if block['BlockType'] == 'QUERY_RESULT':
                query_alias = block.get('Query', {}).get('Alias', 'Unknown')
                query_text = block.get('Query', {}).get('Text', '')
                answer = block.get('Text', 'No answer found')
                confidence = block.get('Confidence', 0)
                
                result_text += f"Q: {query_text}\n"
                result_text += f"A: {answer}\n"
                result_text += f"Confidence: {confidence:.1f}%\n\n"
        
        result_text += "\n" + "=" * 80 + "\n\n"
    
    # Extract full text
    result_text += "EXTRACTED TEXT:\n"
    result_text += "=" * 80 + "\n\n"
    
    lines = []
    for block in response['Blocks']:
        if block['BlockType'] == 'LINE':
            lines.append(block['Text'])
    
    result_text += '\n'.join(lines)
    result_text += "\n\n" + "=" * 80 + "\n\n"
    
    # Extract tables
    tables = extract_tables_from_textract(response)
    if tables:
        result_text += "EXTRACTED TABLES:\n"
        result_text += "=" * 80 + "\n\n"
        
        for i, table in enumerate(tables, 1):
            result_text += f"Table {i}:\n"
            result_text += table + "\n\n"
    
    # Extract key-value pairs (forms)
    key_values = extract_key_values_from_textract(response)
    if key_values:
        result_text += "FORM FIELDS:\n"
        result_text += "=" * 80 + "\n\n"
        
        for key, value in key_values.items():
            result_text += f"{key}: {value}\n"
    
    return result_text

def extract_tables_from_textract(response):
    """Extract tables from Textract response"""
    tables = []
    blocks = response['Blocks']
    block_map = {block['Id']: block for block in blocks}
    
    for block in blocks:
        if block['BlockType'] == 'TABLE':
            table = []
            if 'Relationships' in block:
                for relationship in block['Relationships']:
                    if relationship['Type'] == 'CHILD':
                        for cell_id in relationship['Ids']:
                            cell = block_map[cell_id]
                            if cell['BlockType'] == 'CELL':
                                row_index = cell['RowIndex'] - 1
                                col_index = cell['ColumnIndex'] - 1
                                
                                # Ensure table has enough rows
                                while len(table) <= row_index:
                                    table.append([])
                                
                                # Ensure row has enough columns
                                while len(table[row_index]) <= col_index:
                                    table[row_index].append('')
                                
                                # Get cell text
                                cell_text = ''
                                if 'Relationships' in cell:
                                    for cell_relationship in cell['Relationships']:
                                        if cell_relationship['Type'] == 'CHILD':
                                            for word_id in cell_relationship['Ids']:
                                                if word_id in block_map:
                                                    word = block_map[word_id]
                                                    if word['BlockType'] == 'WORD':
                                                        cell_text += word['Text'] + ' '
                                
                                table[row_index][col_index] = cell_text.strip()
            
            # Convert table to CSV format
            table_str = '\n'.join([','.join([f'"{cell}"' if ',' in cell else cell for cell in row]) for row in table])
            tables.append(table_str)
    
    return tables

def extract_key_values_from_textract(response):
    """Extract key-value pairs (forms) from Textract response"""
    key_values = {}
    blocks = response['Blocks']
    block_map = {block['Id']: block for block in blocks}
    
    for block in blocks:
        if block['BlockType'] == 'KEY_VALUE_SET' and 'KEY' in block.get('EntityTypes', []):
            key_text = ''
            value_text = ''
            
            # Get key text
            if 'Relationships' in block:
                for relationship in block['Relationships']:
                    if relationship['Type'] == 'CHILD':
                        for child_id in relationship['Ids']:
                            if child_id in block_map:
                                child = block_map[child_id]
                                if child['BlockType'] == 'WORD':
                                    key_text += child['Text'] + ' '
                    elif relationship['Type'] == 'VALUE':
                        for value_id in relationship['Ids']:
                            if value_id in block_map:
                                value_block = block_map[value_id]
                                if 'Relationships' in value_block:
                                    for value_relationship in value_block['Relationships']:
                                        if value_relationship['Type'] == 'CHILD':
                                            for value_child_id in value_relationship['Ids']:
                                                if value_child_id in block_map:
                                                    value_child = block_map[value_child_id]
                                                    if value_child['BlockType'] == 'WORD':
                                                        value_text += value_child['Text'] + ' '
            
            if key_text:
                key_values[key_text.strip()] = value_text.strip()
    
    return key_values

def create_searchable_pdf_from_textract(input_pdf_path, task_id, user_id):
    """
    Create a searchable PDF from scanned PDF using AWS Textract and PyMuPDF
    Uses insert_textbox for proper full-word highlighting
    Reference: https://aws.amazon.com/blogs/machine-learning/generating-searchable-pdfs-from-scanned-documents-automatically-with-amazon-textract/
    """
    try:
        processing_status[task_id] = {
            'status': 'processing',
            'message': 'Starting searchable PDF creation...',
            'progress': 5,
            'user_id': user_id
        }
        
        # Check AWS credentials
        if not AWS_ACCESS_KEY_ID or not AWS_SECRET_ACCESS_KEY:
            raise Exception("AWS credentials not configured.")
        
        import boto3
        from botocore.exceptions import ClientError
        
        logger.info(f"Creating searchable PDF from: {input_pdf_path}")
        
        # Initialize Textract client
        textract_client = boto3.client(
            'textract',
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_DEFAULT_REGION
        )
        
        # Check file size
        file_size = os.path.getsize(input_pdf_path)
        file_size_mb = file_size / (1024 * 1024)
        logger.info(f"PDF file size: {file_size_mb:.2f} MB")
        
        # AWS Textract synchronous limit is 5 MB
        if file_size_mb > 5:
            raise Exception(
                f"PDF file is too large ({file_size_mb:.2f} MB). "
                f"AWS Textract synchronous API supports files up to 5 MB. "
                f"Please use a smaller file or split the PDF into smaller parts."
            )
        
        processing_status[task_id]['message'] = 'Analyzing document with Textract...'
        processing_status[task_id]['progress'] = 10
        
        # Read the PDF file
        with open(input_pdf_path, 'rb') as document:
            document_bytes = document.read()
        
        logger.info(f"Calling Textract with {len(document_bytes)} bytes...")
        
        # Call Textract to detect text with geometry
        try:
            logger.info("Calling Textract detect_document_text...")
            response = textract_client.detect_document_text(
                Document={'Bytes': document_bytes}
            )
            textract_blocks = response.get('Blocks', [])
            logger.info(f"Textract succeeded. Blocks found: {len(textract_blocks)}")
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if 'UnsupportedDocument' in error_code or 'unsupported' in str(e).lower():
                raise Exception(
                    f"PDF format not supported by Textract. Common causes:\n"
                    f"- Encrypted/password-protected PDFs\n"
                    f"- PDFs with unusual encoding\n"
                    f"- Corrupted PDF files\n"
                    f"Solution: Re-save the PDF using Adobe Acrobat or a PDF converter"
                )
            raise
        
        # Count WORD blocks
        word_blocks = [b for b in textract_blocks if b['BlockType'] == 'WORD']
        logger.info(f"Found {len(word_blocks)} WORD blocks")
        
        processing_status[task_id]['message'] = 'Creating searchable PDF...'
        processing_status[task_id]['progress'] = 40
        
        # Open PDF with PyMuPDF
        pdf_doc = fitz.open(input_pdf_path)
        
        # Convert PDF pages to images and create new PDF with images
        pdf_image_dpi = 200
        pdf_doc_img = fitz.open()
        
        logger.info("Converting PDF pages to images...")
        for ppi, pdf_page in enumerate(pdf_doc.pages()):
            # Render page to image
            pdf_pix_map = pdf_page.get_pixmap(dpi=pdf_image_dpi, colorspace="RGB")
            # Create new page with same dimensions
            pdf_page_img = pdf_doc_img.new_page(
                width=pdf_page.rect.width, height=pdf_page.rect.height
            )
            # Insert image into page
            pdf_page_img.insert_image(rect=pdf_page.rect, pixmap=pdf_pix_map)
        
        pdf_doc.close()
        
        processing_status[task_id]['message'] = 'Adding searchable text layer...'
        processing_status[task_id]['progress'] = 60
        
        # Add invisible text to the image PDF
        fontsize_initial = 15
        print_step = 1000
        
        for blocki, block in enumerate(textract_blocks):
            if blocki % print_step == 0:
                logger.info(f"Processing blocks {blocki} to {blocki+print_step} out of {len(textract_blocks)}")
                progress = 60 + int((blocki / len(textract_blocks)) * 30)
                processing_status[task_id]['progress'] = progress
            
            if block["BlockType"] == "WORD":
                # Get page (Textract uses 1-based indexing)
                page_num = block.get('Page', 1) - 1  # Convert to 0-based
                pdf_page = pdf_doc_img[page_num]
                
                # Get bounding box from Textract (normalized 0-1 coordinates)
                textract_bbox = block['Geometry']['BoundingBox']
                
                # Convert to PDF coordinates
                # Textract: origin at top-left, coordinates normalized
                # PDF: origin at bottom-left, coordinates in points
                left = textract_bbox['Left'] * pdf_page.rect.width
                top = textract_bbox['Top'] * pdf_page.rect.height
                width = textract_bbox['Width'] * pdf_page.rect.width
                height = textract_bbox['Height'] * pdf_page.rect.height
                
                # Bottom and right edges
                bottom = top + height
                right = left + width
                
                # Get the text
                text = block.get("Text", "")
                if not text:
                    continue
                
                # Calculate optimal font size to fit text in bbox
                text_length = fitz.get_text_length(
                    text, fontname="helv", fontsize=fontsize_initial
                )
                fontsize_optimal = int(
                    math.floor((width / text_length) * fontsize_initial)
                )
                
                # Insert invisible text using textbox for proper full-word highlighting
                try:
                    pdf_page.insert_textbox(
                        fitz.Rect(left, top, right, bottom),
                        text,
                        fontname="helv",
                        fontsize=fontsize_optimal,
                        color=(0, 0, 0),
                        align=fitz.TEXT_ALIGN_LEFT,
                        render_mode=3,  # 3 = invisible
                    )
                except Exception as e:
                    logger.warning(f"Could not add word '{text}': {e}")
        
        processing_status[task_id]['message'] = 'Saving searchable PDF...'
        processing_status[task_id]['progress'] = 95
        
        # Save the searchable PDF
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_filename = f"searchable_{timestamp}_{task_id[:8]}.pdf"
        output_path = os.path.join(OUTPUT_FOLDER, output_filename)
        
        pdf_doc_img.save(output_path)
        pdf_doc_img.close()
        
        logger.info(f"Searchable PDF created successfully: {output_path}")
        
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
            'message': 'Searchable PDF created successfully!',
            'progress': 100,
            'extraction_method': 'searchable_pdf',
            'output_file': output_filename,
            'searchable_pdf': output_filename,
            'user_id': user_id
        }
        logger.info(f"Searchable PDF processing completed for task {task_id}")
        
    except ClientError as e:
        error_msg = f"AWS Textract API error: {e.response['Error']['Message']}"
        processing_status[task_id] = {
            'status': 'error',
            'message': error_msg,
            'progress': 0,
            'user_id': user_id
        }
        logger.error(error_msg)
    except Exception as e:
        processing_status[task_id] = {
            'status': 'error',
            'message': f'Searchable PDF creation failed: {str(e)}',
            'progress': 0,
            'user_id': user_id
        }
        logger.error(f"Searchable PDF creation failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
    try:
        processing_status[task_id] = {
            'status': 'processing',
            'message': 'Starting searchable PDF creation...',
            'progress': 5,
            'user_id': user_id
        }
        
        # Check AWS credentials
        if not AWS_ACCESS_KEY_ID or not AWS_SECRET_ACCESS_KEY:
            raise Exception("AWS credentials not configured.")
        
        import boto3
        from botocore.exceptions import ClientError
        from pdf2image import convert_from_path
        import io
        
        logger.info(f"Creating searchable PDF from: {input_pdf_path}")
        
        # Initialize Textract client
        textract_client = boto3.client(
            'textract',
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_DEFAULT_REGION
        )
        
        # Read original PDF to get page count
        pdf_reader = PdfReader(input_pdf_path)
        total_pages = len(pdf_reader.pages)
        
        # Check file size
        file_size = os.path.getsize(input_pdf_path)
        file_size_mb = file_size / (1024 * 1024)
        logger.info(f"PDF file size: {file_size_mb:.2f} MB, Pages: {total_pages}")
        
        # AWS Textract synchronous limit is 5 MB
        if file_size_mb > 5:
            raise Exception(
                f"PDF file is too large ({file_size_mb:.2f} MB). "
                f"AWS Textract synchronous API supports files up to 5 MB. "
                f"Please use a smaller file or split the PDF into smaller parts."
            )
        
        processing_status[task_id]['message'] = f'Analyzing {total_pages} pages with Textract...'
        processing_status[task_id]['progress'] = 10
        
        # Read the PDF file
        with open(input_pdf_path, 'rb') as document:
            document_bytes = document.read()
        
        logger.info(f"Calling Textract with {len(document_bytes)} bytes...")
        
        # Call Textract to detect text with geometry
        try:
            logger.info("Calling Textract detect_document_text...")
            response = textract_client.detect_document_text(
                Document={'Bytes': document_bytes}
            )
            logger.info(f"Textract succeeded. Blocks found: {len(response.get('Blocks', []))}")
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if 'UnsupportedDocument' in error_code or 'unsupported' in str(e).lower():
                raise Exception(
                    f"PDF format not supported by Textract. Common causes:\n"
                    f"- Encrypted/password-protected PDFs\n"
                    f"- PDFs with unusual encoding\n"
                    f"- Corrupted PDF files\n"
                    f"Solution: Re-save the PDF using Adobe Acrobat or a PDF converter"
                )
            raise
        
        processing_status[task_id]['message'] = 'Creating searchable PDF...'
        processing_status[task_id]['progress'] = 40
        
        # Parse Textract response to get text with coordinates
        blocks = response.get('Blocks', [])
        
        # Group words by page
        words_by_page = {}
        for block in blocks:
            if block['BlockType'] == 'WORD':
                page_num = block.get('Page', 1)
                if page_num not in words_by_page:
                    words_by_page[page_num] = []
                words_by_page[page_num].append(block)
        
        logger.info(f"Found text on {len(words_by_page)} pages")
        
        # Create searchable PDF using pikepdf
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_filename = f"searchable_{timestamp}_{task_id[:8]}.pdf"
        output_path = os.path.join(OUTPUT_FOLDER, output_filename)
        
        # Open original PDF
        pdf = pikepdf.open(input_pdf_path)
        
        # Process each page
        for page_idx in range(len(pdf.pages)):
            page_num = page_idx + 1  # Textract uses 1-based indexing
            page = pdf.pages[page_idx]
            
            # Get page dimensions
            mediabox = page.MediaBox
            page_width = float(mediabox[2] - mediabox[0])
            page_height = float(mediabox[3] - mediabox[1])
            
            # Get words for this page
            page_words = words_by_page.get(page_num, [])
            logger.info(f"Page {page_num}: {len(page_words)} words, size: {page_width}x{page_height} points")
            
            if not page_words:
                continue
            
            # Create invisible text overlay using reportlab
            packet = io.BytesIO()
            can = canvas.Canvas(packet, pagesize=(page_width, page_height))
            
            # Configure for invisible text
            can.setFillColorRGB(0, 0, 0, alpha=0)  # Transparent
            
            for word_block in page_words:
                text = word_block.get('Text', '')
                if not text:
                    continue
                
                # Get bounding box (normalized coordinates 0-1)
                geometry = word_block.get('Geometry', {})
                bbox = geometry.get('BoundingBox', {})
                
                # Convert normalized coordinates to PDF points
                left = bbox.get('Left', 0) * page_width
                top = bbox.get('Top', 0) * page_height
                width = bbox.get('Width', 0) * page_width
                height = bbox.get('Height', 0) * page_height
                
                # PDF coordinate system: origin at bottom-left
                # Textract: origin at top-left, so we need to flip Y
                x = left
                y = page_height - top - height
                
                # Estimate font size based on height
                # Use 85% of height as font size for better fit
                font_size = max(height * 0.85, 1)
                
                try:
                    # Set font (Helvetica is standard and widely supported)
                    can.setFont("Helvetica", font_size)
                    
                    # Create text object for invisible rendering
                    text_obj = can.beginText(x, y)
                    text_obj.setTextRenderMode(3)  # 3 = invisible (neither fill nor stroke)
                    text_obj.textLine(text)
                    can.drawText(text_obj)
                    
                except Exception as e:
                    logger.warning(f"Could not add word '{text}' at ({x},{y}): {e}")
            
            # Save the canvas
            can.save()
            packet.seek(0)
            
            # Merge the text layer with the original page
            try:
                overlay_pdf = pikepdf.open(packet)
                if len(overlay_pdf.pages) > 0:
                    # Add the overlay as a new content stream
                    page.add_overlay(overlay_pdf.pages[0])
                    logger.info(f"Page {page_num}: Text layer added successfully")
            except Exception as e:
                logger.error(f"Page {page_num}: Failed to add overlay: {e}")
            
            # Update progress
            progress = 40 + int((page_idx + 1) / len(pdf.pages) * 50)
            processing_status[task_id]['progress'] = progress
        
        # Save the searchable PDF
        pdf.save(output_path)
        pdf.close()
        
        logger.info(f"Searchable PDF created successfully: {output_path}")
        
        processing_status[task_id]['message'] = 'Finalizing...'
        processing_status[task_id]['progress'] = 95
        
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
            'message': 'Searchable PDF created successfully!',
            'progress': 100,
            'extraction_method': 'searchable_pdf',
            'output_file': output_filename,
            'searchable_pdf': output_filename,
            'user_id': user_id
        }
        logger.info(f"Searchable PDF processing completed for task {task_id}")
        
    except ClientError as e:
        error_msg = f"AWS Textract API error: {e.response['Error']['Message']}"
        processing_status[task_id] = {
            'status': 'error',
            'message': error_msg,
            'progress': 0,
            'user_id': user_id
        }
        logger.error(error_msg)
    except Exception as e:
        processing_status[task_id] = {
            'status': 'error',
            'message': f'Searchable PDF creation failed: {str(e)}',
            'progress': 0,
            'user_id': user_id
        }
        logger.error(f"Searchable PDF creation failed: {e}")
        import traceback
        logger.error(traceback.format_exc())


def process_pdf_with_direct_llm(input_path, task_id, user_id, custom_prompt='', model='gpt-4o', use_text_extraction=True):
    """
    DEPRECATED: This function is replaced by process_pdf_with_textract
    Redirects to Textract for better accuracy and cost
    """
    logger.warning("Direct LLM processing is deprecated. Using AWS Textract instead.")
    return process_pdf_with_textract(input_path, task_id, user_id, custom_prompt)
    """
    Process PDF using direct LLM API calls (OpenAI GPT-4o or Anthropic Claude)
    This bypasses Unstract and allows true custom prompts
    
    Args:
        use_text_extraction: If True, first extract text with LLMWhisperer then send to LLM (faster, cheaper)
                            If False, convert PDF to images and use vision API (slower, more expensive)
    """
    try:
        processing_status[task_id] = {
            'status': 'processing',
            'message': 'Starting extraction...',
            'progress': 10,
            'user_id': user_id
        }
        
        extracted_text = None
        
        # Option 1: Use LLMWhisperer to extract text first (recommended)
        if use_text_extraction:
            try:
                processing_status[task_id]['message'] = 'Extracting text with LLMWhisperer...'
                processing_status[task_id]['progress'] = 20
                
                logger.info(f"Extracting text with LLMWhisperer for Direct LLM: {input_path}")
                
                # Read file as binary
                with open(input_path, 'rb') as f:
                    file_bytes = f.read()
                
                # Submit to LLMWhisperer
                headers = {
                    'unstract-key': LLMWHISPERER_API_KEY,
                    'Content-Type': 'application/octet-stream'
                }
                
                params = {
                    'mode': 'high_quality',
                    'output_mode': 'layout_preserving',
                    'page_seperator': '<<<PAGE_BREAK>>>',
                }
                
                response = requests.post(
                    f'{LLMWHISPERER_API_URL}/whisper',
                    headers=headers,
                    params=params,
                    data=file_bytes,
                    timeout=300
                )
                
                if response.status_code == 202:
                    result_data = response.json()
                    whisper_hash = result_data.get('whisper_hash')
                    
                    # Poll for completion
                    processing_status[task_id]['message'] = 'Processing document...'
                    processing_status[task_id]['progress'] = 40
                    
                    max_retries = 60
                    retry_count = 0
                    
                    while retry_count < max_retries:
                        time.sleep(5)
                        status_response = requests.get(
                            f'{LLMWHISPERER_API_URL}/whisper-status',
                            headers=headers,
                            params={'whisper_hash': whisper_hash},
                            timeout=30
                        )
                        
                        if status_response.status_code == 200:
                            status_data = status_response.json()
                            status = status_data.get('status')
                            
                            if status == 'processed':
                                # Retrieve text
                                retrieve_response = requests.get(
                                    f'{LLMWHISPERER_API_URL}/whisper-retrieve',
                                    headers=headers,
                                    params={'whisper_hash': whisper_hash, 'text_only': 'false'},
                                    timeout=60
                                )
                                
                                if retrieve_response.status_code == 200:
                                    result_data = retrieve_response.json()
                                    extracted_text = result_data.get('result_text', '')
                                    logger.info(f"LLMWhisperer extracted {len(extracted_text)} characters")
                                break
                            elif status in ['error', 'failed']:
                                logger.warning(f"LLMWhisperer failed, falling back to vision API")
                                break
                        
                        retry_count += 1
                    
            except Exception as e:
                logger.warning(f"LLMWhisperer extraction failed: {e}, falling back to vision API")
                extracted_text = None
        
        # Option 2: Fall back to vision API if text extraction failed or disabled
        if extracted_text:
            processing_status[task_id]['message'] = 'Analyzing extracted text with AI...'
            processing_status[task_id]['progress'] = 60
            
            # Prepare the prompt for text-based analysis
            if not custom_prompt:
                custom_prompt = """
First, analyze the text to determine the most appropriate headers for the tables.
Generate a descriptive h1 for the overall document, followed by a brief summary of the data it contains.
For each identified table, create an informative h2 title and a concise description of its contents.
Finally, output the markdown representation of each table.
Make sure to escape the markdown table properly, and make sure to include the caption and the dataframe.
including escaping all the newlines and quotes. Only return a markdown table in dataframe, nothing else.
"""
            
            # Process text with LLM
            if model.startswith('gpt-'):
                result = process_text_with_openai(extracted_text, custom_prompt, model)
            elif model.startswith('claude-'):
                result = process_text_with_anthropic(extracted_text, custom_prompt, model)
            else:
                raise Exception(f"Unsupported model: {model}")
                
        else:
            # Fall back to image-based processing
            processing_status[task_id]['message'] = 'Converting PDF to images...'
            processing_status[task_id]['progress'] = 30
            
            import base64
            import pdf2image
            from PIL import Image
            import io
            
            logger.info(f"Converting PDF to images: {input_path}")
            images = pdf2image.convert_from_path(input_path, dpi=200)
            
            processing_status[task_id]['message'] = 'Analyzing images with AI...'
            processing_status[task_id]['progress'] = 60
            
            if not custom_prompt:
                custom_prompt = """
First, analyze the image to determine the most appropriate headers for the tables.
Generate a descriptive h1 for the overall image, followed by a brief summary of the data it contains.
For each identified table, create an informative h2 title and a concise description of its contents.
Finally, output the markdown representation of each table.
Make sure to escape the markdown table properly, and make sure to include the caption and the dataframe.
including escaping all the newlines and quotes. Only return a markdown table in dataframe, nothing else.
"""
            
            if model.startswith('gpt-'):
                result = process_with_openai(images, custom_prompt, model)
            elif model.startswith('claude-'):
                result = process_with_anthropic(images, custom_prompt, model)
            else:
                raise Exception(f"Unsupported model: {model}")
        
        processing_status[task_id]['message'] = 'Extraction complete!'
        processing_status[task_id]['progress'] = 90
        
        # Save result to file (for download compatibility)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_filename = f"llm_extracted_{timestamp}_{task_id[:8]}.txt"
        output_path = os.path.join(OUTPUT_FOLDER, output_filename)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(f"Direct LLM Extraction Results\n")
            f.write(f"Model: {model}\n")
            f.write(f"File: {os.path.basename(input_path)}\n")
            f.write(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 80 + "\n\n")
            f.write(result)
        
        logger.info(f"Saved LLM results to: {output_path}")
        
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
            'message': 'Direct LLM extraction completed!',
            'progress': 100,
            'extraction_method': 'direct_llm',
            'output_file': output_filename,  # Added for download compatibility
            'llm_data': [{
                'file': os.path.basename(input_path),
                'status': 'Success',
                'result': {
                    'output': {
                        'extracted_data': result
                    }
                }
            }],
            # Also add unstract_data for frontend compatibility
            'unstract_data': [{
                'file': os.path.basename(input_path),
                'status': 'Success',
                'result': {
                    'output': {
                        'Direct_LLM_Output': result
                    }
                }
            }],
            'user_id': user_id
        }
        logger.info(f"Direct LLM processing completed for task {task_id}")
        
    except Exception as e:
        processing_status[task_id] = {
            'status': 'error',
            'message': f'Direct LLM processing failed: {str(e)}',
            'progress': 0,
            'user_id': user_id
        }
        logger.error(f"Direct LLM processing failed: {e}")

def process_with_openai(images, prompt, model='gpt-4o'):
    """Process images with OpenAI GPT-4o Vision API"""
    if not OPENAI_API_KEY:
        raise Exception("OpenAI API key not configured. Set OPENAI_API_KEY environment variable.")
    
    import base64
    import io
    
    # Prepare image data
    image_data = []
    for idx, img in enumerate(images):
        # Convert PIL Image to base64
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()
        
        image_data.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{img_str}",
                "detail": "high"  # High detail for better table extraction
            }
        })
    
    # Call OpenAI API
    headers = {
        'Authorization': f'Bearer {OPENAI_API_KEY}',
        'Content-Type': 'application/json'
    }
    
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are an expert at extracting data from technical documents, specifications, and invoices. Extract data accurately and format it as requested."
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    *image_data
                ]
            }
        ],
        "max_tokens": 4096,
        "temperature": 0.1  # Low temperature for consistent extraction
    }
    
    response = requests.post(
        'https://api.openai.com/v1/chat/completions',
        headers=headers,
        json=payload,
        timeout=120
    )
    
    if response.status_code != 200:
        raise Exception(f"OpenAI API error: {response.status_code} - {response.text}")
    
    result = response.json()
    extracted_text = result['choices'][0]['message']['content']
    
    logger.info(f"OpenAI extraction complete. Tokens used: {result.get('usage', {})}")
    
    return extracted_text

def process_with_anthropic(images, prompt, model='claude-3-5-sonnet-20241022'):
    """Process images with Anthropic Claude 3.5 Sonnet API"""
    if not ANTHROPIC_API_KEY:
        raise Exception("Anthropic API key not configured. Set ANTHROPIC_API_KEY environment variable.")
    
    import base64
    import io
    
    # Prepare image data for Claude
    image_data = []
    for idx, img in enumerate(images):
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        img_bytes = buffered.getvalue()
        img_b64 = base64.b64encode(img_bytes).decode()
        
        image_data.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": img_b64
            }
        })
    
    headers = {
        'x-api-key': ANTHROPIC_API_KEY,
        'anthropic-version': '2023-06-01',
        'content-type': 'application/json'
    }
    
    payload = {
        "model": model,
        "max_tokens": 4096,
        "temperature": 0.1,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    *image_data
                ]
            }
        ]
    }
    
    response = requests.post(
        'https://api.anthropic.com/v1/messages',
        headers=headers,
        json=payload,
        timeout=120
    )
    
    if response.status_code != 200:
        raise Exception(f"Anthropic API error: {response.status_code} - {response.text}")
    
    result = response.json()
    extracted_text = result['content'][0]['text']
    
    logger.info(f"Anthropic extraction complete. Tokens used: {result.get('usage', {})}")
    
    return extracted_text

def process_text_with_openai(text, prompt, model='gpt-4o'):
    """Process extracted text with OpenAI API (no vision, text-only - much cheaper and faster)"""
    if not OPENAI_API_KEY:
        raise Exception("OpenAI API key not configured. Set OPENAI_API_KEY environment variable.")
    
    headers = {
        'Authorization': f'Bearer {OPENAI_API_KEY}',
        'Content-Type': 'application/json'
    }
    
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are an expert at analyzing and extracting data from technical documents, specifications, and invoices. Extract data accurately and format it as requested."
            },
            {
                "role": "user",
                "content": f"{prompt}\n\nDocument text:\n\n{text}"
            }
        ],
        "max_tokens": 4096,
        "temperature": 0.1
    }
    
    response = requests.post(
        'https://api.openai.com/v1/chat/completions',
        headers=headers,
        json=payload,
        timeout=120
    )
    
    if response.status_code != 200:
        raise Exception(f"OpenAI API error: {response.status_code} - {response.text}")
    
    result = response.json()
    extracted_data = result['choices'][0]['message']['content']
    
    logger.info(f"OpenAI text processing complete. Tokens used: {result.get('usage', {})}")
    
    return extracted_data

def process_text_with_anthropic(text, prompt, model='claude-3-5-sonnet-20241022'):
    """Process extracted text with Anthropic Claude API (text-only)"""
    if not ANTHROPIC_API_KEY:
        raise Exception("Anthropic API key not configured. Set ANTHROPIC_API_KEY environment variable.")
    
    headers = {
        'x-api-key': ANTHROPIC_API_KEY,
        'anthropic-version': '2023-06-01',
        'Content-Type': 'application/json'
    }
    
    payload = {
        "model": model,
        "max_tokens": 4096,
        "temperature": 0.1,
        "system": "You are an expert at analyzing and extracting data from technical documents, specifications, and invoices. Extract data accurately and format it as requested.",
        "messages": [
            {
                "role": "user",
                "content": f"{prompt}\n\nDocument text:\n\n{text}"
            }
        ]
    }
    
    response = requests.post(
        'https://api.anthropic.com/v1/messages',
        headers=headers,
        json=payload,
        timeout=120
    )
    
    if response.status_code != 200:
        raise Exception(f"Anthropic API error: {response.status_code} - {response.text}")
    
    result = response.json()
    extracted_data = result['content'][0]['text']
    
    logger.info(f"Anthropic text processing complete. Tokens used: {result.get('usage', {})}")
    
    return extracted_data

def process_pdf_with_llmwhisperer(input_path, task_id, user_id):
    """
    Process PDF using Unstract's LLMWhisperer API
    This extracts text from documents maintaining layout structure
    """
    try:
        processing_status[task_id] = {
            'status': 'processing',
            'message': 'Uploading to LLMWhisperer...',
            'progress': 10,
            'user_id': user_id
        }
        
        # Step 1: Submit document to LLMWhisperer
        logger.info(f"Submitting document to LLMWhisperer: {input_path}")
        
        # Verify it's actually a PDF file
        if not input_path.lower().endswith('.pdf'):
            raise Exception(f"File is not a PDF: {input_path}")
        
        # Read file as binary data
        with open(input_path, 'rb') as f:
            file_bytes = f.read()
        
        # Verify we have content
        logger.info(f"File size: {len(file_bytes)} bytes")
        
        # Prepare headers - use application/octet-stream as per docs
        headers = {
            'unstract-key': LLMWHISPERER_API_KEY,
            'Content-Type': 'application/octet-stream'
        }
        
        # Parameters as query string (not form data)
        # Use high_quality mode for OCR (native_text only extracts embedded text)
        params = {
            'mode': 'high_quality',  # OCR mode for scanned documents
            'output_mode': 'layout_preserving',
            'page_seperator': '<<<PAGE_BREAK>>>',
        }
        
        logger.info(f"Uploading to {LLMWHISPERER_API_URL}/whisper (mode: high_quality OCR)")
        
        try:
            # Send file as raw binary data (not multipart)
            response = requests.post(
                f'{LLMWHISPERER_API_URL}/whisper',
                headers=headers,
                params=params,
                data=file_bytes,  # Send raw bytes, not files dict
                timeout=300
            )
            
            logger.info(f"LLMWhisperer response status: {response.status_code}")
            logger.info(f"LLMWhisperer response: {response.text}")
            
        except Exception as req_error:
            logger.error(f"Request error: {req_error}")
            raise
        
        if response.status_code != 202:
            raise Exception(f"LLMWhisperer submission failed: {response.status_code} - {response.text}")
        
        whisper_data = response.json()
        whisper_hash = whisper_data.get('whisper_hash')
        
        logger.info(f"LLMWhisperer processing started. Whisper hash: {whisper_hash}")
        
        processing_status[task_id]['message'] = 'Processing document...'
        processing_status[task_id]['progress'] = 30
        
        # Step 2: Poll for status
        max_retries = 60  # 5 minutes max (5 second intervals)
        retry_count = 0
        
        while retry_count < max_retries:
            time.sleep(5)
            
            status_response = requests.get(
                f'{LLMWHISPERER_API_URL}/whisper-status',
                headers=headers,
                params={'whisper_hash': whisper_hash},
                timeout=30
            )
            
            if status_response.status_code != 200:
                raise Exception(f"Status check failed: {status_response.status_code}")
            
            status_data = status_response.json()
            status = status_data.get('status')
            
            logger.info(f"LLMWhisperer status: {status}")
            logger.info(f"LLMWhisperer status data: {status_data}")
            
            if status == 'processed':
                break
            elif status == 'processing':
                retry_count += 1
                processing_status[task_id]['progress'] = min(30 + retry_count, 80)
                continue
            elif status == 'failed' or status == 'error':
                error_msg = status_data.get('message', status_data.get('error', 'Unknown error'))
                logger.error(f"LLMWhisperer error: {error_msg}")
                logger.error(f"Full status response: {status_data}")
                raise Exception(f"LLMWhisperer processing failed: {error_msg}")
            else:
                retry_count += 1
                continue
        
        if retry_count >= max_retries:
            raise Exception("LLMWhisperer processing timeout")
        
        processing_status[task_id]['message'] = 'Retrieving extracted text...'
        processing_status[task_id]['progress'] = 85
        
        # Step 3: Retrieve extracted text
        retrieve_response = requests.get(
            f'{LLMWHISPERER_API_URL}/whisper-retrieve',
            headers=headers,
            params={
                'whisper_hash': whisper_hash,
                'text_only': 'false'  # Get metadata too
            },
            timeout=60
        )
        
        if retrieve_response.status_code != 200:
            raise Exception(f"Text retrieval failed: {retrieve_response.status_code}")
        
        result_data = retrieve_response.json()
        extracted_text = result_data.get('result_text', '')
        
        logger.info(f"LLMWhisperer extraction complete. Text length: {len(extracted_text)}")
        
        # Save result to file
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_filename = f"llmwhisperer_{timestamp}_{task_id[:8]}.txt"
        output_path = os.path.join(OUTPUT_FOLDER, output_filename)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(f"LLMWhisperer Extraction Results\n")
            f.write(f"File: {os.path.basename(input_path)}\n")
            f.write(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Whisper Hash: {whisper_hash}\n")
            f.write("=" * 80 + "\n\n")
            f.write(extracted_text)
        
        logger.info(f"Saved LLMWhisperer results to: {output_path}")
        
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
            'message': 'LLMWhisperer extraction completed!',
            'progress': 100,
            'extraction_method': 'llmwhisperer',
            'output_file': output_filename,
            'unstract_data': [{
                'file': os.path.basename(input_path),
                'status': 'Success',
                'result': {
                    'output': {
                        'Extracted_Text': extracted_text
                    }
                }
            }],
            'user_id': user_id
        }
        logger.info(f"LLMWhisperer processing completed for task {task_id}")
        
    except Exception as e:
        processing_status[task_id] = {
            'status': 'error',
            'message': f'LLMWhisperer processing failed: {str(e)}',
            'progress': 0,
            'user_id': user_id
        }
        logger.error(f"LLMWhisperer processing failed: {e}")

def process_pdf_with_gpt4o_hybrid(input_path, task_id, user_id, custom_query):
    """
    Process PDF using GPT-4o multimodal approach:
    1. Extract text using LLMWhisperer (for clean text content)
    2. Send both PDF images and extracted text to GPT-4o
    3. Use custom query to analyze both visual and textual information
    """
    try:
        processing_status[task_id] = {
            'status': 'processing',
            'message': 'Starting GPT-4o hybrid extraction...',
            'progress': 5,
            'user_id': user_id
        }
        
        # Initialize OpenAI client
        if not OPENAI_API_KEY:
            raise Exception("OpenAI API key not configured")
        
        client = OpenAI(api_key=OPENAI_API_KEY)
        
        # Step 1: Extract text using LLMWhisperer
        logger.info(f"Step 1/3: Extracting text with LLMWhisperer for {input_path}")
        processing_status[task_id]['message'] = 'Extracting text with LLMWhisperer...'
        processing_status[task_id]['progress'] = 10
        
        # Read file as binary data
        with open(input_path, 'rb') as f:
            file_bytes = f.read()
        
        # Prepare headers for LLMWhisperer
        headers = {
            'unstract-key': LLMWHISPERER_API_KEY,
            'Content-Type': 'application/octet-stream'
        }
        
        params = {
            'mode': 'high_quality',
            'output_mode': 'layout_preserving',
            'page_seperator': '<<<PAGE_BREAK>>>',
        }
        
        # Submit to LLMWhisperer
        response = requests.post(
            f'{LLMWHISPERER_API_URL}/whisper',
            headers=headers,
            params=params,
            data=file_bytes,
            timeout=300
        )
        
        if response.status_code != 202:
            raise Exception(f"LLMWhisperer submission failed: {response.status_code} - {response.text}")
        
        whisper_data = response.json()
        whisper_hash = whisper_data.get('whisper_hash')
        logger.info(f"LLMWhisperer processing started. Hash: {whisper_hash}")
        
        processing_status[task_id]['progress'] = 20
        
        # Poll for LLMWhisperer completion
        max_retries = 60
        retry_count = 0
        extracted_text = ""
        
        while retry_count < max_retries:
            time.sleep(5)
            
            status_response = requests.get(
                f'{LLMWHISPERER_API_URL}/whisper-status',
                headers=headers,
                params={'whisper_hash': whisper_hash},
                timeout=30
            )
            
            if status_response.status_code == 200:
                status_data = status_response.json()
                status = status_data.get('status')
                
                if status == 'processed':
                    # Retrieve text
                    retrieve_response = requests.get(
                        f'{LLMWHISPERER_API_URL}/whisper-retrieve',
                        headers=headers,
                        params={'whisper_hash': whisper_hash, 'text_only': 'false'},
                        timeout=60
                    )
                    
                    if retrieve_response.status_code == 200:
                        result_data = retrieve_response.json()
                        extracted_text = result_data.get('result_text', '')
                        logger.info(f"LLMWhisperer extraction complete. Text length: {len(extracted_text)}")
                        break
                elif status in ['failed', 'error']:
                    raise Exception(f"LLMWhisperer processing failed: {status_data.get('message', 'Unknown error')}")
            
            retry_count += 1
            processing_status[task_id]['progress'] = min(20 + retry_count, 50)
        
        if not extracted_text:
            raise Exception("Failed to extract text from LLMWhisperer")
        
        # Step 2: Convert PDF pages to base64 images
        logger.info(f"Step 2/3: Converting PDF to images")
        processing_status[task_id]['message'] = 'Converting PDF pages to images...'
        processing_status[task_id]['progress'] = 55
        
        import fitz  # PyMuPDF
        
        pdf_doc = fitz.open(input_path)
        page_images = []
        
        # Limit to first 10 pages to avoid token limits
        max_pages = min(len(pdf_doc), 10)
        
        for page_num in range(max_pages):
            page = pdf_doc[page_num]
            # Render at moderate resolution for GPT-4o (300 DPI)
            pix = page.get_pixmap(dpi=150)
            img_bytes = pix.tobytes("png")
            base64_image = base64.b64encode(img_bytes).decode('utf-8')
            page_images.append(base64_image)
            
            processing_status[task_id]['progress'] = 55 + int((page_num + 1) / max_pages * 20)
        
        pdf_doc.close()
        logger.info(f"Converted {len(page_images)} pages to images")
        
        # Step 3: Send to GPT-4o with multimodal prompt
        logger.info(f"Step 3/3: Querying GPT-4o with custom query")
        processing_status[task_id]['message'] = 'Analyzing with GPT-4o...'
        processing_status[task_id]['progress'] = 80
        
        # Build multimodal messages
        messages = [
            {
                "role": "system",
                "content": """You are an expert document analysis assistant with access to both visual and textual information from a PDF document.

You have:
1. Visual representation (images) of the PDF pages
2. Extracted text content from the document

Use both sources to provide the most accurate and comprehensive answer to the user's query. Consider:
- Visual layout, formatting, tables, charts, diagrams
- Text content for semantic understanding
- Spatial relationships between elements
- Any visual cues that text alone might miss"""
            }
        ]
        
        # Add PDF page images
        content_parts = []
        for i, img_base64 in enumerate(page_images):
            content_parts.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{img_base64}",
                    "detail": "high"
                }
            })
        
        # Add extracted text
        content_parts.append({
            "type": "text",
            "text": f"""**Extracted Text Content:**
```
{extracted_text[:10000]}  # Limit text to avoid token overflow
```

**User Query:**
{custom_query}

Please analyze both the visual PDF pages and the extracted text to answer the query comprehensively."""
        })
        
        messages.append({
            "role": "user",
            "content": content_parts
        })
        
        # Call GPT-4o Vision API
        logger.info("Calling GPT-4o Vision API...")
        completion = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            max_tokens=2000,
            temperature=0.3
        )
        
        gpt4o_response = completion.choices[0].message.content
        logger.info(f"GPT-4o response received: {len(gpt4o_response)} characters")
        
        # Save results
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_filename = f"gpt4o_hybrid_{timestamp}_{task_id[:8]}.txt"
        output_path = os.path.join(OUTPUT_FOLDER, output_filename)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(f"GPT-4o Hybrid Extraction Results\n")
            f.write(f"File: {os.path.basename(input_path)}\n")
            f.write(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Custom Query: {custom_query}\n")
            f.write("=" * 80 + "\n\n")
            f.write("GPT-4o Analysis:\n")
            f.write(gpt4o_response)
            f.write("\n\n" + "=" * 80 + "\n\n")
            f.write("LLMWhisperer Extracted Text:\n")
            f.write(extracted_text)
        
        logger.info(f"Saved GPT-4o results to: {output_path}")
        
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
            'message': 'GPT-4o hybrid extraction completed!',
            'progress': 100,
            'extraction_method': 'gpt4o_hybrid',
            'output_file': output_filename,
            'gpt4o_response': gpt4o_response,
            'llmwhisperer_text': extracted_text[:1000] + "..." if len(extracted_text) > 1000 else extracted_text,
            'pages_processed': len(page_images),
            'user_id': user_id
        }
        logger.info(f"GPT-4o hybrid processing completed for task {task_id}")
        
    except Exception as e:
        processing_status[task_id] = {
            'status': 'error',
            'message': f'GPT-4o hybrid processing failed: {str(e)}',
            'progress': 0,
            'user_id': user_id
        }
        logger.error(f"GPT-4o hybrid processing failed: {e}")

def process_pdf_with_gpt4o_vision(input_path, task_id, user_id, custom_query):
    """
    Process PDF using GPT-4o Vision API only (faster - no LLMWhisperer)
    Converts PDF to images and sends to GPT-4o with custom query
    """
    try:
        processing_status[task_id] = {
            'status': 'processing',
            'message': 'Starting GPT-4o Vision extraction...',
            'progress': 10,
            'user_id': user_id
        }
        
        # Initialize OpenAI client
        if not OPENAI_API_KEY:
            raise Exception("OpenAI API key not configured")
        
        client = OpenAI(api_key=OPENAI_API_KEY)
        
        # Convert PDF pages to base64 images
        logger.info(f"Converting PDF to images: {input_path}")
        processing_status[task_id]['message'] = 'Converting PDF pages to images...'
        processing_status[task_id]['progress'] = 20
        
        import fitz  # PyMuPDF
        
        pdf_doc = fitz.open(input_path)
        page_images = []
        
        # Limit to first 10 pages to avoid token limits
        max_pages = min(len(pdf_doc), 10)
        
        for page_num in range(max_pages):
            page = pdf_doc[page_num]
            # Render at moderate resolution for GPT-4o (150 DPI)
            pix = page.get_pixmap(dpi=150)
            img_bytes = pix.tobytes("png")
            base64_image = base64.b64encode(img_bytes).decode('utf-8')
            page_images.append(base64_image)
            
            processing_status[task_id]['progress'] = 20 + int((page_num + 1) / max_pages * 30)
        
        pdf_doc.close()
        logger.info(f"Converted {len(page_images)} pages to images")
        
        # Send to GPT-4o Vision API
        logger.info(f"Querying GPT-4o Vision with custom query")
        processing_status[task_id]['message'] = 'Analyzing with GPT-4o Vision...'
        processing_status[task_id]['progress'] = 60
        
        # Build multimodal messages
        messages = [
            {
                "role": "system",
                "content": """You are an expert document analysis assistant with advanced vision capabilities.

Analyze the provided PDF document images carefully and answer the user's query with precision.

Consider:
- Visual layout, formatting, tables, charts, diagrams
- Text content and its organization
- Spatial relationships between elements
- Any visual patterns or structures
- Headers, footers, page numbers, and document structure

Provide detailed, accurate, and well-structured responses."""
            }
        ]
        
        # Add PDF page images
        content_parts = []
        for i, img_base64 in enumerate(page_images):
            content_parts.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{img_base64}",
                    "detail": "high"
                }
            })
        
        # Add user query
        content_parts.append({
            "type": "text",
            "text": f"""**User Query:**
{custom_query}

Please analyze the document images above and provide a comprehensive answer to this query."""
        })
        
        messages.append({
            "role": "user",
            "content": content_parts
        })
        
        # Call GPT-4o Vision API
        logger.info("Calling GPT-4o Vision API...")
        processing_status[task_id]['progress'] = 70
        
        completion = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            max_tokens=2000,
            temperature=0.3
        )
        
        gpt4o_response = completion.choices[0].message.content
        logger.info(f"GPT-4o Vision response received: {len(gpt4o_response)} characters")
        
        processing_status[task_id]['progress'] = 90
        
        # Save results
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_filename = f"gpt4o_vision_{timestamp}_{task_id[:8]}.txt"
        output_path = os.path.join(OUTPUT_FOLDER, output_filename)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(f"GPT-4o Vision Extraction Results\n")
            f.write(f"File: {os.path.basename(input_path)}\n")
            f.write(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Pages Processed: {len(page_images)}\n")
            f.write(f"Custom Query: {custom_query}\n")
            f.write("=" * 80 + "\n\n")
            f.write("GPT-4o Vision Analysis:\n")
            f.write(gpt4o_response)
        
        logger.info(f"Saved GPT-4o Vision results to: {output_path}")
        
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
            'message': 'GPT-4o Vision extraction completed!',
            'progress': 100,
            'extraction_method': 'gpt4o_vision',
            'output_file': output_filename,
            'gpt4o_response': gpt4o_response,
            'pages_processed': len(page_images),
            'user_id': user_id
        }
        logger.info(f"GPT-4o Vision processing completed for task {task_id}")
        
    except Exception as e:
        processing_status[task_id] = {
            'status': 'error',
            'message': f'GPT-4o Vision processing failed: {str(e)}',
            'progress': 0,
            'user_id': user_id
        }
        logger.error(f"GPT-4o Vision processing failed: {e}")

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

@app.route('/api/upload_gpt4o_vision', methods=['POST'])
@jwt_required()
def upload_file_gpt4o_vision():
    """Upload PDF for GPT-4o Vision extraction (fast - PDF images only, no LLMWhisperer)"""
    print("=== GPT-4O VISION UPLOAD ENDPOINT CALLED ===")
    
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
    custom_query = request.form.get('custom_prompts', '')
    if not custom_query or custom_query.strip() == '':
        return jsonify({'error': 'Custom query is required for GPT-4o Vision extraction'}), 400
    
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
        'message': 'File uploaded, queued for GPT-4o Vision extraction',
        'progress': 0,
        'user_id': user_id
    }

    thread = threading.Thread(
        target=process_pdf_with_gpt4o_vision,
        args=(input_path, task_id, user_id, custom_query)
    )
    thread.start()
    
    print(f"GPT-4o Vision processing started for task_id: {task_id}")
    return jsonify({
        'task_id': task_id,
        'message': 'File uploaded successfully, processing with GPT-4o Vision',
        'filename': filename
    })

@app.route('/api/upload_gpt4o_hybrid', methods=['POST'])
@jwt_required()
def upload_file_gpt4o_hybrid():
    """Upload PDF for GPT-4o hybrid extraction (combines LLMWhisperer text + GPT-4o vision)"""
    print("=== GPT-4O HYBRID UPLOAD ENDPOINT CALLED ===")
    
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
    custom_query = request.form.get('custom_prompts', '')
    if not custom_query or custom_query.strip() == '':
        return jsonify({'error': 'Custom query is required for GPT-4o hybrid extraction'}), 400
    
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
        'message': 'File uploaded, queued for GPT-4o hybrid extraction',
        'progress': 0,
        'user_id': user_id
    }

    thread = threading.Thread(
        target=process_pdf_with_gpt4o_hybrid,
        args=(input_path, task_id, user_id, custom_query)
    )
    thread.start()
    
    print(f"GPT-4o hybrid processing started for task_id: {task_id}")
    return jsonify({
        'task_id': task_id,
        'message': 'File uploaded successfully, processing with GPT-4o hybrid approach',
        'filename': filename
    })

@app.route('/api/upload_unstract', methods=['POST'])
@jwt_required()
def upload_file_unstract():
    """Upload file for Unstract processing with custom prompts"""
    print("=== UNSTRACT UPLOAD ENDPOINT CALLED ===")
    
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
    
    # Get custom prompts from request
    custom_prompts = request.form.get('custom_prompts', '')
    print(f"Custom prompts received: {custom_prompts}")
    
    # Get model selection from request
    model_name = request.form.get('model_name', 'gpt-4-turbo')  # Default to GPT-4 Turbo
    print(f"Model selected: {model_name}")
    
    # Get API key from request or use default
    api_key = request.form.get('api_key', UNSTRACT_DEFAULT_API_KEY)
    
    task_id = str(uuid.uuid4())
    filename = secure_filename(file.filename)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    input_filename = f"{timestamp}_{filename}"
    input_path = os.path.join(UPLOAD_FOLDER, input_filename)
    file.save(input_path)

    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO processing_jobs (id, user_id, filename, status) VALUES (?, ?, ?, ?)',
        (task_id, user_id, filename, 'processing')
    )
    conn.commit()
    conn.close()
    
    thread = threading.Thread(
        target=process_pdf_with_unstract,
        args=(input_path, task_id, user_id, api_key, custom_prompts, model_name)
    )
    thread.start()
    
    print(f"Unstract processing started for task_id: {task_id}")
    return jsonify({
        'task_id': task_id,
        'message': 'File uploaded successfully, Unstract processing started',
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
    
    output_file = status['output_file']
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
        output_file = status['output_file']
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

@app.route('/api/launch_abaqus', methods=['POST'])
@jwt_required()
def launch_abaqus():
    """Launch ABAQUS CLI with the extracted CSV data"""
    print("=== REQUEST: POST /api/launch_abaqus ===")
    
    try:
        data = request.get_json()
        csv_data = data.get('csv_data')
        
        if not csv_data:
            return jsonify({'success': False, 'message': 'No CSV data provided'}), 400
        
        abaqus_paths = [
            r"C:\SIMULIA\Commands\abaqus.bat",
            r"C:\Program Files\Dassault Systemes\SimulationServices\V6R2017x\win_b64\code\bin\ABQLauncher.exe",
            r"C:\SIMULIA\Abaqus\Commands\abaqus.bat",
            "abaqus"
        ]
        
        abaqus_exe = None
        for path in abaqus_paths:
            if os.path.exists(path):
                abaqus_exe = path
                break
        
        if not abaqus_exe:
            try:
                result = subprocess.run(['where', 'abaqus'], capture_output=True, text=True, shell=True)
                if result.returncode == 0:
                    abaqus_exe = result.stdout.strip().split('\n')[0]
            except:
                pass
        
        if not abaqus_exe:
            return jsonify({
                'success': False, 
                'message': 'ABAQUS not found.'
            }), 404
        
        logger.info(f"Found ABAQUS at: {abaqus_exe}")
        
        try:
            # Launch ABAQUS CLI (command environment) in a new window
            # This opens the ABAQUS command prompt interface
            if os.name == 'nt':  # Windows
                # For ABAQUS, we want to open the Commands prompt first
                # Then optionally launch CAE GUI
                
                # Option 1: Just open ABAQUS Commands environment (CLI)
                # This gives user the ABAQUS> prompt to run commands
                ps_command = f'Start-Process cmd.exe -ArgumentList "/k","{abaqus_exe}" -WindowStyle Normal'
                
                process = subprocess.Popen(
                    ['powershell.exe', '-Command', ps_command],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                
                # Wait a moment for CLI to initialize
                import time
                time.sleep(2)
                
                # Now launch CAE GUI in the background (optional - comment out if you only want CLI)
                gui_command = f'Start-Process "{abaqus_exe}" -ArgumentList "cae" -WindowStyle Normal'
                subprocess.Popen(
                    ['powershell.exe', '-Command', gui_command],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            else:  # Linux/Mac
                process = subprocess.Popen(
                    [abaqus_exe, 'cae'],  
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
            
            logger.info(f"ABAQUS CLI and CAE launched successfully")
            
            return jsonify({
                'success': True,
                'message': f'ABAQUS CLI opened. You can now run ABAQUS commands. CAE GUI is loading...',
                'abaqus_path': abaqus_exe
            })
            
        except Exception as e:
            logger.error(f"Failed to launch ABAQUS: {str(e)}")
            return jsonify({
                'success': False,
                'message': f'Failed to launch ABAQUS: {str(e)}'
            }), 500
            
    except Exception as e:
        logger.error(f"Error in launch_abaqus endpoint: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Error: {str(e)}'
        }), 500


# ============================================================================
# ABAQUS FEM INTEGRATION - Extract dimensions & stress-strain, modify .inp
# ============================================================================

def extract_dimensions_and_stress_strain(pdf_path, serial_number):
    """
    Extract dimensions from page 1 and stress-strain table from PDF based on serial number.
    Uses GPT-4o Vision for intelligent extraction.
    
    Returns:
    {
        'dimensions': {'length': float, 'width': float, 'height': float},
        'stress_strain': [{'stress': float, 'strain': float}, ...],
        'serial_number': str
    }
    """
    try:
        import fitz  # PyMuPDF
        
        # Open PDF
        doc = fitz.open(pdf_path)
        
        # Extract page 1 for dimensions
        page1 = doc[0]
        pix = page1.get_pixmap(dpi=150)
        img_bytes = pix.tobytes("png")
        page1_base64 = base64.b64encode(img_bytes).decode('utf-8')
        
        # Extract all pages for stress-strain table search
        all_pages_base64 = []
        for page_num in range(len(doc)):
            page = doc[page_num]
            pix = page.get_pixmap(dpi=150)
            img_bytes = pix.tobytes("png")
            all_pages_base64.append(base64.b64encode(img_bytes).decode('utf-8'))
        
        doc.close()
        
        # Initialize OpenAI client
        client = OpenAI(api_key=OPENAI_API_KEY)
        
        # Query 1: Extract dimensions from page 1
        dimensions_prompt = f"""
        You are analyzing a technical document for serial number: {serial_number}
        
        This is a CYLINDRICAL SPECIMEN. Look for these specific dimensions:
        - DIAMETER or D or d or Ø (in mm) - the circular cross-section diameter
        - LENGTH or L or l or Height or H (in mm) - the cylinder length/height
        
        Common formats:
        - "Diameter: 100 mm" → diameter = 100
        - "D = 50mm" → diameter = 50
        - "Length: 150 mm" → length = 150
        - "L = 200mm" → length = 200
        
        Extract ONLY numeric values (without units).
        
        Return ONLY a JSON object in this exact format (no markdown, no code blocks):
        {{"diameter": <number>, "length": <number>}}
        
        If a dimension is not found, use null.
        Example: {{"diameter": 100, "length": 150}}
        
        DO NOT wrap in markdown code blocks. Return ONLY the raw JSON.
        """
        
        dimensions_response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": dimensions_prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{page1_base64}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=500
        )
        
        dimensions_text = dimensions_response.choices[0].message.content.strip()
        logger.info(f"Dimensions extraction RAW: {dimensions_text}")
        
        # Parse dimensions JSON (remove markdown code blocks if present)
        import json
        import re
        
        # Remove markdown code blocks (```json ... ``` or ``` ... ```)
        clean_dimensions = re.sub(r'^```(?:json)?\s*|\s*```$', '', dimensions_text, flags=re.MULTILINE).strip()
        logger.info(f"Dimensions extraction CLEANED: {clean_dimensions}")
        dimensions = json.loads(clean_dimensions)
        logger.info(f"Dimensions extraction PARSED: {dimensions}")

        stress_strain_prompt = f"""
        You are analyzing a technical document for serial number: {serial_number}
        
        Find and extract stress-strain data. Look for:
        - Tables with "Stress" and "Strain" columns
        - Graphs with stress-strain curves (read data points from graph)
        - Listed data in format like "Stress: X, Strain: Y"
        
        Extract numeric values only (remove units if present).
        
        Return ONLY a JSON array in this exact format (no markdown, no code blocks):
        [{{"stress": <number>, "strain": <number>}}, {{"stress": <number>, "strain": <number>}}]
        
        If no stress-strain data is found, return an empty array: []
        
        DO NOT wrap in markdown code blocks. Return ONLY the raw JSON array.
        Important: Extract ALL data points you can find.
        """
        
        # Use first 5 pages to search for stress-strain data
        search_pages = all_pages_base64[:min(5, len(all_pages_base64))]
        
        content_list = [{"type": "text", "text": stress_strain_prompt}]
        for idx, page_base64 in enumerate(search_pages):
            content_list.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{page_base64}"}
            })
        
        stress_strain_response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": content_list}],
            max_tokens=2000
        )
        
        stress_strain_text = stress_strain_response.choices[0].message.content.strip()
        logger.info(f"Stress-strain extraction: {stress_strain_text[:200]}...")
        
        # Parse stress-strain JSON (remove markdown code blocks if present)
        clean_stress_strain = re.sub(r'^```(?:json)?\s*|\s*```$', '', stress_strain_text, flags=re.MULTILINE).strip()
        stress_strain_data = json.loads(clean_stress_strain)
        
        return {
            'dimensions': dimensions,
            'stress_strain': stress_strain_data,
            'serial_number': serial_number
        }
        
    except Exception as e:
        logger.error(f"Error extracting data: {str(e)}")
        raise


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


@app.route('/api/upload_abaqus_fem', methods=['POST'])
@jwt_required()
def upload_abaqus_fem():
    """
    Process PDF to extract dimensions and stress-strain data,
    then generate modified Abaqus .inp file for download.
    """
    try:
        current_user = get_jwt_identity()
        logger.info(f"User {current_user} requested ABAQUS FEM processing")
        
        # Validate file upload
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'Empty filename'}), 400
        
        # Get serial number from form
        serial_number = request.form.get('serial_number', '').strip()
        if not serial_number:
            return jsonify({'error': 'Serial number is required'}), 400
        
        # Save uploaded PDF
        filename = secure_filename(file.filename)
        task_id = str(uuid.uuid4())
        pdf_path = os.path.join(UPLOAD_FOLDER, f"{task_id}_{filename}")
        file.save(pdf_path)
        
        # Base Compression.inp path
        base_inp_path = os.path.join(os.path.dirname(__file__), 'Compression.inp')
        if not os.path.exists(base_inp_path):
            return jsonify({'error': 'Base Compression.inp file not found'}), 500
        
        # Output .inp path
        output_filename = f"{serial_number}_modified.inp"
        output_inp_path = os.path.join(OUTPUT_FOLDER, f"{task_id}_{output_filename}")
        
        # Process in background thread
        task_status = {
            'status': 'processing',
            'message': 'Extracting dimensions and stress-strain data...',
            'progress': 0,
            'user_id': int(current_user),
            'extraction_method': 'abaqus_fem'
        }
        
        processing_status[task_id] = task_status
        
        def process_abaqus():
            try:
                # Step 1: Extract data from PDF
                task_status['message'] = 'Analyzing PDF with GPT-4o Vision...'
                task_status['progress'] = 20
                
                extracted_data = extract_dimensions_and_stress_strain(pdf_path, serial_number)
                
                task_status['message'] = 'Modifying Abaqus .inp file...'
                task_status['progress'] = 60
                
                # Step 2: Modify .inp file
                modify_abaqus_inp(
                    base_inp_path,
                    output_inp_path,
                    extracted_data['dimensions'],
                    extracted_data['stress_strain']
                )
                
                task_status['status'] = 'completed'
                task_status['message'] = 'Processing complete'
                task_status['progress'] = 100
                task_status['extracted_data'] = extracted_data
                task_status['output_file'] = output_inp_path
                task_status['output_filename'] = output_filename
                
                logger.info(f"ABAQUS FEM processing completed for task {task_id}")
                
            except Exception as e:
                logger.error(f"Error in ABAQUS FEM processing: {str(e)}")
                task_status['status'] = 'error'
                task_status['message'] = f'Error: {str(e)}'
                task_status['progress'] = 0
        
        thread = threading.Thread(target=process_abaqus)
        thread.start()
        
        return jsonify({
            'task_id': task_id,
            'message': 'Processing started',
            'serial_number': serial_number
        })
        
    except Exception as e:
        logger.error(f"Error in upload_abaqus_fem: {str(e)}")
        return jsonify({'error': str(e)}), 500


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
        serial_number = request.form.get('serialNumber', '').strip()
        
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
        
        output_file = task_data.get('output_file')
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
                
                sim_status['message'] = 'Executing ABAQUS command...'
                sim_status['progress'] = 10
                
                # ABAQUS command: abaqus job=<jobname> input=<inputfile> interactive
                # The command will look for abaqus in PATH
                abaqus_cmd = [
                    'abaqus',
                    f'job={inp_name}',
                    f'input={output_file}',
                    'interactive',
                    'ask_delete=OFF'
                ]
                
                logger.info(f"Running ABAQUS: {' '.join(abaqus_cmd)}")
                sim_status['output'].append(f"Command: {' '.join(abaqus_cmd)}\n")
                
                # Run ABAQUS process
                process = subprocess.Popen(
                    abaqus_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    cwd=inp_dir,
                    bufsize=1,
                    universal_newlines=True
                )
                
                sim_status['progress'] = 20
                
                # Stream output
                for line in iter(process.stdout.readline, ''):
                    if line:
                        sim_status['output'].append(line)
                        logger.info(f"ABAQUS: {line.strip()}")
                        
                        # Update progress based on output
                        if 'Analysis complete' in line or 'completed successfully' in line.lower():
                            sim_status['progress'] = 90
                        elif 'Step' in line or 'Increment' in line:
                            sim_status['progress'] = min(80, sim_status['progress'] + 5)
                
                process.wait()
                
                if process.returncode == 0:
                    sim_status['status'] = 'completed'
                    sim_status['message'] = 'Simulation completed successfully'
                    sim_status['progress'] = 100
                    
                    # Look for output files
                    odb_file = os.path.join(inp_dir, f"{inp_name}.odb")
                    dat_file = os.path.join(inp_dir, f"{inp_name}.dat")
                    msg_file = os.path.join(inp_dir, f"{inp_name}.msg")
                    
                    sim_status['output_files'] = {
                        'odb': odb_file if os.path.exists(odb_file) else None,
                        'dat': dat_file if os.path.exists(dat_file) else None,
                        'msg': msg_file if os.path.exists(msg_file) else None
                    }
                    
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



if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)
