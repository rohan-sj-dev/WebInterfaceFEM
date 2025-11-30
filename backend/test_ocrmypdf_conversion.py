import convertapi
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure ConvertAPI credentials
CONVERT_API_KEY = os.getenv('CONVERT_API_KEY')
if not CONVERT_API_KEY:
    print("Error: CONVERT_API_KEY not found in environment variables!")
    print("Please add it to your .env file:")
    print("CONVERT_API_KEY=your_api_key_here")
    exit(1)

convertapi.api_credentials = CONVERT_API_KEY

# Input and output paths
input_pdf = "0047_001-combined.pdf"
output_dir = "."

# Check if input file exists
if not os.path.exists(input_pdf):
    print(f"Error: Input file '{input_pdf}' not found!")
    print(f"Current directory: {os.getcwd()}")
    exit(1)

print(f"Converting '{input_pdf}' to searchable PDF using ConvertAPI...")
print("This may take a few moments...")

try:
    # Generate output filename: original_name-converted
    base_name = os.path.splitext(os.path.basename(input_pdf))[0]
    output_filename = f"{base_name}-converted"
    
    # Convert PDF to OCR-searchable PDF using ConvertAPI
    result = convertapi.convert('ocr', {
        'File': input_pdf,
        'FileName': output_filename  # Specify output filename to avoid overwriting
    }, from_format='pdf')
    
    # Save the converted file
    saved_files = result.save_files(output_dir)
    
    print(f"\n✓ Success! Searchable PDF created!")
    
    # Display saved files
    for file_path in saved_files:
        if os.path.exists(file_path):
            print(f"  Output: {file_path}")
            
            # Check file sizes
            if os.path.exists(input_pdf):
                input_size = os.path.getsize(input_pdf) / 1024  # KB
                output_size = os.path.getsize(file_path) / 1024  # KB
                
                print(f"\nFile sizes:")
                print(f"  Original: {input_size:.2f} KB")
                print(f"  Converted: {output_size:.2f} KB")
                print(f"\n✓ Original file preserved: {input_pdf}")
    
except Exception as e:
    print(f"\n✗ Error during conversion: {str(e)}")
    print("\nTroubleshooting:")
    print("1. Make sure convertapi is installed: pip install convertapi")
    print("2. Check your API key is valid")
    print("3. Verify you have API credits: https://www.convertapi.com/")
    print("4. Check the input file is a valid PDF")
