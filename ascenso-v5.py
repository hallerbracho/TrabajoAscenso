import streamlit as st
import google.generativeai as genai
import json
import time
import re
import sqlite3
import pandas as pd
from datetime import datetime
import math # Para cálculos de paginación
from google.generativeai.types import HarmCategory, HarmBlockThreshold ### NUEVO ###

# --- Constante para el archivo de la base de datos ---
DB_FILE = "basedatos-v5.db"

# --- Funciones para interactuar con la Base de Datos ---

def init_db():
    """Inicializa la base de datos y crea las tablas e índices si no existen."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # MODIFICADO: Eliminamos 'mensaje_profesor' de esta tabla
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS quiz_configs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        profile_name TEXT NOT NULL,
        variant_name TEXT NOT NULL,
        asignatura TEXT,
        temas TEXT,
        num_preguntas INTEGER,
        dificultad TEXT,
        UNIQUE(profile_name, variant_name)
    )
    """)
    # NUEVO: Tabla para ajustes globales, como el mensaje del profesor
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS global_settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS quiz_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_name TEXT NOT NULL,
        profile_name TEXT NOT NULL,
        variant_name TEXT NOT NULL,
        score INTEGER NOT NULL,
        total_questions INTEGER NOT NULL,
        grade REAL NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    # Creación de índices para optimizar las consultas del ranking
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_results_profile ON quiz_results (profile_name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_results_grade_time ON quiz_results (grade, timestamp)")
    conn.commit()
    conn.close()

# NUEVO: Funciones para manejar el mensaje global
@st.cache_data
def get_global_message():
    """Obtiene el mensaje global del profesor desde la base de datos."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM global_settings WHERE key = ?", ('teacher_message',))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else ""

def save_global_message(message):
    """Guarda o actualiza el mensaje global del profesor en la base de datos."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # UPSERT: Inserta o reemplaza si la clave ya existe
    cursor.execute("""
    INSERT INTO global_settings (key, value) VALUES (?, ?)
    ON CONFLICT(key) DO UPDATE SET value = excluded.value
    """, ('teacher_message', message))
    conn.commit()
    conn.close()
    get_global_message.clear() # Limpiamos la caché para que se vea el cambio

@st.cache_data
def get_all_profiles():
    """Obtiene los nombres de todos los PERFILES PADRE de la DB."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT profile_name FROM quiz_configs ORDER BY profile_name")
    profiles = [row[0] for row in cursor.fetchall()]
    conn.close()
    return profiles

@st.cache_data
def get_variants_for_profile(profile_name):
    """Obtiene todas las variantes (id, nombre) para un perfil padre dado."""
    if not profile_name:
        return []
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, variant_name FROM quiz_configs WHERE profile_name = ? ORDER BY variant_name", (profile_name,))
    variants = cursor.fetchall() # Devuelve una lista de tuplas (id, variant_name)
    conn.close()
    return variants

@st.cache_data
def load_config_from_db(config_id):
    """Carga una configuración específica (una variante) desde la DB usando su ID."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM quiz_configs WHERE id = ?", (config_id,))
    config_row = cursor.fetchone()
    conn.close()
    if config_row:
        config = dict(config_row)
        config['temas'] = json.loads(config['temas'])
        return config
    return None

# MODIFICADO: Eliminamos el parámetro 'mensaje_profesor'
def save_config_to_db(profile_name, variant_name, asignatura, temas, num_preguntas, dificultad):
    """Guarda (inserta o actualiza) una configuración/variante en la DB."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    temas_json = json.dumps(temas)
    cursor.execute("""
    INSERT INTO quiz_configs (profile_name, variant_name, asignatura, temas, num_preguntas, dificultad)
    VALUES (?, ?, ?, ?, ?, ?)
    ON CONFLICT(profile_name, variant_name) DO UPDATE SET
        asignatura=excluded.asignatura,
        temas=excluded.temas,
        num_preguntas=excluded.num_preguntas,
        dificultad=excluded.dificultad
    """, (profile_name, variant_name, asignatura, temas_json, num_preguntas, dificultad))
    conn.commit()
    conn.close()
    get_all_profiles.clear()
    get_variants_for_profile.clear()
    load_config_from_db.clear()

def delete_config_from_db(config_id):
    """Elimina una configuración/variante específica de la DB por su ID."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM quiz_configs WHERE id = ?", (config_id,))
    conn.commit()
    conn.close()
    get_all_profiles.clear()
    get_variants_for_profile.clear()
    load_config_from_db.clear()

