from flask import Flask, request
import requests
from openai import OpenAI
import os
import json
from dotenv import load_dotenv
from pathlib import Path
import base64
import time
from datetime import datetime, timedelta

# Load variables from .env
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

app = Flask(__name__)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Placeholder URLs for your SheetDB APIs
SHEETDB_CLIENTES = "YOUR_CLIENTS_SHEETDB_URL"
SHEETDB_TECNICOS = "YOUR_TECHNICIANS_SHEETDB_URL"
SHEETDB_CITAS = "YOUR_APPOINTMENTS_SHEETDB_URL"

# Global dictionaries for technician priority order and temporary client data
agenda_por_tecnico = {}
estado_temporal = {}
historial_temporal = {}

def obtener_estado_cliente(telefono):
    """Fetches client data from SheetDB based on phone number."""
    r = requests.get(f"{SHEETDB_CLIENTES}/search?telefono={telefono}").json()
    return r[0] if r else None

def actualizar_estado_en_sheetdb(identificacion, nuevo_estado):
    """Updates the 'estado' field for a client in SheetDB."""
    url = f"{SHEETDB_CLIENTES}/identificacion/{identificacion}"
    response = requests.patch(url, json={"data": {"estado": nuevo_estado}})
    print(f"🔀 PATCH estado → {nuevo_estado} | ID: {identificacion} | Status: {response.status_code}")
    print(f"📨 Respuesta: {response.text}")

def guardar_cita(datos):
    """Saves appointment data to SheetDB."""
    payload = {"data": [datos]}
    requests.post(SHEETDB_CITAS, json=payload)

def interpretar_respuesta_con_gpt(prompt):
    """Interprets a user's response using GPT-3.5-turbo to determine 'yes' or 'no'."""
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        temperature=0,
        max_tokens=3,
        messages=[
            {"role": "system", "content": "Respond exclusively with 'yes' or 'no'. Do not write anything else."},
            {"role": "user", "content": prompt}
        ]
    )
    content = response.choices[0].message.content
    print(f"🧐 GPT raw: >>{content}<<")
    return content.strip().lower()

def enviar_mensaje_por_twilio(cliente):
    """Sends a templated message to a client via Twilio."""
    numero = cliente["telefono"]
    nombre = cliente.get("nombre", "client")
    servicio = cliente.get("servicio", "pending service")
    direccion = cliente.get("direccion", "address not registered")

    # Twilio credentials and template SIDs are loaded from environment variables
    TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
    TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
    TWILIO_MESSAGING_SERVICE_SID = os.getenv("TWILIO_MESSAGING_SERVICE_SID")
    TWILIO_TEMPLATE_SID = os.getenv("TWILIO_TEMPLATE_SID")
    TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")

    headers = {
        "Authorization": "Basic " + base64.b64encode(
            f"{TWILIO_ACCOUNT_SID}:{TWILIO_AUTH_TOKEN}".encode()).decode()
    }

    data = {
        "To": f"whatsapp:{numero}",
        "From": TWILIO_WHATSAPP_NUMBER,
        "MessagingServiceSid": TWILIO_MESSAGING_SERVICE_SID,
        "ContentSid": TWILIO_TEMPLATE_SID,
        "ContentVariables": json.dumps({
            "1": nombre,
            "2": servicio,
            "3": direccion
        })
    }

    print("📦 Final payload sent to Twilio:")
    for k, v in data.items():
        print(f"{k}: {v}")

    url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json"
    response = requests.post(url, headers=headers, data=data)

    print(f"Status Code: {response.status_code}")
    print(f"Response Text: {response.text}")

    if response.status_code >= 400:
        print("⚠️ Error sending templated message. Check ContentSid, variables, and API endpoint.")

def normalizar_rango(rango):
    """Normalizes a time range string."""
    if not rango:
        return ""
    return rango.strip().replace("\u00a0", " ").replace("–", "-").replace("—", "-").replace("–", "-")

