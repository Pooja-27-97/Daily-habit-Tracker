from datetime import date, timedelta
from functools import wraps
from flask import Flask, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
import json
import os

DATA_FILE = os.path.join(os.path.dirname(__file__), "habits.json")

app = Flask(__name__)
app.secret_key = "habit-tracker-secret-key"


def load_data():
    if not os.path.exists(DATA_FILE):
        default = {"users": []}
        save_data(default)
        return default

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    if "users" not in data:
        data = {
            "users": [],
            "legacy_habits": data.get("habits", []),
            "legacy_logs": data.get("logs", []),
        }

    for user in data.get("users", []):
        user.setdefault("habits", [])
        user.setdefault("logs", [])
        user.setdefault("created_at", get_today())
        for habit in user["habits"]:
            habit.setdefault("description", "")

    data.setdefault("legacy_habits", [])
    data.setdefault("legacy_logs", [])
    return data


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_today():
    return date.today().isoformat()


def get_last_dates(days=7, start_date=None):
    today = date.today()
    start = today - timedelta(days=days - 1)
    if start_date:
        start = max(start, start_date)
    span = (today - start).days
    return [
        (start + timedelta(days=i)).isoformat()
        for i in range(span + 1)
    ]


def get_user_by_id(data, user_id):
    for user in data["users"]:
        if user["id"] == user_id:
            return user
    return None


def get_user_by_email(data, email):
    email = email.strip().lower()
    for user in data["users"]:
        if user["email"].lower() == email:
            return user
    return None


def get_current_user(data):
    user_id = session.get("user_id")
    if user_id is None:
        return None
    return get_user_by_id(data, user_id)


def login_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)

    return wrapped_view


def habit_done_on(user, habit_id, target_date):
    for log in user["logs"]:
        if log["habit_id"] == habit_id and log["date"] == target_date:
            return log["done"]
    return False


def set_habit_done(user, habit_id, target_date, done):
    for log in user["logs"]:
        if log["habit_id"] == habit_id and log["date"] == target_date:
            log["done"] = done
            return
    user["logs"].append({"date": target_date, "habit_id": habit_id, "done": done})


def compute_streak_for_habit(user, habit_id):
    streak = 0
    current = date.today()
    while True:
        day_str = current.isoformat()
        if habit_done_on(user, habit_id, day_str):
            streak += 1
            current -= timedelta(days=1)
        else:
            break
    return streak


def update_all_streaks(user):
    for habit in user["habits"]:
        habit["streak"] = compute_streak_for_habit(user, habit["id"])


def get_habit_by_id(user, habit_id):
    for habit in user["habits"]:
        if habit["id"] == habit_id:
            return habit
    return None


def get_next_habit_id(user):
    return max((habit["id"] for habit in user["habits"]), default=0) + 1


def build_habit_list(user, target_date):
    habits = []
    completed = 0
    for habit in sorted(user["habits"], key=lambda h: h["id"]):
        done = habit_done_on(user, habit["id"], target_date)
        if done:
            completed += 1
        habits.append(
            {
                "id": habit["id"],
                "name": habit["name"],
                "description": habit.get("description", ""),
                "streak": habit.get("streak", 0),
                "done": done,
            }
        )
    total = len(habits)
    percent = int((completed / total) * 100) if total else 0
    return habits, completed, total, percent


def get_history(user, days=7):
    created_at = date.fromisoformat(user.get("created_at", get_today()))
    dates = get_last_dates(days, start_date=created_at)
    habits = sorted(user["habits"], key=lambda h: h["id"])
    rows = []
    for habit in habits:
        row = {
            "name": habit["name"],
            "description": habit.get("description", ""),
            "streak": habit.get("streak", 0),
            "statuses": [habit_done_on(user, habit["id"], day) for day in dates],
        }
        rows.append(row)
    daily_counts = [
        sum(1 for habit in habits if habit_done_on(user, habit["id"], day))
        for day in dates
    ]
    return dates, rows, daily_counts


def create_user(data, name, email, dob, gender, password):
    user = {
        "id": max((user["id"] for user in data["users"]), default=0) + 1,
        "name": name,
        "email": email.strip().lower(),
        "dob": dob,
        "gender": gender,
        "created_at": get_today(),
        "password_hash": generate_password_hash(password),
        "habits": [],
        "logs": [],
    }

    if not data["users"] and data.get("legacy_habits"):
        user["habits"] = data.pop("legacy_habits", [])
        user["logs"] = data.pop("legacy_logs", [])

    data["users"].append(user)
    return user


