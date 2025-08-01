# app/models.py
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from datetime import datetime

db = SQLAlchemy()
bcrypt = Bcrypt()


class Users(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(128), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship to demo usage
    demo_usages = db.relationship('DemoUsage', backref='user', lazy=True)

    def set_password(self, password):
        """Hash and set password"""
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        """Check if provided password matches hash"""
        return bcrypt.check_password_hash(self.password_hash, password)
    
    def has_used_calling_agent(self):
        """Check if user has already used the calling agent demo"""
        return DemoUsage.query.filter_by(
            user_id=self.id, 
            demo_type='calling_agent'
        ).first() is not None

    def __repr__(self):
        return f'<User {self.name} - {self.email}>'


class DemoUsage(db.Model):
    __tablename__ = 'demo_usage'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    demo_type = db.Column(db.String(50), nullable=False)  # 'calling_agent', 'chatbot', etc.
    phone_number = db.Column(db.String(20), nullable=True)  # For calling agent
    message_count = db.Column(db.Integer, default=0)  # For chatbot message counting
    status = db.Column(db.String(20), default='initiated')  # initiated, completed, failed, active
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Add index for faster queries
    __table_args__ = (
        db.Index('idx_user_demo_type', 'user_id', 'demo_type'),
    )