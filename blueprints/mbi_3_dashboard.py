import json
from flask import Blueprint, render_template, jsonify, request
import mysql.connector
from collections import Counter
from datetime import datetime, timedelta

mbi_3_bp = Blueprint('mbi_3', __name__, template_folder='templates')

# --- CONFIGURACIÓN DE LA BASE DE DATOS ---
DB_CONFIG_MBI_3 = {
    'host': 'localhost',
    'user': 'root', 
    'password': '',
    'database': 'eva_mbi_3',
}

def get_db_connection():
    """Crea una conexión a la base de datos."""
    try:
        conn = mysql.connector.connect(**DB_CONFIG_MBI_3)
        return conn
    except mysql.connector.Error as err:
        print(f"Error de conexión: {err}")
        return None

# --- FUNCIÓN AUXILIAR PARA CONSTRUIR QUERIES CON FILTROS ---
def build_where_clause():
    """
    Construye la cláusula WHERE y los parámetros para las consultas SQL 
    basándose en los argumentos de la URL (filtros).
    Esto previene la inyección de SQL.
    """
    where_clauses = []
    params = []
    
    # Filtro por rango de fechas
    start_date = request.args.get('startDate')
    end_date = request.args.get('endDate')
    if start_date:
        where_clauses.append("INICIO >= %s")
        params.append(start_date)
    if end_date:
        # Añadimos un día para que la fecha final sea inclusiva
        end_date_dt = datetime.strptime(end_date, '%Y-%m-%d').date()
        inclusive_end_date = end_date_dt + timedelta(days=1)
        where_clauses.append("INICIO < %s")
        params.append(inclusive_end_date.strftime('%Y-%m-%d'))

    # Filtro por usuario
    user = request.args.get('user')
    if user:
        # Usamos LIKE para que coincida con "PRODUCCION: Oscar Bustos"
        where_clauses.append("USUARIO LIKE %s")
        params.append(f"%{user}%")

    # Filtro por número de serie (HM)
    hm_serial = request.args.get('hm')
    if hm_serial:
        where_clauses.append("HM = %s")
        params.append(hm_serial)

    # Construye la cláusula final
    sql_where = ""
    if where_clauses:
        sql_where = "WHERE " + " AND ".join(where_clauses)
        
    return sql_where, tuple(params)

# --- RUTA PRINCIPAL ---
@mbi_3_bp.route('/')
def index():
    """Renderiza la página principal del dashboard."""
    return render_template('dashboard_mbi_3.html')

# --- RUTAS DE API ---

@mbi_3_bp.route('/api/production_results')
def production_results():
    """API para OK/NOK, ahora con filtros."""
    conn = get_db_connection()
    if not conn: return jsonify({"error": "DB connection failed"}), 500
    
    cursor = conn.cursor()
    sql_where, params = build_where_clause()
    
    query = f"SELECT RESULTADO FROM historial {sql_where}"
    cursor.execute(query, params)
    
    results = cursor.fetchall()
    cursor.close()
    conn.close()
    
    # Asumo que 2=OK, cualquier otro es NOK.
    ok_count = sum(1 for row in results if row[0] == 2) 
    nok_count = len(results) - ok_count

    data = {"labels": ["OK", "NOK/Scrap"], "data": [ok_count, nok_count]}
    return jsonify(data)

@mbi_3_bp.route('/api/scrap_causes')
def scrap_causes():
    """API para causas de scrap, ahora con filtros."""
    conn = get_db_connection()
    if not conn: return jsonify({"error": "DB connection failed"}), 500

    cursor = conn.cursor(dictionary=True)
    sql_where, params = build_where_clause()
    
    base_query = "SELECT SCRAP FROM historial"
    # Añadimos una condición para que solo coja filas con scrap
    scrap_condition = "SCRAP IS NOT NULL AND SCRAP != '{}'"
    if sql_where:
        query = f"{base_query} {sql_where} AND {scrap_condition}"
    else:
        query = f"{base_query} WHERE {scrap_condition}"

    cursor.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    scrap_counter = Counter()
    for row in rows:
        try:
            scrap_data = json.loads(row['SCRAP'])
            for component, reasons in scrap_data.items():
                for reason_code in reasons.keys():
                    scrap_counter.update([f"{component}-{reason_code}"])
        except (json.JSONDecodeError, TypeError):
            continue
            
    most_common = scrap_counter.most_common(10)
    labels, data = (zip(*most_common)) if most_common else ([], [])
    return jsonify({"labels": list(labels), "data": list(data)})

