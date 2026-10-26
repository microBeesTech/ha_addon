import json

import pytest

from mqtt_bridge import config


def _options(tmp_path, **over):
    opts = {
        "mqtt_host": "test.microbees.com",
        "mqtt_port": 1883,
        "mqtt_username": "u",
        "mqtt_password": "segreta",
        "topic": "sensor.in.31",
        "smartgate_serial": "",
        "heartbeat_interval": 300,
        "send_device_status": True,
        "log_level": "info",
    } | over
    path = tmp_path / "options.json"
    path.write_text(json.dumps(opts))
    return path


def test_serial_da_configurazione_ha_la_precedenza(tmp_path):
    s = config.load_settings(_options(tmp_path, smartgate_serial="AA:BB:CC:DD:EE:FF"), {"SUPERVISOR_TOKEN": "t"})
    assert s.smartgate_serial == "aa:bb:cc:dd:ee:ff"


def test_serial_vuoto_usa_il_mac_dell_host(tmp_path, monkeypatch):
    monkeypatch.setattr(config.uuid, "getnode", lambda: 0x30AE7BEA8680)
    s = config.load_settings(_options(tmp_path), {"SUPERVISOR_TOKEN": "t"})
    assert s.smartgate_serial == "30:ae:7b:ea:86:80"


def test_senza_token_del_supervisor_non_parte(tmp_path):
    with pytest.raises(RuntimeError, match="SUPERVISOR_TOKEN"):
        config.load_settings(_options(tmp_path), {})


def test_password_e_token_non_finiscono_nei_log(tmp_path):
    s = config.load_settings(_options(tmp_path), {"SUPERVISOR_TOKEN": "token-segreto"})
    assert "segreta" not in repr(s) and "token-segreto" not in repr(s)
