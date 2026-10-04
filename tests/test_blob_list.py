from blob_service import list_cvs

files = list_cvs()
print(f"Found {len(files)} files:")
for f in files:
    print(" -", f)