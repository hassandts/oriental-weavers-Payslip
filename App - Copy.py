# --- 1. استيراد المكتبات ---
import os
import pyodbc
import random
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from dotenv import load_dotenv
from functools import wraps
import pandas as pd
from werkzeug.utils import secure_filename
import datetime
import firebase_admin
from firebase_admin import credentials, auth


# --- 2. تهيئة التطبيق والإعدادات ---
load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")


cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred)

# --- 3. إعداد الاتصال بقاعدة البيانات ---
DB_SERVER = os.getenv("DB_SERVER")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

connection_string = (
    f"DRIVER={{ODBC Driver 17 for SQL Server}};"
    f"SERVER={DB_SERVER};DATABASE={DB_NAME};UID={DB_USER};PWD={DB_PASSWORD};"
)

def get_connection():
    try:
        return pyodbc.connect(connection_string)
    except Exception as e:
        print(f"Error connecting to database: {e}")
        return None

# --- 4. Decorator للتحقق من تسجيل الدخول ---
# هذا الكود سيحمي الصفحات الداخلية ويمنع الوصول إليها بدون تسجيل دخول
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'employee_id' not in session:
            flash("يرجى تسجيل الدخول أولاً للوصول لهذه الصفحة.", "error")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --- 5. مسارات (Routes) تسجيل الدخول والخروج ---

@app.route('/login')
def login():
    # إذا كان المستخدم مسجل دخوله بالفعل، يتم توجيهه للصفحة الرئيسية
    if 'employee_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('login.html')

# Decorator جديد للتحقق من أن المستخدم هو المدير
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # --- أضف سطر المراقبة هذا هنا ---
        print(f"ADMIN CHECK: الحارس يرى أن الصلاحية هي: '{session.get('role')}'")
        
        if session.get('role') != 'admin':
            flash("ليس لديك صلاحية للوصول لهذه الصفحة.", "error")
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

# --- مسارات (Routes) لوحة تحكم المدير ---


@app.route('/check_employee', methods=['POST'])
def check_employee():
    data = request.get_json()
    emp_id = data.get('emp_id')
    phone_number = data.get('phone_number')

    conn = get_connection()
    if not conn:
        return jsonify({'exists': False, 'message': 'خطأ في الاتصال بقاعدة البيانات'})
        
    cursor = conn.cursor()
    # ملاحظة: تأكد من أن رقم الهاتف في قاعدة البيانات يحتوي على كود الدولة (مثال: +20)
    cursor.execute("SELECT EmployeeID FROM Employees WHERE EmployeeID = ? AND MobileNumber = ?", (emp_id, phone_number))
    employee = cursor.fetchone()
    conn.close()

    if employee:
        return jsonify({'exists': True})
    else:
        return jsonify({'exists': False, 'message': 'كود الموظف أو رقم الموبايل غير صحيح.'})


# الدالة الجديدة الثانية: لتسجيل الدخول الفعلي بعد التحقق من Firebase
@app.route('/firebase_login', methods=['POST'])
def firebase_login():
    data = request.get_json()
    id_token = data.get('id_token')

    try:
        # التحقق من الـ token باستخدام Firebase Admin
        decoded_token = auth.verify_id_token(id_token)
        phone_number = decoded_token['phone_number']

        # بعد التأكد من هوية المستخدم، نبحث عنه في قاعدة بياناتنا
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT EmployeeID, Role FROM Employees WHERE MobileNumber = ?", (phone_number,))
        employee = cursor.fetchone()
        conn.close()

        if employee:
            # تسجيل الدخول في نظامنا (Flask Session)
            session.clear()
            session['employee_id'] = employee.EmployeeID
            session['role'] = employee.Role.lower()
            return redirect(url_for('dashboard'))
        else:
            # هذا يجب ألا يحدث لأننا تحققنا منه مسبقًا
            return 'Error: Employee not found', 400

    except Exception as e:
        print(f"Firebase login error: {e}")
        return 'Error: Invalid token', 401

