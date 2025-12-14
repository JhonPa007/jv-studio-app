# Documentación de Endpoints de la Aplicación

A continuación se detallan los endpoints de la API y las rutas de la aplicación, sus métodos HTTP y su funcionalidad.

---

## Autenticación

### `/`
- **Métodos:** `GET`
- **Requiere Login:** Sí
- **Función:** Muestra el dashboard principal. Para administradores, muestra KPIs de ventas, citas, stock, etc. Para colaboradores, muestra las próximas citas. También gestiona alertas de cumpleaños.

### `/login`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** No
- **Función:**
    - `GET`: Muestra el formulario de inicio de sesión.
    - `POST`: Procesa el formulario de inicio de sesión, valida las credenciales del usuario y lo redirige a la selección de sucursal o al dashboard.

### `/auth/seleccionar-sucursal`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí
- **Función:**
    - `GET`: Muestra la página para que el usuario seleccione la sucursal en la que desea trabajar.
    - `POST`: Procesa la selección de sucursal y la guarda en la sesión del usuario.

### `/cambiar-sucursal/<int:sucursal_id>`
- **Métodos:** `GET`
- **Requiere Login:** Sí
- **Función:** Permite al usuario cambiar la sucursal activa en la sesión actual sin necesidad de cerrar sesión.

### `/logout`
- **Métodos:** `GET`
- **Requiere Login:** Sí
- **Función:** Cierra la sesión del usuario actual y lo redirige a la página de login.

---

## Gestión de Clientes

### `/api/clientes/registrar_comunicacion`
- **Métodos:** `POST`
- **Requiere Login:** Sí
- **Función (API):** Registra que se ha enviado una comunicación (saludo de cumpleaños, etc.) a un cliente para no volver a enviarla en el mismo año.

### `/clientes`
- **Métodos:** `GET`
- **Requiere Login:** Sí
- **Función:** Muestra una lista de todos los clientes. Permite la búsqueda por nombre, apellidos o número de documento.

### `/clientes/nuevo`
- **Métodos. `GET`, `POST`
- **Requiere Login:** Sí
- **Función:**
    - `GET`: Muestra el formulario para registrar un nuevo cliente.
    - `POST`: Procesa el registro de un nuevo cliente en la base de datos.

### `/clientes/ver/<int:cliente_id>`
- **Métodos:** `GET`
- **Requiere Login:** Sí
- **Función:** Muestra una vista de solo lectura con los detalles de un cliente específico.

### `/clientes/editar/<int:cliente_id>`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí
- **Función:**
    - `GET`: Muestra el formulario para editar los datos de un cliente existente.
    - `POST`: Procesa la actualización de los datos del cliente.

### `/clientes/eliminar/<int:cliente_id>`
- **Métodos:** `GET`, `POST` (Idealmente solo `POST`)
- **Requiere Login:** Sí
- **Función:** Elimina un cliente de la base de datos. No se puede eliminar si tiene un historial asociado (ventas, citas, etc.).

### `/api/clientes/actualizar-campana`
- **Métodos:** `POST`
- **Requiere Login:** Sí
- **Función (API):** Recibe y procesa la respuesta de un cliente a una campaña de actualización de datos (ej. confirmar o actualizar fecha de nacimiento).

### `/api/clientes/buscar_por_documento`
- **Métodos:** `GET`
- **Requiere Login:** Sí
- **Función (API):** Busca un cliente por su número de documento y devuelve sus datos en formato JSON.

### `/api/clientes/<int:cliente_id>/puntos`
- **Métodos:** `GET`
- **Requiere Login:** Sí
- **Función (API):** Obtiene y devuelve el saldo de puntos de fidelidad de un cliente específico.

### `/clientes/importar`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí, Admin
- **Función:**
    - `GET`: Muestra la página para subir un archivo Excel con datos de clientes.
    - `POST`: Procesa el archivo Excel e importa los clientes a la base de datos.