@app.context_processor
def inject_user():
    data = load_data()
    return {"current_user": get_current_user(data)}


@app.route("/")
def index():
    data = load_data()
    user = get_current_user(data)
    if user is None:
        return redirect(url_for("login"))

    update_all_streaks(user)
    save_data(data)
    today = get_today()
    habits, completed, total, percent = build_habit_list(user, today)
    return render_template(
        "index.html",
        page="home",
        habits=habits,
        today=today,
        completed=completed,
        total=total,
        percent=percent,
    )


@app.route("/signup", methods=["GET", "POST"])
def signup():
    data = load_data()
    if session.get("user_id"):
        return redirect(url_for("index"))

    error = ""
    form_data = {
        "name": "",
        "email": "",
        "dob": "",
        "gender": "",
    }

    if request.method == "POST":
        form_data = {
            "name": request.form.get("name", "").strip(),
            "email": request.form.get("email", "").strip(),
            "dob": request.form.get("dob", "").strip(),
            "gender": request.form.get("gender", "").strip(),
        }
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not all(form_data.values()) or not password or not confirm_password:
            error = "Please fill in all fields."
        elif get_user_by_email(data, form_data["email"]):
            error = "An account with this email already exists."
        elif password != confirm_password:
            error = "Passwords do not match."
        else:
            user = create_user(
                data,
                form_data["name"],
                form_data["email"],
                form_data["dob"],
                form_data["gender"],
                password,
            )
            save_data(data)
            session["user_id"] = user["id"]
            return redirect(url_for("index"))

    return render_template(
        "signup.html",
        page="signup",
        error=error,
        form_data=form_data,
        min_dob="1980-01-01",
        max_dob=get_today(),
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    data = load_data()
    if session.get("user_id"):
        return redirect(url_for("index"))

    error = ""
    email = ""

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        user = get_user_by_email(data, email)

        if user is None or not check_password_hash(user["password_hash"], password):
            error = "Invalid email or password."
        else:
            session["user_id"] = user["id"]
            return redirect(url_for("index"))

    return render_template("login.html", page="login", error=error, email=email)


@app.route("/logout", methods=["POST"])
def logout():
    session.pop("user_id", None)
    return redirect(url_for("login"))


@app.route("/add", methods=["GET", "POST"])
@login_required
def add_habit():
    data = load_data()
    user = get_current_user(data)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        if name:
            user["habits"].append(
                {
                    "id": get_next_habit_id(user),
                    "name": name,
                    "description": description,
                    "streak": 0,
                }
            )
            save_data(data)
            return redirect(url_for("index"))

    habits = sorted(user["habits"], key=lambda h: h["id"])
    return render_template("add.html", page="add", habits=habits)


@app.route("/edit/<int:habit_id>", methods=["POST"])
@login_required
def edit_habit(habit_id):
    data = load_data()
    user = get_current_user(data)
    habit = get_habit_by_id(user, habit_id)
    redirect_to = request.form.get("redirect_to") or url_for("index")

    if habit is None:
        return redirect(redirect_to)

    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    if name:
        habit["name"] = name
        habit["description"] = description
        save_data(data)

    return redirect(redirect_to)


@app.route("/history")
@login_required
def history():
    data = load_data()
    user = get_current_user(data)
    update_all_streaks(user)
    save_data(data)
    dates, rows, daily_counts = get_history(user)
    total = len(user["habits"])
    date_totals = list(zip(dates, daily_counts))
    return render_template(
        "history.html",
        page="history",
        dates=dates,
        rows=rows,
        daily_counts=daily_counts,
        date_totals=date_totals,
        total=total,
    )


@app.route("/toggle", methods=["POST"])
@login_required
def toggle():
    data = load_data()
    user = get_current_user(data)
    today = get_today()
    habit_id = int(request.form.get("habit_id", 0))
    done = request.form.get("done") == "on"
    set_habit_done(user, habit_id, today, done)
    update_all_streaks(user)
    save_data(data)
    return redirect(url_for("index"))


@app.route("/delete/<int:habit_id>", methods=["POST"])
@login_required
def delete_habit(habit_id):
    data = load_data()
    user = get_current_user(data)
    user["habits"] = [habit for habit in user["habits"] if habit["id"] != habit_id]
    user["logs"] = [log for log in user["logs"] if log["habit_id"] != habit_id]
    save_data(data)
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True)
