import streamlit as st
import os
import json
import tempfile
import logging
import pandas as pd
from google import genai

# Import decoupled modules
from ingestion import IngestionManager
from extraction import ExtractionEngine
from database import DataManager

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Streamlit Page Config
st.set_page_config(page_title="Logistics & Warehouse Automation", layout="wide")

# Initialize Session State for logs and UI flow
if "process_logs" not in st.session_state:
    st.session_state.process_logs = []

def add_log(message: str):
    """Helper to add logs to session state and display them."""
    st.session_state.process_logs.append(message)
    logger.info(message)

# --- SIDEBAR CONFIGURATION ---
st.sidebar.title("⚙️ Configuration")
gemini_api_key = st.sidebar.text_input("Gemini API Key", type="password")

# Dynamic Model Selector
selected_model = None
if gemini_api_key:
    try:
        client = genai.Client(api_key=gemini_api_key)
        # Fetch available models dynamically
        available_models = [m.name for m in client.models.list()]
        
        # Default to gemini-1.5-flash if available, otherwise fallback to the first in the list
        default_index = available_models.index("gemini-1.5-flash") if "gemini-1.5-flash" in available_models else 0
        
        selected_model = st.sidebar.selectbox(
            "Select Gemini Model", 
            options=available_models,
            index=default_index
        )
    except Exception as e:
        st.sidebar.error(f"Failed to authenticate or fetch models: {str(e)}")
        logger.error(f"Model fetch error: {str(e)}")

st.sidebar.markdown("---")
workspace_dir = st.sidebar.text_input("Local Workspace Directory", value="./workspace")
excel_fallback_path = st.sidebar.text_input("Local Excel Fallback Path", value="./workspace/logistics_db.xlsx")

st.sidebar.markdown("### Google Sheets Config (Optional)")
gs_sheet_name = st.sidebar.text_input("Google Sheet Name", value="Warehouse_Logs")
gs_creds_str = st.sidebar.text_area("GCP Service Account JSON", help="Paste the entire JSON credentials here.")

# Parse GCP Credentials
gs_creds_dict = None
if gs_creds_str:
    try:
        gs_creds_dict = json.loads(gs_creds_str)
    except json.JSONDecodeError:
        st.sidebar.error("Invalid JSON format for GCP Credentials.")

# --- MAIN UI ---
st.title("📦 Logistics & Warehouse Automation Tool")
st.markdown("Plug-and-play document ingestion, LLM extraction, and database synchronization.")

tab1, tab2 = st.tabs(["📊 Live Operations", "📥 Manual Intake"])

# --- TAB 1: LIVE OPERATIONS ---
with tab1:
    st.header("Real-Time Warehouse Logs")
    st.markdown("Displays data pulled directly from the active Google Sheet or Local Excel fallback.")
    
    if st.button("🔄 Refresh Data"):
        with st.spinner("Fetching latest records..."):
            try:
                df = DataManager.get_all_records(gs_creds_dict, gs_sheet_name, excel_fallback_path)
                if not df.empty:
                    # Search and Filter functionality
                    search_query = st.text_input("🔍 Search by Vendor, Invoice, Tracking ID, or Item")
                    if search_query:
                        mask = df.apply(lambda row: row.astype(str).str.contains(search_query, case=False).any(), axis=1)
                        df = df[mask]
                    
                    st.dataframe(df, use_container_width=True)
                else:
                    st.info("No records found in the database.")
            except Exception as e:
                st.error(f"Failed to load data: {str(e)}")

# --- TAB 2: MANUAL INTAKE ---
with tab2:
    st.header("Manual Batch Document Processing")
    
    # Updated file uploader to accept multiple files and image formats
    uploaded_files = st.file_uploader(
        "Drag and drop scanned PDFs or Images (Invoice, BOL, etc.)", 
        type=['pdf', 'png', 'jpg', 'jpeg'], 
        accept_multiple_files=True
    )
    
    if uploaded_files:
        if st.button("🚀 Process Batch"):
            if not gemini_api_key or not selected_model:
                st.error("⚠️ Please provide a valid Gemini API Key and select a model in the sidebar configuration.")
            else:
                progress_bar = st.progress(0)
                total_files = len(uploaded_files)
                
                # Loop through all uploaded files for batch processing
                for idx, uploaded_file in enumerate(uploaded_files):
                    st.markdown(f"#### Processing File {idx + 1} of {total_files}: `{uploaded_file.name}`")
                    
                    # Create a temporary file to bridge Streamlit's UploadedFile with the IngestionManager
                    with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{uploaded_file.name}") as tmp_file:
                        tmp_file.write(uploaded_file.getvalue())
                        temp_filepath = tmp_file.name

                    try:
                        with st.status(f"Processing {uploaded_file.name}...", expanded=True) as status:
                            # Step 1: Ingestion
                            st.write("Step 1: Staging file in local workspace...")
                            add_log(f"Starting ingestion for {uploaded_file.name}")
                            metadata = IngestionManager.stage_local_file(
                                source_filepath=temp_filepath, 
                                workspace_dir=workspace_dir, 
                                source_type="Manual_UI"
                            )
                            add_log(f"File staged at {metadata['file_path']}")

                            # Step 2: Extraction
                            st.write(f"Step 2: Extracting structured data via {selected_model}...")
                            add_log(f"Initiating LLM extraction using {selected_model}...")
                            extracted_data = ExtractionEngine.extract_document_data(
                                file_path=metadata['file_path'], 
                                api_key=gemini_api_key,
                                model_name=selected_model
                            )
                            add_log(f"Extracted Invoice/BOL: {extracted_data.get('invoice_or_bol_number')}")

                            # Step 3: Database Storage
                            st.write("Step 3: Synchronizing with Database (Flattening, Deduplication & Save)...")
                            add_log("Checking for duplicates and saving flattened records...")
                            saved = DataManager.save_record(
                                data=extracted_data,
                                credentials_dict=gs_creds_dict,
                                sheet_name=gs_sheet_name,
                                excel_path=excel_fallback_path
                            )
                            
                            if saved:
                                status.update(label=f"✅ Successfully processed {uploaded_file.name}", state="complete", expanded=False)
                                add_log(f"Record for {uploaded_file.name} successfully persisted.")
                            else:
                                status.update(label=f"⚠️ Duplicate detected for {uploaded_file.name}. Skipped.", state="complete", expanded=False)
                                add_log(f"Duplicate detected for {uploaded_file.name}. Skipped database write.")

                    except Exception as e:
                        st.error(f"An error occurred processing {uploaded_file.name}: {str(e)}")
                        add_log(f"ERROR on {uploaded_file.name}: {str(e)}")
                    finally:
                        # Clean up the temporary file
                        if os.path.exists(temp_filepath):
                            os.remove(temp_filepath)
                            
                    # Update progress bar
                    progress_bar.progress((idx + 1) / total_files)
                
                st.success("🎉 Batch processing complete!")

    # Display Session Logs
    st.markdown("---")
    st.markdown("### 📝 Operation Logs")
    log_container = st.container()
    with log_container:
        for log in st.session_state.process_logs[-15:]: # Show last 15 logs
            st.text(log)
            
    if st.button("Clear Logs"):
        st.session_state.process_logs = []
        st.rerun()