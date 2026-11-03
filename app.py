
import os
import json
import logging
import tempfile
import threading

from pathlib import Path
from datetime import datetime, timezone, timedelta
from functools import wraps

from flask import Flask, render_template, request, jsonify, make_response
from cryptography.fernet import Fernet, InvalidToken
from dotenv import load_dotenv


# =====================================================
# APPLICATION SETUP
# =====================================================

load_dotenv()

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)

# Environment variables
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")
DEVICE_TOKEN = os.getenv("DEVICE_TOKEN")
FERNET_KEY = os.getenv("FERNET_KEY")

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
CONFIG_FILE = DATA_DIR / "wifi_config.json"

# Validate required secrets
if not ADMIN_TOKEN or not DEVICE_TOKEN or not FERNET_KEY:
    raise RuntimeError(
        "Missing ADMIN_TOKEN, DEVICE_TOKEN or FERNET_KEY in .env"
    )

try:
    cipher = Fernet(FERNET_KEY.encode())
except Exception as error:
    raise RuntimeError("Invalid FERNET_KEY in .env") from error

# File access lock
config_lock = threading.RLock()


# =====================================================
# DEFAULT CONFIGURATION
# =====================================================

def default_config():
    return {
        "version": 0,
        "ssid": "",
        "encrypted_password": "",
        "status": "waiting",
        "last_seen": None,
        "updated_at": None
    }


# =====================================================
# SAVE CONFIGURATION
# =====================================================

def save_config(config):

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    temporary_file = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=DATA_DIR,
            delete=False
        ) as file:

            json.dump(config, file, indent=4)
            file.flush()
            os.fsync(file.fileno())

            temporary_file = file.name

        os.replace(temporary_file, CONFIG_FILE)

    except Exception:
        if temporary_file and os.path.exists(temporary_file):
            os.remove(temporary_file)

        raise


# =====================================================
# READ CONFIGURATION
# =====================================================

def read_config():

    with config_lock:

        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)

            # Create the file if it does not exist
            if not CONFIG_FILE.exists():
                config = default_config()
                save_config(config)
                return config

            # Fix an empty JSON file
            if CONFIG_FILE.stat().st_size == 0:
                app.logger.warning(
                    "Empty configuration file detected. Initializing."
                )

                config = default_config()
                save_config(config)
                return config

            with open(CONFIG_FILE, "r", encoding="utf-8") as file:
                config = json.load(file)

            if not isinstance(config, dict):
                raise ValueError("Invalid configuration structure")

            # Add missing fields if necessary
            defaults = default_config()

            for key, value in defaults.items():
                config.setdefault(key, value)

            return config

        except (json.JSONDecodeError, OSError, ValueError) as error:

            app.logger.error(
                "Configuration storage error: %s", error
            )

            raise RuntimeError(
                "Configuration storage is unavailable"
            ) from error


# =====================================================
# AUTHENTICATION
# =====================================================

def token_required(expected_token):

    def decorator(function):

        @wraps(function)
        def wrapper(*args, **kwargs):

            authorization = request.headers.get("Authorization", "")

            expected_header = f"Bearer {expected_token}"

            if not authorization or not __import__("hmac").compare_digest(
                authorization, expected_header
            ):
                return jsonify({
                    "success": False,
                    "message": "Unauthorized access"
                }), 401

            return function(*args, **kwargs)

        return wrapper

    return decorator


# =====================================================
# MAIN WEBSITE
# =====================================================

@app.route("/")
def home():
    return render_template("index.html")


# =====================================================
# ADMIN: UPDATE WIFI CONFIGURATION
# =====================================================

@app.route("/api/admin/wifi", methods=["POST"])
@token_required(ADMIN_TOKEN)
def update_wifi():

    try:

        data = request.get_json(silent=True)

        if not isinstance(data, dict):
            return jsonify({
                "success": False,
                "message": "Invalid JSON request"
            }), 400

        ssid = data.get("ssid", "")
        password = data.get("password", "")

        if not isinstance(ssid, str) or not isinstance(password, str):
            return jsonify({
                "success": False,
                "message": "SSID and password must be text"
            }), 400

        if not ssid.strip() or ssid != ssid.strip():
            return jsonify({
                "success": False,
                "message": "Please enter a valid Wi-Fi name"
            }), 400

        if len(ssid.encode("utf-8")) > 32:
            return jsonify({
                "success": False,
                "message": "Wi-Fi name must be at most 32 bytes"
            }), 400

        # WPA/WPA2 password validation
        password_bytes = password.encode("utf-8")

        valid_password = (
            8 <= len(password_bytes) <= 63
            or (
                len(password) == 64
                and all(c in "0123456789abcdefABCDEF" for c in password)
            )
        )

        if not valid_password:
            return jsonify({
                "success": False,
                "message": "Wi-Fi password must be 8-63 characters, or 64 hexadecimal characters"
            }), 400

        encrypted_password = cipher.encrypt(
            password.encode("utf-8")
        ).decode("utf-8")

        with config_lock:

            config = read_config()

            config["version"] = int(config.get("version", 0)) + 1
            config["ssid"] = ssid
            config["encrypted_password"] = encrypted_password
            config["status"] = "waiting"
            config["updated_at"] = datetime.now(
                timezone.utc
            ).isoformat()

            save_config(config)

        app.logger.info(
            "New Wi-Fi configuration saved. Version: %s",
            config["version"]
        )

        return jsonify({
            "success": True,
            "message": "Wi-Fi configuration saved successfully",
            "version": config["version"],
            "ssid": config["ssid"]
        }), 200

    except Exception:

        app.logger.exception("Could not save Wi-Fi configuration")

        return jsonify({
            "success": False,
            "message": "Server could not save Wi-Fi configuration"
        }), 500


