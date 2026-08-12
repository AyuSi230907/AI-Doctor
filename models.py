from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # patient | guardian | hospital
    phone = db.Column(db.String(20))

    # Extra fields, only relevant depending on role
    dob = db.Column(db.String(20))              # patient
    blood_group = db.Column(db.String(6))        # patient
    emergency_contact_name = db.Column(db.String(120))   # patient
    emergency_contact_phone = db.Column(db.String(20))   # patient
    hospital_name = db.Column(db.String(160))     # hospital
    hospital_reg_no = db.Column(db.String(80))    # hospital

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class GuardianLink(db.Model):
    """Links a guardian account to a patient account."""
    __tablename__ = "guardian_links"

    id = db.Column(db.Integer, primary_key=True)
    guardian_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    patient_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    relation = db.Column(db.String(60))  # e.g. Parent, Spouse, Sibling
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    guardian = db.relationship("User", foreign_keys=[guardian_id])
    patient = db.relationship("User", foreign_keys=[patient_id])


class HospitalLink(db.Model):
    """Links a hospital account to a patient account."""
    __tablename__ = "hospital_links"

    id = db.Column(db.Integer, primary_key=True)
    hospital_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    patient_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    hospital = db.relationship("User", foreign_keys=[hospital_id])
    patient = db.relationship("User", foreign_keys=[patient_id])


class Report(db.Model):
    __tablename__ = "reports"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    filename = db.Column(db.String(255), nullable=False)
    filepath = db.Column(db.String(500), nullable=False)

    extracted_text = db.Column(db.Text)

    # AI analysis output
    analysis_status = db.Column(db.String(20), default="pending")  # pending|done|failed
    risk_level = db.Column(db.String(10))       # low|medium|high
    summary = db.Column(db.Text)
    possible_conditions = db.Column(db.Text)    # JSON string
    suggestions = db.Column(db.Text)            # JSON string
    red_flags = db.Column(db.Text)              # JSON string
    raw_ai_response = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    patient = db.relationship("User", foreign_keys=[patient_id])
    uploaded_by = db.relationship("User", foreign_keys=[uploaded_by_id])


class Alert(db.Model):
    """Created automatically when a report comes back medium/high risk,
    or when a patient manually triggers the Emergency button."""
    __tablename__ = "alerts"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    report_id = db.Column(db.Integer, db.ForeignKey("reports.id"), nullable=True)
    kind = db.Column(db.String(20), nullable=False)  # risk_flag | emergency
    message = db.Column(db.String(500), nullable=False)
    acknowledged = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    patient = db.relationship("User", foreign_keys=[patient_id])
    report = db.relationship("Report", foreign_keys=[report_id])
