import hashlib
import pickle
import sqlite3

from flask import Flask, request

app = Flask(__name__)


@app.route("/user")
def user():
    conn = sqlite3.connect("app.db")
    name = request.args.get("name")
    rows = conn.execute("SELECT * FROM users WHERE name = '" + name + "'").fetchall()
    return {"rows": rows}


@app.route("/load", methods=["POST"])
def load():
    return {"obj": str(pickle.loads(request.data))}


def hash_password(password):
    return hashlib.md5(password.encode()).hexdigest()


if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)
