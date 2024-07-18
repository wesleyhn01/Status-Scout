from __future__ import print_function
import pickle
import os.path
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from email.utils import parsedate_to_datetime
import sqlite3
from googleapiclient.errors import HttpError
from typing import List, Dict, Any
import re
from tqdm import tqdm
from datetime import datetime

# Constants
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/spreadsheets']
DB_FILENAME = "emails.db"
TXT_FILENAME = "email_results.txt"
CREDENTIALS_FILE = 'credentials.json'

def get_service(service_name: str, token_file: str):
    creds = None
    if os.path.exists(token_file):
        with open(token_file, 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_file, 'wb') as token:
            pickle.dump(creds, token)
    return build(service_name, 'v1' if service_name == 'gmail' else 'v4', credentials=creds)

def search_emails(service: Any, query: str) -> List[Dict[str, str]]:
    result = service.users().messages().list(userId='me', q=query).execute()
    messages = result.get('messages', [])
    
    email_details = []
    for message in tqdm(messages, desc="Fetching email details"):
        msg = service.users().messages().get(userId='me', id=message['id']).execute()
        date_str = next((header['value'] for header in msg['payload']['headers'] if header['name'] == 'Date'), 'N/A')
        date_obj = parsedate_to_datetime(date_str)
        formatted_date = date_obj.strftime("%m/%d/%Y") if date_obj else 'N/A'
        email_details.append({
            'subject': next((header['value'] for header in msg['payload']['headers'] if header['name'] == 'Subject'), 'N/A'),
            'date': formatted_date
        })
    
    return email_details

