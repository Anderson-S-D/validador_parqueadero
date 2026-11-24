from pydantic import BaseModel, Field, field_validator
from typing import Literal, Optional
import re

EstadoPlaca = Literal["A", "P", "N"]
TipoVehiculo = Literal["CARRO", "MOTO"]


class VehiculoCreate(BaseModel):
    placa: str = Field(..., min_length=5, max_length=7)
    propietario: str = Field(default="Visitante", min_length=2, max_length=80)
    tipo: TipoVehiculo = "CARRO"
    estado: EstadoPlaca = "P"
    notas: Optional[str] = ""

    @field_validator("placa")
    @classmethod
    def validar_placa(cls, v: str) -> str:
        limpia = re.sub(r"[^A-Z0-9]", "", v.upper())
        if not re.match(r"^[A-Z]{3}[0-9]{2}[0-9A-Z]$", limpia):
            raise ValueError("Formato de placa inválido (use ABC123 o ABC12D)")
        return limpia


class VehiculoUpdate(BaseModel):
    propietario: Optional[str] = None
    tipo: Optional[TipoVehiculo] = None
    estado: Optional[EstadoPlaca] = None
    notas: Optional[str] = None


class PagoRequest(BaseModel):
    placa: str
    abrir_barrera: bool = True


class SimularLecturaRequest(BaseModel):
    placa: str


class ConfiguracionSistema(BaseModel):
    tarifa_minuto_carro: float = Field(..., ge=0)
    tarifa_minuto_moto: float = Field(..., ge=0)
    minutos_gracia: int = Field(..., ge=0)
    puerto_esp32: str
    url_camara: str
    cooldown_segundos: int = Field(..., ge=1, le=60)