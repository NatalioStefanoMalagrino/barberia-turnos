// =====================================================================
//  Formulario de reserva (JavaScript sin frameworks).
//
//  Flujo: el usuario elige servicio y barbero -> elige un día ->
//  pedimos a la API los horarios libres -> elige hora -> completa datos
//  -> POST /api/turnos. La validación "de verdad" la hace el servidor;
//  acá solo guiamos al usuario.
// =====================================================================
(() => {
  const DIAS_A_MOSTRAR = 14;
  const form = document.getElementById("form-reserva");
  const contDias = document.getElementById("dias");
  const contHorarios = document.getElementById("horarios");
  const btn = document.getElementById("btn-reservar");
  const error = document.getElementById("error-reserva");

  let diaElegido = null;     // "YYYY-MM-DD"
  let inicioElegido = null;  // ISO con zona horaria, tal como lo devuelve la API

  const valor = (nombre) => form.querySelector(`[name="${nombre}"]:checked`)?.value ?? "";
  const aISO = (d) => d.toLocaleDateString("en-CA"); // en-CA formatea como YYYY-MM-DD

  // ------------------------------------------------ días (próximas 2 semanas)
  function dibujarDias() {
    const hoy = new Date();
    for (let i = 0; i < DIAS_A_MOSTRAR; i++) {
      const d = new Date(hoy.getFullYear(), hoy.getMonth(), hoy.getDate() + i);
      const b = document.createElement("button");
      b.type = "button";
      b.className = "dia";
      b.dataset.fecha = aISO(d);
      b.setAttribute("aria-pressed", "false");
      const nombre = i === 0 ? "hoy" : d.toLocaleDateString("es-AR", { weekday: "short" }).replace(".", "");
      b.innerHTML = `<small>${nombre}</small><strong>${d.getDate()}</strong>`;
      b.addEventListener("click", () => elegirDia(b.dataset.fecha));
      contDias.appendChild(b);
    }
  }

  function elegirDia(fecha) {
    diaElegido = fecha;
    contDias.querySelectorAll(".dia").forEach((b) =>
      b.setAttribute("aria-pressed", String(b.dataset.fecha === fecha)));
    cargarHorarios();
  }

  // ----------------------------------------------------- horarios libres
  let pedidoActual = 0; // evita que una respuesta vieja pise a una nueva
  async function cargarHorarios() {
    inicioElegido = null;
    actualizarBoton();
    if (!diaElegido) return;
    const nro = ++pedidoActual;
    contHorarios.innerHTML = `<p class="horarios__vacio">Buscando horarios…</p>`;

    const params = new URLSearchParams({ servicio_id: valor("servicio_id"), fecha: diaElegido });
    if (valor("barbero_id")) params.set("barbero_id", valor("barbero_id"));

    try {
      const r = await fetch(`/api/disponibilidad?${params}`);
      const datos = await r.json();
      if (nro !== pedidoActual) return;
      contHorarios.innerHTML = "";
      if (!datos.horarios.length) {
        contHorarios.innerHTML = `<p class="horarios__vacio">No hay horarios libres este día. Probá con otro.</p>`;
        return;
      }
      for (const h of datos.horarios) {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "hora";
        b.textContent = h.hora;
        b.setAttribute("aria-pressed", "false");
        b.addEventListener("click", () => {
          inicioElegido = h.inicio;
          contHorarios.querySelectorAll(".hora").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
          actualizarBoton();
        });
        contHorarios.appendChild(b);
      }
    } catch {
      contHorarios.innerHTML = `<p class="horarios__vacio">No pudimos cargar los horarios. Revisá tu conexión.</p>`;
    }
  }

  function actualizarBoton() {
    btn.disabled = !inicioElegido;
    btn.textContent = inicioElegido ? "Confirmar turno" : "Elegí un horario";
  }

  // Si cambia el servicio o el barbero, los horarios cambian: recargamos.
  form.querySelectorAll('[name="servicio_id"], [name="barbero_id"]').forEach((i) =>
    i.addEventListener("change", cargarHorarios));

  // ------------------------------------------------------------ reservar
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    error.hidden = true;
    const nombre = form.nombre.value.trim();
    const telefono = form.telefono.value.trim();
    if (nombre.length < 2 || telefono.replace(/\D/g, "").length < 8) {
      mostrarError("Completá tu nombre y un celular válido.");
      return;
    }
    btn.disabled = true;
    btn.textContent = "Reservando…";

    const cuerpo = {
      servicio_id: Number(valor("servicio_id")),
      barbero_id: valor("barbero_id") ? Number(valor("barbero_id")) : null,
      inicio: inicioElegido,
      nombre, telefono,
      email: form.email.value.trim() || null,
    };

    try {
      const r = await fetch("/api/turnos", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(cuerpo),
      });
      const datos = await r.json();
      if (!r.ok) {
        // 409 = el horario se ocupó mientras el usuario completaba el form.
        const msg = typeof datos.detail === "string" ? datos.detail : "Revisá los datos ingresados.";
        mostrarError(msg);
        if (r.status === 409) cargarHorarios();
        actualizarBoton();
        return;
      }
      mostrarConfirmacion(datos);
    } catch {
      mostrarError("No pudimos conectar. Probá de nuevo.");
      actualizarBoton();
    }
  });

  function mostrarError(msg) {
    error.textContent = msg;
    error.hidden = false;
  }

  function mostrarConfirmacion(t) {
    const d = new Date(t.inicio);
    const dia = d.toLocaleDateString("es-AR", { weekday: "long", day: "numeric", month: "long" });
    const hora = d.toLocaleTimeString("es-AR", { hour: "2-digit", minute: "2-digit" });
    document.getElementById("confirmacion-detalle").textContent =
      `${t.servicio} con ${t.barbero}, el ${dia} a las ${hora} h.`;
    document.getElementById("confirmacion-link").href = t.link_turno;
    form.hidden = true;
    document.getElementById("confirmacion").hidden = false;
    document.getElementById("reservar").scrollIntoView({ behavior: "smooth" });
  }

  dibujarDias();
})();
