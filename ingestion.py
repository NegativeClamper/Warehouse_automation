import os
import shutil
import logging
import datetime
from typing import List, Dict, Any
from O365 import Account

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class IngestionManager:
    """
    Handles ingestion of logistics documents from various sources (O365 Emails, Teams Webhooks, Local Files).
    Completely decoupled; relies on explicit arguments for configuration.
    """

    @staticmethod
    def fetch_unread_emails(client_id: str, client_secret: str, tenant_id: str, download_dir: str) -> List[Dict[str, Any]]:
        """
        Authenticates with O365 via Client Credentials, fetches unread emails, 
        downloads PDF/Image attachments, and returns metadata.
        """
        downloaded_files = []
        try:
            credentials = (client_id, client_secret)
            account = Account(credentials, auth_flow='client_credentials', tenant_id=tenant_id)
            
            if not account.authenticate():
                logger.error("O365 Authentication failed.")
                return downloaded_files

            mailbox = account.mailbox()
            query = mailbox.new_query().query('isRead').equals(False)
            messages = mailbox.get_messages(query=query, download_attachments=True)

            os.makedirs(download_dir, exist_ok=True)

            for message in messages:
                if message.has_attachments:
                    for attachment in message.attachments:
                        ext = os.path.splitext(attachment.name)[1].lower()
                        if ext in ['.pdf', '.png', '.jpg', '.jpeg', '.tiff']:
                            file_path = os.path.join(download_dir, attachment.name)
                            attachment.save(download_dir)
                            
                            downloaded_files.append({
                                "source": "O365_Email",
                                "sender": message.sender.address if message.sender else "Unknown",
                                "file_path": file_path,
                                "arrival_timestamp": datetime.datetime.now().isoformat()
                            })
                # Mark as read after processing
                message.mark_as_read()
                
            logger.info(f"Successfully fetched and processed {len(downloaded_files)} attachments from O365.")
            return downloaded_files

        except Exception as e:
            logger.error(f"Error fetching emails from O365: {str(e)}")
            raise

    @staticmethod
    def handle_teams_webhook(payload: Dict[str, Any], download_dir: str) -> Dict[str, Any]:
        """
        Parses an incoming Microsoft Teams JSON webhook payload.
        Extracts relevant metadata and simulates attachment staging if URLs are provided.
        """
        try:
            logger.info("Processing incoming Teams webhook payload.")
            os.makedirs(download_dir, exist_ok=True)
            
            message_id = payload.get("id", "unknown_id")
            sender = payload.get("from", {}).get("user", {}).get("displayName", "Unknown Sender")
            attachments = payload.get("attachments", [])
            
            processed_attachments = []
            for att in attachments:
                att_type = att.get("contentType", "")
                if "image" in att_type or "pdf" in att_type:
                    content_url = att.get("contentUrl")
                    # In a full network implementation, we would use requests.get(content_url) here.
                    # For this decoupled skeleton, we log the extraction of the URL.
                    logger.info(f"Identified attachment URL from Teams: {content_url}")
                    processed_attachments.append({
                        "attachment_id": att.get("id"),
                        "url": content_url,
                        "type": att_type
                    })

            result = {
                "source": "Teams_Webhook",
                "message_id": message_id,
                "sender": sender,
                "attachments_found": processed_attachments,
                "arrival_timestamp": datetime.datetime.now().isoformat()
            }
            logger.info(f"Successfully processed Teams payload: {message_id}")
            return result

        except Exception as e:
            logger.error(f"Error processing Teams webhook payload: {str(e)}")
            raise

    @staticmethod
    def stage_local_file(source_filepath: str, workspace_dir: str, source_type: str = "Manual_Upload") -> Dict[str, Any]:
        """
        Moves/copies an incoming file to a temporary workspace directory and returns standardized metadata.
        """
        try:
            if not os.path.exists(source_filepath):
                raise FileNotFoundError(f"Source file not found: {source_filepath}")

            os.makedirs(workspace_dir, exist_ok=True)
            filename = os.path.basename(source_filepath)
            
            # Append timestamp to prevent overwriting files with the same name
            timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            safe_filename = f"{timestamp}_{filename}"
            destination_path = os.path.join(workspace_dir, safe_filename)

            shutil.copy2(source_filepath, destination_path)
            logger.info(f"Successfully staged file to {destination_path}")

            return {
                "source": source_type,
                "original_filename": filename,
                "file_path": destination_path,
                "arrival_timestamp": datetime.datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"Error staging local file {source_filepath}: {str(e)}")
            raise