def save_result_to_db(student_name, profile_name, variant_name, score, total_questions, grade):
    """Guarda el resultado de un quiz en la base de datos."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO quiz_results (student_name, profile_name, variant_name, score, total_questions, grade, timestamp)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (student_name, profile_name, variant_name, score, total_questions, grade, datetime.now()))
    conn.commit()
    conn.close()
    get_results_by_profile_as_df.clear()

@st.cache_data
def get_results_by_profile_as_df(profile_name):
    """Obtiene TODOS los resultados de un perfil padre específico. Ideal para estadísticas."""
    conn = sqlite3.connect(DB_FILE)
    query = "SELECT * FROM quiz_results WHERE profile_name = ? ORDER BY grade DESC, timestamp DESC"
    df = pd.read_sql_query(query, conn, params=(profile_name,))
    conn.close()
    return df

def get_paginated_results(profile_name, limit, offset):
    """Obtiene una 'página' de resultados de un perfil padre específico."""
    conn = sqlite3.connect(DB_FILE)
    query = "SELECT * FROM quiz_results WHERE profile_name = ? ORDER BY grade DESC, timestamp DESC LIMIT ? OFFSET ?"
    df = pd.read_sql_query(query, conn, params=(profile_name, limit, offset))
    conn.close()
    return df

def clear_all_results_from_db():
    """Elimina todos los registros de la tabla de resultados."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM quiz_results")
    cursor.execute("DELETE FROM sqlite_sequence WHERE name='quiz_results'")
    conn.commit()
    conn.close()
    get_results_by_profile_as_df.clear()

# --- Ejecutar la inicialización de la DB al inicio ---
init_db()

# --- CONFIGURACIÓN DE LA PÁGINA Y API ---
st.set_page_config(page_title="Actividades de refuerzo con IA", layout="centered")
try:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    model = genai.GenerativeModel('gemini-2.5-pro')
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

# --- FUNCIÓN MODIFICADA ---
def generar_quiz_con_ia(config, student_name):
    asignatura = config['asignatura']
    temas_lista = config['temas']
    num_preguntas = config['num_preguntas']
    dificultad = config['dificultad']
    temas_str = ", ".join(temas_lista) #or "tópicos generales de la asignatura"

    prompt = f"""
    Actúa como un metódico profesor de matemáticas experto en {asignatura} y un excelente pedagogo. 
    Tu tarea es crear un quiz personalizado de {num_preguntas} preguntas de nivel {dificultad} para el estudiante {student_name}.
    El quiz debe enfocarse en la interpretación de conceptos clave y el razonamiento lógico.
    Los temas a cubrir son: {temas_str}.

    Cada pregunta debe tener 4 opciones (A, B, C, D) y usar LaTeX para las fórmulas (entre signos de dólar $...$).
    La pregunta tiene dos párrafos: El primero explica la importancia de la pregunta y el segundo párrafo la pregunta per se (en bold). 
    Es MUY importante asegurarte que la respuesta correcta se encuentre entre las opciones.
    
    IMPORTANTE PARA LA VALIDEZ DEL JSON: Dentro de las cadenas JSON, todas las barras invertidas `\` de LaTeX DEBEN ser escapadas con una doble barra invertida.
    Por ejemplo, para la fórmula `\frac{{1}}{{2}}`, el texto en el JSON debe ser `\\frac{{1}}{{2}}`. 
    Para `\mathbb{{R}}`, debe ser `\\mathbb{{R}}`.  

    Devuelve el resultado ÚNICAMENTE en formato JSON 100% válido, como una lista de {num_preguntas} objetos.
    Cada objeto debe tener las claves: "pregunta", "opciones", "respuesta_correcta", "explicacion".
    La explicación es neutra; debe servir tanto si responde de forma correcta como de forma incorrecta.
    """
    try:
        ### NUEVO: Definir configuración de seguridad para ser más permisivos ###
        safety_settings = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,            
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        }

        ### MODIFICADO: Añadir safety_settings a la llamada del modelo ###
        response = model.generate_content(prompt, safety_settings=safety_settings)
        
        # Esta comprobación sigue siendo importante por si el bloqueo persiste
        if not response.parts:
            st.error("Comunicación fallida con la IA. Intenta de nuevo. ")
            return None
            
        json_text = response.text.strip().replace("```json", "").replace("```", "").strip()
        json_text = re.sub(r'(?<!\\)\\(?!["\\/bfnrt])', r'\\\\', json_text)
        quiz_data = json.loads(json_text)
        
        if isinstance(quiz_data, list) and len(quiz_data) == num_preguntas and all('pregunta' in q for q in quiz_data):
            return quiz_data
        else:
            st.error("La IA generó una respuesta con un formato inesperado.")
            return None
    except json.JSONDecodeError as e:
        st.error(f"Error al decodificar la respuesta JSON de la IA.")
        #st.code(json_text)
        return None
    except Exception as e:
        st.error(f"Hubo un problema al generar o procesar el quiz.")
        return None

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

