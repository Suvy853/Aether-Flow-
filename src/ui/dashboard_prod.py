import os
from src.ui.dashboard import create_dash_app

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8050))
    api_base = os.getenv("API_BASE", "https://web-production-f0ca5.up.railway.app")
    os.environ["API_BASE"] = api_base
    app = create_dash_app()
    app.run(host="0.0.0.0", port=str(8050), debug=False)