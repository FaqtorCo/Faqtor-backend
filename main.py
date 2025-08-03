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
        print(f"DEBUG: Raw user_id from JWT: {current_user_id}")
        print(f"DEBUG: Type of user_id: {type(current_user_id)}")
        
        # Convert to int if it's a string
        try:
            user_id_int = int(current_user_id)
            print(f"DEBUG: Converted user_id to int: {user_id_int}")
        except (ValueError, TypeError):
            print(f"DEBUG: Could not convert user_id to int")
            user_id_int = current_user_id
        
        user = Users.query.get(user_id_int)
        
        if not user:
            print(f"DEBUG: User not found for id: {user_id_int}")
            return jsonify({"message": "User not found"}), 404
        
        print(f"DEBUG: User found: {user.email}, ID: {user.id}")
        
        # Check if user has used chatbot demo
        chatbot_usage = DemoUsage.query.filter_by(
            user_id=user_id_int,  # Use the converted int
            demo_type='chatbot'
        ).first()
        
        print(f"DEBUG: Chatbot usage found: {chatbot_usage}")
        if chatbot_usage:
            print(f"DEBUG: Usage details - message_count: {chatbot_usage.message_count}, status: {chatbot_usage.status}, created_at: {chatbot_usage.created_at}")
        
        # Also check ALL demo usages for this user
        all_usages = DemoUsage.query.filter_by(user_id=user_id_int).all()
        print(f"DEBUG: All demo usages for user: {len(all_usages)}")
        for usage in all_usages:
            print(f"DEBUG: Usage - demo_type: {usage.demo_type}, message_count: {usage.message_count}, status: {usage.status}")
        
        if chatbot_usage:
            has_used = True
            can_use = chatbot_usage.message_count < 3  # Allow up to 3 messages
            message_count = chatbot_usage.message_count
        else:
            has_used = False
            can_use = True
            message_count = 0
        
        result = {
            "canUse": can_use,
            "hasUsedDemo": has_used,
            "messageCount": message_count,
            "maxMessages": 3
        }
        
        print(f"DEBUG: Returning result: {result}")
        
        return jsonify(result), 200
        
    except Exception as e:
        print(f"DEBUG: Exception in check_chatbot_eligibility: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"message": "Error checking eligibility", "error": str(e)}), 500
    

# New endpoint to send chatbot message with restrictions
# Add this function outside of any route, near the top of your file after imports
def generate_fallback_response(message, prompt):
    """Generate a contextual fallback response based on the prompt"""
    if not prompt:
        return "I understand your question. Let me help you with that!"
    
    # Extract business type/context from prompt for better fallback responses
    message_lower = message.lower()
    prompt_lower = prompt.lower()
    
    # Common business response patterns
    if any(word in message_lower for word in ['hours', 'open', 'close', 'time']):
        if 'bakery' in prompt_lower:
            return "We're typically open Monday-Saturday 6AM-7PM, Sunday 7AM-5PM, but please check our current hours as they may vary."
        elif 'restaurant' in prompt_lower:
            return "We're usually open Tuesday-Sunday 5PM-10PM, closed Mondays, but please verify our current hours."
        else:
            return "I'd be happy to help with our hours. Please check our website or call us for the most current operating hours."
    
    elif any(word in message_lower for word in ['price', 'cost', 'how much', 'pricing']):
        return "I'd be happy to help with pricing information. Our rates vary depending on your specific needs. Would you like me to connect you with someone who can provide detailed pricing?"
    
    elif any(word in message_lower for word in ['location', 'address', 'where']):
        return "I can help you find our location. Please visit our website or contact us directly for our current address and directions."
    
    elif any(word in message_lower for word in ['services', 'offer', 'provide', 'do']):
        if 'bakery' in prompt_lower:
            return "We offer fresh baked goods, custom cakes, artisanal breads, and seasonal pastries. We also provide cake decorating classes and take custom orders."
        elif 'tech' in prompt_lower or 'software' in prompt_lower:
            return "We provide technical support, software solutions, and troubleshooting services. How can I assist you with your specific technical needs?"
        elif 'restaurant' in prompt_lower:
            return "We specialize in farm-to-table cuisine with seasonal menus, private dining, wine pairings, and Sunday brunch. We focus on local, organic ingredients."
        else:
            return "We offer a range of services tailored to meet your needs. Could you tell me more about what you're looking for?"
    
    else:
        return "Thank you for your question. I'm here to help! Could you provide a bit more detail about what you're looking for?"


# Replace your existing /api/chatbot/send-message endpoint with this:
@app.route('/api/chatbot/send-message', methods=['POST'])
@jwt_required()
def send_chatbot_message():
    try:
        current_user_id = get_jwt_identity()
        print(f"DEBUG: send_chatbot_message - user_id: {current_user_id}")
        
        # Convert to int if it's a string
        try:
            user_id_int = int(current_user_id)
        except (ValueError, TypeError):
            user_id_int = current_user_id
        
        user = Users.query.get(user_id_int)
        
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
            user_id=user_id_int,  # Use the converted int
            demo_type='chatbot'
        ).first()
        
        print(f"DEBUG: send_chatbot_message - existing usage: {chatbot_usage}")
        
        if chatbot_usage:
            if chatbot_usage.message_count >= 3:
                return jsonify({
                    "message": "You have reached your 3-message limit for the chatbot demo.",
                    "canUse": False
                }), 403
            
            # Increment message count
            chatbot_usage.message_count += 1
            chatbot_usage.updated_at = datetime.utcnow()
            print(f"DEBUG: Incremented message count to: {chatbot_usage.message_count}")
        else:
            # Create new usage record
            chatbot_usage = DemoUsage(
                user_id=user_id_int,  # Use the converted int
                demo_type='chatbot',
                status='active',
                message_count=1
            )
            db.session.add(chatbot_usage)
            print(f"DEBUG: Created new usage record")
        
        db.session.commit()
        
        # Rest of your function remains the same...
        # [Continue with the webhook call logic]
        
    except Exception as e:
        print(f"DEBUG: Exception in send_chatbot_message: {str(e)}")
        import traceback
        traceback.print_exc()
        db.session.rollback()
        return jsonify({
            "message": "An error occurred while processing your message",
            "error": str(e)
        }), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("DEBUG", False))