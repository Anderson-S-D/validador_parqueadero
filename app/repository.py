import json
import os
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional


class ParkingRepository:
    def __init__(self, base_dir: str):
        self._lock = threading.RLock()
        self._db_path = os.path.join(base_dir, "parking_db.json")
        self._legacy_path = os.path.join(base_dir, "base_placas.json")
        self._inicializar_archivos()

    def _inicializar_archivos(self) -> None:
        with self._lock:
            if not os.path.exists(self._db_path):
                placas_iniciales: Dict[str, Any] = {}
                if os.path.exists(self._legacy_path):
                    try:
                        with open(self._legacy_path, "r", encoding="utf-8") as f:
                            raw = json.load(f)
                        for placa, estado in raw.items():
                            placas_iniciales[placa.upper()] = {
                                "placa": placa.upper(),
                                "propietario": "Usuario Registrado",
                                "tipo": "MOTO" if placa[-1].isalpha() else "CARRO",
                                "estado": estado if estado in ("A", "P", "N") else "N",
                                "hora_ingreso": datetime.now().isoformat(),
                                "notas": "Importado desde base_placas.json",
                            }
                    except Exception:
                        placas_iniciales = {}

                data_inicial = {
                    "config": {
                        "tarifa_minuto_carro": 120.0,
                        "tarifa_minuto_moto": 80.0,
                        "minutos_gracia": 10,
                        "puerto_esp32": "COM7",
                        "url_camara": "0",
                        "cooldown_segundos": 8,
                    },
                    "vehiculos": placas_iniciales,
                    "logs": [],
                    "recaudo_total": 0.0,
                }
                self._guardar_atomico(data_inicial)
            else:
                self._sincronizar_legacy(self._leer_db())

    def _leer_db(self) -> Dict[str, Any]:
        defaults: Dict[str, Any] = {
            "config": {
                "tarifa_minuto_carro": 120.0,
                "tarifa_minuto_moto": 80.0,
                "minutos_gracia": 10,
                "puerto_esp32": "COM7",
                "url_camara": "0",
                "cooldown_segundos": 8,
            },
            "vehiculos": {},
            "logs": [],
            "recaudo_total": 0.0,
        }
        try:
            with open(self._db_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                data = {}
        except (json.JSONDecodeError, OSError):
            data = {}

        modificado = False
        for clave, valor in defaults.items():
            if clave not in data:
                data[clave] = valor
                modificado = True

        if isinstance(data.get("config"), dict):
            for k, v in defaults["config"].items():
                if k not in data["config"]:
                    data["config"][k] = v
                    modificado = True

        if modificado:
            self._guardar_atomico(data)

        return data

    def _guardar_atomico(self, data: Dict[str, Any]) -> None:
        tmp_db = f"{self._db_path}.tmp"
        with open(tmp_db, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_db, self._db_path)
        self._sincronizar_legacy(data)

    def _sincronizar_legacy(self, data: Dict[str, Any]) -> None:
        legacy_map = {
            placa: info["estado"]
            for placa, info in data.get("vehiculos", {}).items()
            if info.get("estado") in ("A", "P")
        }
        tmp_legacy = f"{self._legacy_path}.tmp"
        with open(tmp_legacy, "w", encoding="utf-8") as f:
            json.dump(legacy_map, f, indent=2, ensure_ascii=False)
        os.replace(tmp_legacy, self._legacy_path)

    def obtener_todo(self) -> Dict[str, Any]:
        with self._lock:
            return self._leer_db()

    def obtener_vehiculo(self, placa: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._leer_db().get("vehiculos", {}).get(placa.upper())

    def guardar_vehiculo(self, vehiculo: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            data = self._leer_db()
            data["vehiculos"][vehiculo["placa"]] = vehiculo
            self._guardar_atomico(data)
            return vehiculo

    def eliminar_vehiculo(self, placa: str) -> bool:
        with self._lock:
            data = self._leer_db()
            if placa.upper() in data["vehiculos"]:
                del data["vehiculos"][placa.upper()]
                self._guardar_atomico(data)
                return True
            return False

    def registrar_evento(self, evento: Dict[str, Any]) -> None:
        with self._lock:
            data = self._leer_db()
            data["logs"].insert(0, evento)
            data["logs"] = data["logs"][:200]
            self._guardar_atomico(data)

    def sumar_recaudo(self, monto: float) -> None:
        with self._lock:
            data = self._leer_db()
            data["recaudo_total"] = round(data.get("recaudo_total", 0.0) + monto, 2)
            self._guardar_atomico(data)

    def actualizar_config(self, nueva_config: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            data = self._leer_db()
            data["config"].update(nueva_config)
            self._guardar_atomico(data)
            return data["config"]