from flask import Flask, render_template, request, jsonify
import socket
import time
import logging
from typing import Dict


# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('adt760_webserver.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Cấu hình cố định
ADT760_IP = "192.168.1.15"
ADT760_PORT = 8000
TIMEOUT = 5

pressure_ranges = {
    "PSI": (-12.5, 300),
    "BAR": (-0.8, 20.7),
    "KPA": (-86.2, 2068.4)
}

def validate_input(value: str, field: str) -> bool:
    """Kiểm tra đầu vào không rỗng và hợp lệ"""
    if not value or value.strip() == "":
        logger.error(f"Invalid input: {field} is empty")
        return False
    return True

def send_scpi_command(command: str) -> Dict[str, str]:
    if not validate_input(command, "command"):
        return {"status": "error", "message": "Command cannot be empty"}

    for attempt in range(3):  # Thử lại 3 lần
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(TIMEOUT)
                logger.info(f"Attempt {attempt + 1}: Connecting to {ADT760_IP}:{ADT760_PORT}")
                s.connect((ADT760_IP, ADT760_PORT))
                s.sendall((command + "\n").encode())
                
                if command.endswith("?"):
                    time.sleep(0.5)
                    response = s.recv(1024).decode().strip()
                    logger.info(f"Command sent: {command}, Response: {response}")
                    return {"status": "success", "response": response}
                else:
                    logger.info(f"Command sent: {command}, No response expected")
                    return {"status": "success", "response": "Command executed successfully"}
        except socket.timeout:
            logger.error(f"Attempt {attempt + 1}: Timeout connecting to {ADT760_IP}:{ADT760_PORT}")
            if attempt == 2:
                return {"status": "error", "message": "Connection timeout"}
        except socket.error as e:
            logger.error(f"Attempt {attempt + 1}: Socket error: {str(e)}")
            if attempt == 2:
                return {"status": "error", "message": f"Socket error: {str(e)}"}
            time.sleep(1)  # Đợi 1 giây trước khi thử lại
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

@app.route("/")
def index() -> str:
    """Trang chủ hiển thị giao diện điều khiển"""
    try:
        return render_template("index.html")
    except Exception as e:
        logger.error(f"Error rendering template: {str(e)}")
        return jsonify({"status": "error", "message": "Failed to load template"}), 500

@app.route("/read_pressure", methods=["GET"])
def read_pressure() -> jsonify:
    """Đọc giá trị áp suất từ kênh được chọn"""
    channel = request.args.get("channel")
    valid_channels = ["1", "2", "3"]
    channel = channel if channel in valid_channels else "1"
    
    if channel not in valid_channels:
        logger.error(f"Invalid channel: {channel}")
        return jsonify({"status": "error", "message": "Invalid channel. Must be 1, 2, or 3"}), 400
    
    command = f"MEASure:SCALar:PRESsure{channel}?"
    result = send_scpi_command(command)
    
    if result["status"] == "error":
        error_result = send_scpi_command("SYSTem:ERRor?")
        error_message = error_result.get("response", "No error details available")
        logger.error(f"Failed to read pressure on channel {channel}: {result['message']}, Device error: {error_message}")
        return jsonify({"status": "error", "message": f"Failed to read pressure on channel {channel}: {result['message']}. Device error: {error_message}"}), 400
    
    # Xử lý định dạng: thay thế dấu phẩy bằng khoảng trắng
    formatted_response = result["response"].replace(",", " ")
    return jsonify({"status": "success", "response": formatted_response})

