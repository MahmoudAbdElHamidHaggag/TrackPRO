// Copyright (c) 2025, MahmoudAbdElHamidHaggag and contributors
// For license information, please see license.txt
frappe.ui.form.on('Head Trailer Assignment', {
  refresh(frm) {
    // الفلاتر: دايمًا تتضبط سواء المستند جديد أو لا
    frm.set_query('tractor_vehicle', () => ({
      query: 'trackpro.trackpro.api.vehicles_by_category',
      filters: { category: 'Tractor' }   
    }));

    frm.set_query('trailer_vehicle', () => ({
      query: 'trackpro.trackpro.api.vehicles_by_category',
      filters: { category: 'Trailer' }   
    }));

    // الزر فقط للمستند الموجود وغير ملغى وغير منتهٍ
    if (!frm.is_new() && frm.doc.docstatus === 1 && frm.doc.status !== "Ended") {
      frm.add_custom_button(__('فصل الرأس والذيل'), () => {
        frappe.call({
          method: 'trackpro.trackpro.api.detach_now',
          args: { name: frm.doc.name },
          freeze: true
        }).then(() => {
          frappe.show_alert(__('تم الفصل'));
          frm.reload_doc();
        });
      });
    }
  }
});
