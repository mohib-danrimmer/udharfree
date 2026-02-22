import os
import uuid
from datetime import datetime
from functools import wraps

import pandas as pd
from flask import (Flask, flash, jsonify, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "udharfree-dev-secret-2024")

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
MONGO_URI = os.environ.get("MONGO_URI")

client = MongoClient(MONGO_URI)
db = client["udharfree-db"]



# 3. Fetch all documents from the collections
users_collection = db["users"]
settlements_collection = db["settlements"]
expenses_collection = db["expenses"]
expense_splits_collection = db["expense_splits"]



# ---------------------------------------------------------------------------
# CSV initialisation - Entire Section Removed post migration to MonogDB
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# MongoDB helpers
# ---------------------------------------------------------------------------

def read_users() -> pd.DataFrame:
    cursor = users_collection.find({})
    return pd.DataFrame(list(cursor))


def read_expenses() -> pd.DataFrame:
    cursor = expenses_collection.find({})
    df = pd.DataFrame(list(cursor))
    if not df.empty:
        df["total_amount"] = df["total_amount"].astype(float)
    return df


def read_splits() -> pd.DataFrame:
    cursor = expense_splits_collection.find({})
    df = pd.DataFrame(list(cursor))
    if not df.empty:
        df["amount_owed"] = df["amount_owed"].astype(float)
    return df


def read_settlements() -> pd.DataFrame:
    cursor = settlements_collection.find({})
    df = pd.DataFrame(list(cursor))
    if not df.empty:
        df["amount"] = df["amount"].astype(float)
    return df


def new_id() -> str:
    return uuid.uuid4().hex[:8]


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def get_user(username: str):
    users = read_users()
    row = users[users["username"] == username]
    if row.empty:
        return None
    return row.iloc[0].to_dict()


# ---------------------------------------------------------------------------
# Balance calculation
# ---------------------------------------------------------------------------

def compute_balances(current_user: str) -> dict:
    """Return dict {username: amount} where positive = they owe me, negative = I owe them."""
    expenses = read_expenses()
    splits = read_splits()
    settlements = read_settlements()

    balances: dict = {}

    if not expenses.empty and not splits.empty:
        merged = splits.merge(expenses[["expense_id", "paid_by"]], on="expense_id", how="left")
        for _, row in merged.iterrows():
            payer = row["paid_by"]
            splitter = row["username"]
            amount = float(row["amount_owed"])

            if payer == current_user and splitter != current_user:
                balances[splitter] = balances.get(splitter, 0.0) + amount
            elif splitter == current_user and payer != current_user:
                balances[payer] = balances.get(payer, 0.0) - amount

    if not settlements.empty:
        for _, row in settlements.iterrows():
            amount = float(row["amount"])
            if row["from_user"] == current_user:
                to = row["to_user"]
                balances[to] = balances.get(to, 0.0) + amount
            elif row["to_user"] == current_user:
                frm = row["from_user"]
                balances[frm] = balances.get(frm, 0.0) - amount

    return balances


# ---------------------------------------------------------------------------
# Routes — Auth
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    if "username" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET"])
def login():
    if "username" in session:
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.route("/login", methods=["POST"])
def login_post():
    username = request.form.get("username", "").strip().lower()
    password = request.form.get("password", "")

    if not username or not password:
        flash("Username and password are required.", "error")
        return redirect(url_for("login"))

    user = get_user(username)
    if not user or not check_password_hash(user["password_hash"], password):
        flash("Invalid username or password.", "error")
        return redirect(url_for("login"))

    session["username"] = username
    session["display_name"] = user["display_name"]
    return redirect(url_for("dashboard"))