def generar_bloques_de_horas(rango):
    """Generates one-hour time blocks from a given range."""
    try:
        print(f"🔧 Generating blocks for range: {rango}")
        rango = normalizar_rango(rango)
        if "-" not in rango:
            raise ValueError("Range does not contain '-'")

        partes = [p.strip() for p in rango.split("-")]
        if len(partes) != 2:
            raise ValueError("Malformed range")

        inicio_str = partes[0]
        fin_str = partes[1]

        if ':' not in inicio_str:
            inicio_str += ":00"
        if ':' not in fin_str:
            fin_str += ":00"

        inicio = datetime.strptime(inicio_str, "%H:%M")
        fin = datetime.strptime(fin_str, "%H:%M")
    except Exception as e:
        print(f"❌ Error processing range: '{rango}' -> {e}")
        return []

    bloques = []
    actual = inicio
    while actual + timedelta(hours=1) <= fin:
        fin_bloque = actual + timedelta(hours=1)

        # Skip lunch break (example: 13:00-14:00)
        if actual.strftime("%H:%M") == "13:00":
            actual += timedelta(hours=1)
            continue

        bloque_str = f"{actual.strftime('%H:%M')} - {fin_bloque.strftime('%H:%M')}"
        bloques.append(bloque_str)
        actual += timedelta(hours=1)

    print(f"✅ Blocks generated: {bloques}")
    return bloques

def obtener_siguiente_dia_habil(fechas_bloqueadas):
    """Calculates the next available business day, skipping weekends and blocked dates."""
    dia = datetime.now().date() + timedelta(days=1)
    while dia.weekday() >= 5 or dia.strftime("%Y-%m-%d") in fechas_bloqueadas:
        dia += timedelta(days=1)
    return dia.strftime("%Y-%m-%d")

def obtener_bloques_agendados(tecnico, fecha):
    """Retrieves already booked time blocks for a specific technician on a given date."""
    r = requests.get(SHEETDB_CITAS).json()
    bloques = [cita["fechayhora"].split(" ", 1)[1]
               for cita in r
               if cita["nombre_tecnicos"] == tecnico and cita["fechayhora"].startswith(fecha)]
    return set(bloques)

def obtener_primer_bloque_disponible(nombre_tecnico, fecha, bloques_posibles):
    """Finds the first available time block for a technician on a specific date."""
    agendados = obtener_bloques_agendados(nombre_tecnico, fecha)
    for bloque in bloques_posibles:
        if bloque not in agendados:
            return bloque
    return None

def es_pregunta_de_identidad(texto):
    """Checks if the user's message is a question about the company's identity."""
    texto = texto.lower()
    patrones = [
        "who are you", "who are you all", "where are you from", "what company", 
        "who is writing to me", "who are you guys", "why are you writing to me"
    ]
    return any(p in texto for p in patrones)

def es_negativa(texto):
    """Checks if the user's message expresses a negative sentiment or rejection."""
    negativas = [
        "no", "i can't", "it doesn't work for me", "no thanks", "i prefer another",
        "better another", "i'm not sure", "reject", "another time", "later"
    ]
    texto = texto.lower()
    return any(palabra in texto for palabra in negativas)

def encontrar_bloque_en_fecha(tipo_servicio, fecha, hora_deseada):
    """Finds an available time block for a specific service on a given date and desired time."""
    tecnicos = consultar_tecnicos_por_servicio_prioritario(tipo_servicio)
    if not tecnicos:
        print("❌ No compatible technicians.")
        return None

    print(f"📆 Searching for appointment on {fecha} at {hora_deseada} for service {tipo_servicio}")
    print(f"👷 Compatible technicians found: {[t['nombre_tecnicos'] for t in tecnicos]}")

    for tecnico in tecnicos:
        print(f"\n🔍 Verifying technician: {tecnico['nombre_tecnicos']}")

        bloques = []

        manana = tecnico.get("horario_manana", "").strip()
        tarde = tecnico.get("horario_tarde", "").strip()

        if manana:
            print(f"⏰ Morning schedule: {manana}")
            bloques += generar_bloques_de_horas(manana)
        if tarde:
            print(f"⏰ Afternoon schedule: {tarde}")
            bloques += generar_bloques_de_horas(tarde)

        if not bloques:
            print("⚠️ No blocks generated for this technician.")
            continue

        print(f"📦 Possible blocks: {bloques}")
        agendados = obtener_bloques_agendados(tecnico["nombre_tecnicos"], fecha)
        print(f"🛑 Booked blocks: {agendados}")

        # Find the index of the exact desired block
        idx_deseado = next(
            (i for i, b in enumerate(bloques) if b.split(" - ")[0].strip() == hora_deseada),
            None
        )

        if idx_deseado is None:
            print(f"⛔ Time {hora_deseada} is not in the possible blocks for this technician.")
            continue

        orden_bloques = sorted(bloques, key=lambda b: abs(bloques.index(b) - idx_deseado))

        for bloque in orden_bloques:
            if bloque not in agendados:
                print(f"✅ Assigned block {bloque} with {tecnico['nombre_tecnicos']}")
                return fecha, bloque, tecnico["nombre_tecnicos"]

    print("❌ No available block found on that day with compatible technicians.")
    return None