@app.route('/employees')
@login_required  # يجب أن يكون مسجل دخوله
@admin_required  # يجب أن يكون مديرًا
def employees():
    employees_list = []
    conn = get_connection()
    if not conn:
        flash("خطأ في الاتصال بقاعدة البيانات.", "error")
    else:
        try:
            cursor = conn.cursor()
            # جلب البيانات الأساسية للموظفين
            cursor.execute("SELECT EmployeeID, EmployeeName, NationalID, MobileNumber, Role FROM Employees")
            # تحويل النتائج إلى شكل يمكن استخدامه في HTML
            columns = [column[0] for column in cursor.description]
            employees_list = [dict(zip(columns, row)) for row in cursor.fetchall()]
            conn.close()
        except Exception as e:
            flash(f"حدث خطأ أثناء جلب بيانات الموظفين: {e}", "error")
            
    # إرسال قائمة الموظفين إلى صفحة HTML جديدة اسمها employees.html
    return render_template('employees.html', employees=employees_list)



@app.route('/payslips')
@login_required
@admin_required
def payslips_overview():
    payslip_data = {}
    conn = get_connection()
    if not conn:
        flash("خطأ في الاتصال بقاعدة البيانات.", "error")
    else:
        try:
            cursor = conn.cursor()
            query = "SELECT DISTINCT PayYear, PayMonth FROM Payslips ORDER BY PayYear DESC, PayMonth DESC"
            cursor.execute(query)
            
            for row in cursor.fetchall():
                year = row.PayYear
                month = row.PayMonth

                # --- هذا هو التعديل الهام ---
                # إذا كانت السنة أو الشهر فارغًا في قاعدة البيانات، تجاهل هذا السجل تمامًا
                if not year or not month:
                    continue  # انتقل إلى السجل التالي في قاعدة البيانات

                if year not in payslip_data:
                    payslip_data[year] = []
                payslip_data[year].append(month)
            
            conn.close()
        except Exception as e:
            flash(f"حدث خطأ أثناء جلب بيانات الرواتب: {e}", "error")
            
    return render_template('payslips_overview.html', payslip_data=payslip_data)

@app.route('/payslips/<int:year>/<month>')
@login_required
@admin_required
def payslip_details(year, month):
    summary = {}
    payslips_list = []
    conn = get_connection()
    if not conn:
        flash("خطأ في الاتصال بقاعدة البيانات.", "error")
    else:
        try:
            cursor = conn.cursor()
            
            # --- الاستعلام الأول: جلب الإجماليات ---
            summary_query = """
                SELECT 
                    COUNT(EmployeeID) AS TotalEmployees, 
                    SUM(NetSalary) AS TotalNetSalary
                FROM Payslips 
                WHERE PayYear = ? AND PayMonth = ?
            """
            cursor.execute(summary_query, year, month)
            summary_row = cursor.fetchone()
            if summary_row:
                summary = {
                    'year': year,
                    'month': month,
                    'total_employees': summary_row.TotalEmployees,
                    'total_net_salary': summary_row.TotalNetSalary
                }

            # --- الاستعلام الثاني: جلب قائمة الرواتب المفصلة ---
            details_query = """
                SELECT EmployeeName, EmployeeID, BasicSalary, TotalEntitlements, TotalDeductions, NetSalary 
                FROM Payslips 
                WHERE PayYear = ? AND PayMonth = ?
                ORDER BY EmployeeName
            """
            cursor.execute(details_query, year, month)
            columns = [column[0] for column in cursor.description]
            payslips_list = [dict(zip(columns, row)) for row in cursor.fetchall()]

            conn.close()
        except Exception as e:
            flash(f"حدث خطأ أثناء جلب تفاصيل الرواتب: {e}", "error")
            return redirect(url_for('payslips_overview'))

    return render_template('payslip_details.html', summary=summary, payslips=payslips_list)


