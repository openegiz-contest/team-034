# Водоотлив «Кварцитовые Горки» — заготовка

Папка `team/drainage/` в командном репозитории.

## Запуск (из корня репозитория)

```bash
sudo apt install -y make          # на чистой Ubuntu make нет
make drainage                     # поднимает платформу OpenEgiz и водоотлив (первый раз долго)
```

Двойники появятся в Grafana → приложение **OpenEgiz** → **Twins** (пространство имён `org.kvgorki`).

Логи расчёта:

```bash
make logs S=drainage-simulator
```

Остановить: `make down`. Снова поднять: `make up` (водоотлив поднимется вместе с платформой). Удалить всё с данными: `make clean`.

## Файлы

| Файл | Кто отвечает | Что это |
|---|---|---|
| `twins.json` | участник 1 | все двойники и их поля |
| `setup_twins.py` | — | создаёт двойников в Ditto (копия из примера) |
| `simulator.py` | участник 2 | расчёт: приток − откачка, отправка в MQTT, чтение `control` из Ditto |
| `compose.yml` | участник 1 | запуск setup и simulator вместе с платформой |

## Как экран управляет насосом

Экран пишет в Ditto, расчёт читает оттуда на каждом шаге:

```bash
# пароль: DITTO_PASSWORD в deploy/compose/.env
curl -u ditto:ПАРОЛЬ -X PUT -H 'Content-Type: application/json' \
  http://localhost:8080/api/2/things/org.kvgorki:pump-02/features/control/properties/enabled -d 'false'

curl -u ditto:ПАРОЛЬ -X PUT -H 'Content-Type: application/json' \
  http://localhost:8080/api/2/things/org.kvgorki:sump-01/features/control/properties/inflow_m3h -d '500'
```

Читать текущее состояние:

```bash
curl -u ditto:ПАРОЛЬ http://localhost:8080/api/2/things/org.kvgorki:sump-01/features
```

## Проверка расчёта без платформы

```bash
pip install paho-mqtt==2.1.0
python team/drainage/simulator.py --dry-run --steps 5
```

## Что заменить (TODO)

Числа в начале `simulator.py` и в `twins.json` (`capacity_m3`) — временные. Заменить на значения из проекта горных работ (PDF, стр. 130–134), остальное записать в SUBMISSION.md как допущения.