def admin_panel():
    tab_anuncios, tab_gestion, tab_opciones = st.tabs(["📢 Anuncios", "📚 Gestionar Quizzes", "⚙️ Opciones Avanzadas"])

    with tab_anuncios:
        st.subheader("Anuncio General para Estudiantes", divider=True)
        current_message = get_global_message()
        new_message = st.text_area(
            "Este mensaje se mostrará a todos los estudiantes en la pestaña 'Clases'.",
            value=current_message,
            height=150,
            key="global_message_input"
        )
        if st.button("Guardar Anuncio", type="primary"):
            save_global_message(new_message)
            st.success("¡Anuncio guardado correctamente!")
            time.sleep(1)
            st.rerun()

    with tab_gestion:
        st.subheader("Panel de Configuración de Quizzes", divider=True)
        st.markdown("Crea, edita o elimina perfiles y sus variantes.")
        
        parent_profiles = get_all_profiles()
        create_new_option = "-- Crear nueva asignatura --"
        options = [create_new_option] + parent_profiles

        selected_parent_profile = st.selectbox("Selecciona un perfil padre:", options, key="admin_parent_select")

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
            config_data = {'asignatura': '', 'temas': [], 'num_preguntas': 5, 'dificultad': 'intermedio'}
        else:
            profile_name_input = selected_parent_profile
            st.subheader(f"Gestionar unidades de: {selected_parent_profile}")
            variants = get_variants_for_profile(selected_parent_profile)
            variant_options = {var[0]: var[1] for var in variants}
            
            create_variant_option_id = -1
            variant_options[create_variant_option_id] = "-- Crear Nueva Variante --"
            
            selected_config_id = st.selectbox(
                "Selecciona una variante para editar o crea una nueva:", 
                options=variant_options.keys(), 
                format_func=lambda id: variant_options[id],
                key="admin_variant_select"
            )
            
            if selected_config_id == create_variant_option_id:
                variant_name_input = st.text_input("Nombre de la Nueva Variante:")
                config_data = {'asignatura': '', 'temas': [], 'num_preguntas': 5, 'dificultad': 'intermedio'}
            else:
                config_data = load_config_from_db(selected_config_id)
                variant_name_input = config_data.get('variant_name', '')

        with st.form("admin_form"):
            asignatura = st.text_input("Nombre completo de la asignatura", value=config_data.get('asignatura', ''))
            temas_input = st.text_area("Temas (separados por comas)", value=", ".join(config_data.get('temas', [])), height=100)
            c1, c2 = st.columns(2)
            num_preguntas = c1.number_input("Nº de preguntas", 3, 10, config_data.get('num_preguntas', 7))
            dificultad_options = ["fácil", "intermedio", "intermedio/avanzado", "avanzado"]
            try:
                current_dificultad_index = dificultad_options.index(config_data.get('dificultad', 'intermedio'))
            except ValueError: current_dificultad_index = 1
            dificultad = c2.selectbox("Dificultad", dificultad_options, index=current_dificultad_index)
            
            st.caption("Recomendación: Para una clase formativa de aprendizaje elije mas preguntas con dificultad baja, mientras que para una clase evaluativa elije menos preguntas con dificultad alta")
            
            submitted = st.form_submit_button("Guardar Configuración de Quiz", type="secondary")
            if submitted:
                if not profile_name_input or not variant_name_input:
                    st.error("El nombre del perfil padre y el de la variante no pueden estar vacíos.")
                else:
                    temas_lista = [t.strip() for t in temas_input.split(',') if t.strip()]
                    save_config_to_db(profile_name_input, variant_name_input, asignatura, temas_lista, num_preguntas, dificultad)
                    st.success(f"¡Configuración '{profile_name_input} - {variant_name_input}' guardada correctamente!")
                    time.sleep(1)
                    st.rerun()

        if selected_parent_profile != create_new_option and selected_config_id != -1 and selected_config_id is not None:
            st.markdown("---")
            if st.button("Eliminar esta Variante", type="secondary"):
                st.session_state.config_to_delete = selected_config_id
            
            if 'config_to_delete' in st.session_state and st.session_state.config_to_delete == selected_config_id:
                 st.warning(f"**¿Estás seguro de que quieres eliminar la variante '{variant_name_input}' del perfil '{profile_name_input}'?**")
                 c1, c2 = st.columns(2)
                 if c1.button("Sí, eliminar", type="primary"):
                     delete_config_from_db(st.session_state.config_to_delete)
                     del st.session_state.config_to_delete
                     st.success("Variante eliminada.")
                     time.sleep(1)
                     st.rerun()
                 if c2.button("Cancelar"):
                     del st.session_state.config_to_delete
                     st.rerun()

    with tab_opciones:
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
st.subheader("Actividades de refuerzo", divider=True)
tab_examen, tab_ranking, tab_admin = st.tabs(["Clases", "Tabla de participación", "Área del profesor"])