@mbi_3_bp.route('/api/production_timeline')
def production_timeline():
    """API para la línea de tiempo, ahora con filtros."""
    conn = get_db_connection()
    if not conn: return jsonify({"error": "DB connection failed"}), 500

    cursor = conn.cursor(dictionary=True)
    sql_where, params = build_where_clause()
    
    query = f"SELECT DATE(INICIO) as production_day, COUNT(ID) as total FROM historial {sql_where} GROUP BY production_day ORDER BY production_day ASC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    labels = [row['production_day'].strftime('%Y-%m-%d') for row in rows]
    data = [row['total'] for row in rows]
    return jsonify({"labels": labels, "data": data})

# --- NUEVAS RUTAS DE API ---

@mbi_3_bp.route('/api/users')
def get_users():
    """NUEVA API: Obtiene una lista de usuarios únicos para el filtro."""
    conn = get_db_connection()
    if not conn: return jsonify([])
    cursor = conn.cursor()
    # Extraemos solo el nombre después de "PRODUCCION: "
    query = "SELECT DISTINCT SUBSTRING_INDEX(USUARIO, ': ', -1) as user_name FROM historial WHERE USUARIO LIKE '%:%'"
    cursor.execute(query)
    # Extraemos el primer elemento de cada tupla resultante
    users = [row[0] for row in cursor.fetchall() if row[0]]
    cursor.close()
    conn.close()
    return jsonify(users)

@mbi_3_bp.route('/api/user_production')
def user_production():
    """NUEVA API: Gráfico de producción por usuario, con filtros."""
    conn = get_db_connection()
    if not conn: return jsonify({"error": "DB connection failed"}), 500

    cursor = conn.cursor(dictionary=True)
    sql_where, params = build_where_clause()

    query = f"SELECT SUBSTRING_INDEX(USUARIO, ': ', -1) as clean_user, COUNT(ID) as total FROM historial {sql_where} GROUP BY clean_user ORDER BY total DESC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    labels = [row['clean_user'] for row in rows]
    data = [row['total'] for row in rows]
    return jsonify({"labels": labels, "data": data})

@mbi_3_bp.route('/api/histogram_data')
def histogram_data():
    """NUEVA API: Para los histogramas de Torque y Ángulo."""
    conn = get_db_connection()
    if not conn: return jsonify({"error": "DB connection failed"}), 500

    component_path_str = request.args.get('component', 'BATTERY.BT')
    component_path = component_path_str.split('.')
    
    sql_where, params = build_where_clause()
    
    cursor = conn.cursor(dictionary=True)
    query = f"SELECT TORQUE, ANGULO FROM historial {sql_where}"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    torque_values = []
    angle_values = []

    for row in rows:
        # Extraer valor de TORQUE
        try:
            torque_data = json.loads(row['TORQUE'])
            temp_val = torque_data
            for key in component_path:
                temp_val = temp_val[key]
            if isinstance(temp_val, (int, float)):
                torque_values.append(temp_val)
        except (json.JSONDecodeError, TypeError, KeyError, IndexError):
            pass # Ignorar si el dato no existe o es inválido

        # Extraer valor de ANGULO
        try:
            angle_data = json.loads(row['ANGULO'])
            temp_val = angle_data
            for key in component_path:
                temp_val = temp_val[key]
            if isinstance(temp_val, (int, float)):
                angle_values.append(temp_val)
        except (json.JSONDecodeError, TypeError, KeyError, IndexError):
            pass

    # Para un histograma, contamos la frecuencia de cada valor
    torque_counts = Counter(torque_values)
    angle_counts = Counter(angle_values)

    return jsonify({
        "torque": {"labels": list(torque_counts.keys()), "data": list(torque_counts.values())},
        "angle": {"labels": list(angle_counts.keys()), "data": list(angle_counts.values())}
    })

@mbi_3_bp.route('/api/latest_records')
def latest_records():
    """NUEVA API: Obtiene los últimos 15 registros para la tabla."""
    conn = get_db_connection()
    if not conn: return jsonify({"error": "DB connection failed"}), 500
    
    cursor = conn.cursor(dictionary=True)
    sql_where, params = build_where_clause()
    
    query = f"SELECT ID, HM, RESULTADO, USUARIO, INICIO, FIN FROM historial {sql_where} ORDER BY FIN DESC LIMIT 15"
    cursor.execute(query, params)
    records = cursor.fetchall()
    cursor.close()
    conn.close()
    
    # Convertir datetimes a string para que jsonify funcione
    for record in records:
        record['INICIO'] = record['INICIO'].strftime('%Y-%m-%d %H:%M:%S') if record['INICIO'] else None
        record['FIN'] = record['FIN'].strftime('%Y-%m-%d %H:%M:%S') if record['FIN'] else None
        
    return jsonify(records)