# Python HTTP Server

Минимальный HTTP/1.1 веб-сервер на чистом Python: TCP-сокеты, ручной разбор запросов, роутинг, статика, пул потоков. Без Flask, Django и сторонних HTTP-библиотек.

**Подробное техническое руководство:** [doc.md](doc.md) — пошаговое создание с нуля, диаграммы, примеры кода, конфиг, раздел «Модификация».

## Структура проекта

```
python-http-server/
├── main.py                 # Точка входа, аргументы CLI
├── config.json             # Настройки по умолчанию (host, port, static_dir)
├── README.md
├── server/
│   ├── __init__.py
│   ├── http_parser.py      # HTTP Parser — чтение и разбор запроса
│   ├── http_request.py     # HTTP Request — модель запроса
│   ├── http_response.py    # HTTP Response — сборка ответа
│   ├── router.py           # Router — маршруты GET/POST
│   ├── static_handler.py   # Static File Handler — файлы из static/
│   ├── ssl_support.py      # TLS: загрузка сертификатов, автогенерация
│   ├── error_pages.py      # HTML-страницы ошибок 400/404/500
│   ├── builtin_pages/      # Встроенные шаблоны (не static!)
│   ├── config.py           # Загрузка config.json
│   └── server_core.py      # Server Core — сокет, TLS, пул потоков
│   custom_errors/          # Пример своих страниц ошибок (опционально)
└── static/
    ├── hello.txt
    ├── data.json
    ├── page.html
    └── logo.png
```

## Запуск

```bash
cd python-http-server
python3 main.py
```

Сервер по умолчанию: `http://127.0.0.1:8080`

**Порты** (`http_port`, `https_port`):

| Режим | Порт по умолчанию | Стандарт (флаг `use_standard_ports`) |
|-------|-------------------|--------------------------------------|
| HTTP | 8080 | **80** |
| HTTPS | 8443 | **443** |

Порты 80 и 443 поддерживаются. На Linux/macOS для портов &lt;1024 часто нужны права root или `setcap`.

```bash
# Только HTTP на 80
python3 main.py --standard-ports

# HTTPS на 443 + HTTP на 80 одновременно
python3 main.py --ssl --ssl-auto-generate --standard-ports --ssl-serve-http
```

В конфиге: `"use_standard_ports": true`, `"http_port": 80`, `"https_port": 443`, `"ssl": { "serve_http": true }`.

**TLS/SSL:**

```json
"ssl": {
  "enabled": false,
  "auto_generate": true,
  "serve_http": false,
  "cert_days": 365,
  "cert_cn": "localhost"
}
```

| Поле | Описание |
|------|----------|
| `enabled` | HTTPS |
| `auto_generate` | Сертификат в `certs/.auto-generated/` (**cert_file/key_file не читаются**) |
| `serve_http` | Параллельный HTTP (80) при включённом SSL |
| `cert_file` / `key_file` | Только если `auto_generate: false` |

**CLI:**

```bash
python3 main.py --http-port 8080
python3 main.py --ssl --https-port 8443 --ssl-auto-generate
python3 main.py --standard-ports --ssl --ssl-auto-generate --ssl-serve-http
python3 main.py --ssl --ssl-cert ./my.pem --ssl-key ./my.key   # без auto_generate
```

`curl -sk https://127.0.0.1:8443/` — для самоподписанного сертификата.

```bash
curl -sk https://127.0.0.1:8443/
```

## Страницы ошибок

Встроенные HTML для **400**, **404**, **500** — в `server/builtin_pages/` (не отдаются как статика).

Свои страницы в `config.json`:

```json
"error_pages": {
  "404": "custom_errors/404.html",
  "500": "custom_errors/500.html"
}
```

В шаблоне плейсхолдеры: `{code}`, `{title}`, `{message}`, `{phrase}`.

## Маршруты

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/` | `index.html` из каталога статики |
| GET | `/любой/путь` | Файл из `static_dir` (например `/hello.txt` → `static/hello.txt`) |
| POST | `/api/data` | JSON API (не из static) |

Корень сайта = папка `static_dir`. URL `/about.html` → файл `static/about.html`.

## Примеры curl

```bash
# Главная
curl -s http://127.0.0.1:8080/

# Query-параметры
curl -s "http://127.0.0.1:8080/?name=Nikita&msg=Hello"

# О сервере
curl -s http://127.0.0.1:8080/about

# POST API
curl -s -X POST http://127.0.0.1:8080/api/data \
  -H "Content-Type: application/json" \
  -d '{"user":"test","value":42}'

# Файлы из static/
curl -s http://127.0.0.1:8080/hello.txt
curl -s http://127.0.0.1:8080/data.json
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/logo.png

# 404
curl -s http://127.0.0.1:8080/unknown
```

В браузере откройте: `http://127.0.0.1:8080/`