with tab_admin:
    if st.session_state.password_correct:
        admin_panel()
    else:
        check_password()

with tab_ranking:
    # Obtener la lista de perfiles que tienen resultados
    conn = sqlite3.connect(DB_FILE)
    profiles_with_results_df = pd.read_sql_query("SELECT DISTINCT profile_name FROM quiz_results ORDER BY profile_name", conn)
    conn.close()
    profiles_with_results = profiles_with_results_df['profile_name'].tolist()

    if not profiles_with_results:
        st.info("Aún no hay resultados para mostrar. ¡Sé el primero en completar un quiz!")
    else:
        # Crear una pestaña para cada perfil (asignatura)
        profile_tabs = st.tabs(profiles_with_results)

        # Iterar sobre cada perfil y su pestaña correspondiente
        for i, profile_name in enumerate(profiles_with_results):
            with profile_tabs[i]:
                # Cargar todos los resultados para este perfil (esto está cacheado)
                full_results_df = get_results_by_profile_as_df(profile_name)

                # --- INICIO DE LA MODIFICACIÓN: FILTRO POR UNIDAD ---
                #st.markdown("##### Filtros")
                variants_with_results = sorted(full_results_df['variant_name'].unique().tolist())
                all_variants_option = "-- Todas las Unidades --"
                
                selected_variant = st.selectbox(
                    "Filtrar por Unidad:",
                    options=[all_variants_option] + variants_with_results,
                    key=f"variant_filter_{profile_name}"
                )

                # Aplicar el filtro al DataFrame
                if selected_variant == all_variants_option:
                    df_to_display = full_results_df
                else:
                    df_to_display = full_results_df[full_results_df['variant_name'] == selected_variant]
                # --- FIN DE LA MODIFICACIÓN ---

                # Las estadísticas y la paginación ahora se basan en el DataFrame filtrado 'df_to_display'
                total_rows = len(df_to_display)

                with st.expander("Estadísticas generales", icon=":material/thumb_up:", expanded=True):
                    avg_grade = df_to_display['grade'].mean() if not df_to_display.empty else 0
                    highest_grade = df_to_display['grade'].max() if not df_to_display.empty else 0
                    col1, col2, col3 = st.columns(3)
                    col1.metric("Total de Participaciones", total_rows)
                    col2.metric("Calificación Promedio", f"{avg_grade:.2f}")
                    col3.metric("Mejor Calificación", f"{highest_grade:.2f}")

                st.subheader("Registros", divider=True)

                if total_rows == 0:
                    st.info("No hay registros que coincidan con el filtro seleccionado.")
                else:
                    page_size = 10
                    total_pages = math.ceil(total_rows / page_size) if total_rows > 0 else 1
                    page_number = st.number_input(
                        "Página",
                        min_value=1,
                        max_value=total_pages,
                        step=1,
                        key=f"page_{profile_name}"
                    )
                    
                    # Paginación aplicada directamente al DataFrame de pandas filtrado
                    offset = (page_number - 1) * page_size
                    paginated_df = df_to_display.iloc[offset : offset + page_size]

                    paginated_df.rename(columns={
                        'student_name': 'Estudiante', 'variant_name': 'Unidad',
                        'grade': 'Calificación (20)', 'score': 'Aciertos',
                        'total_questions': 'Preguntas', 'timestamp': 'Fecha'
                    }, inplace=True)
                    paginated_df['Fecha'] = pd.to_datetime(paginated_df['Fecha']).dt.strftime('%Y-%m-%d %H:%M')
                    paginated_df['Calificación (20)'] = paginated_df['Calificación (20)'].map('{:.2f}'.format)
                    paginated_df['Puntaje'] = paginated_df['Aciertos'].astype(str) + '/' + paginated_df['Preguntas'].astype(str)
                    
                    display_columns = ['Estudiante', 'Unidad', 'Puntaje', 'Calificación (20)', 'Fecha']
                    
                    # Re-indexar para mostrar la posición correcta en la paginación
                    paginated_df.index = range(offset + 1, offset + len(paginated_df) + 1)
                    paginated_df.reset_index(inplace=True)
                    paginated_df.rename(columns={'index': 'Posición'}, inplace=True)
                    
                    st.markdown("\n")

                    # El DataFrame se muestra sin el índice de pandas
                    st.dataframe(
                        paginated_df[['Posición'] + display_columns],
                        use_container_width=True, hide_index=True
                    )
                                    
                    st.caption(f"Mostrando {len(paginated_df)} resultados en la página {page_number} de {total_pages}.")


