import os
import logging
import pandas as pd
import gspread
from typing import Dict, Any, List

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class DataManager:
    """
    Handles data persistence to Google Sheets with an automatic local Excel fallback.
    Includes strict deduplication mechanisms, data flattening for line items, 
    and PermissionError handling for Windows file locks.
    """

    @staticmethod
    def _flatten_to_rows(data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Intercepts the raw JSON dictionary, extracts base header data, and loops through 
        the line_items array to create a flattened list of row dictionaries.
        """
        base_data = {
            "vendor_name": data.get("vendor_name", ""),
            "invoice_or_bol_number": data.get("invoice_or_bol_number", ""),
            "date": data.get("date", ""),
            "tracking_id": data.get("tracking_id", ""),
            "document_type": data.get("document_type", "")
        }
        
        line_items = data.get("line_items", [])
        flattened_rows = []
        
        # If no line items exist, still record the base document
        if not line_items:
            row = base_data.copy()
            row.update({
                "item_name": "",
                "sku": "",
                "quantity": "",
                "price": ""
            })
            flattened_rows.append(row)
        else:
            # Create a new row for every individual line item
            for item in line_items:
                row = base_data.copy()
                row.update({
                    "item_name": item.get("item_name", ""),
                    "sku": item.get("sku", ""),
                    "quantity": item.get("quantity", ""),
                    "price": item.get("price", "")
                })
                flattened_rows.append(row)
                
        return flattened_rows

    @staticmethod
    def get_all_records(credentials_dict: Dict[str, Any], sheet_name: str, excel_path: str) -> pd.DataFrame:
        """Fetches all records from Google Sheets, falling back to local Excel if GS fails."""
        try:
            if credentials_dict and sheet_name:
                gc = gspread.service_account_from_dict(credentials_dict)
                sheet = gc.open(sheet_name).sheet1
                records = sheet.get_all_records()
                return pd.DataFrame(records)
        except Exception as e:
            logger.warning(f"Could not fetch from Google Sheets, falling back to Excel: {str(e)}")
        
        try:
            if os.path.exists(excel_path):
                return pd.read_excel(excel_path)
            return pd.DataFrame()
        except Exception as e:
            logger.error(f"Error reading local Excel file: {str(e)}")
            return pd.DataFrame()

    @staticmethod
    def is_duplicate(invoice_number: str, tracking_id: str, credentials_dict: Dict[str, Any], sheet_name: str, excel_path: str) -> bool:
        """Cross-references incoming IDs against existing rows to prevent duplicates globally."""
        try:
            df = DataManager.get_all_records(credentials_dict, sheet_name, excel_path)
            if df.empty:
                return False
            
            # Check for matches in invoice_or_bol_number or tracking_id
            if 'invoice_or_bol_number' in df.columns and invoice_number:
                if invoice_number in df['invoice_or_bol_number'].astype(str).values:
                    return True
            if 'tracking_id' in df.columns and tracking_id:
                # Filter out None/NaN before checking
                valid_tracking = df['tracking_id'].dropna().astype(str).values
                if tracking_id in valid_tracking:
                    return True
            return False
        except Exception as e:
            logger.error(f"Error during deduplication check: {str(e)}")
            raise

    @staticmethod
    def append_to_google_sheet(data: Dict[str, Any], credentials_dict: Dict[str, Any], sheet_name: str) -> None:
        """Appends flattened dictionary rows to a Google Sheet."""
        try:
            logger.info(f"Attempting to append flattened data to Google Sheet: {sheet_name}")
            gc = gspread.service_account_from_dict(credentials_dict)
            sheet = gc.open(sheet_name).sheet1
            
            flattened_rows = DataManager._flatten_to_rows(data)
            
            # If sheet is empty, write headers first
            if not sheet.get_all_values():
                sheet.append_row(list(flattened_rows[0].keys()))
                
            # Append all flattened rows at once
            values_to_append = [list(row.values()) for row in flattened_rows]
            sheet.append_rows(values_to_append)
            
            logger.info(f"Successfully appended {len(flattened_rows)} rows to Google Sheets.")
        except Exception as e:
            logger.error(f"Google Sheets API error: {str(e)}")
            raise

    @staticmethod
    def append_to_local_excel(data: Dict[str, Any], excel_path: str) -> None:
        """Appends flattened dictionary rows to a local Excel file with strict deduplication and error handling."""
        try:
            logger.info(f"Attempting to append flattened data to local Excel: {excel_path}")
            flattened_rows = DataManager._flatten_to_rows(data)
            df_new = pd.DataFrame(flattened_rows)
            invoice_num = str(data.get('invoice_or_bol_number', ''))

            # 1. Deduplication Check
            if os.path.exists(excel_path):
                # Read the existing sheet into a Pandas dataframe
                df_existing = pd.read_excel(excel_path)
                
                # Check if the incoming invoice_or_bol_number already exists in that sheet's data
                if 'invoice_or_bol_number' in df_existing.columns and invoice_num:
                    if invoice_num in df_existing['invoice_or_bol_number'].astype(str).values:
                        logger.warning(f"Duplicate found: Skipping {invoice_num}")
                        return  # DO NOT append the data
                
                # If it does not exist, proceed with appending normally
                df_combined = pd.concat([df_existing, df_new], ignore_index=True)
            else:
                df_combined = df_new

            # Ensure directory exists
            os.makedirs(os.path.dirname(excel_path), exist_ok=True)
            
            # 2. Permission Error Handling
            try:
                with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
                    df_combined.to_excel(writer, index=False, sheet_name='Sheet1')
            except PermissionError:
                # Raise a clear error string so the Streamlit UI doesn't crash and displays this exact message
                raise Exception("ERROR: Please close the Excel file. Windows is blocking the save.")
                
            logger.info(f"Successfully appended {len(flattened_rows)} rows to local Excel file.")
            
        except Exception as e:
            # If it's our custom PermissionError message, bubble it up directly
            if "Windows is blocking the save" in str(e):
                raise e
            logger.error(f"Local Excel write error: {str(e)}")
            raise

    @staticmethod
    def save_record(data: Dict[str, Any], credentials_dict: Dict[str, Any], sheet_name: str, excel_path: str) -> bool:
        """
        Orchestrates deduplication and saving. Tries Google Sheets first, falls back to Excel.
        Returns True if saved, False if duplicate.
        """
        try:
            invoice_num = str(data.get('invoice_or_bol_number', ''))
            tracking_id = str(data.get('tracking_id', ''))

            # Global deduplication check (Checks Google Sheets first if configured)
            if DataManager.is_duplicate(invoice_num, tracking_id, credentials_dict, sheet_name, excel_path):
                logger.warning(f"Duplicate detected for Invoice: {invoice_num} / Tracking: {tracking_id}. Skipping save.")
                return False

            try:
                if credentials_dict and sheet_name:
                    DataManager.append_to_google_sheet(data, credentials_dict, sheet_name)
                else:
                    raise ValueError("Missing Google Sheets credentials or sheet name.")
            except Exception as gs_error:
                logger.warning(f"Google Sheets save failed, triggering local fallback. Reason: {str(gs_error)}")
                # The local fallback now has its own isolated deduplication and PermissionError handling
                DataManager.append_to_local_excel(data, excel_path)
            
            return True
        except Exception as e:
            logger.error(f"Critical error in save_record orchestration: {str(e)}")
            raise