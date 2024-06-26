import re
import json
import os
from enum import Enum
from io import BytesIO
import base64

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file, make_response, abort
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Column, DateTime, String, Integer, Text, Numeric, JSON
from sqlalchemy.orm import relationship
import boto3
import jwt
from datetime import datetime, date
from functools import wraps
from xhtml2pdf import pisa

app = Flask(__name__)

db_host = os.getenv("db_endpoint").split(":")[0]
db_name = "insumos_db"
# db_name = "insumos"
db_user = "insumos_user"
# db_user = "kandreyrosales"
db_password = os.getenv("db_password")

app.config['SQLALCHEMY_DATABASE_URI'] = f'postgresql://{db_user}:{db_password}@{db_host}:5432/{db_name}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

app.secret_key = 'xaldigitalcfobayer!'
AWS_REGION = os.getenv("region_aws", 'us-east-1')
bucket_name = os.getenv("bucket_name")
accessKeyId = os.getenv("accessKeyId")
secretAccessKey = os.getenv("secretAccessKey")
CLIENT_ID_COGNITO = os.getenv("client_id")
USER_POOL_ID_COGNITO = os.getenv("user_pool")

LOGIN_URL_REPRESENTATE = 'login/login_representante.html'
SIGNUP_URL_REPRESENTATE = 'login/registro_representante.html'
CONFIRM_ACCOUNT_CODE_URL = 'login/confirm_account_code.html'
RESET_PASSWORD_URL = 'login/reset_password.html'
SEND_RESET_PASSWORD_LINK = 'login/send_reset_password_link.html'

ADMIN_EMAILS = ['lilian.heredia@xaldigital.com', 'carla.galindo@bayer.com']

TYPE_LETTER_RESPONSE = 'letter_response'
TYPE_LETTER = 'letter'

# boto3 clients
cognito_client = boto3.client('cognito-idp',
                              region_name=AWS_REGION,
                              aws_access_key_id=accessKeyId,
                              aws_secret_access_key=secretAccessKey)
lambda_client = boto3.client('lambda',
                             region_name=AWS_REGION,
                             aws_access_key_id=accessKeyId,
                             aws_secret_access_key=secretAccessKey)
s3_client = boto3.client('s3',
                         region_name=AWS_REGION,
                         aws_access_key_id=accessKeyId,
                         aws_secret_access_key=secretAccessKey)


class BayerUser(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True, nullable=False)
    customer_team = db.Column(db.String(250), nullable=False)
    name = db.Column(db.String(250), nullable=False)
    cwid = db.Column(db.String(20), nullable=False)
    address = db.Column(db.String(250), nullable=False)
    ext_number = db.Column(db.String(100), nullable=False)
    int_number = db.Column(db.String(100), nullable=False)
    colonia = db.Column(db.String(250), nullable=False)
    ciudad = db.Column(db.String(250), nullable=False)
    edo = db.Column(db.String(100), nullable=False)
    cp = db.Column(db.String(100), nullable=False)
    cel_bayer = db.Column(db.String(250), nullable=False)


