import os
import time
import signal
import sys
import numpy as np
import pyaudio
import configparser
from flask import Flask, request, jsonify
from threading import Thread, Lock, Event
from periphery import SPI
import random

CONFIG_PATH = "/etc/prokhor/led_service.conf"

# Загрузка и создание конфигурации по умолчанию при необходимости
def load_config():
    config = configparser.ConfigParser()
    if not os.path.exists(CONFIG_PATH):
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        config['DEFAULT'] = {
            'LED_COUNT': '24',
            'BRIGHTNESS': '0.3',
            'SPI_DEV_PATH': '/dev/spidev1.1',
            'SPI_SPEED_HZ': '2400000',
            'SERVER_HOST': '0.0.0.0',
            'SERVER_PORT': '5000',
            'DEFAULT_MODE': 'spinner',
            'DEFAULT_COLOR': '200,80,10'
        }
        with open(CONFIG_PATH, 'w') as f:
            config.write(f)
    else:
        config.read(CONFIG_PATH)
    return config

# Загрузка конфигурации
config = load_config()
LED_COUNT = int(config['DEFAULT'].get('LED_COUNT', '24'))
BRIGHTNESS = float(config['DEFAULT'].get('BRIGHTNESS', '0.3'))
SPI_DEV_PATH = config['DEFAULT'].get('SPI_DEV_PATH', '/dev/spidev1.1')
SPI_SPEED_HZ = int(config['DEFAULT'].get('SPI_SPEED_HZ', '2400000'))
SERVER_HOST = config['DEFAULT'].get('SERVER_HOST', '127.0.0.1')
SERVER_PORT = int(config['DEFAULT'].get('SERVER_PORT', '5000'))
DEFAULT_MODE = config['DEFAULT'].get('DEFAULT_MODE', 'spinner')
DEFAULT_COLOR = tuple(map(int, config['DEFAULT'].get('DEFAULT_COLOR', '200,80,10').split(',')))

# Проверка устройства SPI
if not os.path.exists(SPI_DEV_PATH):
    raise RuntimeError(f"SPI device {SPI_DEV_PATH} not found. Check orangepiEnv.txt and enable SPI.")

spi = SPI(SPI_DEV_PATH, 0, SPI_SPEED_HZ)
app = Flask(__name__)

# Глобальные переменные
mode = DEFAULT_MODE
current_color = DEFAULT_COLOR
lock = Lock()
audio_level = 0
shutdown_event = Event()

# Обработчик сигналов завершения
def signal_handler(sig, frame):
    print(f"\nПолучен сигнал {sig}, завершаем работу...")
    shutdown_event.set()
    clear_strip()
    spi.close()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Преобразование байта в формат SPI (3 бита на бит)
def encode_byte(byte):
    return [(0b110 if (byte >> (7 - i)) & 1 else 0b100) for i in range(8)]

# Кодировка цвета в формат GRB для WS2812B
def encode_color(r, g, b):
    r = int(r * BRIGHTNESS)
    g = int(g * BRIGHTNESS)
    b = int(b * BRIGHTNESS)
    data = []
    for byte in [g, r, b]:
        data += encode_byte(byte)
    return data

# Отправка данных на светодиоды
def send_leds(colors):
    spi_data = []
    for r, g, b in colors:
        spi_data += encode_color(r, g, b)
    spi_data += [0] * 64  # reset
    spi.transfer(spi_data)

# Очистка ленты
def clear_strip():
    send_leds([(0, 0, 0)] * LED_COUNT)

# Поток захвата аудио
def audio_capture():
    global audio_level
    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16, channels=1, rate=44100, input=True, frames_per_buffer=1024)
    while not shutdown_event.is_set():
        try:
            data = stream.read(1024, exception_on_overflow=False)
            samples = np.frombuffer(data, dtype=np.int16)
            rms = np.sqrt(np.mean(samples**2))
            with lock:
                audio_level = min(100, rms / 500)
        except Exception as e:
            print(f"Audio capture error: {e}")
            break
    stream.stop_stream()
    stream.close()
    p.terminate()

