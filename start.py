import os
import sys

mode = os.getenv("START_MODE", "api")

if mode == "dashboard":
    # Import dynamically to avoid static import issues if `main` isn't exported
    import importlib

    mod = importlib.import_module("src.ui.dashboard_prod")
    main = getattr(mod, "main", None)
    if not callable(main):
        raise ImportError("module 'src.ui.dashboard_prod' has no callable 'main'")
    main()
else:
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("src.api.routes:app", host="0.0.0.0", port=port)