# --- خريطة لترجمة أسماء الأعمدة من العربي في الإكسل إلى الإنجليزي في قاعدة البيانات ---
COLUMN_MAPPING = {
    'رقم الموظف': 'EmployeeID', 'الاسم': 'EmployeeName', 'الرقم القومي': 'NationalID',
    'الوظيفة': 'JobTitle', 'كود مركز التكلفة': 'CostCenterCode', 'مركز التكلفة': 'CostCenterName',
    'الإدارة': 'Department', 'رقم الموبايل': 'MobileNumber', 'مرتب أساسي': 'BasicSalary',
    'بدل تمثيل': 'RepresentationAllowance', 'بدل إنتقال': 'TransportationAllowance',
    'بدل ترقية': 'PromotionAllowance', 'بدل سيارة': 'CarAllowance', 'بدل نول': 'NolAllowance',
    'بدل انتاج': 'ProductionAllowance', 'علاوات خاصة': 'SpecialAllowances',
    'بدل طبيعة': 'NatureOfWorkAllowance', 'بدل غذاء': 'FoodAllowance', 'غلاء معيشة': 'CostOfLiving',
    'جهد': 'EffortAllowance', 'بدل إنتظام': 'RegularityAllowance', 'اجمالي بدلات': 'TotalAllowances',
    'إضافي': 'Overtime', 'صافي الحوافز': 'NetIncentives', 'بدل الباركود': 'BarcodeAllowance',
    'بدل جودة': 'QualityAllowance', 'حافز النسيج': 'FabricIncentive', 'حافز استثنائ': 'ExceptionalIncentive',
    'حافز إداري': 'AdministrativeIncentive', 'حافز عمليات': 'OperationsIncentive', 'بدل سكن': 'HousingAllowance',
    'استحقاقات إخري': 'OtherEntitlements', 'عمولة': 'Commission', 'حافز انتاج': 'ProductionIncentive',
    'الإسترداد': 'Reimbursement', 'حافز كفاءة': 'EfficiencyIncentive', 'بدل ملبس': 'ClothingAllowance',
    'مكافئة': 'Bonus', 'إجمالى الاستحفافات': 'TotalEntitlements',
    'حصة الموظف من التامينات': 'EmployeeInsuranceShare', 'مدة تامينات سابقة': 'PreviousInsurancePeriod',
    'كسب عمل': 'WorkEarnings', 'غياب': 'AbsenceDeduction', 'جزاء راتب': 'SalaryPenalty',
    'سلفة': 'AdvancePayment', 'غرامة': 'FineDeduction', 'كهرباء': 'ElectricityDeduction',
    'تليفون': 'PhoneDeduction', 'مياه': 'WaterDeduction', 'فرق ايام': 'DaysDifferenceDeduction',
    'خصومات اخري': 'OtherDeductions', 'كارت بريميوم': 'PremiumCardDeduction',
    'ص.ت.الشهداء': 'MartyrsFundDeduction', 'خزانه': 'TreasuryDeduction',
    'إجمالى الاستقطاعات': 'TotalDeductions', 'الصافي': 'NetSalary'
}