### `/clientes/detalle/<int:cliente_id>`
- **Métodos:** `GET`
- **Requiere Login:** Sí
- **Función:** Muestra una página de detalle del cliente con su historial de visitas (ventas) y membresías.

---

## Gestión de Servicios y Categorías

### `/servicios/categorias`
- **Métodos:** `GET`
- **Requiere Login:** Sí
- **Función:** Muestra la lista de todas las categorías de servicios.

### `/servicios/categorias/nueva`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí
- **Función:**
    - `GET`: Muestra el formulario para crear una nueva categoría de servicio.
    - `POST`: Procesa la creación de la nueva categoría.

### `/servicios/categorias/editar/<int:categoria_id>`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí
- **Función:**
    - `GET`: Muestra el formulario para editar una categoría de servicio.
    - `POST`: Procesa la actualización de la categoría.

### `/servicios/categorias/eliminar/<int:categoria_id>`
- **Métodos:** `GET`
- **Requiere Login:** Sí
- **Función:** Elimina una categoría de servicio.

### `/servicios`
- **Métodos:** `GET`
- **Requiere Login:** Sí
- **Función:** Muestra la lista de todos los servicios disponibles, incluyendo su categoría.

### `/servicios/nuevo`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí
- **Función:**
    - `GET`: Muestra el formulario para registrar un nuevo servicio.
    - `POST`: Procesa el registro del nuevo servicio.

### `/servicios/editar/<int:servicio_id>`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí
- **Función:**
    - `GET`: Muestra el formulario para editar un servicio existente.
    - `POST`: Procesa la actualización del servicio.

### `/servicios/toggle_activo/<int:servicio_id>`
- **Métodos:** `GET`
- **Requiere Login:** Sí
- **Función:** Activa o desactiva un servicio.

---

## Gestión de Empleados, Horarios y Ausencias

### `/empleados`
- **Métodos:** `GET`
- **Requiere Login:** Sí, Admin
- **Función:** Muestra la lista de todos los colaboradores (empleados).

### `/empleados/nuevo`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí, Admin
- **Función:** Formulario para registrar un nuevo colaborador y procesar su creación.

### `/empleados/editar/<int:empleado_id>`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí, Admin
- **Función:** Formulario para editar un colaborador existente y procesar su actualización.

### `/empleados/toggle_activo/<int:empleado_id>`
- **Métodos:** `GET`
- **Requiere Login:** Sí, Admin
- **Función:** Activa o desactiva a un colaborador.

### `/colaboradores/<int:colaborador_id>/cuotas`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí, Admin
- **Función:**
    - `GET`: Muestra la página para gestionar las cuotas de producción mensuales de un colaborador.
    - `POST`: Agrega una nueva cuota mensual.

### `/colaboradores/<int:colaborador_id>/cuotas/nueva`
- **Métodos:** `POST`
- **Requiere Login:** Sí, Admin
- **Función:** Procesa el formulario para añadir una nueva cuota mensual.

### `/colaboradores/<int:colaborador_id>/cuotas/editar/<int:cuota_id>`
- **Métodos:** `POST`
- **Requiere Login:** Sí, Admin
- **Función:** Procesa la edición de una cuota mensual existente.

### `/colaboradores/<int:colaborador_id>/cuotas/eliminar/<int:cuota_id>`
- **Métodos:** `POST`
- **Requiere Login:** Sí, Admin
- **Función:** Elimina un registro de cuota mensual.

### `/colaboradores/<int:colaborador_id>/ajustes`
- **Métodos:** `GET`
- **Requiere Login:** Sí, Admin
- **Función:** Muestra la página para gestionar ajustes de pago (bonos/descuentos) para un colaborador.

### `/colaboradores/<int:colaborador_id>/ajustes/nueva`
- **Métodos:** `POST`
- **Requiere Login:** Sí, Admin
- **Función:** Procesa la adición de un nuevo ajuste de pago.

