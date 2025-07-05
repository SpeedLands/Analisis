from flask import Flask, render_template
from blueprints.mbi_2_dashboard import mbi_2_bp
from blueprints.eiaf_dashboard import eiaf_bp
from blueprints.mbi_3_dashboard import mbi_3_bp

app = Flask(__name__)

app.register_blueprint(mbi_2_bp, url_prefix='/mbi2') 
app.register_blueprint(mbi_3_bp, url_prefix='/mbi3')
app.register_blueprint(eiaf_bp, url_prefix='/eiaf')

# Ruta de inicio para seleccionar el dashboard
@app.route('/')
def home():
    """Muestra una página de bienvenida con enlaces a cada dashboard."""
    return render_template('home.html')

if __name__ == '__main__':
    app.run(debug=True, port=5001)