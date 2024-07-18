from flask import Flask, render_template, request, jsonify, send_file
from status_scout_test import run_script
import os

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/run_search', methods=['POST'])
def run_search():
    search_type = int(request.form['search_type'])
    sheet_link = request.form['sheet_link']
    keywords = request.form.get('keywords', None)
    linkedin_type = request.form.get('linkedin_type', None)
    
    try:
        results = run_script(search_type, sheet_link, keywords, linkedin_type)
        email_count = len(results)
        return jsonify({
            'success': True,
            'message': f"{email_count} emails were found with your search!",
            'email_count': email_count,
            'results': results
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/download/<file_type>')
def download_file(file_type):
    if file_type == 'db':
        return send_file('emails.db', as_attachment=True)
    elif file_type == 'txt':
        return send_file('email_results.txt', as_attachment=True)
    else:
        return jsonify({'success': False, 'message': 'Invalid file type'})

if __name__ == '__main__':
    app.run(debug=True)
