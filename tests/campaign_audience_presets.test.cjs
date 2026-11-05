const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function workspace(audience) {
    const labels = new Map();
    const frappe = {
        pages: { 'email-campaign-studio': {} },
        ui: { FilterGroup: class { constructor(options) { Object.assign(this, options); } } },
        model: { with_doctype: (_doctype, done) => done() },
    };
    const context = { frappe, __: text => text };
    const filename = path.join(__dirname, '../finbyzreach/finbyzreach/page/email_campaign_studio/email_campaign_studio.js');
    vm.runInNewContext(fs.readFileSync(filename, 'utf8') + '\nglobalThis.Studio = EmailCampaignStudio;', context);
    const studio = Object.create(context.Studio.prototype);
    studio.audienceForm = { get_value: field => field === 'audience_doctype' ? audience : 'Customer' };
    studio.$root = { find: selector => ({
        text(value) { labels.set(selector, value); return this; },
        toggle() { return this; }, removeClass() { return this; }, addClass() { return this; },
    }) };
    studio.filterGroups = [];
    studio.clearSelectedSegment = () => {};
    studio.handleAudienceRuleChange = () => {};
    studio.applyIncludeFilterGroups = groups => { studio.applied = JSON.parse(JSON.stringify(groups)); return Promise.resolve(); };
    return { studio, labels };
}

test('Contact presets use only actual Contact fields and never Lead disabled', async () => {
    const { studio, labels } = workspace('Contact');
    studio.syncAudienceControls();
    assert.equal(labels.get("[data-audience-preset='active-email'] span:last-child"), 'Contacts with email (not opted out)');
    assert.equal(labels.get("[data-audience-preset='all-email'] span:last-child"), 'All contacts with email');
    const metadata = JSON.parse(fs.readFileSync(path.join(__dirname, '../../frappe/frappe/contacts/doctype/contact/contact.json'), 'utf8'));
    const fields = new Set(metadata.fields.map(field => field.fieldname));
    await studio.applyAudiencePreset('active-email');
    assert.deepEqual(studio.applied, [[['Contact', 'unsubscribed', '=', 0], ['Contact', 'email_id', 'is', 'set']]]);
    assert.ok(studio.applied.flat().every(([doctype, field]) => doctype === 'Contact' && fields.has(field)));
    await studio.applyAudiencePreset('all-email');
    assert.deepEqual(studio.applied, [[['Contact', 'email_id', 'is', 'set']]]);
    await studio.applyAudiencePreset('clear');
    assert.deepEqual(studio.applied, []);
    assert.equal(studio.presetFilters, null);
});

for (const audience of ['Lead', 'Customer']) {
    test(`${audience} active preset retains its audience fields`, async () => {
        const { studio } = workspace(audience);
        await studio.applyAudiencePreset('active-email');
        assert.ok(studio.applied.flat().every(([doctype]) => doctype === audience));
        assert.deepEqual(studio.applied[0][0], [audience, 'disabled', '=', 0]);
    });
}

test('switching to Contact clears previous rules and creates native Contact filter controls', async () => {
    const { studio } = workspace('Contact');
    studio.presetFilters = [[['Lead', 'disabled', '=', 0]]];
    studio.contentForm = { set_value: () => Promise.resolve() };
    studio.applyExcludeFilterGroups = groups => { studio.excluded = groups; return Promise.resolve(); };
    studio.queuePreview = () => {};
    await studio.changeAudienceType();
    assert.equal(studio.presetFilters, null);
    assert.deepEqual(studio.applied, []);
    assert.equal(studio.excluded.length, 0);
    assert.equal(studio.makeEmbeddedFilterGroup({}, () => {}).doctype, 'Contact');
});