@app.route('/upload', methods=['GET', 'POST'])
@login_required
@admin_required
def upload_payslips():
    if request.method == 'POST':
        if 'payslip_file' not in request.files:
            flash("لم يتم اختيار أي ملف.", "error")
            return redirect(request.url)
        file = request.files['payslip_file']
        if file.filename == '' or not file.filename.endswith('.xlsx'):
            flash("يرجى اختيار ملف إكسل بصيغة .xlsx", "error")
            return redirect(request.url)

        try:
            pay_year = int(request.form.get('pay_year'))
            pay_month = request.form.get('pay_month')
            
            df = pd.read_excel(file, header=0, dtype=str).fillna('')
            df.rename(columns=COLUMN_MAPPING, inplace=True)

            conn = get_connection()
            cursor = conn.cursor()

            cursor.execute("DELETE FROM Payslips WHERE PayYear = ? AND PayMonth = ?", (pay_year, pay_month))

            cursor.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'Employees'")
            db_employee_columns = {row.COLUMN_NAME for row in cursor.fetchall()}
            
            cursor.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'Payslips'")
            db_payslip_columns = {row.COLUMN_NAME for row in cursor.fetchall()}

            processed_count = 0
            for index, row in df.iterrows():
                employee_id = row.get('EmployeeID')
                if not employee_id:
                    continue

                # --- تعديل جديد: توحيد صيغة أرقام الهواتف ---
                if 'MobileNumber' in row and row['MobileNumber']:
                    phone = str(row['MobileNumber']).strip()
                    if phone.startswith('0'):
                        phone = '+2' + phone
                    elif not phone.startswith('+20'):
                        phone = '+20' + phone
                    row['MobileNumber'] = phone
                # --- نهاية التعديل ---

                # 1. تحديث أو إضافة الموظف
                cursor.execute("SELECT EmployeeID FROM Employees WHERE EmployeeID = ?", employee_id)
                exists = cursor.fetchone()

                employee_data = {k: v for k, v in row.items() if k in db_employee_columns and v != ''}
                
                if exists:
                    if len(employee_data) > 1:
                        update_data = employee_data.copy()
                        del update_data['EmployeeID']
                        set_clause = ", ".join([f"[{key}] = ?" for key in update_data.keys()])
                        values = list(update_data.values()) + [employee_id]
                        query = f"UPDATE Employees SET {set_clause} WHERE EmployeeID = ?"
                        cursor.execute(query, values)
                else:
                    if 'Role' not in employee_data: employee_data['Role'] = 'employee'
                    cols = ", ".join([f"[{key}]" for key in employee_data.keys()])
                    placeholders = ", ".join(['?'] * len(employee_data))
                    query = f"INSERT INTO Employees ({cols}) VALUES ({placeholders})"
                    cursor.execute(query, list(employee_data.values()))

                # 2. إضافة الراتب
                payslip_data = {k: v for k, v in row.items() if k in db_payslip_columns and v != ''}
                payslip_data['PayYear'] = pay_year
                payslip_data['PayMonth'] = pay_month
                
                cols = ", ".join([f"[{key}]" for key in payslip_data.keys()])
                placeholders = ", ".join(['?'] * len(payslip_data))
                query = f"INSERT INTO Payslips ({cols}) VALUES ({placeholders})"
                cursor.execute(query, list(payslip_data.values()))
                
                processed_count += 1

            conn.commit()
            conn.close()
            flash(f"✅ تمت معالجة ورفع بيانات {processed_count} موظفًا بنجاح!", "success")

        except pyodbc.Error as ex:
            sqlstate = ex.args[0]
            print(f"DATABASE ERROR: {ex}")
            flash(f"❌ حدث خطأ في قاعدة البيانات: {ex}", "error")
            return redirect(request.url)
        except Exception as e:
            print(f"GENERAL ERROR: {e}")
            flash(f"❌ حدث خطأ فادح أثناء معالجة الملف: {e}", "error")
            return redirect(request.url)

        return redirect(url_for('payslips_overview'))

    current_year = datetime.datetime.now().year
    return render_template('upload_payslips.html', current_year=current_year)

# --- مسارات (Routes) خاصة بالموظف ---

@app.route('/my_payslips')
@login_required # لا نحتاج لـ @admin_required هنا
def my_payslips():
    employee_id = session.get('employee_id')
    payslip_data = {}
    conn = get_connection()
    if not conn:
        flash("خطأ في الاتصال بقاعدة البيانات.", "error")
    else:
        try:
            cursor = conn.cursor()
            # نفس الاستعلام السابق ولكن مع شرط لجلب بيانات هذا الموظف فقط
            query = """
                SELECT DISTINCT PayYear, PayMonth 
                FROM Payslips 
                WHERE EmployeeID = ? 
                ORDER BY PayYear DESC, PayMonth DESC
            """
            cursor.execute(query, employee_id)
            
            for row in cursor.fetchall():
                year = row.PayYear
                month = row.PayMonth
                if year not in payslip_data:
                    payslip_data[year] = []
                payslip_data[year].append(month)
            
            conn.close()
        except Exception as e:
            flash(f"حدث خطأ أثناء جلب بيانات رواتبك: {e}", "error")
            
    return render_template('my_payslips.html', payslip_data=payslip_data)

