const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// EM-16: the New Email dialog on the Emails list asks for type, language and folder as well.
test('New Email dialog sends email type, language and folder to the server', () => {
    let dialogOptions;
    let call;
    class Dialog {
        constructor(options) {
            dialogOptions = options;
            this.fields_dict = { subject: { $input: { on() {} }, get_value: () => '' }, template_name: { $input: { on() {} }, get_value: () => '' } };
        }
        show() {}
        hide() {}
        set_value() {}
        get_values() { return { template_name: 'Autumn', subject: 'Autumn offer', email_type: 'Newsletter', language: 'fr', folder: 'Campaigns' }; }
    }
    const frappe = {
        listview_settings: {}, provide() {}, user: { has_role: role => role === 'Email Designer' },
        ui: { Dialog },
        call(options) { call = options; },
        email_template_library: { open_builder() {} }, email_template_builder: {}, reach_folder_sidebar: { setup() {} },
    };
    vm.runInNewContext(
        fs.readFileSync(path.join(__dirname, '../finbyzreach/public/js/doctype_list_js/email_template_list.js'), 'utf8'),
        { frappe, __: x => x },
    );
    frappe.listview_settings['Email Template'].primary_action();
    const fields = Array.from(dialogOptions.fields, field => field.fieldname);
    assert.deepEqual(fields, ['template_name', 'subject', 'email_type', 'language', 'folder']);
    const type = dialogOptions.fields.find(field => field.fieldname === 'email_type');
    assert.equal(type.options, 'Subscription Topic');
    assert.deepEqual(JSON.parse(JSON.stringify(type.get_query().filters)), { disabled: 0, category: ['in', ['Mailing Type', 'System']] });
    dialogOptions.primary_action();
    assert.equal(call.args.email_type, 'Newsletter');
    assert.equal(call.args.language, 'fr');
    assert.equal(call.args.folder, 'Campaigns');
});