@app.route("/set_pressure_and_unit", methods=["POST"])
def set_pressure_and_unit() -> jsonify:
    """Đặt giá trị áp suất và/hoặc đơn vị cho kênh được chọn"""
    pressure_value = request.form.get("pressure_value")
    unit = request.form.get("unit")
    channel = request.form.get("channel", "1")
    
    if channel not in ["1", "2", "3"]:
        logger.error(f"Invalid channel: {channel}")
        return jsonify({"status": "error", "message": "Invalid channel. Must be 1, 2, or 3"}), 400
    
    if not pressure_value and not unit:
        logger.error("Both pressure value and unit are empty")
        return jsonify({"status": "error", "message": "At least one of pressure value or unit must be provided"}), 400
    
    valid_units = ["PSI", "BAR", "KPA"]
    response_message = []
    
    # Lấy đơn vị hiện tại nếu không cung cấp unit
    current_unit = None
    if pressure_value and not unit:
        unit_result = send_scpi_command(f"UNIT:PRESsure{channel}?")
        if unit_result["status"] == "error":
            error_result = send_scpi_command("SYSTem:ERRor?")
            error_message = error_result.get("response", "No error details available")
            logger.error(f"Failed to read current unit on channel {channel}: {unit_result['message']}, Device error: {error_message}")
            return jsonify({"status": "error", "message": f"Failed to read current unit on channel {channel}: {unit_result['message']}. Device error: {error_message}"}), 400
        current_unit = unit_result["response"].upper()
    
    # Đặt đơn vị nếu được cung cấp
    if unit:
        if unit.upper() not in valid_units:
            logger.error(f"Invalid unit: {unit}")
            return jsonify({"status": "error", "message": f"Invalid unit. Must be one of {', '.join(valid_units)}"}), 400
        
        unit_command = f"UNIT:PRESsure{channel} '{unit.upper()}'"
        unit_result = send_scpi_command(unit_command)
        if unit_result["status"] == "error":
            error_result = send_scpi_command("SYSTem:ERRor?")
            error_message = error_result.get("response", "No error details available")
            logger.error(f"Failed to set unit {unit} on channel {channel}: {unit_result['message']}, Device error: {error_message}")
            return jsonify({"status": "error", "message": f"Failed to set unit {unit} on channel {channel}: {unit_result['message']}. Device error: {error_message}"}), 400
        
        # Xác nhận đơn vị
        confirm_command = f"UNIT:PRESsure{channel}?"
        confirm_result = send_scpi_command(confirm_command)
        if confirm_result["status"] != "success" or confirm_result["response"].upper() != unit.upper():
            logger.error(f"Unit verification failed: Expected {unit.upper()}, got {confirm_result.get('response', 'N/A')}")
            return jsonify({"status": "error", "message": f"Failed to set unit {unit} on channel {channel}: Got {confirm_result.get('response', 'N/A')}"}), 400
        
        response_message.append(f"Unit set to {unit.upper()} on channel {channel}")
    
    # Đặt áp suất nếu được cung cấp
    if pressure_value:
        try:
            pressure_float = float(pressure_value)
            # Dùng đơn vị được cung cấp hoặc đơn vị hiện tại
            active_unit = unit.upper() if unit else current_unit
            if active_unit not in pressure_ranges:
                logger.error(f"Unknown unit for range check: {active_unit}")
                return jsonify({"status": "error", "message": f"Unknown unit {active_unit} for range check"}), 400
            
            min_val, max_val = pressure_ranges[active_unit]
            if pressure_float < min_val or pressure_float > max_val:
                logger.error(f"Pressure value out of range: {pressure_value}. Must be between {min_val} and {max_val} {active_unit}.")
                return jsonify({"status": "error", "message": f"Pressure value must be between {min_val} and {max_val} {active_unit}"}), 400
        
            # Kiểm tra và đặt chế độ CONTrol
            mode_check = send_scpi_command("OUTPut:PRESsure:MODE?")
            if mode_check["status"] == "error" or mode_check["response"].upper() != "CONTROL":
                logger.info(f"Setting device to CONTROL mode")
                mode_result = send_scpi_command("OUTPut:PRESsure:MODE CONTrol")
                if mode_result["status"] == "error":
                    error_result = send_scpi_command("SYSTem:ERRor?")
                    error_message = error_result.get("response", "No error details available")
                    logger.error(f"Failed to set CONTROL mode: {mode_result['message']}, Device error: {error_message}")
                    return jsonify({"status": "error", "message": f"Failed to set CONTROL mode: {mode_result['message']}. Device error: {error_message}"}), 400
            
            # Đặt áp suất
            pressure_command = f"SOURce:PRESsure {pressure_value}"
            pressure_result = send_scpi_command(pressure_command)
            if pressure_result["status"] == "error":
                error_result = send_scpi_command("SYSTem:ERRor?")
                error_message = error_result.get("response", "No error details available")
                logger.error(f"Failed to set pressure {pressure_value} on channel {channel}: {pressure_result['message']}, Device error: {error_message}")
                return jsonify({"status": "error", "message": f"Failed to set pressure {pressure_value} on channel {channel}: {pressure_result['message']}. Device error: {error_message}"}), 400
            
            response_message.append(f"Pressure set to {pressure_value} {active_unit} on channel {channel}")
        
        except ValueError:
            logger.error(f"Invalid pressure value: {pressure_value}")
            return jsonify({"status": "error", "message": "Invalid pressure value. Must be a number"}), 400
    
    return jsonify({"status": "success", "response": "; ".join(response_message)})

