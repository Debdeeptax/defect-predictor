"""Start the web app:  python run.py   (then open http://127.0.0.1:5000)"""
from app import create_app

app = create_app()

if __name__ == "__main__":
    cfg = app.config_obj
    url = f"http://{'127.0.0.1' if cfg.HOST in ('0.0.0.0', '') else cfg.HOST}:{cfg.PORT}"
    # Flask's own "Running on ..." line goes to logs/app.log (root logger), so say it here.
    print(f"\n  Software Defect Prediction System is running.\n"
          f"  Open {url} in your web browser.\n"
          f"  Keep this window open while you use the app. Press CTRL+C to stop it.\n", flush=True)
    app.run(host=cfg.HOST, port=cfg.PORT, debug=False, threaded=True)
