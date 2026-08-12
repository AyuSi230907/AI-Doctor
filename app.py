import os
import json
import uuid
from datetime import datetime

from flask import Flask, render_template, redirect, url_for, request, flash, abort, jsonify
from flask_login import (
    LoginManager, login_user, logout_user, login_required, current_user
)
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

from models import db, User, GuardianLink, HospitalLink, Report, Alert
from extract import extract_text
from ai_analysis import analyze_report

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXT = {"pdf", "png", "jpg", "jpeg", "webp", "bmp", "tiff", "txt"}

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "ai_doctor.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB uploads
app.config["EMERGENCY_NUMBER"] = os.environ.get("EMERGENCY_NUMBER", "112")

db.init_app(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


def role_required(*roles):
    def wrapper(view_func):
        from functools import wraps

        @wraps(view_func)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return login_manager.unauthorized()
            if current_user.role not in roles:
                abort(403)
            return view_func(*args, **kwargs)
        return wrapped
    return wrapper


# ---------------------------------------------------------------- landing

@app.route("/")
def index():
    return render_template("landing.html")


# ---------------------------------------------------------------- auth

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        role = request.form.get("role", "patient")

        if role not in ("patient", "guardian", "hospital"):
            role = "patient"

        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return render_template("signup.html", form=request.form)
        if password != confirm:
            flash("Passwords do not match.", "error")
            return render_template("signup.html", form=request.form)
        if User.query.filter_by(email=email).first():
            flash("An account with this email already exists. Try logging in.", "error")
            return render_template("signup.html", form=request.form)

        user = User(name=name, email=email, role=role, phone=request.form.get("phone", "").strip())
        user.set_password(password)

        if role == "patient":
            user.dob = request.form.get("dob", "")
            user.blood_group = request.form.get("blood_group", "")
            user.emergency_contact_name = request.form.get("emergency_contact_name", "")
            user.emergency_contact_phone = request.form.get("emergency_contact_phone", "")
        elif role == "hospital":
            user.hospital_name = request.form.get("hospital_name", "")
            user.hospital_reg_no = request.form.get("hospital_reg_no", "")

        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash("Account created. Welcome to AI Doctor.", "success")
        return redirect(url_for("dashboard"))

    return render_template("signup.html", form={})


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            flash("No matching account found. Check your details or sign up.", "error")
            return render_template("login.html")
        login_user(user)
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))


# ---------------------------------------------------------------- dashboard router

@app.route("/dashboard")
@login_required
def dashboard():
    if current_user.role == "patient":
        return redirect(url_for("patient_dashboard"))
    elif current_user.role == "guardian":
        return redirect(url_for("guardian_dashboard"))
    elif current_user.role == "hospital":
        return redirect(url_for("hospital_dashboard"))
    abort(403)


# ---------------------------------------------------------------- patient

@app.route("/patient/dashboard")
@role_required("patient")
def patient_dashboard():
    reports = Report.query.filter_by(patient_id=current_user.id).order_by(Report.created_at.desc()).all()
    guardians = GuardianLink.query.filter_by(patient_id=current_user.id).all()
    hospitals = HospitalLink.query.filter_by(patient_id=current_user.id).all()
    return render_template("patient_dashboard.html", reports=reports, guardians=guardians, hospitals=hospitals)


@app.route("/patient/upload", methods=["GET", "POST"])
@role_required("patient")
def patient_upload():
    if request.method == "POST":
        file = request.files.get("report_file")
        if not file or file.filename == "":
            flash("Please choose a file to upload.", "error")
            return redirect(url_for("patient_upload"))
        if not allowed_file(file.filename):
            flash("Unsupported file type. Upload PDF, image, or TXT.", "error")
            return redirect(url_for("patient_upload"))

        safe_name = secure_filename(file.filename)
        unique_name = f"{uuid.uuid4().hex}_{safe_name}"
        filepath = os.path.join(UPLOAD_DIR, unique_name)
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        file.save(filepath)

        report = Report(
            patient_id=current_user.id,
            uploaded_by_id=current_user.id,
            filename=safe_name,
            filepath=os.path.join("static", "uploads", unique_name),
            analysis_status="pending",
        )
        db.session.add(report)
        db.session.commit()

        run_analysis(report)

        return redirect(url_for("report_detail", report_id=report.id))

    return render_template("patient_upload.html")


