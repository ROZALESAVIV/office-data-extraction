"""
Standalone smoke test for Supabase storage.
Run from the project root:  py -3 test_storage.py
"""
import os
import sys

# config.py resolves .env relative to CWD — must be backend/
os.chdir(os.path.join(os.path.dirname(__file__), "backend"))
sys.path.insert(0, os.getcwd())

from app.services.storage import delete_file, get_file_bytes, get_signed_url, upload_file

TENANT_ID = "test-tenant"
CASE_ID   = "test-case"
FILENAME  = "smoke-test.txt"
CONTENT   = b"Hello from storage smoke test"

print("1. Uploading file...")
path = upload_file(CONTENT, TENANT_ID, CASE_ID, FILENAME)
print(f"   storage_path = {path}")

print("2. Getting signed URL...")
url = get_signed_url(path)
print(f"   signed URL   = {url}")

print("3. Downloading bytes...")
downloaded = get_file_bytes(path)
print(f"   downloaded   = {downloaded}")
assert downloaded == CONTENT, f"Mismatch! Got: {downloaded}"



print("\nAll steps passed.")
