from flask import Flask, jsonify, request, json, send_from_directory
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from flask_sqlalchemy import SQLAlchemy
from app.config import Config
from app.models import db, bcrypt, Users, DemoUsage  # Import DemoUsage
from flask_migrate import Migrate
from flask_cors import CORS
import cloudinary
import cloudinary.api
from cloudinary.uploader import upload
import pandas as pd
import subprocess
import os
import requests
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
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(days=30)

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
            "https://www.faqtor.co",
            "https://faqtor.co"
        ],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization", "Cache-Control"]
    }},
    supports_credentials=True
)

@app.cli.command("db")
def db_cli():
    """Flask-Migrate db command wrapper."""
    pass

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
        "name": user.name
    }), 200

@app.route('/protected', methods=['GET'])
@jwt_required()
def protected():
    current_user_id = get_jwt_identity()
    user = Users.query.get(current_user_id)
    return jsonify(logged_in_as=user.email), 200

@app.route('/logout', methods=['POST'])
@jwt_required()
def logout():
    return jsonify(message="User logged out successfully"), 200

# New endpoint to check if user can use calling agent
@app.route('/api/calling-agent/check-eligibility', methods=['GET'])
@jwt_required()
def check_calling_agent_eligibility():
    try:
        current_user_id = get_jwt_identity()
        user = Users.query.get(current_user_id)
        
        if not user:
            return jsonify({"message": "User not found"}), 404
        
        has_used = user.has_used_calling_agent()
        
        return jsonify({
            "canUse": not has_used,
            "message": "Demo already used" if has_used else "Demo available",
            "hasUsedDemo": has_used
        }), 200
        
    except Exception as e:
        return jsonify({"message": "Error checking eligibility", "error": str(e)}), 500

# New endpoint to initiate calling agent with restrictions
@app.route('/api/calling-agent/initiate', methods=['POST'])
@jwt_required()
def initiate_calling_agent():
    try:
        current_user_id = get_jwt_identity()
        user = Users.query.get(current_user_id)
        
        if not user:
            return jsonify({"message": "User not found"}), 404
        
        # Check if user has already used the calling agent
        if user.has_used_calling_agent():
            return jsonify({
                "message": "You have already used your free calling agent demo. Each account is limited to one demo call.",
                "canUse": False
            }), 403
        
        data = request.get_json()
        phone_number = data.get('phoneNumber')
        
        if not phone_number:
            return jsonify({"message": "Phone number is required"}), 400
        
        # Validate phone number format (basic validation)
        cleaned_number = ''.join(filter(str.isdigit, phone_number.replace('+', '')))
        if len(cleaned_number) < 10:
            return jsonify({"message": "Please enter a valid phone number"}), 400
        
        # Record the demo usage immediately (before making the call)
        demo_usage = DemoUsage(
            user_id=current_user_id,
            demo_type='calling_agent',
            phone_number=phone_number,
            status='initiated'
        )
        
        db.session.add(demo_usage)
        db.session.commit()
        
        # Make the webhook call to n8n
        webhook_url = os.environ.get('N8N_WEBHOOK_URL', 'https://n8n.softtik.com/webhook/calling-agent')
        # webhook_url = os.environ.get('N8N_WEBHOOK_URL', 'https://testing.com')

        payload = {
            'phoneNumber': phone_number,
            'timestamp': datetime.utcnow().isoformat(),
            'name': user.name,
            'userId': current_user_id
        }
        
        try:
            response = requests.post(
                webhook_url,
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=30
            )
            
            if response.status_code == 200:
                # Update status to completed
                demo_usage.status = 'completed'
                db.session.commit()
                
                return jsonify({
                    "message": "AI agent call initiated successfully! Please answer your phone.",
                    "success": True,
                    "canUse": False  # User can no longer use the demo
                }), 200
            else:
                # Update status to failed but don't allow retry
                demo_usage.status = 'failed'
                db.session.commit()
                
                return jsonify({
                    "message": "Failed to initiate call, but your demo quota has been used.",
                    "success": False,
                    "canUse": False
                }), 500
                
        except requests.exceptions.RequestException as e:
            # Update status to failed but don't allow retry
            demo_usage.status = 'failed'
            db.session.commit()
            
            return jsonify({
                "message": "Network error occurred, but your demo quota has been used.",
                "success": False,
                "canUse": False,
                "error": str(e)
            }), 500
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            "message": "An unexpected error occurred",
            "error": str(e)
        }), 500

