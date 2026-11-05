const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

test('record membership form actions send GET to the read-only endpoint', async () => {
    const forms = {};
    const calls = [];
    const frappe = {
        ui: { form: { on: (doctype, handlers) => { forms[doctype] = handlers; } } },
        model: { can_read: () => true },
        listview_settings: {}, realtime: { on: () => {} },
        call: options => { calls.push(options); return Promise.resolve({ message: [] }); }
    };
    const source = fs.readFileSync(path.join(__dirname, '../finbyzreach/public/js/segment_membership.js'), 'utf8');
    vm.runInNewContext(source, { frappe, __: text => text });
    for (const doctype of ['Lead', 'Contact', 'Customer']) {
        forms[doctype].refresh({ is_new: () => false, doc: {name:'TEST-RECORD'}, add_custom_button: () => {} });
    }
    await Promise.resolve();
    assert.equal(calls.length, 3);
    for (const call of calls) {
        assert.equal(call.method, 'finbyzreach.segments.record_segments');
        assert.equal(call.type, 'GET');
        assert.equal(call.args.name, 'TEST-RECORD');
    }
});
