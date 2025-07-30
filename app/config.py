class Config:
    SECRET_KEY = 'your_secret_key_here'  # Make sure to keep this safe
    SQLALCHEMY_DATABASE_URI = 'postgresql://postgres:1234@localhost/faqtor'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