with tab_examen:
    if st.session_state.pagina == 'inicio':
        # MODIFICADO: Muestra el mensaje global al inicio
        global_message = get_global_message()
        if global_message:
            st.info(f"{global_message}")
        
        col11, col22 = st.columns(2)
        available_quizzes = get_all_profiles()
        if not available_quizzes:
            st.warning("Aún no hay quizzes configurados. Pídele a tu profesor que cree uno en el panel de 'Área del profesor'.")
        else:
            with col11:
                selected_quiz_profile = st.selectbox("Elige la asignatura:", available_quizzes, key="student_profile_select")
            
            selected_config_id = None
            if selected_quiz_profile:
                variants = get_variants_for_profile(selected_quiz_profile)
                if variants:
                    variant_options = {var[0]: var[1] for var in variants}
                    with col22:
                        selected_config_id = st.selectbox(
                            "Elige la unidad de aprendizaje:",
                            options=variant_options.keys(),
                            format_func=lambda id: variant_options[id],
                            key="student_variant_select"
                        )
                else:
                    st.info("Este perfil no tiene variantes disponibles.")

            nombre = st.text_input("Ingresa tu nombre:", key="input_nombre", value=st.session_state.nombre_estudiante)
            
            if st.button("Generar Quiz", type="primary"):
                if nombre and selected_config_id:
                    st.session_state.nombre_estudiante = nombre
                    config = load_config_from_db(selected_config_id)
                    st.session_state.config_actual_quiz = config 
                    
                    with st.spinner(f"Generando tu actividad sobre {config['variant_name']}..."):
                        # MODIFICADO: Pasamos el nombre del estudiante a la función
                        quiz_data = generar_quiz_con_ia(config, st.session_state.nombre_estudiante)
                        if quiz_data:
                            st.session_state.quiz_generado = quiz_data
                            st.session_state.pagina = 'quiz'
                            st.session_state.pregunta_actual = 0
                            st.session_state.respuestas_usuario = {}
                            st.session_state.puntaje = 0
                            st.session_state.respuesta_enviada = False
                            st.rerun()
                else:
                    st.warning("Debes seleccionar un quiz, una versión e ingresar tu nombre para continuar.")

    elif st.session_state.pagina == 'quiz':
        config = st.session_state.config_actual_quiz
        num_preguntas = config['num_preguntas']
        st.subheader(f"Actividad para {st.session_state.nombre_estudiante}")
        st.progress((st.session_state.pregunta_actual + 1) / num_preguntas)
        
        idx = st.session_state.pregunta_actual
        q_info = st.session_state.quiz_generado[idx]
        st.subheader(f"Concepto {idx + 1}/{num_preguntas}")
        st.markdown(f"{q_info['pregunta']}")
        
        with st.form(key=f"form_q_{idx}"):
            opciones = q_info.get('opciones', {})
            if not st.session_state.respuesta_enviada:
                resp_usr = st.radio("Respuesta:", opciones.keys(), format_func=lambda k: f"{k}: {opciones.get(k, '')}", key=f"r_{idx}")
            
            if st.form_submit_button("Enviar Respuesta"):
                st.session_state.respuesta_enviada = True
                st.session_state.respuestas_usuario[idx] = resp_usr
                if resp_usr == q_info.get('respuesta_correcta'): st.session_state.puntaje += 1
                st.rerun()

        if st.session_state.respuesta_enviada:
            correcta = q_info.get('respuesta_correcta')
            elegida = st.session_state.respuestas_usuario.get(idx)
            opciones = q_info.get('opciones', {})
            
            if elegida == correcta: st.success(f"¡Correcto! La respuesta es la **{correcta}**.")
            else: st.error(f"**Incorrecto**. La respuesta correcta era **{correcta}**: {opciones.get(correcta, 'N/A')}")
            
            st.info(f"**Explicación:**\n{q_info.get('explicacion', 'No hay explicación disponible.')}")
            
            if idx < num_preguntas - 1:
                if st.button("Siguiente Pregunta"):
                    st.session_state.pregunta_actual += 1
                    st.session_state.respuesta_enviada = False
                    st.rerun()
            else:
                if st.button("Ver Resultados", type="primary"):
                    st.session_state.pagina = 'resultados'
                    st.rerun()
                    
    elif st.session_state.pagina == 'resultados':
        st.header("Resultados Finales")
        puntaje = st.session_state.puntaje
        config = st.session_state.config_actual_quiz
        num_preguntas = config['num_preguntas']
        calif = (puntaje / num_preguntas) * 20 if num_preguntas > 0 else 0
        
        if 'results_saved' not in st.session_state:
            save_result_to_db(
                student_name=st.session_state.nombre_estudiante,
                profile_name=config['profile_name'],
                variant_name=config['variant_name'],
                score=puntaje,
                total_questions=num_preguntas,
                grade=calif
            )
            st.session_state.results_saved = True
            st.toast("¡Tu resultado ha sido guardado en el ranking!")

        c1, c2 = st.columns(2)
        c1.metric("Respuestas Correctas", f"{puntaje} de {num_preguntas}")
        c2.metric("Calificación (sobre 20)", f"{calif:.2f}")
        if st.button("Volver al inicio"):
            reset_quiz_state()

st.caption("DEMAT-FEC-LUZ")