@app.route("/read_pressure_stability", methods=["GET"])
def read_pressure_stability() -> jsonify:
    """Đọc trạng thái ổn định áp suất từ kênh được chọn"""
    command = f"OUTPut:PRESsure:STABle?"
    result = send_scpi_command(command)    
    stability = "Stable" if result["response"] == "1" else "Unstable"
    return jsonify({"status": "success", "response": stability})

@app.route("/set_wifi", methods=["POST"])
def set_wifi() -> jsonify:
    """Cấu hình kết nối WiFi cho ADT760"""
    ssid = request.form.get("ssid")
    password = request.form.get("password")
    encryption = request.form.get("encryption", "WPA2")
    
    if not all(validate_input(field, name) for field, name in [(ssid, "ssid"), (password, "password")]):
        return jsonify({"status": "error", "message": "SSID or password cannot be empty"}), 400
    
    command = f'SYSTem:COMMunicate:SOCKet:WLAN:CONNect "{ssid}",{encryption},"{password}"'
    return jsonify(send_scpi_command(command))

@app.route("/check_wifi_status", methods=["GET"])
def check_wifi_status() -> jsonify:
    """Kiểm tra trạng thái WiFi"""
    return jsonify(send_scpi_command("SYSTem:COMMunicate:SOCKet:WLAN:STATus?"))

@app.route("/read_ip", methods=["GET"])
def read_ip() -> jsonify:
    """Đọc địa chỉ IP hiện tại của ADT760"""
    command = "SYSTem:COMMunicate:SOCKet:WLAN:ADDRess?"
    result = send_scpi_command(command)
    
    if result["status"] == "error":
        error_result = send_scpi_command("SYSTem:ERRor?")
        error_message = error_result.get("response", "No error details available")
        logger.error(f"Failed to read IP: {result['message']}, Device error: {error_message}")
        return jsonify({"status": "error", "message": f"Failed to read IP: {result['message']}. Device error: {error_message}"}), 400
    
    return jsonify(result)

@app.route("/set_ip", methods=["POST"])
def set_ip() -> jsonify:
    """Cấu hình địa chỉ IP cho ADT760"""
    ip_address = request.form.get("ip_address")
    
    if not validate_input(ip_address, "ip_address"):
        return jsonify({"status": "error", "message": "IP address cannot be empty"}), 400
    
    command = f"SYSTem:COMMunicate:SOCKet:WLAN:ADDRESS {ip_address}"
    return jsonify(send_scpi_command(command))

@app.route("/read_device_info", methods=["GET"])
def read_device_info() -> jsonify:
    """Đọc thông tin thiết bị"""
    return jsonify(send_scpi_command("*IDN?"))

@app.route("/set_output_mode", methods=["POST"])
def set_output_mode() -> jsonify:
    """Chuyển đổi chế độ OUTPUT: Control, Measure, Vent"""
    mode = request.form.get("mode")
    
    if not validate_input(mode, "mode"):
        return jsonify({"status": "error", "message": "Mode cannot be empty"}), 400
    
    if mode not in ["CONTrol", "MEASure", "VENT"]:
        logger.error(f"Invalid mode: {mode}")
        return jsonify({"status": "error", "message": "Invalid mode. Must be CONTrol, MEASure, or VENT"}), 400
    
    command = f"OUTPut:PRESsure:MODE {mode}"
    return jsonify(send_scpi_command(command))

if __name__ == "__main__":
    logger.info(f"Starting webserver on host 0.0.0.0, port 8000")
    app.run(host="0.0.0.0", port=8000, debug=True)