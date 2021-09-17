from flask import Flask
from hieutv import run_check as check_hieutv

app = Flask(__name__)

@app.route("/")
def index():
    check_hieutv()
    return "<p>We're running!</p>"

if __name__ == "__main__":
    app.run(host='localhost', port=8080, debug=True)