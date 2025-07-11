import json
from flask import Blueprint, render_template, jsonify, request
import mysql.connector
from collections import Counter
from datetime import datetime, timedelta

eiaf_bp = Blueprint('eiaf', __name__, template_folder='templates')

# --- CONFIGURACIÓN DE LA BASE DE DATOS EIAF ---
DB_CONFIG_EIAF = {
    'host': 'localhost',
    'user': 'root', 
    'password': '',
    'database': 'eiaf',
}

def get_db_connection():
    try:
        return mysql.connector.connect(**DB_CONFIG_EIAF)
    except mysql.connector.Error as err:
        print(f"Error de conexión EIAF: {err}")
        return None

def build_where_clause():
    # Función auxiliar idéntica a la de los otros dashboards
    where_clauses, params = [], []
    if request.args.get('startDate'):
        where_clauses.append("INICIO >= %s")
        params.append(request.args.get('startDate'))
    if request.args.get('endDate'):
        end_date_dt = datetime.strptime(request.args.get('endDate'), '%Y-%m-%d').date()
        where_clauses.append("INICIO < %s")
        params.append((end_date_dt + timedelta(days=1)).strftime('%Y-%m-%d'))
    if request.args.get('user'):
        where_clauses.append("USUARIO LIKE %s")
        params.append(f"%{request.args.get('user')}%")
    if request.args.get('hm'):
        where_clauses.append("HM = %s")
        params.append(request.args.get('hm'))
    
    sql_where = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
    return sql_where, tuple(params)

# --- RUTA PRINCIPAL DEL DASHBOARD EIAF ---
@eiaf_bp.route('/')
def index():
    return render_template('dashboard_eiaf.html')

# --- RUTAS DE API PARA EL DASHBOARD EIAF (COMPLETAS) ---

@eiaf_bp.route('/api/production_results')
def production_results():
    conn = get_db_connection()
    if not conn: return jsonify({"error": "DB connection failed"}), 500
    
    cursor = conn.cursor()
    sql_where, params = build_where_clause()
    
    query = f"SELECT RESULTADO FROM historial {sql_where}"
    cursor.execute(query, params)
    
    results = cursor.fetchall()
    cursor.close()
    conn.close()
    
    ok_count = sum(1 for row in results if row[0] and row[0].upper() == 'BUENO') 
    nok_count = len(results) - ok_count

    return jsonify({"labels": ["BUENO", "MALO"], "data": [ok_count, nok_count]})

@eiaf_bp.route('/api/retry_causes')
def retry_causes():
    conn = get_db_connection()
    if not conn: return jsonify({"error": "DB connection failed"}), 500

    cursor = conn.cursor(dictionary=True)
    sql_where, params = build_where_clause()
    
    condition = "REINTENTOS IS NOT NULL AND REINTENTOS != '{}'"
    query = f"SELECT REINTENTOS FROM historial {sql_where} {'AND' if sql_where else 'WHERE'} {condition}"

    cursor.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    retry_counter = Counter()
    for row in rows:
        try:
            retry_data = json.loads(row['REINTENTOS'])
            for component, reasons in retry_data.items():
                for reason_code in reasons.keys():
                    retry_counter.update([f"{component}-{reason_code}"])
        except (json.JSONDecodeError, TypeError):
            continue
            
    most_common = retry_counter.most_common(10)
    labels, data = (zip(*most_common)) if most_common else ([], [])
    return jsonify({"labels": list(labels), "data": list(data)})

# --- API: Obtener lista de usuarios ---
@eiaf_bp.route('/api/users')
def get_users():
    conn = get_db_connection()
    if not conn: return jsonify([])
    cursor = conn.cursor()
    query = "SELECT DISTINCT SUBSTRING_INDEX(USUARIO, ': ', -1) as user_name FROM historial WHERE USUARIO LIKE '%:%'"
    cursor.execute(query)
    users = [row[0] for row in cursor.fetchall() if row[0]]
    cursor.close()
    conn.close()
    return jsonify(users)

# --- API: Producción por usuario ---
@eiaf_bp.route('/api/user_production')
def user_production():
    conn = get_db_connection()
    if not conn: return jsonify({"error": "DB connection failed"}), 500
    cursor = conn.cursor(dictionary=True)
    sql_where, params = build_where_clause()
    
    query = f"SELECT SUBSTRING_INDEX(USUARIO, ': ', -1) as clean_user, COUNT(ID) as total FROM historial {sql_where} {'AND' if sql_where else 'WHERE'} USUARIO IS NOT NULL AND USUARIO != '' GROUP BY clean_user ORDER BY total DESC"
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    labels = [row['clean_user'] for row in rows]
    data = [row['total'] for row in rows]
    return jsonify({"labels": labels, "data": data})

# --- API: Tiempo de ciclo promedio por día ---
@eiaf_bp.route('/api/cycle_time')
def cycle_time():
    conn = get_db_connection()
    if not conn: return jsonify({"error": "DB connection failed"}), 500
    cursor = conn.cursor(dictionary=True)
    sql_where, params = build_where_clause()

    query = f"""
        SELECT 
            DATE(INICIO) as production_day, 
            AVG(TIMESTAMPDIFF(SECOND, INICIO, FIN)) as avg_cycle_time
        FROM historial 
        {sql_where} {'AND' if sql_where else 'WHERE'} INICIO IS NOT NULL AND FIN IS NOT NULL
        GROUP BY production_day 
        ORDER BY production_day ASC
    """
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    labels = [row['production_day'].strftime('%Y-%m-%d') for row in rows]
    data = [round(row['avg_cycle_time'], 2) if row['avg_cycle_time'] else 0 for row in rows]
    return jsonify({"labels": labels, "data": data})

# --- API: Análisis de amperaje de fusibles ---
@eiaf_bp.route('/api/fuse_amperage')
def fuse_amperage():
    conn = get_db_connection()
    if not conn: return jsonify({"error": "DB connection failed"}), 500
    cursor = conn.cursor(dictionary=True)
    sql_where, params = build_where_clause()
    query = f"SELECT FUSIBLES FROM historial {sql_where}"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    amperage_counter = Counter()
    for row in rows:
        try:
            fuse_data = json.loads(row['FUSIBLES'])
            for component_data in fuse_data.values():
                for fuse_value in component_data.values():
                    if fuse_value and fuse_value.lower() != 'empty':
                        parts = fuse_value.split(',')
                        if len(parts) > 1:
                            amperage = parts[1] + 'A' # Ej: "5A"
                            amperage_counter.update([amperage])
        except (json.JSONDecodeError, TypeError):
            continue

    most_common = amperage_counter.most_common(10)
    labels, data = (zip(*most_common)) if most_common else ([], [])
    return jsonify({"labels": list(labels), "data": list(data)})

# --- API: Últimos registros ---
@eiaf_bp.route('/api/latest_records')
def latest_records():
    conn = get_db_connection()
    if not conn: return jsonify({"error": "DB connection failed"}), 500
    cursor = conn.cursor(dictionary=True)
    sql_where, params = build_where_clause()
    query = f"SELECT ID, HM, RESULTADO, USUARIO, INICIO, FIN FROM historial {sql_where} ORDER BY FIN DESC LIMIT 15"
    cursor.execute(query, params)
    records = cursor.fetchall()
    cursor.close()
    conn.close()
    
    for record in records:
        record['INICIO'] = record['INICIO'].strftime('%Y-%m-%d %H:%M:%S') if record['INICIO'] else 'N/A'
        record['FIN'] = record['FIN'].strftime('%Y-%m-%d %H:%M:%S') if record['FIN'] else 'N/A'
        
    return jsonify(records)