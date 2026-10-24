# Водоотлив «Кварцитовые Горки»

Папка `team/drainage/` в командном репозитории.

## Запуск (из корня репозитория)

```bash
sudo apt install -y make          # на чистой Ubuntu make нет
make drainage                     # поднимает платформу OpenEgiz и водоотлив (первый раз долго)
```

Экран: Grafana (адрес и пароль печатает `make up`, обычно http://localhost:3000) → **Dashboards → OpenEgiz Examples → Водоотлив «Кварцитовые Горки» — горизонт 420 м**: схема водоотлива, кнопки насосов, приток, сценарии и графики.

Двойники видны и в приложении **OpenEgiz** → **Twins** (пространство имён `org.kvgorki`).

Логи расчёта:

```bash
make logs S=drainage-simulator
```

Остановить: `make down`. Снова поднять: `make up` (водоотлив поднимется вместе с платформой). Удалить всё с данными: `make clean`.

## Файлы

| Файл | Что это |
|---|---|
| `twins.json` | все двойники и их поля |
| `setup_twins.py` | создаёт двойников в Ditto (копия из примера) |
| `water_balance.py` | ядро расчёта: приток − откачка, объём не уходит в минус |
| `simulator.py` | вокруг ядра: вместимость, аварийный уровень, время до аварии, мощность; MQTT и чтение `control` из Ditto |
| `panel/` | плагин Grafana: схема водоотлива, кнопки насосов, приток, сценарии «что если» |
| `dashboard.json` | дашборд: схема + графики объёма, притока/откачки, мощности |
| `tests/` | тесты расчёта: `python -m unittest discover -s team/drainage/tests -v` |
| `compose.yml` | запуск setup, simulator, плагина и дашборда вместе с платформой |

## Как экран управляет насосом

Панель пишет в Ditto через прокси Grafana (пароль Ditto в браузер не попадает). То же самое вручную:

Экран пишет в Ditto, расчёт читает оттуда на каждом шаге:

```bash
# пароль: DITTO_PASSWORD в deploy/compose/.env
curl -u ditto:ПАРОЛЬ -X PUT -H 'Content-Type: application/json' \
  http://localhost:8080/api/2/things/org.kvgorki:pump-02/features/control/properties/enabled -d 'false'

curl -u ditto:ПАРОЛЬ -X PUT -H 'Content-Type: application/json' \
  http://localhost:8080/api/2/things/org.kvgorki:sump-01/features/control/properties/inflow_m3h -d '324'
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

## Откуда числа

Параметры — из «Плана горных работ разработки запасов месторождения «Кварцитовые Горки»», стр. 131–134 ([PDF](https://hearings.ndbecology.gov.kz/Public/PubHearings/LoadFile/239849)): насосы ЦНС 300×480 (300 м³/ч, 480 м, двигатель 630 кВт), фактический приток 65–70 м³/ч, максимальный 108 м³/ч, норма откачки суточного притока за 20 ч, автоматическое включение насосов по уровню. Вместимость водосборника, уровни пуска/останова и КПД в проекте не указаны — это допущения, они перечислены в начале `simulator.py`.