# Эффект свечи

def candle_effect():
    global audio_level
    base_color = (200, 80, 10)
    while not shutdown_event.is_set():
        with lock:
            if mode != 'candle':
                break
            current_audio = audio_level

        colors = []
        for _ in range(LED_COUNT):
            flicker = random.randint(0, 50)
            r = max(50, min(255, base_color[0] + flicker - 25 + int(current_audio * 2)))
            g = max(30, min(200, base_color[1] + flicker - 25 + int(current_audio)))
            b = max(0, min(50, base_color[2] + flicker // 2 - 10))
            colors.append((r, g, b))

        send_leds(colors)
        time.sleep(0.05)

# Анимация спиннера

def spinner():
    decay = 0.7
    values = [0.0] * LED_COUNT
    while not shutdown_event.is_set():
        with lock:
            if mode != 'spinner':
                break
            color = current_color
        for i in range(LED_COUNT):
            values = [v * decay for v in values]
            values[i] = 1.0
            output = [(int(color[0]*v), int(color[1]*v), int(color[2]*v)) for v in values]
            send_leds(output)
            time.sleep(0.05)

# Аудиовизуализация

def audio_visualizer():
    global audio_level
    while not shutdown_event.is_set():
        with lock:
            if mode != 'visualizer':
                break
            color = current_color
            current_audio = audio_level

        bars = min(LED_COUNT, max(1, int((current_audio / 100) * LED_COUNT)))
        output = [color if i < bars else (0, 0, 0) for i in range(LED_COUNT)]
        send_leds(output)
        time.sleep(0.05)

# Статичный цвет

def static_color():
    while not shutdown_event.is_set():
        with lock:
            if mode != 'static':
                break
            color = current_color
        send_leds([color] * LED_COUNT)
        time.sleep(0.1)

# Цикл выбора режима

def mode_loop():
    while not shutdown_event.is_set():
        try:
            with lock:
                m = mode
            if m == 'spinner':
                spinner()
            elif m == 'visualizer':
                audio_visualizer()
            elif m == 'static':
                static_color()
            elif m == 'candle':
                candle_effect()
            else:
                time.sleep(0.1)
        except Exception as e:
            print(f"[Mode loop error] {e}")
            time.sleep(1)

# API эндпоинты

@app.route('/visualizer', methods=['POST'])
def api_visualizer_volume():
    data = request.get_json()
    volume = int(data.get('volume', 0))
    volume = max(0, min(volume, LED_COUNT))

    with lock:
        if mode in ('visualizer', 'candle'):
            color = current_color
            output = [color if i < volume else (0, 0, 0) for i in range(LED_COUNT)]
            send_leds(output)
    return jsonify({'status': 'ok', 'volume': volume})

@app.route('/set_color', methods=['POST'])
def api_set_color():
    global current_color
    data = request.get_json()
    try:
        r = int(data.get('r', 0))
        g = int(data.get('g', 0))
        b = int(data.get('b', 0))
        if not all(0 <= v <= 255 for v in (r, g, b)):
            raise ValueError
    except:
        return jsonify({'status': 'error', 'message': 'Invalid RGB'}), 400

    with lock:
        current_color = (r, g, b)
    send_leds([current_color] * LED_COUNT)
    return jsonify({'status': 'ok', 'color': current_color})

@app.route('/set_mode', methods=['POST'])
def api_set_mode():
    global mode
    data = request.get_json()
    m = data.get('mode', 'static')
    if m not in ['static', 'spinner', 'visualizer', 'candle']:
        return jsonify({'status': 'error', 'message': 'Invalid mode'}), 400

    with lock:
        mode = m
    return jsonify({'status': 'ok', 'mode': mode})

# Основной запуск
if __name__ == '__main__':
    try:
        audio_thread = Thread(target=audio_capture, daemon=True)
        audio_thread.start()

        mode_thread = Thread(target=mode_loop, daemon=True)
        mode_thread.start()

        app.run(host=SERVER_HOST, port=SERVER_PORT, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        print("\nОстановка...")
        clear_strip()
    finally:
        spi.close()
