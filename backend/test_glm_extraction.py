"""
Test GLM-4.5V Table Extraction
Quick test script for the GLM vision service
"""

import os
from dotenv import load_dotenv
from glm_vision_service import GLMVisionService

# Load environment variables
load_dotenv()

def test_glm_extraction(image_paths, custom_prompt=None):
    """
    Test GLM table extraction with image files
    
    Args:
        image_paths: List of image file paths
        custom_prompt: Optional custom extraction prompt
    """
    print("="*70)
    print("GLM-4.5V TABLE EXTRACTION TEST")
    print("="*70)
    
    # Check API key
    api_key = os.getenv('GLM_API_KEY')
    if not api_key:
        print("❌ GLM_API_KEY not found in environment variables")
        print("   Add to .env file: GLM_API_KEY=your-key-here")
        print("   Get key from: https://z.ai/manage-apikey/apikey-list")
        return
    
    print(f"\n✓ API Key: {api_key[:10]}...{api_key[-4:]}")
    print(f"✓ Processing {len(image_paths)} images")
    
    # Initialize service
    service = GLMVisionService(api_key=api_key)
    
    # Extract tables
    print("\n📤 Sending request to GLM-4.5V API...")
    result = service.extract_tables_from_images(
        image_paths,
        custom_prompt=custom_prompt,
        return_format="csv"
    )
    
    # Display results
    print("\n" + "="*70)
    print("RESULTS")
    print("="*70)
    
    if result['success']:
        print("✅ Extraction successful!\n")
        print("📊 Extracted Tables (CSV):")
        print("-"*70)
        print(result['content'])
        print("-"*70)
        
        # Usage info
        usage = result.get('usage', {})
        print(f"\n📈 Token Usage:")
        print(f"   Input tokens:  {usage.get('prompt_tokens', 'N/A')}")
        print(f"   Output tokens: {usage.get('completion_tokens', 'N/A')}")
        print(f"   Total tokens:  {usage.get('total_tokens', 'N/A')}")
        
        # Save to file
        output_file = "test_extracted_tables.csv"
        if service.convert_to_csv_file(result['content'], output_file):
            print(f"\n💾 Saved to: {output_file}")
    else:
        print(f"❌ Extraction failed: {result.get('error', 'Unknown error')}")
        if 'raw_response' in result:
            print(f"\nRaw response: {result['raw_response']}")
    
    print("\n" + "="*70)


def test_with_pdf(pdf_path, custom_prompt=None):
    """
    Convert PDF to images and test extraction
    
    Args:
        pdf_path: Path to PDF file
        custom_prompt: Optional custom extraction prompt
    """
    print(f"📄 Converting PDF to images: {pdf_path}")
    
    try:
        import fitz  # PyMuPDF
        from PIL import Image
        import tempfile
        
        doc = fitz.open(pdf_path)
        image_paths = []
        
        # Convert each page
        for page_num in range(len(doc)):
            page = doc[page_num]
            # 2x resolution for better quality
            mat = fitz.Matrix(2.0, 2.0)
            pix = page.get_pixmap(matrix=mat)
            
            # Save to temp file
            img_path = f"temp_page_{page_num + 1}.png"
            pix.save(img_path)
            image_paths.append(img_path)
            print(f"   ✓ Page {page_num + 1} → {img_path}")
        
        doc.close()
        
        # Run extraction
        test_glm_extraction(image_paths, custom_prompt)
        
        # Clean up temp files
        print(f"\n🗑️  Cleaning up temporary files...")
        for img_path in image_paths:
            try:
                os.remove(img_path)
            except:
                pass
        
    except ImportError:
        print("❌ PyMuPDF not installed. Install with: pip install PyMuPDF")
    except Exception as e:
        print(f"❌ Error processing PDF: {e}")


if __name__ == "__main__":
    import sys
    
    print("\nGLM-4.5V Table Extraction Tester")
    print("="*70)
    
    if len(sys.argv) < 2:
        print("\nUsage:")
        print("  # Test with images")
        print("  python test_glm_extraction.py image1.jpg image2.png")
        print("")
        print("  # Test with PDF")
        print("  python test_glm_extraction.py document.pdf")
        print("")
        print("  # Test with custom prompt")
        print('  python test_glm_extraction.py doc.pdf "Extract only financial data"')
        print("\nSetup:")
        print("  1. Get API key from: https://z.ai/manage-apikey/apikey-list")
        print("  2. Add to .env: GLM_API_KEY=your-key-here")
        print("  3. Install deps: pip install python-dotenv requests PyMuPDF pillow")
        sys.exit(1)
    
    file_paths = [sys.argv[1]]
    custom_prompt = sys.argv[2] if len(sys.argv) > 2 else None
    
    # Check if PDF or images
    if file_paths[0].lower().endswith('.pdf'):
        test_with_pdf(file_paths[0], custom_prompt)
    else:
        # Image files
        if len(sys.argv) > 2 and not custom_prompt:
            # Multiple images provided
            file_paths = sys.argv[1:]
        test_glm_extraction(file_paths, custom_prompt)
