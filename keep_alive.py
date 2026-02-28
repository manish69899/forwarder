"""
================================================================================
                           KEEP ALIVE SERVER
================================================================================
Flask server for Render deployment - keeps the bot alive on free tier.
================================================================================
"""

from flask import Flask
from threading import Thread
import logging

# Configure logging
logging.getLogger('werkzeug').setLevel(logging.WARNING)

app = Flask(__name__)

@app.route('/')
def home():
    """Health check endpoint."""
    return '''
    <html>
    <head>
        <title>Telegram Bot - Online</title>
        <style>
            body { 
                font-family: Arial, sans-serif; 
                background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); 
                color: #eee; 
                display: flex; 
                justify-content: center; 
                align-items: center; 
                height: 100vh; 
                margin: 0; 
            }
            .container { 
                text-align: center; 
                padding: 40px; 
                background: rgba(255,255,255,0.1); 
                border-radius: 20px; 
                box-shadow: 0 8px 32px rgba(0,0,0,0.3); 
            }
            h1 { color: #00d9ff; margin-bottom: 10px; }
            p { color: #aaa; }
            .status { 
                display: inline-block; 
                padding: 10px 30px; 
                background: #00d9ff; 
                color: #1a1a2e; 
                border-radius: 25px; 
                font-weight: bold; 
                margin-top: 20px; 
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🤖 Telegram Publisher Bot</h1>
            <p>Enterprise Edition v6.2</p>
            <div class="status">✅ ONLINE</div>
        </div>
    </body>
    </html>
    '''

@app.route('/health')
def health():
    """Health check for monitoring."""
    return {'status': 'healthy', 'service': 'telegram-publisher-bot'}, 200

@app.route('/ping')
def ping():
    """Simple ping endpoint."""
    return 'pong', 200


def run():
    """Run the Flask server."""
    import os
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)


def keep_alive():
    """Start Flask server in a separate thread."""
    server_thread = Thread(target=run, daemon=True)
    server_thread.start()
    print("🌐 Keep-alive server started on port 8080")


if __name__ == '__main__':
    keep_alive()
    import time
    while True:
        time.sleep(1)