### `/colaboradores/<int:colaborador_id>/ajustes/editar/<int:ajuste_id>`
- **Métodos:** `POST`
- **Requiere Login:** Sí, Admin
- **Función:** Procesa la edición de un ajuste de pago existente (solo si está pendiente).

### `/colaboradores/<int:colaborador_id>/ajustes/eliminar/<int:ajuste_id>`
- **Métodos:** `POST`
- **Requiere Login:** Sí, Admin
- **Función:** Elimina un ajuste de pago (solo si está pendiente).

### `/empleados/<int:empleado_id>/horarios`
- **Métodos:** `GET`
- **Requiere Login:** Sí, Admin
- **Función:** Muestra la interfaz para gestionar los turnos de trabajo semanales de un empleado.

### `/empleados/<int:empleado_id>/horarios/agregar_turno`
- **Métodos:** `POST`
- **Requiere Login:** Sí, Admin
- **Función:** Procesa la adición de un nuevo turno al horario de un empleado.

### `/horarios_empleado/eliminar/<int:horario_id>`
- **Métodos:** `GET`
- **Requiere Login:** Sí, Admin
- **Función:** Elimina un turno de trabajo específico del horario de un empleado.

### `/horarios_empleado/editar/<int:horario_id>`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí, Admin
- **Función:** Formulario para editar un turno de trabajo y procesar la actualización.

### `/empleados/<int:empleado_id>/ausencias`
- **Métodos:** `GET`
- **Requiere Login:** Sí, Admin
- **Función:** Muestra la página para gestionar las ausencias (vacaciones, permisos, etc.) de un empleado.

### `/empleados/<int:empleado_id>/ausencias/nueva`
- **Métodos:** `POST`
- **Requiere Login:** Sí, Admin
- **Función:** Procesa el registro de una nueva ausencia para un empleado.

### `/ausencias_empleado/editar/<int:ausencia_id>`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí, Admin
- **Función:** Formulario para editar una ausencia existente y procesar su actualización.

### `/ausencias_empleado/eliminar/<int:ausencia_id>`
- **Métodos:** `GET`
- **Requiere Login:** Sí, Admin
- **Función:** Elimina un registro de ausencia.

---

## Gestión de Reservas y Agenda

### `/reservas`
- **Métodos:** `GET`
- **Requiere Login:** Sí
- **Función:** Muestra una lista histórica de todas las reservas.

### `/reservas/agenda`
- **Métodos:** `GET`
- **Requiere Login:** Sí
- **Función:** Renderiza la página principal de la agenda diaria con FullCalendar.

### `/api/reservas/<int:reserva_id>`
- **Métodos:** `GET`
- **Requiere Login:** Sí
- **Función (API):** Obtiene y devuelve los detalles completos de una reserva específica en formato JSON para el modal de gestión.

### `/api/agenda_dia_data`
- **Métodos:** `GET`
- **Requiere Login:** Sí
- **Función (API):** Devuelve en formato JSON los datos de recursos (empleados) y eventos (turnos, ausencias, reservas) para un día y sucursal específicos, para alimentar FullCalendar.

### `/reservas/nueva`
- **Métodos:** `POST`
- **Requiere Login:** Sí
- **Función (API):** Procesa la creación de una nueva reserva desde una petición AJAX (JSON). Valida disponibilidad y horarios.

### `/reservas/editar/<int:reserva_id>`
- **Métodos:** `POST`
- **Requiere Login:** Sí
- **Función (API):** Procesa la edición de una reserva existente desde una petición AJAX (JSON). Valida disponibilidad.

### `/reservas/cancelar/<int:reserva_id>`
- **Métodos:** `POST`
- **Requiere Login:** Sí
- **Función (API):** Cambia el estado de una reserva a 'Cancelada por Staff'.

### `/api/reservas/<int:reserva_id>/completar`
- **Métodos:** `POST`
- **Requiere Login:** Sí
- **Función (API):** Marca una reserva como 'Completada' y devuelve una URL para redirigir al formulario de venta.

