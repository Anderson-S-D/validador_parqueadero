import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.hardware import HardwareBridge
from app.repository import ParkingRepository
from app.schemas import (
    ConfiguracionSistema,
    PagoRequest,
    SimularLecturaRequest,
    VehiculoCreate,
    VehiculoUpdate,
)
from app.services import ParkingService

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
repo = ParkingRepository(BASE_DIR)
hardware = HardwareBridge(repo)
service = ParkingService(repo, hardware)


@asynccontextmanager
async def lifespan(app: FastAPI):
    hardware.iniciar()
    yield
    hardware.detener()


app = FastAPI(title="Portal Validador de Parqueadero ESP32", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE_DIR, "static", "index.html"))


@app.get("/api/dashboard")
def get_dashboard():
    return service.obtener_estado_dashboard()


@app.get("/api/vehiculos")
def get_vehiculos():
    return service.listar_vehiculos()


@app.post("/api/vehiculos")
def create_vehiculo(payload: VehiculoCreate):
    return service.registrar_o_ingresar_vehiculo(payload)


@app.put("/api/vehiculos/{placa}")
def update_vehiculo(placa: str, payload: VehiculoUpdate):
    try:
        return service.actualizar_vehiculo(placa, payload)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.delete("/api/vehiculos/{placa}")
def delete_vehiculo(placa: str):
    if not service.eliminar_vehiculo(placa):
        raise HTTPException(status_code=404, detail="Placa no encontrada")
    return {"ok": True}


@app.get("/api/caja/{placa}")
def cotizar_placa(placa: str):
    return service.calcular_tarifa(placa)


@app.post("/api/caja/pagar")
def pagar_placa(payload: PagoRequest):
    try:
        return service.procesar_pago(payload.placa, payload.abrir_barrera)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/hardware/abrir-manual")
def abrir_manual():
    return service.apertura_manual_emergencia()


@app.post("/api/hardware/simular")
def simular_lectura(payload: SimularLecturaRequest):
    return service.simular_deteccion_placa(payload.placa)


@app.post("/api/hardware/reconectar-serial")
def reconectar_serial():
    ok = hardware.conectar_serial()
    return {"conectado": ok, "mensaje": hardware.ultimo_mensaje_esp32}


@app.put("/api/config")
def actualizar_config(payload: ConfiguracionSistema):
    cfg = repo.actualizar_config(payload.model_dump())
    hardware.conectar_serial()
    return cfg


def _generador_mjpeg():
    while True:
        frame = hardware.obtener_frame()
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
        time.sleep(0.05)


@app.get("/api/video_feed")
def video_feed():
    return StreamingResponse(_generador_mjpeg(), media_type="multipart/x-mixed-replace; boundary=frame")