from flask import Flask

def create_app():
    app = Flask(__name__)
    app.config.from_object('app.config')
    
    # Import and register your routes
    from app.routes import main
    app.register_blueprint(main)
    
    return app
