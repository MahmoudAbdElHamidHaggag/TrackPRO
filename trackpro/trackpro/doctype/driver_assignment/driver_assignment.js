// Copyright (c) 2025, MahmoudAbdElHamidHaggag and contributors
// For license information, please see license.txt

const HEAD_ONLY  = ['Head','Tractor']; // رأس
const TRUCK_ONLY = ['Truck'];          // ترنك/سيارة كاملة

frappe.ui.form.on('Driver Assignment', {
  setup(frm) {
    // اجلب النوع إلى الحقل المخفي "type"
    frm.add_fetch('vehicle', 'custom_vehicle_category', 'type');

    // فلترة المركبات المعروضة: رأس + ترنك فقط (عبر API)
    frm.set_query('vehicle', () => ({
      query: 'trackpro.trackpro.api.vehicles_by_category_drive',
      filters: { categories: [...HEAD_ONLY, ...TRUCK_ONLY] }
    }));

    // مفتاح داخلي لتجنّب تكرار رسالة التأكيد لنفس الاختيار
    frm.__trailer_prompt_key = null;
  },

  refresh(frm) {
    // نظّف شريط التنبيه العلوي
    frm.dashboard?.clear_headline();

    // زر "إنهاء الربط" يظهر فقط بعد الترحيل (docstatus=1) ومش Ended
    if (frm.doc.docstatus === 1 && frm.doc.status !== 'Ended') {
      frm.add_custom_button(__('إنهاء الربط'), () => {
        frappe.call({
          method: 'trackpro.trackpro.api.detach_driver_now',
          args: { name: frm.doc.name },
          freeze: true
        }).then(() => frm.reload_doc());
      });
    }
    // ملاحظة مهمة: لا نستدعي frm.trigger('vehicle') هنا عشان ما نفتحش حوارات عند الحفظ/الريفريش
  },

  // لو غيّر تاريخ البداية نعتبرها حالة جديدة → اسمح بعرض الرسالة مرة أخرى
  from_datetime(frm) {
    frm.__trailer_prompt_key = null;
  },

  vehicle(frm) {
    // امسح أي تنبيه قديم
    frm.dashboard?.clear_headline();

    const cat = (frm.doc.type || '').trim();

    // لو ترنك: اخفي الذيل ولا رسائل
    if (TRUCK_ONLY.includes(cat)) {
      frm.toggle_display('trailer', false);
      frm.set_value('trailer', null);
      frm.__trailer_prompt_key = `${frm.doc.vehicle || ''}__${frm.doc.from_datetime || ''}`;
      return;
    }

    // لو رأس: أظهر الذيل وافحص الربط
    const isHead = HEAD_ONLY.includes(cat);
    frm.toggle_display('trailer', isHead);

    if (!isHead || !frm.doc.vehicle) {
      frm.set_value('trailer', null);
      frm.__trailer_prompt_key = null;
      return;
    }

    // مفتاح ي uniquely يحدد الاختيار الحالي (عربية + من-تاريخ)
    const key = `${frm.doc.vehicle}__${frm.doc.from_datetime || ''}`;

    // لو سبق وافق المستخدم لنفس الاختيار، لا تعِد عرض الرسالة
    if (frm.__trailer_prompt_key === key) {
      return;
    }

    // استعلم عن الذيل النشِط فعليًا
    frappe.call({
      method: 'trackpro.trackpro.api.get_active_trailer_for_head',
      args: {
        head: frm.doc.vehicle,
        at: frm.doc.from_datetime || frappe.datetime.now_datetime()
      }
    }).then(r => {
      const trailer = r.message;

      if (trailer) {
        // مرتبط بذيل: عبّي الحقل واظهر تنبيه أخضر في الأعلى، ولا تسأل المستخدم
        frm.set_value('trailer', trailer);
        frm.dashboard?.set_headline_alert(
          __('الرأس مرتبط بذيل: {0}', [trailer]),
          'green'
        );
        // ثبّت المفتاح عشان ما نكررش أي حوار لنفس الاختيار
        frm.__trailer_prompt_key = key;
        return;
      }

      // غير مرتبط بذيل: فضّي الحقل واسأل المستخدم "مرّة واحدة" لهذا الاختيار
      frm.set_value('trailer', null);

      frappe.confirm(
        __('الرأس غير مرتبط بمقطورة الآن. هل تريد إكمال المستند دون مقطورة؟'),
        // نعم
        () => {
          frm.__trailer_prompt_key = key; // وافق → لا تكرّر الرسالة لنفس الاختيار
          frm.dashboard?.set_headline_alert(__('سيتم الإكمال بدون مقطورة.'), 'orange');
        },
        // لا
        () => {
          // الغِ الاختيار واسمحله يختار عربية أخرى
          frm.set_value('vehicle', null);
          frm.set_value('trailer', null);
          frm.__trailer_prompt_key = null;
          frm.dashboard?.clear_headline();
          frappe.utils.play_sound('error');
        }
      );
    });
  }
});