### `/reservas/reagendar`
- **Métodos:** `POST`
- **Requiere Login:** Sí, Admin
- **Función (API):** Procesa el movimiento o redimensión de una reserva en el calendario (drag & drop).

---

## Gestión de Productos, Marcas y Proveedores

### `/productos/categorias`
- **Métodos:** `GET`
- **Requiere Login:** Sí
- **Función:** Muestra la lista de todas las categorías de productos.

### `/productos/categorias/nueva`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí
- **Función:** Formulario para crear una nueva categoría de producto y procesar la creación.

### `/productos/categorias/editar/<int:categoria_id>`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí
- **Función:** Formulario para editar una categoría de producto y procesar la actualización.

### `/productos/categorias/eliminar/<int:categoria_id>`
- **Métodos:** `GET`
- **Requiere Login:** Sí
- **Función:** Elimina una categoría de producto.

### `/productos`
- **Métodos:** `GET`
- **Requiere Login:** Sí
- **Función:** Muestra la lista de todos los productos.

### `/productos/nuevo`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí
- **Función:** Formulario para registrar un nuevo producto y procesar su creación.

### `/productos/editar/<int:producto_id>`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí
- **Función:** Formulario para editar un producto y procesar su actualización.

### `/productos/toggle_activo/<int:producto_id>`
- **Métodos:** `GET`
- **Requiere Login:** Sí, Admin
- **Función:** Activa o desactiva un producto.

### `/marcas`
- **Métodos:** `GET`
- **Requiere Login:** Sí
- **Función:** Muestra la lista de todas las marcas de productos.

### `/marcas/nueva`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí, Admin
- **Función:** Formulario para crear una nueva marca y procesar su creación.

### `/marcas/editar/<int:marca_id>`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí, Admin
- **Función:** Formulario para editar una marca y procesar su actualización.

### `/marcas/toggle_activo/<int:marca_id>`
- **Métodos:** `GET`
- **Requiere Login:** Sí, Admin
- **Función:** Activa o desactiva una marca.

### `/proveedores`
- **Métodos:** `GET`
- **Requiere Login:** Sí, Admin
- **Función:** Muestra la lista de todos los proveedores.

### `/proveedores/nuevo`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí, Admin
- **Función:** Formulario para registrar un nuevo proveedor y procesar su creación.

### `/proveedores/editar/<int:proveedor_id>`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí, Admin
- **Función:** Formulario para editar un proveedor y procesar su actualización.

### `/proveedores/toggle_activo/<int:proveedor_id>`
- **Métodos:** `GET`
- **Requiere Login:** Sí, Admin
- **Función:** Activa o desactiva un proveedor.

---

## Gestión de Ventas y Comandas

### `/ventas/nueva`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí
- **Función:**
    - `GET`: Muestra el formulario principal de ventas (POS).
    - `POST`: Procesa el registro de una nueva venta. Requiere que el usuario tenga una caja abierta.

### `/ventas/editar/<int:venta_id>`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí
- **Función:** Permite editar datos básicos de una venta ya registrada (cliente, empleado, fecha, pagos). No permite cambiar ítems.

### `/ventas/anular/<int:venta_id>`
- **Métodos:** `POST`
- **Requiere Login:** Sí, Admin
- **Función:** Anula una venta, revirtiendo el stock de productos y los puntos de fidelidad otorgados.

### `/ventas/detalle/<int:venta_id>`
- **Métodos:** `GET`
- **Requiere Login:** Sí
- **Función:** Muestra el detalle completo de una venta, incluyendo ítems y pagos.

### `/ventas/ticket/<int:venta_id>`
- **Métodos:** `GET`
- **Requiere Login:** Sí
- **Función:** Genera una vista simple en HTML optimizada para la impresión en una tiquetera térmica.

