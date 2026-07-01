import logging
import json
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from google import genai
from google.genai import types

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Define Strict Pydantic Models for Structured Output
class LineItem(BaseModel):
    item_name: str = Field(description="The name or description of the item.")
    sku: Optional[str] = Field(default=None, description="The Stock Keeping Unit or product code.")
    quantity: float = Field(description="The quantity of the item.")
    price: float = Field(description="The unit price or total price of the item.")

class LogisticsDocument(BaseModel):
    vendor_name: str = Field(description="The name of the vendor, supplier, or shipper.")
    invoice_or_bol_number: str = Field(description="The Invoice number or Bill of Lading (BOL) number.")
    date: str = Field(description="The date on the document (YYYY-MM-DD format preferred).")
    tracking_id: Optional[str] = Field(default=None, description="The shipping tracking ID, if available.")
    document_type: str = Field(description="The type of document (e.g., Invoice, Bill of Lading, Packing Slip).")
    line_items: List[LineItem] = Field(description="List of items extracted from the document.")

class ExtractionEngine:
    """
    Leverages Google Gemini to extract structured data from logistics documents
    using the modern google-genai SDK and dynamic model selection.
    """

    @staticmethod
    def extract_document_data(file_path: str, api_key: str, model_name: str) -> Dict[str, Any]:
        """
        Uploads a document to Gemini, forces a structured JSON output matching the Pydantic schema,
        and returns the validated Python dictionary.
        """
        uploaded_file = None
        client = None
        
        try:
            logger.info(f"Starting extraction process for {file_path} using model {model_name}")
            
            # Initialize the modern GenAI client locally
            client = genai.Client(api_key=api_key)
            
            # Upload the file to Gemini's temporary storage
            logger.info("Uploading file to Gemini API...")
            uploaded_file = client.files.upload(file=file_path)
            logger.info(f"File uploaded successfully. URI: {uploaded_file.uri}")

            # Define prompt and generation configuration enforcing JSON and schema
            prompt = (
                "Analyze the attached logistics document. Extract the vendor name, invoice or BOL number, "
                "date, tracking ID, document type, and all line items. Ensure the output strictly matches "
                "the provided JSON schema."
            )
            
            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=LogisticsDocument,
                temperature=0.1 # Low temperature for factual extraction
            )

            logger.info(f"Generating structured content via {model_name}...")
            response = client.models.generate_content(
                model=model_name,
                contents=[uploaded_file, prompt],
                config=config
            )

            # Parse the guaranteed JSON string into a Python dictionary
            extracted_data = json.loads(response.text)
            logger.info("Successfully extracted and validated document data.")
            
            return extracted_data

        except Exception as e:
            logger.error(f"Error during document extraction: {str(e)}")
            raise
        finally:
            # Clean up the file from Gemini's servers to ensure security and quota management
            if client and uploaded_file:
                try:
                    client.files.delete(name=uploaded_file.name)
                    logger.info(f"Cleaned up remote file: {uploaded_file.name}")
                except Exception as cleanup_error:
                    logger.warning(f"Failed to clean up remote file {uploaded_file.name}: {str(cleanup_error)}")