@app.route("/register", methods=["POST"])
def register():
    username = request.form.get("username", "").strip().lower()
    display_name = request.form.get("display_name", "").strip()
    password = request.form.get("password", "")
    confirm = request.form.get("confirm_password", "")

    if not username or not display_name or not password:
        flash("All fields are required.", "error")
        return redirect(url_for("login"))

    if password != confirm:
        flash("Passwords do not match.", "error")
        return redirect(url_for("login"))

    if len(password) < 4:
        flash("Password must be at least 4 characters.", "error")
        return redirect(url_for("login"))

    users = read_users()
    if not users.empty and username in users["username"].values:
        flash("Username already taken.", "error")
        return redirect(url_for("login"))

    # 1. Store your data in a standard Python dictionary
    new_user_document = {
        "username": username,
        "display_name": display_name,
        "password_hash": generate_password_hash(password),
        "created_at": now_str()
    }

    # 2. Insert the dictionary directly into the active MongoDB collection
    users_collection.insert_one(new_user_document)

    flash("Account created! Please log in.", "success")
    return redirect(url_for("login"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Routes — Dashboard
# ---------------------------------------------------------------------------

@app.route("/dashboard")
@login_required
def dashboard():
    current_user = session["username"]
    balances = compute_balances(current_user)

    users = read_users()
    user_map = {r["username"]: r["display_name"] for _, r in users.iterrows()}

    balance_list = []
    for uname, amount in balances.items():
        if abs(amount) < 0.005:
            continue
        balance_list.append({
            "username": uname,
            "display_name": user_map.get(uname, uname),
            "amount": round(amount, 2),
        })
    balance_list.sort(key=lambda x: abs(x["amount"]), reverse=True)

    total_owed_to_me = sum(b["amount"] for b in balance_list if b["amount"] > 0)
    total_i_owe = sum(-b["amount"] for b in balance_list if b["amount"] < 0)

    expenses = read_expenses()
    recent_expenses = []
    if not expenses.empty:
        expenses["created_at"] = pd.to_datetime(expenses["created_at"])
        expenses = expenses.sort_values("created_at", ascending=False)
        for _, row in expenses.iterrows():
            recent_expenses.append({
                "expense_id": row["expense_id"],
                "description": row["description"],
                "total_amount": round(float(row["total_amount"]), 2),
                "paid_by": user_map.get(row["paid_by"], row["paid_by"]),
                "created_at": row["created_at"].strftime("%d %b %Y"),
            })

    return render_template(
        "dashboard.html",
        balance_list=balance_list,
        total_owed_to_me=round(total_owed_to_me, 2),
        total_i_owe=round(total_i_owe, 2),
        recent_expenses=recent_expenses,
    )


# ---------------------------------------------------------------------------
# Routes — Add Expense
# ---------------------------------------------------------------------------

@app.route("/add-expense", methods=["GET"])
@login_required
def add_expense():
    users = read_users()
    all_users = [{"username": r["username"], "display_name": r["display_name"]}
                 for _, r in users.iterrows()]
    return render_template("add_expense.html", all_users=all_users, current_user=session["username"])


@app.route("/add-expense", methods=["POST"])
@login_required
def add_expense_post():
    description = request.form.get("description", "").strip()
    total_amount_str = request.form.get("total_amount", "").strip()
    paid_by = request.form.get("paid_by", "").strip()
    split_type = request.form.get("split_type", "equal")
    members = request.form.getlist("members")

    # Basic validation
    if not description:
        flash("Description is required.", "error")
        return redirect(url_for("add_expense"))

    try:
        total_amount = round(float(total_amount_str), 2)
        if total_amount <= 0:
            raise ValueError
    except ValueError:
        flash("Enter a valid positive amount.", "error")
        return redirect(url_for("add_expense"))

    if not paid_by:
        flash("Select who paid.", "error")
        return redirect(url_for("add_expense"))

    if not members:
        flash("Select at least one member.", "error")
        return redirect(url_for("add_expense"))

    # Ensure paid_by is in members
    if paid_by not in members:
        members.append(paid_by)

    # Compute splits
    splits = {}  # username -> amount_owed

    if split_type == "equal":
        per_person = round(total_amount / len(members), 2)
        remainder = round(total_amount - per_person * len(members), 2)
        for m in members:
            splits[m] = per_person
        splits[paid_by] = round(splits[paid_by] + remainder, 2)

    elif split_type == "percentage":
        total_pct = 0.0
        pct_map = {}
        for m in members:
            pct_str = request.form.get(f"pct_{m}", "0")
            try:
                pct = float(pct_str)
            except ValueError:
                pct = 0.0
            pct_map[m] = pct
            total_pct += pct
        if abs(total_pct - 100.0) > 0.01:
            flash(f"Percentages must sum to 100% (got {total_pct:.2f}%).", "error")
            return redirect(url_for("add_expense"))
        for m in members:
            splits[m] = round(total_amount * pct_map[m] / 100.0, 2)

    elif split_type == "exact":
        total_exact = 0.0
        for m in members:
            amt_str = request.form.get(f"exact_{m}", "0")
            try:
                amt = float(amt_str)
            except ValueError:
                amt = 0.0
            splits[m] = round(amt, 2)
            total_exact += amt
        if abs(total_exact - total_amount) > 0.01:
            flash(f"Exact amounts must sum to ₹{total_amount:.2f} (got ₹{total_exact:.2f}).", "error")
            return redirect(url_for("add_expense"))

    else:
        flash("Invalid split type.", "error")
        return redirect(url_for("add_expense"))

    # Persist expense
    expense_id = new_id()
    expense_row = {
        "expense_id": expense_id,
        "description": description,
        "total_amount": total_amount,
        "paid_by": paid_by,
        "split_type": split_type,
        "created_by": session["username"],
        "created_at": now_str(),
    }
    expenses_collection.insert_one(expense_row)

    # Persist splits
    split_rows = []
    for username, amount_owed in splits.items():
        split_rows.append({
            "split_id": new_id(),
            "expense_id": expense_id,
            "username": username,
            "amount_owed": amount_owed,
        })
    # Good practice to check if the list has items before inserting
    if split_rows:
        expense_splits_collection.insert_many(split_rows)

    flash("Expense added successfully!", "success")
    return redirect(url_for("dashboard"))


# ---------------------------------------------------------------------------
# Routes — Expense Detail
# ---------------------------------------------------------------------------

@app.route("/expense/<expense_id>")
@login_required
def expense_detail(expense_id):
    expenses = read_expenses()
    row = expenses[expenses["expense_id"] == expense_id]
    if row.empty:
        flash("Expense not found.", "error")
        return redirect(url_for("dashboard"))

    expense = row.iloc[0].to_dict()
    expense["total_amount"] = round(float(expense["total_amount"]), 2)

    splits = read_splits()
    exp_splits = splits[splits["expense_id"] == expense_id]

    users = read_users()
    user_map = {r["username"]: r["display_name"] for _, r in users.iterrows()}

    split_list = []
    for _, s in exp_splits.iterrows():
        split_list.append({
            "username": s["username"],
            "display_name": user_map.get(s["username"], s["username"]),
            "amount_owed": round(float(s["amount_owed"]), 2),
        })

    expense["paid_by_display"] = user_map.get(expense["paid_by"], expense["paid_by"])

    return render_template("expense_detail.html", expense=expense, split_list=split_list)


# ---------------------------------------------------------------------------
# Routes — Settle Up
# ---------------------------------------------------------------------------

@app.route("/settle", methods=["GET"])
@login_required
def settle():
    current_user = session["username"]
    balances = compute_balances(current_user)

    users = read_users()
    user_map = {r["username"]: r["display_name"] for _, r in users.iterrows()}

    # Only show people I owe (negative balance)
    owe_list = []
    for uname, amount in balances.items():
        if amount < -0.005:
            owe_list.append({
                "username": uname,
                "display_name": user_map.get(uname, uname),
                "amount": round(-amount, 2),  # positive for display
            })
    owe_list.sort(key=lambda x: x["amount"], reverse=True)

    prefill_user = request.args.get("user", "")
    prefill_amount = ""
    if prefill_user and prefill_user in balances:
        prefill_amount = str(round(-balances[prefill_user], 2))

    return render_template("settle.html", owe_list=owe_list,
                           prefill_user=prefill_user, prefill_amount=prefill_amount)


@app.route("/settle", methods=["POST"])
@login_required
def settle_post():
    current_user = session["username"]
    to_user = request.form.get("to_user", "").strip()
    amount_str = request.form.get("amount", "").strip()

    if not to_user:
        flash("Select a person to settle with.", "error")
        return redirect(url_for("settle"))

    try:
        amount = round(float(amount_str), 2)
        if amount <= 0:
            raise ValueError
    except ValueError:
        flash("Enter a valid positive amount.", "error")
        return redirect(url_for("settle"))

    row = {
        "settlement_id": new_id(),
        "from_user": current_user,
        "to_user": to_user,
        "amount": amount,
        "created_at": now_str(),
    }
    settlements_collection.insert_one(row)

    flash(f"Settlement of ₹{amount:.2f} recorded!", "success")
    return redirect(url_for("dashboard"))

# ---------------------------------------------------------------------------
# Routes — Delete Expense - OLD
# ---------------------------------------------------------------------------

# @app.route("/api/expenses/<expense_id>", methods=["DELETE"])
# @login_required
# def delete_expense(expense_id):
#     current_user = session["username"]

#     # 1. Load the current data

#     expenses = db["expenses"]
#     expense_splits = db["expense_splits"]
#     expense_df = pd.DataFrame(list(expenses.find({})))
#     splits_df = pd.DataFrame(list(expense_splits.find({})))

#     # 2. Verify the expense actually exists
#     if expense_df.empty or expense_id not in expense_df["expense_id"].values:
#         return jsonify({"success": False, "error": "Expense not found."}), 404

#     # Optional Security: Only allow the person who created the expense to delete it
#     # expense_row = expenses[expenses["expense_id"] == expense_id].iloc[0]
#     # if expense_row["created_by"] != current_user:
#     #     return jsonify({"success": False, "error": "You can only delete your own expenses."}), 403

#     # 3. Filter OUT the expense (Keep everything where the ID does NOT match)
#     expenses_updated = expense_df[expense_df["expense_id"] != expense_id]
#     splits_updated = splits_df[splits_df["expense_id"] != expense_id]
#     new_expenses_data = expenses_updated.to_dict(orient="records")
#     new_splits_data = splits_updated.to_dict(orient="records")

#     # 4. Save the updated dataframes back to MongoDB
    
#     if new_expenses_data:
#         expenses.delete_many({})
#         expenses.insert_many(new_expenses_data)
#     if new_splits_data:
#         expense_splits.delete_many({})
#         expense_splits.insert_many(new_splits_data)
#     return jsonify({"success": True, "message": "Expense and associated splits removed successfully."}), 200


# ---------------------------------------------------------------------------
# Routes — Delete Expense - REVAMPED
# ---------------------------------------------------------------------------

@app.route("/api/expenses/<expense_id>", methods=["DELETE"])
@login_required
def delete_expense(expense_id):
    current_user = session["username"]

    expenses = db["expenses"]
    expense_splits = db["expense_splits"]

    # Optional Security: Verify ownership before deleting
    # expense_doc = expenses.find_one({"expense_id": expense_id})
    # if not expense_doc:
    #     return jsonify({"success": False, "error": "Expense not found."}), 404
    # if expense_doc["created_by"] != current_user:
    #     return jsonify({"success": False, "error": "You can only delete your own expenses."}), 403

    # 1. Delete the specific expense from the expenses collection
    # delete_one finds the first document that matches your criteria and drops it
    result = expenses.delete_one({"expense_id": expense_id})

    # 2. Verify the expense actually existed and was deleted
    if result.deleted_count == 0:
        return jsonify({"success": False, "error": "Expense not found."}), 404

    # 3. Delete ALL matching splits from the expense_splits collection
    # delete_many finds every document that matches your criteria and drops them
    expense_splits.delete_many({"expense_id": expense_id})

    return jsonify({"success": True, "message": "Expense and associated splits removed successfully."}), 200

# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.route("/api/users")
@login_required
def api_users():
    users = read_users()
    result = [{"username": r["username"], "display_name": r["display_name"]}
              for _, r in users.iterrows()]
    return jsonify(result)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