### `/ventas`
- **Métodos:** `GET`
- **Requiere Login:** Sí
- **Función:** Muestra el historial de todas las ventas registradas.

### `/comandas/nueva`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí
- **Función:**
    - `GET`: Muestra el formulario para crear una nueva comanda (una pre-venta).
    - `POST`: Guarda la comanda, que luego puede ser cobrada desde caja.

### `/ventas/comandas-pendientes`
- **Métodos:** `GET`
- **Requiere Login:** Sí
- **Función:** Muestra una lista de todas las comandas que están pendientes de ser cobradas.

---

## Finanzas y Caja

### `/finanzas/caja`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí
- **Función:**
    - `GET`: Muestra el estado actual de la caja. Si está cerrada, muestra el formulario de apertura. Si está abierta, muestra el panel de gestión de caja (cierre).
    - `POST`: Procesa la apertura de una nueva sesión de caja.

### `/finanzas/caja/cerrar/<int:sesion_id>`
- **Métodos:** `POST`
- **Requiere Login:** Sí
- **Función:** Procesa el cierre de una sesión de caja, calculando descuadres y guardando el estado final.

### `/finanzas/caja/confirmar_recepcion/<int:sesion_id>`
- **Métodos:** `POST`
- **Requiere Login:** Sí, Admin
- **Función:** Permite a un administrador confirmar que ha recibido el dinero de un cierre de caja cuyo destino era 'Gerencia'.

### `/finanzas/caja/historial`
- **Métodos:** `GET`
- **Requiere Login:** Sí
- **Función:** Muestra el historial de todas las sesiones de caja (aperturas y cierres).

### `/finanzas/caja/pagar-comision/<int:comision_id>`
- **Métodos:** `POST`
- **Requiere Login:** Sí, Admin
- **Función:** Registra el pago de una comisión desde la caja abierta actual.

### `/finanzas/categorias_gastos`
- **Métodos:** `GET`
- **Requiere Login:** Sí, Admin
- **Función:** Muestra la lista de categorías de gastos.

### `/finanzas/categorias_gastos/nueva`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí, Admin
- **Función:** Formulario para crear una nueva categoría de gasto.

### `/finanzas/categorias_gastos/editar/<int:categoria_id>`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí, Admin
- **Función:** Formulario para editar una categoría de gasto.

### `/finanzas/categorias_gastos/eliminar/<int:categoria_id>`
- **Métodos:** `GET`
- **Requiere Login:** Sí, Admin
- **Función:** Elimina una categoría de gasto si no tiene gastos asociados.

### `/finanzas/gastos`
- **Métodos:** `GET`
- **Requiere Login:** Sí
- **Función:** Muestra el historial de todos los gastos registrados.

### `/finanzas/gastos/nuevo`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí
- **Función:** Formulario para registrar un nuevo gasto. Requiere tener una caja abierta.

### `/finanzas/gastos/editar/<int:gasto_id>`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí
- **Función:** Formulario para editar un gasto existente.

### `/finanzas/gastos/eliminar/<int:gasto_id>`
- **Métodos:** `GET`
- **Requiere Login:** Sí, Admin
- **Función:** Elimina un registro de gasto.

### `/finanzas/caja/detalle/<int:sesion_id>`
- **Métodos:** `GET`
- **Requiere Login:** Sí
- **Función:** Muestra el detalle de una sesión de caja, incluyendo todos los movimientos (ventas y gastos).

---

## Compras

### `/compras/nueva`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí, Admin
- **Función:** Formulario para registrar una nueva compra a un proveedor y actualizar el stock de productos.

### `/compras`
- **Métodos:** `GET`
- **Requiere Login:** Sí, Admin
- **Función:** Muestra el historial de todas las compras registradas.

### `/compras/detalle/<int:compra_id>`
- **Métodos:** `GET`
- **Requiere Login:** Sí, Admin
- **Función:** Muestra el detalle completo de una compra, incluyendo los productos comprados.

