const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function studio(files = []) {
    const uploads = [];
    const messages = [];
    let html = '';
    const wrapper = { html(value) { html = value; return this; }, find() { return { on() {} }; } };
    const frappe = {
        pages: { 'email-campaign-studio': {} },
        ui: { FileUploader: class { constructor(options) { uploads.push(options); } } },
        utils: { escape_html: text => String(text) },
        msgprint: message => messages.push(message),
    };
    const context = { frappe, __: (text, args) => args ? text.replace(/\{(\d)\}/g, (_, i) => args[i]) : text };
    const filename = path.join(__dirname, '../finbyzreach/finbyzreach/page/email_campaign_studio/email_campaign_studio.js');
    vm.runInNewContext(fs.readFileSync(filename, 'utf8') + '\nglobalThis.Studio = EmailCampaignStudio;', context);
    const instance = Object.create(context.Studio.prototype);
    instance.attachments = files;
    instance.contentForm = { get_field: () => ({ $wrapper: wrapper }) };
    return { instance, uploads, messages, html: () => html };
}

test('the attachment list shows names, size used out of 12 MB and a remove button', () => {
    const { instance, html } = studio([{ name: 'F1', file_name: 'price list.pdf', file_size: 2 * 1048576 }]);
    instance.renderAttachments();
    assert.match(html(), /price list\.pdf/);
    assert.match(html(), /2\.0 MB of 12 MB used/);
    assert.match(html(), /data-remove-attachment/);
});

test('a file that pushes the total over 12 MB is refused with a message', () => {
    const { instance, uploads, messages } = studio([{ name: 'F1', file_name: 'a.pdf', file_size: 10 * 1048576 }]);
    instance.addAttachment();
    uploads[0].on_success({ name: 'F2', file_name: 'b.pdf', file_size: 3 * 1048576 });
    assert.equal(instance.attachments.length, 1);
    assert.match(messages[0], /limit is 12 MB/);
    uploads[0].on_success({ name: 'F3', file_name: 'c.pdf', file_size: 1048576 });
    assert.deepEqual(Array.from(instance.attachments, file => file.name), ['F1', 'F3']);
});

test('a frozen campaign shows its attachments without add or remove buttons', () => {
    const { instance, html } = studio([{ name: 'F1', file_name: 'a.pdf', file_size: 1024 }]);
    instance.campaignEditable = false;
    instance.renderAttachments();
    assert.doesNotMatch(html(), /data-add-attachment|data-remove-attachment/);
});
