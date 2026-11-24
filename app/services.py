from datetime import datetime
from typing import Any, Dict, List
import math

from app.hardware import HardwareBridge
from app.repository import ParkingRepository
from app.schemas import VehiculoCreate, VehiculoUpdate


class ParkingService:
    def __init__(self, repo: ParkingRepository, hardware: HardwareBridge):
        self.repo = repo
        self.hardware = hardware

    def obtener_estado_dashboard(self) -> Dict[str, Any]:
        data = self.repo.obtener_todo()
        vehiculos = list(data["vehiculos"].values())
        al_dia = sum(1 for v in vehiculos if v["estado"] == "A")
        pendientes = sum(1 for v in vehiculos if v["estado"] == "P")
        no_reg = sum(1 for v in vehiculos if v["estado"] == "N")

        return {
            "kpis": {
                "total_vehiculos": len(vehiculos),
                "al_dia": al_dia,
                "pendientes": pendientes,
                "no_registrados": no_reg,
                "recaudo_total": data.get("recaudo_total", 0.0),
            },
            "hardware": {
                "serial_conectado": self.hardware.serial_conectado,
                "mensaje_esp32": self.hardware.ultimo_mensaje_esp32,
                "camara_activa": self.hardware.camara_activa,
                "ultima_deteccion": self.hardware.ultima_deteccion,
            },
            "config": data["config"],
            "logs_recientes": data["logs"][:25],
        }

    def listar_vehiculos(self) -> List[Dict[str, Any]]:
        data = self.repo.obtener_todo()
        resultado = []
        for v in data["vehiculos"].values():
            item = dict(v)
            item["liquidacion"] = self.calcular_tarifa(item["placa"])
            resultado.append(item)
        return resultado

    def registrar_o_ingresar_vehiculo(self, payload: VehiculoCreate) -> Dict[str, Any]:
        existente = self.repo.obtener_vehiculo(payload.placa)
        hora_ingreso = (
            existente.get("hora_ingreso")
            if existente and existente.get("estado") == "P" and payload.estado == "P"
            else datetime.now().isoformat()
        )
        registro = {
            "placa": payload.placa,
            "propietario": payload.propietario,
            "tipo": payload.tipo,
            "estado": payload.estado,
            "hora_ingreso": hora_ingreso,
            "notas": payload.notas or "",
        }
        guardado = self.repo.guardar_vehiculo(registro)
        self.repo.registrar_evento({
            "timestamp": datetime.now().isoformat(),
            "placa": payload.placa,
            "estado": payload.estado,
            "origen": "PORTAL_WEB",
            "detalle": f"Registro/Ingreso actualizado a estado {payload.estado}",
            "hardware_tx": False,
        })
        return guardado

    def actualizar_vehiculo(self, placa: str, payload: VehiculoUpdate) -> Dict[str, Any]:
        actual = self.repo.obtener_vehiculo(placa)
        if not actual:
            raise KeyError("Placa no encontrada")
        if payload.propietario is not None:
            actual["propietario"] = payload.propietario
        if payload.tipo is not None:
            actual["tipo"] = payload.tipo
        if payload.notas is not None:
            actual["notas"] = payload.notas
        if payload.estado is not None:
            if payload.estado == "P" and actual["estado"] != "P":
                actual["hora_ingreso"] = datetime.now().isoformat()
            actual["estado"] = payload.estado
        return self.repo.guardar_vehiculo(actual)

    def eliminar_vehiculo(self, placa: str) -> bool:
        return self.repo.eliminar_vehiculo(placa)

    def calcular_tarifa(self, placa: str) -> Dict[str, Any]:
        data = self.repo.obtener_todo()
        vehiculo = data["vehiculos"].get(placa.upper())
        config = data["config"]

        if not vehiculo:
            return {"placa": placa.upper(), "minutos": 0, "monto": 0.0, "estado": "N"}

        if vehiculo["estado"] != "P":
            return {
                "placa": vehiculo["placa"],
                "minutos": 0,
                "monto": 0.0,
                "estado": vehiculo["estado"],
            }

        inicio = datetime.fromisoformat(vehiculo["hora_ingreso"])
        minutos_totales = max(1, math.ceil((datetime.now() - inicio).total_seconds() / 60.0))
        gracia = int(config.get("minutos_gracia", 10))
        minutos_cobrables = max(0, minutos_totales - gracia)
        tarifa_min = (
            float(config["tarifa_minuto_moto"])
            if vehiculo["tipo"] == "MOTO"
            else float(config["tarifa_minuto_carro"])
        )
        monto = round(minutos_cobrables * tarifa_min, 0)

        return {
            "placa": vehiculo["placa"],
            "tipo": vehiculo["tipo"],
            "hora_ingreso": vehiculo["hora_ingreso"],
            "minutos": minutos_totales,
            "minutos_cobrables": minutos_cobrables,
            "tarifa_minuto": tarifa_min,
            "monto": monto,
            "estado": vehiculo["estado"],
        }

    def procesar_pago(self, placa: str, abrir_barrera: bool) -> Dict[str, Any]:
        placa_norm = placa.upper()
        vehiculo = self.repo.obtener_vehiculo(placa_norm)
        if not vehiculo:
            raise KeyError("La placa no está registrada en el sistema")

        liquidacion = self.calcular_tarifa(placa_norm)
        monto = liquidacion["monto"]

        vehiculo["estado"] = "A"
        self.repo.guardar_vehiculo(vehiculo)
        self.repo.sumar_recaudo(monto)

        self.repo.registrar_evento({
            "timestamp": datetime.now().isoformat(),
            "placa": placa_norm,
            "estado": "A",
            "origen": "CAJA_WEB",
            "detalle": f"Pago liquidado por ${monto:,.0f} ({liquidacion['minutos']} min)",
            "hardware_tx": abrir_barrera,
        })

        if abrir_barrera:
            self.hardware.enviar_comando_esp32("A", placa_norm, origen="CAJA_SALIDA")

        return {"vehiculo": vehiculo, "cobro": liquidacion}

    def apertura_manual_emergencia(self) -> Dict[str, Any]:
        return self.hardware.enviar_comando_esp32("A", "MANUAL", origen="CONTROL_MANUAL")

    def simular_deteccion_placa(self, placa: str) -> Dict[str, Any]:
        placa_norm = placa.upper()
        vehiculo = self.repo.obtener_vehiculo(placa_norm)
        estado = vehiculo["estado"] if vehiculo else "N"
        return self.hardware.enviar_comando_esp32(estado, placa_norm, origen="SIMULADOR_WEB")