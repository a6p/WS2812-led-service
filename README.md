# LED Service для Orange Pi с WS2812B

Этот сервис управляет кольцом/лентой WS2812B через аппаратный SPI.


## Требования
- Python 3.7+
- Аппаратный SPI

## Установка

```bash
sudo apt update
sudo apt install python3 python3-pip python3-numpy portaudio19-dev
pip3 install -r requirements.txt


## Разрешения

Добавьте пользователя в группу spi, если нужно:

sudo usermod -aG spi $USER

## Конфигурация

Файл: /etc/prokhor/led_service.conf

Создаётся автоматически при первом запуске:

[DEFAULT]
LED_COUNT = 24
BRIGHTNESS = 0.3
SPI_DEV_PATH = /dev/spidev1.1
SPI_SPEED_HZ = 2400000
SERVER_HOST = 0.0.0.0
SERVER_PORT = 5000
DEFAULT_MODE = spinner
DEFAULT_COLOR = 200,80,10

## API

    POST /set_mode — изменить режим (spinner, visualizer, static, candle)

    POST /set_color — установить цвет (r, g, b)

    POST /visualizer — установка яркости

## Пример:
```bash
curl -X POST -H "Content-Type: application/json" \
     -d '{"mode": "candle"}' http://localhost:5000/set_mode

Сервис systemd

sudo cp led_service.service /etc/systemd/system/
sudo systemctl daemon-reexec
sudo systemctl enable led_service
sudo systemctl start led_service