class Vendor(db.Model):
    """
    Proveedor
    """
    __tablename__ = 'vendors'
    id = db.Column(Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    cellphone = db.Column(db.String(80), nullable=False)
    user_email = db.Column(String(80), nullable=False)
    creation_date = Column(DateTime, nullable=False, default=datetime.utcnow)
    insumos = relationship('Insumo', backref='vendor', lazy=True)


class Insumo(db.Model):
    __tablename__ = 'insumos'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    stock = db.Column(db.Integer, nullable=False)
    unit_cost = db.Column(db.Float, nullable=False)
    vendor_id = Column(Integer, db.ForeignKey('vendors.id'), nullable=False)
    order_id = Column(Integer, db.ForeignKey('orders.id'), nullable=True)
    last_updated = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def update(self, new_data):
        # Update other fields in self based on new_data
        self.last_updated = datetime.utcnow()
        db.session.commit()


class OrderStatus(Enum):
    ENTREGADO = "Entregado"
    EN_CAMINO = "En camino"
    CANCELADO = "Cancelado"
    CREADA = "Creado"
    RECHAZADA = "Rechazado"


class Signature(db.Model):
    __tablename__ = 'signatures'
    id = db.Column(Integer, primary_key=True)
    user_email = db.Column(String(80), nullable=False)
    signature_image = db.Column(db.LargeBinary, nullable=False)
    last_updated = Column(DateTime, nullable=False, default=datetime.utcnow)

    def update(self, new_data):
        # Update other fields in self based on new_data
        self.last_updated = datetime.utcnow()
        db.session.commit()


class Order(db.Model):
    __tablename__ = 'orders'
    id = db.Column(Integer, primary_key=True)
    user_email = db.Column(String(80), nullable=False)
    creation_date = Column(DateTime, nullable=False, default=datetime.utcnow)
    estimated_delivery_date = Column(DateTime, nullable=True)
    last_updated = Column(DateTime, nullable=False, default=datetime.utcnow)
    insumos = relationship('Insumo', backref='order', lazy=True)
    data = Column(JSON)
    letter = db.Column(db.LargeBinary, nullable=True)
    letter_response = db.Column(db.LargeBinary, nullable=True)
    letter_response_date = Column(DateTime, nullable=True)
    status = db.Column(db.Enum(OrderStatus), default=OrderStatus.CREADA, nullable=False)
    delivery_information = db.Column(Text(), nullable=True)
    delivery_institute = db.Column(String(250), nullable=True)
    doctor_name = db.Column(String(250), nullable=True)
    doctor_position = db.Column(String(250), nullable=True)
    total = db.Column(Numeric, nullable=False)
    letter_signature = db.Column(db.Text, nullable=True)
    letter_response_signature = db.Column(db.Text, nullable=True)

    def update(self, new_data):
        # Update other fields in self based on new_data
        self.last_updated = datetime.utcnow()
        db.session.commit()


# Create the database tables
def create_tables():
    with app.app_context():
        db.create_all()
        print("All tables created.")


def drop_tables():
    with app.app_context():
        db.drop_all()
        print("All tables dropped.")


@app.route('/initial_data', methods=["GET"])
def initial_data():
    with app.app_context():
        db.drop_all()
        db.create_all()
        vendor = Vendor(name="Daniel Rodriguez", cellphone="31822211308", user_email="daniel@bayer.com")
        vendor_2 = Vendor(name="Juan Perez", cellphone="31822211308", user_email="juan.perez@bayer.com")
        db.session.add(vendor)
        db.session.add(vendor_2)
        insumos_list = [
            Insumo(name="Campos quirúrgicos estériles, reutilizables o desechables", stock=1500, unit_cost=3000,
                   vendor=vendor),
            Insumo(name="Gasas desechables", stock=1500, unit_cost=2000, vendor=vendor),
            Insumo(name="Hisopos estériles", stock=1500, unit_cost=2000, vendor=vendor_2),
            Insumo(name="Micropore, tela adhesiva o transport", stock=1500, unit_cost=2000, vendor=vendor_2),
            Insumo(name="Torundas de algodón", stock=1500, unit_cost=4500, vendor=vendor),
            Insumo(name="Alcohol de 96°", stock=1500, unit_cost=2000, vendor=vendor_2),
            Insumo(name="Yodopovidona", stock=1500, unit_cost=2000, vendor=vendor),
            Insumo(name="Microdacyn", stock=1500, unit_cost=3000, vendor=vendor_2),
            Insumo(name="Clorhexidina", stock=1500, unit_cost=2000, vendor=vendor),
            Insumo(name="Krit, desinfectante de instrumental quirúrgico", stock=1500, unit_cost=2000, vendor=vendor),
            Insumo(name="Jeringas de insuina", stock=1500, unit_cost=2000, vendor=vendor_2),
            Insumo(name="Agujas de insulina, 30G o 32G", stock=1500, unit_cost=2000, vendor=vendor),
            Insumo(name="Blefarostato", stock=1500, unit_cost=2000, vendor=vendor),
            Insumo(name="Tetracaina solución oftálmica", stock=1500, unit_cost=2000, vendor=vendor),
            Insumo(name="Tropicamida- fenilefrina solución oftálmica", stock=1500, unit_cost=5000, vendor=vendor_2),
            Insumo(name="Solución y/o ungüento antibótico/antiinflamatorio", stock=1500, unit_cost=2000, vendor=vendor),
            Insumo(name="Bloques de gel congelante", stock=1500, unit_cost=2000, vendor=vendor)
        ]
        for insumo in insumos_list:
            db.session.add(insumo)

        bayer_cwid_initial_data = [
            "WETLIA,GUTIERREZ MEDINA LUIS ERNESTO,MEBGV,FRANCITA,No 199,,PETROLERA,AZCAPOTZALCO,DIF,02480,55 27550384,ernesto.gutierrez@bayer.com",
            "WETLIA,HERNANDEZ GARCIA BRENDA,MEBKF,CALLE 27,No 43,,OLIVAR DEL CONDE 2A SECC,ALVARO OBREGON,DIF,01408,55 26992682,brenda.hernandez@bayer.com",
            "WETLIA,GONZALEZ VIVIAN ILESVE CARMEN,MEBKP,MIGUEL DE MENDOZA,No 4,104,MIXCOAC,BENITO JUAREZ,DIF,03910,55 30765297,carmen.gonzalez3@bayer.com",
            "WETLIA,VELAZQUEZ BARRON MARIA DEL CARMEN,MEBYE,HONDA DE SAN MIGUEL,No 452,,SAN MIGUEL,LEON,GTO,37390,477 6702290,madelcarmen.velazquez@bayer.com",
            "WETLIA,MARCIAL CARDENAS MIGUEL ANGEL,GNFMO,UNIVERSIDAD DE TORINO ,No 4245,0,LOMAS UNIVERSIDAD ETAPA V,CHIHUAHUA,CHI,31123,614 1420421,miguel.marcial@bayer.com",
            "WETLIA,HERNANDEZ FERNANDEZ JOSE ALFREDO,GFBSI,COAHUILA,No 162,,VILLA RICA AMPLIACIÓN,BOCA DEL RIO,VER,94298,229 2138725,josealfredo.hernandez@bayer.com",
            "WETLIA,ORTIZ CURIEL DIANA LIZETH,GDUQN,PINOS,No 232,,VILLAS DE ANAHUAC SEC ALPES II,ESCOBEDO,NLE,66059,81 80118978,diana.ortiz@bayer.com",
            "WETLIA,AHUMADA GARCIA ISRAEL,GMQPR,BOSQUE DE TAMARINDOS,1116,,VILLAS DEL CAMPO,CALIMAYA,ESTADO DE MEXICO,52220,55 5619939574,israel.ahumada@bayer.com",
            "WETLIA,DE LA ROSA MATA RUTH NOHEMI,EQHPU,FAISAN VENERADO,No 1013,,LOS FAISANES SECTOR EL DORADO,GUADALUPE,NLE,67169,81 82528262,ruthnohemi.delarosamata@bayer.com",
            "WETLIA,SOLTERO ROMERO MIRIAM,GFNXH,C. ALI CHUMACERO,No 1000,118,SAN LORENZO COACALCO,METEPEC,MEX,52140,55 54568550,miriam.soltero@bayer.com",
            "WETLIA,SALAZAR GOMEZ MARTHA LUCERO,GHMAP,LERDO,No 92,ED- D D-304,SAN PABLO,IZTAPALAPA,DIF,09000,55 43750564,martha.salazar@bayer.com",
            "WETLIA,MONDRAGON ROSALES LILIANA,MEBLR,TINACO,No 20,,BARRANCA SECA,LA MAGDALENA CONTRERAS,DIF,10580,55 54157176,liliana.mondragon@bayer.com",
            "WETLIA,DE LEON BUSTAMANTE VIOLETA ESMERALDA,GHUUA,EL OCOTE,No 254,,TERRANOVA TUXTLA,TUXTLA GUTIERREZ,CHS,29089,96 16030508,violeta.deleon@bayer.com",
            "WETLIA,AZPEITIA PEREZ GEORGINA BELEN,MECXX,CIRCUITO DEL BOSQUE,No 242,,BOSQUES VALLARTA,ZAPOPAN,JAL,45222,33 18657198,georgina.azpeitia@bayer.com",
            "WETLIA,GUTIERREZ ESPARZA NORA DENISSE,GOMJD,C-35,No 401,0,FRANCISCO DE MONTEJO,MERIDA,YUC,97203,0,denisse.gutierrez@bayer.com",
            "WETLIA,BARRERAS ESPINOZA EDNA GUADALUPE,GIAZX,CDA DE LOS ROMANCES,No 20,,PRIVADAS DEL CID,HERMOSILLO,SON,83107,662 4702948,edna.barreras@bayer.com",
            "WETLIA,ORONA RUIZ JOSE,GGKFI,PRIVADA COLINA DEL RIO,No 7653,91,RESIDENCIAL AGUA CALIENTE,TIJUANA,BCN,22194,664 2010578,jose.orona@bayer.com",
            "WETLIA,HERRERA LIMON MARIO,MEBPT,CALLE 12 PONIENTE,No 912,,LA LIBERTAD,PUEBLA,PUE,72130,222 3509687,mario.herrera@bayer.com",
            "WETLIA,XALDIGITAL REPRESENTANTE TEST,MEBPZ,CALLE 12 PONIENTE,No 912,,LA LIBERTAD,PUEBLA,PUE,72130,222 3509687,kandreyrosales@gmail.com",
            "WETLIA,BAYER REPRESENTANTE TEST,REPR1,CALLE 12 PONIENTE,No 912,,LA LIBERTAD,PUEBLA,PUE,72130,222 3509687,juangabriel.gonzalez@bayer.com",
            "WETLIA,XALDIGITAL ADMIN TEST,ABCDE,CALLE 12 PONIENTE,No 912,,LA LIBERTAD,PUEBLA,PUE,72130,222 3509687,lilian.heredia@xaldigital.com",
            "WETLIA,CARLA GALINDO,ADMIN1,CALLE 12 PONIENTE,No 912,,LA LIBERTAD,PUEBLA,PUE,72130,222 3509687,carla.galindo@bayer.com",

        ]
        for entry in bayer_cwid_initial_data:
            fields = entry.split(',')
            bayer_user = BayerUser(
                customer_team=fields[0],
                name=fields[1],
                cwid=fields[2],
                address=fields[3],
                ext_number=fields[4],
                int_number=fields[5],
                colonia=fields[6],
                ciudad=fields[7],
                edo=fields[8],
                cp=fields[9],
                cel_bayer=fields[10],
                email=fields[11]
            )
            db.session.add(bayer_user)
        # with open('static/assets/img/bayer_admin_signature.png', 'rb') as f:
        #     image_data = f.read()
        #     admin_signature = Signature(user_email=ADMIN_EMAIL, signature_image=image_data)
        #     db.session.add(admin_signature)
        db.session.commit()
    return {"message": "Data inicial cargada!"}


@app.route('/autocomplete')
def autocomplete():
    """
    Function to get all the data of representante based on CWID field
    :return:
    """
    cwid = request.args.get('cwid_custom_id', '')
    bayer_user = BayerUser.query.filter_by(cwid=cwid).first()
    if bayer_user:
        return render_template(
            "login/form_data_cwid_registro_representante.html",
            cwid_custom_id=bayer_user.cwid,
            username=bayer_user.email,
            fullname=bayer_user.name,
            customer_team_input=bayer_user.customer_team,
            delivery_address=bayer_user.address,
            city=bayer_user.ciudad,
            colonia=bayer_user.colonia,
            ext_number=bayer_user.ext_number,
            int_number=bayer_user.int_number,
            edo=bayer_user.edo,
            cp=bayer_user.cp,
            telephone_bayer=bayer_user.cel_bayer
        )
    else:
        return render_template(
            "login/form_data_cwid_registro_representante.html",
            cwid_custom_id=cwid,
            username="",
            fullname="",
            customer_team_input="",
            delivery_address="",
            city="",
            colonia="",
            ext_number="",
            int_number="",
            edo="",
            cp="",
            telephone_bayer=""
        )


def authenticate_user(username, password):
    try:
        response = cognito_client.admin_initiate_auth(
            AuthFlow='ADMIN_NO_SRP_AUTH',
            AuthParameters={
                'USERNAME': username,
                'PASSWORD': password
            },
            ClientId=CLIENT_ID_COGNITO,
            UserPoolId=USER_POOL_ID_COGNITO,
            ClientMetadata={
                'username': username,
                'password': password,
            }
        )
        return response
    except cognito_client.exceptions.NotAuthorizedException as e:
        # Handle invalid credentials
        return {"reason": "Credenciales Inválidas"}
    except cognito_client.exceptions.ResourceNotFoundException as e:
        # Handle invalid credentials
        return {"reason": "Recurso No Encontrado"}
    except cognito_client.exceptions.UserNotFoundException as e:
        # Handle invalid credentials
        return {"reason": "Usuario No Encontrado"}
    except cognito_client.exceptions.UserNotConfirmedException as e:
        # Handle invalid credentials
        return {"reason": "Usuario No Confirmado"}
    except Exception as e:
        # Handle other errors
        return {"reason": "Error general. Por favor contactar al administrador"}


def requires_admin_email():
    def decorator(func):
        @wraps(func)
        def decorated_function(*args, **kwargs):
            if session.get('user_email') not in ADMIN_EMAILS:
                return redirect(url_for('representante'))
            return func(*args, **kwargs)
        return decorated_function
    return decorator


def requires_representante_email():
    def decorator(func):
        @wraps(func)
        def decorated_function(*args, **kwargs):
            if session.get('user_email') in ADMIN_EMAILS:
                return redirect(url_for('index_admin'))
            if (not BayerUser.query.filter_by(email=session.get('user_email')).first() or
                    session.get('user_email') in ADMIN_EMAILS):
                return abort(404)
            return func(*args, **kwargs)

        return decorated_function

    return decorator


@app.route('/login', methods=['GET', 'POST'])
def login_representante():
    """
        Accessing with Cognito using username and password.
        After login is redirected to reset password and login again
    """

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if not username or not password:
            return render_template(LOGIN_URL_REPRESENTATE, error="Nombre de usuario y Contraseña obligatorios")

        cognito_response = authenticate_user(username, password)

        reason = cognito_response.get("reason")
        if reason == "Usuario No Confirmado":
            return render_template(CONFIRM_ACCOUNT_CODE_URL, email=username)
        elif reason is not None:
            return render_template(LOGIN_URL_REPRESENTATE, error=reason)

        auth_result = cognito_response.get("AuthenticationResult")
        if not auth_result:
            return render_template(LOGIN_URL_REPRESENTATE, error=cognito_response)

        session['access_token'] = auth_result.get('AccessToken')
        session['id_token'] = auth_result.get('IdToken')
        session['user_email'] = username
        with app.app_context():
            if username in ADMIN_EMAILS:
                return redirect(url_for('index_admin'))
            elif BayerUser.query.filter_by(email=username).first():
                return redirect(url_for('representante'))
            else:
                return redirect(url_for('logout'))


    else:
        return render_template(
            LOGIN_URL_REPRESENTATE,
            accessKeyId=accessKeyId,
            secretAccessKey=secretAccessKey
        )


@app.route('/registro', methods=['GET', 'POST'])
def registro_representante():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        try:
            response = cognito_client.sign_up(
                ClientId=CLIENT_ID_COGNITO,
                Username=username,
                Password=password
            )
            return render_template(CONFIRM_ACCOUNT_CODE_URL, email=username)
        except cognito_client.exceptions.NotAuthorizedException as e:
            # Handle authentication failure
            return render_template(SIGNUP_URL_REPRESENTATE, error="Usuario no Autorizado para ejecutar esta acción")
        except cognito_client.exceptions.UsernameExistsException:
            return render_template(
                SIGNUP_URL_REPRESENTATE,
                error="Ya existe una cuenta asociada a este correo")
        except cognito_client.exceptions.InvalidPasswordException:
            return render_template(
                SIGNUP_URL_REPRESENTATE,
                error="Crea una contraseña de al menos 8 dígitos, más segura, usando al menos una letra mayúscula, "
                      "un número y un carácter especial")
        except Exception as e:
            return render_template(
                LOGIN_URL_REPRESENTATE,
                error=f"Ha ocurrido el siguiente error: {e}")
    else:
        return render_template(SIGNUP_URL_REPRESENTATE)


def refresh_access_token():
    refresh_token = session.get("refresh_token")
    if not refresh_token:
        return None

    try:
        response = cognito_client.initiate_auth(
            ClientId=CLIENT_ID_COGNITO,
            AuthFlow='REFRESH_TOKEN_AUTH',
            AuthParameters={
                'REFRESH_TOKEN': refresh_token
            }
        )
        new_access_token = response['AuthenticationResult']['AccessToken']
        session['access_token'] = new_access_token
        return new_access_token
    except cognito_client.exceptions.NotAuthorizedException:
        return None
    except Exception as e:
        print(f"Error refreshing token: {e}")
        return None


@app.route('/confirmar_cuenta', methods=['GET', 'POST'])
def confirm_account_code():
    email = request.form['email_not_confirmed']
    email_code = request.form['custom_code']
    if request.method == "POST":
        try:
            cognito_client.confirm_sign_up(
                ClientId=CLIENT_ID_COGNITO,
                Username=email,
                ConfirmationCode=email_code
            )
            return render_template(LOGIN_URL_REPRESENTATE)
        except cognito_client.exceptions.ExpiredCodeException as e:
            return render_template(CONFIRM_ACCOUNT_CODE_URL,
                                   error="El código enviado a su correo ha expirado",
                                   email=email)
        except cognito_client.exceptions.CodeMismatchException as e:
            return render_template(
                CONFIRM_ACCOUNT_CODE_URL,
                error="El código no es válido", email=email)
        except cognito_client.exceptions.TooManyFailedAttemptsException as e:
            return render_template(
                CONFIRM_ACCOUNT_CODE_URL,
                error="Máximo de intentos superados para validar la cuenta", email=email)
        except cognito_client.exceptions.UserNotFoundException as e:
            return render_template(
                CONFIRM_ACCOUNT_CODE_URL,
                error="Error: Usuario no Encontrado o Eliminado", email=email)
    else:
        return render_template(CONFIRM_ACCOUNT_CODE_URL, email=email)


@app.route('/logout')
def logout():
    # Clear the session data
    session.clear()
    db.session.remove()
    return redirect(url_for('login_representante'))


def token_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = session.get("access_token")
        if not token:
            return render_template(LOGIN_URL_REPRESENTATE)
        try:
            decoded_token = jwt.decode(token, options={"verify_signature": False})
            expiration_time = datetime.utcfromtimestamp(decoded_token['exp'])
            current_time = datetime.utcnow()
            if expiration_time > current_time:
                return f(*args, **kwargs)
            else:
                new_token = refresh_access_token()
                if new_token:
                    return f(*args, **kwargs)
                else:
                    db.session.remove()
                    return render_template(LOGIN_URL_REPRESENTATE, error="Sesión Expirada. Ingrese sus datos de nuevo")
        except jwt.ExpiredSignatureError:
            new_token = refresh_access_token()
            if new_token:
                return f(*args, **kwargs)
            else:
                db.session.remove()
                return render_template(LOGIN_URL_REPRESENTATE, error="Sesión Expirada. Ingrese sus datos de nuevo")
        except jwt.InvalidTokenError:
            return render_template(LOGIN_URL_REPRESENTATE, error="Token inválido. Ingrese sus datos de nuevo")

    return decorated_function


@app.route('/olvido_contrasena', methods=['GET', 'POST'])
def forgot_password():
    if request.method == "POST":
        email = request.form['email_forgot_password']
        password = request.form['password']
        custom_code = request.form['custom_code']
        try:
            cognito_client.confirm_forgot_password(
                ClientId=CLIENT_ID_COGNITO,
                Username=email,
                ConfirmationCode=custom_code,
                Password=password,
            )
            return render_template(LOGIN_URL_REPRESENTATE)
        except cognito_client.exceptions.UserNotFoundException as e:
            return render_template(RESET_PASSWORD_URL,
                                   error="Usuario No Encontrado o Eliminado.", email=email)
        except cognito_client.exceptions.InvalidPasswordException as e:
            return render_template(RESET_PASSWORD_URL,
                                   error="Usuario No Encontrado o Eliminado.", email=email)
        except cognito_client.exceptions.CodeMismatchException as e:
            return render_template(RESET_PASSWORD_URL,
                                   error="Ha ocurrido un problema al enviar el código para asignar una nueva contraseña. "
                                         "Intenta de nuevo.",
                                   email=email)
        except Exception as e:
            return render_template(RESET_PASSWORD_URL,
                                   error=f"Error: {e}", email=email)
    else:
        return render_template(RESET_PASSWORD_URL)


@app.route('/enviar_link_contrasena', methods=['GET', 'POST'])
def send_reset_password_link():
    if request.method == "POST":
        email = request.form['email_forgot_password']
        try:
            cognito_client.forgot_password(
                ClientId=CLIENT_ID_COGNITO,
                Username=email
            )
            return render_template(RESET_PASSWORD_URL)

        except cognito_client.exceptions.UserNotFoundException as e:
            return render_template(SEND_RESET_PASSWORD_LINK,
                                   error="Usuario No Encontrado o Eliminado.", email=email)
        except cognito_client.exceptions.CodeDeliveryFailureException as e:
            return render_template(
                SEND_RESET_PASSWORD_LINK,
                error="Ha ocurrido un problema al enviar el código para asignar una nueva contraseña. "
                      "Intenta de nuevo.",
                email=email)
        except Exception as e:
            return render_template(SEND_RESET_PASSWORD_LINK,
                                   error=f"Error: {e}", email=email)
    else:
        return render_template(SEND_RESET_PASSWORD_LINK)


@app.route('/admin', methods=["GET"])
@token_required
@requires_admin_email()
def index_admin():
    return render_template('admin/index_admin.html', admin_user=True)


@app.route('/add_insumos_form', methods=["GET"])
@token_required
def add_insumos_form():
    vendors = Vendor.query.all()
    return render_template("representante/add_insumos_form.html",
                           vendors=vendors)



@app.route('/representante', methods=["GET"])
@token_required
@requires_representante_email()
def representante():
    return render_template('representante/representante_index.html', admin_user=False)


@app.route('/image/<int:signature_id>')
@token_required
def get_image(signature_id):
    signature = Signature.query.get_or_404(signature_id)
    return send_file(
        BytesIO(signature.signature_image),
        mimetype='image/jpeg',
        as_attachment=False
    )


@app.route('/getvendorlist', methods=["GET"])
@token_required
def getvendorlist():
    with app.app_context():
        vendors = Vendor.query.all()
    options = [
        {'id': vendor.id, 'text': vendor.name} for vendor in vendors
    ]
    return jsonify(options)


@app.route('/api/vendors', methods=["GET"])
@token_required
def insumos_list():
    with app.app_context():
        page = request.args.get('page', 1, type=int)
        per_page = 10  # Number of records per page
        pagination = Insumo.query.order_by(Insumo.last_updated.desc()).paginate(
            page=page, per_page=per_page, max_per_page=10, count=True, error_out=False)
        insumos = pagination.items
        return render_template('admin/insumos_table.html',
                               insumos=insumos,
                               pagination=pagination)


def search_query_insumos(query, page, per_page):
    if query:
        insumos = (
            Insumo.query.filter(Insumo.name.ilike(f'%{query}%'))
            .order_by(Insumo.last_updated.desc())
            .paginate(page=page, per_page=per_page, max_per_page=10, count=True, error_out=False)
        )
    else:
        insumos = Insumo.query.order_by(Insumo.last_updated.desc()).paginate(
            page=page, per_page=per_page, max_per_page=10, count=True, error_out=False)
    return insumos


def search_query_orders_admin(query, page, per_page, field):
    """
    Function for Filtering all the status except orders with status CREADA
    """
    if query:
        if field == 'status':
            if query == 'todos':
                # Construcción de la consulta con el filtro para excluir el estado 'CREADA'
                query_not_created = Order.query.filter(Order.status != OrderStatus.CREADA).order_by(Order.id.desc())
                return query_not_created.paginate(
                    page=page, per_page=per_page, max_per_page=10, count=True, error_out=False)
            else:
                orders = (
                    Order.query.filter(Order.status == query).filter(Order.status != OrderStatus.CREADA)
                    .order_by(Order.id.desc())
                    .paginate(page=page, per_page=per_page, max_per_page=10, count=True, error_out=False)
                )
        elif field == 'representante':
            email_tuples = BayerUser.query.with_entities(BayerUser.email).filter(
                BayerUser.name.ilike(f'%{query}%')).all()
            emails = [email[0] for email in email_tuples]
            orders = (
                Order.query.filter(Order.user_email.in_(emails)).filter(Order.status != OrderStatus.CREADA)
                .order_by(Order.id.desc())
                .paginate(page=page, per_page=per_page, max_per_page=10, count=True, error_out=False)
            )
        else:
            return Order.query.filter(Order.status != OrderStatus.CREADA).order_by(Order.id.desc()).paginate(
                page=page, per_page=per_page, max_per_page=10, count=True, error_out=False)
    else:
        return Order.query.filter(Order.status != OrderStatus.CREADA).order_by(Order.id.desc()).paginate(
            page=page, per_page=per_page, max_per_page=10, count=True, error_out=False)
    return orders


@app.route('/search_insumos', methods=['GET'])
@token_required
@requires_admin_email()
def search_insumos():
    query = request.args.get('query', '')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    insumos = search_query_insumos(query=query, per_page=per_page, page=page)
    return render_template('admin/insumos_table.html', insumos=insumos.items, pagination=insumos)


@app.route('/search_orders_admin', methods=['GET'])
@token_required
@requires_admin_email()
def search_orders_admin():
    """
    Filtering all the status except orders with status CREADA
    """
    query_representante_name = request.args.get('query_representante_name', '')
    query_status = request.args.get('query_status', '')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    if query_representante_name:
        pagination = search_query_orders_admin(query=query_representante_name,
                                               per_page=per_page, page=page,
                                               field='representante')
    elif query_status:
        pagination = search_query_orders_admin(query=query_status,
                                               per_page=per_page, page=page,
                                               field='status')
    else:
        pagination = Order.query.filter(
            Order.status != OrderStatus.CREADA).paginate(
            page=page,
            per_page=per_page, max_per_page=10,
            count=True,
            error_out=False)
    new_dict_orders_list = []
    for order in pagination.items:
        bayer_user = BayerUser.query.filter_by(email=order.user_email).first()
        new_dict_orders_list.append({
            "id": order.id,
            "representante": bayer_user.name,
            "institucion_entrega": order.delivery_institute,
            "customer_team": bayer_user.customer_team,
            "total": order.total,
            "fecha_pedido": order.creation_date,
            "fecha_entrega": datetime.strftime(
                order.estimated_delivery_date,
                "%d-%m-%Y") if order.estimated_delivery_date else "",
            "estado": order.status.value,
            "direccion_entrega": order.delivery_information
        })
    return render_template(
        'admin/orders_table.html',
        orders=new_dict_orders_list,
        pagination=pagination
    )


@app.route('/search_insumos_representante', methods=['GET'])
@token_required
def search_insumos_representante():
    query = request.args.get('query', '')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    insumos = search_query_insumos(query=query, per_page=per_page, page=page)
    return render_template(
        'representante/insumos_table_representante.html',
        insumos=insumos.items,
        pagination=insumos)


@app.route('/api/insumos_representante', methods=["GET"])
@token_required
@requires_representante_email()
def insumos_representante_list():
    with app.app_context():
        page = request.args.get('page', 1, type=int)
        per_page = 10  # Number of records per page
        pagination = Insumo.query.order_by(Insumo.last_updated.desc()).paginate(
            page=page, per_page=per_page, max_per_page=10, count=True, error_out=False)
        insumos = pagination.items
        return render_template('representante/insumos_table_representante.html',
                               insumos=insumos,
                               pagination=pagination)


@app.route('/pedidos', methods=["GET"])
@token_required
@requires_admin_email()
def pedidos():
    return render_template(
        'admin/orders_admin.html',
        admin_user=True,
        statuses=[status for status in OrderStatus if status != OrderStatus.CREADA]
    )


@app.route('/pedidos_representante', methods=["GET"])
@token_required
@requires_representante_email()
def pedidos_representante():
    return render_template('representante/orders_representante.html',
                           user_admin=False)


@app.route('/api/orders_representante', methods=["GET"])
@token_required
@requires_representante_email()
def orders_representante_list():
    email = session.get("user_email")
    with app.app_context():
        page = request.args.get('page', 1, type=int)
        per_page = 10  # Number of records per page
        pagination = Order.query.filter_by(user_email=email).order_by(Order.id.desc()).paginate(
            page=page,
            per_page=per_page,
            max_per_page=10,
            count=True,
            error_out=False)
        orders = pagination.items
        new_dict_orders_list_representante = []
        bayer_user = BayerUser.query.filter_by(email=email).first()
        for order in orders:
            new_dict_orders_list_representante.append({
                "id": order.id,
                "representante": bayer_user.name,
                "institucion_entrega": order.delivery_institute,
                "customer_team": bayer_user.customer_team,
                "total": order.total,
                "fecha_pedido": order.creation_date,
                "fecha_entrega": datetime.strftime(order.estimated_delivery_date, "%d-%m-%Y")
                if order.estimated_delivery_date else "",
                "estado": order.status.value,
                "direccion_entrega": order.delivery_information
            })
        return render_template('representante/orders_table_representante.html',
                               orders=new_dict_orders_list_representante,
                               pagination=pagination)


@app.route('/api/generate_insumos_list_html', methods=["GET"])
@token_required
def generate_insumos_list_html():
    lista_insumos_id_raw = request.args.get('insumos_id_list')
    insumos_ids = [int(insumo_id) for insumo_id in json.loads(lista_insumos_id_raw)]
    filtered_insumos = Insumo.query.filter(Insumo.id.in_(insumos_ids)).all()
    user_email = session.get("user_email")
    user_signature = Signature.query.filter_by(user_email=user_email).first()
    return render_template(
        'representante/modal_fields_get_insumos_list.html',
        insumos=filtered_insumos,
        user_signature=user_signature
    )


@app.route('/api/get_orders_to_delete_html', methods=["GET", "POST"])
@token_required
@requires_admin_email()
def get_orders_to_delete_html():
    if request.method == 'GET':
        list_orders_id_raw = request.args.get('orders_id_list')
        orders_ids = [int(order_id) for order_id in json.loads(list_orders_id_raw)]
        filtered_orders = Order.query.filter(Order.id.in_(orders_ids)).all()
        return render_template(
            'admin/orders_to_delete.html',
            orders_to_delete=filtered_orders
        )
    else:
        list_orders_id_raw = request.form.get('orders_id_list')
        orders_ids = [int(order_id) for order_id in json.loads(list_orders_id_raw)]
        filtered_orders = Order.query.filter(Order.id.in_(orders_ids)).all()
        for order in filtered_orders:
            order.status = OrderStatus.CANCELADO
        db.session.commit()
        return render_template(
            'custom_alert_message.html',
            message='Pedidos cancelados!'
        )


@app.route('/api/cancel_order', methods=["POST"])
@token_required
@requires_representante_email()
def cancel_order():
    order_id = request.args.get('order_id')
    order = Order.query.get_or_404(order_id)
    order.status = OrderStatus.CANCELADO
    db.session.commit()
    return jsonify({"Pedido cancelado!"})


def filter_vendor(vendor_id: int):
    filtered_vendor = Vendor.query.filter_by(id=vendor_id).all()
    if len(filtered_vendor) == 1:
        return filtered_vendor[0]
    else:
        raise ValueError("El proveedor no existe")


@app.route('/add_insumos_records', methods=["POST"])
@token_required
def add_insumos_records():
    """
    Adding an Insumo record to the datatabase
    """
    name = request.form.get('name')
    stock = request.form.get('stock')
    unit_cost = request.form.get('unit_cost')
    vendor_id = int(request.form.get('vendorselect'))
    try:
        with app.app_context():
            vendor = filter_vendor(vendor_id=vendor_id)
            insumo = Insumo(name=name, stock=stock, unit_cost=unit_cost, vendor=vendor)
            db.session.add(insumo)
            db.session.commit()
        message = "Insumo agregado correctamente!"
        error = False
    except Exception as e:
        message = str(e)
        error = True
    return render_template("custom_alert_message.html",
                           error=error,
                           message=message)


@app.route('/add_order_record', methods=["POST"])
@token_required
def add_order_record():
    """
    Adding an Order record to the datatabase
    """
    # Counter of quantity_insumo
    user_email = session.get("user_email")
    medico_solicitante = request.form.get('medico_solicitante')
    posicion_medico = request.form.get('posicion_medico')
    nombre_institucion = request.form.get('nombre_institucion')
    direccion_entrega = request.form.get('direccion_entrega')

    # Filtrar los valores que contienen 'quantity_insumo'
    values = [key for key in request.form.keys()]
    quantity_values = [value for value in values if 'quantity_insumo' in value]

    # Extraer los números de los valores filtrados
    quantity_numbers = [re.search(r'\d+', value).group() for value in quantity_values]

    insumos_for_order = []
    try:
        with app.app_context():
            total_cost = 0
            for insumoid in quantity_numbers:
                insumoid = int(insumoid)
                insumo = Insumo.query.filter_by(id=insumoid).first()
                quantity_insumo_ordered = int(request.form.get(f"quantity_insumo_{insumoid}"))
                name_insumo_ordered = request.form.get(f"name_{insumoid}")
                # updating insumo stock
                insumo.stock = insumo.stock - quantity_insumo_ordered
                total_cost += (insumo.unit_cost * quantity_insumo_ordered)
                insumos_for_order.append(
                    {
                        "id": insumo.id,
                        "name": name_insumo_ordered,
                        "quantity": quantity_insumo_ordered,
                        "cost": insumo.unit_cost
                    }
                )

            order = Order(
                user_email=user_email,
                status=OrderStatus.CREADA,
                delivery_institute=nombre_institucion,
                doctor_name=medico_solicitante,
                doctor_position=posicion_medico,
                total=total_cost,
                data=insumos_for_order,
                delivery_information=direccion_entrega
            )
            db.session.add(order)
            db.session.commit()
            return render_template(
                'representante/button_go_to_order_detail.html',
                order_id=order.id
            )
    except Exception as e:
        message = str(e)
        error = True
        return render_template(
            "custom_alert_message.html",
            message=message,
            error=error)


def generate_pdf(html):
    pdf = BytesIO()
    pisa_status = pisa.CreatePDF(BytesIO(html.encode('utf-8')), dest=pdf)
    if pisa_status.err:
        return None
    pdf.seek(0)
    return pdf


@app.route('/order_pdf_letter/<int:order_id>/<type_letter>')
@token_required
def order_pdf_letter(order_id, type_letter):
    order = Order.query.get_or_404(order_id)
    if type_letter == TYPE_LETTER_RESPONSE:
        doctor_signature = order.letter_response_signature if order.letter_response_signature else None
        representante = BayerUser.query.filter_by(email=session.get("user_email")).first()
        letter_html_rendered = render_template(
            'representante/letter_representante_response_generate_order.html',
            order_id=order_id,
            actual_date=date.today(),
            medico_solicitante=order.doctor_name,
            posicion_medico=order.doctor_position,
            nombre_institucion=order.delivery_institute,
            doctor_signature=doctor_signature,
            nombre_representante=representante.name,
            logo_bayer=get_bayer_logo()
        )
        file_pdf_name = f'inline; filename=carta_respuesta_pedido_{order_id}.pdf'
    else:
        doctor_signature = order.letter_signature if order.letter_signature else None
        letter_html_rendered = render_template(
            'representante/letter_representante_generate_order.html',
            actual_date=date.today(),
            insumos_order=order.data,
            medico_solicitante=order.doctor_name,
            posicion_medico=order.doctor_position,
            nombre_institucion=order.delivery_institute,
            logo_bayer=get_bayer_logo(),
            doctor_signature=doctor_signature,
        )
        file_pdf_name = f'inline; filename=carta_solicitud_pedido_{order_id}.pdf'
    # Convertir el HTML a PDF
    pdf = generate_pdf(letter_html_rendered)
    if pdf is None:
        return "Error al generar el PDF", 500
    response = make_response(pdf.read())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = file_pdf_name
    return response


@app.route('/order_detail/<int:order_id>')
@token_required
def order_detail(order_id):
    return render_template(
        'representante/order_detail.html',
        order_id=order_id,
    )


@app.route('/edit_insumo/<int:insumo_id>', methods=["GET", "POST"])
@token_required
@requires_admin_email()
def edit_insumo(insumo_id):
    """
    Editing an Insumo record based on its ID
    """
    name = request.form.get('name')
    stock = request.form.get('stock')
    unit_cost = request.form.get('unit_cost')
    vendor_id = int(request.form.get('vendorselect', 0))
    try:
        with app.app_context():
            insumo = Insumo.query.get(insumo_id)
            if request.method == "POST":
                vendor = filter_vendor(vendor_id=vendor_id)
                insumo.name = name
                insumo.stock = stock
                insumo.unit_cost = unit_cost
                insumo.vendor = vendor
                db.session.commit()
                return render_template(
                    "custom_alert_message.html",
                    message="Insumo agregado correctamente!",
                    error=False)
            else:
                vendor = filter_vendor(vendor_id=insumo.vendor_id)
                vendors = Vendor.query.all()
                return render_template('admin/edit_insumos_admin.html',
                                       insumo=insumo,
                                       insumo_number=insumo.id,
                                       vendors=vendors,
                                       vendor_selected_id=vendor.id)
    except Exception as e:
        return render_template(
            "custom_alert_message.html",
            message=str(e),
            error=True)


@app.route('/edit_order/<int:order_id>', methods=["GET", "POST"])
@token_required
@requires_admin_email()
def edit_order(order_id):
    """
    Editing an Insumo record based on its ID
    """
    estimated_delivery_date = request.form.get('estimated_delivery_date')
    status = request.form.get('status_order')
    try:
        with app.app_context():
            order = Order.query.get(order_id)
            general_statuses_for_admin = [status for status in OrderStatus if status != OrderStatus.CREADA]
            if request.method == "POST":
                if estimated_delivery_date:
                    order.estimated_delivery_date = estimated_delivery_date
                order.status = status
                db.session.commit()
                return render_template(
                    "custom_alert_message.html",
                    message="Pedido actualizado correctamente!",
                    order_id=order_id,
                    estimated_delivery_date=order.estimated_delivery_date,
                    statuses=general_statuses_for_admin,
                    actual_status=order.status.value,
                    error=False)
            else:
                return render_template(
                    'admin/edit_order_admin.html',
                    order_id=order_id,
                    estimated_delivery_date=order.estimated_delivery_date.strftime("%Y-%m-%d")
                    if order.estimated_delivery_date else '',
                    statuses=general_statuses_for_admin,
                    actual_status=order.status.value,
                    error=False
                )
    except Exception as e:
        message = str(e)
        return render_template(
            "custom_alert_message.html",
            message=message,
            error=True)


# Route to upload a file
@app.route('/upload_signature', methods=['POST'])
@token_required
def upload_signature():
    try:
        data_from_request = [key for key in request.form.keys()][0].split("_")
        order_id = data_from_request[1]
        order = Order.query.get_or_404(order_id)
        if request.form.get(f'signature_{order_id}'):
            order.letter_signature = request.form[f'signature_{order_id}']
            order.status = OrderStatus.EN_CAMINO
        else:
            order.letter_response_signature = request.form[f'signatureresponse_{order_id}']
            order.status = OrderStatus.ENTREGADO
        db.session.commit()
        return redirect(url_for('get_letter_html', order_id=order_id))
    except Exception as e:
        return f"Ha ocurrido un error cargando la firma: {str(e)}"


@app.route('/get_letter_html/<int:order_id>', methods=["GET"])
def get_letter_html(order_id):
    order = Order.query.get_or_404(order_id)
    return render_template(
        "representante/embed_letter.html",
        order_id=order_id,
        order_letter_signature=True if order.letter_signature else False,
        order_letter_response_signature=True if order.letter_response_signature else False
    )


def get_bayer_logo():
    image_path = os.path.join(app.root_path, 'static/assets/img/bayer_logo.png')
    # Read the image file and encode it in base64
    with open(image_path, 'rb') as image_file:
        encoded_image = base64.b64encode(image_file.read()).decode('utf-8')
    image_data = f'data:image/png;base64,{encoded_image}'
    return image_data


@app.route('/delete_insumo/<int:insumo_id>', methods=["DELETE"])
def delete_insumo(insumo_id):
    insumo = Insumo.query.get_or_404(insumo_id)
    db.session.delete(insumo)
    db.session.commit()
    return jsonify({"Insumo eliminado!"}), 201