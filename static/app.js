let vehiculosCache = [];
let placaSeleccionadaCaja = null;

document.querySelectorAll(".nav-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".nav-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");
  });
});

function badgeEstado(estado) {
  if (estado === "A") return `<span class="pill on">A - Validado</span>`;
  if (estado === "P") return `<span class="pill" style="background:rgba(245,158,11,.2);color:#f59e0b">P - Pendiente</span>`;
  return `<span class="pill off">N - Sin Registro</span>`;
}

function actualizarSimuladorHardware(det) {
  const l1 = document.getElementById("lcd-line-1");
  const l2 = document.getElementById("lcd-line-2");
  const servo = document.getElementById("servo-estado");
  const leds = ["led-b1", "led-b2", "led-am", "led-ve"];
  leds.forEach((id) => document.getElementById(id).classList.remove("on"));

  if (!det || !det.estado || det.estado === "ESPERA") {
    l1.textContent = "PARQUEADERO";
    l2.textContent = "ESPERANDO PLACA";
    document.getElementById("led-b1").classList.add("on");
    document.getElementById("led-b2").classList.add("on");
    servo.textContent = "CERRADA (0°)";
    return;
  }

  l1.textContent = det.placa;
  if (det.estado === "A") {
    l2.textContent = "ACCESO PERMITIDO";
    document.getElementById("led-ve").classList.add("on");
    servo.textContent = "ABIERTA (90°)";
  } else if (det.estado === "P") {
    l2.textContent = "PAGO PENDIENTE";
    document.getElementById("led-am").classList.add("on");
    servo.textContent = "CERRADA (0°)";
  } else {
    l2.textContent = "NO REGISTRADA";
    document.getElementById("led-am").classList.add("on");
    document.getElementById("led-b1").classList.add("on");
    servo.textContent = "CERRADA (0°)";
  }
}

async function refrescarDashboard() {
  const res = await fetch("/api/dashboard");
  const data = await res.json();

  document.getElementById("kpi-total").textContent = data.kpis.total_vehiculos;
  document.getElementById("kpi-al-dia").textContent = data.kpis.al_dia;
  document.getElementById("kpi-pendientes").textContent = data.kpis.pendientes;
  document.getElementById("kpi-recaudo").textContent = `$${data.kpis.recaudo_total.toLocaleString("es-CO")}`;

  const elSerial = document.getElementById("status-serial");
  elSerial.textContent = data.hardware.serial_conectado ? "Conectado" : "Simulación";
  elSerial.className = `pill ${data.hardware.serial_conectado ? "on" : "off"}`;

  const elCam = document.getElementById("status-cam");
  elCam.textContent = data.hardware.camara_activa ? "Activa" : "Sin señal";
  elCam.className = `pill ${data.hardware.camara_activa ? "on" : "off"}`;

  document.getElementById("status-msg").textContent = data.hardware.mensaje_esp32;
  actualizarSimuladorHardware(data.hardware.ultima_deteccion);

  const miniLogs = document.getElementById("mini-logs");
  miniLogs.innerHTML = data.logs_recientes
    .slice(0, 6)
    .map((l) => `<li><strong>${l.placa}</strong> [${l.estado}] - ${l.detalle}</li>`)
    .join("");

  const tablaLogs = document.getElementById("tabla-logs");
  tablaLogs.innerHTML = data.logs_recientes
    .map(
      (l) => `<tr>
        <td>${new Date(l.timestamp).toLocaleString("es-CO")}</td>
        <td><strong>${l.placa}</strong></td>
        <td>${badgeEstado(l.estado)}</td>
        <td>${l.origen}</td>
        <td>${l.detalle}</td>
        <td>${l.hardware_tx ? "OK" : "Simulado"}</td>
      </tr>`
    )
    .join("");

  if (!document.activeElement || !document.activeElement.id.startsWith("cfg-")) {
    document.getElementById("cfg-tarifa-carro").value = data.config.tarifa_minuto_carro;
    document.getElementById("cfg-tarifa-moto").value = data.config.tarifa_minuto_moto;
    document.getElementById("cfg-gracia").value = data.config.minutos_gracia;
    document.getElementById("cfg-puerto").value = data.config.puerto_esp32;
    document.getElementById("cfg-camara").value = data.config.url_camara;
    document.getElementById("cfg-cooldown").value = data.config.cooldown_segundos;
  }
}

async function refrescarVehiculos() {
  const res = await fetch("/api/vehiculos");
  vehiculosCache = await res.json();
  renderizarTablasVehiculos();
}