---

## Configuración

### `/configuracion/sucursales`
- **Métodos:** `GET`
- **Requiere Login:** Sí, Admin
- **Función:** Muestra la lista de todas las sucursales del negocio.

### `/configuracion/sucursales/nueva`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí, Admin
- **Función:** Formulario para registrar una nueva sucursal.

### `/configuracion/sucursales/editar/<int:sucursal_id>`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí, Admin
- **Función:** Formulario para editar una sucursal existente.

### `/configuracion/sucursales/toggle_activo/<int:sucursal_id>`
- **Métodos:** `GET`
- **Requiere Login:** Sí, Admin
- **Función:** Activa o desactiva una sucursal.

### `/configuracion/series`
- **Métodos:** `GET`
- **Requiere Login:** Sí, Admin
- **Función:** Muestra la lista de series y correlativos para los comprobantes de pago.

### `/configuracion/series/nueva`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí, Admin
- **Función:** Formulario para registrar una nueva serie de comprobante.

### `/configuracion/series/editar/<int:serie_id>`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí, Admin
- **Función:** Formulario para editar una serie de comprobante.

### `/configuracion/series/toggle_activo/<int:serie_id>`
- **Métodos:** `GET`
- **Requiere Login:** Sí, Admin
- **Función:** Activa o desactiva una serie de comprobante.

### `/api/series_por_sucursal_y_tipo`
- **Métodos:** `GET`
- **Requiere Login:** Sí, Admin
- **Función (API):** Devuelve las series de comprobantes activas para una sucursal y tipo de comprobante específicos.

### `/configuracion/roles`
- **Métodos:** `GET`
- **Requiere Login:** Sí, Admin
- **Función:** Muestra la lista de roles de usuario.

### `/configuracion/roles/nuevo`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí, Admin
- **Función:** Formulario para crear un nuevo rol de usuario.

### `/configuracion/roles/<int:rol_id>/permisos`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí, Admin
- **Función:**
    - `GET`: Muestra la interfaz para asignar permisos a un rol.
    - `POST`: Guarda los permisos asignados a un rol.

### `/configuracion/bonos`
- **Métodos:** `GET`
- **Requiere Login:** Sí, Admin
- **Función:** Muestra la lista de bonos e incentivos configurados.

### `/configuracion/bonos/nuevo`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí, Admin
- **Función:** Formulario para crear un nuevo bono.

### `/configuracion/bonos/<int:bono_id>/reglas`
- **Métodos:** `GET`
- **Requiere Login:** Sí, Admin
- **Función:** Muestra la interfaz para gestionar las reglas que activan un bono.

### `/configuracion/bonos/<int:bono_id>/reglas/nueva`
- **Métodos:** `POST`
- **Requiere Login:** Sí, Admin
- **Función:** Procesa la adición de una nueva regla a un bono.

### `/configuracion/bonos/reglas/eliminar/<int:regla_id>`
- **Métodos:** `POST`
- **Requiere Login:** Sí, Admin
- **Función:** Elimina una regla de un bono.

### `/configuracion/membresias`
- **Métodos:** `GET`
- **Requiere Login:** Sí, Admin
- **Función:** Muestra la lista de todos los planes de membresía.

### `/configuracion/membresias/nuevo`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí, Admin
- **Función:** Formulario para crear un nuevo plan de membresía y sus beneficios.

### `/configuracion/membresias/editar/<int:plan_id>`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí, Admin
- **Función:** Formulario para editar un plan de membresía y sus beneficios.

### `/configuracion/membresias/toggle-activo/<int:plan_id>`
- **Métodos:** `GET`
- **Requiere Login:** Sí, Admin
- **Función:** Activa o desactiva un plan de membresía.

### `/configuracion/estilos`
- **Métodos:** `GET`
- **Requiere Login:** Sí, Admin
- **Función:** Muestra el catálogo de estilos y cortes de cabello.

