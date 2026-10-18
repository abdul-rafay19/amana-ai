import os, sys, tempfile
os.environ["AMANA_SKIP_DOTENV"] = "1"   # tests must never use the real keys in .env
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ["AMANA_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GROQ_API_KEY", "NVIDIA_API_KEY"):
    os.environ.pop(k, None)
import db
db.init()