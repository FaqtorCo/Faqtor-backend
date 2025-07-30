from flask import Blueprint, jsonify

# Define a blueprint named 'main'
main = Blueprint('main', __name__)

@main.route('/api/hello', methods=['GET'])
def hello():
    return jsonify(message="Hello from the backend!")