### `/configuracion/estilos/nuevo`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí, Admin
- **Función:** Formulario para crear un nuevo estilo, incluyendo la subida de una foto.

### `/configuracion/estilos/editar/<int:estilo_id>`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí, Admin
- **Función:** Formulario para editar un estilo existente.

### `/configuracion/sistema`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí, Admin
- **Función:** Permite configurar aspectos generales del sistema como el nombre de la empresa y los colores de la interfaz.

---

## Reportes

### `/reportes/estado_resultados`
- **Métodos:** `GET`
- **Requiere Login:** Sí, Admin
- **Función:** Genera y muestra un reporte de estado de resultados (ingresos vs. gastos) para un período y sucursal seleccionados.

### `/reportes/liquidacion`
- **Métodos:** `GET`
- **Requiere Login:** Sí, Admin
- **Función:** Genera la liquidación de pago mensual para un colaborador, calculando sueldo, comisiones y bonos.

### `/reportes/liquidacion/pagar`
- **Métodos:** `POST`
- **Requiere Login:** Sí, Admin
- **Función:** Procesa y registra el pago de una liquidación, actualizando estados y creando el registro de gasto correspondiente.

### `/reportes/produccion`
- **Métodos:** `GET`
- **Requiere Login:** Sí, Admin
- **Función:** Muestra un reporte detallado de la producción (servicios y productos vendidos) para un colaborador en un período y sucursal.

### `/reportes/produccion/exportar`
- **Métodos:** `GET`
- **Requiere Login:** Sí, Admin
- **Función:** Exporta el reporte de producción a un archivo Excel.

### `/reportes/produccion-general`
- **Métodos:** `GET`
- **Requiere Login:** Sí, Admin
- **Función:** Muestra un reporte de producción consolidado para todos los colaboradores de una sucursal en un período.

---

## Facturación Electrónica (SUNAT)

### `/configuracion/facturacion`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí, Admin
- **Función:**
    - `GET`: Muestra el formulario para configurar los datos de facturación electrónica (RUC, credenciales SOL, certificado).
    - `POST`: Guarda la configuración y el certificado digital.

### `/ventas/xml/<int:venta_id>`
- **Métodos:** `GET`
- **Requiere Login:** Sí, Admin
- **Función:** Genera y descarga el archivo XML firmado del comprobante electrónico para una venta.

### `/ventas/enviar-sunat/<int:venta_id>`
- **Métodos:** `POST`
- **Requiere Login:** Sí
- **Función:** Envía el comprobante electrónico a la SUNAT, procesa la respuesta (CDR) y actualiza el estado de la venta.

### `/api/consultar-documento/<tipo>/<numero>`
- **Métodos:** `GET`
- **Requiere Login:** Sí
- **Función (API):** Consulta un número de DNI o RUC en un servicio externo y devuelve los datos del cliente/empresa.

### `/ventas/convertir/<int:venta_id>`
- **Métodos:** `GET`
- **Requiere Login:** Sí
- **Función:** Muestra la pantalla para canjear una "Nota de Venta" por una Boleta o Factura Electrónica.

### `/ventas/procesar-conversion/<int:venta_id>`
- **Métodos:** `POST`
- **Requiere Login:** Sí
- **Función:** Procesa el canje de una Nota de Venta a un comprobante fiscal, generando la nueva serie y correlativo.

### `/ventas/<int:venta_id>/emitir_comprobante`
- **Métodos:** `GET`, `POST`
- **Requiere Login:** Sí
- **Función:**
    - `GET`: Muestra la pantalla para seleccionar si se emite Boleta o Factura.
    - `POST`: Procesa la emisión del comprobante fiscal y lo envía a SUNAT.

### `/ventas/cdr/<int:venta_id>`
- **Métenos:** `GET`
- **Requiere Login:** Sí
- **Función:** Permite descargar el archivo CDR (Constancia de Recepción) de SUNAT para una venta específica.
