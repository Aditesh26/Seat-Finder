import RPi.GPIO as GPIO, time, requests

# ---- EDIT THIS with your laptop IP ----
LAPTOP_API = "http://192.168.137.1:5000/api/seats/update"  # change to your laptop IP
# ---------------------------------------

# Map sensors (IR) and LEDs (lights)
SEATS = [
    {"seat_id": 1, "ir_pin": 17, "led_pin": 22},  # Seat 1: IR=GPIO17, LED=GPIO22
    {"seat_id": 2, "ir_pin": 27, "led_pin": 23},  # Seat 2: IR=GPIO27, LED=GPIO23
]

GPIO.setmode(GPIO.BCM)

# Setup pins
for s in SEATS:
    GPIO.setup(s["ir_pin"], GPIO.IN)
    GPIO.setup(s["led_pin"], GPIO.OUT)
    GPIO.output(s["led_pin"], GPIO.LOW)

def post_state(seat_id, occupied: bool):
    try:
        r = requests.post(LAPTOP_API, json={"seat_id": seat_id, "occupied": occupied}, timeout=3)
        if r.status_code == 200:
            print(f"[OK] Seat {seat_id} updated → occupied={occupied}")
        else:
            print(f"[WARN] API {r.status_code}: {r.text}")
    except Exception as e:
        print("[ERROR] POST failed:", e)
	
print("IR watcher started (checks every 5s). Ctrl+C to stop.")
try:
    last = {s["seat_id"]: None for s in SEATS}
    while True:
        for s in SEATS:
            # Many IR modules go LOW (0) when blocked
            occupied = (GPIO.input(s["ir_pin"]) == GPIO.LOW)
            if last[s["seat_id"]] != occupied:
                last[s["seat_id"]] = occupied
                GPIO.output(s["led_pin"], GPIO.HIGH if occupied else GPIO.LOW)
                post_state(s["seat_id"], occupied)
        time.sleep(5)  # check every 5 seconds
except KeyboardInterrupt:
    pass
finally:
    GPIO.cleanup()	
    print("GPIO cleaned up.")
