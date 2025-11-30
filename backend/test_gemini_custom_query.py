"""
Test script for Gemini API custom query extraction from PDF
Uses Google's Gemini Pro Vision to answer custom queries about PDF documents
"""

import google.generativeai as genai
import os
from pathlib import Path
import mimetypes
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure Gemini API
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
if not GEMINI_API_KEY:
    print("Error: GEMINI_API_KEY environment variable not set")
    print("Set it in your .env file or export it:")
    print("  export GEMINI_API_KEY='your-api-key-here'")
    exit(1)

genai.configure(api_key=GEMINI_API_KEY)

def extract_custom_query_from_pdf(pdf_path, custom_query, system_prompt=None):
    """
    Extract custom query information from PDF using Gemini Pro Vision
    
    Args:
        pdf_path: Path to the PDF file
        custom_query: Custom question/query to ask about the PDF
        system_prompt: System instruction to guide the AI's behavior
        
    Returns:
        Dict with extraction results
    """
    try:
        print(f"Processing PDF: {pdf_path}")
        print(f"Query: {custom_query}")
        print("-" * 80)
        
        # Upload the PDF file
        print("Uploading PDF to Gemini...")
        pdf_file = genai.upload_file(pdf_path)
        print(f"Uploaded file: {pdf_file.name}")
        print(f"Display name: {pdf_file.display_name}")
        
        # Wait for file to be processed
        import time
        while pdf_file.state.name == "PROCESSING":
            print("Waiting for file processing...")
            time.sleep(2)
            pdf_file = genai.get_file(pdf_file.name)
        
        if pdf_file.state.name == "FAILED":
            raise Exception("File processing failed")
        
        print(f"File ready: {pdf_file.state.name}")
        
        # Default system prompt for ABAQUS input file generation
        if system_prompt is None:
            system_prompt = """You are a proffesional ABAQUS input file maker. You make input files with accurate syntax based on stress strain data for certain simulations as instructed"""
        
        # Use Gemini Pro Vision model with system instruction
        model = genai.GenerativeModel(
            'gemini-3-pro-preview',
            system_instruction=system_prompt
        )
        
        # Build the prompt
        prompt = custom_query
        
        print("\nSending request to Gemini Pro Vision...")
        print(f"System Prompt: {system_prompt[:100]}...")
        
        # Generate response
        response = model.generate_content(
            [pdf_file, prompt],
            generation_config={
                'temperature': 0.1,  # Low temperature for more factual responses
                'top_p': 0.95,
                'top_k': 40,
                'max_output_tokens': 8192,
            }
        )
        
        # Extract the response
        extracted_text = response.text
        
        print("\n" + "=" * 80)
        print("GEMINI RESPONSE")
        print("=" * 80)
        print(extracted_text)
        print("=" * 80)
        
        # Get token usage info if available
        try:
            usage = {
                'prompt_tokens': response.usage_metadata.prompt_token_count,
                'completion_tokens': response.usage_metadata.candidates_token_count,
                'total_tokens': response.usage_metadata.total_token_count
            }
            print(f"\nTokens used: {usage['total_tokens']} (prompt: {usage['prompt_tokens']}, completion: {usage['completion_tokens']})")
        except:
            usage = None
        
        return {
            'success': True,
            'query': custom_query,
            'response': extracted_text,
            'usage': usage,
            'file_uri': pdf_file.uri
        }
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }


if __name__ == "__main__":
    import sys
    
    # Example usage
    if len(sys.argv) < 3:
        print("Usage: python test_gemini_custom_query.py <pdf_file> <query>")
        print("\nExample:")
        print('  python test_gemini_custom_query.py document.pdf "Extract stress-strain data and generate ABAQUS input file"')
        print('  python test_gemini_custom_query.py data.pdf "Create a compression test input file with the material properties from this document"')
        print('  python test_gemini_custom_query.py report.pdf "Generate ABAQUS .inp file for tensile test using the data in this PDF"')
        sys.exit(1)
    
    pdf_path = sys.argv[1]
    custom_query = sys.argv[2]
    
    # Check if file exists
    if not os.path.exists(pdf_path):
        print(f"Error: File not found: {pdf_path}")
        sys.exit(1)
    
    # Run the extraction with ABAQUS system prompt
    result = extract_custom_query_from_pdf(pdf_path, custom_query)
    
    # Save result to file
    if result['success']:
        # Check if response contains .inp file content
        if '*HEADING' in result['response'] or '**' in result['response']:
            # Save as .inp file if it looks like ABAQUS input
            output_file = f"{Path(pdf_path).stem}_generated.inp"
        else:
            output_file = f"{Path(pdf_path).stem}_gemini_query_result.txt"
        
        with open(output_file, 'w', encoding='utf-8') as f:
            if not ('*HEADING' in result['response'] or '**' in result['response']):
                f.write(f"Query: {custom_query}\n\n")
                f.write("=" * 80 + "\n\n")
            f.write(result['response'])
        
        print(f"\nResult saved to: {output_file}")
    else:
        print(f"\nExtraction failed: {result['error']}")