def run_analysis(report):
    """Extracts text and runs the Claude analysis, saving results onto the report."""
    text = extract_text(os.path.join(BASE_DIR, report.filepath))
    report.extracted_text = text

    result = analyze_report(text)

    if result.get("error"):
        report.analysis_status = "failed"
        report.summary = result["error"]
        report.raw_ai_response = result.get("raw_response", "")
    else:
        report.analysis_status = "done"
        report.summary = result["summary"]
        report.risk_level = result["risk_level"]
        report.possible_conditions = json.dumps(result["possible_conditions"])
        report.suggestions = json.dumps(result["suggestions"])
        report.red_flags = json.dumps(result["red_flags"])
        report.raw_ai_response = result.get("raw_response", "")

    db.session.commit()

    # Auto-alert guardians & hospital if risk is medium/high or red flags exist
    if result.get("risk_level") in ("medium", "high") or result.get("red_flags"):
        msg = f"New report for {report.patient.name} flagged {result.get('risk_level', 'medium')} risk."
        alert = Alert(patient_id=report.patient_id, report_id=report.id, kind="risk_flag", message=msg)
        db.session.add(alert)
        db.session.commit()


@app.route("/patient/report/<int:report_id>")
@login_required
def report_detail(report_id):
    report = db.session.get(Report, report_id)
    if not report:
        abort(404)

    # Access control: the patient themself, their linked guardians, or linked hospitals
    is_owner = current_user.id == report.patient_id
    is_guardian = current_user.role == "guardian" and GuardianLink.query.filter_by(
        guardian_id=current_user.id, patient_id=report.patient_id).first()
    is_hospital = current_user.role == "hospital" and HospitalLink.query.filter_by(
        hospital_id=current_user.id, patient_id=report.patient_id).first()

    if not (is_owner or is_guardian or is_hospital):
        abort(403)

    conditions = json.loads(report.possible_conditions) if report.possible_conditions else []
    suggestions = json.loads(report.suggestions) if report.suggestions else []
    red_flags = json.loads(report.red_flags) if report.red_flags else []

    return render_template(
        "report_detail.html",
        report=report,
        conditions=conditions,
        suggestions=suggestions,
        red_flags=red_flags,
        viewer_role=current_user.role,
    )


@app.route("/patient/link", methods=["GET", "POST"])
@role_required("patient")
def link_guardian():
    if request.method == "POST":
        link_type = request.form.get("link_type")
        email = request.form.get("email", "").strip().lower()
        target = User.query.filter_by(email=email).first()

        if link_type == "guardian":
            if not target or target.role != "guardian":
                flash("No guardian account found with that email.", "error")
            elif GuardianLink.query.filter_by(guardian_id=target.id, patient_id=current_user.id).first():
                flash("Already linked with this guardian.", "error")
            else:
                db.session.add(GuardianLink(
                    guardian_id=target.id, patient_id=current_user.id,
                    relation=request.form.get("relation", "")
                ))
                db.session.commit()
                flash(f"Linked with guardian {target.name}.", "success")
        elif link_type == "hospital":
            if not target or target.role != "hospital":
                flash("No hospital account found with that email.", "error")
            elif HospitalLink.query.filter_by(hospital_id=target.id, patient_id=current_user.id).first():
                flash("Already linked with this hospital.", "error")
            else:
                db.session.add(HospitalLink(hospital_id=target.id, patient_id=current_user.id))
                db.session.commit()
                flash(f"Linked with hospital {target.hospital_name or target.name}.", "success")

        return redirect(url_for("link_guardian"))

    guardians = GuardianLink.query.filter_by(patient_id=current_user.id).all()
    hospitals = HospitalLink.query.filter_by(patient_id=current_user.id).all()
    return render_template("link_guardian.html", guardians=guardians, hospitals=hospitals)


