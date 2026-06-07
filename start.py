import os
import sys

mode = os.getenv("START_MODE", "api")

if mode == "dashboard":
    from src.ui.dashboard_prod import main
    main()
else:
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("src.api.routes:app", host="0.0.0.0", port=port)