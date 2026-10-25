from flask import Blueprint, send_from_directory

pages_bp = Blueprint('pages', __name__)


@pages_bp.route('/')
def index():
    return send_from_directory('static', 'index.html')


@pages_bp.route('/practice')
def practice_page():
    return send_from_directory('static', 'practice.html')
