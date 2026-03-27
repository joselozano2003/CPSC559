from flask import Flask, request, jsonify
import subprocess

app = Flask(__name__)

@app.route('/set-leader', methods=['POST'])
def set_leader():
    data = request.get_json()
    address = data.get('address', '')
    # Strip scheme so nginx upstream format is just host:port
    address = address.replace('http://', '').replace('https://', '')
    if not address:
        return jsonify({'error': 'address required'}), 400
    with open('/etc/nginx/upstream.conf', 'w') as f:
        f.write(f'proxy_pass http://{address};\n')
    result = subprocess.run(['nginx', '-s', 'reload'])
    if result.returncode != 0:
        # nginx wasn't running (e.g. crashed on startup) — start it fresh
        subprocess.run(['nginx'])
    print(f'[nginx-updater] Upstream set to {address}', flush=True)
    return jsonify({'ok': True})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
