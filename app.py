from flask import Flask
from subprocess import Popen
import logging

app = Flask(__name__)

@app.route("/")
def index():
    Popen(['python', 'hieutv.py'])
    logging.info("Spawned process 'python hieutv.py'")
    return "<p>We're running!</p>"

if __name__ == "__main__":
    app.run()