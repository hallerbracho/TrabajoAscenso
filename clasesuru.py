import streamlit as st
import google.generativeai as genai
import json
import time
import re
from libsql_client import create_client_sync, Statement
import pandas as pd
from datetime import datetime
import math
from zoneinfo import ZoneInfo
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import random
from streamlit_oauth import OAuth2Component
import base64

try:
    CLIENT_ID = st.secrets["google_oauth"]["client_id"]
    CLIENT_SECRET = st.secrets["google_oauth"]["client_secret"]
    try:
        float(st.secrets.get("some_secret_that_doesnt_exist", "0.0"))
        REDIRECT_URI = st.secrets["google_oauth"]["redirect_uri_prod"]
    except (ValueError, KeyError):
        REDIRECT_URI = st.secrets["google_oauth"]["redirect_uri_local"]

    oauth2 = OAuth2Component(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        authorize_endpoint="https://accounts.google.com/o/oauth2/v2/auth",
        token_endpoint="https://oauth2.googleapis.com/token",
    )
except (KeyError, Exception) as e:
    st.error(f"Error al configurar la autenticación de Google. Revisa los secretos. Error: {e}")
    st.stop()

st.markdown(
    """
    <style>
        section[data-testid="stSidebar"] {
            width: 380px !important; # Set the width to your desired value
        }
    </style>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:	
    #st.header("Opciones de Calendario")
    st.image("https://uru.edu/wp-content/uploads/2023/02/uru-logo-maracaibo.png")
    #st.image("https://luz.unir.edu.ve/wp-content/uploads/2024/04/escudo-Hor-gris-1024x427-1.png")
    st.subheader("Actividades formativas y de evaluación")
    st.markdown("Prof. Haller Bracho")
    #st.html("<p>Departamento de Matemática<br>Facultad Experimental de Ciencias<br>La Universidad del Zulia</p>")    
    st.html("<p>Escuela de Telecomunicaciones<br>Facultad de Ingeniería<br>Universidad Rafael Urdaneta</p>")    
    #fecha2 = st.date_input("Calendario escolar", value="today", format="DD/MM/YYYY", width="stretch")
    st.caption("Todas las actividades han sido generadas automáticamente por la IA y revisadas por el profesor siguiendo el enfoque _human-in-the-loop_.")

# --- Constantes para la configuración de IA (sin cambios) ---
DEFAULT_IA_MODEL = 'models/gemini-2.5-pro'
DEFAULT_IA_PROMPT = """
## PERSONA ##
Actúa como un profesor e investigador universitario experto en {asignatura}.

## TAREA PRINCIPAL ##
Tu tarea es generar un quiz de {num_preguntas} preguntas de nivel {dificultad} sobre los temas: {temas_str}.
Tu única salida debe ser un bloque de código JSON 100% válido. No escribas nada antes o después del bloque JSON.

## REGLAS DE FORMATO (SEGUIR ESTRICTAMENTE) ##

1.  **SALIDA FINAL:** Una lista de {num_preguntas} objetos JSON.
2.  **CLAVES DEL OBJETO:** Cada objeto DEBE tener estas 4 claves: "pregunta", "opciones", "respuesta_correcta", "explicacion". Una y sólo una de las opciones debe ser la respuesta correcta.  Asegúrate de que cada párrafo esté separado por un doble espacio (una línea en blanco completa).
3.  **ESTRUCTURA DE "pregunta":**
    -   Párrafo 1: Explicación muy breve del concepto. **Palabras clave en negrita**. Incluir enlace `[Más información](URL_YOUTUBE_SEARCH)`.
    -   Párrafo 2: Describe la importancia del concepto. 
    -   Párrafo 3: **La pregunta en sí, en negrita, ambientado en un escenario real**.
4.  **ESTRUCTURA DE "opciones":** Objeto JSON con 4 claves: "A", "B", "C", "D".
5.  **REGLA DE LATEX:** Usa LaTeX con signos de dólar ($...$). En el JSON, escapa todas las barras ´\´ con ´\\´. Ejemplo: ´\\frac{{1}}{{2}}´.
6.  **REGLAS DE "explicacion":**
    -   Debe ser un tutorial paso a paso.
    -   **PROHIBIDO:** No expliques las opciones incorrectas. No describas tu proceso de creación. No uses preguntas retóricas. Sé directo.

## EJEMPLO DE UN OBJETO JSON VÁLIDO ##
{{
  "pregunta": "El **determinante** de una matriz es un valor escalar clave en álgebra lineal. [más información](https://es.wikipedia.org/wiki/Determinante_(matemática)) **¿Para qué valores de 'c' el sistema homogéneo $Ax=0$ tiene soluciones no triviales si $A = \\begin{{pmatrix}} 1 & c \\\\ c & 4 \\end{{pmatrix}}$?**",
  "opciones": {{
    "A": "$c=1$ y $c=-1$",
    "B": "$c=2$ y $c=-2$",
    "C": "$c=0$",
    "D": "$c=4$ y $c=-4$"
  }},
  "respuesta_correcta": "B",
  "explicacion": "Un sistema homogéneo tiene soluciones no triviales si el determinante de la matriz de coeficientes es cero. El determinante es $det(A) = (1)(4) - (c)(c) = 4 - c^2$. Igualamos a cero: $4 - c^2 = 0$. Resolvemos para c: $c^2 = 4$, lo que da las soluciones $c=2$ y $c=-2$."
}}

## INSTRUCCIÓN FINAL Y CRÍTICA ##
Ahora, genera la lista de {num_preguntas} preguntas. Recuerda, tu respuesta debe ser exclusivamente el código JSON.
"""

# --- MODIFICADO: Funciones para interactuar con la Base de Datos (Turso) ---

@st.cache_resource
def get_db_client():
    """Crea y retorna un cliente para Turso, cacheado por sesión."""
    try:
        db_url = st.secrets["turso"]["db_url"]
        auth_token = st.secrets["turso"]["auth_token"]
        return create_client_sync(url=db_url, auth_token=auth_token)
    except (KeyError, Exception) as e:
        st.error(f"Error conectando a la base de datos Turso: {e}. Asegúrate de configurar 'db_url' y 'auth_token' en los secretos de Streamlit.")
        st.stop()
        

def create_turso_client():
    """Crea y retorna un cliente para la base de datos Turso usando secretos."""
    try:
        db_url = st.secrets["turso"]["db_url"]
        auth_token = st.secrets["turso"]["auth_token"]
        # MODIFICADO: Se utiliza create_client_sync en lugar de create_client
        return create_client_sync(url=db_url, auth_token=auth_token)
    except (KeyError, Exception) as e:
        st.error(f"Error conectando a la base de datos Turso: {e}. Asegúrate de configurar 'db_url' y 'auth_token' en los secretos de Streamlit.")
        st.stop()


def init_db():
    """
    Inicializa la base de datos, crea las tablas si no existen y
    realiza migraciones de esquema necesarias, como añadir nuevas columnas.
    """
    client = get_db_client()
    try:
        # 1. Ejecutar las creaciones de tablas estándar
        # NOTA: La tabla quiz_results ahora se crea con las nuevas columnas si no existe.
        create_statements = [
            Statement("""
                CREATE TABLE IF NOT EXISTS quiz_configs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile_name TEXT NOT NULL,
                    variant_name TEXT NOT NULL,
                    asignatura TEXT,
                    temas TEXT,
                    num_preguntas INTEGER,
                    dificultad TEXT,
                    show_feedback INTEGER DEFAULT 1,
                    UNIQUE(profile_name, variant_name)
                )
            """),
            Statement("CREATE TABLE IF NOT EXISTS global_settings (key TEXT PRIMARY KEY, value TEXT)"),
            Statement("""
                CREATE TABLE IF NOT EXISTS quiz_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_name TEXT NOT NULL,
                    profile_name TEXT NOT NULL,
                    variant_name TEXT NOT NULL,
                    score INTEGER NOT NULL,
                    total_questions INTEGER NOT NULL,
                    grade REAL NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    quiz_snapshot_json TEXT,
                    student_answers_json TEXT
                )
            """),
            Statement("""
                CREATE TABLE IF NOT EXISTS generated_quizzes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    config_id INTEGER NOT NULL,
                    quiz_data_json TEXT NOT NULL,
                    is_active INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (config_id) REFERENCES quiz_configs (id) ON DELETE CASCADE
                )
            """),
            Statement("CREATE INDEX IF NOT EXISTS idx_quizzes_config_id ON generated_quizzes (config_id)"),
            Statement("CREATE INDEX IF NOT EXISTS idx_quizzes_active ON generated_quizzes (is_active)"),
            Statement("CREATE INDEX IF NOT EXISTS idx_results_profile ON quiz_results (profile_name)"),
            Statement("CREATE INDEX IF NOT EXISTS idx_results_grade_time ON quiz_results (grade, timestamp)"),
        ]
        client.batch(create_statements)

        # 2. Realizar migraciones para bases de datos antiguas
        rs = client.execute("PRAGMA table_info(quiz_results)")
        columns = [row[1] for row in rs.rows]

        migration_statements = []
        if 'show_feedback' not in [c[1] for c in client.execute("PRAGMA table_info(quiz_configs)").rows]:
             migration_statements.append(Statement("ALTER TABLE quiz_configs ADD COLUMN show_feedback INTEGER DEFAULT 1"))
        if 'quiz_snapshot_json' not in columns:
            migration_statements.append(Statement("ALTER TABLE quiz_results ADD COLUMN quiz_snapshot_json TEXT"))
        if 'student_answers_json' not in columns:
            migration_statements.append(Statement("ALTER TABLE quiz_results ADD COLUMN student_answers_json TEXT"))

        if migration_statements:
            st.warning("Detectada una versión antigua de la base de datos. Actualizando esquema...")
            client.batch(migration_statements)
            st.success("¡Esquema de la base de datos actualizado correctamente!")
            time.sleep(2)

    except Exception as e:
        st.error(f"Error al inicializar o migrar la base de datos: {e}")
    #finally:
        #client.close()

@st.cache_data
def get_global_setting(key, default_value=None):
    """Obtiene una configuración global desde la base de datos."""
    client = get_db_client()
    rs = client.execute("SELECT value FROM global_settings WHERE key = ?", (key,))
    #client.close()
    return rs.rows[0][0] if rs.rows else default_value

def save_global_setting(key, value):
    """Guarda o actualiza una configuración global en la base de datos."""
    client = get_db_client()
    sql = """
    INSERT INTO global_settings (key, value) VALUES (?, ?)
    ON CONFLICT(key) DO UPDATE SET value = excluded.value
    """
    client.execute(sql, (key, value))
    #client.close()
    get_global_setting.clear()

def get_global_message():
    return get_global_setting('teacher_message', default_value="")

def save_global_message(message):
    save_global_setting('teacher_message', message)

@st.cache_data
def get_all_profiles():
    """Obtiene los nombres de todos los PERFILES PADRE de la DB."""
    client = get_db_client()
    rs = client.execute("SELECT DISTINCT profile_name FROM quiz_configs ORDER BY profile_name")
    #client.close()
    return [row[0] for row in rs.rows]

@st.cache_data
def get_variants_for_profile(profile_name):
    """Obtiene todas las variantes (id, nombre) para un perfil padre dado."""
    if not profile_name: return []
    client = get_db_client()
    rs = client.execute("SELECT id, variant_name FROM quiz_configs WHERE profile_name = ? ORDER BY variant_name", (profile_name,))
    #client.close()
    return rs.rows

@st.cache_data
def get_variants_with_status_for_profile(profile_name):
    """Obtiene variantes para un perfil, indicando si hay un quiz activo."""
    if not profile_name: return []
    client = get_db_client()
    query = """
    SELECT c.id, c.variant_name, CASE WHEN q.id IS NOT NULL THEN 1 ELSE 0 END as is_active
    FROM quiz_configs c
    LEFT JOIN generated_quizzes q ON c.id = q.config_id AND q.is_active = 1
    WHERE c.profile_name = ? ORDER BY c.variant_name
    """
    rs = client.execute(query, (profile_name,))
    #client.close()
    return rs.rows

@st.cache_data
def load_config_from_db(config_id):
    """Carga una configuración específica (una variante) desde la DB usando su ID."""
    client = get_db_client()
    rs = client.execute("SELECT * FROM quiz_configs WHERE id = ?", (config_id,))
    #client.close()
    if rs.rows:
        config_row = rs.rows[0]
        config = {col: config_row[idx] for idx, col in enumerate(rs.columns)}
        config['temas'] = json.loads(config['temas'])
        return config
    return None

def save_config_to_db(profile_name, variant_name, asignatura, temas, num_preguntas, dificultad, show_feedback):
    """Guarda (inserta o actualiza) una configuración/variante en la DB."""
    client = get_db_client()
    temas_json = json.dumps(temas)
    sql = """
    INSERT INTO quiz_configs (profile_name, variant_name, asignatura, temas, num_preguntas, dificultad, show_feedback)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(profile_name, variant_name) DO UPDATE SET
        asignatura=excluded.asignatura,
        temas=excluded.temas,
        num_preguntas=excluded.num_preguntas,
        dificultad=excluded.dificultad,
        show_feedback=excluded.show_feedback
    """
    client.execute(sql, (profile_name, variant_name, asignatura, temas_json, num_preguntas, dificultad, int(show_feedback)))
    #client.close()
    get_all_profiles.clear()
    get_variants_for_profile.clear()
    load_config_from_db.clear()
    get_variants_with_status_for_profile.clear()
    get_configs_for_profile_as_df.clear()

def delete_config_from_db(config_id):
    """Elimina una configuración/variante específica de la DB por su ID."""
    client = get_db_client()
    client.execute("DELETE FROM quiz_configs WHERE id = ?", (config_id,))
    #client.close()
    get_all_profiles.clear()
    get_variants_for_profile.clear()
    load_config_from_db.clear()
    get_variants_with_status_for_profile.clear()
    get_configs_for_profile_as_df.clear()

def save_and_activate_quiz(config_id, quiz_data):
    """Guarda un nuevo quiz en la BD y lo activa, desactivando cualquier otro."""
    client = get_db_client()
    quiz_data_json = json.dumps(quiz_data)
    
    statements = [
        Statement("UPDATE generated_quizzes SET is_active = 0 WHERE config_id = ?", (config_id,)),
        Statement("INSERT INTO generated_quizzes (config_id, quiz_data_json, is_active) VALUES (?, ?, 1)", (config_id, quiz_data_json))
    ]
    try:
        client.batch(statements)
    except Exception as e:
        st.error(f"Error en la base de datos al activar el quiz: {e}")
    #finally:
        #client.close()
    
    get_active_quiz_for_config.clear()
    get_variants_with_status_for_profile.clear()

@st.cache_data
def get_active_quiz_for_config(config_id):
    """Obtiene el quiz activo (JSON) para una configuración dada."""
    client = get_db_client()
    rs = client.execute("SELECT quiz_data_json FROM generated_quizzes WHERE config_id = ? AND is_active = 1", (config_id,))
    #client.close()
    if rs.rows:
        return json.loads(rs.rows[0][0])
    return None

@st.cache_data
def get_latest_quiz_for_config(config_id):
    """Obtiene la última versión de un quiz generado para una configuración."""
    client = get_db_client()
    rs = client.execute("SELECT quiz_data_json FROM generated_quizzes WHERE config_id = ? ORDER BY created_at DESC LIMIT 1", (config_id,))
    #client.close()
    if rs.rows:
        return json.loads(rs.rows[0][0])
    return None

def check_if_any_quiz_exists(config_id):
    """Verifica si existe CUALQUIER quiz (activo o no) para una configuración."""
    client = get_db_client()
    rs = client.execute("SELECT 1 FROM generated_quizzes WHERE config_id = ? LIMIT 1", (config_id,))
    #client.close()
    return bool(rs.rows)

def set_quiz_activation_status(config_id, is_active):
    """Activa o desactiva la versión más reciente de un quiz."""
    client = get_db_client()
    try:
        statements = [Statement("UPDATE generated_quizzes SET is_active = 0 WHERE config_id = ?", (config_id,))]
        if is_active:
            update_sql = """
                UPDATE generated_quizzes
                SET is_active = 1
                WHERE id = (SELECT id FROM generated_quizzes WHERE config_id = ? ORDER BY created_at DESC LIMIT 1)
            """
            statements.append(Statement(update_sql, (config_id,)))
        client.batch(statements)
    except Exception as e:
        st.error(f"Error en la base de datos al cambiar el estado del quiz: {e}")
    #finally:
        #client.close()
    
    get_active_quiz_for_config.clear()
    get_variants_with_status_for_profile.clear()

def save_result_to_db(student_name, profile_name, variant_name, score, total_questions, grade, quiz_snapshot, student_answers):
    """Guarda el resultado de un quiz, incluyendo el snapshot y las respuestas."""
    client = get_db_client()
    sql = """
    INSERT INTO quiz_results (
        student_name, profile_name, variant_name, score, total_questions, grade, timestamp,
        quiz_snapshot_json, student_answers_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    now_in_venezuela = datetime.now(ZoneInfo("America/Caracas"))
    quiz_snapshot_json = json.dumps(quiz_snapshot)
    student_answers_json = json.dumps(student_answers)

    client.execute(sql, (
        student_name, profile_name, variant_name, score, total_questions, grade,
        now_in_venezuela.isoformat(), quiz_snapshot_json, student_answers_json
    ))
    #client.close()
    get_results_by_profile_as_df.clear()

@st.cache_data
def get_configs_for_profile_as_df(profile_name):
    """Obtiene todas las configuraciones de un perfil como un DataFrame de pandas."""
    client = get_db_client()
    query = "SELECT variant_name, show_feedback FROM quiz_configs WHERE profile_name = ?"
    rs = client.execute(query, (profile_name,))
    #client.close()
    df = pd.DataFrame(rs.rows, columns=rs.columns)
    return df
    
@st.cache_data
def get_results_by_profile_as_df(profile_name):
    """Obtiene TODOS los resultados de un perfil padre específico."""
    client = get_db_client()
    query = "SELECT * FROM quiz_results WHERE profile_name = ? ORDER BY timestamp DESC, grade DESC"
    rs = client.execute(query, (profile_name,))
    #client.close()
    df = pd.DataFrame(rs.rows, columns=rs.columns)
    return df

def clear_all_results_from_db():
    """Elimina todos los registros de la tabla de resultados."""
    client = get_db_client()
    statements = [
        Statement("DELETE FROM quiz_results"),
        Statement("DELETE FROM sqlite_sequence WHERE name='quiz_results'")
    ]
    client.batch(statements)
    #client.close()
    get_results_by_profile_as_df.clear()



# --- El resto del script (UI, lógica de IA, etc.) no necesita cambios ---
# --- Ejecutar la inicialización de la DB al inicio ---
init_db()

# --- CONFIGURACIÓN DE LA PÁGINA Y API ---
#st.set_page_config(page_title="Actividades de refuerzo", layout="centered")
st.set_page_config(page_title="Actividades de refuerzo", layout="centered", initial_sidebar_state="auto", menu_items={
        'Get Help': 'https://uru.haller.com.ve'
    })
try:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
except Exception as e:
    st.error(f"Error al configurar la API de Google: {e}")
    st.stop()


# --- FUNCIONES AUXILIARES Y DE UI ---
def reset_quiz_state():
    keys_to_delete = ['pagina', 'quiz_generado', 'pregunta_actual', 'respuestas_usuario', 'puntaje', 'respuesta_enviada', 'config_actual_quiz', 'results_saved']
    for key in keys_to_delete:
        if key in st.session_state:
            del st.session_state[key]
    st.session_state.pagina = 'inicio'
    st.rerun()


def generar_quiz_con_ia(config):
    """
    Genera un quiz utilizando la IA, cargando el prompt y el modelo desde la configuración
    global y aplicando un sistema de reintentos.
    """
    prompt_template = get_global_setting('ia_prompt', DEFAULT_IA_PROMPT)
    model_name = get_global_setting('ia_model', DEFAULT_IA_MODEL)

    try:
        model = genai.GenerativeModel(model_name)
    except Exception as e:
        st.error(f"Error al inicializar el modelo de IA '{model_name}': {e}")
        st.error("Por favor, revisa el nombre del modelo en el Área del Profesor > Opciones Avanzadas.")
        return None

    MAX_RETRIES = 3
    asignatura = config['asignatura']
    temas_lista = config['temas']
    num_preguntas = config['num_preguntas']
    dificultad = config['dificultad']
    temas_str = ", ".join(temas_lista)

    prompt = prompt_template.format(
        asignatura=asignatura,
        num_preguntas=num_preguntas,
        dificultad=dificultad,
        temas_str=temas_str
    )

    safety_settings = {
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    }

    for attempt in range(MAX_RETRIES):
        try:
            response = model.generate_content(prompt, safety_settings=safety_settings)
            if not response.parts:
                st.warning(f"Intento {attempt + 1}/{MAX_RETRIES} falló: La IA no devolvió contenido. Reintentando...")
                time.sleep(1)
                continue
            
            json_text = response.text.strip()
            match = re.search(r'\[.*\]', json_text, re.DOTALL)
            if match:
                json_text = match.group(0)
            else:
                json_text = json_text.replace("```json", "").replace("```", "").strip()

            json_text = re.sub(r'(?<!\\)\\(?!["\\/bfnrt])', r'\\\\', json_text)
            quiz_data = json.loads(json_text)

            if isinstance(quiz_data, list) and len(quiz_data) == num_preguntas and all('pregunta' in q for q in quiz_data):
                return quiz_data
            else:
                st.warning(f"Intento {attempt + 1}/{MAX_RETRIES} falló: El formato JSON es válido pero no cumple la estructura. Reintentando...")
                time.sleep(1)
        except json.JSONDecodeError as e:
            st.warning(f"Intento {attempt + 1}/{MAX_RETRIES} falló al decodificar JSON: {e}. Reintentando...")
            st.code(json_text, language="text")
            time.sleep(1)
        except Exception as e:
            st.warning(f"Intento {attempt + 1}/{MAX_RETRIES} falló con un error: {e}. Reintentando...")
            time.sleep(1)
            
    st.error(f"No se pudo generar el quiz después de {MAX_RETRIES} intentos.")
    return None

def shuffle_question_options(question_data):
    """
    Toma los datos de una pregunta, baraja sus opciones y actualiza la clave
    de la respuesta correcta para que coincida con la nueva posición.
    """
    options = question_data['opciones']
    correct_key = question_data['respuesta_correcta']
    correct_text = options[correct_key]

    option_items = list(options.items())
    random.shuffle(option_items)

    new_options = {}
    new_correct_key = ''
    new_keys = ['A', 'B', 'C', 'D']

    for i, (original_key, text) in enumerate(option_items):
        new_key = new_keys[i]
        new_options[new_key] = text
        if text == correct_text:
            new_correct_key = new_key

    shuffled_question = question_data.copy()
    shuffled_question['opciones'] = new_options
    shuffled_question['respuesta_correcta'] = new_correct_key

    return shuffled_question


# --- FUNCIONES DE INTERFAZ DE ADMINISTRADOR ---
def check_password():
    st.subheader("Acceso Restringido", divider=True)
    password = st.text_input("Ingresa la contraseña:", type="password", key="pwd_input")
    if st.button("Acceder"):
        try:
            if password == st.secrets["admin"]["password"]:
                st.session_state.password_correct = True
                st.rerun()
            else: st.error("La contraseña es incorrecta.")
        except KeyError: st.error("Contraseña de administrador no configurada.")


def clear_review_state():
    """Elimina del session_state el quiz en revisión y todas sus claves de edición."""
    if 'quiz_for_review' in st.session_state:
        num_questions = len(st.session_state.quiz_for_review.get('content', []))
        for i in range(num_questions):
            for key_part in ['pregunta', 'opcion_A', 'opcion_B', 'opcion_C', 'opcion_D', 'correcta', 'explicacion']:
                widget_key = f"review_q{i}_{key_part}"
                if widget_key in st.session_state:
                    del st.session_state[widget_key]
        del st.session_state.quiz_for_review


def admin_panel():
    tab_anuncios, tab_gestion_config, tab_activar_quiz, tab_opciones = st.tabs(
        [":clipboard: Anuncios", "📚 Gestionar Configuraciones", "✅ Generar y Activar Actividades", "⚙️ Opciones Avanzadas"]
    )

    with tab_anuncios:
        st.subheader("Anuncio General para Estudiantes", divider=True)
        current_message = get_global_message()
        new_message = st.text_area(
            "Este mensaje se mostrará a todos los estudiantes en la pestaña 'Actividades'.",
            value=current_message,
            height=150,
            key="global_message_input"
        )
        if st.button("Guardar Anuncio", type="primary"):
            save_global_message(new_message)
            st.success("¡Anuncio guardado correctamente!")
            time.sleep(1)
            st.rerun()

    with tab_gestion_config:
        st.subheader("Panel de Configuración de Quizzes", divider=True)
        st.markdown("Crea, edita o elimina las plantillas de las actividades (asignaturas y unidades).")
        
        parent_profiles = get_all_profiles()
        create_new_option = "-- Crear nueva asignatura --"
        options = [create_new_option] + parent_profiles

        selected_parent_profile = st.selectbox("Selecciona una asignatura:", options, key="admin_parent_select")

        config_data = {}
        profile_name_input = ""
        selected_config_id = None
        
        if selected_parent_profile == create_new_option:
            st.subheader("Crear nueva asignatura")
            coll1, coll2  = st.columns(2)
            with coll1:
                profile_name_input = st.text_input("Nombre nueva asignatura", placeholder="Asignatura nueva")
            with coll2:
                variant_name_input = st.text_input("Unidad de aprendizaje", placeholder="#1: Nombre del tema general")
            config_data = {'asignatura': '', 'temas': [], 'num_preguntas': 7, 'dificultad': 'fácil/intermedio', 'show_feedback': 1}
        else:
            profile_name_input = selected_parent_profile
            st.subheader(f"Gestionar unidades de: {selected_parent_profile}")
            variants = get_variants_for_profile(selected_parent_profile)
            variant_options = {var[0]: var[1] for var in variants}
            
            create_variant_option_id = -1
            variant_options[create_variant_option_id] = "-- Crear Nueva Unidad --"
            
            selected_config_id = st.selectbox(
                "Selecciona una unidad para editar o crea una nueva:", 
                options=variant_options.keys(), 
                format_func=lambda id: variant_options[id],
                key="admin_variant_select"
            )
            
            if selected_config_id == create_variant_option_id:
                variant_name_input = st.text_input("Nombre de la Nueva Unidad:")
                config_data = {'asignatura': '', 'temas': [], 'num_preguntas': 7, 'dificultad': 'fácil/intermedio', 'show_feedback': 1}
            else:
                config_data = load_config_from_db(selected_config_id)
                variant_name_input = config_data.get('variant_name', '')

        with st.form("admin_form"):
            asignatura = st.text_input("Nombre completo de la asignatura", value=config_data.get('asignatura', ''))
            temas_input = st.text_area("Temas (separados por comas)", value=", ".join(config_data.get('temas', [])), height=100)
            c1, c2 = st.columns(2)
            num_preguntas = c1.number_input("Nº de preguntas", 3, 12, config_data.get('num_preguntas', 7))
            dificultad_options = ["fácil/intermedio", "intermedio/avanzado", "avanzado/difícil"]
            try:
                current_dificultad_index = dificultad_options.index(config_data.get('dificultad', 'fácil/intermedio'))
            except ValueError: current_dificultad_index = 1
            dificultad = c2.selectbox("Dificultad", dificultad_options, index=current_dificultad_index)
            
            show_feedback_toggle = st.toggle(
                "Mostrar retroalimentación inmediata",
                value=bool(config_data.get('show_feedback', 1)),
                help="Si está activo, los estudiantes verán la respuesta correcta y la explicación después de cada pregunta. Si no, solo verán la calificación final."
            )
            #st.caption("Recomendación: Para una clase formativa elije mas preguntas con dificultad baja, mientras que para una clase evaluativa elije menos preguntas con dificultad alta")
            
            submitted = st.form_submit_button("Guardar Configuración", type="secondary")
            if submitted:
                if not profile_name_input or not variant_name_input:
                    st.error("El nombre de la asignatura y de la unidad no pueden estar vacíos.")
                else:
                    temas_lista = [t.strip() for t in temas_input.split(',') if t.strip()]
                    save_config_to_db(profile_name_input, variant_name_input, asignatura, temas_lista, num_preguntas, dificultad, show_feedback_toggle)
                    st.success(f"¡Configuración '{profile_name_input} - {variant_name_input}' guardada correctamente!")
                    time.sleep(1)
                    st.rerun()

        if selected_parent_profile != create_new_option and selected_config_id != -1 and selected_config_id is not None:
            st.markdown("---")
            if st.button("Eliminar esta Unidad", type="secondary"):
                st.session_state.config_to_delete = selected_config_id
            
            if 'config_to_delete' in st.session_state and st.session_state.config_to_delete == selected_config_id:
                 st.warning(f"**¿Estás seguro de que quieres eliminar la unidad '{variant_name_input}' de la asignatura '{profile_name_input}'?**")
                 c1, c2 = st.columns(2)
                 if c1.button("Sí, eliminar", type="primary"):
                     delete_config_from_db(st.session_state.config_to_delete)
                     del st.session_state.config_to_delete
                     st.success("Unidad eliminada.")
                     time.sleep(1)
                     st.rerun()
                 if c2.button("Cancelar"):
                     del st.session_state.config_to_delete
                     st.rerun()

    with tab_activar_quiz:
        if 'quiz_for_review' in st.session_state:
            review_data = st.session_state.quiz_for_review
            st.subheader("Previsualización y Edición de la Actividad", divider='rainbow')
            st.info("Revisa la actividad generada. Puedes expandir cada pregunta para editarla si es necesario. Cuando termines, aprueba los cambios para que esté disponible para los estudiantes.")

            with st.form("review_form"):
                quiz_content = review_data['content']
                
                for i, q_data in enumerate(quiz_content):
                    pregunta_resumen = q_data['pregunta'].split('\n\n')[1] if '\n\n' in q_data['pregunta'] else q_data['pregunta']
                    with st.expander(f"**Pregunta {i+1}:** {pregunta_resumen.strip()}", expanded=i==0):
                        st.markdown("---")
                        st.markdown("##### Así lo verá el estudiante:")
                        with st.container(border=True):
                            st.markdown(q_data['pregunta'])
                            st.radio(
                                "Opciones:", 
                                options=q_data['opciones'].keys(), 
                                format_func=lambda k: f"{k}: {q_data['opciones'][k]}", 
                                key=f"preview_q{i}_radio",
                                disabled=True,
                                index=list(q_data['opciones'].keys()).index(q_data['respuesta_correcta'])
                            )
                        st.markdown("---")
                        
                        st.markdown("##### Editar campos:")
                        st.text_area(label="Texto de la Pregunta (Markdown/LaTeX)", value=q_data['pregunta'], key=f"review_q{i}_pregunta", height=200)
                        
                        opciones_keys = ['A', 'B', 'C', 'D']
                        cols = st.columns(2)
                        for idx, opt_key in enumerate(opciones_keys):
                            cols[idx % 2].text_input(label=f"Opción {opt_key}", value=q_data['opciones'].get(opt_key, ""), key=f"review_q{i}_opcion_{opt_key}")
                        
                        st.radio(label="**Respuesta Correcta**", options=opciones_keys, index=opciones_keys.index(q_data['respuesta_correcta']) if q_data['respuesta_correcta'] in opciones_keys else 0, key=f"review_q{i}_correcta", horizontal=True)
                        st.text_area(label="Explicación", value=q_data['explicacion'], key=f"review_q{i}_explicacion", height=150)

                submitted = st.form_submit_button("✅ Aprobar y Activar Cambios", type="primary", width='stretch')
                if submitted:
                    edited_quiz_content = []
                    for i in range(len(quiz_content)):
                        new_q = {
                            "pregunta": st.session_state[f"review_q{i}_pregunta"],
                            "opciones": { "A": st.session_state[f"review_q{i}_opcion_A"], "B": st.session_state[f"review_q{i}_opcion_B"], "C": st.session_state[f"review_q{i}_opcion_C"], "D": st.session_state[f"review_q{i}_opcion_D"]},
                            "respuesta_correcta": st.session_state[f"review_q{i}_correcta"],
                            "explicacion": st.session_state[f"review_q{i}_explicacion"],
                        }
                        edited_quiz_content.append(new_q)
                    
                    config_id = review_data['config_id']
                    save_and_activate_quiz(config_id, edited_quiz_content)
                    
                    st.success("¡Actividad revisada y activada con éxito! Los estudiantes ya pueden acceder a ella.")
                    clear_review_state()
                    time.sleep(2)
                    st.rerun()

            if st.button("❌ Descartar y Volver", width='stretch'):
                clear_review_state()
                st.info("Generación descartada. Volviendo a la selección.")
                time.sleep(1)
                st.rerun()
        else:
            st.subheader("Generar y Activar Actividades para Estudiantes", divider=True)
            st.info("Gestiona el estado de cada unidad de aprendizaje. Genera, revisa, edita y activa el contenido para los estudiantes.")
            
            profiles = get_all_profiles()
            if not profiles:
                st.warning("Primero debes crear una configuración en la pestaña 'Gestionar Configuraciones'.")
            else:
                for profile_name in profiles:
                    st.markdown(f"### {profile_name}")
                    variants = get_variants_for_profile(profile_name)
                    if not variants:
                        st.caption("No hay unidades configuradas para esta asignatura.")
                        continue
                    
                    for config_id, variant_name in variants:
                        with st.container(border=True):
                            active_quiz = get_active_quiz_for_config(config_id)
                            quiz_has_been_generated = check_if_any_quiz_exists(config_id)
                            
                            col1, col2, col3, col4 = st.columns([2, 1, 1, 1.2])

                            with col1:
                                st.markdown(f"**{variant_name}**")
                                if active_quiz:
                                    st.success("✅ Activa")
                                else:
                                    st.warning("⚠️ Inactiva")

                            with col2:
                                if st.button("Generar", key=f"gen_{config_id}", width='stretch', help="Crea una nueva versión con IA para revisarla y activarla."):
                                    config = load_config_from_db(config_id)
                                    with st.spinner(f"Generando ..."):
                                        quiz_content = generar_quiz_con_ia(config)
                                        if quiz_content:
                                            st.session_state.quiz_for_review = {
                                                "config_id": config_id,
                                                "content": quiz_content
                                            }
                                            st.rerun()

                            with col3:
                                if quiz_has_been_generated:
                                    if st.button("Editar", key=f"edit_{config_id}", width='stretch', help="Edita la versión más reciente de esta actividad (activa o inactiva)."):
                                        latest_quiz_data = get_latest_quiz_for_config(config_id)
                                        if latest_quiz_data:
                                            st.session_state.quiz_for_review = {
                                                "config_id": config_id,
                                                "content": latest_quiz_data
                                            }
                                            st.rerun()
                                        else:
                                            st.error("No se encontró ninguna versión de esta actividad para editar.")
                                else:
                                    st.write("") 

                            with col4:
                                if quiz_has_been_generated:
                                    is_currently_active = bool(active_quiz)
                                    new_status = st.toggle(
                                        "Estado",
                                        value=is_currently_active,
                                        key=f"toggle_{config_id}",
                                        label_visibility="collapsed",
                                        help="Activa o desactiva esta actividad para los estudiantes."
                                    )
                                    if new_status != is_currently_active:
                                        set_quiz_activation_status(config_id, new_status)
                                        st.toast(f"Actividad '{variant_name}' {'activada' if new_status else 'desactivada'}.")
                                        time.sleep(0.5)
                                        st.rerun()
                                else:
                                    st.caption("Generar para activar")

    with tab_opciones:
        st.subheader("Configuración de Inteligencia Artificial", divider=True)
        st.warning(
            "**Atención:** Modificar estos valores es una función avanzada. "
            "Un cambio incorrecto en el 'Prompt de Sistema', especialmente en las reglas de formato JSON, "
            "puede impedir que la IA genere actividades correctamente."
        )

        with st.form("ia_settings_form"):
            current_model = get_global_setting('ia_model', DEFAULT_IA_MODEL)
            current_prompt = get_global_setting('ia_prompt', DEFAULT_IA_PROMPT)

            new_model = st.text_input(
                "Modelo de IA a utilizar",
                value=current_model,
                help="Especifica el identificador del modelo de Google AI que se usará para generar las preguntas."
            )
            st.caption("Modelos recomendados: `models/gemini-1.5-flash-latest` (rápido y eficiente), `models/gemini-1.5-pro-latest` (más potente).")

            new_prompt = st.text_area(
                "Prompt de Sistema para la IA",
                value=current_prompt,
                height=400,
                help="Este es el conjunto de instrucciones que sigue la IA. Usa las variables {asignatura}, {temas_str}, {num_preguntas}, y {dificultad} que serán reemplazadas dinámicamente."
            )

            submitted = st.form_submit_button("Guardar Configuración de IA", type="primary", width='stretch')
            if submitted:
                save_global_setting('ia_model', new_model)
                save_global_setting('ia_prompt', new_prompt)
                st.success("¡Configuración de IA guardada correctamente!")
                time.sleep(1)
                st.rerun()
        
        if st.button("Restaurar Configuración de IA por Defecto"):
            st.session_state.confirm_restore_ia = True

        if 'confirm_restore_ia' in st.session_state:
            st.warning("**¿Estás seguro de que quieres restaurar el modelo y el prompt a sus valores originales?** Se perderán tus personalizaciones.")
            c1, c2 = st.columns(2)
            if c1.button("Sí, restaurar", type="primary"):
                save_global_setting('ia_model', DEFAULT_IA_MODEL)
                save_global_setting('ia_prompt', DEFAULT_IA_PROMPT)
                del st.session_state.confirm_restore_ia
                st.success("Configuración de IA restaurada.")
                time.sleep(1)
                st.rerun()
            if c2.button("Cancelar"):
                del st.session_state.confirm_restore_ia
                st.rerun()

        st.subheader("Zona de Peligro", divider=True)
        
        if st.button("Limpiar TODO el Ranking", type="secondary"):
            st.session_state.confirm_clear_ranking = True
        
        if 'confirm_clear_ranking' in st.session_state and st.session_state.confirm_clear_ranking:
            st.warning("**¡ADVERTENCIA!** Vas a eliminar TODOS los resultados de TODOS los estudiantes.")
            col1, col2 = st.columns(2)
            if col1.button("Sí, eliminar todo", type="primary"):
                clear_all_results_from_db()
                del st.session_state.confirm_clear_ranking
                st.success("El ranking ha sido limpiado.")
                time.sleep(2)
                st.rerun()
            if col2.button("No, cancelar"):
                del st.session_state.confirm_clear_ranking
                st.rerun()

        st.subheader("Sesión de Administrador", divider=True)
        if st.button("Cerrar Sesión de Administrador"):
            st.session_state.password_correct = False
            st.rerun()

# --- INICIALIZACIÓN DEL ESTADO DE LA SESIÓN ---
if 'pagina' not in st.session_state: st.session_state.pagina = 'inicio'
if 'nombre_estudiante' not in st.session_state: st.session_state.nombre_estudiante = ""
if 'password_correct' not in st.session_state: st.session_state.password_correct = False

# --- PANELES Y PESTAÑAS ---
#st.subheader("Actividades formativas de refuerzo", divider=True)
tab_examen, tab_ranking, tab_admin = st.tabs(["Actividades", "Registro de participaciones", "Área del profesor"])

with tab_admin:
    if st.session_state.password_correct:
        admin_panel()
    else:
        check_password()

def display_attempt_review(attempt_details):
    """Muestra la vista detallada de un intento de quiz."""
    student_name = attempt_details['student_name']
    st.header(f"Revisando la actividad de: {student_name}")
    st.caption(f"Realizada el: {pd.to_datetime(attempt_details['timestamp']).strftime('%Y-%m-%d %H:%M')}")
    st.info("A continuación se muestra cada pregunta tal como la vio el estudiante, junto con su respuesta y la corrección.")

    quiz_snapshot = json.loads(attempt_details['quiz_snapshot_json'])
    student_answers = json.loads(attempt_details['student_answers_json'])

    for idx, question_data in enumerate(quiz_snapshot):
        with st.container(border=True):
            st.subheader(f"Pregunta {idx + 1}")
            st.markdown(question_data['pregunta'])

            student_answer_key = student_answers.get(str(idx)) # Las claves JSON pueden ser strings
            correct_answer_key = question_data['respuesta_correcta']

            st.markdown("---")
            st.write("**Respuesta del estudiante:**")
            if student_answer_key is None:
                st.warning("El estudiante no respondió a esta pregunta.")
            elif student_answer_key == correct_answer_key:
                st.success(f"**{student_answer_key}:** {question_data['opciones'][student_answer_key]} (Correcta)")
            else:
                st.error(f"**{student_answer_key}:** {question_data['opciones'][student_answer_key]} (Incorrecta)")

            st.write("**Respuesta correcta:**")
            st.info(f"**{correct_answer_key}:** {question_data['opciones'][correct_answer_key]}")
            
            with st.expander("Ver explicación completa"):
                st.markdown(question_data['explicacion'])
    
    if st.button("← Volver al ranking"):
        del st.session_state.reviewing_attempt_id
        st.rerun()

# --- BLOQUE 'with tab_ranking:' CON VISTAS CONDICIONALES ---

@st.cache_data
def convert_df_to_csv(df):
    """Convierte un DataFrame de pandas a un archivo CSV codificado en UTF-8."""
    return df.to_csv(index=True).encode('utf-8')


@st.cache_data
def calculate_gradebook(df, policy):
    """
    Toma el DataFrame de resultados y la política de calificación,
    y devuelve el DataFrame procesado para el libro de calificaciones.
    """
    processed_df = df.copy()
    processed_df['timestamp'] = pd.to_datetime(processed_df['timestamp'])

    if policy == "Calificación más reciente":
        final_grades_df = processed_df.sort_values('timestamp').groupby(['student_name', 'variant_name']).last().reset_index()
    elif policy == "Promedio de calificaciones":
        final_grades_df = processed_df.groupby(['student_name', 'variant_name'])['grade'].mean().reset_index()
    else:  # "Calificación más alta" por defecto
        final_grades_df = processed_df.sort_values('grade').groupby(['student_name', 'variant_name']).last().reset_index()

    gradebook_view = final_grades_df.pivot_table(
        index='student_name', columns='variant_name', values='grade'
    )
    return gradebook_view


with tab_ranking:
    #if st.session_state.get('pagina') == 'quiz':
        #with st.container(border=True):
            #col_text, col_button = st.columns([3, 1])
            #with col_text:
                #st.caption("¡Cuidado! Tienes una actividad en progreso. Si sales, tu progreso no se guardará.")
            #with col_button:
                #if st.button("Salir", type="primary", use_container_width=True):
                    #reset_quiz_state()
        #st.divider()
        
    # 1. LÓGICA PARA MOSTRAR UNA REVISIÓN INDIVIDUAL (SÓLO PROFESOR)
    if 'reviewing_attempt_id' in st.session_state and st.session_state.password_correct:
        client = get_db_client()
        rs = client.execute("SELECT * FROM quiz_results WHERE id = ?", (st.session_state.reviewing_attempt_id,))
        #client.close()
        if rs.rows:
            attempt_details = {col: rs.rows[0][idx] for idx, col in enumerate(rs.columns)}
            display_attempt_review(attempt_details)
        else:
            st.error("No se encontró el intento seleccionado.")
            if st.button("Volver"): del st.session_state.reviewing_attempt_id; st.rerun()
    
    # 2. VISTA PRINCIPAL (Libro de Calificaciones para Profesor, Lista para Estudiantes)
    else:
        col_title, col_button = st.columns([4, 1])
        with col_title:
            st.subheader("Participaciones por asignatura", anchor=False)
        with col_button:
            if st.button("Refrescar", width='stretch', help="Vuelve a cargar los resultados desde la base de datos y resetea cualquier quiz activo."):
            	reset_quiz_state(); get_results_by_profile_as_df.clear(); st.toast("¡Registro actualizado!"); st.rerun()
		
			

        client = get_db_client(); rs = client.execute("SELECT DISTINCT profile_name FROM quiz_results ORDER BY profile_name"); #client.close()
        profiles_with_results = [row[0] for row in rs.rows]

        if not profiles_with_results:
            st.info("Aún no hay resultados para mostrar.")
        else:
            profile_tabs = st.tabs(profiles_with_results)
            for i, profile_name in enumerate(profiles_with_results):
                with profile_tabs[i]:
                    full_results_df = get_results_by_profile_as_df(profile_name)

                    # --- VISTA DE LIBRO DE CALIFICACIONES (SÓLO PROFESOR) ---
                    if st.session_state.password_correct:
                        st.subheader("Libro de Calificaciones (Solo Unidades Evaluativas)", divider=True)
                        st.caption("Esta vista solo incluye los resultados de las unidades configuradas sin retroalimentación inmediata.")
                        
                        configs_df = get_configs_for_profile_as_df(profile_name)
                        evaluative_variants = configs_df[configs_df['show_feedback'] == 0]['variant_name'].tolist()
                        gradebook_data_df = full_results_df[full_results_df['variant_name'].isin(evaluative_variants)]

                        if gradebook_data_df.empty:
                            st.info("No hay resultados de unidades evaluativas para mostrar en el libro de calificaciones.")
                        else:
                            policy = st.selectbox(
                                "Política de Calificación:",
                                options=["Calificación más alta", "Calificación más reciente", "Promedio de calificaciones"],
                                key=f"grading_policy_{profile_name}",
                                help="Define cómo se consolidan múltiples intentos de un mismo estudiante en una sola nota."
                            )
                            
                            #processed_df = gradebook_data_df.copy()
                            #processed_df['timestamp'] = pd.to_datetime(processed_df['timestamp'])

                            #if policy == "Calificación más reciente":
                                #final_grades_df = processed_df.sort_values('timestamp').groupby(['student_name', 'variant_name']).last().reset_index()
                            #elif policy == "Promedio de calificaciones":
                                #final_grades_df = processed_df.groupby(['student_name', 'variant_name'])['grade'].mean().reset_index()
                            #else: # "Calificación más alta" por defecto (LÓGICA CORREGIDA)
                                #final_grades_df = processed_df.sort_values('grade').groupby(['student_name', 'variant_name']).last().reset_index()

                            #gradebook_view = final_grades_df.pivot_table(
                                #index='student_name', columns='variant_name', values='grade'
                            #)
                            
                            gradebook_view = calculate_gradebook(gradebook_data_df, policy)

                            st.dataframe(gradebook_view.style.format("{:.2f}", na_rep='-').highlight_null(props="color: #666;"), width='stretch')
                            
                            csv_data = convert_df_to_csv(gradebook_view)
                            st.download_button(
                               label="📥 Descargar como CSV",
                               data=csv_data,
                               file_name=f'calificaciones_evaluativas_{profile_name.replace(" ", "_")}.csv',
                               mime='text/csv',
                            )
                        
                        st.subheader("Registro de Todos los Intentos (Auditoría)", divider=True)


                    # --- VISTA DE INTENTOS INDIVIDUALES (SE MANTIENE IGUAL, MUESTRA TODO) ---
                    variants_with_results = sorted(full_results_df['variant_name'].unique().tolist())
                    all_variants_option = "-- Todas las Unidades --"
                    selected_variant = st.selectbox("Filtrar por unidad: ", [all_variants_option] + variants_with_results, key=f"variant_filter_{profile_name}")
                    df_to_display = full_results_df if selected_variant == all_variants_option else full_results_df[full_results_df['variant_name'] == selected_variant]
                    
                    if df_to_display.empty:
                        st.info("No hay registros que coincidan con el filtro seleccionado.")
                    else:
                        page_size = 10
                        page_key = f"page_number_{profile_name}_{selected_variant}"
                        st.session_state.setdefault(page_key, 1)

                        total_rows = len(df_to_display)
                        total_pages = math.ceil(total_rows / page_size) if total_rows > 0 else 1
                        if st.session_state[page_key] > total_pages: st.session_state[page_key] = total_pages

                        offset = (st.session_state[page_key] - 1) * page_size
                        paginated_df = df_to_display.iloc[offset : offset + page_size]

                        if st.session_state.password_correct:
                            # VISTA DE TARJETAS PARA EL PROFESOR
                            for _, row in paginated_df.iterrows():
                                with st.container(border=True):
                                    c1, c2, c3, c4 = st.columns([2, 1, 1, 1.2])
                                    with c1:
                                        st.markdown(f"**{row['student_name']}**")
                                        st.caption(f"Unidad: {row['variant_name']}")
                                        fecha = pd.to_datetime(row['timestamp']).strftime('%d de %b, %Y - %H:%M')
                                        st.caption(fecha)
                                    with c2: st.metric(label="Aciertos", value=f"{row['score']}/{row['total_questions']}")
                                    with c3:
                                        grade_value = row['grade']
                                        delta_color = "normal" if grade_value >= 9.5 else "inverse"
                                        st.metric(label="Calificación", value=f"{grade_value:.2f}", delta_color=delta_color)
                                    with c4:
                                        st.write("") 
                                        if st.button("Revisar Intento", key=f"review_{row['id']}", width='stretch'):
                                            st.session_state.reviewing_attempt_id = row['id']; st.rerun()
                        else:
                            # VISTA DE TABLA PARA EL ESTUDIANTE
                            df_for_student = paginated_df.copy()
                            df_for_student.rename(columns={'student_name': 'Estudiante', 'variant_name': 'Unidad', 'grade': 'Nota', 'score': 'Aciertos', 'total_questions': 'Preguntas', 'timestamp': 'Fecha'}, inplace=True)
                            df_for_student['Fecha'] = pd.to_datetime(df_for_student['Fecha']).dt.strftime('%Y-%m-%d %H:%M')
                            df_for_student['Nota'] = df_for_student['Nota'].map('{:.2f}'.format)
                            df_for_student['Puntaje'] = df_for_student['Aciertos'].astype(str) + '/' + df_for_student['Preguntas'].astype(str)
                            display_columns = ['Estudiante', 'Unidad', 'Puntaje', 'Nota', 'Fecha']
                            st.dataframe(df_for_student[display_columns], width='stretch', hide_index=True)
                        
                        # CONTROLES DE PAGINACIÓN
                        if total_pages > 1:
                            nav_cols = st.columns([1, 2, 1])
                            with nav_cols[0]:
                                if st.button("← Anterior", width='stretch', disabled=(st.session_state[page_key] <= 1), key=f"prev_{profile_name}_{selected_variant}"):
                                    st.session_state[page_key] -= 1; st.rerun()
                            with nav_cols[1]:
                                st.write(f"<div style='text-align: center;'>Página {st.session_state[page_key]} de {total_pages}</div>", unsafe_allow_html=True)
                            with nav_cols[2]:
                                if st.button("Siguiente →", width='stretch', disabled=(st.session_state[page_key] >= total_pages), key=f"next_{profile_name}_{selected_variant}"):
                                    st.session_state[page_key] += 1; st.rerun()


with tab_examen:	
    # 1. INICIALIZAR ESTADO DE SESIÓN PARA TOKEN Y USUARIO
    if 'token' not in st.session_state: st.session_state.token = None
    if 'user_info' not in st.session_state: st.session_state.user_info = None

    # 2. MOSTRAR BOTÓN DE LOGIN SI EL USUARIO NO ESTÁ AUTENTICADO
    if st.session_state.token is None:
        st.subheader("Actividades formativas de refuerzo", divider=True)
        st.info("Para continuar, por favor, inicia sesión con tu cuenta de Google.")
        
        result = oauth2.authorize_button(
            name="Iniciar Sesión con Google",
            icon="https://www.google.com.tw/favicon.ico",
            width='stretch',
            redirect_uri=REDIRECT_URI,
            scope="openid https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/userinfo.profile"
        )

        if result and "token" in result:
            st.session_state.token = result.get('token')
            id_token = st.session_state.token.get('id_token')
            
            # Decodificar el JWT (id_token) para obtener los datos del usuario
            if id_token:
                payload = id_token.split('.')[1]
                payload += '=' * (-len(payload) % 4)
                user_data_bytes = base64.b64decode(payload)
                user_data_json = user_data_bytes.decode('utf-8')
                st.session_state.user_info = json.loads(user_data_json)
            
            st.rerun()

    # 3. MOSTRAR INTERFAZ PRINCIPAL SI EL USUARIO YA ESTÁ AUTENTICADO
    else:
        # VISTA DE INICIO: SELECCIÓN DE ACTIVIDAD
        if st.session_state.pagina == 'inicio':
            user_info = st.session_state.user_info
            
            # Usar el nombre completo (clave 'name') y el email como identificador único
            student_identifier = f"{user_info.get('name', 'N/A')}"
            #student_identifier = f"{user_info.get('name', 'N/A')} ({user_info.get('email', 'N/A')})"
            st.session_state.nombre_estudiante = student_identifier 

            st.subheader(f"Bienvenido, {user_info.get('name', 'Estudiante')}", divider=True)
            
            global_message = get_global_message()
            if global_message:
                st.info(f"{global_message}")
            
            available_quizzes = get_all_profiles()
            if not available_quizzes:
                st.warning("Aún no hay actividades configuradas. Pídele a tu profesor que cree una.")
            else:
                col11, col22 = st.columns([1,1])
                
                with col11:                    
                    selected_quiz_profile = st.radio(
                        "**Elige la asignatura:**",
                        available_quizzes,                        
                        key="student_profile_select",
                        index=None,
                        on_change=lambda: st.session_state.pop('student_variant_select', None)
                    )

                selected_config_id = None
                is_selected_variant_active = False
                with col22:
                    if selected_quiz_profile:
                        variants_with_status = get_variants_with_status_for_profile(selected_quiz_profile)
                        
                        if variants_with_status:
                            # Ordena la lista: primero por estado activo (descendente), luego por nombre (ascendente)
                            sorted_variants = sorted(variants_with_status, key=lambda var: (-var[2], var[1]))
                            
                            # Crea una lista ordenada de los IDs para el widget de radio
                            sorted_option_ids = [var[0] for var in sorted_variants]

                            # Los diccionarios para buscar nombres y estados no necesitan estar ordenados
                            variant_options = {var[0]: var[1] for var in variants_with_status}
                            active_status_map = {var[0]: var[2] for var in variants_with_status}

                            def format_variant_label(config_id):
                                label = variant_options.get(config_id, "Error")
                                is_active = active_status_map.get(config_id, 0)
                                if is_active:
                                    return label  # Texto normal para unidades activas
                                else:
                                    # Markdown para texto en rojo y cursiva para unidades inactivas
                                    return f":gray[*{label}*]"

                            selected_config_id = st.radio(
                                "**Elige la unidad de aprendizaje:**",
                                options=sorted_option_ids,  # Usa la nueva lista ordenada de IDs
                                format_func=format_variant_label,
                                key="student_variant_select",
                                index=None
                            )

                            if selected_config_id:
                                is_selected_variant_active = active_status_map.get(selected_config_id, 0) == 1
                        else:
                            st.info("Esta asignatura no tiene unidades configuradas.")

                if st.button("Iniciar Actividad", type="primary", disabled=not is_selected_variant_active):
                    if selected_config_id:
                        config = load_config_from_db(selected_config_id)
                        st.session_state.config_actual_quiz = config
                        
                        with st.spinner(f"¡Mucha suerte, {user_info.get('name')}! Preparando tu actividad..."):
                            quiz_data = get_active_quiz_for_config(selected_config_id)
                            
                            if quiz_data:
                                time.sleep(2)
                                if not config.get('show_feedback', 1): random.shuffle(quiz_data)
                                
                                num_a_presentar = config['num_preguntas']
                                quiz_subset = quiz_data[:num_a_presentar]
                                
                                #shuffled_quiz = [shuffle_question_options(q) for q in quiz_data]
                                shuffled_quiz = [shuffle_question_options(q) for q in quiz_subset]
                                st.session_state.quiz_generado = shuffled_quiz
                                
                                st.session_state.pagina = 'quiz'
                                st.session_state.pregunta_actual = 0
                                st.session_state.respuestas_usuario = {}
                                st.session_state.puntaje = 0
                                st.session_state.respuesta_enviada = False
                                st.rerun()
                            else:
                                st.error("Lo sentimos, esta actividad no está activada.")
                    else:
                        st.warning("Debes seleccionar una asignatura y una unidad para continuar.")
                
                if selected_config_id and not is_selected_variant_active:
                    st.warning("La unidad seleccionada no está disponible en este momento.")

            # Añadir botón de cerrar sesión al final de la página de inicio
            st.markdown("---")
            if st.button("Cerrar Sesión"):
                st.session_state.token = None
                st.session_state.user_info = None
                reset_quiz_state() # Llama a tu función para limpiar el estado del quiz
                st.rerun()

        # VISTA DEL QUIZ: MOSTRAR PREGUNTAS
        elif st.session_state.pagina == 'quiz':
            config = st.session_state.config_actual_quiz
            num_preguntas = config['num_preguntas']        
            st.markdown(f"#### Actividad para {st.session_state.nombre_estudiante}")        
            st.progress((st.session_state.pregunta_actual + 1) / num_preguntas)
            
            idx = st.session_state.pregunta_actual
            q_info = st.session_state.quiz_generado[idx]
            st.subheader(f"Actividad {idx + 1}/{num_preguntas}")
            st.caption(f"**Asignatura:** {config.get('asignatura', 'N/A')} ({config.get('variant_name', 'N/A')})")
            
            show_feedback_enabled = config.get('show_feedback', 1) == 1
            pregunta_a_mostrar = q_info['pregunta']
            if not show_feedback_enabled:
                partes = pregunta_a_mostrar.split('\n\n')
                # Si la pregunta tiene más de un párrafo (idealmente 3),
                # se unen los dos últimos para mostrarlos.
                if len(partes) > 1:
                    pregunta_a_mostrar = '\n\n'.join(partes[-1:])
            st.markdown(f"{pregunta_a_mostrar}")
            
            with st.form(key=f"form_q_{idx}"):
                opciones = q_info.get('opciones', {})
                if isinstance(opciones, list):
                    letras_opcion = [chr(65 + i) for i in range(len(opciones))]
                    opciones_normalizadas = {}
                    for letra, texto_opcion in zip(letras_opcion, opciones):
                        texto_limpio = re.sub(r'^[A-Z][\)\.]\s*', '', str(texto_opcion)).strip()
                        opciones_normalizadas[letra] = texto_limpio
                    opciones = opciones_normalizadas
                
                resp_usr = st.radio("Respuesta:", opciones.keys(), index=None, format_func=lambda k: f"{k}: {opciones.get(k, '')}", key=f"r_{idx}", disabled=st.session_state.respuesta_enviada)
                
                is_last_question = (idx == num_preguntas - 1)
                
                if show_feedback_enabled:
                    submit_label = "Enviar Respuesta"
                else:
                    submit_label = "Siguiente Pregunta" if not is_last_question else "Ver Resultados"

                if st.form_submit_button(submit_label, disabled=st.session_state.respuesta_enviada):
                    st.session_state.respuestas_usuario[idx] = resp_usr
                    if resp_usr == q_info.get('respuesta_correcta'):
                        st.session_state.puntaje += 1
                    
                    if show_feedback_enabled:
                        st.session_state.respuesta_enviada = True
                    else:
                        if is_last_question:
                            st.session_state.pagina = 'resultados'
                        else:
                            st.session_state.pregunta_actual += 1
                    st.rerun()
                    
            #if st.button("Cancelar y volver al inicio", type="secondary"):
            	#reset_quiz_state()
            
            if st.session_state.respuesta_enviada:
                correcta = q_info.get('respuesta_correcta')
                elegida = st.session_state.respuestas_usuario.get(idx)
                
                if elegida == correcta: st.success(f"¡Correcto! La respuesta es la **{correcta}**.")
                else: st.error(f"**Incorrecto**. La respuesta correcta era **{correcta}**: {opciones.get(correcta, 'N/A')}")
                
                st.info(f"**Explicación:**\n\n{q_info.get('explicacion', 'No hay explicación disponible.')}")
                
                if idx < num_preguntas - 1:
                    if st.button("Siguiente Pregunta"):
                        st.session_state.pregunta_actual += 1
                        st.session_state.respuesta_enviada = False
                        st.rerun()
                else:
                    if st.button("Ver Resultados", type="primary"):
                        st.session_state.pagina = 'resultados'
                        st.rerun()
                        
        # VISTA DE RESULTADOS FINALES
        elif st.session_state.pagina == 'resultados':
            st.header("Resultados Finales")
            puntaje = st.session_state.puntaje
            config = st.session_state.config_actual_quiz
            #num_preguntas = config['num_preguntas']
            num_preguntas = len(st.session_state.quiz_generado)
            calif = (puntaje / num_preguntas) * 19 if num_preguntas > 0 else 0
            
            if 'results_saved' not in st.session_state:
                save_result_to_db(
                    student_name=st.session_state.nombre_estudiante,
                    profile_name=config['profile_name'],
                    variant_name=config['variant_name'],
                    score=puntaje,
                    total_questions=num_preguntas,
                    grade=calif,
                    quiz_snapshot=st.session_state.quiz_generado,
                    student_answers=st.session_state.respuestas_usuario
                )
                st.session_state.results_saved = True
                st.toast("¡Tu resultado ha sido guardado en el registro de participaciones!")

            c1, c2 = st.columns(2)
            c1.metric("Respuestas Correctas", f"{puntaje} de {num_preguntas}", border=True)
            c2.metric("Calificación", f"{calif:.2f}", border=True)
            if st.button("Volver al inicio"):
                reset_quiz_state()

#st.markdown("---")
st.caption("Versión alpha-1.1")
#st.caption("DEMAT-FEC-LUZ")