def save_to_database(email_details: List[Dict[str, str]], db_filename: str):
    with sqlite3.connect(db_filename) as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT, date TEXT)''')
        c.executemany('''INSERT INTO emails (subject, date) VALUES (?, ?)''',
                      [(email['subject'], email['date']) for email in email_details])

def save_to_file(email_details: List[Dict[str, str]], filename: str):
    with open(filename, 'w', encoding='utf-8') as f:
        for email in email_details:
            f.write(f"Subject/Title/Event: {email['subject']}\n")
            f.write(f"Date Applied: {email['date']}\n\n")

def update_sheet(email_details: List[Dict[str, str]], spreadsheet_id: str, platform: str, status: str):
    sheets_service = get_service('sheets', 'token_sheets.pickle')
    
    # First, get the current values in the sheet
    result = sheets_service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range='A:Z').execute()
    current_values = result.get('values', [])
    
    # Find the columns for "Subject/Title/Event", "Date Applied", "Platform", and "Status"
    header_row = current_values[0] if current_values else []
    subject_col = next((chr(65 + i) for i, h in enumerate(header_row) if h == "Subject/Title/Event"), None)
    date_col = next((chr(65 + i) for i, h in enumerate(header_row) if h == "Date Applied/Email Sent"), None)
    platform_col = next((chr(65 + i) for i, h in enumerate(header_row) if h == "Platform"), None)
    status_col = next((chr(65 + i) for i, h in enumerate(header_row) if h == "Status"), None)
    
    if not subject_col or not date_col or not platform_col or not status_col:
        raise ValueError("Required columns not found in the sheet")
    
    # Find the first empty row in each column
    subject_empty_row = next((i for i, row in enumerate(current_values) if i > 0 and (len(row) <= ord(subject_col) - 65 or row[ord(subject_col) - 65] == "")), len(current_values))
    date_empty_row = next((i for i, row in enumerate(current_values) if i > 0 and (len(row) <= ord(date_col) - 65 or row[ord(date_col) - 65] == "")), len(current_values))
    platform_empty_row = next((i for i, row in enumerate(current_values) if i > 0 and (len(row) <= ord(platform_col) - 65 or row[ord(platform_col) - 65] == "")), len(current_values))
    status_empty_row = next((i for i, row in enumerate(current_values) if i > 0 and (len(row) <= ord(status_col) - 65 or row[ord(status_col) - 65] == "")), len(current_values))
    
    # Prepare the values to be inserted
    subject_values = [[email['subject']] for email in email_details]
    date_values = [[email['date']] for email in email_details]
    platform_values = [[platform] for _ in email_details]
    status_values = [[status] for _ in email_details]
    
    # Update the sheet
    subject_range = f'{subject_col}{subject_empty_row + 1}:{subject_col}{subject_empty_row + len(subject_values)}'
    date_range = f'{date_col}{date_empty_row + 1}:{date_col}{date_empty_row + len(date_values)}'
    platform_range = f'{platform_col}{platform_empty_row + 1}:{platform_col}{platform_empty_row + len(platform_values)}'
    status_range = f'{status_col}{status_empty_row + 1}:{status_col}{status_empty_row + len(status_values)}'
    
    try:
        sheets_service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id, range=subject_range,
            valueInputOption='RAW', body={'values': subject_values}).execute()
        
        sheets_service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id, range=date_range,
            valueInputOption='RAW', body={'values': date_values}).execute()
        
        sheets_service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id, range=platform_range,
            valueInputOption='RAW', body={'values': platform_values}).execute()
        
        sheets_service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id, range=status_range,
            valueInputOption='RAW', body={'values': status_values}).execute()
    except HttpError as err:
        print(f"An error occurred while updating the sheet: {err}")

def extract_spreadsheet_id(sheet_link: str) -> str:
    match = re.search(r'/d/([a-zA-Z0-9-_]+)', sheet_link)
    if match:
        return match.group(1)
    else:
        raise ValueError("Invalid Google Sheet link")

def run_script(search_type: int, sheet_link: str, keywords: str = None, linkedin_type: str = None) -> List[Dict[str, str]]:
    spreadsheet_id = extract_spreadsheet_id(sheet_link)
    
    for filename in [DB_FILENAME, TXT_FILENAME]:
        if os.path.exists(filename):
            os.remove(filename)
    
    service = get_service('gmail', 'token_gmail.pickle')

    if search_type == 1:
        query = '"Application submitted to"'
        platform = "Handshake"
        status = "Applied"
    elif search_type == 2:
        platform = "LinkedIn"
        if linkedin_type == '1':
            query = '"Your application was sent"'
            status = "Applied"
        elif linkedin_type == '2':
            query = '"Your application was viewed"'
            status = "Viewed"
        elif linkedin_type == '3':
            query = '"Thank you for your interest" AND "Unfortunately"'
            status = "Deferred"
        else:
            raise ValueError("Invalid LinkedIn query type.")
    elif search_type == 3 and keywords:
        query = ' OR '.join(keywords.split())
        platform = "External"
        status = ""  # Leave status empty for free search
    else:
        raise ValueError("Invalid search type or missing keywords for free search.")

    email_details = search_emails(service, query)
    
    save_to_database(email_details, DB_FILENAME)
    save_to_file(email_details, TXT_FILENAME)
    
    update_sheet(email_details, spreadsheet_id, platform, status)
    
    return email_details

if __name__ == "__main__":
    print("Welcome to Status Scout!")
    print("\nFirst, please make a copy of this spreadsheet:")
    print("https://docs.google.com/spreadsheets/d/10H-ZVEZ7kCJeH1xGnBr5qTzHrJ2v8s0FVWy-RsasVGY/edit?usp=sharing")
    print("\nAfter making a copy, please enter the link to your copy of the spreadsheet.")
    sheet_link = input("Paste your copy of the sheet link here: ")

    print("\nSelect search type:")
    print("1. Handshake")
    print("2. LinkedIn")
    print("3. Free-Search")
    search_type = int(input("Enter 1, 2, or 3: "))
    
    keywords = None
    if search_type == 3:
        keywords = input("Enter keywords to search (space-separated): ")
    
    linkedin_type = None
    if search_type == 2:
        print("\nSelect LinkedIn query type:")
        print("1. Applied")
        print("2. Viewed")
        print("3. Deferred")
        linkedin_type = input("Enter 1, 2, or 3: ")
    
    try:
        run_script(search_type, sheet_link, keywords, linkedin_type)
        print("Check your sheet for the updated results!")
    except ValueError as e:
        print(e)