# =====================================================
# ADMIN: DEVICE STATUS
# =====================================================

@app.route("/api/admin/status", methods=["GET"])
@token_required(ADMIN_TOKEN)
def admin_status():

    try:

        with config_lock:
            config = read_config()

        last_seen = config.get("last_seen")
        online = False

        if last_seen:
            try:
                seen_time = datetime.fromisoformat(last_seen)

                if seen_time.tzinfo is None:
                    seen_time = seen_time.replace(
                        tzinfo=timezone.utc
                    )

                online = (
                    datetime.now(timezone.utc) - seen_time
                    < timedelta(seconds=60)
                )

            except (ValueError, TypeError):
                online = False

        return jsonify({
            "success": True,
            "version": config["version"],
            "ssid": config["ssid"],
            "status": config["status"],
            "online": online,
            "last_seen": last_seen,
            "updated_at": config["updated_at"]
        }), 200

    except Exception:

        app.logger.exception("Could not read admin status")

        return jsonify({
            "success": False,
            "message": "Could not read device status"
        }), 500


# =====================================================
# DEVICE: CHECK FOR NEW WIFI CONFIGURATION
# =====================================================

@app.route("/api/device/config", methods=["GET"])
@token_required(DEVICE_TOKEN)
def device_config():

    try:

        requested_version = request.args.get("version", "0")

        try:
            requested_version = int(requested_version)
        except (TypeError, ValueError):
            return jsonify({
                "success": False,
                "message": "Invalid version"
            }), 400

        with config_lock:

            config = read_config()

            # Record successful device communication
            config["last_seen"] = datetime.now(
                timezone.utc
            ).isoformat()

            save_config(config)

            if config["version"] <= requested_version:
                response = make_response("", 204)
                response.headers["Cache-Control"] = "no-store"
                return response

            try:
                password = cipher.decrypt(
                    config["encrypted_password"].encode("utf-8")
                ).decode("utf-8")

            except (InvalidToken, ValueError, TypeError):
                app.logger.exception(
                    "Could not decrypt Wi-Fi password"
                )

                return jsonify({
                    "success": False,
                    "message": "Could not decrypt configuration"
                }), 500

            response = jsonify({
                "success": True,
                "version": config["version"],
                "ssid": config["ssid"],
                "password": password
            })

            response.headers["Cache-Control"] = "no-store"

            return response, 200

    except Exception:

        app.logger.exception("Device configuration request failed")

        return jsonify({
            "success": False,
            "message": "Could not retrieve device configuration"
        }), 500


# =====================================================
# DEVICE: ACKNOWLEDGE WIFI CONNECTION
# =====================================================

@app.route("/api/device/ack", methods=["POST"])
@token_required(DEVICE_TOKEN)
def device_ack():

    try:

        data = request.get_json(silent=True)

        if not isinstance(data, dict):
            return jsonify({
                "success": False,
                "message": "Invalid JSON request"
            }), 400

        status = data.get("status")
        version = data.get("version")

        if status not in ["connected", "failed"]:
            return jsonify({
                "success": False,
                "message": "Invalid device status"
            }), 400

        try:
            version = int(version)
        except (TypeError, ValueError):
            return jsonify({
                "success": False,
                "message": "Invalid version"
            }), 400

        with config_lock:

            config = read_config()

            # Do not let an old acknowledgement overwrite a newer one
            if version == config["version"]:
                config["status"] = status
                save_config(config)

        return jsonify({
            "success": True,
            "message": "Device acknowledgement received"
        }), 200

    except Exception:

        app.logger.exception("Device acknowledgement failed")

        return jsonify({
            "success": False,
            "message": "Could not process acknowledgement"
        }), 500


# =====================================================
# HEALTH CHECK
# =====================================================

@app.route("/health", methods=["GET"])
def health():

    return jsonify({
        "success": True,
        "application": "JARVIC",
        "status": "running"
    }), 200


# =====================================================
# RUN APPLICATION
# =====================================================

if __name__ == "__main__":

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False
    )
