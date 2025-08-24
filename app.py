from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from functools import wraps
import mysql.connector
import os
from datetime import datetime, timedelta

app = Flask(__name__, template_folder="templates")
app.secret_key = os.getenv("FLASK_SECRET", "change-this")

# In-memory storage for reservations (since we don't have a reservations table)
reservations = {}

def get_conn():
    return mysql.connector.connect(host = "localhost", user = "root", password = "admin1234", database = "hackathon")

def login_required(f):
    @wraps(f)
    def wrap(*a, **k):
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*a, **k)
    return wrap

# ======== PAGES (use your existing templates unchanged) ========

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html", error=None)

    # accept common field names from your form
    reg_no = (request.form.get("reg_no")
              or request.form.get("registration_number")
              or request.form.get("reg") or "").strip()
    full_name = (request.form.get("name")
                 or request.form.get("full_name")
                 or request.form.get("fullname") or "").strip()

    if not reg_no:
        return render_template("login.html", error="Enter your Reg Number")

    conn = get_conn(); cur = conn.cursor(dictionary=True)
    cur.execute("SELECT reg_no, name FROM customers WHERE reg_no=%s", (reg_no,))
    row = cur.fetchone()

    # if not found, create using the Full Name once, then login
    if not row:
        if not full_name:
            cur.close(); conn.close()
            return render_template("login.html", error="New user. Please enter Full Name once.")
        cur.execute("INSERT INTO customers (reg_no, name) VALUES (%s, %s)", (reg_no, full_name))
        conn.commit()
        row = {"reg_no": reg_no, "name": full_name}

    cur.close(); conn.close()
    session["user"] = row
    # send them straight to the seats page after login
    return redirect(url_for("seats_page"))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
@login_required
def home():
    if "user" not in session:
        return redirect(url_for("login"))
    return render_template("home.html", user_info=session["user"])

@app.route("/about")
@login_required
def about():
    return render_template("home.html", user_info=session["user"])

@app.route("/seats")
@login_required
def seats_page():
    if "user" not in session:
        return redirect(url_for("login"))
    return render_template("seat_matrix.html", user_info=session["user"])

# ======== APIs your frontend already calls ========

# Return seats (optionally `?floor=0/1/2/3`)
@app.get("/api/seats")
def api_get_seats():
    floor = request.args.get("floor")
    conn = get_conn(); cur = conn.cursor(dictionary=True)

    if floor is None or floor == "":
        cur.execute("""
            SELECT id, floor, seat_no, socket, occupied, updated_at
            FROM seats
            ORDER BY floor, seat_no
        """)
    else:
        cur.execute("""
            SELECT id, floor, seat_no, socket, occupied, updated_at
            FROM seats
            WHERE floor=%s
            ORDER BY seat_no
        """, (floor,))

    data = cur.fetchall()
    cur.close(); conn.close()
    # send exactly what the frontend expects: JSON with "seats"
    return jsonify({"seats": data})

# Update one seat's values (send only fields you want to change)
# body: {"seat_id": 12, "occupied": true} or {"seat_id": 12, "socket": false}
@app.post("/api/seats/update")
def api_update_seat():
    payload = request.get_json(force=True) or {}
    seat_id = payload.get("seat_id")
    socket = payload.get("socket")
    occupied = payload.get("occupied")

    if not seat_id:
        return jsonify({"ok": False, "error": "seat_id required"}), 400

    sets, vals = [], []
    if socket is not None:
        sets.append("socket=%s")
        vals.append(1 if socket else 0)
    if occupied is not None:
        sets.append("occupied=%s")
        vals.append(1 if occupied else 0)
    if not sets:
        return jsonify({"ok": False, "error": "nothing to update"}), 400

    sets.append("updated_at=NOW()")
    sql = f"UPDATE seats SET {', '.join(sets)} WHERE id=%s"
    vals.append(int(seat_id))

    conn = get_conn(); cur = conn.cursor()
    cur.execute(sql, tuple(vals))
    conn.commit()
    cur.close(); conn.close()
    return jsonify({"ok": True})

# ======== RESERVATION ENDPOINTS (using in-memory storage) ========

@app.post("/reserve-seat")
@login_required
def reserve_seat():
    payload = request.get_json(force=True) or {}
    seat_number = payload.get("seat_number")
    floor = payload.get("floor")
    user_name = payload.get("user_name")
    
    if not all([seat_number, floor, user_name]):
        return jsonify({"success": False, "message": "Missing required fields"}), 400
    
    seat_id = f"{floor}_{seat_number}"
    
    # Check if user already has a reservation
    for existing_seat_id, reservation in reservations.items():
        if reservation["user_name"] == user_name and reservation["expires_at"] > datetime.now():
            return jsonify({
                "success": False, 
                "message": f"You already have a reservation for seat {reservation['seat_number']} on {reservation['floor']}",
                "existing_reservation": True
            }), 400
    
    # Check if seat is already reserved
    if seat_id in reservations and reservations[seat_id]["expires_at"] > datetime.now():
        return jsonify({
            "success": False, 
            "message": f"Seat {seat_number} is already reserved"
        }), 400
    
    # Create reservation (10 minutes expiry)
    expires_at = datetime.now() + timedelta(minutes=10)
    reservations[seat_id] = {
        "seat_id": seat_id,
        "seat_number": seat_number,
        "floor": floor,
        "user_name": user_name,
        "expires_at": expires_at
    }
    
    return jsonify({
        "success": True,
        "message": f"Seat {seat_number} reserved successfully for 10 minutes",
        "expires_at": expires_at.isoformat()
    })

@app.post("/cancel-reservation")
@login_required
def cancel_reservation():
    payload = request.get_json(force=True) or {}
    seat_id = payload.get("seat_id")
    user_name = payload.get("user_name")
    
    if not all([seat_id, user_name]):
        return jsonify({"success": False, "message": "Missing required fields"}), 400
    
    # Check if reservation exists and belongs to user
    if seat_id in reservations and reservations[seat_id]["user_name"] == user_name:
        del reservations[seat_id]
        return jsonify({"success": True, "message": "Reservation cancelled successfully"})
    else:
        return jsonify({"success": False, "message": "Reservation not found"}), 404

@app.get("/get-user-reservation")
@login_required
def get_user_reservation():
    user_name = session["user"]["name"]
    
    # Find user's active reservation
    for seat_id, reservation in reservations.items():
        if reservation["user_name"] == user_name and reservation["expires_at"] > datetime.now():
            return jsonify({
                "success": True,
                "reservation": {
                    "seat_id": reservation["seat_id"],
                    "seat_number": reservation["seat_number"],
                    "floor": reservation["floor"],
                    "user_name": reservation["user_name"],
                    "expires_at": reservation["expires_at"].isoformat()
                }
            })
    
    return jsonify({"success": False})

# Error handler for template errors
@app.errorhandler(500)
def internal_error(error):
    return f"Internal Server Error: {error}", 500

@app.errorhandler(404)
def not_found_error(error):
    return "Page not found", 404

# Simple health check
@app.get("/healthz")
def healthz():
    try:
        conn = get_conn(); conn.close()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

if __name__ == "__main__":
    # runs on 5000 so your existing links keep working
    app.run(host="0.0.0.0", port=5000, debug=True)