# Endpoint to get user's demo usage history (optional)
@app.route('/api/user/demo-history', methods=['GET'])
@jwt_required()
def get_demo_history():
    try:
        current_user_id = get_jwt_identity()
        
        demo_usages = DemoUsage.query.filter_by(user_id=current_user_id).order_by(DemoUsage.created_at.desc()).all()
        
        history = []
        for usage in demo_usages:
            history.append({
                'demoType': usage.demo_type,
                'status': usage.status,
                'phoneNumber': usage.phone_number[-4:] if usage.phone_number else None,  # Only show last 4 digits
                'usedAt': usage.created_at.isoformat()
            })
        
        return jsonify({
            'history': history,
            'totalDemosUsed': len(history)
        }), 200
        
    except Exception as e:
        return jsonify({"message": "Error fetching demo history", "error": str(e)}), 500



# Add this to your main.py

# New endpoint to check if user can use chatbot demo
@app.route('/api/chatbot/check-eligibility', methods=['GET'])
@jwt_required()
def check_chatbot_eligibility():
    try:
        current_user_id = get_jwt_identity()
        user = Users.query.get(current_user_id)
        
        if not user:
            return jsonify({"message": "User not found"}), 404
        
        # Check if user has used chatbot demo
        chatbot_usage = DemoUsage.query.filter_by(
            user_id=current_user_id,
            demo_type='chatbot'
        ).first()
        
        if chatbot_usage:
            has_used = True
            can_use = chatbot_usage.message_count < 3  # Allow up to 3 messages
            message_count = chatbot_usage.message_count
        else:
            has_used = False
            can_use = True
            message_count = 0
        
        return jsonify({
            "canUse": can_use,
            "hasUsedDemo": has_used,
            "messageCount": message_count,
            "maxMessages": 3
        }), 200
        
    except Exception as e:
        return jsonify({"message": "Error checking eligibility", "error": str(e)}), 500

# New endpoint to send chatbot message with restrictions
@app.route('/api/chatbot/send-message', methods=['POST'])
@jwt_required()
def send_chatbot_message():
    try:
        current_user_id = get_jwt_identity()
        user = Users.query.get(current_user_id)
        
        if not user:
            return jsonify({"message": "User not found"}), 404
        
        data = request.get_json()
        message = data.get('message')
        prompt = data.get('prompt')
        session_id = data.get('sessionId')
        
        if not message:
            return jsonify({"message": "Message is required"}), 400
        
        # Check existing usage
        chatbot_usage = DemoUsage.query.filter_by(
            user_id=current_user_id,
            demo_type='chatbot'
        ).first()
        
        if chatbot_usage:
            if chatbot_usage.message_count >= 3:
                return jsonify({
                    "message": "You have reached your 3-message limit for the chatbot demo.",
                    "canUse": False
                }), 403
            
            # Increment message count
            chatbot_usage.message_count += 1
            chatbot_usage.updated_at = datetime.utcnow()
        else:
            # Create new usage record
            chatbot_usage = DemoUsage(
                user_id=current_user_id,
                demo_type='chatbot',
                status='active',
                message_count=1
            )
            db.session.add(chatbot_usage)
        
        db.session.commit()
        
        # Here you can integrate with your AI service or return a mock response
        # For now, returning a simple response
        response_text = f"Thank you for your message: '{message}'. This is a demo response from your configured chatbot."
        
        return jsonify({
            "response": response_text,
            "messageCount": chatbot_usage.message_count,
            "canUse": chatbot_usage.message_count < 3
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            "message": "An error occurred while processing your message",
            "error": str(e)
        }), 500





if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("DEBUG", False))