# Copyright (c) 2025, MahmoudAbdElHamidHaggag and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, getdate, date_diff, time_diff_in_hours
from datetime import datetime
import json

def execute(filters=None):
    """
    تقرير أداء السائقين والمركبات
    Driver/Vehicle Performance Report
    """
    if not filters:
        filters = {}
    
    columns = get_columns()
    data = get_data(filters)
    
    return columns, data

def get_columns():
    """تعريف أعمدة التقرير"""
    return [
        {
            "label": _("Driver/السائق"),
            "fieldname": "driver",
            "fieldtype": "Link",
            "options": "Employee",
            "width": 150
        },
        {
            "label": _("Vehicle/المركبة"),
            "fieldname": "vehicle",
            "fieldtype": "Link", 
            "options": "Vehicle",
            "width": 120
        },
        {
            "label": _("Total Trips/إجمالي النقلات"),
            "fieldname": "total_trips",
            "fieldtype": "Int",
            "width": 100
        },
        {
            "label": _("Total Quantity/إجمالي الكمية"),
            "fieldname": "total_quantity",
            "fieldtype": "Float",
            "width": 120
        },
        {
            "label": _("Total Revenue/إجمالي الإيرادات"),
            "fieldname": "total_revenue",
            "fieldtype": "Currency",
            "width": 130
        },
        {
            "label": _("Vehicle Costs/تكاليف المركبة"),
            "fieldname": "vehicle_costs",
            "fieldtype": "Currency", 
            "width": 130
        },
        {
            "label": _("Driver Salary/راتب السائق"),
            "fieldname": "driver_salary",
            "fieldtype": "Currency",
            "width": 120
        },
        {
            "label": _("Loading Time (Hrs)/وقت التحميل"),
            "fieldname": "total_loading_time",
            "fieldtype": "Float",
            "width": 120
        },
        {
            "label": _("Unloading Time (Hrs)/وقت التفريغ"),
            "fieldname": "total_unloading_time", 
            "fieldtype": "Float",
            "width": 120
        },
        {
            "label": _("Total Work Hours/إجمالي ساعات العمل"),
            "fieldname": "total_work_hours",
            "fieldtype": "Float",
            "width": 130
        },
        {
            "label": _("Salary Rate/Hour/معدل الأجر بالساعة"),
            "fieldname": "hourly_rate",
            "fieldtype": "Currency",
            "width": 130
        },
        {
            "label": _("Net Profit/صافي الربح"),
            "fieldname": "net_profit",
            "fieldtype": "Currency",
            "width": 120
        },
        {
            "label": _("Profit Margin %/هامش الربح %"),
            "fieldname": "profit_margin",
            "fieldtype": "Percent",
            "width": 120
        }
    ]

def get_data(filters):
    """جلب البيانات وتجميعها"""
    conditions = get_conditions(filters)
    
    # استعلام أساسي لجلب بيانات النقلات
    query = """
    SELECT 
        uu.driver,
        uu.vehicle,
        uu.delivered_quantity,
        sbb.transportation_price,
        sbb.customer,
        sbb.from_date,
        sbb.to_date,
        uu.parent as sales_billing_batch
    FROM `tabUnbilled Unloading` uu
    INNER JOIN `tabSales Billing Batch` sbb ON uu.parent = sbb.name
    WHERE sbb.docstatus != 2 {conditions}
    ORDER BY uu.driver, uu.vehicle
    """.format(conditions=conditions)
    
    raw_data = frappe.db.sql(query, filters, as_dict=True)
    
    # تجميع البيانات حسب السائق والمركبة
    grouped_data = {}
    
    for row in raw_data:
        key = (row.driver or "", row.vehicle or "")
        
        if key not in grouped_data:
            grouped_data[key] = {
                'driver': row.driver,
                'vehicle': row.vehicle,
                'total_trips': 0,
                'total_quantity': 0,
                'total_revenue': 0,
                'total_loading_time': 0,
                'total_unloading_time': 0,
                'from_date': row.from_date,
                'to_date': row.to_date,
                'customer': row.customer
            }
        
        # تجميع البيانات
        grouped_data[key]['total_trips'] += 1
        grouped_data[key]['total_quantity'] += flt(row.delivered_quantity)
        grouped_data[key]['total_revenue'] += flt(row.transportation_price) * flt(row.delivered_quantity)
        
        # حساب أوقات التحميل والتفريغ
        if row.loading_start_time and row.loading_end_time:
            loading_hours = time_diff_in_hours(row.loading_end_time, row.loading_start_time)
            grouped_data[key]['total_loading_time'] += flt(loading_hours)
        
        if row.unloading_start_time and row.unloading_end_time:
            unloading_hours = time_diff_in_hours(row.unloading_end_time, row.unloading_start_time)
            grouped_data[key]['total_unloading_time'] += flt(unloading_hours)
    
    # إضافة التكاليف والحسابات النهائية
    final_data = []
    for key, data in grouped_data.items():
        # حساب تكاليف المركبة
        vehicle_costs = get_vehicle_costs(data['vehicle'], data['from_date'], data['to_date'])
        
        # حساب راتب السائق
        driver_salary = get_driver_salary(data['driver'], data['from_date'], data['to_date'])
        
        # حساب إجمالي ساعات العمل
        total_work_hours = data['total_loading_time'] + data['total_unloading_time']
        
        # حساب معدل الأجر بالساعة
        hourly_rate = 0
        if total_work_hours > 0 and driver_salary > 0:
            hourly_rate = driver_salary / total_work_hours
        
        # حساب صافي الربح
        total_costs = vehicle_costs + driver_salary
        net_profit = data['total_revenue'] - total_costs
        
        # حساب هامش الربح
        profit_margin = 0
        if data['total_revenue'] > 0:
            profit_margin = (net_profit / data['total_revenue']) * 100
        
        final_data.append({
            'driver': data['driver'],
            'vehicle': data['vehicle'],
            'total_trips': data['total_trips'],
            'total_quantity': data['total_quantity'],
            'total_revenue': data['total_revenue'],
            'vehicle_costs': vehicle_costs,
            'driver_salary': driver_salary,
            'total_loading_time': data['total_loading_time'],
            'total_unloading_time': data['total_unloading_time'],
            'total_work_hours': total_work_hours,
            'hourly_rate': hourly_rate,
            'net_profit': net_profit,
            'profit_margin': profit_margin
        })
    
    return final_data

