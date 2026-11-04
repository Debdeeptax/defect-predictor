"""Start the web app:  python run.py   (then open http://127.0.0.1:5000)"""
from app import create_app

app = create_app()

if __name__ == "__main__":
    cfg = app.config_obj
    app.run(host=cfg.HOST, port=cfg.PORT, debug=False, threaded=True)
