"""
Secure Email Dispatch Service for Job Hunter & Recruiter Intelligence.
Pulls sender email, recipient email, and app password securely from environment variables / .env.
Ensures zero hardcoding, zero credential leakage, and complete privacy.
"""

import os
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv

# Load local environment configuration safely
load_dotenv()


def get_email_credentials() -> Dict[str, str]:
    """
    Dynamically discover email settings and app password from environment variables.
    Supports standard naming conventions:
    - SENDER/USERNAME: SENDER_EMAIL, EMAIL_USER, GMAIL_USER, DEFAULT_EMAIL, USER_EMAIL, or fallback
    - RECIPIENT: RECIPIENT_EMAIL, TARGET_EMAIL, NOTIFICATION_EMAIL, or sender
    - APP PASSWORD: EMAIL_APP_PASSWORD, EAIL_APP_PASSWORD, GMAIL_APP_PASSWORD, SMTP_PASSWORD, MAIL_PASSWORD
    - SMTP HOST: SMTP_HOST (default: smtp.gmail.com)
    - SMTP PORT: SMTP_PORT (default: 465 for SSL or 587 for TLS)
    """
    app_password = (
        os.getenv("EMAIL_APP_PASSWORD")
        or os.getenv("EAIL_APP_PASSWORD")
        or os.getenv("GMAIL_APP_PASSWORD")
        or os.getenv("SMTP_PASSWORD")
        or os.getenv("MAIL_PASSWORD")
        or ""
    ).strip()

    # User recipient / dedicated email address (strictly from environment)
    recipient = (
        os.getenv("RECIPIENT_EMAIL")
        or os.getenv("NOTIFICATION_EMAIL")
        or os.getenv("TARGET_EMAIL")
        or os.getenv("DEFAULT_EMAIL")
        or ""
    ).strip()

    # Sender username / address (strictly from environment)
    sender = (
        os.getenv("SENDER_EMAIL")
        or os.getenv("EMAIL_USER")
        or os.getenv("GMAIL_USER")
        or os.getenv("USER_EMAIL")
        or recipient
    ).strip()

    # Fallback to active candidate profile if not specified in .env
    if not recipient or not sender:
        try:
            from runtime.intelligence import get_candidate_context
            ctx = get_candidate_context()
            cand_email = ctx.get("email", "").strip()
            if cand_email:
                recipient = recipient or cand_email
                sender = sender or cand_email
        except Exception:
            pass


    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
    smtp_port = int(os.getenv("SMTP_PORT", "465"))

    return {
        "sender": sender,
        "recipient": recipient,
        "app_password": app_password,
        "smtp_host": smtp_host,
        "smtp_port": smtp_port,
    }


def send_email(
    subject: str,
    body: str,
    to_email: Optional[str] = None,
    html: bool = False,
    attachment_paths: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Send an email securely using SMTP over SSL or STARTTLS.
    
    Args:
        subject: Email subject line.
        body: Plain text or HTML body content.
        to_email: Optional override for recipient. If omitted, uses RECIPIENT_EMAIL or default from .env.
        html: Whether the body should be sent as text/html.
        attachment_paths: Optional list of local file paths to attach (e.g., generated PDF dossiers/cover letters).
        
    Returns:
        Dict with status, message, and delivery details (omitting sensitive credentials).
    """
    creds = get_email_credentials()
    sender = creds["sender"]
    target_to = (to_email or creds["recipient"]).strip()
    app_password = creds["app_password"]
    smtp_host = creds["smtp_host"]
    smtp_port = creds["smtp_port"]

    if not app_password:
        return {
            "status": "error",
            "message": "Email app password not found in environment. Please set EMAIL_APP_PASSWORD or EAIL_APP_PASSWORD in .env.",
        }

    if not sender or not target_to:
        return {
            "status": "error",
            "message": "Sender or recipient email address is missing.",
        }

    # Construct the message
    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = target_to
    msg["Subject"] = subject

    body_type = "html" if html else "plain"
    msg.attach(MIMEText(body, body_type, "utf-8"))

    # Attach any requested documents
    attached_files = []
    if attachment_paths:
        for file_path_str in attachment_paths:
            path = Path(file_path_str).expanduser().resolve()
            if not path.is_file():
                continue
            try:
                with open(path, "rb") as f:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    f'attachment; filename="{path.name}"',
                )
                msg.attach(part)
                attached_files.append(path.name)
            except Exception as e:
                # Log attachment failure without breaking entire email send
                pass

    try:
        if smtp_port == 465:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context) as server:
                server.login(sender, app_password)
                server.sendmail(sender, [target_to], msg.as_string())
        else:
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.ehlo()
                context = ssl.create_default_context()
                server.starttls(context=context)
                server.ehlo()
                server.login(sender, app_password)
                server.sendmail(sender, [target_to], msg.as_string())

        return {
            "status": "success",
            "message": f"Email successfully delivered to {target_to}.",
            "recipient": target_to,
            "subject": subject,
            "attachments_count": len(attached_files),
            "attachments": attached_files,
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"SMTP dispatch failed: {str(e)}",
        }