def get_conditions(filters):
    """بناء شروط الاستعلام"""
    conditions = ""
    
    if filters.get("driver"):
        conditions += " AND uu.driver = %(driver)s"
    
    if filters.get("vehicle"):
        conditions += " AND uu.vehicle = %(vehicle)s"
    
    if filters.get("customer"):
        conditions += " AND sbb.customer = %(customer)s"
    
    if filters.get("from_date"):
        conditions += " AND sbb.from_date >= %(from_date)s"
    
    if filters.get("to_date"):
        conditions += " AND sbb.to_date <= %(to_date)s"
    
    if filters.get("contract_of_carriage"):
        conditions += " AND sbb.contract_of_carriage = %(contract_of_carriage)s"
    
    return conditions

def get_vehicle_costs(vehicle, from_date, to_date):
    """حساب تكاليف المركبة من القيود ومستندات الصيانة"""
    if not vehicle:
        return 0
    
    vehicle_costs = 0
    
    # تكاليف من Journal Entry
    journal_costs = frappe.db.sql("""
        SELECT SUM(jea.debit) as total_cost
        FROM `tabJournal Entry Account` jea
        INNER JOIN `tabJournal Entry` je ON jea.parent = je.name
        WHERE je.docstatus = 1
        AND jea.reference_type = 'Vehicle'
        AND jea.reference_name = %s
        AND je.posting_date BETWEEN %s AND %s
    """, (vehicle, from_date, to_date))
    
    if journal_costs and journal_costs[0][0]:
        vehicle_costs += flt(journal_costs[0][0])
    
    # تكاليف من مستندات الصيانة (إذا كانت متوفرة)
    try:
        maintenance_costs = frappe.db.sql("""
            SELECT SUM(total_cost) as total_maintenance
            FROM `tabAsset Maintenance Log`
            WHERE asset = %s
            AND docstatus = 1
            AND maintenance_date BETWEEN %s AND %s
        """, (vehicle, from_date, to_date))
        
        if maintenance_costs and maintenance_costs[0][0]:
            vehicle_costs += flt(maintenance_costs[0][0])
    except:
        pass
    
    # تكاليف الوقود (إذا كانت متوفرة)
    try:
        fuel_costs = frappe.db.sql("""
            SELECT SUM(fuel_cost) as total_fuel
            FROM `tabVehicle Log`
            WHERE license_plate = %s
            AND docstatus = 1
            AND date BETWEEN %s AND %s
        """, (vehicle, from_date, to_date))
        
        if fuel_costs and fuel_costs[0][0]:
            vehicle_costs += flt(fuel_costs[0][0])
    except:
        pass
    
    return vehicle_costs

def get_driver_salary(driver, from_date, to_date):
    """حساب راتب السائق للفترة المحددة"""
    if not driver:
        return 0
    
    try:
        # محاولة الحصول على راتب السائق من جدول الرواتب
        salary_data = frappe.db.sql("""
            SELECT SUM(net_pay) as total_salary
            FROM `tabSalary Slip`
            WHERE employee = %s
            AND docstatus = 1
            AND start_date >= %s
            AND end_date <= %s
        """, (driver, from_date, to_date))
        
        if salary_data and salary_data[0][0]:
            return flt(salary_data[0][0])
        
        # إذا لم تكن متوفرة، محاولة الحصول على الراتب الأساسي وتقسيمه
        employee_salary = frappe.db.get_value("Employee", driver, "salary")
        if employee_salary:
            # حساب عدد الأيام وتقسيم الراتب بناءً على الفترة
            days_diff = date_diff(to_date, from_date) + 1
            monthly_salary = flt(employee_salary)
            daily_rate = monthly_salary / 30
            return daily_rate * days_diff
            
    except:
        pass
    
    return 0

# إعدادات الفلاتر للتقرير
def get_filters():
    """تعريف فلاتر التقرير"""
    return [
        {
            "fieldname": "driver",
            "label": _("Driver"),
            "fieldtype": "Link",
            "options": "Employee"
        },
        {
            "fieldname": "vehicle", 
            "label": _("Vehicle"),
            "fieldtype": "Link",
            "options": "Vehicle"
        },
        {
            "fieldname": "customer",
            "label": _("Customer"),
            "fieldtype": "Link", 
            "options": "Customer"
        },
        {
            "fieldname": "from_date",
            "label": _("From Date"),
            "fieldtype": "Date",
            "default": frappe.utils.add_months(frappe.utils.today(), -1)
        },
        {
            "fieldname": "to_date",
            "label": _("To Date"), 
            "fieldtype": "Date",
            "default": frappe.utils.today()
        },
        {
            "fieldname": "contract_of_carriage",
            "label": _("Contract of Carriage"),
            "fieldtype": "Link",
            "options": "Contract of Carriage"
        }
    ]