def interpretar_fecha_hora(texto_usuario):
    """Interprets natural language input from the user to extract a future date and time."""
    hoy = datetime.now()
    prompt = f"""
Today is {hoy.strftime('%A %d of %B of %Y')}. The client wrote: \"{texto_usuario}\".

Your task is to interpret the client's intention as a future date and time, even if expressed informally or partially.

✔ Interpret expressions like:
- \"Wednesday at 10\" → next Wednesday at 10:00
- \"tomorrow at 9\" → tomorrow's date, time 09:00
- \"Thursday afternoon\" → next Thursday, 15:00
- \"around 4\" or \"like 3\" → interpret as 16:00 or 15:00 respectively
- \"at half past 10\" → interpret as 10:30
- \"around 11\" → interpret as 11:00
- \"May 14th at 8:30\" → that exact date and time

❗ Always assume it's a future intention (today or later), even if the year is not mentioned. Use the current year.

Return ONLY a JSON with the fields:
{{
  "fecha": "YYYY-MM-DD",
  "hora": "HH:MM"
}}

If you cannot understand the date or time, respond exactly:
{{"error": "not understood"}}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4",
            temperature=0,
            max_tokens=100,
            messages=[
                {"role": "system", "content": "You are an assistant that converts natural language into future dates and times."},
                {"role": "user", "content": prompt}
            ]
        )
        content = response.choices[0].message.content.strip()
        print("📆 GPT interpreted:", content)
        data = json.loads(content)
        if "fecha" in data and "hora" in data:
            return data
        else:
            return {"error": "not understood"}
    except Exception as e:
        print(f"❌ Error in GPT interpretation: {e}")
        return {"error": "not understood"}

def consultar_tecnicos_por_servicio_prioritario(tipo_servicio):
    """Consults available technicians for a given service type, prioritizing based on historical assignments."""
    global agenda_por_tecnico
    tecnicos = requests.get(SHEETDB_TECNICOS).json()
    compatibles = [t for t in tecnicos if t.get(tipo_servicio, "").strip().lower() == "si"]
    fechas_bloqueadas = set(t.get("fecha_bloqueada", "").strip() for t in compatibles if t.get("fecha_bloqueada"))

    dia_actual = datetime.now().date()
    intentos = 0
    max_dias = 10  # Do not search beyond 10 business days

    while intentos < max_dias:
        siguiente_dia = dia_actual + timedelta(days=1)
        if siguiente_dia.weekday() >= 5 or siguiente_dia.strftime("%Y-%m-%d") in fechas_bloqueadas:
            dia_actual = siguiente_dia
            continue

        fecha_str = siguiente_dia.strftime("%Y-%m-%d")
        tecnicos_disponibles = []

        tecnicos_ordenados = sorted(
            compatibles,
            key=lambda t: agenda_por_tecnico.get(t["nombre_tecnicos"], float('inf'))
        )

        for tecnico in tecnicos_ordenados:
            if tecnico.get("fecha_bloqueada", "").strip() == fecha_str:
                continue

            bloques = []
            if tecnico.get("horario_manana"):
                bloques += generar_bloques_de_horas(tecnico["horario_manana"])
            if tecnico.get("horario_tarde"):
                bloques += generar_bloques_de_horas(tecnico["horario_tarde"])
            if not bloques:
                continue

            primer_bloque = obtener_primer_bloque_disponible(tecnico["nombre_tecnicos"], fecha_str, bloques)
            if not primer_bloque:
                continue

            if tecnico["nombre_tecnicos"] not in agenda_por_tecnico:
                agenda_por_tecnico[tecnico["nombre_tecnicos"]] = len(agenda_por_tecnico)

            tecnicos_disponibles.append({
                "nombre_tecnicos": tecnico["nombre_tecnicos"],
                "bloques": [primer_bloque],
                "fecha": fecha_str,
                "horario_manana": tecnico.get("horario_manana", "").strip(),
                "horario_tarde": tecnico.get("horario_tarde", "").strip()
            })

        # Display technicians and schedules for debugging
        for tecnico in compatibles:
            print(f"\n🧾 Technician from SheetDB: {tecnico['nombre_tecnicos']}")
            print(f"🕒 Morning schedule: {tecnico.get('horario_manana')}")
            print(f"🕒 Afternoon schedule: {tecnico.get('horario_tarde')}")

        if tecnicos_disponibles:
            return tecnicos_disponibles

        dia_actual = siguiente_dia
        intentos += 1

    return []

@app.route("/whatsapp", methods=["POST"])
def webhook():
    """Webhook for handling incoming WhatsApp messages."""
    numero = request.form.get("From", "").replace("whatsapp:", "")
    mensaje = request.form.get("Body", "").strip()
    cliente = obtener_estado_cliente(numero)
    if not cliente:
        return "<Response><Message>Could not find your information.</Message></Response>"

    estado = cliente.get("estado", "").lower()
    print(f"📥 Message from {numero}: {mensaje}")
    print(f"🔹 Current state: {estado}")

    # Respond to identity questions
    if es_pregunta_de_identidad(mensaje):
        return "<Response><Message>Hello 👋, we are a service provider. We are writing to you because you have a pending service with us. Would you like to schedule your pending appointment?</Message></Response>"

    # Accumulate recent history
    historial = historial_temporal.get(numero, "")
    historial += " " + mensaje
    historial_temporal[numero] = historial.strip()

    if estado == "esperando_confirmacion_agenda": # Waiting for appointment confirmation
        respuesta = interpretar_respuesta_con_gpt(f"The client wrote: \"{historial}\". Do they wish to schedule an appointment?")
        if any(p in respuesta for p in ["sí", "si", "quiero", "me sirve", "yes"]):
            tipo = cliente["tipo"]
            tecnicos = consultar_tecnicos_por_servicio_prioritario(tipo)
            if tecnicos:
                tecnico = tecnicos[0]
                bloque = tecnico["bloques"][0]
                fecha = tecnico["fecha"]
                actualizar_estado_en_sheetdb(cliente["identificacion"], "proponiendo_cita")
                estado_temporal[numero] = {
                    "bloque": bloque,
                    "fecha": fecha,
                    "tecnico": tecnico["nombre_tecnicos"]
                }
                historial_temporal.pop(numero, None)
                return f"<Response><Message>Perfect {cliente['nombre']}, does an appointment with technician {tecnico['nombre_tecnicos']} on {fecha} from {bloque} work for you?</Message></Response>"
            else:
                actualizar_estado_en_sheetdb(cliente["identificacion"], "esperando_preferencia")
                return "<Response><Message>No technicians available. What date do you prefer?</Message></Response>"
        else:
            if len(historial.strip().split()) <= 3:
                return "<Response><Message>Hello 👋 Would you like to schedule an appointment for the service?</Message></Response>"
            else:
                actualizar_estado_en_sheetdb(cliente["identificacion"], "")
                historial_temporal.pop(numero, None)
                return "<Response><Message>Understood! You can write to us later.</Message></Response>"

    elif estado == "proponiendo_cita": # Proposing an appointment
        if es_negativa(mensaje):
            actualizar_estado_en_sheetdb(cliente["identificacion"], "esperando_preferencia")
            return "<Response><Message>What date and time do you prefer?</Message></Response>"

        mensaje_limpio = mensaje.strip().lower()
        frases_afirmativas = ["sí", "si", "me sirve", "ok", "dale", "perfecto", "vale", "claro", "de acuerdo", "sí perfecto", "sí claro", "yes", "confirm"]

        if any(frase in mensaje_limpio for frase in frases_afirmativas):
            temporal = estado_temporal.get(numero)
            if temporal:
                bloque = temporal.get("bloque")
                fecha = temporal.get("fecha")
                tecnico = temporal.get("tecnico")
            else:
                bloque = fecha = tecnico = None

            if bloque and fecha and tecnico:
                if bloque in obtener_bloques_agendados(tecnico, fecha):
                    siguiente_bloque = obtener_primer_bloque_disponible(tecnico, fecha, generar_bloques_de_horas("09:00 - 18:00"))
                    if siguiente_bloque:
                        return f"<Response><Message>Sorry, that time is no longer available. Does the block {siguiente_bloque} with {tecnico} on {fecha} work for you?</Message></Response>"
                    else:
                        return "<Response><Message>No available times today. Please suggest another date.</Message></Response>"

                guardar_cita({
                    "telefono": numero,
                    "nombre": cliente["nombre"],
                    "tipo": cliente["tipo"],
                    "servicio": cliente["servicio"],
                    "nombre_tecnicos": tecnico,
                    "fechayhora": f"{fecha} {bloque}",
                    "direccion": cliente["direccion"]
                })
                actualizar_estado_en_sheetdb(cliente["identificacion"], "Scheduled")
                estado_temporal.pop(numero, None)
                historial_temporal.pop(numero, None)
                return f"<Response><Message>✅ Appointment confirmed for {fecha} at {bloque} with {tecnico} at {cliente['direccion']}!</Message></Response>"

        actualizar_estado_en_sheetdb(cliente["identificacion"], "esperando_preferencia")
        return "<Response><Message>What date and time do you prefer?</Message></Response>"

    elif estado == "esperando_preferencia": # Waiting for user's preference
        interpretado = interpretar_fecha_hora(mensaje)
        if "error" in interpretado:
            return "<Response><Message>I didn't quite understand the date and time. Can you write it differently?</Message></Response>"

        fecha = interpretado["fecha"]
        hora = interpretado["hora"]
        tipo = cliente["tipo"]
        propuesta = encontrar_bloque_en_fecha(tipo, fecha, hora)

        if propuesta:
            fecha, bloque, tecnico = propuesta
            actualizar_estado_en_sheetdb(cliente["identificacion"], "proponiendo_cita")
            estado_temporal[numero] = {
                "bloque": bloque,
                "fecha": fecha,
                "tecnico": tecnico
            }
            return f"<Response><Message>Does an appointment with {tecnico} on {fecha} at {bloque} work for you?</Message></Response>"
        else:
            return "<Response><Message>I don't have availability for that date. Would you like me to suggest another nearby time?</Message></Response>"

    return "<Response><Message>I didn't understand! Please try again.</Message></Response>"

def enviar_mensajes_a_todos():
    """Initiates contact with all clients who haven't been contacted yet."""
    clientes = requests.get(SHEETDB_CLIENTES).json()
    for cliente in clientes:
        if cliente.get("contactado", "").lower() != "sí": # Not yet contacted
            enviar_mensaje_por_twilio(cliente)
            actualizar_estado_en_sheetdb(cliente["identificacion"], "esperando_confirmacion_agenda")
            requests.patch(f"{SHEETDB_CLIENTES}/identificacion/{cliente['identificacion']}", json={"data": {"contactado": "sí"}})
            time.sleep(2) # Pause to avoid hitting API rate limits

@app.route("/iniciar-contacto", methods=["GET"])
def iniciar_contacto():
    """Endpoint to trigger mass contact initiation."""
    token = request.args.get("token")
    # Use a secure token for triggering this action
    if token != os.getenv("SECRET_TRIGGER_TOKEN"):
        return "Unauthorized", 403
    enviar_mensajes_a_todos()
    return "Contacts initiated successfully", 200

if __name__ == '__main__':
    # For local development, run with `flask run` or a WSGI server
    # For production, use a production-ready WSGI server like Gunicorn or uWSGI
    # app.run(debug=True) # Do not use debug=True in production
    pass # This line ensures the app doesn't run directly when imported