# --- دالة مساعدة لتنظيم بيانات الراتب ---
def process_payslip_data(raw_data):
    # قائمة بأسماء أعمدة الاستحقاقات
    entitlement_cols = [
        'BasicSalary', 'RepresentationAllowance', 'TransportationAllowance', 'PromotionAllowance', 
        'CarAllowance', 'NolAllowance', 'ProductionAllowance', 'SpecialAllowances', 
        'NatureOfWorkAllowance', 'FoodAllowance', 'CostOfLiving', 'EffortAllowance', 
        'RegularityAllowance', 'Overtime', 'NetIncentives', 'BarcodeAllowance', 
        'QualityAllowance', 'FabricIncentive', 'ExceptionalIncentive', 'AdministrativeIncentive', 
        'OperationsIncentive', 'HousingAllowance', 'OtherEntitlements', 'Commission', 
        'ProductionIncentive', 'Reimbursement', 'EfficiencyIncentive', 'ClothingAllowance', 'Bonus'
    ]
    # قائمة بأسماء أعمدة الاستقطاعات
    deduction_cols = [
        'EmployeeInsuranceShare', 'WorkEarnings', 'AbsenceDeduction', 'SalaryPenalty', 
        'AdvancePayment', 'FineDeduction', 'ElectricityDeduction', 'PhoneDeduction', 
        'WaterDeduction', 'DaysDifferenceDeduction', 'OtherDeductions', 'PremiumCardDeduction', 
        'MartyrsFundDeduction', 'TreasuryDeduction'
    ]
    # خريطة لترجمة الأسماء من الإنجليزية إلى العربية للعرض
    arabic_map = {v: k for k, v in COLUMN_MAPPING.items()}

    payslip = {
        'raw_data': raw_data,
        'entitlements': {},
        'deductions': {},
        'totals': {
            'إجمالي الاستحقاقات': raw_data.get('TotalEntitlements', 0),
            'إجمالي الاستقطاعات': raw_data.get('TotalDeductions', 0)
        }
    }

    for col in entitlement_cols:
        if raw_data.get(col) and float(raw_data[col]) > 0:
            payslip['entitlements'][arabic_map.get(col, col)] = raw_data[col]
            
    for col in deduction_cols:
        if raw_data.get(col) and float(raw_data[col]) != 0: # قد تكون سالبة
            payslip['deductions'][arabic_map.get(col, col)] = raw_data[col]
            
    return payslip

# --- مسار عرض تفاصيل راتب الموظف ---
@app.route('/my_payslips/<int:year>/<month>')
@login_required
def my_payslip_detail(year, month):
    employee_id = session.get('employee_id')
    payslip_details = None
    
    conn = get_connection()
    if not conn:
        flash("خطأ في الاتصال بقاعدة البيانات.", "error")
    else:
        try:
            cursor = conn.cursor()
            query = "SELECT * FROM Payslips WHERE EmployeeID = ? AND PayYear = ? AND PayMonth = ?"
            cursor.execute(query, employee_id, year, month)
            
            # تحويل الصف إلى قاموس (dictionary)
            columns = [column[0] for column in cursor.description]
            raw_data = cursor.fetchone()
            
            if raw_data:
                raw_data_dict = dict(zip(columns, raw_data))
                # معالجة البيانات باستخدام الدالة المساعدة
                payslip_details = process_payslip_data(raw_data_dict)
            
            conn.close()
        except Exception as e:
            flash(f"حدث خطأ أثناء جلب تفاصيل راتبك: {e}", "error")

    if not payslip_details:
        flash("لم يتم العثور على بيانات راتب لهذا الشهر.", "error")
        return redirect(url_for('my_payslips'))

    return render_template('my_payslip_detail.html', payslip=payslip_details)


@app.route('/complaints')
@login_required
def complaints():
    # الآن الدالة تقوم فقط بعرض الصفحة
    return render_template('complaints.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("تم تسجيل الخروج بنجاح.", "success")
    return redirect(url_for('login'))

# --- 6. الصفحات الداخلية للتطبيق ---

@app.route('/')
@login_required
def dashboard():
    print(f"DEBUG: دور المستخدم الحالي في الجلسة هو: '{session.get('role')}'") 
    return render_template('dashboard.html')
    

# --- 7. تشغيل التطبيق ---
if __name__ == '__main__':
    app.run(debug=True)