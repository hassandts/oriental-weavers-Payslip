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
#import firebase_admin
#from firebase_admin import credentials, auth


# --- 2. تهيئة التطبيق والإعدادات ---
load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")


#cred = credentials.Certificate("serviceAccountKey.json")
#firebase_admin.initialize_app(cred)

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


@app.route("/request_otp", methods=["POST"])
def request_otp():
    emp_id = request.form.get("emp_id")
    phone_number_from_form = request.form.get("phone_number")
    
    # --- منطق توحيد رقم الهاتف (للمقارنة مع قاعدة البيانات) ---
    phone_to_check = str(phone_number_from_form).strip()
    if phone_to_check.startswith('0'):
        phone_to_check = '+2' + phone_to_check
    elif not phone_to_check.startswith('+20'):
        phone_to_check = '+20' + phone_to_check
    
    conn = get_connection()
    if not conn:
        flash("خطأ في الاتصال بقاعدة البيانات.", "error")
        return redirect(url_for('login'))
        
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM Employees WHERE EmployeeID = ? AND MobileNumber = ?", (emp_id, phone_to_check))
        employee = cursor.fetchone()

        if employee:
            otp = random.randint(100000, 999999)
            session['otp'] = str(otp) 
            session['otp_emp_id'] = emp_id
            
            # --- هذا هو الـ OTP التجريبي ---
            print("\n===================================")
            print(f"OTP for Employee {emp_id} is: {otp}")
            print("===================================\n")
            
            flash("تم إرسال رمز التحقق (انظر الكونسول).", "success")
            return redirect(url_for('verify_otp'))
        else:
            flash("كود الموظف أو رقم الموبايل غير صحيح.", "error")
            return redirect(url_for('login'))
    except Exception as e:
        flash(f"حدث خطأ: {e}", "error")
        return redirect(url_for('login'))

@app.route("/verify_otp", methods=["GET", "POST"])
def verify_otp():
    if 'otp_emp_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        user_otp = request.form.get('otp')
        if user_otp == session.get('otp'):
            emp_id = session.pop('otp_emp_id', None)
            session.pop('otp', None)
            session['employee_id'] = emp_id
            
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT Role FROM Employees WHERE EmployeeID = ?", (emp_id,))
            user_role = cursor.fetchone()
            conn.close()
            
            session['role'] = user_role.Role.lower() if user_role and user_role.Role else 'employee'

            return redirect(url_for('dashboard'))
        else:
            flash("رمز التحقق غير صحيح.", "error")
    
    return render_template('verify_otp.html')
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
            
            # 1. ترجمة الأعمدة المعروفة وتجهيز الجديدة
            original_excel_cols = df.columns.tolist()
            final_col_names = {}
            for col in original_excel_cols:
                if col in COLUMN_MAPPING:
                    final_col_names[col] = COLUMN_MAPPING[col]
                else:
                    safe_col_name = col.strip().replace(' ', '_')
                    final_col_names[col] = safe_col_name
            df.rename(columns=final_col_names, inplace=True)
            
            conn = get_connection()
            cursor = conn.cursor()

            # 2. المزامنة الديناميكية لهيكل قاعدة البيانات
            cursor.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'Employees'")
            db_employee_columns = {row.COLUMN_NAME for row in cursor.fetchall()}
            cursor.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'Payslips'")
            db_payslip_columns = {row.COLUMN_NAME for row in cursor.fetchall()}
            
            employee_base_cols = ['EmployeeID', 'EmployeeName', 'NationalID', 'JobTitle', 'CostCenterCode', 'CostCenterName', 'Department', 'MobileNumber', 'Role']

            for col_name in df.columns:
                is_employee_col = any(emp_col in col_name for emp_col in employee_base_cols)
                if is_employee_col and col_name not in db_employee_columns:
                    cursor.execute(f"ALTER TABLE Employees ADD [{col_name}] NVARCHAR(255) NULL")
                elif not is_employee_col and col_name not in db_payslip_columns:
                    cursor.execute(f"ALTER TABLE Payslips ADD [{col_name}] NVARCHAR(MAX) NULL")
            
            conn.commit()

            # تحديث قوائم الأعمدة بعد أي إضافة محتملة
            cursor.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'Employees'")
            db_employee_columns = {row.COLUMN_NAME for row in cursor.fetchall()}
            cursor.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'Payslips'")
            db_payslip_columns = {row.COLUMN_NAME for row in cursor.fetchall()}

            # 3. إدخال البيانات بعد التأكد من مزامنة الهيكل
            cursor.execute("DELETE FROM Payslips WHERE PayYear = ? AND PayMonth = ?", (pay_year, pay_month))
            processed_count = 0
            for index, row in df.iterrows():
                employee_id = row.get('EmployeeID')
                if not employee_id: continue

                # --- بداية التعديل: توحيد صيغة رقم الهاتف إجباريًا ---
                if 'MobileNumber' in row and row['MobileNumber']:
                    phone = str(row['MobileNumber']).strip()
                    if phone.startswith('0'):
                        # تحويل 010... إلى +2010...
                        phone = '+2' + phone
                    elif not phone.startswith('+20'):
                        # إضافة +20 إذا لم تكن موجودة
                        phone = '+20' + phone
                    # تحديث القيمة في الصف ليتم حفظها بالشكل الصحيح
                    row['MobileNumber'] = phone
                # --- نهاية التعديل ---

                # تحديث أو إضافة الموظف
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

                # إضافة الراتب
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

        except Exception as e:
            print(f"AN ERROR OCCURRED: {e}")
            flash(f"❌ حدث خطأ فادح أثناء معالجة الملف: {e}", "error")
            return redirect(request.url)

        return redirect(url_for('payslips_overview'))

    current_year = datetime.datetime.now().year
    return render_template('upload_payslips.html', current_year=current_year)# --- مسارات (Routes) خاصة بالموظف ---

