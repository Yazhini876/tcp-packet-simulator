import uvicorn
import sys
import os

if __name__ == "__main__":
    # Add backend directory to path
    backend_path = os.path.join(os.path.dirname(__file__), "backend")
    sys.path.insert(0, backend_path)
    
    # Run uvicorn server
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True, reload_dirs=[backend_path])
