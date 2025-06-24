# 🤖 Agente de WhatsApp con IA para Agendamiento Automático de Citas

Este proyecto implementa un **agente inteligente para WhatsApp** que gestiona de manera autónoma la agenda de citas de clientes. Utiliza **Flask**, **OpenAI GPT-4** y **SheetDB** para ofrecer una experiencia de atención al cliente sin fricción, desde el primer mensaje hasta la confirmación de cita.

---

## 🚀 Características principales

- ✉️ Recibe mensajes de WhatsApp a través de Webhooks (Twilio).
- 🧠 Usa **GPT-4** para interpretar lenguaje natural ("puedo el martes a las 10" → fecha + hora).
- ⏰ Consulta la disponibilidad de técnicos según su servicio, horario y citas ya asignadas.
- 🗓️ Propone fechas y horarios disponibles al cliente, o registra directamente si acepta.
- ✉️ Envía mensajes de plantilla por WhatsApp usando Twilio.
- ✅ Guarda la cita confirmada en una hoja de Google Sheets vía SheetDB.

---

## 📂 Tecnologías utilizadas

| Componente           | Tecnología            |
|---------------------|------------------------|
| Web server           | Flask (Python)         |
| IA conversacional    | OpenAI GPT-4 + GPT-3.5 |
| Base de datos        | Google Sheets + SheetDB|
| Mensajería           | Twilio WhatsApp API    |
| Variables de entorno | dotenv                 |

---

## 📅 Flujo de funcionamiento

1. **Cliente recibe mensaje** de inicio usando plantilla aprobada de WhatsApp.
2. Cuando responde:
   - Si es afirmativo → se propone fecha + hora.
   - Si responde negativamente → se pregunta por su preferencia.
3. Si propone día/hora → se interpreta con IA y se consulta disponibilidad.
4. Si hay cupo, se agenda.
5. Si no hay, se le sugiere otra opción.

---

## 🔧 Variables requeridas (.env)

```env
OPENAI_API_KEY=sk-...
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_MESSAGING_SERVICE_SID=...
TWILIO_TEMPLATE_SID=...
TWILIO_WHATSAPP_NUMBER=whatsapp:+123456789
SECRET_TRIGGER_TOKEN=una_clave_segura
```

También debes reemplazar las siguientes URLs en el código:

```python
SHEETDB_CLIENTES = "https://sheetdb.io/api/v1/tu_base_clientes"
SHEETDB_TECNICOS = "https://sheetdb.io/api/v1/tu_base_tecnicos"
SHEETDB_CITAS    = "https://sheetdb.io/api/v1/tu_base_citas"
```

---

## 📝 Ejemplo de interacción

> 📨 Cliente: Hola, recibí su mensaje.  
> 🧳 Bot: Perfecto Juan, ¿le serviría una cita con el técnico Pedro el martes 25 de junio de 10:00 a 11:00?  
> 📨 Cliente: Mejor a las 12  
> 🧳 Bot: De acuerdo, tengo a las 12:00 disponible ese mismo día. ¿Confirmamos?  
> ✅ Cliente: Listo  
> 🧳 Bot: ✅ Cita confirmada el martes 25 a las 12:00 con Pedro. Gracias.

---

## 🔐 Endpoints disponibles

- `/whatsapp` - Webhook POST para Twilio (recepción de mensajes)
- `/iniciar-contacto?token=...` - GET para enviar mensajes a todos los clientes no contactados

---

## 📆 Lógica de asignación
- Los técnicos son filtrados por compatibilidad con el servicio.
- Se prioriza la distribución equitativa (por orden).
- Se evita agendar en horas de almuerzo.
- Se interpretan horarios naturales tipo: "entre 10 y 11", "tipo 4", "por la tarde".

---

## 🛠️ Requisitos para correr localmente

```bash
pip install -r requirements.txt
flask run
```

Para producción, usa Gunicorn, uWSGI o despliega en un servicio como Render, Railway, etc.

---

## 📅 Estado temporal y robustez
- El sistema guarda respuestas parciales y espera confirmación del cliente.
- Maneja mensajes ambiguos, silencios o respuestas inesperadas.
- Permite al cliente cancelar, postergar o reagendar.

---

## 🚫 Advertencia
Este proyecto está pensado como **plantilla**. No incluye validación de usuarios ni capa de autenticación avanzada.

---

## 🚀 ¿Quieres adaptarlo a tu negocio?
Puedes personalizar la plantilla, los textos, la base de datos o el modelo de IA para ajustarlo a tu operación real.

🔗 [Portafolio y contacto](https://federicogzc.github.io)
