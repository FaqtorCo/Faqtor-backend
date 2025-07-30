from flask import Flask, jsonify, request, json, send_from_directory
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from flask_sqlalchemy import SQLAlchemy
from app.config import Config
from app.models import db, bcrypt, Users
from flask_migrate import Migrate
from flask_cors import CORS
import cloudinary
import cloudinary.api
from cloudinary.uploader import upload
import pandas as pd
import subprocess
import os
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename


# Cloudinary configuration
cloudinary.config(
  cloud_name="dyglrkcfq",
  api_key="395913749757967",
  api_secret="M6teHfar6P_82VDeL7Yo5vzor_8"
)


app = Flask(__name__)
app.config.from_object(Config)
app.config['CORS_HEADERS'] = 'Content-Type'
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(days=30)  # Set to 30 days
# Add this configuration


database_url = os.environ.get('DATABASE_URL')


if database_url:
    # Cloud Run environment
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    # Local development
    app.config['SQLALCHEMY_DATABASE_URI'] = "postgresql://faqtor:1234@127.0.0.1:5432/faqtor"



db.init_app(app)
bcrypt.init_app(app)
jwt = JWTManager(app)
migrate = Migrate(app, db)


CORS(
    app,
    resources={r"/api/*": {
        "origins": [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
           
        ],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization", "Cache-Control"]
    }},
    supports_credentials=True
)

# CORS(app, resources={r"/api/*": {"origins": "*"}})

@app.cli.command("db")
def db_cli():
    """Flask-Migrate db command wrapper."""
    pass


from flask import make_response


@app.route("/healthz", methods=["GET"])
def healthz():
    return "OK", 200




@app.route('/api/signup', methods=['POST'])
def signup():
    data = request.get_json()
    name = data.get('name')
    email = data.get('email')
    password = data.get('password')

    # Validation
    if not name or not name.strip():
        return jsonify({"message": "Name is required"}), 400
    
    if not password or len(password) < 8:
        return jsonify({"message": "Password must be at least 8 characters long"}), 400

    # Check if user exists
    user = Users.query.filter_by(email=email).first()
    if user:
        return jsonify({"message": "User already exists"}), 400

    # Create new user
    new_user = Users(name=name.strip(), email=email)
    new_user.set_password(password)

    db.session.add(new_user)
    db.session.commit()

    return jsonify({"message": "User created successfully"}), 201


@app.route('/api/signin', methods=['POST'])
def signin():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    user = Users.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        return jsonify({"message": "Invalid email or password"}), 401

    # Create JWT token for the user
    access_token = create_access_token(identity=str(user.id))

    return jsonify({
        "access_token": access_token,
        "name": user.name  # Return user's name
    }), 200

@app.route('/protected', methods=['GET'])
@jwt_required()
def protected():
    # Access the identity of the current user with get_jwt_identity
    current_user = get_jwt_identity()
    user = Users.query.get(current_user)
    return jsonify(logged_in_as=user.email), 200

@app.route('/logout', methods=['POST'])
@jwt_required()
def logout():
    return jsonify(message="User logged out successfully"), 200









if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))  # Default to 5050 if PORT isn't set
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("DEBUG", False))




# if __name__ == "__main__":
#     port = int(os.environ.get("PORT", 8080))  # Default to 5050 if PORT isn't set
#     app.run(host="0.0.0.0", port=port, debug=False)