@app.route('/my_payslips')
@login_required
def my_payslips():
    employee_id = session.get('employee_id')
    payslip_data = {}
    conn = get_connection()
    if not conn:
        flash("خطأ في الاتصال بقاعدة البيانات.", "error")
    else:
        try:
            cursor = conn.cursor()
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

                # --- هذا هو التعديل الهام ---
                # إذا كانت السنة أو الشهر فارغًا في قاعدة البيانات، تجاهل هذا السجل تمامًا
                if not year or not month:
                    continue  # انتقل إلى السجل التالي

                if year not in payslip_data:
                    payslip_data[year] = []
                payslip_data[year].append(month)
            
            conn.close()
        except Exception as e:
            flash(f"حدث خطأ أثناء جلب بيانات رواتبك: {e}", "error")
            
    return render_template('my_payslips.html', payslip_data=payslip_data)

# --- دالة مساعدة لتنظيم بيانات الراتب (الإصدار النهائي مع الحساب التلقائي) ---
def process_payslip_data(raw_data):
    non_salary_cols = [
        'PayslipID', 'EmployeeID', 'EmployeeName', 'NationalID', 'Role', 'JobTitle',
        'CostCenterCode', 'CostCenterName', 'Department', 'MobileNumber', 'PayMonth', 'PayYear',
        'TotalAllowances', 'TotalEntitlements', 'TotalDeductions', 'NetSalary', # سنتجاهل الصافي من الملف
        'PreviousInsurancePeriod'
    ]
    
    arabic_map = {v: k for k, v in COLUMN_MAPPING.items()}

    # --- بداية التعديل الهام ---
    
    # 1. جلب الإجماليات وتحويلها إلى أرقام بشكل آمن
    total_entitlements = float(raw_data.get('TotalEntitlements', 0) or 0)
    total_deductions = float(raw_data.get('TotalDeductions', 0) or 0)
    
    # 2. حساب صافي المرتب الصحيح
    calculated_net_salary = total_entitlements + total_deductions
    
    # 3. تحديث البيانات الخام بالقيمة الصحيحة
    raw_data['NetSalary'] = calculated_net_salary

    payslip = {
        'raw_data': raw_data, # الآن تحتوي على الصافي الصحيح
        'entitlements': {},
        'deductions': {},
        'totals': {
            'إجمالي الاستحقاقات': total_entitlements,
            'إجمالي الاستقطاعات': total_deductions
        }
    }
    # --- نهاية التعديل الهام ---

    for db_col_name, value in raw_data.items():
        if db_col_name in non_salary_cols:
            continue
        
        try:
            numeric_value = float(value)
            if numeric_value > 0:
                arabic_name = arabic_map.get(db_col_name, db_col_name)
                payslip['entitlements'][arabic_name] = numeric_value
            elif numeric_value < 0:
                arabic_name = arabic_map.get(db_col_name, db_col_name)
                # نعرض الاستقطاعات كأرقام موجبة لتجنب علامة السالب المزدوجة
                payslip['deductions'][arabic_name] = abs(numeric_value) 
        except (ValueError, TypeError):
            continue
            
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