@app.route("/patient/emergency", methods=["POST"])
@role_required("patient")
def trigger_emergency():
    guardians = GuardianLink.query.filter_by(patient_id=current_user.id).all()
    hospitals = HospitalLink.query.filter_by(patient_id=current_user.id).all()

    msg = f"{current_user.name} triggered an EMERGENCY alert."
    for g in guardians:
        db.session.add(Alert(patient_id=current_user.id, kind="emergency", message=msg))
    for h in hospitals:
        db.session.add(Alert(patient_id=current_user.id, kind="emergency", message=msg))
    if not guardians and not hospitals:
        db.session.add(Alert(patient_id=current_user.id, kind="emergency", message=msg))
    db.session.commit()

    return jsonify({
        "ok": True,
        "emergency_number": app.config["EMERGENCY_NUMBER"],
        "contact_name": current_user.emergency_contact_name,
        "contact_phone": current_user.emergency_contact_phone,
    })


# ---------------------------------------------------------------- guardian

@app.route("/guardian/dashboard")
@role_required("guardian")
def guardian_dashboard():
    links = GuardianLink.query.filter_by(guardian_id=current_user.id).all()
    patient_ids = [l.patient_id for l in links]
    alerts = Alert.query.filter(Alert.patient_id.in_(patient_ids)).order_by(Alert.created_at.desc()).limit(20).all() if patient_ids else []
    latest_reports = {}
    for pid in patient_ids:
        r = Report.query.filter_by(patient_id=pid).order_by(Report.created_at.desc()).first()
        if r:
            latest_reports[pid] = r
    return render_template("guardian_dashboard.html", links=links, alerts=alerts, latest_reports=latest_reports)


@app.route("/guardian/patient/<int:patient_id>")
@role_required("guardian")
def guardian_patient(patient_id):
    link = GuardianLink.query.filter_by(guardian_id=current_user.id, patient_id=patient_id).first()
    if not link:
        abort(403)
    patient = db.session.get(User, patient_id)
    reports = Report.query.filter_by(patient_id=patient_id).order_by(Report.created_at.desc()).all()
    return render_template("guardian_patient.html", patient=patient, reports=reports)


# ---------------------------------------------------------------- hospital

@app.route("/hospital/dashboard")
@role_required("hospital")
def hospital_dashboard():
    links = HospitalLink.query.filter_by(hospital_id=current_user.id).all()
    patient_ids = [l.patient_id for l in links]
    alerts = Alert.query.filter(Alert.patient_id.in_(patient_ids)).order_by(Alert.created_at.desc()).limit(20).all() if patient_ids else []
    latest_reports = {}
    for pid in patient_ids:
        r = Report.query.filter_by(patient_id=pid).order_by(Report.created_at.desc()).first()
        if r:
            latest_reports[pid] = r
    return render_template("hospital_dashboard.html", links=links, alerts=alerts, latest_reports=latest_reports)


@app.route("/hospital/patient/<int:patient_id>")
@role_required("hospital")
def hospital_patient(patient_id):
    link = HospitalLink.query.filter_by(hospital_id=current_user.id, patient_id=patient_id).first()
    if not link:
        abort(403)
    patient = db.session.get(User, patient_id)
    reports = Report.query.filter_by(patient_id=patient_id).order_by(Report.created_at.desc()).all()
    return render_template("hospital_patient.html", patient=patient, reports=reports)


# ---------------------------------------------------------------- misc

@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", code=403, message="You don't have access to this page."), 403


@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404, message="Page not found."), 404


with app.app_context():
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    db.create_all()


if __name__ == "__main__":
    app.run(debug=True)