function renderizarTablasVehiculos() {
  const filtro = document.getElementById("filtro-placa").value.toUpperCase();
  const filtrados = vehiculosCache.filter(
    (v) => v.placa.includes(filtro) || v.propietario.toUpperCase().includes(filtro)
  );

  document.getElementById("tabla-vehiculos").innerHTML = filtrados
    .map(
      (v) => `<tr>
        <td><strong>${v.placa}</strong></td>
        <td>${v.propietario}</td>
        <td>${v.tipo}</td>
        <td>${badgeEstado(v.estado)}</td>
        <td>${v.estado === "P" ? `${v.liquidacion.minutos} min` : "-"}</td>
        <td>
          <button class="btn-success btn-sm" onclick="cambiarEstado('${v.placa}', 'A')">Validar (A)</button>
          <button class="btn-secondary btn-sm" onclick="cambiarEstado('${v.placa}', 'P')">Ingreso (P)</button>
          <button class="btn-danger btn-sm" onclick="eliminarPlaca('${v.placa}')">Eliminar</button>
        </td>
      </tr>`
    )
    .join("");

  const pendientes = vehiculosCache.filter((v) => v.estado === "P");
  document.getElementById("tabla-pendientes").innerHTML = pendientes
    .map(
      (v) => `<tr>
        <td><strong>${v.placa}</strong></td>
        <td>${v.tipo}</td>
        <td>${v.liquidacion.minutos} min</td>
        <td>$${v.liquidacion.monto.toLocaleString("es-CO")}</td>
        <td><button class="btn-primary btn-sm" onclick="cargarEnCaja('${v.placa}')">Liquidar</button></td>
      </tr>`
    )
    .join("");
}

async function cambiarEstado(placa, estado) {
  await fetch(`/api/vehiculos/${placa}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ estado }),
  });
  await Promise.all([refrescarVehiculos(), refrescarDashboard()]);
}

async function eliminarPlaca(placa) {
  await fetch(`/api/vehiculos/${placa}`, { method: "DELETE" });
  await Promise.all([refrescarVehiculos(), refrescarDashboard()]);
}

async function cargarEnCaja(placa) {
  const res = await fetch(`/api/caja/${placa}`);
  const info = await res.json();
  placaSeleccionadaCaja = placa;
  document.getElementById("rec-placa").textContent = info.placa;
  document.getElementById("rec-tipo").textContent = info.tipo || "CARRO";
  document.getElementById("rec-minutos").textContent = info.minutos;
  document.getElementById("rec-cobrables").textContent = info.minutos_cobrables ?? 0;
  document.getElementById("rec-monto").textContent = `$${info.monto.toLocaleString("es-CO")}`;
  document.getElementById("detalle-cobro").classList.remove("hidden");
}

document.getElementById("form-vehiculo").addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = {
    placa: document.getElementById("v-placa").value,
    propietario: document.getElementById("v-propietario").value,
    tipo: document.getElementById("v-tipo").value,
    estado: document.getElementById("v-estado").value,
  };
  const res = await fetch("/api/vehiculos", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json();
    alert(err.detail[0]?.msg || "Error al guardar placa");
    return;
  }
  e.target.reset();
  await Promise.all([refrescarVehiculos(), refrescarDashboard()]);
});

document.getElementById("form-simulador").addEventListener("submit", async (e) => {
  e.preventDefault();
  const placa = document.getElementById("sim-placa").value;
  await fetch("/api/hardware/simular", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ placa }),
  });
  e.target.reset();
  await refrescarDashboard();
});

document.getElementById("btn-abrir-manual").addEventListener("click", async () => {
  await fetch("/api/hardware/abrir-manual", { method: "POST" });
  await refrescarDashboard();
});

document.getElementById("btn-reconectar").addEventListener("click", async () => {
  await fetch("/api/hardware/reconectar-serial", { method: "POST" });
  await refrescarDashboard();
});

document.getElementById("form-cotizar").addEventListener("submit", async (e) => {
  e.preventDefault();
  const placa = document.getElementById("caja-placa").value.toUpperCase();
  await cargarEnCaja(placa);
});

document.getElementById("btn-confirmar-pago").addEventListener("click", async () => {
  if (!placaSeleccionadaCaja) return;
  const abrir_barrera = document.getElementById("rec-abrir").checked;
  const res = await fetch("/api/caja/pagar", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ placa: placaSeleccionadaCaja, abrir_barrera }),
  });
  if (res.ok) {
    document.getElementById("detalle-cobro").classList.add("hidden");
    placaSeleccionadaCaja = null;
    await Promise.all([refrescarVehiculos(), refrescarDashboard()]);
  }
});

document.getElementById("form-config").addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = {
    tarifa_minuto_carro: parseFloat(document.getElementById("cfg-tarifa-carro").value),
    tarifa_minuto_moto: parseFloat(document.getElementById("cfg-tarifa-moto").value),
    minutos_gracia: parseInt(document.getElementById("cfg-gracia").value, 10),
    puerto_esp32: document.getElementById("cfg-puerto").value,
    url_camara: document.getElementById("cfg-camara").value,
    cooldown_segundos: parseInt(document.getElementById("cfg-cooldown").value, 10),
  };
  await fetch("/api/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  await refrescarDashboard();
});

document.getElementById("filtro-placa").addEventListener("input", renderizarTablasVehiculos);

refrescarDashboard();
refrescarVehiculos();
setInterval(() => {
  refrescarDashboard();
  refrescarVehiculos();
}, 2500);